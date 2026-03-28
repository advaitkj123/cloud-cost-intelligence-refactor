"""XAI (Explainable AI) Layer for Anomaly Explanations.

Provides deterministic, human-readable explanations for:
- Isolation Forest anomalies (feature deviations)
- Prophet anomalies (time-series cost spikes)
- Zombie Detector findings (idle resources)
- Hybrid decisions (combined signals)
"""

from app.xai.explainer import XAIExplainer

__all__ = ["XAIExplainer"]
