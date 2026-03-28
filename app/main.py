from __future__ import annotations

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logger import logger, setup_logging
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.repositories.action_repository import ActionRepository
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.db.session import SessionLocal, engine
from app.models import actions, anomalies, cost, metrics, resource  # noqa: F401
from app.services.anomaly_detector import AnomalyDetector
from app.services.collector import CloudMetricCollector
from app.services.inference_queue import initialize_inference_scheduler, shutdown_inference_scheduler, InferenceQueueService
from app.services.orchestrator import MetricOrchestrator
from app.services.shap_explainer import ShapExplainer

settings = get_settings()
setup_logging()

scheduler = BackgroundScheduler(timezone="UTC")


def run_collection_cycle() -> None:
    db = SessionLocal()
    try:
        collector = CloudMetricCollector()
        orchestrator = MetricOrchestrator(
            transaction_session=db,
            metric_repository=MetricRepository(db),
            resource_repository=ResourceRepository(db),
            cost_repository=CostRecordRepository(db),
            anomaly_repository=AnomalyRepository(db),
            action_repository=ActionRepository(db),
            collector=collector,
            anomaly_detector=AnomalyDetector(
                metric_repository=MetricRepository(db),
                cost_repository=CostRecordRepository(db),
                shap_explainer=ShapExplainer(),
            ),
            inference_queue=InferenceQueueService(),
        )
        if settings.cloud_collector_mode.lower() == "aws":
            summary = orchestrator.sync_aws()
            logger.info("AWS collection cycle completed: %s", summary.model_dump())
        else:
            resources = ResourceRepository(db).list_all()
            for resource_item in resources:
                metric = collector.generate_metric(resource_item)
                orchestrator.ingest_metric(metric, async_inference=True)
            logger.info("Simulation cycle completed for %s resources", len(resources))
    except Exception as exc:  # pragma: no cover - operational guardrail
        db.rollback()
        logger.exception("Collection cycle failed: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    bootstrap_database(engine)
    initialize_inference_scheduler()
    if settings.scheduler_enabled and not scheduler.running:
        scheduler.add_job(
            run_collection_cycle,
            trigger="interval",
            seconds=settings.scheduler_interval_seconds,
            id="metric-collector",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Background scheduler started")
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
    shutdown_inference_scheduler()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin) for origin in settings.cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
