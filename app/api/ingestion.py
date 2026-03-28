"""API endpoints for ingestion management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_ingestion_service
from app.services.ingestion_service import IngestionService

router = APIRouter()


@router.post("/ingestion/trigger")
def trigger_ingestion(
    regions: list[str] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger a cloud metric ingestion cycle.

    Args:
        regions: List of AWS regions to collect from (default: us-east-1)

    Returns:
        Results dictionary with metrics collected, resources updated, and errors
    """
    if regions is None:
        regions = ["us-east-1"]

    ingestion_service = IngestionService(db)
    results = ingestion_service.run_ingestion_cycle(regions)
    return results


@router.post("/ingestion/trigger/{region}")
def trigger_regional_ingestion(
    region: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger ingestion for a specific region.

    Args:
        region: AWS region to collect from

    Returns:
        Results dictionary with metrics collected, resources updated, and errors
    """
    ingestion_service = IngestionService(db)
    results = ingestion_service.ingest_region(region)
    return results


@router.get("/ingestion/status")
def get_ingestion_status() -> dict[str, Any]:
    """Get the status of the ingestion system.

    Returns:
        Status information including scheduler state
    """
    return {
        "status": "operational",
        "version": "1.0.0",
        "supported_collectors": [
            "ec2",
            "cloudwatch",
            "s3",
            "lambda",
        ],
        "message": "Ingestion system is operational",
    }
