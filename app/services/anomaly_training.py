"""Anomaly Model Training Service.

Background training jobs for ML-based anomaly detection models.
Handles scheduled retraining of Isolation Forest and Prophet models.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.isolation_forest import IsolationForestModel
from app.ml.prophet_model import ProphetModel
from app.ml.zombie_detector import ZombieDetector

logger = logging.getLogger(__name__)


class AnomalyTrainingService:
    """Service for training anomaly detection models."""

    def __init__(self):
        """Initialize training service."""
        self.isolation_forest = IsolationForestModel(
            contamination=settings.anomaly_contamination
        )
        self.prophet = ProphetModel(interval_width=settings.prophet_interval_width)
        self.zombie_detector = ZombieDetector()
        self.last_training_time: datetime | None = None

    def train_all_models(
        self, db: Session, days_back: int = 30, force: bool = False
    ) -> dict:
        """Train all anomaly detection models.

        Args:
            db: Database session
            days_back: Days of history to use for training
            force: Force retraining regardless of schedule

        Returns:
            Dict with training results
        """
        logger.info("Starting anomaly model training (days_back=%d, force=%s)", days_back, force)

        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "days_back": days_back,
            "models": {},
        }

        # Train Isolation Forest
        if settings.isolation_forest_enabled:
            try:
                logger.info("Training Isolation Forest model...")
                iso_result = self.isolation_forest.train(db, days_back)
                results["models"]["isolation_forest"] = iso_result
                logger.info("Isolation Forest training completed: %s", iso_result)
            except Exception as e:
                logger.error("Error training Isolation Forest: %s", e, exc_info=True)
                results["models"]["isolation_forest"] = {
                    "trained": False,
                    "error": str(e),
                }

        # Train Prophet
        if settings.prophet_enabled:
            try:
                logger.info("Training Prophet models...")
                prophet_result = self.prophet.train_all(db, days_back)
                results["models"]["prophet"] = prophet_result
                logger.info("Prophet training completed: %s", prophet_result)
            except Exception as e:
                logger.error("Error training Prophet: %s", e, exc_info=True)
                results["models"]["prophet"] = {
                    "trained": False,
                    "error": str(e),
                }

        # Zombie detector is rule-based, no training needed
        if settings.zombie_detector_enabled:
            results["models"]["zombie"] = {
                "type": "rule_based",
                "status": "ready",
                "thresholds": self.zombie_detector.get_info(),
            }

        self.last_training_time = datetime.utcnow()
        logger.info("Anomaly model training completed")

        return results

    def get_training_status(self) -> dict:
        """Get training status information.

        Returns:
            Dict with training status
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "last_training_time": (
                self.last_training_time.isoformat() if self.last_training_time else None
            ),
            "models": {
                "isolation_forest": self.isolation_forest.get_info(),
                "prophet": self.prophet.get_info(),
                "zombie": self.zombie_detector.get_info(),
            },
        }


# Global instance for background jobs
_training_service: AnomalyTrainingService | None = None


def get_training_service() -> AnomalyTrainingService:
    """Get or create training service instance.

    Returns:
        AnomalyTrainingService instance
    """
    global _training_service
    if _training_service is None:
        _training_service = AnomalyTrainingService()
    return _training_service
