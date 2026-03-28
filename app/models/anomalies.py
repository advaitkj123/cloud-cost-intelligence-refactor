"""Anomaly Detection Model.

Stores detected anomalies in the database for tracking and analysis.
Combines results from multiple detection methods: Isolation Forest, Prophet, Zombie Detector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, JSON as SQLJSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

json_type = JSON().with_variant(JSONB, "postgresql")


class Anomaly(Base):
    """Detected Anomaly Record - Result of hybrid anomaly detection."""

    __tablename__ = "anomalies"
    __table_args__ = (
        Index("ix_anomaly_resource_timestamp", "resource_id", "timestamp"),
        Index("ix_anomaly_type", "anomaly_type"),
        Index("ix_anomaly_detected_at", "detected_at"),
        Index("ix_anomaly_is_anomaly", "is_anomaly"),
    )

    # Primary keys and relationships
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # New detection fields (ML detection layer)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0-100
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Detection method scores
    isolation_forest_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prophet_is_anomaly: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    prophet_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zombie_is_idle: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    zombie_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Resource metrics  
    cost_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cpu_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    efficiency_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Legacy/existing fields
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    anomaly_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    detection_source: Mapped[str] = mapped_column(String(64), nullable=False, default="hybrid")
    expected_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_predicted: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_actual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shap_contributions: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type, nullable=False, default=list
    )

    # Metadata
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(json_type, nullable=True)
    recommendations: Mapped[list[str]] = mapped_column(json_type, nullable=False, default=list)
    alert_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Timestamps
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    resource = relationship("Resource", back_populates="anomalies")

    @property
    def cost_delta_computed(self) -> Optional[float]:
        """Compute cost delta from expected and actual."""
        if self.expected_cost is None or self.actual_cost is None:
            return None
        return round(self.actual_cost - self.expected_cost, 6)

    @property
    def resource_name(self) -> Optional[str]:
        """Get resource name."""
        return self.resource.name if self.resource is not None else None

    @property
    def resource_type(self) -> Optional[str]:
        """Get resource type."""
        if self.resource is None:
            return None
        return self.resource.type.value if hasattr(self.resource.type, 'value') else str(self.resource.type)

    @property
    def region(self) -> Optional[str]:
        """Get resource region."""
        return self.resource.region if self.resource is not None else None

    @property
    def instance_type(self) -> Optional[str]:
        """Get instance type."""
        return self.resource.instance_type if self.resource is not None else None

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "resource_type": self.resource_type,
            "is_anomaly": self.is_anomaly,
            "confidence": self.confidence,
            "anomaly_type": self.anomaly_type,
            "isolation_forest_score": self.isolation_forest_score,
            "prophet_is_anomaly": self.prophet_is_anomaly,
            "prophet_confidence": self.prophet_confidence,
            "zombie_is_idle": self.zombie_is_idle,
            "zombie_confidence": self.zombie_confidence,
            "cost_delta": self.cost_delta,
            "cpu_avg": self.cpu_avg,
            "efficiency_score": self.efficiency_score,
            "details": self.details,
            "recommendations": self.recommendations,
            "alert_sent": self.alert_sent,
            "acknowledged": self.acknowledged,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
