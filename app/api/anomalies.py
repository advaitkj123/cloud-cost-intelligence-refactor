"""Anomaly Detection API Endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_database
from app.db.repositories.anomaly_repository import AnomalyRepository
from app.db.repositories.feature_repository import FeatureRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.services.anomaly_service import AnomalyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.post("/detect-all")
def detect_anomalies_all(db: Session = Depends(get_database)) -> dict:
    """Detect anomalies for all resources.
    
    Returns:
        Dict with detected anomalies count and results
    """
    logger.info("Detecting anomalies for all resources")
    
    try:
        service = AnomalyService()
        resource_repo = ResourceRepository(db)
        feature_repo = FeatureRepository(db)
        anomaly_repo = AnomalyRepository(db)
        
        resources = resource_repo.list()
        detected_count = 0
        anomalies = []
        
        for resource in resources:
            # Get latest feature for resource
            latest_features = feature_repo.list_for_resource(resource.id, limit=1)
            if not latest_features:
                continue
            
            feature = latest_features[0]
            result = service.detect(db, resource, feature)
            
            if result.is_anomaly:
                detected_count += 1
                
                # Store anomaly in database
                from app.models.anomaly import Anomaly
                anomaly = Anomaly(
                    resource_id=resource.id,
                    is_anomaly=result.is_anomaly,
                    confidence=result.confidence,
                    anomaly_type=result.anomaly_type.value,
                    isolation_forest_score=result.details["isolation_forest"].get("anomaly_score"),
                    prophet_is_anomaly=result.details["prophet"].get("is_anomaly"),
                    prophet_confidence=result.details["prophet"].get("confidence"),
                    zombie_is_idle=result.details["zombie"].get("is_zombie"),
                    zombie_confidence=result.details["zombie"].get("confidence"),
                    cost_delta=feature.cost_delta,
                    cpu_avg=feature.cpu_avg,
                    efficiency_score=feature.efficiency_score,
                    details=result.details,
                    recommendations=service.get_recommendations(result, db),
                    timestamp=result.timestamp,
                )
                anomaly_repo.create(anomaly)
                anomalies.append(result.to_dict())
        
        return {
            "resources_processed": len(resources),
            "anomalies_detected": detected_count,
            "anomalies": anomalies,
        }
    except Exception as e:
        logger.error(f"Error detecting anomalies: {e}")
        return {"error": str(e), "anomalies_detected": 0}


@router.post("/detect-resource/{resource_id}")
def detect_anomaly_resource(
    resource_id: int, db: Session = Depends(get_database)
) -> dict:
    """Detect anomalies for specific resource.
    
    Args:
        resource_id: Resource ID
        
    Returns:
        Dict with anomaly detection result
    """
    logger.info(f"Detecting anomalies for resource_id={resource_id}")
    
    try:
        service = AnomalyService()
        resource_repo = ResourceRepository(db)
        feature_repo = FeatureRepository(db)
        anomaly_repo = AnomalyRepository(db)
        
        resource = resource_repo.get_by_id(resource_id)
        if not resource:
            return {"error": f"Resource {resource_id} not found"}
        
        # Get latest feature
        latest_features = feature_repo.list_for_resource(resource_id, limit=1)
        if not latest_features:
            return {"error": f"No features found for resource {resource_id}"}
        
        feature = latest_features[0]
        result = service.detect(db, resource, feature)
        
        if result.is_anomaly:
            # Store anomaly in database
            from app.models.anomaly import Anomaly
            anomaly = Anomaly(
                resource_id=resource.id,
                is_anomaly=result.is_anomaly,
                confidence=result.confidence,
                anomaly_type=result.anomaly_type.value,
                isolation_forest_score=result.details["isolation_forest"].get("anomaly_score"),
                prophet_is_anomaly=result.details["prophet"].get("is_anomaly"),
                prophet_confidence=result.details["prophet"].get("confidence"),
                zombie_is_idle=result.details["zombie"].get("is_zombie"),
                zombie_confidence=result.details["zombie"].get("confidence"),
                cost_delta=feature.cost_delta,
                cpu_avg=feature.cpu_avg,
                efficiency_score=feature.efficiency_score,
                details=result.details,
                recommendations=service.get_recommendations(result, db),
                timestamp=result.timestamp,
            )
            anomaly_repo.create(anomaly)
        
        return result.to_dict()
    except Exception as e:
        logger.error(f"Error detecting anomaly for resource {resource_id}: {e}")
        return {"error": str(e)}


@router.get("/recent")
def get_recent_anomalies(
    hours: int = Query(24, gt=0, le=720),
    min_confidence: float = Query(50.0, ge=0, le=100),
    db: Session = Depends(get_database),
) -> dict:
    """Get recent detected anomalies.
    
    Args:
        hours: Hours back to look
        min_confidence: Minimum confidence threshold
        
    Returns:
        List of recent anomalies
    """
    try:
        anomaly_repo = AnomalyRepository(db)
        anomalies = anomaly_repo.get_recent_anomalies(hours, min_confidence)
        
        return {
            "hours": hours,
            "min_confidence": min_confidence,
            "count": len(anomalies),
            "anomalies": [a.to_dict() for a in anomalies],
        }
    except Exception as e:
        logger.error(f"Error fetching anomalies: {e}")
        return {"error": str(e)}


@router.get("/resource/{resource_id}")
def get_resource_anomalies(
    resource_id: int, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_database)
) -> dict:
    """Get anomalies for specific resource.
    
    Args:
        resource_id: Resource ID
        limit: Maximum records to return
        
    Returns:
        List of anomalies for resource
    """
    try:
        anomaly_repo = AnomalyRepository(db)
        anomalies = anomaly_repo.get_for_resource(resource_id, limit)
        
        return {
            "resource_id": resource_id,
            "count": len(anomalies),
            "anomalies": [a.to_dict() for a in anomalies],
        }
    except Exception as e:
        logger.error(f"Error fetching anomalies for resource {resource_id}: {e}")
        return {"error": str(e)}


@router.get("/by-type/{anomaly_type}")
def get_anomalies_by_type(
    anomaly_type: str, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_database)
) -> dict:
    """Get anomalies of specific type.
    
    Args:
        anomaly_type: Type of anomaly (isolation_forest, prophet, zombie, hybrid)
        limit: Maximum records
        
    Returns:
        List of anomalies by type
    """
    try:
        anomaly_repo = AnomalyRepository(db)
        anomalies = anomaly_repo.get_anomalies_by_type(anomaly_type, limit)
        
        return {
            "anomaly_type": anomaly_type,
            "count": len(anomalies),
            "anomalies": [a.to_dict() for a in anomalies],
        }
    except Exception as e:
        logger.error(f"Error fetching anomalies by type {anomaly_type}: {e}")
        return {"error": str(e)}


@router.post("/acknowledge/{anomaly_id}")
def acknowledge_anomaly(
    anomaly_id: int,
    acknowledged_by: Optional[str] = Query(None),
    notes: Optional[str] = Query(None),
    db: Session = Depends(get_database),
) -> dict:
    """Acknowledge anomaly.
    
    Args:
        anomaly_id: Anomaly ID
        acknowledged_by: User acknowledging
        notes: Optional notes
        
    Returns:
        Updated anomaly
    """
    try:
        anomaly_repo = AnomalyRepository(db)
        anomaly = anomaly_repo.acknowledge(anomaly_id, acknowledged_by, notes)
        
        if anomaly:
            return anomaly.to_dict()
        return {"error": f"Anomaly {anomaly_id} not found"}
    except Exception as e:
        logger.error(f"Error acknowledging anomaly {anomaly_id}: {e}")
        return {"error": str(e)}


@router.get("/unacknowledged")
def get_unacknowledged_anomalies(
    resource_id: Optional[int] = Query(None), db: Session = Depends(get_database)
) -> dict:
    """Get unacknowledged anomalies.
    
    Args:
        resource_id: Optional resource filter
        
    Returns:
        List of unacknowledged anomalies
    """
    try:
        anomaly_repo = AnomalyRepository(db)
        anomalies = anomaly_repo.get_unacknowledged(resource_id)
        
        return {
            "resource_id": resource_id,
            "count": len(anomalies),
            "anomalies": [a.to_dict() for a in anomalies],
        }
    except Exception as e:
        logger.error(f"Error fetching unacknowledged anomalies: {e}")
        return {"error": str(e)}


@router.get("/statistics")
def get_anomaly_statistics(
    days: int = Query(30, ge=1, le=365), db: Session = Depends(get_database)
) -> dict:
    """Get anomaly detection statistics.
    
    Args:
        days: Days of history to analyze
        
    Returns:
        Statistics dict
    """
    try:
        anomaly_repo = AnomalyRepository(db)
        stats = anomaly_repo.get_statistics(days)
        
        return {"period_days": days, **stats}
    except Exception as e:
        logger.error(f"Error getting anomaly statistics: {e}")
        return {"error": str(e)}


@router.get("/status")
def get_anomaly_detection_status(db: Session = Depends(get_database)) -> dict:
    """Get anomaly detection system status.
    
    Returns:
        Status information
    """
    try:
        service = AnomalyService()
        status = service.get_status()
        
        # Add statistics
        anomaly_repo = AnomalyRepository(db)
        stats = anomaly_repo.get_statistics(days=30)
        
        return {**status, "statistics_30d": stats}
    except Exception as e:
        logger.error(f"Error getting anomaly detection status: {e}")
        return {"error": str(e)}


@router.post("/train")
def train_anomaly_models(db: Session = Depends(get_database)) -> dict:
    """Train all anomaly detection models.
    
    Returns:
        Training results
    """
    logger.info("Training anomaly detection models")
    
    try:
        service = AnomalyService()
        results = service.train_models(db)
        
        return results
    except Exception as e:
        logger.error(f"Error training models: {e}")
        return {"error": str(e), "timestamp": None}
