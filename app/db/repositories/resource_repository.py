from __future__ import annotations

import json

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.resource import Resource, ResourceStatus, ResourceType


class ResourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, resource: Resource) -> Resource:
        self.db.add(resource)
        self.db.flush()
        self.db.refresh(resource)
        return resource

    def get(self, resource_id: int) -> Resource | None:
        return self.db.get(Resource, resource_id)

    def get_by_name(self, name: str) -> Resource | None:
        return self.db.scalar(select(Resource).where(Resource.name == name))

    def get_by_external_id(self, provider: str, external_id: str) -> Resource | None:
        stmt = select(Resource).where(and_(Resource.provider == provider, Resource.external_id == external_id))
        return self.db.scalar(stmt)

    def list_all(self) -> list[Resource]:
        return list(self.db.scalars(select(Resource).order_by(Resource.id)))

    def list_by_provider(self, provider: str) -> list[Resource]:
        stmt = select(Resource).where(Resource.provider == provider).order_by(Resource.id)
        return list(self.db.scalars(stmt))

    def upsert_cloud_resource(
        self,
        *,
        name: str,
        resource_type: ResourceType,
        region: str,
        status: ResourceStatus,
        provider: str,
        external_id: str,
        instance_type: str | None = None,
        cloud_state: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> Resource:
        resource = self.get_by_external_id(provider, external_id)
        if resource is None:
            resource = Resource(
                name=name,
                type=resource_type,
                region=region,
                status=status,
                provider=provider,
                external_id=external_id,
                instance_type=instance_type,
                cloud_state=cloud_state,
                tags_json=json.dumps(tags or {}),
            )
            self.db.add(resource)
        else:
            resource.name = name
            resource.type = resource_type
            resource.region = region
            resource.status = status
            resource.instance_type = instance_type
            resource.cloud_state = cloud_state
            resource.tags_json = json.dumps(tags or {})

        self.db.flush()
        self.db.refresh(resource)
        return resource
