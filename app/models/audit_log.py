"""Audit log model for tracking execution actions."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditStatus(str, Enum):
    """Status of audit log entry."""

    PENDING = "pending"  # Scheduled, not yet executed
    SUCCESS = "success"  # Action completed successfully
    FAILED = "failed"  # Action failed after retries
    RETRYING = "retrying"  # In retry attempt
    SKIPPED = "skipped"  # Skipped (e.g., dry-run)


class AuditLog(Base):
    """Track all execution actions and outcomes.

    Attributes:
        id: Unique identifier
        resource_id: Target resource
        action_type: Type of action (stop_instance, delete_volume, limit_lambda)
        status: Current status
        attempt: Current attempt number (1-3)
        max_attempts: Maximum retry attempts
        error_message: Error details if failed
        dry_run: Whether this was a dry-run simulation
        decision_id: Associated decision ID (optional)
        external_id: AWS resource ID
        region: AWS region
        timestamp: When action was logged
        completed_at: When action completed (null if still running)

        resource: Relationship to Resource
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_resource_timestamp", "resource_id", "timestamp"),
        Index("ix_audit_status_timestamp", "status", "timestamp"),
        Index("ix_audit_action_type", "action_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[AuditStatus] = mapped_column(
        SqlEnum(AuditStatus, name="audit_status"), nullable=False, default=AuditStatus.PENDING, index=True
    )
    attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(default=False)
    decision_id: Mapped[int | None] = mapped_column(nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    resource = relationship("Resource", foreign_keys=[resource_id])
