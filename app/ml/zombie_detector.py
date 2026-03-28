"""Zombie Detector for Idle Resource Detection.

Detects idle/unused resources:
- EC2: CPU < 2% AND network low
- EBS: Unattached AND no IO
- Lambda: No invocations in period
- RDS: Low connections
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.features import Feature
from app.models.metrics import Metric
from app.models.resource import Resource

logger = logging.getLogger(__name__)


class ZombieDetector:
    """Detect idle/zombie resources that are consuming costs without providing value."""

    # Thresholds for different resource types
    EC2_CPU_THRESHOLD = 2.0  # %
    EC2_NETWORK_THRESHOLD = 100.0  # bytes per minute
    EC2_IDLE_PERIOD = 720  # hours (30 days)

    EBS_MIN_IO_OPS = 10  # per day
    EBS_IDLE_PERIOD = 168  # hours (7 days)

    LAMBDA_MIN_INVOCATIONS = 10
    LAMBDA_IDLE_PERIOD = 168  # hours (7 days)

    LB_MIN_REQUESTS = 100  # per day

    def __init__(self):
        """Initialize Zombie Detector."""
        self.cpu_threshold = self.EC2_CPU_THRESHOLD
        self.network_threshold = self.EC2_NETWORK_THRESHOLD

    def detect_zombie_ec2(self, feature: Feature) -> Optional[dict]:
        """Detect idle EC2 instances.
        
        Idle criteria:
        - CPU < 2% AND
        - Network traffic low
        
        Args:
            feature: Feature record for EC2 instance
            
        Returns:
            Dict with zombie detection results or None
        """
        if feature.cpu_avg is None or feature.network_total is None:
            return None

        cpu_idle = feature.cpu_avg < self.cpu_threshold
        network_idle = feature.network_total < self.network_threshold

        is_zombie = cpu_idle and network_idle

        confidence = 0.0
        if is_zombie:
            # Higher confidence if both metrics are very low
            cpu_factor = (self.cpu_threshold - feature.cpu_avg) / self.cpu_threshold
            network_factor = (
                (self.network_threshold - feature.network_total) / self.network_threshold
                if feature.network_total < self.network_threshold
                else 0.0
            )
            confidence = min(100.0, (cpu_factor + network_factor) / 2 * 100)

        return {
            "is_zombie": is_zombie,
            "cpu_avg": feature.cpu_avg,
            "cpu_threshold": self.cpu_threshold,
            "cpu_idle": cpu_idle,
            "network_total": feature.network_total,
            "network_threshold": self.network_threshold,
            "network_idle": network_idle,
            "confidence": float(confidence),
            "resource_type": "ec2",
        }

    def detect_zombie_ebs(self, resource: Resource, feature: Feature) -> Optional[dict]:
        """Detect idle EBS volumes.
        
        Idle criteria:
        - Unattached volume OR
        - Attached but no IO operations
        
        Args:
            resource: Resource record
            feature: Feature record for EBS volume
            
        Returns:
            Dict with zombie detection results or None
        """
        # Check if volume is attached (this would be in metadata)
        is_attached = resource.tags.get("attached", True) if resource.tags else True
        has_io = (
            feature.request_count is not None and feature.request_count > self.EBS_MIN_IO_OPS
        )

        is_zombie = not is_attached or (is_attached and not has_io)

        confidence = 0.0
        if is_zombie:
            if not is_attached:
                confidence = 95.0  # High confidence for unattached
            elif not has_io:
                confidence = min(100.0, (1 - (feature.request_count or 0) / self.EBS_MIN_IO_OPS) * 100)

        return {
            "is_zombie": is_zombie,
            "is_attached": is_attached,
            "request_count": feature.request_count or 0,
            "min_io_ops": self.EBS_MIN_IO_OPS,
            "has_io": has_io,
            "confidence": float(confidence),
            "resource_type": "ebs",
        }

    def detect_zombie_lambda(self, feature: Feature) -> Optional[dict]:
        """Detect idle Lambda functions.
        
        Idle criteria:
        - No invocations in period
        
        Args:
            feature: Feature record for Lambda function
            
        Returns:
            Dict with zombie detection results or None
        """
        if feature.request_count is None:
            return None

        is_zombie = feature.request_count < self.LAMBDA_MIN_INVOCATIONS

        confidence = 0.0
        if is_zombie:
            confidence = min(100.0, (1 - (feature.request_count / self.LAMBDA_MIN_INVOCATIONS)) * 100)

        return {
            "is_zombie": is_zombie,
            "request_count": feature.request_count,
            "min_invocations": self.LAMBDA_MIN_INVOCATIONS,
            "confidence": float(confidence),
            "resource_type": "lambda",
        }

    def detect_zombie_lb(self, feature: Feature) -> Optional[dict]:
        """Detect idle Load Balancers.
        
        Idle criteria:
        - No requests in period
        
        Args:
            feature: Feature record for Load Balancer
            
        Returns:
            Dict with zombie detection results or None
        """
        if feature.request_count is None:
            return None

        is_zombie = feature.request_count < self.LB_MIN_REQUESTS

        confidence = 0.0
        if is_zombie:
            confidence = min(100.0, (1 - (feature.request_count / self.LB_MIN_REQUESTS)) * 100)

        return {
            "is_zombie": is_zombie,
            "request_count": feature.request_count,
            "min_requests": self.LB_MIN_REQUESTS,
            "confidence": float(confidence),
            "resource_type": "load_balancer",
        }

    def detect(self, resource: Resource, feature: Feature) -> Optional[dict]:
        """Detect zombies based on resource type.
        
        Args:
            resource: Resource record
            feature: Feature record
            
        Returns:
            Dict with zombie detection results or None if type not supported
        """
        resource_type = resource.type.lower()

        if resource_type == "ec2":
            return self.detect_zombie_ec2(feature)

        if resource_type == "ebs":
            return self.detect_zombie_ebs(resource, feature)

        if resource_type == "lambda":
            return self.detect_zombie_lambda(feature)

        if resource_type in ["lb", "load_balancer", "elb", "alb", "nlb"]:
            return self.detect_zombie_lb(feature)

        logger.debug("Zombie detection not supported for resource type: %s", resource_type)
        return None

    def get_info(self) -> dict:
        """Get detector information.
        
        Returns:
            Dict with thresholds and configuration
        """
        return {
            "detector_type": "zombie_detector",
            "ec2_cpu_threshold": self.cpu_threshold,
            "ec2_network_threshold": self.network_threshold,
            "ebs_min_io_ops": self.EBS_MIN_IO_OPS,
            "lambda_min_invocations": self.LAMBDA_MIN_INVOCATIONS,
            "lb_min_requests": self.LB_MIN_REQUESTS,
            "supported_types": ["ec2", "ebs", "lambda", "load_balancer"],
        }

    @staticmethod
    def get_zombie_recommendations(zombie_result: dict) -> list[str]:
        """Get recommendations for zombie resources.
        
        Args:
            zombie_result: Result from detect() method
            
        Returns:
            List of recommendations
        """
        recommendations = []
        resource_type = zombie_result.get("resource_type")

        if zombie_result.get("is_zombie"):
            if resource_type == "ec2":
                recommendations.append("Stop or terminate idle EC2 instance")
                recommendations.append("Use auto-scaling to remove from load balancer")
                recommendations.append("Review scheduled scaling policies")

            elif resource_type == "ebs":
                if not zombie_result.get("is_attached"):
                    recommendations.append("Delete unattached EBS volume")
                    recommendations.append("Back up if data is needed")
                else:
                    recommendations.append("Attach volume to active instance or delete")
                    recommendations.append("Review snapshot schedule")

            elif resource_type == "lambda":
                recommendations.append("Delete unused Lambda function")
                recommendations.append("Archive code if retention needed")
                recommendations.append("Update CloudWatch alarms")

            elif resource_type == "load_balancer":
                recommendations.append("Delete idle load balancer")
                recommendations.append("Consider serverless alternatives")
                recommendations.append("Archive DNS records")

        return recommendations
