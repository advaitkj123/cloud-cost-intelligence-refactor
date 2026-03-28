from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.db.repositories.action_repository import ActionRepository
from app.db.repositories.cost_repository import CostRecordRepository
from app.schemas.cost import CostSummaryResponse, CostTrendPoint, ResourceCostSummary

router = APIRouter()


@router.get("/cost", response_model=CostSummaryResponse)
def get_cost_summary(db: Session = Depends(get_db)) -> CostSummaryResponse:
    cost_repo = CostRecordRepository(db)
    action_repo = ActionRepository(db)

    total_cost = cost_repo.total_cost()
    total_savings = action_repo.total_savings()
    trend = [CostTrendPoint(timestamp=t, estimated_cost=c) for t, c in cost_repo.trend()]
    per_resource = [
        ResourceCostSummary(
            resource_id=resource_id,
            resource_name=resource_name,
            resource_type=resource_type,
            total_cost=total,
        )
        for resource_id, resource_name, resource_type, total in cost_repo.per_resource_totals()
    ]

    average_hourly_cost = sum(point.estimated_cost for point in trend) / len(trend) if trend else 0.0
    projected_monthly_cost = round(average_hourly_cost * 24 * 30, 2)

    return CostSummaryResponse(
        total_cost=round(total_cost, 2),
        total_savings=round(total_savings, 2),
        projected_monthly_cost=projected_monthly_cost,
        trend=trend,
        per_resource=per_resource,
    )
