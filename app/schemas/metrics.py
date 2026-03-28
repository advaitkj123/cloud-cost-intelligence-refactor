from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MetricCreate(BaseModel):
    resource_id: int
    timestamp: datetime
    cpu_usage: float = Field(ge=0, le=100)
    memory_usage: float = Field(ge=0, le=100)
    requests: int = Field(ge=0)
    storage_used: float = Field(ge=0)
    network_in: float = Field(default=0.0, ge=0)
    network_out: float = Field(default=0.0, ge=0)


class MetricRead(MetricCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class MetricIngestResponse(BaseModel):
    metric_id: int
    cost_record_id: int
    anomaly_detected: bool
    action_executed: str | None = None
    action_status: str | None = None
    inference_queued: bool = False
    inference_job_id: str | None = None
