"""System health API — observability and automation state."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.system_health.monitor import evaluate_system_health

router = APIRouter()


@router.get("/health", summary="System health and observability")
def get_system_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return pipeline, ML inference, execution, and data freshness signals.

    When ``status`` is ``unhealthy``, automation (auto-apply optimizations) is paused
    until the system recovers.
    """
    # Always compute fresh metrics for the API response (also refreshes automation state).
    return evaluate_system_health(db)
