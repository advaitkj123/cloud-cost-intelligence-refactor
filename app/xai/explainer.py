"""XAI Explainer - Deterministic Explanations for Anomaly Detections.

Explains:
1. Isolation Forest anomalies via feature deviations
2. Prophet time-series spike explanations
3. Zombie detector idle resource rules
4. Hybrid decision logic combining all signals
"""

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.anomalies import Anomaly
from app.models.resource import Resource

logger = logging.getLogger(__name__)


class XAIExplainer:
    """Explainable AI interface for anomaly explanations.
    
    Provides deterministic, human-readable explanations for all detection methods.
    No LLM - pure logic-based explanations.
    """

    # Feature names and their human descriptions
    FEATURE_DESCRIPTIONS = {
        "cost_delta": "Cost change from baseline",
        "cost_rolling_mean": "Rolling average cost",
        "cost_rolling_std": "Cost volatility",
        "cpu_avg": "Average CPU utilization",
        "cpu_rolling_mean": "Rolling average CPU",
        "cpu_rolling_std": "CPU volatility",
        "memory_avg": "Average memory usage",
        "memory_rolling_mean": "Rolling average memory",
        "storage_total": "Total storage usage",
        "network_total": "Total network traffic",
        "network_rolling_mean_in": "Incoming network traffic",
        "network_rolling_mean_out": "Outgoing network traffic",
        "request_count": "Request volume",
        "request_rolling_mean": "Rolling average requests",
        "service_ratio": "Service efficiency ratio",
        "efficiency_score": "Overall resource efficiency",
        "data_quality": "Data quality score",
    }

    # Thresholds for significant deviations
    SIGNIFICANT_DEVIATION = 1.5  # Standard deviations
    VERY_SIGNIFICANT_DEVIATION = 2.5  # Standard deviations
    CRITICAL_DEVIATION = 3.5  # Standard deviations

    def __init__(self):
        """Initialize XAI Explainer."""
        self.logger = logging.getLogger(__name__)

    def explain_anomaly(self, anomaly: Anomaly, db: Optional[Session] = None) -> dict:
        """Generate complete explanation for an anomaly.
        
        Args:
            anomaly: Anomaly record from database
            db: Optional database session for context
            
        Returns:
            Dict with keys:
            - summary: Human-readable summary
            - key_factors: List of key contributing factors
            - model_output: Detailed output from each model
            - impact: Business impact description
            - recommendation: Recommended action
            - confidence: Confidence percentage
            - timestamp: Explanation generated at
        """
        logger.debug(f"Explaining anomaly {anomaly.id}: {anomaly.anomaly_type}")

        # Get explanations from each detector
        iso_explanation = self._explain_isolation_forest(anomaly)
        prophet_explanation = self._explain_prophet(anomaly)
        zombie_explanation = self._explain_zombie(anomaly)

        # Combine into comprehensive explanation
        summary = self._generate_summary(anomaly, iso_explanation, prophet_explanation, zombie_explanation)
        key_factors = self._extract_key_factors(anomaly, iso_explanation, prophet_explanation, zombie_explanation)
        impact = self._assess_impact(anomaly)
        recommendation = self._get_recommendation(anomaly, key_factors)

        explanation = {
            "resource_id": anomaly.resource_id,
            "anomaly_id": anomaly.id,
            "anomaly_type": anomaly.anomaly_type,
            "is_anomaly": anomaly.is_anomaly,
            "confidence": anomaly.confidence,
            "summary": summary,
            "key_factors": key_factors,
            "model_output": {
                "isolation_forest": iso_explanation,
                "prophet": prophet_explanation,
                "zombie_detector": zombie_explanation,
            },
            "impact": impact,
            "recommendation": recommendation,
            "detected_at": anomaly.detected_at.isoformat() if anomaly.detected_at else None,
            "explained_at": datetime.utcnow().isoformat(),
        }

        return explanation

    def _explain_isolation_forest(self, anomaly: Anomaly) -> dict:
        """Explain Isolation Forest anomaly via feature deviations.
        
        Args:
            anomaly: Anomaly record
            
        Returns:
            Dict with explanation details
        """
        iso_score = anomaly.isolation_forest_score or 0
        is_flagged = iso_score > 70

        if not is_flagged:
            return {
                "method": "Isolation Forest",
                "is_flagged": False,
                "anomaly_score": iso_score,
                "interpretation": "Resource features appear normal",
                "key_deviations": [],
            }

        # Build explanation based on anomaly score severity
        deviation_level = self._categorize_deviation_level(iso_score)

        # Extract key deviations from details if available
        key_deviations = []
        if anomaly.details and "feature_deviations" in anomaly.details:
            deviations = anomaly.details["feature_deviations"]
            sorted_deviations = sorted(
                deviations.items(),
                key=lambda x: abs(x[1]),
                reverse=True
            )
            for feature_name, deviation in sorted_deviations[:5]:  # Top 5
                description = self.FEATURE_DESCRIPTIONS.get(feature_name, feature_name)
                key_deviations.append({
                    "feature": feature_name,
                    "description": description,
                    "deviation": round(deviation, 2),
                    "severity": self._categorize_deviation_severity(deviation),
                })

        # Gather relevant metrics for explanation
        metrics_context = []
        if anomaly.cpu_avg is not None:
            metrics_context.append(f"CPU at {anomaly.cpu_avg:.1f}%")
        if anomaly.cost_delta is not None:
            sign = "+" if anomaly.cost_delta > 0 else ""
            metrics_context.append(f"Cost delta {sign}{anomaly.cost_delta:.2f}")
        if anomaly.efficiency_score is not None:
            metrics_context.append(f"Efficiency score {anomaly.efficiency_score:.1f}")

        interpretation = (
            f"Anomalous resource behavior detected ({deviation_level}). "
            f"Feature patterns deviate significantly from normal. "
            f"{', '.join(metrics_context) if metrics_context else 'Multi-dimensional anomaly'}"
        )

        return {
            "method": "Isolation Forest",
            "is_flagged": True,
            "anomaly_score": iso_score,
            "deviation_level": deviation_level,
            "severity": self._score_to_severity(iso_score),
            "key_deviations": key_deviations,
            "interpretation": interpretation,
            "details": {
                "metric_snapshot": {
                    "cpu": anomaly.cpu_avg,
                    "cost_delta": anomaly.cost_delta,
                    "efficiency": anomaly.efficiency_score,
                }
            }
        }

    def _explain_prophet(self, anomaly: Anomaly) -> dict:
        """Explain Prophet time-series anomaly.
        
        Args:
            anomaly: Anomaly record
            
        Returns:
            Dict with explanation details
        """
        is_flagged = anomaly.prophet_is_anomaly or False
        confidence = anomaly.prophet_confidence or 0

        if not is_flagged or confidence < 30:
            return {
                "method": "Prophet Time-Series",
                "is_flagged": False,
                "confidence": confidence,
                "interpretation": "Cost trend appears normal based on historical patterns",
            }

        # Calculate cost overage
        actual = anomaly.actual_cost or 0
        predicted = anomaly.cost_predicted or 0
        overage = actual - predicted
        overage_pct = ((actual - predicted) / predicted * 100) if predicted > 0 else 0

        # Build explanation
        if overage_pct > 50:
            cost_severity = "Critical"
            interpretation_prefix = "CRITICAL cost spike detected"
        elif overage_pct > 25:
            cost_severity = "High"
            interpretation_prefix = "Significant cost increase detected"
        elif overage_pct > 10:
            cost_severity = "Moderate"
            interpretation_prefix = "Noticeable cost increase detected"
        else:
            cost_severity = "Low"
            interpretation_prefix = "Slight cost increase detected"

        interpretation = (
            f"{interpretation_prefix}. "
            f"Actual cost (${actual:.2f}) exceeds forecast (${predicted:.2f}) "
            f"by ${overage:.2f} ({overage_pct:.1f}%). "
            f"Confidence: {confidence:.0f}%"
        )

        return {
            "method": "Prophet Time-Series",
            "is_flagged": True,
            "confidence": confidence,
            "severity": cost_severity,
            "actual_cost": round(actual, 2),
            "predicted_cost": round(predicted, 2),
            "cost_overage": round(overage, 2),
            "overage_percentage": round(overage_pct, 1),
            "interpretation": interpretation,
            "details": {
                "forecast_vs_actual": {
                    "predicted": round(predicted, 2),
                    "actual": round(actual, 2),
                    "confidence_interval": f"95% CI around forecast",
                }
            }
        }

    def _explain_zombie(self, anomaly: Anomaly) -> dict:
        """Explain Zombie Detector idle resource finding.
        
        Args:
            anomaly: Anomaly record
            
        Returns:
            Dict with explanation details
        """
        is_flagged = anomaly.zombie_is_idle or False
        confidence = anomaly.zombie_confidence or 0

        if not is_flagged or confidence < 50:
            return {
                "method": "Zombie Detector",
                "is_flagged": False,
                "confidence": confidence,
                "interpretation": "Resource is actively being used",
            }

        # Extract zombie details from anomaly
        zombie_details = anomaly.details.get("zombie", {}) if anomaly.details else {}
        resource_type = zombie_details.get("resource_type", "Unknown")

        # Build type-specific explanation
        if resource_type.lower() == "ec2":
            explanation = self._explain_zombie_ec2(anomaly, zombie_details, confidence)
        elif resource_type.lower() == "ebs":
            explanation = self._explain_zombie_ebs(anomaly, zombie_details, confidence)
        elif resource_type.lower() == "lambda":
            explanation = self._explain_zombie_lambda(anomaly, zombie_details, confidence)
        elif resource_type.lower() == "load_balancer":
            explanation = self._explain_zombie_lb(anomaly, zombie_details, confidence)
        else:
            explanation = self._explain_zombie_generic(anomaly, zombie_details, confidence)

        return explanation

    def _explain_zombie_ec2(
        self,
        anomaly: Anomaly,
        zombie_details: dict,
        confidence: float
    ) -> dict:
        """Explain idle EC2 instance."""
        cpu = anomaly.cpu_avg or 0
        network = zombie_details.get("network_total", 0) or 0
        cpu_idle = cpu < 2.0
        network_idle = network < 100.0

        factors = []
        if cpu_idle:
            factors.append(f"CPU usage critically low ({cpu:.1f}%)")
        if network_idle:
            factors.append(f"Network traffic minimal ({network:.0f} bytes/min)")

        interpretation = (
            f"EC2 instance appears idle. "
            f"{' '.join(factors)}. "
            f"Instance is consuming resources without active use. "
            f"Confidence: {confidence:.0f}%"
        )

        return {
            "method": "Zombie Detector",
            "is_flagged": True,
            "resource_type": "EC2",
            "confidence": confidence,
            "severity": "High",
            "idle_factors": factors,
            "interpretation": interpretation,
            "details": {
                "cpu_utilization": f"{cpu:.1f}%",
                "cpu_threshold": "2.0%",
                "network_traffic": f"{network:.0f} bytes/min",
                "network_threshold": "100 bytes/min",
            }
        }

    def _explain_zombie_ebs(
        self,
        anomaly: Anomaly,
        zombie_details: dict,
        confidence: float
    ) -> dict:
        """Explain idle EBS volume."""
        is_unattached = zombie_details.get("is_unattached", False)
        iops = zombie_details.get("iops", 0) or 0

        if is_unattached:
            reason = "Volume is unattached and not in use"
        else:
            reason = f"Volume has minimal I/O operations ({iops:.0f} ops/day)"

        interpretation = (
            f"EBS volume appears idle. "
            f"{reason}. "
            f"Volume is consuming storage costs without providing value. "
            f"Confidence: {confidence:.0f}%"
        )

        return {
            "method": "Zombie Detector",
            "is_flagged": True,
            "resource_type": "EBS",
            "confidence": confidence,
            "severity": "Medium",
            "idle_reason": reason,
            "interpretation": interpretation,
            "details": {
                "is_unattached": is_unattached,
                "iops": iops,
                "min_threshold": 10,
            }
        }

    def _explain_zombie_lambda(
        self,
        anomaly: Anomaly,
        zombie_details: dict,
        confidence: float
    ) -> dict:
        """Explain idle Lambda function."""
        invocations = zombie_details.get("invocations", 0) or 0

        interpretation = (
            f"AWS Lambda function appears idle. "
            f"Very few invocations ({invocations:.0f} in period) despite active deployment. "
            f"Function is consuming reservation costs without significant use. "
            f"Confidence: {confidence:.0f}%"
        )

        return {
            "method": "Zombie Detector",
            "is_flagged": True,
            "resource_type": "Lambda",
            "confidence": confidence,
            "severity": "Low",
            "idle_reason": f"Minimal invocations ({invocations:.0f})",
            "interpretation": interpretation,
            "details": {
                "invocations": invocations,
                "min_threshold": 10,
            }
        }

    def _explain_zombie_lb(
        self,
        anomaly: Anomaly,
        zombie_details: dict,
        confidence: float
    ) -> dict:
        """Explain idle Load Balancer."""
        requests = zombie_details.get("requests", 0) or 0

        interpretation = (
            f"Load Balancer appears idle. "
            f"Very few requests ({requests:.0f} per day) despite deployment. "
            f"Load Balancer is consuming costs without significant traffic. "
            f"Confidence: {confidence:.0f}%"
        )

        return {
            "method": "Zombie Detector",
            "is_flagged": True,
            "resource_type": "Load Balancer",
            "confidence": confidence,
            "severity": "Medium",
            "idle_reason": f"Minimal traffic ({requests:.0f} requests/day)",
            "interpretation": interpretation,
            "details": {
                "requests_per_day": requests,
                "min_threshold": 100,
            }
        }

    def _explain_zombie_generic(
        self,
        anomaly: Anomaly,
        zombie_details: dict,
        confidence: float
    ) -> dict:
        """Explain idle resource (generic)."""
        interpretation = (
            f"Resource appears idle based on low utilization metrics. "
            f"Resource is consuming costs without active use. "
            f"Confidence: {confidence:.0f}%"
        )

        return {
            "method": "Zombie Detector",
            "is_flagged": True,
            "resource_type": "Generic Resource",
            "confidence": confidence,
            "severity": "Medium",
            "interpretation": interpretation,
        }

    def _generate_summary(
        self,
        anomaly: Anomaly,
        iso_explain: dict,
        prophet_explain: dict,
        zombie_explain: dict
    ) -> str:
        """Generate human-readable summary of anomaly.
        
        Args:
            anomaly: Anomaly record
            iso_explain: Isolation Forest explanation
            prophet_explain: Prophet explanation
            zombie_explain: Zombie explanation
            
        Returns:
            Summary text
        """
        if not anomaly.is_anomaly:
            return "No anomaly detected. Resource metrics are within normal ranges."

        # Count triggered detectors
        triggered = []
        if iso_explain.get("is_flagged"):
            triggered.append("unusual behavior patterns")
        if prophet_explain.get("is_flagged"):
            triggered.append("cost spike")
        if zombie_explain.get("is_flagged"):
            triggered.append("idle resource")

        if not triggered:
            return f"Anomaly detected with {anomaly.confidence:.0f}% confidence."

        triggered_str = ", ".join(triggered)

        if len(triggered) == 1:
            return (
                f"Anomaly detected: {triggered[0]}. "
                f"Confidence: {anomaly.confidence:.0f}%. "
                f"Type: {anomaly.anomaly_type}"
            )
        else:
            return (
                f"Multiple anomalies detected: {triggered_str}. "
                f"High confidence: {anomaly.confidence:.0f}%. "
                f"Type: Hybrid"
            )

    def _extract_key_factors(
        self,
        anomaly: Anomaly,
        iso_explain: dict,
        prophet_explain: dict,
        zombie_explain: dict
    ) -> list[str]:
        """Extract key contributing factors.
        
        Args:
            anomaly: Anomaly record
            iso_explain: Isolation Forest explanation
            prophet_explain: Prophet explanation  
            zombie_explain: Zombie explanation
            
        Returns:
            List of key factors as strings
        """
        factors = []

        # From Isolation Forest
        if iso_explain.get("is_flagged"):
            deviation_level = iso_explain.get("deviation_level", "Unknown")
            factors.append(f"Feature deviation: {deviation_level}")
            for deviation in iso_explain.get("key_deviations", [])[:3]:
                factors.append(f"{deviation['description']}: {deviation['severity']}")

        # From Prophet
        if prophet_explain.get("is_flagged"):
            overage = prophet_explain.get("overage_percentage", 0)
            factors.append(f"Cost overage: +{overage:.1f}% vs forecast")

        # From Zombie
        if zombie_explain.get("is_flagged"):
            resource_type = zombie_explain.get("resource_type", "Resource")
            factors.append(f"{resource_type} appears idle")
            for factor in zombie_explain.get("idle_factors", []):
                factors.append(factor)

        return factors if factors else ["General anomaly detected"]

    def _assess_impact(self, anomaly: Anomaly) -> str:
        """Assess business impact of anomaly.
        
        Args:
            anomaly: Anomaly record
            
        Returns:
            Impact description
        """
        impacts = []

        # Cost impact
        if anomaly.actual_cost is not None and anomaly.expected_cost is not None:
            delta = anomaly.actual_cost - anomaly.expected_cost
            if delta > 0:
                impacts.append(f"Cost increased by ${delta:.2f}")
        elif anomaly.cost_delta is not None and anomaly.cost_delta > 0:
            impacts.append(f"Cost increased by ${anomaly.cost_delta:.2f}")

        # Efficiency impact
        if anomaly.efficiency_score is not None and anomaly.efficiency_score < 50:
            impacts.append("Resource efficiency compromised")

        # Zombie impact
        if anomaly.zombie_is_idle:
            impacts.append("Wasted cloud spending on idle resources")

        if not impacts:
            impacts.append("Potential performance or cost anomaly")

        # Determine severity
        if anomaly.confidence > 80:
            severity = "CRITICAL"
        elif anomaly.confidence > 60:
            severity = "HIGH"
        elif anomaly.confidence > 40:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        impact_text = f"[{severity}] " + "; ".join(impacts)
        return impact_text

    def _get_recommendation(self, anomaly: Anomaly, key_factors: list[str]) -> dict:
        """Get recommended action.
        
        Args:
            anomaly: Anomaly record
            key_factors: Key factors from analysis
            
        Returns:
            Recommendation dict with action and urgency
        """
        urgency = "LOW"
        actions = []

        if anomaly.confidence > 80:
            urgency = "CRITICAL"
        elif anomaly.confidence > 60:
            urgency = "HIGH"
        elif anomaly.confidence > 40:
            urgency = "MEDIUM"

        # Type-specific recommendations
        if anomaly.anomaly_type == "resource_idle":
            actions.append("Terminate or deallocate idle resource")
            actions.append("Review resource tagging and resource group")
            actions.append("Implement automatic cleanup policies")
            urgency = "HIGH"
        elif anomaly.anomaly_type == "cost_spike":
            actions.append("Investigate recent workload changes")
            actions.append("Review resource scaling events")
            actions.append("Check for unintended deployments")
            urgency = "HIGH"
        elif anomaly.anomaly_type == "behavior_change":
            actions.append("Review resource configuration changes")
            actions.append("Check CloudTrail for modifications")
            actions.append("Verify against deployment plans")
            urgency = "MEDIUM"
        elif anomaly.anomaly_type == "hybrid":
            actions.append("Immediate investigation required")
            actions.append("Multiple anomaly signals detected")
            actions.append("Review all metrics and logs")
            urgency = "CRITICAL"

        # Add generic recommendations
        if not actions:
            actions.append("Monitor resource closely")
            actions.append("Gather additional diagnostics")
            actions.append("Escalate if issue persists")

        return {
            "urgency": urgency,
            "actions": actions,
            "next_steps": [
                "Acknowledge this anomaly",
                "Take recommended action",
                "Monitor for recurrence",
            ]
        }

    # Helper methods

    def _categorize_deviation_level(self, score: float) -> str:
        """Categorize isolation forest score into level.
        
        Args:
            score: Anomaly score 0-100
            
        Returns:
            Deviation level string
        """
        if score < 30:
            return "Normal"
        elif score < 50:
            return "Borderline"
        elif score < 70:
            return "Concerning"
        elif score < 85:
            return "Anomalous"
        else:
            return "Highly Anomalous"

    def _categorize_deviation_severity(self, deviation: float) -> str:
        """Categorize feature deviation into severity.
        
        Args:
            deviation: Deviation value in std devs
            
        Returns:
            Severity level
        """
        abs_dev = abs(deviation)
        if abs_dev < self.SIGNIFICANT_DEVIATION:
            return "Minor"
        elif abs_dev < self.VERY_SIGNIFICANT_DEVIATION:
            return "Significant"
        elif abs_dev < self.CRITICAL_DEVIATION:
            return "Severe"
        else:
            return "Critical"

    def _score_to_severity(self, score: float) -> str:
        """Convert score to severity level.
        
        Args:
            score: Score 0-100
            
        Returns:
            Severity level
        """
        if score < 30:
            return "Low"
        elif score < 50:
            return "Moderate"
        elif score < 70:
            return "High"
        else:
            return "Critical"
