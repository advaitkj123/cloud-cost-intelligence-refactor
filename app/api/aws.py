from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.resources import build_resource_response
from app.core.dependencies import (
    get_cost_repository,
    get_metric_orchestrator,
    get_metric_repository,
    get_resource_repository,
)
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.schemas.aws import AWSMetricRead, AWSSyncResponse
from app.schemas.resource import ResourceWithLatest
from app.services.orchestrator import MetricOrchestrator

router = APIRouter()


@router.get("/aws/resources", response_model=list[ResourceWithLatest])
def list_aws_resources(
    resource_repo: ResourceRepository = Depends(get_resource_repository),
    metric_repo: MetricRepository = Depends(get_metric_repository),
    cost_repo: CostRecordRepository = Depends(get_cost_repository),
) -> list[ResourceWithLatest]:
    response: list[ResourceWithLatest] = []
    for resource in resource_repo.list_by_provider("aws"):
        latest_metric = metric_repo.latest_for_resource(resource.id)
        latest_cost = cost_repo.latest_for_resource(resource.id)
        response.append(build_resource_response(resource, latest_metric, latest_cost))
    return response


@router.get("/aws/metrics", response_model=list[AWSMetricRead])
def list_aws_metrics(
    resource_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    metric_repo: MetricRepository = Depends(get_metric_repository),
    resource_repo: ResourceRepository = Depends(get_resource_repository),
) -> list[AWSMetricRead]:
    resources = {resource.id: resource for resource in resource_repo.list_by_provider("aws")}
    metrics = metric_repo.list_for_provider("aws", limit=limit, resource_id=resource_id)
    return [
        AWSMetricRead(
            resource_id=metric.resource_id,
            instance_id=resources.get(metric.resource_id).external_id if resources.get(metric.resource_id) else None,
            instance_type=resources.get(metric.resource_id).instance_type if resources.get(metric.resource_id) else None,
            timestamp=metric.timestamp,
            cpu_usage=metric.cpu_usage,
            network_in=metric.network_in,
            network_out=metric.network_out,
        )
        for metric in metrics
    ]


@router.post("/aws/sync", response_model=AWSSyncResponse)
def sync_aws(orchestrator: MetricOrchestrator = Depends(get_metric_orchestrator)) -> AWSSyncResponse:
    try:
        return orchestrator.sync_aws()
    except (NoCredentialsError, ClientError, BotoCoreError) as exc:
        orchestrator.db.rollback()
        raise HTTPException(status_code=503, detail=f"AWS sync failed: {exc}") from exc
    except Exception as exc:
        orchestrator.db.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected AWS sync failure: {exc}") from exc
