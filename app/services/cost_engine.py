from app.cloud.aws.pricing_service import AWSPricingService
from app.core.config import get_settings
from app.models.resource import Resource, ResourceType
from app.schemas.metrics import MetricCreate

settings = get_settings()


class CostEngine:
    def __init__(self) -> None:
        self.pricing_service = AWSPricingService()

    def resolve_cost_per_hour(
        self,
        resource: Resource,
        metric: MetricCreate,
        cost_per_hour: float | None = None,
    ) -> float:
        if cost_per_hour is not None:
            return round(cost_per_hour, 6)

        if resource.type == ResourceType.ec2 and resource.provider == "aws":
            instance_type = resource.instance_type or "m5.large"
            return round(self.pricing_service.get_ec2_hourly_price(instance_type, resource.region), 6)

        if resource.type == ResourceType.ec2:
            return round(settings.ec2_hourly_rate * max(metric.cpu_usage / 100, 0.15), 6)

        if resource.type == ResourceType.lambda_fn:
            requests_cost = (metric.requests / 1_000_000) * settings.lambda_request_cost_per_million
            estimated_duration_seconds = max(metric.memory_usage / 100, 0.1)
            memory_gb = 1.0
            duration_cost = estimated_duration_seconds * memory_gb * settings.lambda_duration_cost_per_gb_second
            return round(requests_cost + duration_cost, 6)

        if resource.type == ResourceType.s3:
            hourly_storage_rate = settings.s3_storage_cost_per_gb_month / (30 * 24)
            return round(hourly_storage_rate, 6)

        return 0.0

    def estimate_cost(
        self,
        resource: Resource,
        metric: MetricCreate,
        cost_per_hour: float | None = None,
        usage_hours: float = 1.0,
    ) -> float:
        effective_cost_per_hour = self.resolve_cost_per_hour(resource, metric, cost_per_hour=cost_per_hour)

        if resource.type == ResourceType.ec2 and resource.provider == "aws":
            if (resource.cloud_state or resource.status.value) not in {"running", "pending"}:
                return 0.0
            return self.pricing_service.estimate_cost(effective_cost_per_hour, usage_hours)

        if resource.type == ResourceType.ec2:
            return round(effective_cost_per_hour * usage_hours, 6)

        if resource.type == ResourceType.lambda_fn:
            return effective_cost_per_hour

        if resource.type == ResourceType.s3:
            return round(metric.storage_used * effective_cost_per_hour * usage_hours, 6)

        return 0.0
