from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.metrics import Metric
from app.models.resource import Resource


class MetricRepository:
    """Repository for metric lifecycle operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, metric: Metric) -> Metric:
        self.db.add(metric)
        self.db.flush()
        self.db.refresh(metric)
        return metric

    def get(self, metric_id: int) -> Metric | None:
        return self.db.get(Metric, metric_id)

    def list(self, limit: int = 100, resource_id: int | None = None) -> list[Metric]:
        stmt = select(Metric)
        if resource_id is not None:
            stmt = stmt.where(Metric.resource_id == resource_id)
        stmt = stmt.order_by(desc(Metric.timestamp)).limit(limit)
        return list(self.db.scalars(stmt))

    def list_for_provider(self, provider: str, limit: int = 100, resource_id: int | None = None) -> list[Metric]:
        stmt = select(Metric).join(Resource, Metric.resource_id == Resource.id).where(Resource.provider == provider)
        if resource_id is not None:
            stmt = stmt.where(Metric.resource_id == resource_id)
        stmt = stmt.order_by(desc(Metric.timestamp)).limit(limit)
        return list(self.db.scalars(stmt))

    def recent_for_resource(self, resource_id: int, limit: int = 200) -> list[Metric]:
        stmt = (
            select(Metric)
            .where(Metric.resource_id == resource_id)
            .order_by(desc(Metric.timestamp))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def latest_for_resource(self, resource_id: int) -> Metric | None:
        stmt = (
            select(Metric)
            .where(Metric.resource_id == resource_id)
            .order_by(desc(Metric.timestamp))
            .limit(1)
        )
        return self.db.scalar(stmt)
