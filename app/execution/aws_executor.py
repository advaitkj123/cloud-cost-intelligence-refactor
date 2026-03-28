"""AWS Execution Engine - Execute cloud actions with retry and error handling.

Executes recommended actions on AWS resources:
- stop_instances: Stop EC2 instances (recoverable)
- delete_volume: Delete EBS volumes (destructive)
- limit_lambda: Throttle Lambda concurrency (safe)

Features:
- Retry logic (up to 3 attempts)
- Comprehensive error handling
- Detailed logging (debug, info, warning, error)
- Dry-run mode for safe testing
- Database audit trail
- Resource status updates
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from time import sleep
from typing import Optional

from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from app.cloud.aws.client import get_aws_client_factory
from app.models.actions import ActionLog, ActionType
from app.models.audit_log import AuditLog, AuditStatus
from app.models.resource import Resource, ResourceStatus, ResourceType

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    """Status of execution attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    DRY_RUN = "dry_run"


@dataclass
class ExecutionResult:
    """Result of executing an action.

    Attributes:
        status: SUCCESS, FAILED, RETRYING, or DRY_RUN
        attempt: Current attempt number (1-3)
        message: Human-readable status message
        error: Error details if failed
        audit_log_id: Reference to audit log entry
        dry_run: Whether this was a simulation
    """

    status: ExecutionStatus
    attempt: int
    message: str
    error: Optional[str] = None
    audit_log_id: Optional[int] = None
    dry_run: bool = False


