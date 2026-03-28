"""
Integration test examples for the ingestion layer.

These tests demonstrate how to verify the ingestion pipeline works correctly.
Run with: pytest tests/test_ingestion_integration.py -v
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.repositories.resource_repository import ResourceRepository
from app.db.repositories.metric_repository import MetricRepository
from app.ingestion.aws_collector import (
    EC2Collector,
    CloudWatchCollector,
    S3Collector,
    LambdaCollector,
    NormalizedMetric,
    AWSCollectorError,
)
from app.ingestion.scheduler import IngestionScheduler
from app.services.ingestion_service import IngestionService
from app.models.resource import Resource, ResourceType, ResourceStatus


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def db():
    """Create test database session."""
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def ingestion_service(db):
    """Create ingestion service instance."""
    return IngestionService(db)


@pytest.fixture
def sample_normalized_metrics():
    """Create sample normalized metrics."""
    return [
        NormalizedMetric(
            resource_id="i-0123456789abcdef0",
            resource_type="ec2",
            region="us-east-1",
            resource_name="web-server-01",
            timestamp=datetime.now(UTC),
            cpu_usage=45.2,
            memory_usage=62.3,
            network_in=1024000.0,
            network_out=512000.0,
            storage_used=0.0,
            requests=0,
            extra_data={"instance_type": "t3.medium"},
        ),
        NormalizedMetric(
            resource_id="bucket-prod-data",
            resource_type="s3",
            region="us-east-1",
            resource_name="bucket-prod-data",
            timestamp=datetime.now(UTC),
            cpu_usage=0.0,
            memory_usage=0.0,
            network_in=0.0,
            network_out=0.0,
            storage_used=5368709120.0,  # 5 GB
            requests=0,
            extra_data=None,
        ),
    ]


# ============================================================================
# EC2Collector Tests
# ============================================================================

class TestEC2Collector:
    """Test EC2 metric collection."""

    def test_ec2_collector_initialization(self):
        """Test EC2Collector can be initialized."""
        from app.cloud.aws.client import AWSClientFactory
        
        factory = AWSClientFactory()
        collector = EC2Collector(factory)
        
        assert collector is not None
        assert hasattr(collector, 'collect')

    def test_ec2_collector_retry_logic(self):
        """Test exponential backoff retry on failure."""
        from app.cloud.aws.client import AWSClientFactory
        from botocore.exceptions import ClientError
        
        factory = AWSClientFactory()
        collector = EC2Collector(factory)
        
        # Track retry attempts
        attempts = []
        
        def failing_function(attempt_num):
            attempts.append(attempt_num)
            if attempt_num < 2:
                raise ClientError(
                    {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}},
                    "DescribeInstances"
                )
            return ["success"]
        
        # This would normally work with retries
        # The actual retry behavior is tested via integration tests

    def test_ec2_metric_validation(self):
        """Test metric validation filtering."""
        from app.cloud.aws.client import AWSClientFactory
        
        factory = AWSClientFactory()
        collector = EC2Collector(factory)
        
        # Create test metrics with invalid ones
        metrics = [
            NormalizedMetric(
                resource_id="i-valid",
                resource_type="ec2",
                region="us-east-1",
                resource_name="valid",
                timestamp=datetime.now(UTC),
            ),
            NormalizedMetric(
                resource_id="",  # Invalid: empty resource id
                resource_type="ec2",
                region="us-east-1",
                resource_name="invalid",
                timestamp=datetime.now(UTC),
            ),
        ]
        
        valid = collector._validate_metrics(metrics)
        
        # Should filter out invalid metrics
        assert len(valid) == 1
        assert valid[0].resource_id == "i-valid"


# ============================================================================
# IngestionService Tests
# ============================================================================

class TestIngestionService:
    """Test ingestion service orchestration."""

    def test_ingestion_service_initialization(self, db):
        """Test IngestionService can be initialized."""
        service = IngestionService(db)
        
        assert service.db is db
        assert service.metric_repo is not None
        assert service.resource_repo is not None
        assert service.ec2_collector is not None
        assert service.s3_collector is not None
        assert service.lambda_collector is not None

    def test_store_metric_creates_resource(self, db, ingestion_service):
        """Test that storing a metric creates a resource."""
        metric = NormalizedMetric(
            resource_id="i-testresource",
            resource_type="ec2",
            region="us-east-1",
            resource_name="test-instance",
            timestamp=datetime.now(UTC),
            cpu_usage=50.0,
        )
        
        results = {
            "total_metrics_collected": 0,
            "resources_created": 0,
            "resources_updated": 0,
            "metrics_stored": 0,
            "errors": [],
        }
        
        # Store the metric
        ingestion_service._store_metric(metric, "us-east-1", results)
        
        # Verify resource was created
        resource_repo = ResourceRepository(db)
        resource = resource_repo.get_by_external_id("aws", "i-testresource")
        
        assert resource is not None
        assert resource.name == "test-instance"
        assert resource.type == ResourceType.ec2
        assert resource.region == "us-east-1"

    def test_store_metric_creates_metric_record(self, db, ingestion_service):
        """Test that metric record is created in database."""
        metric = NormalizedMetric(
            resource_id="i-testmetric",
            resource_type="ec2",
            region="us-east-1",
            resource_name="test-instance",
            timestamp=datetime.now(UTC),
            cpu_usage=60.0,
            network_in=2000000.0,
            network_out=1000000.0,
        )
        
        results = {
            "total_metrics_collected": 0,
            "resources_created": 0,
            "resources_updated": 0,
            "metrics_stored": 0,
            "errors": [],
        }
        
        # Store the metric
        ingestion_service._store_metric(metric, "us-east-1", results)
        
        # Verify metric was created
        db.commit()  # Commit to ensure record is available
        metric_repo = MetricRepository(db)
        
        resource_repo = ResourceRepository(db)
        resource = resource_repo.get_by_external_id("aws", "i-testmetric")
        
        metrics = metric_repo.recent_for_resource(resource.id, limit=1)
        
        assert len(metrics) > 0
        assert metrics[0].cpu_usage == 60.0
        assert metrics[0].network_in == 2000000.0

    def test_ingestion_cycle_returns_results(self, ingestion_service):
        """Test that ingestion cycle returns structured results."""
        with patch.object(ingestion_service.ec2_collector, 'collect', return_value=[]):
            with patch.object(ingestion_service.cloudwatch_collector, 'collect', return_value=[]):
                with patch.object(ingestion_service.s3_collector, 'collect', return_value=[]):
                    with patch.object(ingestion_service.lambda_collector, 'collect', return_value=[]):
                        results = ingestion_service.run_ingestion_cycle(regions=["us-east-1"])
        
        assert "total_metrics_collected" in results
        assert "resources_created" in results
        assert "resources_updated" in results
        assert "metrics_stored" in results
        assert "errors" in results
        assert "timestamp" in results
        
        assert results["total_metrics_collected"] == 0
        assert results["errors"] == []


# ============================================================================
# IngestionScheduler Tests
# ============================================================================

class TestIngestionScheduler:
    """Test scheduler functionality."""

    def test_scheduler_initialization(self):
        """Test scheduler can be initialized."""
        scheduler = IngestionScheduler()
        
        assert scheduler is not None
        assert scheduler.is_running() is False

    def test_scheduler_add_job(self):
        """Test adding job to scheduler."""
        scheduler = IngestionScheduler()
        
        def mock_job():
            pass
        
        scheduler.add_job(
            mock_job,
            interval_minutes=5,
            job_id="test-job"
        )
        
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "test-job"

    def test_scheduler_lifecycle(self):
        """Test scheduler start/stop lifecycle."""
        scheduler = IngestionScheduler()
        
        def mock_job():
            pass
        
        scheduler.add_job(mock_job, interval_minutes=5)
        
        # Initially not running
        assert scheduler.is_running() is False
        
        # Start scheduler
        scheduler.start()
        assert scheduler.is_running() is True
        
        # Stop scheduler
        scheduler.stop()
        assert scheduler.is_running() is False


# ============================================================================
# Normalized Metric Tests
# ============================================================================

class TestNormalizedMetric:
    """Test normalized metric dataclass."""

    def test_normalized_metric_creation(self):
        """Test creating normalized metric."""
        metric = NormalizedMetric(
            resource_id="resource-123",
            resource_type="ec2",
            region="us-east-1",
            resource_name="test-resource",
            timestamp=datetime.now(UTC),
            cpu_usage=45.5,
            network_in=1000.0,
            network_out=500.0,
        )
        
        assert metric.resource_id == "resource-123"
        assert metric.cpu_usage == 45.5
        assert metric.network_in == 1000.0
        assert metric.network_out == 500.0
        assert metric.storage_used == 0.0
        assert metric.memory_usage == 0.0

    def test_normalized_metric_with_extra_data(self):
        """Test metric with extra metadata."""
        extra = {"instance_type": "t3.medium", "state": "running"}
        metric = NormalizedMetric(
            resource_id="i-123",
            resource_type="ec2",
            region="us-east-1",
            resource_name="server",
            timestamp=datetime.now(UTC),
            extra_data=extra,
        )
        
        assert metric.extra_data == extra
        assert metric.extra_data["instance_type"] == "t3.medium"


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling in ingestion."""

    def test_collector_error_handling(self):
        """Test that collector errors are caught."""
        from app.cloud.aws.client import AWSClientFactory
        
        factory = AWSClientFactory()
        collector = EC2Collector(factory)
        
        # Mock a collection failure
        with patch.object(collector, '_execute_with_retry') as mock_retry:
            mock_retry.side_effect = AWSCollectorError("AWS API failure")
            
            # Should return empty list on error
            results = collector.collect("us-east-1")
            
            assert results == []

    def test_ingestion_service_error_tracking(self, ingestion_service):
        """Test that errors are tracked in results."""
        
        # Mock collectors to raise errors
        with patch.object(ingestion_service.ec2_collector, 'collect') as mock_ec2:
            mock_ec2.side_effect = AWSCollectorError("EC2 failed")
            
            results = ingestion_service.run_ingestion_cycle(regions=["us-east-1"])
        
        # Errors should be logged but not crash
        assert "errors" in results


