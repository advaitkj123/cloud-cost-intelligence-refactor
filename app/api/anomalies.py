from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_anomaly_repository
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.schemas.anomalies import AnomalyRead

router = APIRouter()


@router.get("/anomalies", response_model=list[AnomalyRead])
def list_anomalies(
    limit: int = Query(default=100, ge=1, le=500),
    repository: AnomalyRepository = Depends(get_anomaly_repository),
) -> list[AnomalyRead]:
    return repository.list(limit=limit)
