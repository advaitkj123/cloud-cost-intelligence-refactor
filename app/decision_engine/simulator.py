"""Simulation Engine - Evaluate action outcomes.

Simulates the impact of potential actions:
- stop_instance: Reduces resource to near-zero (still incurs storage/data costs)
- scale_down: Reduces resource by 50% (for scalable resources like EC2)
- delete_resource: Complete removal (includes cost and risk of data loss)
- do_nothing: Baseline for comparison

For each action calculates:
- Cost savings: current_cost - new_cost
- Carbon reduction: based on usage reduction
- Risk: criticality × (1 - confidence) × usage_factor
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

from sqlalchemy.orm import Session

from app.models.anomalies import Anomaly
from app.models.cost import CostRecord
from app.models.features import Feature
from app.models.resource import Resource, ResourceType

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Result of simulating a single action."""

    action: str
    cost_saving: float  # dollars/month
    carbon_reduction: float  # kg CO2
    risk_score: float  # 0-100
    details: dict = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = asdict(self)
        if self.details is None:
            result["details"] = {}
        return result


class SimulationEngine:
    """Simulation engine for evaluating action outcomes.
    
    Calculates cost savings, carbon reduction, and risk for each potential action.
    """

    # Carbon emissions per resource type (kg CO2 per 10 USD of hourly cost)
    # Based on average cloud provider energy intensity
    CARBON_INTENSITY = {
        ResourceType.ec2: 0.8,  # EC2 highest carbon footprint (compute)
        ResourceType.lambda_fn: 0.3,  # Lambda lower (serverless, optimized)
        ResourceType.s3: 0.1,  # S3 lowest (storage, less energy-intensive)
    }

    # Action parameters: (usage_reduction_pct, is_reversible)
    ACTION_PARAMS = {
        "do_nothing": (0.0, True),  # No change
        "stop_instance": (0.95, True),  # 95% cost reduction (storage remains ~5%)
        "scale_down": (0.50, True),  # 50% cost reduction (for scalable resources)
        "delete_resource": (1.0, False),  # 100% cost reduction (irreversible)
    }

    def __init__(self):
        """Initialize Simulation Engine."""
        self.logger = logging.getLogger(__name__)

    def simulate_actions(
        self,
        db: Session,
        resource: Resource,
        anomaly: Anomaly,
        current_feature: Feature,
    ) -> list[SimulationResult]:
        """Simulate all potential actions for a resource.
        
        Args:
            db: Database session
            resource: Resource record
            anomaly: Anomaly that triggered simulation
            current_feature: Current feature data for resource
            
        Returns:
            List of SimulationResult objects, one per action
        """
        logger.debug(f"Simulating actions for resource {resource.id}")

        # Get current cost data
        current_monthly_cost = self._get_monthly_cost(db, resource)
        current_usage = self._calculate_usage_factor(current_feature)

        # Derive criticality from resource type and usage
        criticality = self._calculate_criticality(resource, current_monthly_cost, current_usage)

        # Get confidence from anomaly
        confidence = anomaly.confidence / 100.0  # Normalize to 0-1

        results = []
        for action in ["do_nothing", "stop_instance", "scale_down", "delete_resource"]:
            # Skip scale_down for non-scalable resources
            if action == "scale_down" and resource.type == ResourceType.s3:
                continue

            result = self._simulate_action(
                action=action,
                resource=resource,
                current_monthly_cost=current_monthly_cost,
                current_usage=current_usage,
                criticality=criticality,
                confidence=confidence,
                feature=current_feature,
            )
            results.append(result)

        logger.debug(f"Generated {len(results)} simulation results for resource {resource.id}")
        return results

    def _simulate_action(
        self,
        action: str,
        resource: Resource,
        current_monthly_cost: float,
        current_usage: float,
        criticality: float,
        confidence: float,
        feature: Feature,
    ) -> SimulationResult:
        """Simulate a single action.
        
        Args:
            action: Action name
            resource: Resource being acted upon
            current_monthly_cost: Current monthly cost in dollars
            current_usage: Current usage factor (0-1)
            criticality: Criticality score (0-1)
            confidence: Anomaly confidence (0-1)
            feature: Current feature data
            
        Returns:
            SimulationResult with cost, carbon, and risk calculations
        """
        # Get action parameters
        usage_reduction_pct, is_reversible = self.ACTION_PARAMS[action]

        # Calculate cost savings
        cost_saving = self._calculate_cost_saving(
            current_monthly_cost, usage_reduction_pct, action, resource.type
        )

        # Calculate carbon reduction
        carbon_reduction = self._calculate_carbon_reduction(
            resource, current_monthly_cost, usage_reduction_pct, feature
        )

        # Calculate risk
        risk_score = self._calculate_risk(
            action=action,
            criticality=criticality,
            confidence=confidence,
            usage_factor=current_usage,
            is_reversible=is_reversible,
        )

        details = {
            "usage_reduction_pct": usage_reduction_pct,
            "is_reversible": is_reversible,
            "resource_type": resource.type.value,
            "criticality": round(criticality, 2),
            "confidence": round(confidence * 100, 1),
        }

        return SimulationResult(
            action=action,
            cost_saving=round(cost_saving, 2),
            carbon_reduction=round(carbon_reduction, 2),
            risk_score=round(risk_score, 1),
            details=details,
        )

    def _get_monthly_cost(self, db: Session, resource: Resource) -> float:
        """Get average monthly cost for resource.
        
        Args:
            db: Database session
            resource: Resource record
            
        Returns:
            Estimated monthly cost in dollars
        """
        # Query last 30 days of cost data
        costs = (
            db.query(CostRecord)
            .filter(CostRecord.resource_id == resource.id)
            .order_by(CostRecord.timestamp.desc())
            .limit(720)  # 30 days * 24 hours
            .all()
        )

        if not costs:
            return 0.0

        # Sum and extrapolate to monthly (730 hours in a month)
        total_cost = sum(c.estimated_cost for c in costs)
        hours_of_data = len(costs)

        if hours_of_data > 0:
            monthly_cost = (total_cost / hours_of_data) * 730
            return monthly_cost

        return 0.0

    def _calculate_cost_saving(
        self,
        current_monthly_cost: float,
        usage_reduction_pct: float,
        action: str,
        resource_type: ResourceType,
    ) -> float:
        """Calculate cost saving for action.
        
        Args:
            current_monthly_cost: Current monthly cost
            usage_reduction_pct: Percentage reduction (0-1)
            action: Action name
            resource_type: Type of resource
            
        Returns:
            Monthly cost saving in dollars
        """
        # Base savings from usage reduction
        base_saving = current_monthly_cost * usage_reduction_pct

        # For stopped instances, account for remaining storage costs (~5% of EC2 cost)
        if action == "stop_instance":
            if resource_type == ResourceType.ec2:
                # EC2 has EBS storage that still costs money when stopped
                base_saving *= 0.95  # Keep 5% ongoing cost
            elif resource_type == ResourceType.s3:
                # S3 cost is mostly storage, stops when deleted
                base_saving *= 1.0

        return base_saving

    def _calculate_carbon_reduction(
        self,
        resource: Resource,
        current_monthly_cost: float,
        usage_reduction_pct: float,
        feature: Feature,
    ) -> float:
        """Calculate carbon reduction from action.
        
        Args:
            resource: Resource record
            current_monthly_cost: Current monthly cost
            usage_reduction_pct: Percentage reduction (0-1)
            feature: Current feature data
            
        Returns:
            Carbon reduction in kg CO2
        """
        # Get carbon intensity for resource type (default 0.5 if not found)
        intensity = self.CARBON_INTENSITY.get(resource.type, 0.5)

        # Calculate carbon from current usage
        # Assumptions: 730 hours/month, carbon_intensity kg CO2 per $10/hour
        current_carbon = (current_monthly_cost / 10.0) * intensity

        # Carbon reduction is proportional to usage reduction
        carbon_reduction = current_carbon * usage_reduction_pct

        # Adjust based on actual usage from features
        # If CPU is low, carbon impact is lower
        usage_factor = self._calculate_usage_factor(feature)
        carbon_reduction *= usage_factor

        return carbon_reduction

    def _calculate_risk(
        self,
        action: str,
        criticality: float,
        confidence: float,
        usage_factor: float,
        is_reversible: bool,
    ) -> float:
        """Calculate operational risk of action.
        
        Risk = criticality × (1 - confidence) × usage_factor × reversibility_factor
        
        Args:
            action: Action name
            criticality: Criticality score (0-1)
            confidence: Detection confidence (0-1)
            usage_factor: Usage factor (0-1)
            is_reversible: Whether action is reversible
            
        Returns:
            Risk score (0-100)
        """
        # Base risk calculation
        base_risk = criticality * (1.0 - confidence) * usage_factor

        # Reversibility adjustment
        # Irreversible actions have higher risk
        reversibility_multiplier = 3.0 if not is_reversible else 1.0

        # Action-specific adjustments
        if action == "do_nothing":
            risk = 0.0  # No action = no risk
        elif action == "stop_instance":
            risk = base_risk * reversibility_multiplier * 0.5  # Lower risk (reversible)
        elif action == "scale_down":
            risk = base_risk * reversibility_multiplier * 0.3  # Lower risk (safer)
        elif action == "delete_resource":
            risk = base_risk * reversibility_multiplier * 2.0  # Higher risk (irreversible)
        else:
            risk = base_risk

        # Normalize to 0-100
        return min(100.0, max(0.0, risk * 100.0))

    def _calculate_criticality(
        self,
        resource: Resource,
        monthly_cost: float,
        usage_factor: float,
    ) -> float:
        """Calculate criticality score for resource.
        
        Criticality combines:
        - Resource type importance
        - Cost (higher cost = more critical)
        - Usage level (higher usage = more critical)
        
        Args:
            resource: Resource record
            monthly_cost: Monthly cost
            usage_factor: Usage factor (0-1)
            
        Returns:
            Criticality score (0-1)
        """
        # Base criticality by resource type
        type_criticality = {
            ResourceType.lambda_fn: 0.6,  # Functions are less critical
            ResourceType.s3: 0.7,  # Storage is moderately critical
            ResourceType.ec2: 0.8,  # EC2 instances are highly critical
        }
        base_criticality = type_criticality.get(resource.type, 0.5)

        # Cost multiplier (higher cost = more critical)
        # Normalize to $0-1000 range
        cost_factor = min(1.0, monthly_cost / 1000.0)

        # Combine factors
        criticality = (base_criticality * 0.5) + (cost_factor * 0.3) + (usage_factor * 0.2)

        return min(1.0, criticality)

    def _calculate_usage_factor(self, feature: Feature) -> float:
        """Calculate usage factor (0-1) from feature data.
        
        Usage factor represents how actively the resource is being used.
        
        Args:
            feature: Feature data
            
        Returns:
            Usage factor (0-1)
        """
        if feature is None:
            return 0.5  # Unknown usage

        factors = []

        # CPU usage (0-100%) -> 0-1 factor
        if feature.cpu_avg is not None and feature.cpu_avg > 0:
            cpu_factor = min(1.0, feature.cpu_avg / 100.0)
            factors.append(cpu_factor * 0.4)

        # Network usage
        if feature.network_total is not None and feature.network_total > 0:
            # Normalize network to 0-1000 MB/min
            network_factor = min(1.0, feature.network_total / 1000.0)
            factors.append(network_factor * 0.3)

        # Request volume
        if feature.request_count is not None and feature.request_count > 0:
            # Normalize request count to 0-10000
            request_factor = min(1.0, feature.request_count / 10000.0)
            factors.append(request_factor * 0.3)

        if not factors:
            return 0.3  # Low usage if no factors available

        return sum(factors)

    def recommend_action(
        self,
        results: list[SimulationResult],
        confidence: float,
    ) -> Optional[str]:
        """Recommend the best action based on simulation results.
        
        Args:
            results: List of simulation results
            confidence: Anomaly confidence (0-100)
            
        Returns:
            Recommended action name, or None if no action recommended
        """
        if not results:
            return None

        # Confidence threshold: need >60% confidence to take action
        if confidence < 60:
            logger.debug(f"Confidence too low ({confidence:.1f}%), recommending do_nothing")
            return "do_nothing"

        # Find best action using multi-criteria decision
        # Preference: high cost_saving, low risk
        best_action = None
        best_score = -float("inf")

        for result in results:
            # Skip "do_nothing" unless it's the only option
            if result.action == "do_nothing":
                continue

            # Score: cost_saving / (1 + risk_score)
            score = result.cost_saving / (1.0 + result.risk_score / 100.0)

            logger.debug(
                f"Action {result.action}: saving={result.cost_saving}, "
                f"risk={result.risk_score}, score={score}"
            )

            if score > best_score:
                best_score = score
                best_action = result.action

        if best_action is None:
            return "do_nothing"

        return best_action
