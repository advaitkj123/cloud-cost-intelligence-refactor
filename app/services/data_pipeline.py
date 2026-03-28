"""End-to-end data pipeline: metrics → costs → features."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.logger import logger
from app.cost_engine.calculator import CostCalculator, CostEstimate
from app.db.repositories.cost_repository import CostRecordRepository
from app.db.repositories.feature_repository import FeatureRepository
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.feature_engineering.pipeline import FeatureAggregator, FeatureEngineer
from app.models.cost import CostRecord
from app.models.features import Feature
from app.models.metrics import Metric

if TYPE_CHECKING:
    pass


class DataPipeline:
    """Orchestrates the complete metrics → costs → features pipeline."""

    def __init__(self, db: Session):
        self.db = db
        self.metric_repo = MetricRepository(db)
        self.cost_repo = CostRecordRepository(db)
        self.feature_repo = FeatureRepository(db)
        self.resource_repo = ResourceRepository(db)
        self.cost_calculator = CostCalculator()

    def process_metrics_for_resource(self, resource_id: int) -> dict:
        """Process all pipeline steps for a single resource.

        Steps:
        1. Get recent metrics
        2. Calculate cost estimate
        3. Store cost record
        4. Engineer features
        5. Store feature record

        Args:
            resource_id: ID of resource to process

        Returns:
            Dictionary with processing results
        """
        results = {
            "resource_id": resource_id,
            "cost_calculated": False,
            "cost": 0.0,
            "features_engineered": False,
            "timestamp": datetime.now(UTC).isoformat(),
            "errors": [],
        }

        try:
            # Get resource
            resource = self.resource_repo.get(resource_id)
            if not resource:
                results["errors"].append(f"Resource {resource_id} not found")
                return results

            # Step 1: Get recent metrics (last 1 hour)
            recent_metrics = self._get_recent_metrics(resource_id, hours=1)
            if not recent_metrics:
                logger.debug(f"No recent metrics for resource {resource_id}")
                return results

            # Step 2: Calculate cost
            cost_estimate = self.cost_calculator.estimate_cost(
                resource_id=resource_id,
                resource_type=resource.type,
                metrics=recent_metrics,
            )
            results["cost_calculated"] = True
            results["cost"] = cost_estimate.estimated_cost

            # Step 3: Store cost record
            cost_record = CostRecord(
                resource_id=resource_id,
                timestamp=cost_estimate.timestamp,
                estimated_cost=cost_estimate.estimated_cost,
                cost_per_hour=cost_estimate.cost_per_hour,
                usage_hours=cost_estimate.usage_hours,
            )
            self.cost_repo.create(cost_record)
            logger.debug(f"Stored cost record: resource={resource_id}, cost=${cost_estimate.estimated_cost:.4f}")

            # Step 4: Get previous cost for delta
            prev_cost_record = self._get_prev_cost_record(resource_id)
            prev_cost = prev_cost_record.estimated_cost if prev_cost_record else cost_estimate.estimated_cost

            # Step 5: Get rolling metrics (7 days)
            rolling_metrics = self._get_rolling_metrics(resource_id, days=7)

            # Step 6: Engineer features
            engineer = FeatureEngineer(resource)
            feature = engineer.engineer_features(
                recent_metrics=recent_metrics,
                rolling_metrics=rolling_metrics,
                current_cost=cost_estimate.estimated_cost,
                prev_cost=prev_cost,
                timestamp=cost_estimate.timestamp,
            )
            results["features_engineered"] = True

            # Step 7: Store feature record
            self.feature_repo.create(feature)
            logger.debug(f"Stored feature record: resource={resource_id}, efficiency={feature.efficiency_score:.2f}")

            results["cost_breakdown"] = cost_estimate.breakdown

        except Exception as e:
            error_msg = f"Error processing resource {resource_id}: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)

        return results

    def process_all_resources(self) -> dict:
        """Process pipeline for all resources.

        Returns:
            Dictionary with aggregate results
        """
        logger.info("Starting data pipeline for all resources")

        results = {
            "total_resources": 0,
            "resources_processed": 0,
            "costs_calculated": 0,
            "features_engineered": 0,
            "errors": [],
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            # Get all resources
            resources = self.resource_repo.list_all()
            results["total_resources"] = len(resources)

            for resource in resources:
                try:
                    resource_result = self.process_metrics_for_resource(resource.id)

                    results["resources_processed"] += 1
                    if resource_result["cost_calculated"]:
                        results["costs_calculated"] += 1
                    if resource_result["features_engineered"]:
                        results["features_engineered"] += 1

                    if resource_result["errors"]:
                        results["errors"].extend(resource_result["errors"])

                except Exception as e:
                    error_msg = f"Error processing resource {resource.id}: {e}"
                    logger.error(error_msg, exc_info=True)
                    results["errors"].append(error_msg)

            # Commit all changes
            self.db.commit()
            logger.info(
                f"Data pipeline completed: {results['resources_processed']} resources processed, "
                f"{results['costs_calculated']} costs, {results['features_engineered']} features"
            )

        except Exception as e:
            self.db.rollback()
            error_msg = f"Data pipeline failed: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)

        return results

    def process_providers(self, providers: list[str] = None) -> dict:
        """Process pipeline for resources from specific providers.

        Args:
            providers: List of provider names (e.g., ['aws', 'simulated'])

        Returns:
            Dictionary with processing results
        """
        if providers is None:
            providers = ["aws", "simulated"]

        logger.info(f"Starting data pipeline for providers: {providers}")

        results = {
            "total_resources": 0,
            "resources_processed": 0,
            "costs_calculated": 0,
            "features_engineered": 0,
            "errors": [],
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            for provider in providers:
                # Get resources from this provider
                resources = self.resource_repo.list_by_provider(provider)
                results["total_resources"] += len(resources)

                for resource in resources:
                    try:
                        resource_result = self.process_metrics_for_resource(resource.id)

                        results["resources_processed"] += 1
                        if resource_result["cost_calculated"]:
                            results["costs_calculated"] += 1
                        if resource_result["features_engineered"]:
                            results["features_engineered"] += 1

                        if resource_result["errors"]:
                            results["errors"].extend(resource_result["errors"])

                    except Exception as e:
                        error_msg = f"Error processing resource {resource.id}: {e}"
                        logger.error(error_msg, exc_info=True)
                        results["errors"].append(error_msg)

            # Commit all changes
            self.db.commit()
            logger.info(
                f"Data pipeline completed: {results['resources_processed']} resources processed, "
                f"{results['costs_calculated']} costs, {results['features_engineered']} features"
            )

        except Exception as e:
            self.db.rollback()
            error_msg = f"Data pipeline failed: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)

        return results

    def _get_recent_metrics(self, resource_id: int, hours: int = 1) -> list[Metric]:
        """Get metrics from last N hours."""
        start_time = datetime.now(UTC) - timedelta(hours=hours)
        return self.metric_repo.list_by_hour_range(resource_id, start_time, datetime.now(UTC))

    def _get_rolling_metrics(self, resource_id: int, days: int = 7) -> list[Metric]:
        """Get metrics from last N days."""
        start_time = datetime.now(UTC) - timedelta(days=days)
        return self.metric_repo.list_by_hour_range(resource_id, start_time, datetime.now(UTC))

    def _get_prev_cost_record(self, resource_id: int) -> CostRecord | None:
        """Get the most recent cost record before now."""
        # Get latest cost record
        return self.cost_repo.latest_for_resource(resource_id)

    def get_pipeline_stats(self, days: int = 30) -> dict:
        """Get statistics about the pipeline's recent executions.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with stats
        """
        cutoff_time = datetime.now(UTC) - timedelta(days=days)

        # Get counts
        cost_records = self.db.query(CostRecord).filter(CostRecord.timestamp >= cutoff_time).all()
        features = self.db.query(Feature).filter(Feature.timestamp >= cutoff_time).all()

        return {
            "period_days": days,
            "cost_records_count": len(cost_records),
            "features_count": len(features),
            "total_cost_estimate": sum(c.estimated_cost for c in cost_records),
            "avg_cost_per_record": (
                sum(c.estimated_cost for c in cost_records) / len(cost_records)
                if cost_records
                else 0.0
            ),
        }

    def cleanup_old_records(self, days: int = 90) -> dict:
        """Delete old feature records for maintenance/storage efficiency.

        Args:
            days: Delete records older than this many days

        Returns:
            Dictionary with cleanup stats
        """
        logger.info(f"Cleaning up records older than {days} days")

        deleted = self.feature_repo.delete_older_than(days)
        self.db.commit()

        return {
            "deleted_feature_records": deleted,
            "timestamp": datetime.now(UTC).isoformat(),
        }
