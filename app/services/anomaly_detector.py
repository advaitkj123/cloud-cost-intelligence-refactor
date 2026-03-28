from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestRegressor

from app.core.config import get_settings
from app.core.logger import logger
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.metric_repository import MetricRepository
from app.models.resource import Resource
from app.schemas.metrics import MetricCreate
from app.services.shap_explainer import ShapExplainer

settings = get_settings()

try:  # pragma: no cover - dependency availability varies by environment
    from xgboost import XGBRegressor
except Exception:  # pragma: no cover - graceful degradation
    XGBRegressor = RandomForestRegressor  # type: ignore[assignment]


@dataclass(slots=True)
class FeatureRow:
    vector: list[float]
    display: dict[str, Any]


@dataclass(slots=True)
class AnomalyResult:
    is_anomaly: bool
    score: float
    reason: str
    detection_source: str
    expected_cost: float | None = None
    actual_cost: float | None = None
    shap_contributions: list[dict[str, Any]] = field(default_factory=list)


class AnomalyDetector:
    """Hybrid anomaly detector using regression residuals and drift scoring."""

    FEATURE_NAMES = [
        "cpu_usage",
        "memory_usage",
        "requests",
        "storage_used",
        "network_in",
        "network_out",
        "time_of_day",
        "day_of_week",
        "is_weekend",
        "request_density",
        "storage_pressure",
        "region_code",
        "resource_type_code",
        "instance_family_code",
    ]

    def __init__(
        self,
        metric_repository: MetricRepository,
        cost_repository: CostRecordRepository,
        shap_explainer: ShapExplainer | None = None,
    ):
        self.metric_repository = metric_repository
        self.cost_repository = cost_repository
        self.shap_explainer = shap_explainer or ShapExplainer()

    def detect(self, resource: Resource, metric: MetricCreate, estimated_cost: float) -> AnomalyResult:
        training_rows = self._build_training_rows(resource=resource, metric=metric, estimated_cost=estimated_cost)
        current_row = self._build_feature_row(resource=resource, metric=metric)
        actual_cost = round(float(estimated_cost), 6)

        if len(training_rows) < settings.anomaly_min_training_points:
            return self._rule_based_fallback(training_rows=training_rows, current_row=current_row, actual_cost=actual_cost)

        x_train = np.asarray([row.vector for row, _ in training_rows], dtype=float)
        y_train = np.asarray([cost for _, cost in training_rows], dtype=float)
        x_current = np.asarray([current_row.vector], dtype=float)

        regressor = self._build_regressor()
        regressor.fit(x_train, y_train)
        expected_cost = max(float(regressor.predict(x_current)[0]), 0.0)

        isolation_forest = IsolationForest(
            contamination=settings.isolation_forest_contamination,
            random_state=42,
            n_estimators=300,
        )
        isolation_forest.fit(x_train)
        isolation_prediction = int(isolation_forest.predict(x_current)[0])
        drift_score = float(-isolation_forest.decision_function(x_current)[0])

        residual = abs(actual_cost - expected_cost)
        baseline_cost = max(abs(expected_cost), float(np.median(y_train)), 0.01)
        residual_ratio = residual / baseline_cost
        drift_flag = isolation_prediction == -1 or drift_score >= settings.anomaly_drift_score_threshold
        regression_flag = residual_ratio >= settings.anomaly_residual_ratio_threshold
        high_residual_flag = residual_ratio >= settings.anomaly_high_residual_ratio_threshold
        request_spike_flag = self._is_request_spike(metric, training_rows)
        cpu_spike_flag = self._is_cpu_spike(metric, training_rows)

        is_anomaly = (drift_flag and regression_flag) or high_residual_flag or request_spike_flag or cpu_spike_flag
        normalized_drift = min(drift_score / max(settings.anomaly_drift_score_threshold, 0.001), 2.0) / 2.0
        normalized_residual = min(residual_ratio, 2.0) / 2.0
        heuristic_bonus = 0.1 if request_spike_flag else 0.0
        heuristic_bonus += 0.1 if cpu_spike_flag else 0.0
        score = round(min(1.0, normalized_drift * 0.45 + normalized_residual * 0.45 + heuristic_bonus), 4)

        shap_contributions = (
            self.shap_explainer.explain_regression(
                model=regressor,
                feature_names=self.FEATURE_NAMES,
                feature_values=current_row.vector,
                feature_display=current_row.display,
            )
            if is_anomaly
            else []
        )

        reasons: list[str] = []
        if regression_flag:
            reasons.append(
                f"Actual cost ${actual_cost:.4f} deviated from expected baseline ${expected_cost:.4f} by {residual_ratio * 100:.1f}%"
            )
        if drift_flag:
            reasons.append(f"Isolation Forest detected drift with score {drift_score:.4f}")
        if request_spike_flag:
            reasons.append("Request volume spiked materially above recent baseline")
        if cpu_spike_flag:
            reasons.append("CPU utilization deviated materially from the recent operating envelope")
        if shap_contributions:
            top_driver = shap_contributions[0]
            reasons.append(
                f"Top driver: {top_driver['feature_label']}={top_driver.get('feature_value')} ({top_driver['direction']})"
            )
        if not reasons:
            reasons.append("Hybrid regression and drift detectors found behavior within the normal operating range")

        detection_source = self._resolve_detection_source(
            drift_flag=drift_flag,
            regression_flag=regression_flag or high_residual_flag,
            rule_flag=request_spike_flag or cpu_spike_flag,
        )

        return AnomalyResult(
            is_anomaly=is_anomaly and score >= settings.anomaly_score_threshold,
            score=score,
            reason="; ".join(reasons),
            detection_source=detection_source,
            expected_cost=round(expected_cost, 6),
            actual_cost=actual_cost,
            shap_contributions=shap_contributions,
        )

    def _build_training_rows(
        self,
        *,
        resource: Resource,
        metric: MetricCreate,
        estimated_cost: float,
    ) -> list[tuple[FeatureRow, float]]:
        rows: list[tuple[FeatureRow, float]] = []
        if hasattr(self.cost_repository, "recent_training_rows"):
            for historical_resource, historical_metric, historical_cost in self.cost_repository.recent_training_rows(
                limit=settings.default_metric_window * 5
            ):
                rows.append(
                    (
                        self._build_feature_row(resource=historical_resource, metric=historical_metric),
                        float(historical_cost.estimated_cost),
                    )
                )
            if rows:
                return rows

        historical_metrics = list(reversed(self.metric_repository.recent_for_resource(resource.id, limit=settings.default_metric_window)))
        historical_costs = list(
            reversed(self.cost_repository.recent_for_resource(resource.id, limit=max(len(historical_metrics), 1)))
        )
        for index, metric_item in enumerate(historical_metrics):
            cost_value = historical_costs[index].estimated_cost if index < len(historical_costs) else estimated_cost
            rows.append((self._build_feature_row(resource=resource, metric=metric_item), float(cost_value)))
        return rows

    def _build_feature_row(self, *, resource: Resource, metric: Any) -> FeatureRow:
        timestamp = getattr(metric, "timestamp")
        time_of_day = float(timestamp.hour)
        day_of_week = float(timestamp.weekday())
        requests = float(getattr(metric, "requests", 0.0))
        cpu_usage = float(getattr(metric, "cpu_usage", 0.0))
        storage_used = float(getattr(metric, "storage_used", 0.0))
        region = resource.region or "unknown"
        resource_type = resource.type.value
        instance_family = (resource.instance_type or "generic").split(".")[0]
        region_code = float(self._stable_code(region))
        resource_type_code = float(self._stable_code(resource_type))
        instance_family_code = float(self._stable_code(instance_family))

        display = {
            "cpu_usage": round(cpu_usage, 4),
            "memory_usage": round(float(getattr(metric, "memory_usage", 0.0)), 4),
            "requests": int(requests),
            "storage_used": round(storage_used, 4),
            "network_in": round(float(getattr(metric, "network_in", 0.0)), 4),
            "network_out": round(float(getattr(metric, "network_out", 0.0)), 4),
            "time_of_day": int(time_of_day),
            "day_of_week": int(day_of_week),
            "is_weekend": int(day_of_week >= 5),
            "request_density": round(requests / max(cpu_usage, 1.0), 4),
            "storage_pressure": round(storage_used / max(float(getattr(metric, "memory_usage", 0.0)), 1.0), 4),
            "region_code": region,
            "resource_type_code": resource_type,
            "instance_family_code": instance_family,
        }
        vector = [
            cpu_usage,
            float(getattr(metric, "memory_usage", 0.0)),
            requests,
            storage_used,
            float(getattr(metric, "network_in", 0.0)),
            float(getattr(metric, "network_out", 0.0)),
            time_of_day,
            day_of_week,
            float(day_of_week >= 5),
            float(display["request_density"]),
            float(display["storage_pressure"]),
            region_code,
            resource_type_code,
            instance_family_code,
        ]
        return FeatureRow(vector=vector, display=display)

    def _build_regressor(self):
        try:
            return XGBRegressor(
                n_estimators=settings.xgboost_n_estimators,
                learning_rate=settings.xgboost_learning_rate,
                max_depth=settings.xgboost_max_depth,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="reg:squarederror",
                random_state=42,
            )
        except TypeError:  # pragma: no cover - fallback estimator signature
            logger.warning("XGBoost unavailable, falling back to RandomForestRegressor")
            return XGBRegressor(n_estimators=200, random_state=42)

    def _rule_based_fallback(
        self,
        *,
        training_rows: list[tuple[FeatureRow, float]],
        current_row: FeatureRow,
        actual_cost: float,
    ) -> AnomalyResult:
        recent_costs = [cost for _, cost in training_rows] or [actual_cost]
        expected_cost = float(mean(recent_costs))
        residual_ratio = abs(actual_cost - expected_cost) / max(expected_cost, 0.01)
        request_values = [float(row.display["requests"]) for row, _ in training_rows] or [0.0]
        cpu_values = [float(row.display["cpu_usage"]) for row, _ in training_rows] or [0.0]
        request_spike = float(current_row.display["requests"]) > mean(request_values) * settings.high_request_spike_multiplier
        cpu_spike = float(current_row.display["cpu_usage"]) > max(mean(cpu_values) * 2.2, 90.0)
        is_anomaly = residual_ratio >= settings.anomaly_high_residual_ratio_threshold or request_spike or cpu_spike
        reasons = ["Insufficient model history, using fallback heuristics"]
        if residual_ratio >= settings.anomaly_high_residual_ratio_threshold:
            reasons.append(f"Observed cost ${actual_cost:.4f} exceeded rolling baseline ${expected_cost:.4f}")
        if request_spike:
            reasons.append("Request volume spiked above the fallback threshold")
        if cpu_spike:
            reasons.append("CPU utilization spiked above the fallback threshold")
        return AnomalyResult(
            is_anomaly=is_anomaly,
            score=round(min(1.0, residual_ratio + (0.2 if request_spike else 0.0) + (0.2 if cpu_spike else 0.0)), 4),
            reason="; ".join(reasons),
            detection_source="fallback-rules",
            expected_cost=round(expected_cost, 6),
            actual_cost=actual_cost,
            shap_contributions=[],
        )

    @staticmethod
    def _is_request_spike(metric: MetricCreate, training_rows: list[tuple[FeatureRow, float]]) -> bool:
        recent_requests = [float(row.display["requests"]) for row, _ in training_rows[-25:]]
        if not recent_requests:
            return False
        return metric.requests > mean(recent_requests) * settings.high_request_spike_multiplier

    @staticmethod
    def _is_cpu_spike(metric: MetricCreate, training_rows: list[tuple[FeatureRow, float]]) -> bool:
        recent_cpu = [float(row.display["cpu_usage"]) for row, _ in training_rows[-25:]]
        if not recent_cpu:
            return False
        return metric.cpu_usage > max(mean(recent_cpu) * 2.2, 90.0)

    @staticmethod
    def _resolve_detection_source(*, drift_flag: bool, regression_flag: bool, rule_flag: bool) -> str:
        components: list[str] = []
        if regression_flag:
            components.append("xgboost-regression")
        if drift_flag:
            components.append("isolation-forest")
        if rule_flag:
            components.append("heuristics")
        return "+".join(components) if components else "normal"

    @staticmethod
    def _stable_code(value: str) -> int:
        return sum(ord(char) for char in value) % 997
