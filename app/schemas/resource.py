from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.resource import ResourceStatus, ResourceType


class ResourceBase(BaseModel):
    name: str
    type: ResourceType
    region: str
    status: ResourceStatus
    provider: str = "simulated"
    external_id: str | None = None
    instance_type: str | None = None
    cloud_state: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ResourceCreate(ResourceBase):
    pass


class ResourceRead(ResourceBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResourceWithLatest(ResourceRead):
    latest_cost: float | None = None
    cost_per_hour: float | None = None
    latest_cpu: float | None = None
    latest_memory: float | None = None
    latest_requests: int | None = None
    latest_network_in: float | None = None
    latest_network_out: float | None = None
