"""System health: pipeline latency, ML inference time, execution success, missing data."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit_log import AuditLog, AuditStatus
from app.models.resource import Resource
from app.models.metrics import Metric

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_pipeline_latency_seconds: float | None = None
_last_pipeline_at: datetime | None = None
_inference_durations: deque[float] = deque(maxlen=100)

_automation_paused_by_health: bool = False
_last_evaluated_status: str | None = None
_health_cache_time: float = 0.0
_health_cache_report: dict[str, Any] | None = None

HealthStatus = Literal["healthy", "degraded", "unhealthy"]


def record_pipeline_run(duration_seconds: float) -> None:
    """Record end-to-end data pipeline duration (from scheduler or API)."""
    global _last_pipeline_latency_seconds, _last_pipeline_at
    with _lock:
        _last_pipeline_latency_seconds = max(0.0, float(duration_seconds))
        _last_pipeline_at = datetime.now(timezone.utc)


def record_inference_duration(duration_seconds: float) -> None:
    """Record a single ML inference job duration (anomaly + decision path)."""
    with _lock:
        _inference_durations.append(max(0.0, float(duration_seconds)))


def _avg_inference_seconds() -> float | None:
    with _lock:
        if not _inference_durations:
            return None
        return sum(_inference_durations) / len(_inference_durations)


def _snapshot_observability() -> dict[str, Any]:
    with _lock:
        lat = _last_pipeline_latency_seconds
        at = _last_pipeline_at.isoformat() if _last_pipeline_at else None
        last_at = _last_pipeline_at
        inf = list(_inference_durations)[-20:]
        inf_avg = sum(inf) / len(inf) if inf else None
        inf_n = len(_inference_durations)
    return {
        "pipeline_latency_seconds": lat,
        "pipeline_last_run_at": at,
        "pipeline_last_run_at_dt": last_at,
        "ml_inference_time_seconds_recent_avg": round(inf_avg, 4) if inf_avg is not None else None,
        "ml_inference_samples": inf_n,
    }


def _execution_stats(db: Session, lookback_hours: int) -> tuple[int, int]:
    """Returns (success_count, failed_count) for completed non-dry-run audits."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    stmt = select(
        func.coalesce(
            func.sum(case((AuditLog.status == AuditStatus.SUCCESS, 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((AuditLog.status == AuditStatus.FAILED, 1), else_=0)),
            0,
        ),
    ).where(
        AuditLog.completed_at.is_not(None),
        AuditLog.completed_at >= cutoff,
        AuditLog.dry_run.is_(False),
    )
    row = db.execute(stmt).one()
    success = int(row[0] or 0)
    failed = int(row[1] or 0)
    return success, failed


def _metric_ts_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _missing_data_count(db: Session, stale_hours: int) -> tuple[int, int]:
    """Returns (resources_without_fresh_metrics, total_resources)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    resources = db.scalars(select(Resource)).all()
    if not resources:
        return 0, 0
    missing = 0
    for r in resources:
        latest = db.scalar(
            select(Metric)
            .where(Metric.resource_id == r.id)
            .order_by(desc(Metric.timestamp))
            .limit(1)
        )
        if latest is None or _metric_ts_utc(latest.timestamp) < cutoff:
            missing += 1
    return missing, len(resources)


def evaluate_system_health(db: Session) -> dict[str, Any]:
    """Compute status, issues, and observability metrics."""
    global _automation_paused_by_health, _last_evaluated_status, _health_cache_report, _health_cache_time
    settings = get_settings()
    issues: list[str] = []
    degraded_hints: list[str] = []

    obs = _snapshot_observability()
    last_pipeline_at = obs.pop("pipeline_last_run_at_dt", None)

    success_n, failed_n = _execution_stats(db, settings.health_execution_lookback_hours)
    total_exec = success_n + failed_n
    if total_exec >= settings.health_execution_min_samples:
        rate = success_n / total_exec if total_exec else 0.0
        obs["execution_success_rate"] = round(rate, 4)
        obs["execution_samples"] = total_exec
        if rate < settings.health_execution_success_rate_min:
            issues.append(
                f"Execution success rate {rate:.0%} below minimum "
                f"{settings.health_execution_success_rate_min:.0%} "
                f"({success_n} ok / {total_exec} in {settings.health_execution_lookback_hours}h)"
            )
        elif rate < settings.health_execution_success_rate_min + 0.1:
            degraded_hints.append(f"Execution success rate elevated risk: {rate:.0%}")
    else:
        obs["execution_success_rate"] = None
        obs["execution_samples"] = total_exec
        if total_exec > 0:
            degraded_hints.append(
                f"Low execution sample count ({total_exec}) for success-rate signal"
            )

    missing, total_r = _missing_data_count(db, settings.health_missing_data_stale_hours)
    obs["missing_data_resource_count"] = missing
    obs["total_resources"] = total_r
    if total_r > 0:
        ratio = missing / total_r
        obs["missing_data_ratio"] = round(ratio, 4)
        if ratio > settings.health_missing_data_max_ratio:
            issues.append(
                f"Missing or stale metrics for {missing}/{total_r} resources "
                f"(>{settings.health_missing_data_stale_hours}h old)"
            )
        elif missing > 0:
            degraded_hints.append(
                f"Some resources lack fresh metrics ({missing}/{total_r})"
            )

    now = datetime.now(timezone.utc)
    if last_pipeline_at is None and total_r > 0:
        degraded_hints.append(
            "Pipeline has not recorded a run yet (metrics will populate after first cycle)"
        )
    elif last_pipeline_at is not None:
        age = (now - last_pipeline_at).total_seconds()
        obs["pipeline_age_seconds"] = round(age, 1)
        if age > settings.health_pipeline_stale_seconds:
            issues.append(
                f"Pipeline stale: last run {age:.0f}s ago (threshold {settings.health_pipeline_stale_seconds:.0f}s)"
            )
        elif age > settings.health_pipeline_stale_seconds * 0.7:
            degraded_hints.append(f"Pipeline run aging ({age:.0f}s since last run)")

    if _last_pipeline_latency_seconds is not None:
        lat = _last_pipeline_latency_seconds
        obs["pipeline_latency_seconds"] = round(lat, 3)
        if lat >= settings.health_pipeline_latency_critical_seconds:
            issues.append(
                f"Pipeline latency critical: {lat:.1f}s "
                f"(>={settings.health_pipeline_latency_critical_seconds}s)"
            )
        elif lat >= settings.health_pipeline_latency_warn_seconds:
            degraded_hints.append(
                f"Pipeline latency elevated: {lat:.1f}s"
            )

    inf_avg = _avg_inference_seconds()
    if inf_avg is not None:
        obs["ml_inference_time_seconds_recent_avg"] = round(inf_avg, 4)
        if inf_avg >= settings.health_inference_critical_seconds:
            issues.append(
                f"ML inference time critical: avg {inf_avg:.2f}s "
                f"(>={settings.health_inference_critical_seconds}s)"
            )
        elif inf_avg >= settings.health_inference_warn_seconds:
            degraded_hints.append(f"ML inference time elevated: avg {inf_avg:.2f}s")
    else:
        obs["ml_inference_time_seconds_recent_avg"] = None

    if issues:
        status: HealthStatus = "unhealthy"
    elif degraded_hints:
        status = "degraded"
    else:
        status = "healthy"

    out: dict[str, Any] = {
        "status": status,
        "issues": issues + degraded_hints,
        "metrics": obs,
        "automation_paused": status == "unhealthy",
    }

    prev = _last_evaluated_status
    if status == "unhealthy" and prev != "unhealthy":
        logger.error(
            "SYSTEM HEALTH ALERT: status=%s issues=%s — automation paused",
            status,
            issues,
        )
    elif status == "healthy" and prev == "unhealthy":
        logger.warning("SYSTEM HEALTH RECOVERED: automation resumed")

    with _lock:
        _automation_paused_by_health = status == "unhealthy"
        _health_cache_report = out
        _health_cache_time = time.monotonic()
    _last_evaluated_status = status

    return out


def ensure_health_evaluated(db: Session) -> dict[str, Any]:
    """Return cached health report, refreshing when cache expires."""
    global _health_cache_time, _health_cache_report
    settings = get_settings()
    now = time.monotonic()
    if _health_cache_report is not None and (now - _health_cache_time) < settings.health_eval_cache_seconds:
        return _health_cache_report
    return evaluate_system_health(db)


def automation_may_run(db: Session) -> bool:
    """True if settings allow auto-apply and system health does not pause automation."""
    if not get_settings().auto_apply_optimizations:
        return False
    ensure_health_evaluated(db)
    return not _automation_paused_by_health


def is_automation_paused_by_health() -> bool:
    """Whether the last evaluation marked automation paused (unhealthy)."""
    return _automation_paused_by_health


@dataclass
class SystemHealthReport:
    """Typed view of GET /system/health payload."""

    status: HealthStatus
    issues: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)
    automation_paused: bool = False


def as_report(d: dict[str, Any]) -> SystemHealthReport:
    return SystemHealthReport(
        status=d.get("status", "healthy"),
        issues=list(d.get("issues", [])),
        metrics=dict(d.get("metrics", {})),
        automation_paused=bool(d.get("automation_paused", False)),
    )


__all__ = [
    "SystemHealthReport",
    "as_report",
    "automation_may_run",
    "ensure_health_evaluated",
    "evaluate_system_health",
    "is_automation_paused_by_health",
    "record_inference_duration",
    "record_pipeline_run",
]
