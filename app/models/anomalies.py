from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

json_type = JSON().with_variant(JSONB, "postgresql")


class Anomaly(Base):
    """Persisted anomaly event enriched with explainability metadata."""

    __tablename__ = "anomalies"
    __table_args__ = (
        Index("ix_anomaly_resource_timestamp", "resource_id", "timestamp"),
        Index("ix_anomaly_detection_source", "detection_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    detection_source: Mapped[str] = mapped_column(String(64), nullable=False, default="hybrid")
    expected_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    shap_contributions: Mapped[list[dict[str, Any]]] = mapped_column(json_type, nullable=False, default=list)

    resource = relationship("Resource", back_populates="anomalies")

    @property
    def cost_delta(self) -> float | None:
        if self.expected_cost is None or self.actual_cost is None:
            return None
        return round(self.actual_cost - self.expected_cost, 6)

    @property
    def resource_name(self) -> str | None:
        return self.resource.name if self.resource is not None else None

    @property
    def resource_type(self) -> str | None:
        if self.resource is None:
            return None
        return self.resource.type.value

    @property
    def region(self) -> str | None:
        return self.resource.region if self.resource is not None else None

    @property
    def instance_type(self) -> str | None:
        return self.resource.instance_type if self.resource is not None else None
