from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.cloud.aws.client import AWSClientFactory, get_aws_client_factory


@dataclass(slots=True)
class CloudWatchMetricPoint:
    timestamp: datetime
    cpu_utilization: float
    network_in: float
    network_out: float
    period_seconds: int


class AWSCloudWatchService:
    def __init__(self, client_factory: AWSClientFactory | None = None) -> None:
        self.client_factory = client_factory or get_aws_client_factory()

    def get_instance_metrics(
        self,
        instance_id: str,
        region_name: str | None = None,
        lookback_minutes: int = 60,
        period_seconds: int = 300,
    ) -> list[CloudWatchMetricPoint]:
        region = region_name or self.client_factory.default_region
        client = self.client_factory.cloudwatch(region_name=region)
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(minutes=lookback_minutes)

        queries = [
            {
                "Id": "cpu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "CPUUtilization",
                        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    },
                    "Period": period_seconds,
                    "Stat": "Average",
                },
                "ReturnData": True,
            },
            {
                "Id": "networkin",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "NetworkIn",
                        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    },
                    "Period": period_seconds,
                    "Stat": "Sum",
                },
                "ReturnData": True,
            },
            {
                "Id": "networkout",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "NetworkOut",
                        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    },
                    "Period": period_seconds,
                    "Stat": "Sum",
                },
                "ReturnData": True,
            },
        ]

        response = client.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start_time,
            EndTime=end_time,
            ScanBy="TimestampAscending",
        )

        series: dict[datetime, dict[str, float]] = defaultdict(dict)
        for result in response.get("MetricDataResults", []):
            metric_id = result.get("Id", "")
            timestamps = result.get("Timestamps", [])
            values = result.get("Values", [])
            for timestamp, value in zip(timestamps, values, strict=False):
                series[timestamp][metric_id] = float(value)

        points: list[CloudWatchMetricPoint] = []
        for timestamp in sorted(series.keys()):
            values = series[timestamp]
            points.append(
                CloudWatchMetricPoint(
                    timestamp=timestamp,
                    cpu_utilization=round(values.get("cpu", 0.0), 4),
                    network_in=round(values.get("networkin", 0.0), 4),
                    network_out=round(values.get("networkout", 0.0), 4),
                    period_seconds=period_seconds,
                )
            )
        return points
