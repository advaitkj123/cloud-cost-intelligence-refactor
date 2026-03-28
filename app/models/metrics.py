from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (Index("ix_metrics_resource_timestamp", "resource_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cpu_usage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    memory_usage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    network_in: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    network_out: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    resource = relationship("Resource", back_populates="metrics")
