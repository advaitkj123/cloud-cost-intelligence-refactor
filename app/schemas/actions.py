from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.actions import ActionType


class ActionCreate(BaseModel):
    resource_id: int
    action_type: ActionType
    dry_run: bool = True


class ActionRead(BaseModel):
    id: int
    resource_id: int
    action_type: ActionType
    timestamp: datetime
    estimated_savings: float

    model_config = ConfigDict(from_attributes=True)


class ActionTriggerResponse(BaseModel):
    action_id: int
    status: str
    estimated_savings: float
