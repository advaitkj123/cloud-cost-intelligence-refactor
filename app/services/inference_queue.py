from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.core.logger import logger
from app.db.repositories.action_repository import ActionRepository
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.db.session import SessionLocal
from app.models.anomalies import Anomaly
from app.services.anomaly_detector import AnomalyDetector
from app.services.decision_engine import DecisionEngine
from app.services.optimizer import Optimizer
from app.services.shap_explainer import ShapExplainer
from app.system_health.monitor import automation_may_run, record_inference_duration

settings = get_settings()
_inference_scheduler = BackgroundScheduler(timezone="UTC")


class InferenceQueueService:
    """Queue one-off inference jobs so API writes stay responsive."""

    def enqueue(self, *, resource_id: int, metric_id: int, cost_record_id: int) -> str:
        job_id = f"ml-inference-{metric_id}-{uuid4().hex[:8]}"
        if not settings.inference_scheduler_enabled:
            logger.info("Inference scheduler disabled, executing job %s inline", job_id)
            _process_inference_job(resource_id=resource_id, metric_id=metric_id, cost_record_id=cost_record_id)
            return job_id

        if not _inference_scheduler.running:
            _inference_scheduler.start()
        _inference_scheduler.add_job(
            _process_inference_job,
            trigger="date",
            run_date=datetime.now(UTC),
            id=job_id,
            misfire_grace_time=settings.inference_job_misfire_grace_seconds,
            replace_existing=False,
            kwargs={
                "resource_id": resource_id,
                "metric_id": metric_id,
                "cost_record_id": cost_record_id,
            },
        )
        logger.info("Queued anomaly inference job %s for metric %s", job_id, metric_id)
        return job_id


def initialize_inference_scheduler() -> None:
    if settings.inference_scheduler_enabled and not _inference_scheduler.running:
        _inference_scheduler.start()
        logger.info("Inference scheduler started")


def shutdown_inference_scheduler() -> None:
    if _inference_scheduler.running:
        _inference_scheduler.shutdown(wait=False)
        logger.info("Inference scheduler stopped")


def _process_inference_job(*, resource_id: int, metric_id: int, cost_record_id: int) -> None:
    db = SessionLocal()
    t0 = perf_counter()
    try:
        resource_repo = ResourceRepository(db)
        metric_repo = MetricRepository(db)
        cost_repo = CostRecordRepository(db)
        anomaly_repo = AnomalyRepository(db)
        action_repo = ActionRepository(db)

        resource = resource_repo.get(resource_id)
        metric_record = metric_repo.get(metric_id)
        cost_record = cost_repo.get(cost_record_id)
        if resource is None or metric_record is None or cost_record is None:
            logger.warning(
                "Skipping inference job for resource=%s metric=%s cost_record=%s due to missing data",
                resource_id,
                metric_id,
                cost_record_id,
            )
            return

        detector = AnomalyDetector(metric_repository=metric_repo, cost_repository=cost_repo, shap_explainer=ShapExplainer())
        result = detector.detect(resource=resource, metric=metric_record, estimated_cost=cost_record.estimated_cost)
        if result.is_anomaly:
            anomaly_repo.create(
                Anomaly(
                    resource_id=resource.id,
                    timestamp=metric_record.timestamp,
                    anomaly_score=result.score,
                    reason=result.reason,
                    detection_source=result.detection_source,
                    expected_cost=result.expected_cost,
                    actual_cost=result.actual_cost,
                    shap_contributions=result.shap_contributions,
                )
            )

        decision = DecisionEngine().evaluate(resource, metric_record, cost_record.estimated_cost, result)
        if decision.should_act and decision.action_type and automation_may_run(db):
            Optimizer(action_repo).execute(
                resource=resource,
                action_type=decision.action_type,
                estimated_savings=decision.estimated_savings,
                dry_run=settings.dry_run_optimizations,
            )
        db.commit()
    except Exception as exc:  # pragma: no cover - operational async safeguard
        db.rollback()
        logger.exception("Async inference job failed for metric %s: %s", metric_id, exc)
    finally:
        record_inference_duration(perf_counter() - t0)
        db.close()
