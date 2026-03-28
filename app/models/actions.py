from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, Float, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ActionType(str, Enum):
    stop_instance = "stop_instance"
    throttle_lambda = "throttle_lambda"
    cleanup_storage = "cleanup_storage"


class ActionLog(Base):
    __tablename__ = "actions"
    __table_args__ = (Index("ix_action_resource_timestamp", "resource_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[ActionType] = mapped_column(SqlEnum(ActionType, name="action_type"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    estimated_savings: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    resource = relationship("Resource", back_populates="actions")
