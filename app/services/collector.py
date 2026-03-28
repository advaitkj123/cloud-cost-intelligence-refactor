from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import random
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from app.cloud.aws.client import AWSClientFactory, get_aws_client_factory
from app.cloud.aws.cloudwatch_service import AWSCloudWatchService, CloudWatchMetricPoint
from app.cloud.aws.ec2_service import EC2InstanceDescription
from app.cloud.aws.pricing_service import AWSPricingService
from app.core.config import get_settings
from app.core.logger import logger
from app.models.resource import Resource, ResourceType
from app.schemas.metrics import MetricCreate

settings = get_settings()


class AWSCollectorError(RuntimeError):
    """Raised when AWS collection cannot complete successfully."""


@dataclass(slots=True)
class CostUsageResult:
    start: str
    end: str
    amount_usd: float
    unit: str
    groups: list[dict[str, Any]]


class CloudMetricCollector:
    """Collect metrics and cost signals from simulated or AWS sources."""

    def __init__(self, client_factory: AWSClientFactory | None = None) -> None:
        self.client_factory = client_factory or get_aws_client_factory()
        self.aws_cloudwatch_service = AWSCloudWatchService(client_factory=self.client_factory)
        self.aws_pricing_service = AWSPricingService(client_factory=self.client_factory)

    def generate_metric(self, resource: Resource) -> MetricCreate:
        if resource.type == ResourceType.ec2:
            cpu = random.uniform(1, 95)
            memory = random.uniform(20, 90)
            requests = random.randint(100, 5000)
            storage = random.uniform(5, 50)
        elif resource.type == ResourceType.lambda_fn:
            cpu = random.uniform(5, 70)
            memory = random.uniform(20, 85)
            requests = random.randint(1000, 15000)
            storage = random.uniform(0.1, 5)
        else:
            cpu = random.uniform(0, 10)
            memory = random.uniform(10, 40)
            requests = random.randint(0, 300)
            storage = random.uniform(100, 1500)

        return MetricCreate(
            resource_id=resource.id,
            timestamp=datetime.now(UTC),
            cpu_usage=round(cpu, 2),
            memory_usage=round(memory, 2),
            requests=requests,
            storage_used=round(storage, 2),
            network_in=0.0,
            network_out=0.0,
        )

    def describe_instances(self, region_name: str | None = None) -> list[EC2InstanceDescription]:
        """Return EC2 inventory using the AWS singleton client with pagination."""

        region = region_name or self.client_factory.default_region
        client = self.client_factory.ec2(region_name=region)
        paginator = client.get_paginator("describe_instances")
        instances: list[EC2InstanceDescription] = []

        try:
            for page in paginator.paginate(PaginationConfig={"PageSize": 100}):
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        tags = {
                            tag["Key"]: tag["Value"]
                            for tag in instance.get("Tags", [])
                            if "Key" in tag and "Value" in tag
                        }
                        instances.append(
                            EC2InstanceDescription(
                                instance_id=instance["InstanceId"],
                                instance_type=instance.get("InstanceType", "unknown"),
                                state=instance.get("State", {}).get("Name", "unknown"),
                                region=region,
                                tags=tags,
                            )
                        )
        except (NoCredentialsError, ClientError, BotoCoreError) as exc:
            logger.exception("Failed to describe EC2 instances in %s: %s", region, exc)
            raise AWSCollectorError(f"Unable to describe EC2 instances in {region}") from exc

        logger.info("Discovered %s EC2 instances in %s", len(instances), region)
        return instances

    def get_cost_and_usage(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        granularity: str = "DAILY",
    ) -> list[CostUsageResult]:
        """Fetch AWS Cost Explorer data with pagination and resilient error handling."""

        resolved_end = end_date or datetime.now(UTC).date()
        resolved_start = start_date or (resolved_end - timedelta(days=7))
        client = self.client_factory.client("ce", region_name="us-east-1")
        next_token: str | None = None
        results: list[CostUsageResult] = []

        try:
            while True:
                payload: dict[str, Any] = {
                    "TimePeriod": {"Start": resolved_start.isoformat(), "End": resolved_end.isoformat()},
                    "Granularity": granularity,
                    "Metrics": ["UnblendedCost"],
                    "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
                }
                if next_token:
                    payload["NextPageToken"] = next_token
                response = client.get_cost_and_usage(**payload)
                for result_by_time in response.get("ResultsByTime", []):
                    total = result_by_time.get("Total", {}).get("UnblendedCost", {})
                    results.append(
                        CostUsageResult(
                            start=result_by_time.get("TimePeriod", {}).get("Start", ""),
                            end=result_by_time.get("TimePeriod", {}).get("End", ""),
                            amount_usd=float(total.get("Amount", 0.0)),
                            unit=total.get("Unit", "USD"),
                            groups=result_by_time.get("Groups", []),
                        )
                    )
                next_token = response.get("NextPageToken")
                if not next_token:
                    break
        except (NoCredentialsError, ClientError, BotoCoreError) as exc:
            logger.exception("Failed to fetch AWS cost and usage data: %s", exc)
            raise AWSCollectorError("Unable to fetch AWS cost and usage data") from exc

        logger.info("Fetched %s Cost Explorer windows", len(results))
        return results

    def fetch_aws_resources(self) -> list[EC2InstanceDescription]:
        return self.describe_instances(region_name=settings.aws_region)

    def fetch_aws_metrics(self, instance_id: str, region_name: str) -> list[CloudWatchMetricPoint]:
        return self.aws_cloudwatch_service.get_instance_metrics(
            instance_id=instance_id,
            region_name=region_name,
            lookback_minutes=settings.aws_metric_lookback_minutes,
            period_seconds=settings.aws_metric_period_seconds,
        )

    def get_aws_hourly_cost(self, instance_type: str, region_name: str) -> float:
        return self.aws_pricing_service.get_ec2_hourly_price(instance_type, region_name)
