"""API endpoints for data pipeline operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.services.data_pipeline import DataPipeline
from app.core.logger import logger

router = APIRouter()


@router.post("/pipeline/process")
def process_all_resources(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Process all resources through the complete data pipeline.

    Pipeline steps:
    1. Collect recent metrics
    2. Calculate cost estimates
    3. Engineer ML features
    4. Store results

    Returns:
        Results dictionary with processing stats
    """
    try:
        pipeline = DataPipeline(db)
        results = pipeline.process_all_resources()
        return results
    except Exception as e:
        logger.error(f"Error in data pipeline: {e}", exc_info=True)
        return {
            "error": str(e),
            "resources_processed": 0,
            "costs_calculated": 0,
            "features_engineered": 0,
        }


@router.post("/pipeline/process-resource/{resource_id}")
def process_resource(
    resource_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Process a single resource through the pipeline.

    Args:
        resource_id: ID of resource to process

    Returns:
        Results dictionary with processing stats
    """
    try:
        pipeline = DataPipeline(db)
        results = pipeline.process_metrics_for_resource(resource_id)
        return results
    except Exception as e:
        logger.error(f"Error processing resource {resource_id}: {e}", exc_info=True)
        return {
            "error": str(e),
            "resource_id": resource_id,
            "cost_calculated": False,
            "features_engineered": False,
        }


@router.post("/pipeline/process-providers")
def process_providers(
    providers: list[str] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Process resources from specific providers.

    Args:
        providers: List of provider names (e.g., ['aws', 'simulated'])

    Returns:
        Results dictionary with processing stats
    """
    if providers is None:
        providers = ["aws", "simulated"]

    try:
        pipeline = DataPipeline(db)
        results = pipeline.process_providers(providers)
        return results
    except Exception as e:
        logger.error(f"Error processing providers {providers}: {e}", exc_info=True)
        return {
            "error": str(e),
            "providers": providers,
            "resources_processed": 0,
        }


@router.get("/pipeline/stats")
def get_pipeline_stats(
    days: int = 30,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get statistics about pipeline executions.

    Args:
        days: Number of days to analyze (default: 30)

    Returns:
        Dictionary with pipeline statistics
    """
    try:
        pipeline = DataPipeline(db)
        stats = pipeline.get_pipeline_stats(days=days)
        return stats
    except Exception as e:
        logger.error(f"Error getting pipeline stats: {e}", exc_info=True)
        return {"error": str(e)}


@router.post("/pipeline/cleanup")
def cleanup_old_records(
    days: int = 90,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Clean up old feature records for maintenance.

    Args:
        days: Delete records older than this many days (default: 90)

    Returns:
        Dictionary with cleanup stats
    """
    try:
        pipeline = DataPipeline(db)
        results = pipeline.cleanup_old_records(days=days)
        logger.info(f"Cleanup completed: {results}")
        return results
    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        return {"error": str(e)}


@router.get("/pipeline/status")
def get_pipeline_status() -> dict[str, Any]:
    """Get the status of the data pipeline system.

    Returns:
        Status information
    """
    return {
        "status": "operational",
        "version": "1.0.0",
        "pipeline_stages": [
            "metrics_collection",
            "cost_estimation",
            "feature_engineering",
            "storage",
        ],
        "supported_features": [
            "cost_delta",
            "rolling_statistics",
            "time_encoding",
            "efficiency_scoring",
        ],
    }
