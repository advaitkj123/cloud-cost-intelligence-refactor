from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.logger import logger

settings = get_settings()

try:  # pragma: no cover - dependency availability is environment specific
    import shap  # type: ignore
except Exception:  # pragma: no cover - graceful degradation
    shap = None


class ShapExplainer:
    """Generate frontend-ready SHAP explanations for anomaly records."""

    def explain_regression(
        self,
        *,
        model: Any,
        feature_names: list[str],
        feature_values: list[float],
        feature_display: dict[str, Any],
        max_features: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return ranked SHAP contributions for a single observation.

        Falls back to a deterministic zero-contribution payload when SHAP is not
        available so the API contract remains stable.
        """

        limit = max_features or settings.shap_top_features
        if not feature_names:
            return []

        if shap is None:
            logger.warning("SHAP library unavailable, returning fallback explainability payload")
            return self._fallback(feature_names, feature_display, limit)

        feature_matrix = np.asarray([feature_values], dtype=float)
        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(feature_matrix)
            if isinstance(shap_values, list):
                shap_values = shap_values[0]
            row_values = np.asarray(shap_values, dtype=float)[0]
        except Exception as exc:  # pragma: no cover - vendor-specific runtime guardrail
            logger.warning("Failed to compute SHAP values: %s", exc)
            return self._fallback(feature_names, feature_display, limit)

        ranked = sorted(
            zip(feature_names, row_values, strict=False),
            key=lambda item: abs(float(item[1])),
            reverse=True,
        )[:limit]

        payload: list[dict[str, Any]] = []
        for rank, (feature_name, contribution) in enumerate(ranked, start=1):
            payload.append(
                {
                    "feature": feature_name,
                    "feature_label": feature_name.replace("_", " ").title(),
                    "feature_value": feature_display.get(feature_name),
                    "contribution": round(float(contribution), 6),
                    "direction": "increase" if float(contribution) >= 0 else "decrease",
                    "impact_rank": rank,
                    "metadata": {"abs_contribution": round(abs(float(contribution)), 6)},
                }
            )
        return payload

    @staticmethod
    def _fallback(feature_names: list[str], feature_display: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        return [
            {
                "feature": feature_name,
                "feature_label": feature_name.replace("_", " ").title(),
                "feature_value": feature_display.get(feature_name),
                "contribution": 0.0,
                "direction": "increase",
                "impact_rank": index,
                "metadata": {"fallback": True},
            }
            for index, feature_name in enumerate(feature_names[:limit], start=1)
        ]
