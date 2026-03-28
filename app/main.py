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
from app.db.session import SessionLocal, engine
from app.models import actions, anomalies, cost, features, metrics, resource  # noqa: F401
from app.services.anomaly_training import get_training_service
from app.services.inference_queue import initialize_inference_scheduler, shutdown_inference_scheduler
from app.services.pipeline_orchestrator import run_unified_pipeline

settings = get_settings()
setup_logging()

scheduler = BackgroundScheduler(timezone="UTC")


def run_unified_pipeline_cycle() -> None:
    """Single scheduled run: ingestion → cost → features → ML → XAI → sim → decision → safety → execution → health."""
    db = SessionLocal()
    try:
        summary = run_unified_pipeline(db)
        logger.info(
            "Unified pipeline finished: duration=%ss actioned=%s errors=%s health=%s",
            summary.get("duration_seconds"),
            summary.get("resources_actioned"),
            len(summary.get("errors", [])),
            summary.get("steps", {}).get("system_health", {}).get("status"),
        )
    except Exception as exc:  # pragma: no cover - operational guardrail
        db.rollback()
        logger.exception("Unified pipeline cycle failed: %s", exc)
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
        unified_interval = max(settings.unified_pipeline_interval_seconds, 60)
        scheduler.add_job(
            run_unified_pipeline_cycle,
            trigger="interval",
            seconds=unified_interval,
            id="unified-pipeline",
            replace_existing=True,
        )
        logger.info("Unified pipeline job added to scheduler (interval: %ds)", unified_interval)

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
