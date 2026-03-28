"""Ingestion service for orchestrating cloud metric collection and storage."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.logger import logger
from app.ingestion.aws_collector import (
    EC2Collector,
    CloudWatchCollector,
    S3Collector,
    LambdaCollector,
    NormalizedMetric,
    AWSCollectorError,
)
from app.models.metrics import Metric
from app.models.resource import Resource, ResourceStatus, ResourceType
from app.db.repositories.metric_repository import MetricRepository
from app.db.repositories.resource_repository import ResourceRepository
from app.cloud.aws.client import AWSClientFactory

if TYPE_CHECKING:
    from app.db.session import SessionLocal


class IngestionService:
    """Orchestrates collection and storage of cloud metrics."""

    def __init__(self, db: Session, client_factory: AWSClientFactory | None = None) -> None:
        self.db = db
        self.client_factory = client_factory
        self.metric_repo = MetricRepository(db)
        self.resource_repo = ResourceRepository(db)

        # Initialize collectors
        self.ec2_collector = EC2Collector(client_factory or AWSClientFactory())
        self.cloudwatch_collector = CloudWatchCollector(client_factory or AWSClientFactory())
        self.s3_collector = S3Collector(client_factory or AWSClientFactory())
        self.lambda_collector = LambdaCollector(client_factory or AWSClientFactory())

    def run_ingestion_cycle(self, regions: list[str] | None = None) -> dict:
        """Execute a complete ingestion cycle across all collectors and regions.

        Args:
            regions: List of AWS regions to collect from (default: us-east-1)

        Returns:
            Dictionary with results: total metrics collected, resources updated, errors
        """
        if regions is None:
            regions = ["us-east-1"]

        logger.info(f"Starting ingestion cycle for regions: {regions}")
        results = {
            "total_metrics_collected": 0,
            "resources_created": 0,
            "resources_updated": 0,
            "metrics_stored": 0,
            "errors": [],
            "timestamp": datetime.now(UTC).isoformat(),
        }

        for region in regions:
            try:
                # Collect from EC2
                ec2_metrics = self._collect_and_store(
                    self.ec2_collector, region, results
                )

                # Collect from CloudWatch
                cw_metrics = self._collect_and_store(
                    self.cloudwatch_collector, region, results
                )

                # Collect from S3
                s3_metrics = self._collect_and_store(
                    self.s3_collector, region, results
                )

                # Collect from Lambda
                lambda_metrics = self._collect_and_store(
                    self.lambda_collector, region, results
                )

                logger.info(
                    f"Ingestion cycle completed for region {region}: "
                    f"EC2={len(ec2_metrics)}, CW={len(cw_metrics)}, "
                    f"S3={len(s3_metrics)}, Lambda={len(lambda_metrics)}"
                )

            except Exception as e:
                error_msg = f"Error during ingestion cycle for region {region}: {e}"
                logger.error(error_msg, exc_info=True)
                results["errors"].append(error_msg)

        # Commit all changes
        try:
            self.db.commit()
            logger.info("Database commit successful")
        except Exception as e:
            self.db.rollback()
            error_msg = f"Database commit failed: {e}"
            logger.error(error_msg, exc_info=True)
            results["errors"].append(error_msg)

        logger.info(
            f"Ingestion cycle finished. Results: {results['total_metrics_collected']} metrics, "
            f"{results['resources_created']} resources created, "
            f"{results['errors'].__len__()} errors"
        )
        return results

    def _collect_and_store(self, collector, region: str, results: dict) -> list[NormalizedMetric]:
        """Collect metrics using a specific collector and store in database.

        Args:
            collector: The collector instance to use
            region: AWS region to collect from
            results: Results dictionary to update

        Returns:
            List of collected metrics
        """
        try:
            metrics = collector.collect(region)
            results["total_metrics_collected"] += len(metrics)
            logger.debug(f"{collector.__class__.__name__} collected {len(metrics)} metrics from {region}")

            # Process and store each metric
            for metric in metrics:
                try:
                    self._store_metric(metric, region, results)
                except Exception as e:
                    error_msg = f"Failed to store metric for {metric.resource_id}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)

            return metrics

        except AWSCollectorError as e:
            error_msg = f"{collector.__class__.__name__} failed: {e}"
            logger.error(error_msg)
            results["errors"].append(error_msg)
            return []

    def _store_metric(self, normalized_metric: NormalizedMetric, region: str, results: dict) -> None:
        """Store a normalized metric in the database.

        Args:
            normalized_metric: The metric to store
            region: AWS region for the resource
            results: Results dictionary to update
        """
        # Get or create resource
        resource_type = ResourceType(normalized_metric.resource_type)
        
        resource = self.resource_repo.upsert_cloud_resource(
            name=normalized_metric.resource_name,
            resource_type=resource_type,
            region=region,
            status=ResourceStatus.running,
            provider="aws",
            external_id=normalized_metric.resource_id,
            tags={"collected": "true"},
        )

        if resource.id:
            # Track if this was a new resource
            existing = self.db.query(Resource).filter(
                Resource.external_id == normalized_metric.resource_id,
                Resource.provider == "aws",
            ).first()
            
            if existing and existing.created_at.timestamp() == datetime.now(UTC).timestamp():
                results["resources_created"] += 1
            else:
                results["resources_updated"] += 1

        # Create metric record
        metric = Metric(
            resource_id=resource.id,
            timestamp=normalized_metric.timestamp,
            cpu_usage=normalized_metric.cpu_usage,
            memory_usage=normalized_metric.memory_usage,
            network_in=normalized_metric.network_in,
            network_out=normalized_metric.network_out,
            storage_used=normalized_metric.storage_used,
            requests=normalized_metric.requests,
        )

        self.metric_repo.create(metric)
        results["metrics_stored"] += 1
        logger.debug(f"Stored metric for resource {resource.id} (name: {resource.name})")

    def ingest_region(self, region: str) -> dict:
        """Ingest metrics for a specific region.

        Args:
            region: AWS region to collect from

        Returns:
            Results dictionary
        """
        return self.run_ingestion_cycle([region])

    def ingest_all_regions(self, regions: list[str]) -> dict:
        """Ingest metrics for multiple regions.

        Args:
            regions: List of AWS regions to collect from

        Returns:
            Results dictionary
        """
        return self.run_ingestion_cycle(regions)
