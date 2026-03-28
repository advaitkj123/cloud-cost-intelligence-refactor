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
from app.models import actions, anomalies, cost, features, metrics, resource  # noqa: F401
from app.services.anomaly_detector import AnomalyDetector
from app.services.collector import CloudMetricCollector
from app.services.data_pipeline import DataPipeline
from app.services.inference_queue import initialize_inference_scheduler, shutdown_inference_scheduler, InferenceQueueService
from app.services.ingestion_service import IngestionService
from app.services.orchestrator import MetricOrchestrator
from app.services.shap_explainer import ShapExplainer
from app.services.anomaly_training import get_training_service
from app.services.anomaly_service import AnomalyService
from app.db.repositories.feature_repository import FeatureRepository

settings = get_settings()
setup_logging()

scheduler = BackgroundScheduler(timezone="UTC")


def run_ingestion_cycle() -> None:
    """Run the AWS ingestion collection cycle."""
    db = SessionLocal()
    try:
        if settings.cloud_collector_mode.lower() == "aws":
            ingestion_service = IngestionService(db)
            results = ingestion_service.run_ingestion_cycle(regions=[settings.aws_region])
            logger.info(
                "AWS ingestion cycle completed: %d metrics collected, "
                "%d stored, %d errors",
                results["total_metrics_collected"],
                results["metrics_stored"],
                len(results["errors"]),
            )
            if results["errors"]:
                logger.warning("Ingestion errors: %s", results["errors"])
    except Exception as exc:  # pragma: no cover - operational guardrail
        db.rollback()
        logger.exception("Ingestion cycle failed: %s", exc)
    finally:
        db.close()


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


def run_data_pipeline_cycle() -> None:
    """Run the data pipeline: metrics → costs → features."""
    db = SessionLocal()
    try:
        pipeline = DataPipeline(db)
        results = pipeline.process_all_resources()
        logger.info(
            "Data pipeline cycle completed: %d resources processed, "
            "%d costs, %d features, %d errors",
            results["resources_processed"],
            results["costs_calculated"],
            results["features_engineered"],
            len(results["errors"]),
        )
        if results["errors"]:
            logger.warning("Pipeline errors: %s", results["errors"][:5])  # Log first 5
    except Exception as exc:  # pragma: no cover - operational guardrail
        db.rollback()
        logger.exception("Data pipeline cycle failed: %s", exc)
    finally:
        db.close()


def run_anomaly_detection_cycle() -> None:
    """Run anomaly detection on all resources."""
    db = SessionLocal()
    try:
        service = AnomalyService()
        resource_repo = ResourceRepository(db)
        feature_repo = FeatureRepository(db)
        anomaly_repo = AnomalyRepository(db)
        
        resources = resource_repo.list_all()
        detected_count = 0
        errors = []
        
        for resource in resources:
            try:
                # Get latest feature for resource
                latest_features = feature_repo.list_for_resource(resource.id, limit=1)
                if not latest_features:
                    continue
                
                feature = latest_features[0]
                result = service.detect(db, resource, feature)
                
                if result.is_anomaly:
                    detected_count += 1
                    
                    # Store anomaly in database
                    from app.models.anomalies import Anomaly
                    anomaly = Anomaly(
                        resource_id=resource.id,
                        is_anomaly=result.is_anomaly,
                        confidence=result.confidence,
                        anomaly_type=result.anomaly_type.value,
                        isolation_forest_score=result.details["isolation_forest"].get("anomaly_score"),
                        prophet_is_anomaly=result.details["prophet"].get("is_anomaly"),
                        prophet_confidence=result.details["prophet"].get("confidence"),
                        zombie_is_idle=result.details["zombie"].get("is_zombie"),
                        zombie_confidence=result.details["zombie"].get("confidence"),
                        cost_delta=feature.cost_delta,
                        cpu_avg=feature.cpu_avg,
                        efficiency_score=feature.efficiency_score,
                        details=result.details,
                        recommendations=service.get_recommendations(result, db),
                        timestamp=result.timestamp,
                    )
                    anomaly_repo.create(anomaly)
            except Exception as resource_error:
                logger.warning("Error detecting anomaly for resource %s: %s", resource.id, resource_error)
                errors.append(str(resource_error))
        
        logger.info(
            "Anomaly detection cycle completed: %d resources processed, "
            "%d anomalies detected, %d errors",
            len(resources),
            detected_count,
            len(errors),
        )
        if errors:
            logger.debug("Anomaly detection errors: %s", errors[:5])
    except Exception as exc:
        db.rollback()
        logger.exception("Anomaly detection cycle failed: %s", exc)
    finally:
        db.close()


def run_anomaly_model_training() -> None:
    """Run anomaly model training."""
    db = SessionLocal()
    try:
        training_service = get_training_service()
        results = training_service.train_all_models(db, days_back=30)
        
        logger.info(
            "Anomaly model training completed: isolation_forest=%s, prophet=%s, zombie=%s",
            results["models"].get("isolation_forest", {}).get("trained", False),
            results["models"].get("prophet", {}).get("trained", False),
            results["models"].get("zombie", {}).get("status", "unknown"),
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Anomaly model training failed: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    bootstrap_database(engine)
    initialize_inference_scheduler()
    if settings.scheduler_enabled and not scheduler.running:
        # Add ingestion job if AWS mode is enabled
        if settings.cloud_collector_mode.lower() == "aws":
            scheduler.add_job(
                run_ingestion_cycle,
                trigger="interval",
                seconds=settings.scheduler_interval_seconds,
                id="aws-ingestion",
                replace_existing=True,
            )
            logger.info("AWS ingestion job added to scheduler (interval: %ds)", settings.scheduler_interval_seconds)
        
        # Add collection cycle job
        scheduler.add_job(
            run_collection_cycle,
            trigger="interval",
            seconds=settings.scheduler_interval_seconds,
            id="metric-collector",
            replace_existing=True,
        )
        
        # Add data pipeline job (runs after collection to process metrics)
        pipeline_interval = max(settings.scheduler_interval_seconds * 2, 60)  # At least 1 minute
        scheduler.add_job(
            run_data_pipeline_cycle,
            trigger="interval",
            seconds=pipeline_interval,
            id="data-pipeline",
            replace_existing=True,
        )
        logger.info("Data pipeline job added to scheduler (interval: %ds)", pipeline_interval)
        
        # Add anomaly detection job (runs after data pipeline to detect anomalies)
        anomaly_interval = max(settings.scheduler_interval_seconds * 4, 120)  # At least 2 minutes
        scheduler.add_job(
            run_anomaly_detection_cycle,
            trigger="interval",
            seconds=anomaly_interval,
            id="anomaly-detection",
            replace_existing=True,
        )
        logger.info("Anomaly detection job added to scheduler (interval: %ds)", anomaly_interval)
        
        # Add anomaly model training job (runs daily)
        scheduler.add_job(
            run_anomaly_model_training,
            trigger="interval",
            days=settings.anomaly_training_interval_days,
            id="anomaly-training",
            replace_existing=True,
        )
        logger.info("Anomaly model training job added to scheduler (interval: %d days)", settings.anomaly_training_interval_days)
        
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
