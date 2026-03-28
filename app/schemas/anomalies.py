from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SHAPContribution(BaseModel):
    """Human-readable SHAP contribution payload for frontend rendering."""

    feature: str
    feature_label: str
    feature_value: str | float | int | None = None
    contribution: float
    direction: str
    impact_rank: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnomalyRead(BaseModel):
    id: int
    resource_id: int
    resource_name: str | None = None
    resource_type: str | None = None
    region: str | None = None
    instance_type: str | None = None
    timestamp: datetime
    anomaly_score: float
    reason: str
    detection_source: str
    expected_cost: float | None = None
    actual_cost: float | None = None
    cost_delta: float | None = None
    shap_contributions: list[SHAPContribution] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
