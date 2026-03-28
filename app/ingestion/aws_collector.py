"""AWS resource collectors for ingesting cloud metrics."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.client import BaseClient
from botocore.exceptions import ClientError, NoCredentialsError

from app.core.logger import logger
from app.cloud.aws.client import AWSClientFactory


class AWSCollectorError(RuntimeError):
    """Raised when AWS collection cannot complete successfully."""


@dataclass(slots=True)
class NormalizedMetric:
    """Unified schema for cloud metrics."""

    resource_id: str
    resource_type: str
    region: str
    resource_name: str
    timestamp: datetime
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    network_in: float = 0.0
    network_out: float = 0.0
    storage_used: float = 0.0
    requests: int = 0
    extra_data: dict[str, Any] | None = None


class AWSCollectorBase(ABC):
    """Base class for AWS resource collectors with retry logic."""

    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 1  # seconds

    def __init__(self, client_factory: AWSClientFactory) -> None:
        self.client_factory = client_factory

    def _exponential_backoff_retry(self, attempt: int) -> None:
        """Apply exponential backoff between retries."""
        if attempt > 0:
            wait_time = self.RETRY_BACKOFF_BASE * (2**attempt) + (1 * attempt)
            logger.info(
                f"Retry attempt {attempt + 1}/{self.MAX_RETRIES} for {self.__class__.__name__}. "
                f"Waiting {wait_time}s..."
            )
            time.sleep(wait_time)

    def _execute_with_retry(self, func, *args, **kwargs) -> Any:
        """Execute function with exponential backoff retry."""
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except (ClientError, NoCredentialsError) as e:
                last_error = e
                logger.warning(
                    f"{self.__class__.__name__} attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )
                if attempt < self.MAX_RETRIES - 1:
                    self._exponential_backoff_retry(attempt)
            except Exception as e:
                logger.error(f"Unexpected error in {self.__class__.__name__}: {e}", exc_info=True)
                raise AWSCollectorError(f"Unexpected error: {e}") from e

        raise AWSCollectorError(
            f"{self.__class__.__name__} failed after {self.MAX_RETRIES} attempts: {last_error}"
        )

    @abstractmethod
    def collect(self, region: str = "us-east-1") -> list[NormalizedMetric]:
        """Collect metrics from AWS service."""
        pass

    def _validate_metrics(self, metrics: list[NormalizedMetric]) -> list[NormalizedMetric]:
        """Validate and filter empty/invalid metrics."""
        valid_metrics = []
        for metric in metrics:
            if metric is None:
                logger.warning("Skipping null metric")
                continue
            if not metric.resource_id or metric.resource_id.strip() == "":
                logger.warning(f"Skipping metric with empty resource_id: {metric}")
                continue
            valid_metrics.append(metric)

        logger.info(f"{self.__class__.__name__} validated {len(valid_metrics)}/{len(metrics)} metrics")
        return valid_metrics


class EC2Collector(AWSCollectorBase):
    """Collect metrics from EC2 instances."""

    def collect(self, region: str = "us-east-1") -> list[NormalizedMetric]:
        """Collect EC2 instance metadata and state."""
        logger.info(f"Collecting EC2 metrics from region: {region}")

        def _fetch() -> list[NormalizedMetric]:
            ec2_client = self.client_factory.ec2(region)
            metrics = []

            try:
                response = ec2_client.describe_instances(
                    Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}]
                )
            except ClientError as e:
                logger.error(f"Failed to describe EC2 instances: {e}", exc_info=True)
                raise

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    try:
                        instance_id = instance.get("InstanceId")
                        instance_type = instance.get("InstanceType", "unknown")
                        state = instance.get("State", {}).get("Name", "unknown")
                        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                        instance_name = tags.get("Name", instance_id)

                        # Fetch CPU metrics from CloudWatch
                        cw_client = self.client_factory.cloudwatch(region)
                        cw_response = cw_client.get_metric_statistics(
                            Namespace="AWS/EC2",
                            MetricName="CPUUtilization",
                            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                            StartTime=datetime.now(UTC) - timedelta(minutes=5),
                            EndTime=datetime.now(UTC),
                            Period=300,
                            Statistics=["Average"],
                        )

                        cpu_usage = 0.0
                        if cw_response.get("Datapoints"):
                            cpu_usage = cw_response["Datapoints"][-1].get("Average", 0.0)

                        metric = NormalizedMetric(
                            resource_id=instance_id,
                            resource_type="ec2",
                            region=region,
                            resource_name=instance_name,
                            timestamp=datetime.now(UTC),
                            cpu_usage=cpu_usage,
                            extra_data={
                                "instance_type": instance_type,
                                "state": state,
                                "tags": tags,
                            },
                        )
                        metrics.append(metric)
                        logger.debug(f"Collected EC2 metric: {instance_id} (CPU: {cpu_usage}%)")

                    except Exception as e:
                        logger.error(f"Error collecting metrics for instance {instance.get('InstanceId')}: {e}")
                        continue

            return metrics

        try:
            metrics = self._execute_with_retry(_fetch)
            return self._validate_metrics(metrics)
        except AWSCollectorError as e:
            logger.error(f"EC2Collector failed: {e}")
            return []


class CloudWatchCollector(AWSCollectorBase):
    """Collect metrics from CloudWatch."""

    def collect(self, region: str = "us-east-1") -> list[NormalizedMetric]:
        """Collect CloudWatch metrics including network statistics."""
        logger.info(f"Collecting CloudWatch metrics from region: {region}")

        def _fetch() -> list[NormalizedMetric]:
            ec2_client = self.client_factory.ec2(region)
            cw_client = self.client_factory.cloudwatch(region)
            metrics = []

            # Get all running instances
            instances_response = ec2_client.describe_instances(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            )

            for reservation in instances_response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    try:
                        instance_id = instance.get("InstanceId")
                        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                        instance_name = tags.get("Name", instance_id)

                        # Collect NetworkIn and NetworkOut
                        network_in = self._get_metric_value(
                            cw_client, instance_id, "NetworkIn"
                        )
                        network_out = self._get_metric_value(
                            cw_client, instance_id, "NetworkOut"
                        )

                        metric = NormalizedMetric(
                            resource_id=instance_id,
                            resource_type="ec2",
                            region=region,
                            resource_name=instance_name,
                            timestamp=datetime.now(UTC),
                            network_in=network_in,
                            network_out=network_out,
                        )
                        metrics.append(metric)
                        logger.debug(
                            f"Collected CloudWatch metrics: {instance_id} "
                            f"(NetworkIn: {network_in}, NetworkOut: {network_out})"
                        )

                    except Exception as e:
                        logger.error(f"Error collecting CloudWatch metrics for {instance.get('InstanceId')}: {e}")
                        continue

            return metrics

        try:
            metrics = self._execute_with_retry(_fetch)
            return self._validate_metrics(metrics)
        except AWSCollectorError as e:
            logger.error(f"CloudWatchCollector failed: {e}")
            return []

    def _get_metric_value(self, cw_client: BaseClient, instance_id: str, metric_name: str) -> float:
        """Get specific metric value from CloudWatch."""
        try:
            response = cw_client.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName=metric_name,
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=datetime.now(UTC) - timedelta(minutes=5),
                EndTime=datetime.now(UTC),
                Period=300,
                Statistics=["Sum", "Average"],
            )

            if response.get("Datapoints"):
                datapoint = response["Datapoints"][-1]
                return datapoint.get("Sum", datapoint.get("Average", 0.0))
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get {metric_name} metric: {e}")
            return 0.0


class S3Collector(AWSCollectorBase):
    """Collect metrics from S3 buckets."""

    def collect(self, region: str = "us-east-1") -> list[NormalizedMetric]:
        """Collect S3 bucket storage size."""
        logger.info(f"Collecting S3 metrics from region: {region}")

        def _fetch() -> list[NormalizedMetric]:
            s3_client = self.client_factory.client("s3")
            cw_client = self.client_factory.cloudwatch(region)
            metrics = []

            try:
                response = s3_client.list_buckets()
            except ClientError as e:
                logger.error(f"Failed to list S3 buckets: {e}", exc_info=True)
                raise

            for bucket in response.get("Buckets", []):
                try:
                    bucket_name = bucket.get("Name")

                    # Get bucket size from CloudWatch
                    storage_size = self._get_bucket_size(cw_client, bucket_name)

                    metric = NormalizedMetric(
                        resource_id=bucket_name,
                        resource_type="s3",
                        region=region,
                        resource_name=bucket_name,
                        timestamp=datetime.now(UTC),
                        storage_used=storage_size,
                    )
                    metrics.append(metric)
                    logger.debug(f"Collected S3 metric: {bucket_name} (Size: {storage_size} bytes)")

                except Exception as e:
                    logger.error(f"Error collecting metrics for bucket {bucket.get('Name')}: {e}")
                    continue

            return metrics

        try:
            metrics = self._execute_with_retry(_fetch)
            return self._validate_metrics(metrics)
        except AWSCollectorError as e:
            logger.error(f"S3Collector failed: {e}")
            return []

    def _get_bucket_size(self, cw_client: BaseClient, bucket_name: str) -> float:
        """Get S3 bucket size in bytes."""
        try:
            response = cw_client.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": bucket_name},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=datetime.now(UTC) - timedelta(days=1),
                EndTime=datetime.now(UTC),
                Period=86400,
                Statistics=["Average"],
            )

            if response.get("Datapoints"):
                return response["Datapoints"][-1].get("Average", 0.0)
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get S3 bucket size for {bucket_name}: {e}")
            return 0.0


class LambdaCollector(AWSCollectorBase):
    """Collect metrics from Lambda functions."""

    def collect(self, region: str = "us-east-1") -> list[NormalizedMetric]:
        """Collect Lambda function invocations and duration."""
        logger.info(f"Collecting Lambda metrics from region: {region}")

        def _fetch() -> list[NormalizedMetric]:
            lambda_client = self.client_factory.client("lambda", region)
            cw_client = self.client_factory.cloudwatch(region)
            metrics = []

            try:
                response = lambda_client.list_functions()
            except ClientError as e:
                logger.error(f"Failed to list Lambda functions: {e}", exc_info=True)
                raise

            for function in response.get("Functions", []):
                try:
                    function_name = function.get("FunctionName")
                    function_arn = function.get("FunctionArn")

                    # Get invocations and duration from CloudWatch
                    invocations = self._get_metric_value(cw_client, function_name, "Invocations")
                    duration = self._get_metric_value(cw_client, function_name, "Duration")

                    metric = NormalizedMetric(
                        resource_id=function_arn,
                        resource_type="lambda",
                        region=region,
                        resource_name=function_name,
                        timestamp=datetime.now(UTC),
                        requests=int(invocations),
                        extra_data={
                            "duration_ms": duration,
                            "runtime": function.get("Runtime"),
                            "memory_size": function.get("MemorySize"),
                        },
                    )
                    metrics.append(metric)
                    logger.debug(
                        f"Collected Lambda metric: {function_name} "
                        f"(Invocations: {invocations}, Duration: {duration}ms)"
                    )

                except Exception as e:
                    logger.error(f"Error collecting metrics for function {function.get('FunctionName')}: {e}")
                    continue

            return metrics

        try:
            metrics = self._execute_with_retry(_fetch)
            return self._validate_metrics(metrics)
        except AWSCollectorError as e:
            logger.error(f"LambdaCollector failed: {e}")
            return []

    def _get_metric_value(self, cw_client: BaseClient, function_name: str, metric_name: str) -> float:
        """Get specific metric value from CloudWatch."""
        try:
            response = cw_client.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName=metric_name,
                Dimensions=[{"Name": "FunctionName", "Value": function_name}],
                StartTime=datetime.now(UTC) - timedelta(minutes=5),
                EndTime=datetime.now(UTC),
                Period=300,
                Statistics=["Sum", "Average"],
            )

            if response.get("Datapoints"):
                datapoint = response["Datapoints"][-1]
                return datapoint.get("Sum", datapoint.get("Average", 0.0))
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get {metric_name} metric for {function_name}: {e}")
            return 0.0
