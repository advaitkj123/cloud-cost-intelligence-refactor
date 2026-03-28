from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_metric_orchestrator, get_metric_repository
from app.db.repositories.metric_repository import MetricRepository
from app.schemas.metrics import MetricCreate, MetricIngestResponse, MetricRead
from app.services.orchestrator import MetricOrchestrator

router = APIRouter()


@router.post("/metrics", response_model=MetricIngestResponse)
def ingest_metric(
    payload: MetricCreate,
    orchestrator: MetricOrchestrator = Depends(get_metric_orchestrator),
) -> MetricIngestResponse:
    try:
        return orchestrator.ingest_metric(payload, async_inference=True)
    except ValueError as exc:
        orchestrator.db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/metrics", response_model=list[MetricRead])
def list_metrics(
    resource_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    repository: MetricRepository = Depends(get_metric_repository),
) -> list[MetricRead]:
    return repository.list(limit=limit, resource_id=resource_id)
