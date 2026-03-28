from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logger import logger
from app.db.repositories.action_repository import ActionRepository
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.models.anomalies import Anomaly
from app.models.cost import CostRecord
from app.models.metrics import Metric
from app.models.resource import Resource, ResourceStatus, ResourceType
from app.schemas.aws import AWSSyncResponse
from app.schemas.metrics import MetricCreate, MetricIngestResponse
from app.services.anomaly_detector import AnomalyDetector
from app.services.collector import CloudMetricCollector
from app.services.cost_engine import CostEngine
from app.services.decision_engine import DecisionEngine
from app.services.inference_queue import InferenceQueueService
from app.services.optimizer import Optimizer

settings = get_settings()


class MetricOrchestrator:
    """Coordinates ingestion, pricing, anomaly detection, and optimization."""

    def __init__(
        self,
        *,
        transaction_session: Session,
        metric_repository: MetricRepository,
        resource_repository: ResourceRepository,
        cost_repository: CostRecordRepository,
        anomaly_repository: AnomalyRepository,
        action_repository: ActionRepository,
        collector: CloudMetricCollector,
        anomaly_detector: AnomalyDetector,
        inference_queue: InferenceQueueService,
    ) -> None:
        self.db = transaction_session
        self.metric_repo = metric_repository
        self.resource_repo = resource_repository
        self.cost_repo = cost_repository
        self.anomaly_repo = anomaly_repository
        self.action_repo = action_repository
        self.cost_engine = CostEngine()
        self.collector = collector
        self.anomaly_detector = anomaly_detector
        self.decision_engine = DecisionEngine()
        self.optimizer = Optimizer(self.action_repo)
        self.inference_queue = inference_queue

    def ingest_metric(
        self,
        payload: MetricCreate,
        *,
        cost_per_hour: float | None = None,
        usage_hours: float = 1.0,
        async_inference: bool = True,
    ) -> MetricIngestResponse:
        resource = self.resource_repo.get(payload.resource_id)
        if not resource:
            raise ValueError(f"Resource {payload.resource_id} not found")

        metric_record = self.metric_repo.create(
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

        effective_cost_per_hour = self.cost_engine.resolve_cost_per_hour(resource, payload, cost_per_hour=cost_per_hour)
        estimated_cost = self.cost_engine.estimate_cost(
            resource,
            payload,
            cost_per_hour=effective_cost_per_hour,
            usage_hours=usage_hours,
        )
        cost_record = self.cost_repo.create(
            CostRecord(
                resource_id=payload.resource_id,
                timestamp=payload.timestamp,
                estimated_cost=estimated_cost,
                cost_per_hour=effective_cost_per_hour,
                usage_hours=usage_hours,
            )
        )

        self.db.commit()
        self.db.refresh(metric_record)
        self.db.refresh(cost_record)

        if async_inference:
            job_id = self.inference_queue.enqueue(
                resource_id=resource.id,
                metric_id=metric_record.id,
                cost_record_id=cost_record.id,
            )
            return MetricIngestResponse(
                metric_id=metric_record.id,
                cost_record_id=cost_record.id,
                anomaly_detected=False,
                action_executed=None,
                action_status=None,
                inference_queued=True,
                inference_job_id=job_id,
            )

        anomaly_result = self.anomaly_detector.detect(resource, payload, estimated_cost)
        action_name = None
        action_status = None

        if anomaly_result.is_anomaly:
            self.anomaly_repo.create(
                Anomaly(
                    resource_id=payload.resource_id,
                    timestamp=payload.timestamp,
                    anomaly_score=anomaly_result.score,
                    reason=anomaly_result.reason,
                    detection_source=anomaly_result.detection_source,
                    expected_cost=anomaly_result.expected_cost,
                    actual_cost=anomaly_result.actual_cost,
                    shap_contributions=anomaly_result.shap_contributions,
                )
            )

        decision = self.decision_engine.evaluate(resource, payload, estimated_cost, anomaly_result)
        if decision.should_act and decision.action_type and settings.auto_apply_optimizations:
            action_log, action_status = self.optimizer.execute(
                resource=resource,
                action_type=decision.action_type,
                estimated_savings=decision.estimated_savings,
                dry_run=settings.dry_run_optimizations,
            )
            action_name = action_log.action_type.value

        self.db.commit()
        logger.info(
            "Processed metric=%s resource=%s anomaly=%s action=%s",
            metric_record.id,
            resource.id,
            anomaly_result.is_anomaly,
            action_name,
        )
        return MetricIngestResponse(
            metric_id=metric_record.id,
            cost_record_id=cost_record.id,
            anomaly_detected=anomaly_result.is_anomaly,
            action_executed=action_name,
            action_status=action_status,
            inference_queued=False,
            inference_job_id=None,
        )

    def ingest_for_resource(self, resource: Resource, payload: MetricCreate) -> MetricIngestResponse:
        payload.resource_id = resource.id
        payload.timestamp = payload.timestamp or datetime.now(UTC)
        return self.ingest_metric(payload)

    def sync_aws(self) -> AWSSyncResponse:
        resources_synced = 0
        metrics_ingested = 0
        anomalies_detected = 0
        actions_triggered = 0

        for instance in self.collector.fetch_aws_resources():
            resource = self.resource_repo.upsert_cloud_resource(
                name=instance.instance_id,
                resource_type=ResourceType.ec2,
                region=instance.region,
                status=self._map_aws_state(instance.state),
                provider="aws",
                external_id=instance.instance_id,
                instance_type=instance.instance_type,
                cloud_state=instance.state,
                tags=instance.tags,
            )
            self.db.commit()
            resources_synced += 1
            hourly_cost = self.collector.get_aws_hourly_cost(instance.instance_type, instance.region)
            metric_points = self.collector.fetch_aws_metrics(instance.instance_id, instance.region)

            for point in metric_points:
                result = self.ingest_metric(
                    MetricCreate(
                        resource_id=resource.id,
                        timestamp=point.timestamp,
                        cpu_usage=point.cpu_utilization,
                        memory_usage=0.0,
                        requests=0,
                        storage_used=0.0,
                        network_in=point.network_in,
                        network_out=point.network_out,
                    ),
                    cost_per_hour=hourly_cost,
                    usage_hours=point.period_seconds / 3600,
                    async_inference=False,
                )
                metrics_ingested += 1
                if result.anomaly_detected:
                    anomalies_detected += 1
                if result.action_executed:
                    actions_triggered += 1

        return AWSSyncResponse(
            resources_synced=resources_synced,
            metrics_ingested=metrics_ingested,
            cost_records_created=metrics_ingested,
            anomalies_detected=anomalies_detected,
            actions_triggered=actions_triggered,
        )

    @staticmethod
    def _map_aws_state(state: str) -> ResourceStatus:
        if state == "running":
            return ResourceStatus.running
        if state in {"stopped", "stopping", "shutting-down", "terminated"}:
            return ResourceStatus.stopped
        return ResourceStatus.active
