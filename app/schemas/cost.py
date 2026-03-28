from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CostRecordRead(BaseModel):
    id: int
    resource_id: int
    timestamp: datetime
    estimated_cost: float

    model_config = ConfigDict(from_attributes=True)


class CostTrendPoint(BaseModel):
    timestamp: datetime
    estimated_cost: float


class ResourceCostSummary(BaseModel):
    resource_id: int
    resource_name: str
    resource_type: str
    total_cost: float


class CostSummaryResponse(BaseModel):
    total_cost: float
    total_savings: float
    projected_monthly_cost: float
    trend: list[CostTrendPoint]
    per_resource: list[ResourceCostSummary]
