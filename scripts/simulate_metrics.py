import time

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.db.repositories.resource_repository import ResourceRepository
from app.models import actions, anomalies, cost, metrics, resource  # noqa: F401
from app.services.collector import CloudMetricCollector
from app.services.orchestrator import MetricOrchestrator


def main(cycles: int = 5, sleep_seconds: int = 2) -> None:
    Base.metadata.create_all(bind=engine)
    collector = CloudMetricCollector()
    for cycle in range(cycles):
        db = SessionLocal()
        try:
            resources = ResourceRepository(db).list_all()
            orchestrator = MetricOrchestrator(db)
            for resource in resources:
                metric = collector.generate_metric(resource)
                response = orchestrator.ingest_metric(metric)
                print(
                    f"cycle={cycle + 1} resource={resource.name} metric_id={response.metric_id} anomaly={response.anomaly_detected}"
                )
        finally:
            db.close()
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
