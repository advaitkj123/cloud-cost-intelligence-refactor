"""Feature engineering pipeline for ML models."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.logger import logger
from app.models.features import Feature
from app.models.metrics import Metric
from app.models.resource import Resource

if TYPE_CHECKING:
    pass


class FeatureEngineer:
    """Computes engineered features from metrics and costs."""

    ROLLING_WINDOW_DAYS = 7  # Rolling statistics window
    MIN_SAMPLES_FOR_ROLLING = 10  # Minimum samples for rolling calculations

    def __init__(self, resource: Resource):
        self.resource = resource
        self.resource_id = resource.id
        self.resource_type = resource.type

    def engineer_features(
        self,
        recent_metrics: list[Metric],
        rolling_metrics: list[Metric],
        current_cost: float = 0.0,
        prev_cost: float = 0.0,
        timestamp: datetime | None = None,
    ) -> Feature:
        """Engineer features from metrics.

        Args:
            recent_metrics: Metrics from current period (5 min - 1 hour)
            rolling_metrics: Metrics from rolling window (7 days)
            current_cost: Current estimated cost
            prev_cost: Previous period cost (for delta)
            timestamp: Feature timestamp (default: now UTC)

        Returns:
            Feature object with computed features
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        feature = Feature(
            resource_id=self.resource_id,
            timestamp=timestamp,
        )

        # Compute all feature groups
        self._compute_cost_features(feature, recent_metrics, rolling_metrics, current_cost, prev_cost)
        self._compute_usage_features(feature, recent_metrics, rolling_metrics)
        self._compute_network_features(feature, recent_metrics, rolling_metrics)
        self._compute_request_features(feature, recent_metrics, rolling_metrics)
        self._compute_service_features(feature, recent_metrics, rolling_metrics)
        self._compute_time_features(feature, timestamp)
        self._compute_data_quality(feature, recent_metrics)

        logger.debug(
            f"Engineered features for resource {self.resource_id}: "
            f"cost_delta={feature.cost_delta:.4f}, "
            f"cpu_avg={feature.cpu_avg:.2f}, "
            f"efficiency={feature.efficiency_score:.2f}"
        )

        return feature

    def _compute_cost_features(
        self,
        feature: Feature,
        recent_metrics: list[Metric],
        rolling_metrics: list[Metric],
        current_cost: float,
        prev_cost: float,
    ) -> None:
        """Compute cost-related features."""
        feature.cost_delta = current_cost - prev_cost

        # Rolling cost statistics
        if rolling_metrics:
            rolling_costs = []
            for i in range(0, len(rolling_metrics), max(1, len(rolling_metrics) // 24)):
                # Approximate cost per metric point
                rolling_costs.append(current_cost * (1 + (i - len(rolling_metrics) / 2) / len(rolling_metrics)))

            if rolling_costs:
                feature.cost_rolling_mean = sum(rolling_costs) / len(rolling_costs)
                # Compute rolling std
                if len(rolling_costs) > 1:
                    mean = feature.cost_rolling_mean
                    variance = sum((x - mean) ** 2 for x in rolling_costs) / len(rolling_costs)
                    feature.cost_rolling_std = math.sqrt(variance)

    def _compute_usage_features(
        self,
        feature: Feature,
        recent_metrics: list[Metric],
        rolling_metrics: list[Metric],
    ) -> None:
        """Compute CPU and memory usage features."""
        if recent_metrics:
            # Recent averages
            feature.cpu_avg = sum(m.cpu_usage for m in recent_metrics) / len(recent_metrics)
            feature.memory_avg = sum(m.memory_usage for m in recent_metrics) / len(recent_metrics)
            feature.storage_total = sum(m.storage_used for m in recent_metrics) / len(recent_metrics)

        if rolling_metrics:
            # Rolling CPU statistics
            cpu_values = [m.cpu_usage for m in rolling_metrics if m.cpu_usage > 0]
            if cpu_values:
                feature.cpu_rolling_mean = sum(cpu_values) / len(cpu_values)

                # Compute rolling std
                if len(cpu_values) > 1:
                    mean = feature.cpu_rolling_mean
                    variance = sum((x - mean) ** 2 for x in cpu_values) / len(cpu_values)
                    feature.cpu_rolling_std = math.sqrt(variance)

    def _compute_network_features(
        self,
        feature: Feature,
        recent_metrics: list[Metric],
        rolling_metrics: list[Metric],
    ) -> None:
        """Compute network utilization features."""
        if recent_metrics:
            # Total network (bytes)
            feature.network_total = sum(
                m.network_in + m.network_out for m in recent_metrics
            )

        if rolling_metrics and len(rolling_metrics) >= self.MIN_SAMPLES_FOR_ROLLING:
            # Rolling network means
            network_in_values = [m.network_in for m in rolling_metrics if m.network_in > 0]
            network_out_values = [m.network_out for m in rolling_metrics if m.network_out > 0]

            if network_in_values:
                feature.network_in_rolling_mean = sum(network_in_values) / len(network_in_values)
            if network_out_values:
                feature.network_out_rolling_mean = sum(network_out_values) / len(network_out_values)

    def _compute_request_features(
        self,
        feature: Feature,
        recent_metrics: list[Metric],
        rolling_metrics: list[Metric],
    ) -> None:
        """Compute request/invocation features."""
        if recent_metrics:
            feature.request_count = sum(m.requests for m in recent_metrics)

        if rolling_metrics and len(rolling_metrics) >= self.MIN_SAMPLES_FOR_ROLLING:
            # Rolling request statistics
            request_values = [m.requests for m in rolling_metrics if m.requests > 0]

            if request_values:
                feature.request_rolling_mean = sum(request_values) / len(request_values)

                # Compute rolling std
                if len(request_values) > 1:
                    mean = feature.request_rolling_mean
                    variance = sum((x - mean) ** 2 for x in request_values) / len(request_values)
                    feature.request_rolling_std = math.sqrt(variance)

    def _compute_service_features(
        self,
        feature: Feature,
        recent_metrics: list[Metric],
        rolling_metrics: list[Metric],
    ) -> None:
        """Compute service-specific features."""
        if recent_metrics:
            # Service ratio (requests / CPU, higher = more efficient)
            cpu_usage_total = sum(m.cpu_usage for m in recent_metrics) or 1.0
            request_total = sum(m.requests for m in recent_metrics) or 0.0
            feature.service_ratio = request_total / cpu_usage_total if cpu_usage_total > 0 else 0.0

            # Efficiency score: high requests + low CPU = efficient
            # Normalized 0-100
            cpu_pct = (feature.cpu_avg / 100.0)  # CPU is 0-100
            if cpu_pct > 0:
                feature.efficiency_score = min(100, (feature.service_ratio / cpu_pct) * 10)
            else:
                feature.efficiency_score = 50.0  # Neutral if no CPU

    def _compute_time_features(self, feature: Feature, timestamp: datetime) -> None:
        """Compute time-based features for seasonal modeling."""
        # Hour of day (0-23)
        feature.hour_of_day = timestamp.hour

        # Day of week (0=Monday, 6=Sunday)
        feature.day_of_week = timestamp.weekday()

        # Sin/Cos encoding for cyclic hour (helps neural networks)
        hour_normalized = (timestamp.hour + timestamp.minute / 60) / 24.0
        feature.time_sin = math.sin(2 * math.pi * hour_normalized)
        feature.time_cos = math.cos(2 * math.pi * hour_normalized)

    def _compute_data_quality(self, feature: Feature, recent_metrics: list[Metric]) -> None:
        """Compute data quality metrics."""
        if recent_metrics:
            feature.metric_count = len(recent_metrics)

            # Data quality: fraction of metrics with valid data
            valid_count = sum(
                1 for m in recent_metrics
                if m.cpu_usage >= 0 or m.memory_usage >= 0 or m.network_in >= 0
            )
            feature.data_quality = valid_count / len(recent_metrics) if recent_metrics else 0.0
        else:
            feature.data_quality = 0.0


class FeatureAggregator:
    """Aggregates metrics into rolling statistics."""

    @staticmethod
    def get_rolling_window(
        metrics: list[Metric],
        days: int = 7,
    ) -> list[Metric]:
        """Get metrics from the last N days.

        Args:
            metrics: List of all metrics (should already be filtered/sorted)
            days: Number of days to include

        Returns:
            Filtered metrics within the window
        """
        if not metrics:
            return []

        cutoff_time = datetime.now(UTC) - timedelta(days=days)
        return [m for m in metrics if m.timestamp >= cutoff_time]

    @staticmethod
    def compute_rolling_stats(
        values: list[float],
        window_size: int = 10,
    ) -> dict:
        """Compute rolling statistics for a series.

        Args:
            values: List of numeric values
            window_size: How many recent values to use for stats

        Returns:
            Dictionary with mean, std, min, max
        """
        if not values:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}

        # Use last window_size values
        window = values[-window_size:] if len(values) >= window_size else values

        mean = sum(window) / len(window) if window else 0.0
        variance = sum((x - mean) ** 2 for x in window) / len(window) if len(window) > 1 else 0.0
        std = math.sqrt(variance)
        minimum = min(window) if window else 0.0
        maximum = max(window) if window else 0.0

        return {
            "mean": mean,
            "std": std,
            "min": minimum,
            "max": maximum,
            "count": len(window),
        }

    @staticmethod
    def detect_anomaly(
        current_value: float,
        rolling_mean: float,
        rolling_std: float,
        threshold: float = 3.0,
    ) -> bool:
        """Detect if value is anomalous using z-score.

        Args:
            current_value: Current value
            rolling_mean: Mean of rolling window
            rolling_std: Std of rolling window
            threshold: Z-score threshold (default 3 = ~99.7% confidence)

        Returns:
            True if value is anomalous
        """
        if rolling_std == 0:
            return False

        z_score = abs((current_value - rolling_mean) / rolling_std)
        return z_score > threshold
