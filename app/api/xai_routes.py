"""XAI Routes - Explainability API Endpoints.

Provides:
- GET /xai/{resource_id} - Get explanation for latest anomaly
- GET /xai/anomaly/{anomaly_id} - Get explanation for specific anomaly
- GET /xai/resource/{resource_id}/recent - Recent explanations for resource
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.models.resource import Resource
from app.xai.explainer import XAIExplainer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/xai", tags=["xai"])
explainer = XAIExplainer()


@router.get("/{resource_id}", summary="Explain Latest Anomaly for Resource")
async def explain_resource_anomaly(
    resource_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Explain the latest anomaly detected for a resource.
    
    Returns comprehensive explanation including:
    - Summary of what happened
    - Key contributing factors
    - Output from each detection model
    - Business impact
    - Recommended actions
    
    Args:
        resource_id: ID of the resource
        db: Database session
        
    Returns:
        XAI explanation object with keys:
        - summary: Human-readable summary
        - key_factors: List of contributing factors
        - model_output: Details from each model
        - impact: Business impact
        - recommendation: Suggested actions
        
    Raises:
        404: If resource not found or no anomalies exist
    """
    logger.info(f"Getting XAI explanation for resource {resource_id}")
    
    # Verify resource exists
    resource_repo = ResourceRepository(db)
    resource = resource_repo.get_by_id(resource_id)
    if not resource:
        logger.warning(f"Resource {resource_id} not found")
        raise HTTPException(status_code=404, detail=f"Resource {resource_id} not found")
    
    # Get latest anomaly
    anomaly_repo = AnomalyRepository(db)
    anomaly = anomaly_repo.get_for_resource(resource_id, limit=1)
    
    if not anomaly:
        logger.info(f"No anomalies found for resource {resource_id}")
        return {
            "resource_id": resource_id,
            "message": "No anomalies detected for this resource",
            "summary": "Resource is operating normally with no detected anomalies",
            "key_factors": [],
            "model_output": {
                "isolation_forest": {"is_flagged": False},
                "prophet": {"is_flagged": False},
                "zombie_detector": {"is_flagged": False},
            },
            "impact": "None",
            "recommendation": {
                "urgency": "LOW",
                "actions": ["Continue monitoring"],
            }
        }
    
    # Get explanation for latest anomaly
    anomaly_record = anomaly[0] if isinstance(anomaly, list) else anomaly
    explanation = explainer.explain_anomaly(anomaly_record, db)
    
    logger.debug(f"Generated XAI explanation for resource {resource_id}, "
                f"anomaly {anomaly_record.id}: {explanation['summary']}")
    
    return explanation


