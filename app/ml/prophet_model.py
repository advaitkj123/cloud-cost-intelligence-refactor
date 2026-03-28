"""Prophet Model for Time-Series Forecasting and Anomaly Detection.

Uses Facebook's Prophet library to fit time-series data and detect anomalies
when actual values exceed predicted upper bounds.
"""

import logging
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.cost import CostRecord
from app.models.resource import Resource

logger = logging.getLogger(__name__)


class ProphetModel:
    """Time-Series Forecasting and Anomaly Detection using Prophet.
    
    Trains on cost time-series data and detects anomalies when
    actual values exceed predicted upper confidence bounds.
    """

    def __init__(self, interval_width: float = 0.95):
        """Initialize Prophet model.
        
        Args:
            interval_width: Confidence interval width (0.0-1.0)
        """
        self.interval_width = interval_width
        self.models: dict[int, Prophet] = {}  # resource_id -> model
        self.model_paths = Path(settings.model_storage_path) / "prophet"
        self.model_paths.mkdir(parents=True, exist_ok=True)

    def train(self, db: Session, resource_id: int, days_back: int = 30) -> dict:
        """Train Prophet model on cost time-series for a resource.
        
        Args:
            db: Database session
            resource_id: Resource ID to train for
            days_back: Days of history to use for training
            
        Returns:
            Training statistics dict
        """
        logger.info(
            "Starting Prophet training for resource_id=%s with %d days of history",
            resource_id,
            days_back,
        )

        # Get cost data for resource
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        costs = (
            db.query(CostRecord)
            .filter(
                CostRecord.resource_id == resource_id,
                CostRecord.created_at >= cutoff_date,
            )
            .order_by(CostRecord.timestamp.asc())
            .all()
        )

        if len(costs) < 10:
            logger.warning(
                "Not enough training data for resource_id=%s: %d records (need at least 10)",
                resource_id,
                len(costs),
            )
            return {
                "trained": False,
                "resource_id": resource_id,
                "reason": "insufficient_data",
                "records_count": len(costs),
            }

        # Prepare data for Prophet
        df_data = []
        for cost in costs:
            df_data.append(
                {
                    "ds": pd.Timestamp(cost.timestamp),
                    "y": float(cost.estimated_cost),
                }
            )

        df = pd.DataFrame(df_data)

        # Check for minimum variation
        if df["y"].std() < 1e-6:
            logger.warning(
                "Insufficient cost variation for resource_id=%s: std=%.2e",
                resource_id,
                df["y"].std(),
            )
            return {
                "trained": False,
                "resource_id": resource_id,
                "reason": "insufficient_variation",
                "cost_std": float(df["y"].std()),
            }

        # Train Prophet model
        try:
            model = Prophet(
                interval_width=self.interval_width,
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=False,
                seasonality_mode="additive",
            )
            model.fit(df)

            self.models[resource_id] = model
            self._save_model(resource_id, model)

            stats = {
                "trained": True,
                "resource_id": resource_id,
                "training_records": len(df),
                "cost_mean": float(df["y"].mean()),
                "cost_std": float(df["y"].std()),
                "cost_min": float(df["y"].min()),
                "cost_max": float(df["y"].max()),
                "interval_width": self.interval_width,
            }

            logger.info("Prophet training completed for resource_id=%s: %s", resource_id, stats)
            return stats

        except Exception as e:
            logger.error("Error training Prophet model for resource_id=%s: %s", resource_id, e)
            return {
                "trained": False,
                "resource_id": resource_id,
                "reason": "training_error",
                "error": str(e),
            }

    def predict_anomaly(
        self, resource_id: int, actual_cost: float, periods_ahead: int = 1
    ) -> Optional[dict]:
        """Detect anomaly by comparing actual cost to predicted upper bound.
        
        Args:
            resource_id: Resource ID
            actual_cost: Actual observed cost
            periods_ahead: Periods ahead to use for prediction (default: next period)
            
        Returns:
            Dict with anomaly detection results, or None if model unavailable
        """
        model = self.models.get(resource_id)
        if model is None:
            model = self._load_model(resource_id)

        if model is None:
            logger.debug("Prophet model not available for resource_id=%s", resource_id)
            return None

        try:
            # Make prediction for next period
            future = model.make_future_dataframe(periods=periods_ahead)
            forecast = model.predict(future)

            # Get latest prediction
            latest_forecast = forecast.iloc[-1]

            predicted_cost = float(latest_forecast["yhat"])
            upper_bound = float(latest_forecast["yhat_upper"])
            lower_bound = float(latest_forecast["yhat_lower"])

            # Detect anomaly
            is_anomaly = actual_cost > upper_bound
            confidence = min(
                100.0,
                ((actual_cost - upper_bound) / (upper_bound - predicted_cost + 1e-6)) * 100
                if upper_bound > predicted_cost
                else 0.0,
            )

            # Clip confidence to 0-100
            confidence = max(0.0, min(100.0, confidence))

            return {
                "is_anomaly": is_anomaly,
                "actual_cost": actual_cost,
                "predicted_cost": predicted_cost,
                "upper_bound": upper_bound,
                "lower_bound": lower_bound,
                "confidence": float(confidence),
                "anomaly_severity": (actual_cost - upper_bound) / (upper_bound + 1e-6)
                if is_anomaly
                else 0.0,
            }

        except Exception as e:
            logger.error("Error predicting anomaly for resource_id=%s: %s", resource_id, e)
            return None

    def _save_model(self, resource_id: int, model: Prophet) -> None:
        """Save Prophet model to pickle file.
        
        Args:
            resource_id: Resource ID
            model: Trained Prophet model
        """
        try:
            model_path = self.model_paths / f"prophet_resource_{resource_id}.pkl"
            with open(model_path, "wb") as f:
                pickle.dump(model, f)
            logger.info("Prophet model saved for resource_id=%s to %s", resource_id, model_path)
        except Exception as e:
            logger.error("Error saving Prophet model for resource_id=%s: %s", resource_id, e)

    def _load_model(self, resource_id: int) -> Optional[Prophet]:
        """Load Prophet model from pickle file.
        
        Args:
            resource_id: Resource ID
            
        Returns:
            Prophet model if loaded successfully, None otherwise
        """
        try:
            model_path = self.model_paths / f"prophet_resource_{resource_id}.pkl"
            if not model_path.exists():
                logger.debug("Prophet model file not found for resource_id=%s", resource_id)
                return None

            with open(model_path, "rb") as f:
                model = pickle.load(f)
            logger.info("Prophet model loaded for resource_id=%s", resource_id)
            return model

        except Exception as e:
            logger.error("Error loading Prophet model for resource_id=%s: %s", resource_id, e)
            return None

    def train_all(self, db: Session, days_back: int = 30) -> dict:
        """Train Prophet models for all resources.
        
        Args:
            db: Database session
            days_back: Days of history to use for training
            
        Returns:
            Dict with training results for all resources
        """
        logger.info("Starting Prophet training for all resources")

        resources = db.query(Resource).all()
        results = {
            "total_resources": len(resources),
            "trained": 0,
            "failed": 0,
            "details": [],
        }

        for resource in resources:
            result = self.train(db, resource.id, days_back)
            if result["trained"]:
                results["trained"] += 1
            else:
                results["failed"] += 1
            results["details"].append(result)

        logger.info(
            "Prophet training completed: %d trained, %d failed",
            results["trained"],
            results["failed"],
        )
        return results

    def get_info(self) -> dict:
        """Get model information.
        
        Returns:
            Dict with model status and info
        """
        return {
            "model_type": "prophet",
            "interval_width": self.interval_width,
            "trained_resources": len(self.models),
            "resource_ids": list(self.models.keys()),
            "model_dir": str(self.model_paths),
        }