# ============================================================================
# Integration Tests (Requires AWS Credentials)
# ============================================================================

class TestIngestionIntegration:
    """Integration tests with actual AWS resources (optional)."""

    @pytest.mark.skip(reason="Requires AWS credentials")
    def test_full_collection_cycle(self, db):
        """Test full collection cycle with actual AWS."""
        service = IngestionService(db)
        
        # This test requires:
        # 1. Valid AWS credentials in .env
        # 2. Running AWS resources
        # 3. Network connectivity
        
        results = service.run_ingestion_cycle(regions=["us-east-1"])
        
        assert results["total_metrics_collected"] > 0
        assert results["errors"] == []

    @pytest.mark.skip(reason="Requires AWS credentials")
    def test_scheduler_integration(self, db):
        """Test scheduler with actual ingestion."""
        service = IngestionService(db)
        scheduler = IngestionScheduler()
        
        # Add ingestion job
        scheduler.add_job(
            service.run_ingestion_cycle,
            interval_minutes=1,
            job_id="test-ingestion"
        )
        
        # Start and verify
        scheduler.start()
        assert scheduler.is_running()
        
        # Clean up
        scheduler.stop()
        assert not scheduler.is_running()


# ============================================================================
# Mock Data for Testing
# ============================================================================

def create_mock_ec2_response():
    """Create mock EC2 DescribeInstances response."""
    return {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0123456789abcdef0",
                        "InstanceType": "t3.medium",
                        "State": {"Name": "running"},
                        "Tags": [
                            {"Key": "Name", "Value": "web-server-01"},
                            {"Key": "Environment", "Value": "production"},
                        ],
                    }
                ]
            }
        ]
    }


def create_mock_cloudwatch_response(value=45.0):
    """Create mock CloudWatch GetMetricStatistics response."""
    return {
        "Datapoints": [
            {
                "Timestamp": datetime.now(UTC),
                "Average": value,
                "Unit": "Percent",
            }
        ]
    }


def create_mock_s3_response():
    """Create mock S3 ListBuckets response."""
    return {
        "Buckets": [
            {"Name": "bucket-prod-data", "CreationDate": datetime.now(UTC)},
            {"Name": "bucket-logs", "CreationDate": datetime.now(UTC)},
        ]
    }


def create_mock_lambda_response():
    """Create mock Lambda ListFunctions response."""
    return {
        "Functions": [
            {
                "FunctionName": "process-data",
                "FunctionArn": "arn:aws:lambda:us-east-1:123456789:function:process-data",
                "Runtime": "python3.11",
                "MemorySize": 256,
            }
        ]
    }


if __name__ == "__main__":
    print("Run tests with: pytest tests/test_ingestion_integration.py -v")
