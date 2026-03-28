"""ML Feature models for cost intelligence."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Feature(Base):
    """Engineered features for ML models."""

    __tablename__ = "features"
    __table_args__ = (
        Index("ix_features_resource_timestamp", "resource_id", "timestamp"),
        Index("ix_features_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Cost features
    cost_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_rolling_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_rolling_std: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Usage features
    cpu_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cpu_rolling_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cpu_rolling_std: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    memory_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    storage_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Network features
    network_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    network_in_rolling_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    network_out_rolling_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Aggregated metrics
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_rolling_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    request_rolling_std: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Service-specific
    service_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    efficiency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Time encoding (for time-series models)
    time_sin: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    time_cos: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Metadata
    metric_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_quality: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    resource = relationship("Resource", back_populates="features")
