"""Isolation Forest Model for Anomaly Detection.

Train on feature vectors and detect anomalies using Isolation Forest.
Uses scikit-learn's implementation with configurable contamination.
"""

import logging
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.repositories.feature_repository import FeatureRepository
from app.models.features import Feature

logger = logging.getLogger(__name__)


class IsolationForestModel:
    """Isolation Forest Anomaly Detection Model.
    
    Trains on feature vectors and detects anomalies using isolation forest.
    Stores model as pickle file for persistence.
    """

    def __init__(self, contamination: float = 0.1, random_state: int = 42):
        """Initialize Isolation Forest model.
        
        Args:
            contamination: Fraction of dataset to consider as anomalies (0.0-0.5)
            random_state: Random seed for reproducibility
        """
        self.contamination = contamination
        self.random_state = random_state
        self.model: Optional[IsolationForest] = None
        self.model_path = Path(settings.model_storage_path) / "isolation_forest.pkl"
        self.feature_names: list[str] = []
        self.trained_at: Optional[datetime] = None
        self.training_samples: int = 0

    def _get_feature_vector(self, feature: Feature) -> Optional[np.ndarray]:
        """Extract feature vector from Feature model instance.
        
        Args:
            feature: Feature model instance
            
        Returns:
            numpy array of numeric features, or None if incomplete
        """
        features_dict = {
            "cost_delta": feature.cost_delta,
            "cost_rolling_mean": feature.cost_rolling_mean,
            "cost_rolling_std": feature.cost_rolling_std,
            "cpu_avg": feature.cpu_avg,
            "cpu_rolling_mean": feature.cpu_rolling_mean,
            "cpu_rolling_std": feature.cpu_rolling_std,
            "memory_avg": feature.memory_avg,
            "memory_rolling_mean": feature.memory_rolling_mean,
            "storage_total": feature.storage_total,
            "storage_rolling_mean": feature.storage_rolling_mean,
            "network_total": feature.network_total,
            "network_rolling_mean_in": feature.network_rolling_mean_in,
            "network_rolling_mean_out": feature.network_rolling_mean_out,
            "request_count": feature.request_count,
            "request_rolling_mean": feature.request_rolling_mean,
            "request_rolling_std": feature.request_rolling_std,
            "service_ratio": feature.service_ratio,
            "efficiency_score": feature.efficiency_score,
            "data_quality": feature.data_quality,
        }

        # Check for missing values
        if any(v is None for v in features_dict.values()):
            return None

        self.feature_names = list(features_dict.keys())
        return np.array(list(features_dict.values()), dtype=np.float32).reshape(1, -1)

    def train(self, db: Session, days_back: int = 30) -> dict:
        """Train Isolation Forest on recent feature data.
        
        Args:
            db: Database session
            days_back: How many days of history to use for training
            
        Returns:
            Training statistics dict
        """
        logger.info(
            "Starting Isolation Forest training with %d days of history",
            days_back,
        )

        feature_repo = FeatureRepository(db)

        # Get recent features
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        features = (
            db.query(Feature)
            .filter(Feature.created_at >= cutoff_date)
            .order_by(Feature.timestamp.desc())
            .all()
        )

        if len(features) < 10:
            logger.warning(
                "Not enough training data: %d features (need at least 10)",
                len(features),
            )
            return {
                "trained": False,
                "reason": "insufficient_data",
                "features_count": len(features),
            }

        # Extract feature vectors
        feature_vectors = []
        for feature in features:
            vector = self._get_feature_vector(feature)
            if vector is not None:
                feature_vectors.append(vector[0])

        if len(feature_vectors) < 10:
            logger.warning(
                "Not enough valid feature vectors: %d (need at least 10)",
                len(feature_vectors),
            )
            return {
                "trained": False,
                "reason": "insufficient_valid_vectors",
                "vectors_count": len(feature_vectors),
            }

        # Train model
        X_train = np.array(feature_vectors, dtype=np.float32)
        logger.info("Training on %d samples with %d features", X_train.shape[0], X_train.shape[1])

        self.model = IsolationForest(
            contamination=self.contamination,
            random_state=self.random_state,
            n_estimators=100,
        )
        self.model.fit(X_train)

        self.trained_at = datetime.utcnow()
        self.training_samples = len(feature_vectors)

        # Save model
        self._save_model()

        stats = {
            "trained": True,
            "training_samples": len(feature_vectors),
            "feature_count": X_train.shape[1],
            "contamination": self.contamination,
            "trained_at": self.trained_at.isoformat(),
        }

        logger.info("Isolation Forest training completed: %s", stats)
        return stats

    def predict_anomaly_score(self, feature: Feature) -> Optional[float]:
        """Predict anomaly score for a feature.
        
        Score ranges from -1 (anomaly) to 1 (normal).
        Normalized to 0-100 where:
        - 0-30: Normal
        - 30-70: Borderline
        - 70-100: Anomaly
        
        Args:
            feature: Feature model instance
            
        Returns:
            Anomaly score (0-100), or None if model not trained
        """
        if self.model is None:
            self._load_model()

        if self.model is None:
            logger.warning("Isolation Forest model not available for prediction")
            return None

        try:
            vector = self._get_feature_vector(feature)
            if vector is None:
                logger.debug("Missing features for anomaly score calculation")
                return None

            # Get raw prediction (-1 for anomaly, 1 for normal)
            raw_prediction = self.model.predict(vector)[0]
            anomaly_score_raw = self.model.score_samples(vector)[0]

            # Normalize to 0-100
            # score_samples returns negative values for anomalies
            # We normalize: -0.5 (anomaly) -> 100, 0.5 (normal) -> 0
            anomaly_score_normalized = np.clip(
                ((anomaly_score_raw - anomaly_score_raw.min()) / 
                 (anomaly_score_raw.max() - anomaly_score_raw.min() + 1e-8) * 100),
                0,
                100,
            )

            # Simpler normalization: convert -1/1 to 0-100
            # If prediction is -1 (anomaly), give high score
            # If prediction is 1 (normal), give low score
            if raw_prediction == -1:
                # For anomalies, use higher score
                anomaly_score_normalized = max(70.0, min(100.0, 70.0 + (abs(anomaly_score_raw) * 10)))
            else:
                # For normal, use lower score, but still consider the anomaly_score
                anomaly_score_normalized = max(0.0, min(70.0, max(0.0, anomaly_score_raw * 50)))

            return float(anomaly_score_normalized)

        except Exception as e:
            logger.error("Error predicting anomaly score: %s", e)
            return None

    def _save_model(self) -> None:
        """Save model to pickle file."""
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.model_path, "wb") as f:
                pickle.dump(
                    {
                        "model": self.model,
                        "feature_names": self.feature_names,
                        "contamination": self.contamination,
                        "trained_at": self.trained_at,
                        "training_samples": self.training_samples,
                    },
                    f,
                )
            logger.info("Isolation Forest model saved to %s", self.model_path)
        except Exception as e:
            logger.error("Error saving model: %s", e)

    def _load_model(self) -> bool:
        """Load model from pickle file.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            if not self.model_path.exists():
                logger.debug("Model file not found: %s", self.model_path)
                return False

            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
                self.model = data["model"]
                self.feature_names = data.get("feature_names", [])
                self.contamination = data.get("contamination", 0.1)
                self.trained_at = data.get("trained_at")
                self.training_samples = data.get("training_samples", 0)

            logger.info("Isolation Forest model loaded from %s", self.model_path)
            return True
        except Exception as e:
            logger.error("Error loading model: %s", e)
            return False

    def get_info(self) -> dict:
        """Get model information.
        
        Returns:
            Dict with model status and training info
        """
        return {
            "model_type": "isolation_forest",
            "is_trained": self.model is not None,
            "contamination": self.contamination,
            "feature_count": len(self.feature_names),
            "feature_names": self.feature_names,
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "training_samples": self.training_samples,
            "model_path": str(self.model_path),
        }
