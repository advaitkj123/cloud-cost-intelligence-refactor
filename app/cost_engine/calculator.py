"""Cost calculation engine for cloud resources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.core.logger import logger
from app.models.metrics import Metric
from app.models.resource import ResourceType

if TYPE_CHECKING:
    pass

settings = get_settings()


@dataclass(slots=True)
class CostEstimate:
    """Cost estimate for a resource."""

    resource_id: int
    resource_type: ResourceType
    timestamp: datetime
    estimated_cost: float
    cost_per_hour: float
    usage_hours: float
    breakdown: dict | None = None


class CostCalculator:
    """Calculates estimated costs for AWS resources based on metrics."""

    def __init__(self):
        self.ec2_hourly_rate = settings.ec2_hourly_rate
        self.lambda_request_cost_per_million = settings.lambda_request_cost_per_million
        self.lambda_duration_cost_per_gb_second = settings.lambda_duration_cost_per_gb_second
        self.s3_storage_cost_per_gb_month = settings.s3_storage_cost_per_gb_month

    def estimate_cost(
        self,
        resource_id: int,
        resource_type: ResourceType,
        metrics: list[Metric],
        timestamp: datetime | None = None,
    ) -> CostEstimate:
        """Estimate cost for a resource based on recent metrics.

        Args:
            resource_id: Resource ID
            resource_type: Type of resource (ec2, lambda, s3)
            metrics: List of metric records from last period
            timestamp: Timestamp for cost record (default: now UTC)

        Returns:
            CostEstimate object with breakdown
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        breakdown = {}

        if not metrics:
            logger.warning(f"No metrics available for cost calculation of resource {resource_id}")
            return CostEstimate(
                resource_id=resource_id,
                resource_type=resource_type,
                timestamp=timestamp,
                estimated_cost=0.0,
                cost_per_hour=0.0,
                usage_hours=0.0,
                breakdown=breakdown,
            )

        # Route to specific calculator
        if resource_type == ResourceType.ec2:
            return self._calculate_ec2_cost(resource_id, metrics, timestamp, breakdown)
        elif resource_type == ResourceType.lambda_fn:
            return self._calculate_lambda_cost(resource_id, metrics, timestamp, breakdown)
        elif resource_type == ResourceType.s3:
            return self._calculate_s3_cost(resource_id, metrics, timestamp, breakdown)
        else:
            logger.warning(f"Unknown resource type for cost calculation: {resource_type}")
            return CostEstimate(
                resource_id=resource_id,
                resource_type=resource_type,
                timestamp=timestamp,
                estimated_cost=0.0,
                cost_per_hour=0.0,
                usage_hours=0.0,
                breakdown=breakdown,
            )

    def _calculate_ec2_cost(
        self,
        resource_id: int,
        metrics: list[Metric],
        timestamp: datetime,
        breakdown: dict,
    ) -> CostEstimate:
        """Calculate cost for EC2 instance.

        Cost = (Hours Running) × Hourly Rate + Data Transfer

        Args:
            resource_id: EC2 instance ID
            metrics: List of metrics
            timestamp: Timestamp for cost
            breakdown: Dict to populate with cost details

        Returns:
            CostEstimate
        """
        # Assume hourly usage (1 hour per metric period)
        hours = len(metrics) * (settings.aws_metric_period_seconds / 3600)

        # EC2 instance cost
        instance_cost = hours * self.ec2_hourly_rate
        breakdown["instance_cost"] = instance_cost
        breakdown["hours"] = hours

        # Data transfer cost (network_in + network_out in GB)
        total_network_gb = sum(m.network_in + m.network_out for m in metrics) / (1024 ** 3)
        data_transfer_cost = total_network_gb * 0.02  # $0.02 per GB (approximate)
        breakdown["data_transfer_cost"] = data_transfer_cost
        breakdown["network_gb"] = total_network_gb

        total_cost = instance_cost + data_transfer_cost
        cost_per_hour = self.ec2_hourly_rate + (data_transfer_cost / max(hours, 1))

        logger.debug(
            f"EC2 cost (resource {resource_id}): instance=${instance_cost:.4f}, "
            f"transfer=${data_transfer_cost:.4f}, total=${total_cost:.4f}"
        )

        return CostEstimate(
            resource_id=resource_id,
            resource_type=ResourceType.ec2,
            timestamp=timestamp,
            estimated_cost=total_cost,
            cost_per_hour=cost_per_hour,
            usage_hours=hours,
            breakdown=breakdown,
        )

    def _calculate_lambda_cost(
        self,
        resource_id: int,
        metrics: list[Metric],
        timestamp: datetime,
        breakdown: dict,
    ) -> CostEstimate:
        """Calculate cost for Lambda function.

        Cost = (Invocations / 1,000,000) × $0.20 + (Duration GB-seconds) × Rate

        Args:
            resource_id: Lambda function ID
            metrics: List of metrics
            timestamp: Timestamp for cost
            breakdown: Dict to populate with cost details

        Returns:
            CostEstimate
        """
        # Request costs
        total_requests = sum(m.requests for m in metrics)
        request_cost = (total_requests / 1_000_000) * self.lambda_request_cost_per_million
        breakdown["request_cost"] = request_cost
        breakdown["total_requests"] = total_requests

        # Compute cost (approximation using CPU as proxy for memory usage)
        # Assume 512MB memory * CPU milliseconds
        total_cpu_seconds = sum(m.cpu_usage / 100 for m in metrics)  # Approximate compute seconds
        gb_seconds = (total_cpu_seconds * 0.5) / 1024  # 512MB = 0.5GB
        compute_cost = gb_seconds * self.lambda_duration_cost_per_gb_second
        breakdown["compute_cost"] = compute_cost
        breakdown["gb_seconds"] = gb_seconds

        total_cost = request_cost + compute_cost
        cost_per_hour = total_cost / max(len(metrics) * (settings.aws_metric_period_seconds / 3600), 1)

        logger.debug(
            f"Lambda cost (resource {resource_id}): requests=${request_cost:.4f}, "
            f"compute=${compute_cost:.4f}, total=${total_cost:.4f}"
        )

        return CostEstimate(
            resource_id=resource_id,
            resource_type=ResourceType.lambda_fn,
            timestamp=timestamp,
            estimated_cost=total_cost,
            cost_per_hour=cost_per_hour,
            usage_hours=len(metrics) * (settings.aws_metric_period_seconds / 3600),
            breakdown=breakdown,
        )

    def _calculate_s3_cost(
        self,
        resource_id: int,
        metrics: list[Metric],
        timestamp: datetime,
        breakdown: dict,
    ) -> CostEstimate:
        """Calculate cost for S3 bucket.

        Cost = Storage (GB-month) × $0.023 + Request costs

        Args:
            resource_id: S3 bucket ID
            metrics: List of metrics
            timestamp: Timestamp for cost
            breakdown: Dict to populate with cost details

        Returns:
            CostEstimate
        """
        # Get latest storage size (storage metrics are cumulative)
        latest_storage_bytes = metrics[-1].storage_used if metrics else 0.0
        storage_gb = latest_storage_bytes / (1024 ** 3)

        # Annualize for monthly rate (this is rough estimate)
        storage_cost_monthly = storage_gb * self.s3_storage_cost_per_gb_month
        breakdown["storage_cost_monthly"] = storage_cost_monthly
        breakdown["storage_gb"] = storage_gb

        # Request costs (GET: $0.0004/1000, PUT: $0.005/1000)
        total_requests = sum(m.requests for m in metrics)
        request_cost = (total_requests / 1000) * 0.0004  # Approximate as GETs
        breakdown["request_cost"] = request_cost
        breakdown["total_requests"] = total_requests

        # Estimate daily cost
        daily_cost = (storage_cost_monthly + request_cost) / 30
        total_cost = daily_cost * len(metrics) * (settings.aws_metric_period_seconds / 86400)

        logger.debug(
            f"S3 cost (resource {resource_id}): storage=${storage_cost_monthly:.4f}/month, "
            f"requests=${request_cost:.4f}, daily≈${daily_cost:.4f}"
        )

        return CostEstimate(
            resource_id=resource_id,
            resource_type=ResourceType.s3,
            timestamp=timestamp,
            estimated_cost=total_cost,
            cost_per_hour=total_cost / max(len(metrics) * (settings.aws_metric_period_seconds / 3600), 1),
            usage_hours=len(metrics) * (settings.aws_metric_period_seconds / 3600),
            breakdown=breakdown,
        )

    def project_monthly_cost(self, hourly_cost: float) -> float:
        """Project hourly cost to monthly."""
        return hourly_cost * 24 * 30

    def project_annual_cost(self, hourly_cost: float) -> float:
        """Project hourly cost to annual."""
        return hourly_cost * 24 * 365
