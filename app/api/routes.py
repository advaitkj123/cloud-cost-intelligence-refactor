from fastapi import APIRouter

from app.api import actions, anomalies, aws, cost, metrics, resources

api_router = APIRouter()
api_router.include_router(metrics.router, tags=["metrics"])
api_router.include_router(cost.router, tags=["cost"])
api_router.include_router(anomalies.router, tags=["anomalies"])
api_router.include_router(actions.router, tags=["actions"])
api_router.include_router(resources.router, tags=["resources"])
api_router.include_router(aws.router, tags=["aws"])
