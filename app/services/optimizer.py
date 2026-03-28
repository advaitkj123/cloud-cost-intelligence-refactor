from datetime import datetime

from app.cloud.aws.ec2_service import AWSEC2Service
from app.core.config import get_settings
from app.core.logger import logger
from app.db.repositories.action_repository import ActionRepository
from app.models.actions import ActionLog, ActionType
from app.models.resource import Resource, ResourceStatus, ResourceType

settings = get_settings()


class Optimizer:
    def __init__(self, action_repository: ActionRepository):
        self.action_repository = action_repository
        self.aws_ec2_service = AWSEC2Service()

    def stop_ec2_instance(self, instance_id: str, region_name: str, dry_run: bool = True) -> str:
        status = self.aws_ec2_service.stop_instance(instance_id, region_name=region_name, dry_run=dry_run)
        if dry_run:
            logger.info("DRY RUN: stop_instance requested for %s in %s", instance_id, region_name)
        else:
            logger.info("AWS stop_instance result for %s in %s: %s", instance_id, region_name, status)
        return status

    def execute(
        self,
        resource: Resource,
        action_type: ActionType,
        estimated_savings: float,
        dry_run: bool | None = None,
    ) -> tuple[ActionLog, str]:
        effective_dry_run = settings.dry_run_optimizations if dry_run is None else dry_run
        status = "dry-run"

        if action_type == ActionType.stop_instance and resource.type == ResourceType.ec2:
            if resource.provider == "aws" and resource.external_id:
                status = self.stop_ec2_instance(resource.external_id, resource.region, dry_run=effective_dry_run)
                if status == "executed":
                    resource.status = ResourceStatus.stopped
                    resource.cloud_state = "stopping"
            elif not effective_dry_run:
                resource.status = ResourceStatus.stopped
                status = "executed"
        elif not effective_dry_run:
            if action_type == ActionType.throttle_lambda and resource.type == ResourceType.lambda_fn:
                resource.status = ResourceStatus.throttled
            elif action_type == ActionType.cleanup_storage and resource.type == ResourceType.s3:
                resource.status = ResourceStatus.active
            status = "executed"

        action_log = ActionLog(
            resource_id=resource.id,
            action_type=action_type,
            timestamp=datetime.utcnow(),
            estimated_savings=estimated_savings,
        )
        created = self.action_repository.create(action_log)
        return created, status
