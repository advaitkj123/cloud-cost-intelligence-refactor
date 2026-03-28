"""Repository for feature lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.models.features import Feature


class FeatureRepository:
    """Repository for ML feature operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, feature: Feature) -> Feature:
        """Create a new feature record."""
        self.db.add(feature)
        self.db.flush()
        self.db.refresh(feature)
        return feature

    def bulk_create(self, features: list[Feature]) -> list[Feature]:
        """Create multiple feature records efficiently."""
        self.db.add_all(features)
        self.db.flush()
        return features

    def get(self, feature_id: int) -> Feature | None:
        """Get a single feature by ID."""
        return self.db.get(Feature, feature_id)

    def list_all(self, limit: int = 100, offset: int = 0) -> list[Feature]:
        """List all features with pagination."""
        stmt = select(Feature).order_by(desc(Feature.timestamp)).limit(limit).offset(offset)
        return list(self.db.scalars(stmt))

    def list_for_resource(self, resource_id: int, limit: int = 200, offset: int = 0) -> list[Feature]:
        """List features for a specific resource."""
        stmt = (
            select(Feature)
            .where(Feature.resource_id == resource_id)
            .order_by(desc(Feature.timestamp))
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt))

    def latest_for_resource(self, resource_id: int) -> Feature | None:
        """Get the latest feature record for a resource."""
        stmt = (
            select(Feature)
            .where(Feature.resource_id == resource_id)
            .order_by(desc(Feature.timestamp))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_recent(self, days: int = 7, limit: int = 1000) -> list[Feature]:
        """List features from the last N days."""
        cutoff_time = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(Feature)
            .where(Feature.timestamp >= cutoff_time)
            .order_by(desc(Feature.timestamp))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_by_hour_range(self, resource_id: int, start_time: datetime, end_time: datetime) -> list[Feature]:
        """List features within a time range."""
        stmt = (
            select(Feature)
            .where(
                and_(
                    Feature.resource_id == resource_id,
                    Feature.timestamp >= start_time,
                    Feature.timestamp <= end_time,
                )
            )
            .order_by(Feature.timestamp)
        )
        return list(self.db.scalars(stmt))

    def get_stats_for_resource(self, resource_id: int, days: int = 30) -> dict:
        """Get aggregated statistics for a resource over time period."""
        cutoff_time = datetime.now(UTC) - timedelta(days=days)
        stmt = select(
            func.count(Feature.id).label("total_features"),
            func.avg(Feature.cost_delta).label("avg_cost_delta"),
            func.avg(Feature.cpu_avg).label("avg_cpu"),
            func.avg(Feature.efficiency_score).label("avg_efficiency"),
            func.min(Feature.timestamp).label("earliest_timestamp"),
            func.max(Feature.timestamp).label("latest_timestamp"),
        ).where(
            and_(
                Feature.resource_id == resource_id,
                Feature.timestamp >= cutoff_time,
            )
        )

        result = self.db.execute(stmt).first()
        if not result:
            return {}

        return {
            "total_features": result.total_features or 0,
            "avg_cost_delta": float(result.avg_cost_delta or 0.0),
            "avg_cpu": float(result.avg_cpu or 0.0),
            "avg_efficiency": float(result.avg_efficiency or 0.0),
            "earliest_timestamp": result.earliest_timestamp,
            "latest_timestamp": result.latest_timestamp,
        }

    def delete_older_than(self, days: int) -> int:
        """Delete features older than N days (for maintenance)."""
        cutoff_time = datetime.now(UTC) - timedelta(days=days)
        stmt = select(Feature).where(Feature.timestamp < cutoff_time)
        features_to_delete = self.db.scalars(stmt).all()
        deleted_count = len(features_to_delete)

        for feature in features_to_delete:
            self.db.delete(feature)

        self.db.flush()
        return deleted_count
