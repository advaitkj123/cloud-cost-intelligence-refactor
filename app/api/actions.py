from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.db.repositories import ActionRepository, CostRecordRepository, ResourceRepository
from app.schemas.actions import ActionCreate, ActionRead, ActionTriggerResponse
from app.services.optimizer import Optimizer

router = APIRouter()


@router.get("/actions", response_model=list[ActionRead])
def list_actions(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ActionRead]:
    repository = ActionRepository(db)
    return repository.list(limit=limit)


@router.post("/actions", response_model=ActionTriggerResponse)
def trigger_action(payload: ActionCreate, db: Session = Depends(get_db)) -> ActionTriggerResponse:
    resource_repo = ResourceRepository(db)
    cost_repo = CostRecordRepository(db)
    resource = resource_repo.get(payload.resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    latest_cost = cost_repo.latest_for_resource(resource.id)
    estimated_savings = round((latest_cost.estimated_cost if latest_cost else 0.0) * 0.5, 4)

    optimizer = Optimizer(ActionRepository(db))
    action_log, status = optimizer.execute(
        resource=resource,
        action_type=payload.action_type,
        estimated_savings=estimated_savings,
        dry_run=payload.dry_run,
    )
    db.commit()
    return ActionTriggerResponse(
        action_id=action_log.id,
        status=status,
        estimated_savings=action_log.estimated_savings,
    )
