from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ResourceType(str, Enum):
    ec2 = "ec2"
    lambda_fn = "lambda"
    s3 = "s3"


class ResourceStatus(str, Enum):
    running = "running"
    stopped = "stopped"
    throttled = "throttled"
    active = "active"


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    type: Mapped[ResourceType] = mapped_column(SqlEnum(ResourceType, name="resource_type"), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[ResourceStatus] = mapped_column(
        SqlEnum(ResourceStatus, name="resource_status"), nullable=False, default=ResourceStatus.running
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated", index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    instance_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cloud_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    metrics = relationship("Metric", back_populates="resource", cascade="all, delete-orphan")
    cost_records = relationship("CostRecord", back_populates="resource", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="resource", cascade="all, delete-orphan")
    actions = relationship("ActionLog", back_populates="resource", cascade="all, delete-orphan")
