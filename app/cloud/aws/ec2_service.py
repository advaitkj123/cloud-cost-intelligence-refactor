from __future__ import annotations

from dataclasses import dataclass

from botocore.exceptions import ClientError

from app.cloud.aws.client import AWSClientFactory, get_aws_client_factory


@dataclass(slots=True)
class EC2InstanceDescription:
    instance_id: str
    instance_type: str
    state: str
    region: str
    tags: dict[str, str]


class AWSEC2Service:
    def __init__(self, client_factory: AWSClientFactory | None = None) -> None:
        self.client_factory = client_factory or get_aws_client_factory()

    def list_instances(self, region_name: str | None = None) -> list[EC2InstanceDescription]:
        region = region_name or self.client_factory.default_region
        client = self.client_factory.ec2(region_name=region)
        paginator = client.get_paginator("describe_instances")
        instances: list[EC2InstanceDescription] = []

        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", []) if "Key" in tag and "Value" in tag}
                    instances.append(
                        EC2InstanceDescription(
                            instance_id=instance["InstanceId"],
                            instance_type=instance.get("InstanceType", "unknown"),
                            state=instance.get("State", {}).get("Name", "unknown"),
                            region=region,
                            tags=tags,
                        )
                    )
        return instances

    def stop_instance(self, instance_id: str, region_name: str | None = None, dry_run: bool = True) -> str:
        region = region_name or self.client_factory.default_region
        if dry_run:
            return "dry-run"

        client = self.client_factory.ec2(region_name=region)
        try:
            client.stop_instances(InstanceIds=[instance_id], DryRun=False)
            return "executed"
        except ClientError as exc:
            message = exc.response.get("Error", {}).get("Message", str(exc))
            return f"failed: {message}"
