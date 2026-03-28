from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CostRecord(Base):
    __tablename__ = "cost_records"
    __table_args__ = (Index("ix_cost_resource_timestamp", "resource_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False)
    cost_per_hour: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    usage_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    resource = relationship("Resource", back_populates="cost_records")
