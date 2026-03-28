from datetime import datetime

from pydantic import BaseModel


class AWSMetricRead(BaseModel):
    resource_id: int
    instance_id: str | None = None
    instance_type: str | None = None
    timestamp: datetime
    cpu_usage: float
    network_in: float
    network_out: float


class AWSSyncResponse(BaseModel):
    resources_synced: int
    metrics_ingested: int
    cost_records_created: int
    anomalies_detected: int
    actions_triggered: int
