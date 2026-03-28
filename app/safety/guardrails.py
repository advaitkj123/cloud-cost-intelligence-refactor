"""Safety guardrails: validate actions before execution.

- Tag filter: only resources tagged costintel-managed=true
- Cooldown: block repeat actions on the same resource/action too soon
- Dependency check: block changes that would break dependents
- Rollback: EBS snapshot before volume delete
- Circuit breaker: pause execution after too many failures
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from botocore.exceptions import ClientError
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.cloud.aws.client import AWSClientFactory, get_aws_client_factory
from app.core.config import get_settings
from app.models.audit_log import AuditLog, AuditStatus
from app.models.resource import Resource, ResourceStatus
from app.models.resource import ResourceType

logger = logging.getLogger(__name__)

MANAGED_TAG_KEY = "costintel-managed"
DEPENDS_ON_TAG_KEY = "costintel-depends-on"
SERVICE_CRITICAL_TAG_KEY = "costintel-service-critical"


def _parse_tags(tags_json: str) -> dict[str, Any]:
    if not tags_json or not tags_json.strip():
        return {}
    try:
        data = json.loads(tags_json)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _tag_bool(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def _parse_depends_on_list(tags: dict[str, Any]) -> list[str]:
    raw = tags.get(DEPENDS_ON_TAG_KEY)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                pass
        return [p.strip() for p in s.split(",") if p.strip()]
    return []


def _is_costintel_managed(resource: Resource) -> bool:
    tags = _parse_tags(resource.tags_json)
    return _tag_bool(tags.get(MANAGED_TAG_KEY))


def _is_service_critical(resource: Resource) -> bool:
    tags = _parse_tags(resource.tags_json)
    return _tag_bool(tags.get(SERVICE_CRITICAL_TAG_KEY))


def _ebs_volume_external_id(resource: Resource) -> bool:
    return bool(resource.external_id and resource.external_id.startswith("vol-"))


class CircuitBreakerState:
    """Sliding-window failure counter; circuit opens when failures exceed threshold."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        window_seconds: int,
    ) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._window = timedelta(seconds=max(1, window_seconds))
        self._failures: deque[datetime] = deque()
        self._lock = threading.Lock()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._window
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def is_open(self) -> bool:
        """True when the circuit is open (tripped) — callers should block execution."""
        with self._lock:
            now = self._now()
            self._prune(now)
            return len(self._failures) >= self._failure_threshold

    def record_failure(self) -> None:
        with self._lock:
            now = self._now()
            self._prune(now)
            self._failures.append(now)
            if len(self._failures) >= self._failure_threshold:
                logger.warning(
                    "Safety circuit breaker tripped (%s failures in %ss window)",
                    self._failure_threshold,
                    int(self._window.total_seconds()),
                )

    def record_success(self) -> None:
        with self._lock:
            self._failures.clear()


_circuit_breaker: CircuitBreakerState | None = None
_circuit_lock = threading.Lock()


def get_circuit_breaker() -> CircuitBreakerState:
    global _circuit_breaker
    with _circuit_lock:
        if _circuit_breaker is None:
            s = get_settings()
            _circuit_breaker = CircuitBreakerState(
                failure_threshold=s.safety_circuit_failure_threshold,
                window_seconds=s.safety_circuit_window_seconds,
            )
        return _circuit_breaker


def record_execution_outcome(success: bool) -> None:
    """Call after an execution attempt to feed the circuit breaker."""
    cb = get_circuit_breaker()
    if success:
        cb.record_success()
    else:
        cb.record_failure()


