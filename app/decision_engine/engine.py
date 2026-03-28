"""Decision Engine - Make deterministic action decisions.

Deterministic decision system that:
1. Scores all simulation results
2. Selects best action
3. Applies risk policy (auto-execute, safe-execute+notify, notify-only)
4. Calculates priority
5. Returns structured decision

Scoring: score = cost_saving + (carbon_saving × weight) - risk
Action: Select highest scoring result
Policy: Risk level determines execution & notification strategy
Priority: cost × severity × confidence (for queuing recommendations)
"""

import logging
from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Optional

from sqlalchemy.orm import Session

from app.decision_engine.simulator import SimulationResult
from app.models.anomalies import Anomaly
from app.models.resource import Resource

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk classification for action execution."""

    LOW = "low"  # 0-20: Safe to auto-execute
    MEDIUM = "medium"  # 20-50: Requires notification but safe to execute
    HIGH = "high"  # 50-100: Only notify, do not execute


class ExecutionPolicy(str, Enum):
    """Execution strategy based on risk level."""

    AUTO_EXECUTE = "auto_execute"  # Automatically execute action
    SAFE_EXECUTE = "safe_execute"  # Execute but send notification
    NOTIFY_ONLY = "notify_only"  # Notify only, no automatic execution


@dataclass
class DecisionResult:
    """Final decision for a resource anomaly.

    Attributes:
        resource_id: Target resource ID
        anomaly_id: Source anomaly ID
        final_action: Recommended action to take ("stop_instance", "scale_down", etc.)
        decision: Overall decision string (e.g., "AUTO_EXECUTE", "NOTIFY_ONLY")
        reason: Human-readable explanation of the decision
        score: Overall score for this decision (for ranking)
        risk_level: Risk classification (LOW, MEDIUM, HIGH)
        priority: Priority score for queuing (cost × severity × confidence)
        details: Additional context (selected action, alternatives, policy applied)
    """

    resource_id: int
    anomaly_id: int
    final_action: str
    decision: ExecutionPolicy
    reason: str
    score: float
    risk_level: RiskLevel
    priority: float
    details: dict = None

    def to_dict(self) -> dict:
        """Convert to dictionary with enum values as strings."""
        result = asdict(self)
        result["decision"] = self.decision.value
        result["risk_level"] = self.risk_level.value
        if result["details"] is None:
            result["details"] = {}
        return result


class DecisionEngine:
    """Deterministic decision engine for cloud resource optimization.

    Makes optimal decisions by:
    1. Scoring simulations: cost_saving + (carbon × weight) - risk
    2. Selecting best action (highest score)
    3. Applying risk policy (auto/notify/safe)
    4. Calculating priority for queue management
    5. Returning structured decision with reasoning
    """

    # Configuration constants
    CARBON_WEIGHT = 50.0  # Weight for carbon reduction ($$ equivalent per kg CO2)
    CONFIDENCE_THRESHOLD = 60.0  # Minimum confidence to act (0-100%)
    LOW_RISK_THRESHOLD = 20.0  # Risk threshold for auto-execute (0-100)
    MEDIUM_RISK_THRESHOLD = 50.0  # Risk threshold for safe-execute (0-100)

    def decide(
        self,
        resource: Resource,
        anomaly: Anomaly,
        simulation_results: List[SimulationResult],
        confidence: float,
    ) -> DecisionResult:
        """Make a decision for a resource based on simulation results.

        Args:
            resource: The affected resource
            anomaly: The detected anomaly
            simulation_results: Results from SimulationEngine (4 actions)
            confidence: Anomaly detection confidence (0-100%)

        Returns:
            DecisionResult with final_action, decision policy, and reasoning
        """
        # Low confidence: always do_nothing
        if confidence < self.CONFIDENCE_THRESHOLD:
            return self._low_confidence_decision(
                resource, anomaly, simulation_results, confidence
            )

        # Score all simulations
        scored_results = [
            self._score_simulation(result) for result in simulation_results
        ]

        # Find best action
        best_result = max(scored_results, key=lambda x: x["score"])
        best_action = best_result["action"]

        # If best action is "do_nothing", return it
        if best_action == "do_nothing":
            return self._do_nothing_decision(
                resource, anomaly, simulation_results, confidence, scored_results
            )

        # Calculate risk level
        risk_score = best_result["risk_score"]
        risk_level = self._classify_risk(risk_score)

        # Apply risk policy
        execution_policy = self._apply_risk_policy(risk_level)

        # Calculate priority
        priority = self._calculate_priority(
            best_result["cost_saving"],
            anomaly.severity if hasattr(anomaly, "severity") else 0.5,
            confidence,
        )

        # Build reason
        reason = self._build_reason(
            best_result, risk_level, execution_policy, confidence
        )

        return DecisionResult(
            resource_id=resource.id,
            anomaly_id=anomaly.id,
            final_action=best_action,
            decision=execution_policy,
            reason=reason,
            score=best_result["score"],
            risk_level=risk_level,
            priority=priority,
            details={
                "selected": best_result,
                "alternatives": scored_results,
                "confidence": confidence,
                "policy": execution_policy.value,
            },
        )

    def _score_simulation(self, result: SimulationResult) -> dict:
        """Score a single simulation result.

        Score = cost_saving + (carbon_reduction × weight) - risk
        
        This prioritizes cost savings while:
        - Valuing environmental impact (~$50 per kg CO2 saved)
        - Penalizing risk operations
        
        Args:
            result: SimulationResult from simulator
            
        Returns:
            Dictionary with action, score, and metrics
        """
        carbon_value = result.carbon_reduction * self.CARBON_WEIGHT
        score = result.cost_saving + carbon_value - result.risk_score

        return {
            "action": result.action,
            "score": score,
            "cost_saving": result.cost_saving,
            "carbon_reduction": result.carbon_reduction,
            "risk_score": result.risk_score,
            "details": result.details or {},
        }

    def _classify_risk(self, risk_score: float) -> RiskLevel:
        """Classify risk level based on risk score.

        Args:
            risk_score: Risk score (0-100)

        Returns:
            RiskLevel (LOW, MEDIUM, or HIGH)
        """
        if risk_score < self.LOW_RISK_THRESHOLD:
            return RiskLevel.LOW
        elif risk_score < self.MEDIUM_RISK_THRESHOLD:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.HIGH

    def _apply_risk_policy(self, risk_level: RiskLevel) -> ExecutionPolicy:
        """Apply execution policy based on risk level.

        Policy:
        - LOW (0-20): AUTO_EXECUTE - Automatically execute action
        - MEDIUM (20-50): SAFE_EXECUTE - Execute but notify operators
        - HIGH (50+): NOTIFY_ONLY - Only notify, require manual approval

        Args:
            risk_level: RiskLevel classification

        Returns:
            ExecutionPolicy for this decision
        """
        policy_map = {
            RiskLevel.LOW: ExecutionPolicy.AUTO_EXECUTE,
            RiskLevel.MEDIUM: ExecutionPolicy.SAFE_EXECUTE,
            RiskLevel.HIGH: ExecutionPolicy.NOTIFY_ONLY,
        }
        return policy_map[risk_level]

    def _calculate_priority(
        self, cost_saving: float, severity: float, confidence: float
    ) -> float:
        """Calculate priority score for decision queue.

        Priority = cost × severity × (confidence/100)

        Higher priority = should be acted on sooner
        - Cost: Savings in dollars (more valuable = higher priority)
        - Severity: Anomaly severity (0-1) (critical = higher priority)
        - Confidence: Detection confidence (0-100%) (certain = higher priority)

        Args:
            cost_saving: Monthly cost savings ($)
            severity: Anomaly severity (0-1)
            confidence: Detection confidence (0-100%)

        Returns:
            Priority score for queue ordering
        """
        # Normalize confidence to 0-1 range
        confidence_factor = min(confidence / 100.0, 1.0)

        # Severity defaults to 0.5 if not provided
        severity_factor = max(min(severity, 1.0), 0.0)

        # Priority = cost × severity × confidence
        priority = cost_saving * severity_factor * confidence_factor

        return priority

    def _build_reason(
        self,
        best_result: dict,
        risk_level: RiskLevel,
        execution_policy: ExecutionPolicy,
        confidence: float,
    ) -> str:
        """Build human-readable reason for decision.

        Args:
            best_result: Scored best simulation result
            risk_level: RiskLevel for this action
            execution_policy: ExecutionPolicy to apply
            confidence: Detection confidence

        Returns:
            Human-readable reason string
        """
        action = best_result["action"]
        cost = best_result["cost_saving"]
        carbon = best_result["carbon_reduction"]
        risk = best_result["risk_score"]

        # Format values for readability
        cost_str = f"${cost:.2f}/month (${cost*12:.2f}/year)"
        carbon_str = f"{carbon:.1f} kg CO2/month"
        risk_str = f"{risk:.1f}/100"
        confidence_str = f"{confidence:.1f}%"

        # Build reason based on components
        action_description = self._describe_action(action)

        reason_parts = [
            f"Recommend: {action_description}",
            f"Savings: {cost_str}",
            f"Carbon: {carbon_str}",
            f"Risk: {risk_str} ({risk_level.value})",
            f"Confidence: {confidence_str}",
        ]

        # Add policy-specific reasoning
        if execution_policy == ExecutionPolicy.AUTO_EXECUTE:
            reason_parts.append("Action: AUTO-EXECUTE (low risk)")
        elif execution_policy == ExecutionPolicy.SAFE_EXECUTE:
            reason_parts.append("Action: SAFE EXECUTE + NOTIFY (medium risk)")
        elif execution_policy == ExecutionPolicy.NOTIFY_ONLY:
            reason_parts.append("Action: NOTIFY ONLY - requires approval (high risk)")

        return " | ".join(reason_parts)

    def _describe_action(self, action: str) -> str:
        """Get human-readable description of action.

        Args:
            action: Action string (e.g., "stop_instance")

        Returns:
            Human-readable description
        """
        descriptions = {
            "do_nothing": "No action (resource acceptable)",
            "stop_instance": "Stop/pause instance (recoverable)",
            "scale_down": "Scale down capacity (reversible)",
            "delete_resource": "Delete resource (permanent)",
        }
        return descriptions.get(action, action)

    def _low_confidence_decision(
        self,
        resource: Resource,
        anomaly: Anomaly,
        simulation_results: List[SimulationResult],
        confidence: float,
    ) -> DecisionResult:
        """Make decision when confidence is below threshold.

        Args:
            resource: Target resource
            anomaly: Source anomaly
            simulation_results: Simulations (unused for low confidence)
            confidence: Detection confidence

        Returns:
            DecisionResult recommending no action
        """
        reason = (
            f"Low confidence ({confidence:.1f}%) detected. "
            f"Threshold is {self.CONFIDENCE_THRESHOLD}%. "
            "Recommend manual investigation before taking action."
        )

        return DecisionResult(
            resource_id=resource.id,
            anomaly_id=anomaly.id,
            final_action="do_nothing",
            decision=ExecutionPolicy.NOTIFY_ONLY,
            reason=reason,
            score=0.0,
            risk_level=RiskLevel.MEDIUM,
            priority=0.0,
            details={
                "confidence_below_threshold": True,
                "confidence": confidence,
                "threshold": self.CONFIDENCE_THRESHOLD,
            },
        )

    def _do_nothing_decision(
        self,
        resource: Resource,
        anomaly: Anomaly,
        simulation_results: List[SimulationResult],
        confidence: float,
        scored_results: List[dict],
    ) -> DecisionResult:
        """Make decision when best action is 'do_nothing'.

        Args:
            resource: Target resource
            anomaly: Source anomaly
            simulation_results: Simulations
            confidence: Detection confidence
            scored_results: Scored simulations

        Returns:
            DecisionResult recommending no action
        """
        # Find the do_nothing result
        do_nothing = next(s for s in scored_results if s["action"] == "do_nothing")

        reason = (
            "No action recommended. "
            "All potential actions have negative net value due to risk. "
            "Resource appears to be operating within acceptable parameters."
        )

        return DecisionResult(
            resource_id=resource.id,
            anomaly_id=anomaly.id,
            final_action="do_nothing",
            decision=ExecutionPolicy.NOTIFY_ONLY,
            reason=reason,
            score=do_nothing["score"],
            risk_level=RiskLevel.LOW,
            priority=0.0,
            details={
                "selected": do_nothing,
                "alternatives": scored_results,
                "confidence": confidence,
                "rationale": "Best action (do_nothing) has highest score",
            },
        )

    def batch_decide(
        self,
        decisions_input: List[dict],
        db: Session,
    ) -> List[DecisionResult]:
        """Process multiple decisions in batch.

        Args:
            decisions_input: List of {"resource": Resource, "anomaly": Anomaly,
                                      "simulations": List[SimulationResult],
                                      "confidence": float}
            db: Database session

        Returns:
            List of DecisionResult objects, sorted by priority (highest first)
        """
        results = []

        for item in decisions_input:
            try:
                result = self.decide(
                    resource=item["resource"],
                    anomaly=item["anomaly"],
                    simulation_results=item["simulations"],
                    confidence=item["confidence"],
                )
                results.append(result)
            except Exception as e:
                logger.error(
                    f"Error processing decision for resource {item['resource'].id}: {e}"
                )
                continue

        # Sort by priority (highest first)
        return sorted(results, key=lambda x: x.priority, reverse=True)

    def get_config(self) -> dict:
        """Get current configuration parameters.

        Returns:
            Dictionary of configuration parameters
        """
        return {
            "carbon_weight": self.CARBON_WEIGHT,
            "confidence_threshold": self.CONFIDENCE_THRESHOLD,
            "low_risk_threshold": self.LOW_RISK_THRESHOLD,
            "medium_risk_threshold": self.MEDIUM_RISK_THRESHOLD,
            "risk_levels": {
                "low": f"0-{self.LOW_RISK_THRESHOLD}",
                "medium": f"{self.LOW_RISK_THRESHOLD}-{self.MEDIUM_RISK_THRESHOLD}",
                "high": f"{self.MEDIUM_RISK_THRESHOLD}+",
            },
            "policies": {
                "low": "AUTO_EXECUTE",
                "medium": "SAFE_EXECUTE (notify + execute)",
                "high": "NOTIFY_ONLY",
            },
        }
