from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.client import BaseClient

from app.core.config import get_settings

settings = get_settings()


class AWSClientFactory:
    def __init__(self) -> None:
        self._session = boto3.Session(
            aws_access_key_id=settings.aws_access_key or None,
            aws_secret_access_key=settings.aws_secret_key or None,
            aws_session_token=settings.aws_session_token or None,
            region_name=settings.aws_region,
        )
        self._config = Config(retries={"max_attempts": 8, "mode": "standard"})

    @property
    def default_region(self) -> str:
        return settings.aws_region

    def client(self, service_name: str, region_name: str | None = None) -> BaseClient:
        target_region = region_name or self.default_region
        return self._session.client(service_name, region_name=target_region, config=self._config)

    def resource(self, service_name: str, region_name: str | None = None) -> Any:
        target_region = region_name or self.default_region
        return self._session.resource(service_name, region_name=target_region, config=self._config)

    def ec2(self, region_name: str | None = None) -> BaseClient:
        return self.client("ec2", region_name=region_name)

    def cloudwatch(self, region_name: str | None = None) -> BaseClient:
        return self.client("cloudwatch", region_name=region_name)

    def pricing(self) -> BaseClient:
        return self.client("pricing", region_name=settings.aws_pricing_region)


@lru_cache(maxsize=1)
def get_aws_client_factory() -> AWSClientFactory:
    return AWSClientFactory()
