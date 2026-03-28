"""System health monitoring and automation gating."""

from app.system_health.monitor import (
    SystemHealthReport,
    as_report,
    automation_may_run,
    ensure_health_evaluated,
    evaluate_system_health,
    record_inference_duration,
    record_pipeline_run,
)

__all__ = [
    "SystemHealthReport",
    "as_report",
    "automation_may_run",
    "ensure_health_evaluated",
    "evaluate_system_health",
    "record_inference_duration",
    "record_pipeline_run",
]
