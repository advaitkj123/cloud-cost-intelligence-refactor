"""End-to-end backend pipeline: ingestion → execution → system health.

Chains all layers in order with structured logging at each step.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.cloud.aws.client import AWSClientFactory
from app.core.config import get_settings
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.feature_repository import FeatureRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.decision_engine.engine import DecisionEngine as SimulationDecisionEngine
from app.decision_engine.engine import ExecutionPolicy
from app.decision_engine.simulator import SimulationEngine
from app.execution.aws_executor import AWSExecutor, ExecutionStatus
from app.models.anomalies import Anomaly
from app.models.metrics import Metric
from app.models.resource import Resource, ResourceType
from app.schemas.metrics import MetricCreate
from app.services.anomaly_detector import AnomalyDetector
from app.services.collector import CloudMetricCollector
from app.services.data_pipeline import DataPipeline
from app.services.ingestion_service import IngestionService
from app.services.shap_explainer import ShapExplainer
from app.system_health.monitor import automation_may_run, evaluate_system_health, record_pipeline_run
from app.xai.explainer import XAIExplainer

logger = logging.getLogger(__name__)

LOG_PREFIX = "[unified-pipeline]"


class UnifiedPipelineOrchestrator:
    """Runs ingestion, cost/features, ML+XAI, simulation, decision, safety, execution, health."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.resource_repo = ResourceRepository(db)
        self.metric_repo = MetricRepository(db)
        self.cost_repo = CostRecordRepository(db)
        self.feature_repo = FeatureRepository(db)
        self.detector = AnomalyDetector(
            metric_repository=self.metric_repo,
            cost_repository=self.cost_repo,
            shap_explainer=ShapExplainer(),
        )
        self.simulation_engine = SimulationEngine()
        self.simulation_decision = SimulationDecisionEngine()
        self.xai_explainer = XAIExplainer()

    def _log(self, step: str, message: str, **extra: Any) -> None:
        if extra:
            logger.info("%s %s: %s | %s", LOG_PREFIX, step, message, extra)
        else:
            logger.info("%s %s: %s", LOG_PREFIX, step, message)

    def _step_ingestion(self) -> dict[str, Any]:
        """Collect cloud metrics into DB (simulated or AWS)."""
        self._log("1_ingestion", "starting metric collection")
        out: dict[str, Any] = {"mode": self.settings.cloud_collector_mode, "metrics_stored": 0}

        if self.settings.cloud_collector_mode.lower() == "aws":
            ingestion = IngestionService(self.db, client_factory=AWSClientFactory())
            res = ingestion.run_ingestion_cycle(regions=[self.settings.aws_region])
            out.update(res)
            self._log("1_ingestion", "AWS ingestion complete", metrics_stored=res.get("metrics_stored"))
            return out

        collector = CloudMetricCollector()
        for resource in self.resource_repo.list_all():
            payload = collector.generate_metric(resource)
            self.metric_repo.create(
                Metric(
                    resource_id=payload.resource_id,
                    timestamp=payload.timestamp,
                    cpu_usage=payload.cpu_usage,
                    memory_usage=payload.memory_usage,
                    requests=payload.requests,
                    storage_used=payload.storage_used,
                    network_in=payload.network_in,
                    network_out=payload.network_out,
                )
            )
            out["metrics_stored"] += 1
        self.db.commit()
        self._log("1_ingestion", "simulated metrics stored", count=out["metrics_stored"])
        return out

    def _step_cost_and_features(self) -> dict[str, Any]:
        """Cost engine + feature engineering via DataPipeline."""
        self._log("2_cost_engine", "running cost estimation (DataPipeline)")
        self._log("3_feature_engineering", "engineering features (FeatureEngineer / CostCalculator)")
        pipeline = DataPipeline(self.db)
        results = pipeline.process_all_resources()
        self._log(
            "2_3_data_pipeline",
            "cost + features complete",
            resources=results.get("resources_processed"),
            costs=results.get("costs_calculated"),
            features=results.get("features_engineered"),
        )
        return results

    @staticmethod
    def _metric_to_create(metric: Metric) -> MetricCreate:
        return MetricCreate(
            resource_id=metric.resource_id,
            timestamp=metric.timestamp,
            cpu_usage=metric.cpu_usage,
            memory_usage=metric.memory_usage,
            requests=metric.requests,
            storage_used=metric.storage_used,
            network_in=metric.network_in,
            network_out=metric.network_out,
        )

    def _build_anomaly_row(
        self,
        resource: Resource,
        metric: Metric,
        ad_result: Any,
    ) -> Anomaly:
        conf = min(100.0, max(0.0, float(ad_result.score) * 100.0))
        reason = (ad_result.reason or "")[:500]
        return Anomaly(
            resource_id=resource.id,
            timestamp=metric.timestamp,
            is_anomaly=bool(ad_result.is_anomaly),
            confidence=conf,
            anomaly_type="cost_regression",
            anomaly_score=float(ad_result.score),
            reason=reason,
            detection_source=str(ad_result.detection_source),
            expected_cost=ad_result.expected_cost,
            actual_cost=ad_result.actual_cost,
            shap_contributions=list(ad_result.shap_contributions or []),
            details={"pipeline": "unified", "source": "AnomalyDetector"},
            recommendations=[],
        )

    def _step_ml_xai_sim_decide(
        self,
        resource: Resource,
        feature: Any,
        metric: Metric,
        estimated_cost: float,
    ) -> dict[str, Any]:
        """ML detection, XAI narrative, simulation, decision."""
        payload = self._metric_to_create(metric)
        self._log("4_ml_detection", f"resource_id={resource.id}", detector="AnomalyDetector")
        ad_result = self.detector.detect(resource, payload, estimated_cost)

        if not ad_result.is_anomaly:
            self._log("4_ml_detection", f"resource_id={resource.id} — no anomaly, skipping downstream")
            return {"skipped": True, "reason": "no_anomaly"}

        anomaly_row = self._build_anomaly_row(resource, metric, ad_result)
        self.db.add(anomaly_row)
        self.db.flush()
        self.db.refresh(anomaly_row)

        top_shap = (ad_result.shap_contributions or [])[:3]
        self._log(
            "5_xai",
            f"resource_id={resource.id}",
            shap_top_features=[x.get("feature") for x in top_shap],
            contributions_preview=top_shap,
        )
        try:
            xai_payload = self.xai_explainer.explain_anomaly(anomaly_row, self.db)
            self._log("5_xai", f"resource_id={resource.id} narrative keys", keys=list(xai_payload.keys())[:8])
        except Exception as exc:  # pragma: no cover
            logger.warning("%s 5_xai: explainer fallback: %s", LOG_PREFIX, exc)

        self._log("6_simulation", f"resource_id={resource.id}", engine="SimulationEngine")
        sim_results = self.simulation_engine.simulate_actions(
            self.db, resource, anomaly_row, feature
        )

        self._log("7_decision", f"resource_id={resource.id}", engine="decision_engine.DecisionEngine")
        decision = self.simulation_decision.decide(
            resource,
            anomaly_row,
            sim_results,
            confidence=anomaly_row.confidence,
        )
        self._log(
            "7_decision",
            f"resource_id={resource.id}",
            final_action=decision.final_action,
            policy=str(decision.decision),
        )
        return {
            "skipped": False,
            "anomaly_id": anomaly_row.id,
            "decision": decision,
            "simulation_count": len(sim_results),
        }

    def _map_executor_action(self, resource: Resource, final_action: str) -> str | None:
        if final_action == "do_nothing":
            return None
        if final_action == "stop_instance":
            return "stop_instance" if resource.type == ResourceType.ec2 else None
        if final_action == "scale_down":
            if resource.type == ResourceType.ec2:
                return "stop_instance"
            if resource.type == ResourceType.lambda_fn:
                return "limit_lambda"
            return None
        if final_action == "delete_resource":
            return "delete_volume"
        return None

    def _step_safety_execution(
        self,
        resource: Resource,
        decision_result: Any,
    ) -> dict[str, Any]:
        """Safety (inside AWSExecutor) + execution."""
        fa = decision_result.final_action
        exec_action = self._map_executor_action(resource, fa)

        if decision_result.decision != ExecutionPolicy.AUTO_EXECUTE or exec_action is None:
            self._log(
                "8_safety",
                f"resource_id={resource.id} — skip execution",
                policy=str(decision_result.decision),
                final_action=fa,
            )
            self._log("9_execution", f"resource_id={resource.id} — not auto-executed")
            return {"executed": False, "reason": "policy_or_unmapped_action"}

        self._log("8_safety", f"resource_id={resource.id}", note="guardrails validated inside AWSExecutor")

        if not automation_may_run(self.db):
            self._log("9_execution", f"resource_id={resource.id} — blocked by system health / settings")
            return {"executed": False, "reason": "automation_paused"}

        executor = AWSExecutor(dry_run=self.settings.dry_run_optimizations)
        self._log("9_execution", f"resource_id={resource.id}", action=exec_action)
        result = executor.execute_action(self.db, resource, exec_action, decision_id=None)
        ok = result.status in (ExecutionStatus.SUCCESS, ExecutionStatus.DRY_RUN)
        self._log(
            "9_execution",
            f"resource_id={resource.id} done",
            status=str(result.status),
            message=result.message[:200] if result.message else "",
        )
        return {"executed": ok, "status": str(result.status), "error": result.error}

    def run(self) -> dict[str, Any]:
        """Execute steps 1–10 and return aggregated results."""
        t0 = perf_counter()
        summary: dict[str, Any] = {
            "steps": {},
            "resources_actioned": 0,
            "errors": [],
        }
        try:
            summary["steps"]["ingestion"] = self._step_ingestion()

            summary["steps"]["cost_and_features"] = self._step_cost_and_features()

            processed = 0
            for resource in self.resource_repo.list_all():
                try:
                    latest_m = self.metric_repo.latest_for_resource(resource.id)
                    if latest_m is None:
                        continue
                    latest_cost = self.cost_repo.latest_for_resource(resource.id)
                    if latest_cost is None:
                        continue
                    feature = self.feature_repo.latest_for_resource(resource.id)
                    if feature is None:
                        continue

                    branch = self._step_ml_xai_sim_decide(
                        resource,
                        feature,
                        latest_m,
                        float(latest_cost.estimated_cost),
                    )
                    if branch.get("skipped"):
                        processed += 1
                        continue

                    ex = self._step_safety_execution(resource, branch["decision"])
                    if ex.get("executed"):
                        summary["resources_actioned"] += 1
                    processed += 1
                    self.db.commit()
                except Exception as exc:
                    err = f"resource {resource.id}: {exc}"
                    logger.exception("%s resource loop: %s", LOG_PREFIX, err)
                    summary["errors"].append(err)
                    self.db.rollback()

            summary["steps"]["resources_evaluated"] = processed
            self._log("pipeline", "resource loop complete", evaluated=processed)

        except Exception as exc:
            logger.exception("%s fatal: %s", LOG_PREFIX, exc)
            summary["errors"].append(str(exc))
            self.db.rollback()
        finally:
            duration = perf_counter() - t0
            record_pipeline_run(duration)
            self._log("10_system_health", "evaluating system health")
            summary["steps"]["system_health"] = evaluate_system_health(self.db)
            summary["duration_seconds"] = round(duration, 3)

        return summary


def run_unified_pipeline(db: Session) -> dict[str, Any]:
    """Convenience entrypoint for scheduler and API."""
    return UnifiedPipelineOrchestrator(db).run()
