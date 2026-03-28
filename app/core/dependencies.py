from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.repositories.action_repository import ActionRepository
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.db.session import SessionLocal
from app.services.anomaly_detector import AnomalyDetector
from app.services.collector import CloudMetricCollector
from app.services.inference_queue import InferenceQueueService
from app.services.orchestrator import MetricOrchestrator
from app.services.shap_explainer import ShapExplainer


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_resource_repository(db: Session = Depends(get_db)) -> ResourceRepository:
    return ResourceRepository(db)


def get_metric_repository(db: Session = Depends(get_db)) -> MetricRepository:
    return MetricRepository(db)


def get_cost_repository(db: Session = Depends(get_db)) -> CostRecordRepository:
    return CostRecordRepository(db)


def get_anomaly_repository(db: Session = Depends(get_db)) -> AnomalyRepository:
    return AnomalyRepository(db)


def get_action_repository(db: Session = Depends(get_db)) -> ActionRepository:
    return ActionRepository(db)


def get_cloud_metric_collector() -> CloudMetricCollector:
    return CloudMetricCollector()


def get_inference_queue_service() -> InferenceQueueService:
    return InferenceQueueService()


def get_anomaly_detector(
    metric_repository: MetricRepository = Depends(get_metric_repository),
    cost_repository: CostRecordRepository = Depends(get_cost_repository),
) -> AnomalyDetector:
    return AnomalyDetector(
        metric_repository=metric_repository,
        cost_repository=cost_repository,
        shap_explainer=ShapExplainer(),
    )


def get_metric_orchestrator(
    db: Session = Depends(get_db),
    metric_repository: MetricRepository = Depends(get_metric_repository),
    resource_repository: ResourceRepository = Depends(get_resource_repository),
    cost_repository: CostRecordRepository = Depends(get_cost_repository),
    anomaly_repository: AnomalyRepository = Depends(get_anomaly_repository),
    action_repository: ActionRepository = Depends(get_action_repository),
    collector: CloudMetricCollector = Depends(get_cloud_metric_collector),
    anomaly_detector: AnomalyDetector = Depends(get_anomaly_detector),
    inference_queue: InferenceQueueService = Depends(get_inference_queue_service),
) -> MetricOrchestrator:
    return MetricOrchestrator(
        transaction_session=db,
        metric_repository=metric_repository,
        resource_repository=resource_repository,
        cost_repository=cost_repository,
        anomaly_repository=anomaly_repository,
        action_repository=action_repository,
        collector=collector,
        anomaly_detector=anomaly_detector,
        inference_queue=inference_queue,
    )