@dataclass
class SafetyResult:
    """Outcome of pre-execution safety validation."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    rollback_snapshot_id: str | None = None

    def add(self, ok: bool, message: str) -> None:
        if not ok:
            self.reasons.append(message)
            self.allowed = False


def _cooldown_blocks(
    db: Session,
    resource_id: int,
    action_type: str,
    cooldown_seconds: int,
) -> tuple[bool, str | None]:
    if cooldown_seconds <= 0:
        return False, None
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)
    stmt = (
        select(AuditLog)
        .where(
            and_(
                AuditLog.resource_id == resource_id,
                AuditLog.action_type == action_type,
                AuditLog.status == AuditStatus.SUCCESS,
                AuditLog.completed_at.is_not(None),
                AuditLog.completed_at >= cutoff,
            )
        )
        .order_by(AuditLog.completed_at.desc())
        .limit(1)
    )
    row = db.scalar(stmt)
    if row:
        return True, (
            f"Cooldown active: same action succeeded within {cooldown_seconds}s "
            f"(audit id {row.id})"
        )
    return False, None


def _active_dependents_block(
    db: Session,
    target: Resource,
) -> tuple[bool, str | None]:
    if not target.external_id:
        return False, None
    others = db.scalars(select(Resource).where(Resource.id != target.id)).all()
    blocking_statuses = {ResourceStatus.running, ResourceStatus.active}
    for r in others:
        tags = _parse_tags(r.tags_json)
        deps = _parse_depends_on_list(tags)
        if target.external_id not in deps:
            continue
        if r.status in blocking_statuses:
            return True, (
                f"Dependency check: resource {r.name!r} (id={r.id}) depends on "
                f"{target.external_id!r} and is still {r.status.value}"
            )
    return False, None


def rollback_required_for_delete(resource: Resource, action_type: str) -> bool:
    if action_type != "delete_volume":
        return False
    if resource.type == ResourceType.s3:
        return False
    return _ebs_volume_external_id(resource)


def create_ebs_rollback_snapshot(
    resource: Resource,
    client_factory: Optional[AWSClientFactory] = None,
) -> str:
    """Create an EBS snapshot for rollback before volume delete. Returns SnapshotId."""
    if not resource.external_id or not resource.external_id.startswith("vol-"):
        raise ValueError("create_ebs_rollback_snapshot requires an EBS volume id (vol-*)")
    factory = client_factory or get_aws_client_factory()
    ec2 = factory.ec2(region_name=resource.region)
    try:
        resp = ec2.create_snapshot(
            VolumeId=resource.external_id,
            Description=f"costintel rollback snapshot for {resource.external_id}",
            TagSpecifications=[
                {
                    "ResourceType": "snapshot",
                    "Tags": [
                        {"Key": "costintel-rollback-for", "Value": resource.external_id},
                        {"Key": "costintel-managed", "Value": "true"},
                    ],
                }
            ],
        )
        snap_id = resp["SnapshotId"]
        logger.info("Created rollback snapshot %s for volume %s", snap_id, resource.external_id)
        return snap_id
    except ClientError as e:
        logger.error("Failed to create rollback snapshot: %s", e)
        raise


def validate_before_execution(
    db: Session,
    resource: Resource,
    action_type: str,
    *,
    rollback_snapshot_id: str | None = None,
    dry_run: bool = False,
    skip_rollback_check: bool = False,
) -> SafetyResult:
    """Run all safety checks before executing an action. Returns aggregated result.

    Use ``skip_rollback_check=True`` to validate tag filter, cooldown, dependencies, and
    circuit breaker before creating a rollback snapshot for EBS deletes.
    """
    result = SafetyResult(allowed=True)
    settings = get_settings()

    if get_circuit_breaker().is_open():
        result.add(
            False,
            "Circuit breaker is open: too many recent failures; execution blocked",
        )
        return result

    if not _is_costintel_managed(resource):
        result.add(
            False,
            f"Tag filter: resource must have {MANAGED_TAG_KEY!r}=true in tags",
        )

    if _is_service_critical(resource) and action_type in ("delete_volume", "stop_instance"):
        result.add(
            False,
            f"Dependency check: {SERVICE_CRITICAL_TAG_KEY!r} blocks this action",
        )

    blocked, msg = _cooldown_blocks(
        db,
        resource.id,
        action_type,
        settings.safety_cooldown_seconds,
    )
    if blocked and msg:
        result.add(False, f"Cooldown: {msg}")

    blocked, msg = _active_dependents_block(db, resource)
    if blocked and msg:
        result.add(False, msg)

    if (
        not skip_rollback_check
        and rollback_required_for_delete(resource, action_type)
        and not dry_run
    ):
        if rollback_snapshot_id:
            result.rollback_snapshot_id = rollback_snapshot_id
        else:
            result.add(
                False,
                "Rollback: EBS delete requires a snapshot first (provide rollback_snapshot_id "
                "or call create_ebs_rollback_snapshot before delete)",
            )

    return result


__all__ = [
    "CircuitBreakerState",
    "DEPENDS_ON_TAG_KEY",
    "MANAGED_TAG_KEY",
    "SERVICE_CRITICAL_TAG_KEY",
    "SafetyResult",
    "create_ebs_rollback_snapshot",
    "get_circuit_breaker",
    "record_execution_outcome",
    "rollback_required_for_delete",
    "validate_before_execution",
]
