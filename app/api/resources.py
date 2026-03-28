import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.models.resource import Resource
from app.schemas.resource import ResourceWithLatest

router = APIRouter()


def build_resource_response(resource: Resource, latest_metric, latest_cost) -> ResourceWithLatest:
    return ResourceWithLatest(
        id=resource.id,
        name=resource.name,
        type=resource.type,
        region=resource.region,
        status=resource.status,
        provider=resource.provider,
        external_id=resource.external_id,
        instance_type=resource.instance_type,
        cloud_state=resource.cloud_state or resource.status.value,
        tags=json.loads(resource.tags_json or "{}"),
        created_at=resource.created_at,
        latest_cost=latest_cost.estimated_cost if latest_cost else None,
        cost_per_hour=latest_cost.cost_per_hour if latest_cost else None,
        latest_cpu=latest_metric.cpu_usage if latest_metric else None,
        latest_memory=latest_metric.memory_usage if latest_metric else None,
        latest_requests=latest_metric.requests if latest_metric else None,
        latest_network_in=latest_metric.network_in if latest_metric else None,
        latest_network_out=latest_metric.network_out if latest_metric else None,
    )


@router.get("/resources", response_model=list[ResourceWithLatest])
def list_resources(db: Session = Depends(get_db)) -> list[ResourceWithLatest]:
    resource_repo = ResourceRepository(db)
    metric_repo = MetricRepository(db)
    cost_repo = CostRecordRepository(db)

    response: list[ResourceWithLatest] = []
    for resource in resource_repo.list_all():
        latest_metric = metric_repo.latest_for_resource(resource.id)
        latest_cost = cost_repo.latest_for_resource(resource.id)
        response.append(build_resource_response(resource, latest_metric, latest_cost))
    return response
