from fastapi import APIRouter

from app.api import actions, anomalies, aws, cost, ingestion, metrics, pipeline, resources, system_health, xai_routes

api_router = APIRouter()
api_router.include_router(metrics.router, tags=["metrics"])
api_router.include_router(cost.router, tags=["cost"])
api_router.include_router(anomalies.router, tags=["anomalies"])
api_router.include_router(actions.router, tags=["actions"])
api_router.include_router(resources.router, tags=["resources"])
api_router.include_router(aws.router, tags=["aws"])
api_router.include_router(ingestion.router, tags=["ingestion"])
api_router.include_router(pipeline.router, tags=["pipeline"])
api_router.include_router(xai_routes.router, tags=["xai"])
api_router.include_router(system_health.router, prefix="/system", tags=["system"])