@router.get("/anomaly/{anomaly_id}", summary="Explain Specific Anomaly")
async def explain_specific_anomaly(
    anomaly_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Explain a specific anomaly record.
    
    Returns comprehensive explanation for any anomaly in the system.
    
    Args:
        anomaly_id: ID of the anomaly record
        db: Database session
        
    Returns:
        XAI explanation with all details
        
    Raises:
        404: If anomaly not found
    """
    logger.info(f"Getting XAI explanation for anomaly {anomaly_id}")
    
    anomaly_repo = AnomalyRepository(db)
    anomaly = anomaly_repo.get_by_id(anomaly_id)
    
    if not anomaly:
        logger.warning(f"Anomaly {anomaly_id} not found")
        raise HTTPException(status_code=404, detail=f"Anomaly {anomaly_id} not found")
    
    explanation = explainer.explain_anomaly(anomaly, db)
    
    logger.debug(f"Generated XAI explanation for anomaly {anomaly_id}")
    return explanation


@router.get("/resource/{resource_id}/recent", summary="Recent Explanations for Resource")
async def explain_recent_anomalies(
    resource_id: int,
    hours: int = Query(24, ge=1, le=720, description="Hours of history"),
    limit: int = Query(10, ge=1, le=100, description="Max results"),
    db: Session = Depends(get_db),
) -> dict:
    """Get explanations for recent anomalies on a resource.
    
    Args:
        resource_id: ID of the resource
        hours: How far back to look (default 24)
        limit: Maximum number of results (default 10)
        db: Database session
        
    Returns:
        Dict with:
        - resource_id
        - time_range: Hours of history
        - found: Number of anomalies
        - explanations: List of XAI results
        
    Raises:
        404: If resource not found
    """
    logger.info(f"Getting recent XAI explanations for resource {resource_id}")
    
    # Verify resource exists
    resource_repo = ResourceRepository(db)
    resource = resource_repo.get_by_id(resource_id)
    if not resource:
        logger.warning(f"Resource {resource_id} not found")
        raise HTTPException(status_code=404, detail=f"Resource {resource_id} not found")
    
    # Get recent anomalies
    anomaly_repo = AnomalyRepository(db)
    anomalies = anomaly_repo.get_for_resource(resource_id, limit=limit)
    
    if not anomalies:
        logger.info(f"No recent anomalies for resource {resource_id}")
        return {
            "resource_id": resource_id,
            "time_range_hours": hours,
            "found": 0,
            "explanations": [],
        }
    
    # Generate explanations for each anomaly
    explanations = []
    for anomaly in anomalies:
        try:
            explanation = explainer.explain_anomaly(anomaly, db)
            explanations.append(explanation)
        except Exception as e:
            logger.error(f"Error explaining anomaly {anomaly.id}: {e}")
            explanations.append({
                "anomaly_id": anomaly.id,
                "error": str(e),
            })
    
    logger.debug(f"Generated {len(explanations)} XAI explanations for resource {resource_id}")
    
    return {
        "resource_id": resource_id,
        "time_range_hours": hours,
        "found": len(explanations),
        "explanations": explanations,
    }


@router.get("/status", summary="XAI System Status")
async def get_xai_status() -> dict:
    """Get XAI system status and capabilities.
    
    Returns:
        Status information
    """
    return {
        "service": "XAI Explainability Layer",
        "version": "1.0",
        "status": "operational",
        "supported_models": [
            "Isolation Forest - Feature deviation explanations",
            "Prophet - Time-series cost analysis",
            "Zombie Detector - Idle resource identification",
        ],
        "explanation_types": [
            "summary - Human-readable summary",
            "key_factors - Contributing factors",
            "model_output - Detailed model results",
            "impact - Business impact assessment",
            "recommendation - Suggested actions",
        ],
        "endpoints": [
            "GET /xai/{resource_id} - Latest anomaly explanation",
            "GET /xai/anomaly/{anomaly_id} - Specific anomaly explanation",
            "GET /xai/resource/{resource_id}/recent - Recent explanations",
        ],
    }


@router.post("/batch-explain", summary="Batch Explanation Generation")
async def batch_explain_anomalies(
    resource_ids: list[int] = Query(..., description="Resource IDs to explain"),
    db: Session = Depends(get_db),
) -> dict:
    """Generate explanations for latest anomalies across multiple resources.
    
    Args:
        resource_ids: List of resource IDs
        db: Database session
        
    Returns:
        Dict mapping resource_id to explanation (or error message)
    """
    logger.info(f"Batch explaining anomalies for {len(resource_ids)} resources")
    
    results = {
        "total_resources": len(resource_ids),
        "explained": 0,
        "errors": 0,
        "explanations": {},
    }
    
    for resource_id in resource_ids:
        try:
            resource_repo = ResourceRepository(db)
            resource = resource_repo.get_by_id(resource_id)
            if not resource:
                results["explanations"][resource_id] = {"error": "Resource not found"}
                results["errors"] += 1
                continue
            
            anomaly_repo = AnomalyRepository(db)
            anomaly = anomaly_repo.get_for_resource(resource_id, limit=1)
            
            if not anomaly:
                results["explanations"][resource_id] = {
                    "message": "No anomalies detected",
                    "summary": "Resource operating normally",
                }
                results["explained"] += 1
            else:
                anomaly_record = anomaly[0] if isinstance(anomaly, list) else anomaly
                explanation = explainer.explain_anomaly(anomaly_record, db)
                results["explanations"][resource_id] = explanation
                results["explained"] += 1
                
        except Exception as e:
            logger.error(f"Error explaining resource {resource_id}: {e}")
            results["explanations"][resource_id] = {"error": str(e)}
            results["errors"] += 1
    
    logger.info(f"Batch explanation complete: {results['explained']} succeeded, "
               f"{results['errors']} failed")
    
    return results
