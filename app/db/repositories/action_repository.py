from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.actions import ActionLog


class ActionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, action: ActionLog) -> ActionLog:
        self.db.add(action)
        self.db.flush()
        self.db.refresh(action)
        return action

    def list(self, limit: int = 100) -> list[ActionLog]:
        stmt = select(ActionLog).order_by(desc(ActionLog.timestamp)).limit(limit)
        return list(self.db.scalars(stmt))

    def total_savings(self) -> float:
        return float(self.db.scalar(select(func.coalesce(func.sum(ActionLog.estimated_savings), 0.0))) or 0.0)
