from dataclasses import dataclass

from app.core.config import get_settings
from app.models.actions import ActionType
from app.models.resource import Resource, ResourceType
from app.schemas.metrics import MetricCreate
from app.services.anomaly_detector import AnomalyResult

settings = get_settings()


@dataclass
class OptimizationDecision:
    should_act: bool
    action_type: ActionType | None
    reason: str
    estimated_savings: float


class DecisionEngine:
    def evaluate(
        self,
        resource: Resource,
        metric: MetricCreate,
        estimated_cost: float,
        anomaly_result: AnomalyResult,
    ) -> OptimizationDecision:
        if (
            resource.type == ResourceType.ec2
            and metric.cpu_usage < settings.low_cpu_threshold
            and estimated_cost > settings.cost_threshold_for_stop
        ):
            return OptimizationDecision(
                should_act=True,
                action_type=ActionType.stop_instance,
                reason="Low CPU utilization and elevated cost detected",
                estimated_savings=round(estimated_cost * 0.65, 4),
            )

        if resource.type == ResourceType.lambda_fn and (
            anomaly_result.is_anomaly or metric.requests > 10000
        ):
            return OptimizationDecision(
                should_act=True,
                action_type=ActionType.throttle_lambda,
                reason="Request spike or anomaly indicates lambda throttling is advisable",
                estimated_savings=round(estimated_cost * 0.35, 4),
            )

        if resource.type == ResourceType.s3 and metric.storage_used > 500:
            return OptimizationDecision(
                should_act=True,
                action_type=ActionType.cleanup_storage,
                reason="Storage growth suggests cleanup or lifecycle optimization",
                estimated_savings=round(estimated_cost * 0.25, 4),
            )

        return OptimizationDecision(
            should_act=False,
            action_type=None,
            reason="No optimization action recommended",
            estimated_savings=0.0,
        )
