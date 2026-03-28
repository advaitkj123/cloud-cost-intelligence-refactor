"""Anomaly Service - Hybrid Anomaly Detection.

Combines Isolation Forest, Prophet, and Zombie Detector
to provide comprehensive anomaly detection.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.isolation_forest import IsolationForestModel
from app.ml.prophet_model import ProphetModel
from app.ml.zombie_detector import ZombieDetector
from app.models.features import Feature
from app.models.resource import Resource

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """Types of anomalies that can be detected."""

    ISOLATION_FOREST = "isolation_forest"
    PROPHET = "prophet"
    ZOMBIE = "zombie"
    HYBRID = "hybrid"
    COST_SPIKE = "cost_spike"
    BEHAVIOR_CHANGE = "behavior_change"
    RESOURCE_IDLE = "resource_idle"


class AnomalyResult:
    """Result of anomaly detection."""

    def __init__(
        self,
        is_anomaly: bool,
        confidence: float,
        anomaly_type: AnomalyType,
        resource_id: int,
        timestamp: datetime,
        details: dict,
    ):
        """Initialize anomaly result.
        
        Args:
            is_anomaly: Whether anomaly was detected
            confidence: Confidence score (0-100)
            anomaly_type: Type of anomaly
            resource_id: Resource ID
            timestamp: Timestamp of detection
            details: Detailed detection results
        """
        self.is_anomaly = is_anomaly
        self.confidence = confidence
        self.anomaly_type = anomaly_type
        self.resource_id = resource_id
        self.timestamp = timestamp
        self.details = details

    def to_dict(self) -> dict:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation
        """
        return {
            "is_anomaly": self.is_anomaly,
            "confidence": self.confidence,
            "anomaly_type": self.anomaly_type.value,
            "resource_id": self.resource_id,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class AnomalyService:
    """Hybrid Anomaly Detection Service.
    
    Combines multiple anomaly detection methods:
    1. Isolation Forest - feature vector anomalies
    2. Prophet - cost time-series anomalies
    3. Zombie Detector - idle resource detection
    """

    def __init__(self):
        """Initialize Anomaly Service."""
        self.isolation_forest = IsolationForestModel(contamination=settings.anomaly_contamination)
        self.prophet = ProphetModel()
        self.zombie_detector = ZombieDetector()

    def detect(self, db: Session, resource: Resource, feature: Feature) -> AnomalyResult:
        """Detect anomalies using hybrid approach.
        
        Args:
            db: Database session
            resource: Resource record
            feature: Feature record
            
        Returns:
            AnomalyResult with combined detection results
        """
        logger.debug("Detecting anomalies for resource_id=%s", resource.id)

        # Collect detection results
        isolation_score = self.isolation_forest.predict_anomaly_score(feature)
        prophet_result = self.prophet.predict_anomaly(resource.id, feature.cost_delta or 0.0)
        zombie_result = self.zombie_detector.detect(resource, feature)

        # Determine combined anomaly and confidence
        is_anomaly, confidence, anomaly_type = self._combine_results(
            isolation_score, prophet_result, zombie_result
        )

        # Create detailed result
        details = {
            "isolation_forest": {
                "anomaly_score": isolation_score,
                "is_anomaly": isolation_score is not None and isolation_score > 70,
            },
            "prophet": prophet_result if prophet_result else {"not_available": True},
            "zombie": zombie_result if zombie_result else {"not_available": True},
        }

        result = AnomalyResult(
            is_anomaly=is_anomaly,
            confidence=confidence,
            anomaly_type=anomaly_type,
            resource_id=resource.id,
            timestamp=datetime.utcnow(),
            details=details,
        )

        if is_anomaly:
            logger.warning(
                "Anomaly detected: resource_id=%s, type=%s, confidence=%.1f%%",
                resource.id,
                anomaly_type,
                confidence,
            )
        else:
            logger.debug(
                "No anomaly detected: resource_id=%s, confidence=%.1f%%",
                resource.id,
                confidence,
            )

        return result

    def _combine_results(
        self,
        isolation_score: Optional[float],
        prophet_result: Optional[dict],
        zombie_result: Optional[dict],
    ) -> tuple[bool, float, AnomalyType]:
        """Combine detection results from all methods.
        
        Args:
            isolation_score: Anomaly score from Isolation Forest (0-100)
            prophet_result: Anomaly result from Prophet
            zombie_result: Anomaly result from Zombie Detector
            
        Returns:
            Tuple of (is_anomaly, confidence, anomaly_type)
        """
        # Track which detectors flagged anomalies
        detectors_triggered = []
        confidence_scores = []

        # Check Isolation Forest
        if isolation_score is not None and isolation_score > 70:
            detectors_triggered.append(AnomalyType.ISOLATION_FOREST)
            confidence_scores.append(isolation_score)

        # Check Prophet
        if (
            prophet_result
            and prophet_result.get("is_anomaly")
            and prophet_result.get("confidence", 0) > 30
        ):
            detectors_triggered.append(AnomalyType.PROPHET)
            confidence_scores.append(prophet_result.get("confidence", 0))

        # Check Zombie Detector
        if (
            zombie_result
            and zombie_result.get("is_zombie")
            and zombie_result.get("confidence", 0) > 50
        ):
            detectors_triggered.append(AnomalyType.ZOMBIE)
            confidence_scores.append(zombie_result.get("confidence", 0))

        # Determine combined result
        is_anomaly = len(detectors_triggered) > 0
        confidence = (
            sum(confidence_scores) / len(confidence_scores)
            if confidence_scores
            else 0.0
        )

        # Select anomaly type based on detectors triggered
        if not is_anomaly:
            anomaly_type = AnomalyType.HYBRID
        elif len(detectors_triggered) > 1:
            # Multiple detectors triggered - high confidence hybrid anomaly
            anomaly_type = AnomalyType.HYBRID
        elif AnomalyType.ISOLATION_FOREST in detectors_triggered:
            anomaly_type = AnomalyType.BEHAVIOR_CHANGE
        elif AnomalyType.PROPHET in detectors_triggered:
            anomaly_type = AnomalyType.COST_SPIKE
        elif AnomalyType.ZOMBIE in detectors_triggered:
            anomaly_type = AnomalyType.RESOURCE_IDLE
        else:
            anomaly_type = AnomalyType.HYBRID

        return is_anomaly, min(100.0, confidence), anomaly_type

    def train_models(self, db: Session, days_back: int = 30) -> dict:
        """Train all models.
        
        Args:
            db: Database session
            days_back: Days of history to use for training
            
        Returns:
            Dict with training results for all models
        """
        logger.info("Starting model training for all detectors")

        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "isolation_forest": {},
            "prophet": {},
            "zombie": {"status": "rule_based, no training needed"},
        }

        # Train Isolation Forest on all features
        try:
            iso_result = self.isolation_forest.train(db, days_back)
            results["isolation_forest"] = iso_result
        except Exception as e:
            logger.error("Error training Isolation Forest: %s", e)
            results["isolation_forest"] = {"error": str(e)}

        # Train Prophet for all resources
        try:
            prophet_result = self.prophet.train_all(db, days_back)
            results["prophet"] = prophet_result
        except Exception as e:
            logger.error("Error training Prophet: %s", e)
            results["prophet"] = {"error": str(e)}

        logger.info("Model training completed: %s", results)
        return results

    def get_status(self) -> dict:
        """Get status of all detectors.
        
        Returns:
            Dict with status information
        """
        return {
            "service_type": "hybrid_anomaly_detection",
            "timestamp": datetime.utcnow().isoformat(),
            "detectors": {
                "isolation_forest": self.isolation_forest.get_info(),
                "prophet": self.prophet.get_info(),
                "zombie": self.zombie_detector.get_info(),
            },
        }

    def get_recommendations(
        self, result: AnomalyResult, db: Optional[Session] = None
    ) -> list[str]:
        """Get recommendations for detected anomaly.
        
        Args:
            result: AnomalyResult from detect()
            db: Optional database session for additional context
            
        Returns:
            List of recommendations
        """
        recommendations = []

        if not result.is_anomaly:
            return ["No anomalies detected"]

        # Add type-specific recommendations
        if result.anomaly_type == AnomalyType.RESOURCE_IDLE:
            zombie_result = result.details.get("zombie", {})
            recommendations.extend(ZombieDetector.get_zombie_recommendations(zombie_result))

        elif result.anomaly_type == AnomalyType.COST_SPIKE:
            recommendations.append("Investigate cost increase")
            recommendations.append("Review recent deployments")
            recommendations.append("Check for unexpected traffic")
            recommendations.append("Review scaling policies")

        elif result.anomaly_type == AnomalyType.BEHAVIOR_CHANGE:
            recommendations.append("Unusual resource behavior detected")
            recommendations.append("Review recent configuration changes")
            recommendations.append("Check CloudWatch metrics")
            recommendations.append("Consider incident investigation")

        elif result.anomaly_type == AnomalyType.HYBRID:
            recommendations.append("Multiple anomaly signals detected")
            recommendations.append("Priority: Immediate investigation recommended")
            recommendations.append("Check all telemetry channels")
            recommendations.append("Contact on-call team")

        # Add general recommendations
        recommendations.append("Set up CloudWatch alarm for this resource")
        recommendations.append("Review logs for correlation")

        return recommendations
