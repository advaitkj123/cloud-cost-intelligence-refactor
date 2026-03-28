from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.db.repositories.resource_repository import ResourceRepository
from app.models import actions, anomalies, cost, metrics, resource  # noqa: F401
from app.models.resource import Resource, ResourceStatus, ResourceType

SEED_RESOURCES = [
    {"name": "prod-web-01", "type": ResourceType.ec2, "region": "us-east-1", "status": ResourceStatus.running},
    {"name": "prod-worker-01", "type": ResourceType.ec2, "region": "us-east-1", "status": ResourceStatus.running},
    {"name": "checkout-handler", "type": ResourceType.lambda_fn, "region": "us-west-2", "status": ResourceStatus.active},
    {"name": "analytics-processor", "type": ResourceType.lambda_fn, "region": "eu-west-1", "status": ResourceStatus.active},
    {"name": "billing-archive", "type": ResourceType.s3, "region": "us-east-1", "status": ResourceStatus.active},
    {"name": "event-lake", "type": ResourceType.s3, "region": "eu-central-1", "status": ResourceStatus.active},
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    repo = ResourceRepository(db)
    try:
        created = 0
        for item in SEED_RESOURCES:
            if repo.get_by_name(item["name"]):
                continue
            repo.create(Resource(**item))
            created += 1
        db.commit()
        print(f"Seed completed. Created {created} resources.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