class AWSExecutor:
    """Execute cloud actions on AWS resources with retry and error handling.

    Configuration:
    - MAX_RETRIES: Maximum retry attempts (default 3)
    - RETRY_DELAY: Delay between retries in seconds (default 2)
    - DRY_RUN_ENABLED: Enable dry-run mode by default (default False)
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self, dry_run: bool = False):
        """Initialize executor.

        Args:
            dry_run: If True, simulate actions without making changes
        """
        self.client_factory = get_aws_client_factory()
        self.dry_run = dry_run
        logger.info(f"AWSExecutor initialized (dry_run={self.dry_run})")

    def execute_action(
        self,
        db: Session,
        resource: Resource,
        action_type: str,
        decision_id: Optional[int] = None,
    ) -> ExecutionResult:
        """Execute action on resource with retry logic.

        Args:
            db: Database session
            resource: Target resource
            action_type: Type of action to execute
            decision_id: Associated decision ID (optional)

        Returns:
            ExecutionResult with status and details
        """
        logger.info(f"Starting execution: {action_type} on {resource.name}")

        # Validate action type
        if action_type not in ["stop_instance", "delete_volume", "limit_lambda"]:
            error_msg = f"Unknown action type: {action_type}"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=0,
                message=error_msg,
                error=error_msg,
                dry_run=self.dry_run,
            )

        # Create audit log entry
        audit_log = AuditLog(
            resource_id=resource.id,
            action_type=action_type,
            status=AuditStatus.PENDING,
            attempt=0,
            max_attempts=self.MAX_RETRIES,
            dry_run=self.dry_run,
            decision_id=decision_id,
            external_id=resource.external_id,
            region=resource.region,
            timestamp=datetime.utcnow(),
        )
        db.add(audit_log)
        db.commit()
        logger.debug(f"Created audit log entry: {audit_log.id}")

        # Execute with retry logic
        result = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            logger.info(f"Execution attempt {attempt}/{self.MAX_RETRIES}")

            try:
                result = self._execute_with_type(resource, action_type, attempt, audit_log)

                if result.status == ExecutionStatus.SUCCESS:
                    logger.info(f"Action succeeded: {action_type} on {resource.name}")
                    audit_log.status = AuditStatus.SUCCESS
                    audit_log.completed_at = datetime.utcnow()
                    break

                elif result.status == ExecutionStatus.DRY_RUN:
                    logger.info(f"Dry-run completed: {action_type} on {resource.name}")
                    audit_log.status = AuditStatus.SKIPPED
                    audit_log.completed_at = datetime.utcnow()
                    break

                elif attempt < self.MAX_RETRIES:
                    logger.warning(f"Attempt {attempt} failed, retrying in {self.RETRY_DELAY}s")
                    audit_log.status = AuditStatus.RETRYING
                    audit_log.attempt = attempt
                    db.commit()
                    sleep(self.RETRY_DELAY)

            except Exception as e:
                error_msg = f"Unexpected error on attempt {attempt}: {str(e)}"
                logger.error(error_msg)

                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Retrying in {self.RETRY_DELAY}s")
                    audit_log.status = AuditStatus.RETRYING
                    audit_log.attempt = attempt
                    db.commit()
                    sleep(self.RETRY_DELAY)
                else:
                    result = ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        attempt=attempt,
                        message=f"Failed after {self.MAX_RETRIES} attempts",
                        error=error_msg,
                        dry_run=self.dry_run,
                    )
                    audit_log.status = AuditStatus.FAILED
                    audit_log.error_message = error_msg

        # Update audit log with final result
        if result:
            audit_log.status = (
                AuditStatus.SUCCESS
                if result.status == ExecutionStatus.SUCCESS
                else (
                    AuditStatus.SKIPPED
                    if result.status == ExecutionStatus.DRY_RUN
                    else AuditStatus.FAILED
                )
            )
            audit_log.attempt = result.attempt
            if result.error:
                audit_log.error_message = result.error

        audit_log.completed_at = datetime.utcnow()
        db.commit()

        logger.info(
            f"Execution completed: {action_type} - {result.status if result else 'UNKNOWN'}"
        )

        # Set audit log ID in result
        if result:
            result.audit_log_id = audit_log.id

        return result or ExecutionResult(
            status=ExecutionStatus.FAILED,
            attempt=self.MAX_RETRIES,
            message="Execution failed",
            error="Unknown error",
            dry_run=self.dry_run,
        )

    # ========== Action Implementations ==========

    def _execute_with_type(
        self, resource: Resource, action_type: str, attempt: int, audit_log: AuditLog
    ) -> ExecutionResult:
        """Route to appropriate action handler.

        Args:
            resource: Target resource
            action_type: Type of action
            attempt: Current attempt number
            audit_log: Audit log entry

        Returns:
            ExecutionResult
        """
        if action_type == "stop_instance":
            return self._stop_instance(resource, attempt, audit_log)
        elif action_type == "delete_volume":
            return self._delete_volume(resource, attempt, audit_log)
        elif action_type == "limit_lambda":
            return self._limit_lambda(resource, attempt, audit_log)
        else:
            raise ValueError(f"Unknown action type: {action_type}")

    def _stop_instance(
        self, resource: Resource, attempt: int, audit_log: AuditLog
    ) -> ExecutionResult:
        """Stop EC2 instance.

        Args:
            resource: EC2 resource to stop
            attempt: Attempt number
            audit_log: Audit log entry

        Returns:
            ExecutionResult
        """
        logger.debug(f"Stopping EC2 instance: {resource.external_id} (attempt {attempt})")

        if resource.type != ResourceType.ec2:
            error_msg = f"stop_instance requires EC2 resource, got {resource.type}"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=error_msg,
                error=error_msg,
            )

        if not resource.external_id:
            error_msg = "Resource missing external_id (instance ID)"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=error_msg,
                error=error_msg,
            )

        # Dry-run mode
        if self.dry_run:
            message = f"[DRY-RUN] Would stop EC2 instance: {resource.external_id}"
            logger.info(message)
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                attempt=attempt,
                message=message,
                dry_run=True,
            )

        # Real execution
        try:
            client = self.client_factory.ec2(region_name=resource.region)
            logger.debug(f"Sending StopInstances request to AWS")
            client.stop_instances(InstanceIds=[resource.external_id], DryRun=False)
            logger.info(f"Successfully stopped EC2 instance: {resource.external_id}")
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                attempt=attempt,
                message=f"Successfully stopped EC2 instance: {resource.external_id}",
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            log_msg = f"AWS error ({error_code}): {error_msg}"
            logger.error(log_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=f"Failed to stop EC2 instance: {resource.external_id}",
                error=log_msg,
            )

    def _delete_volume(
        self, resource: Resource, attempt: int, audit_log: AuditLog
    ) -> ExecutionResult:
        """Delete EBS volume.

        Args:
            resource: EBS volume resource to delete
            attempt: Attempt number
            audit_log: Audit log entry

        Returns:
            ExecutionResult
        """
        logger.debug(f"Deleting EBS volume: {resource.external_id} (attempt {attempt})")

        # For now, S3 volumes handled here (can be expanded)
        if resource.type != ResourceType.s3:
            error_msg = f"delete_volume in context of unattached volumes, got {resource.type}"
            logger.warning(error_msg)

        if not resource.external_id:
            error_msg = "Resource missing external_id (volume ID)"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=error_msg,
                error=error_msg,
            )

        # Dry-run mode
        if self.dry_run:
            message = f"[DRY-RUN] Would delete volume/resource: {resource.external_id}"
            logger.info(message)
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                attempt=attempt,
                message=message,
                dry_run=True,
            )

        # Real execution
        try:
            # For S3: delete bucket (simplified)
            if resource.type == ResourceType.s3:
                client = self.client_factory.s3(region_name=resource.region)
                logger.debug(f"Sending DeleteBucket request to AWS")
                client.delete_bucket(Bucket=resource.external_id)
                logger.info(f"Successfully deleted S3 bucket: {resource.external_id}")
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    attempt=attempt,
                    message=f"Successfully deleted S3 bucket: {resource.external_id}",
                )

            # For EBS volumes (if applicable)
            if resource.instance_type and resource.instance_type.startswith("vol-"):
                client = self.client_factory.ec2(region_name=resource.region)
                logger.debug(f"Sending DeleteVolume request to AWS")
                client.delete_volume(VolumeId=resource.external_id)
                logger.info(f"Successfully deleted EBS volume: {resource.external_id}")
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    attempt=attempt,
                    message=f"Successfully deleted EBS volume: {resource.external_id}",
                )

            error_msg = f"Unsupported resource type for delete: {resource.type}"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=error_msg,
                error=error_msg,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            log_msg = f"AWS error ({error_code}): {error_msg}"
            logger.error(log_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=f"Failed to delete volume: {resource.external_id}",
                error=log_msg,
            )

    def _limit_lambda(
        self, resource: Resource, attempt: int, audit_log: AuditLog
    ) -> ExecutionResult:
        """Limit Lambda function concurrency.

        Args:
            resource: Lambda function resource
            attempt: Attempt number
            audit_log: Audit log entry

        Returns:
            ExecutionResult
        """
        logger.debug(f"Limiting Lambda concurrency: {resource.external_id} (attempt {attempt})")

        if resource.type != ResourceType.lambda_fn:
            error_msg = f"limit_lambda requires Lambda resource, got {resource.type}"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=error_msg,
                error=error_msg,
            )

        if not resource.external_id:
            error_msg = "Resource missing external_id (function name)"
            logger.error(error_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=error_msg,
                error=error_msg,
            )

        # Dry-run mode
        if self.dry_run:
            message = f"[DRY-RUN] Would limit Lambda concurrency: {resource.external_id} to 10"
            logger.info(message)
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                attempt=attempt,
                message=message,
                dry_run=True,
            )

        # Real execution
        try:
            client = self.client_factory.lambda_client(region_name=resource.region)
            logger.debug(f"Sending PutFunctionConcurrentExecutions request to AWS")
            client.put_function_concurrency(
                FunctionName=resource.external_id, ReservedConcurrentExecutions=10
            )
            logger.info(
                f"Successfully limited Lambda concurrency: {resource.external_id} to 10"
            )
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                attempt=attempt,
                message=f"Successfully limited Lambda concurrency: {resource.external_id} to 10",
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            log_msg = f"AWS error ({error_code}): {error_msg}"
            logger.error(log_msg)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                attempt=attempt,
                message=f"Failed to limit Lambda concurrency: {resource.external_id}",
                error=log_msg,
            )

    def batch_execute(
        self, db: Session, executions: list[dict]
    ) -> list[ExecutionResult]:
        """Execute multiple actions.

        Args:
            db: Database session
            executions: List of {"resource": Resource, "action_type": str, "decision_id": int}

        Returns:
            List of ExecutionResult objects
        """
        logger.info(f"Starting batch execution of {len(executions)} actions")
        results = []

        for i, execution in enumerate(executions, 1):
            try:
                logger.debug(f"Batch execution {i}/{len(executions)}")
                result = self.execute_action(
                    db,
                    execution["resource"],
                    execution["action_type"],
                    execution.get("decision_id"),
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Batch execution {i} failed: {str(e)}")
                results.append(
                    ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        attempt=0,
                        message=f"Batch execution failed",
                        error=str(e),
                    )
                )

        logger.info(
            f"Batch execution completed: {sum(1 for r in results if r.status == ExecutionStatus.SUCCESS)}/{len(results)} succeeded"
        )
        return results

    def get_config(self) -> dict:
        """Get executor configuration.

        Returns:
            Dictionary of configuration parameters
        """
        return {
            "max_retries": self.MAX_RETRIES,
            "retry_delay_seconds": self.RETRY_DELAY,
            "dry_run": self.dry_run,
            "supported_actions": ["stop_instance", "delete_volume", "limit_lambda"],
            "aws_regions": self.client_factory.default_region,
        }
