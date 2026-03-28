# Cloud Ingestion Layer Documentation

## Overview

The ingestion layer continuously collects real-time cloud metrics from AWS services and stores them in a PostgreSQL database. It provides:

- **Multiple AWS collectors**: EC2, CloudWatch, S3, Lambda
- **Unified normalization**: All metrics normalized to a consistent schema
- **Error resilience**: Exponential backoff retry logic
- **Database integration**: Automatic resource creation/updates and metric storage
- **Scheduled collection**: Runs every 5 minutes via APScheduler
- **API endpoints**: Manual ingestion triggers and status monitoring

## Architecture

```
AWS Services
    ↓
Collectors (EC2, CloudWatch, S3, Lambda)
    ↓
NormalizedMetric Schema
    ↓
IngestionService (Orchestration & Storage)
    ↓
Database (Resources + Metrics)
```

## Components

### 1. AWS Collectors (`aws_collector.py`)

#### Base Class: `AWSCollectorBase`
- Provides retry logic with exponential backoff
- Configurable max retries (default: 3)
- Base wait time: 1 second, doubles with each retry
- Validates metrics before storage

#### EC2Collector
- Collects instance metadata (ID, type, state, tags)
- Fetches CPU utilization from CloudWatch
- Properties tracked:
  - `cpu_usage`: CPU utilization percentage
  - `extra_data`: Instance type, state, tags

#### CloudWatchCollector
- Collects network metrics for running instances
- Properties tracked:
  - `network_in`: Bytes received (5-minute total)
  - `network_out`: Bytes transmitted (5-minute total)

#### S3Collector
- Lists all S3 buckets
- Retrieves storage size from CloudWatch
- Properties tracked:
  - `storage_used`: Bucket size in bytes

#### LambdaCollector
- Lists all Lambda functions
- Collects invocation and duration metrics
- Properties tracked:
  - `requests`: Total invocations in period
  - `extra_data`: Duration (ms), runtime, memory size

### 2. Normalized Metric Schema

All collectors output `NormalizedMetric` objects:

```python
@dataclass
class NormalizedMetric:
    resource_id: str        # AWS resource ID (e.g., i-0123456789abcdef0)
    resource_type: str      # Resource type (ec2, s3, lambda, etc.)
    region: str             # AWS region
    resource_name: str      # Human-readable name
    timestamp: datetime     # Collection timestamp (UTC)
    cpu_usage: float        # CPU percentage (0-100)
    memory_usage: float     # Memory percentage (0-100)
    network_in: float       # Bytes in
    network_out: float      # Bytes out
    storage_used: float     # Storage in bytes
    requests: int           # Request count
    extra_data: dict | None # Provider-specific metadata
```

### 3. Ingestion Service (`ingestion_service.py`)

Orchestrates the full ingestion pipeline:

1. **Collection**: Calls all collectors for specified regions
2. **Normalization**: Works with normalized metrics
3. **Resource Management**: Creates/updates resources using `upsert_cloud_resource`
4. **Metric Storage**: Stores metrics in the database
5. **Error Handling**: Logs failures without crashing
6. **Commit**: All changes transaction-safe

#### Key Methods

```python
# Run complete cycle across all collectors
results = ingestion_service.run_ingestion_cycle(regions=["us-east-1", "us-west-2"])

# Ingest specific region
results = ingestion_service.ingest_region("us-east-1")

# Ingest multiple regions
results = ingestion_service.ingest_all_regions(["us-east-1", "us-west-2"])
```

#### Results Dictionary

```python
{
    "total_metrics_collected": 42,      # Metrics from all collectors
    "resources_created": 0,              # New resources added
    "resources_updated": 5,              # Existing resources updated
    "metrics_stored": 42,                # Metrics stored successfully
    "errors": [],                        # List of errors encountered
    "timestamp": "2024-03-28T10:00:00Z"  # Cycle completion time
}
```

### 4. Scheduler (`scheduler.py`)

`IngestionScheduler` manages periodic execution using APScheduler:

```python
scheduler = IngestionScheduler()
scheduler.add_job(
    func=ingestion_service.run_ingestion_cycle,
    interval_minutes=5,
    job_id="aws-ingestion"
)
scheduler.start()
scheduler.stop()
```

## Error Handling

### Exponential Backoff Retry

When AWS APIs fail:

1. **Attempt 1**: Immediate retry
2. **Attempt 2**: Wait 2s + jitter, retry
3. **Attempt 3**: Wait 4s + jitter, retry
4. **Failure**: Log error, continue with other collectors

```python
wait_time = base_wait * (2^attempt) + (1 * attempt)
```

### Empty Datapoints

- Handles CloudWatch metrics with no datapoints
- Returns 0.0 instead of failing
- Validates metrics before storage
- Logs skipped metrics

### Validation

```python
def _validate_metrics(metrics) -> list[NormalizedMetric]:
    # Filters null metrics
    # Validates resource_id is not empty
    # Logs validation results
```

## Integration

### Application Startup

In `app/main.py`, the ingestion job is added to the scheduler on startup:

```python
if settings.cloud_collector_mode.lower() == "aws":
    scheduler.add_job(
        run_ingestion_cycle,
        trigger="interval",
        seconds=settings.scheduler_interval_seconds,
        id="aws-ingestion",
    )
```

### Dependencies

Add to FastAPI dependencies:

```python
def get_ingestion_service(db: Session = Depends(get_db)) -> IngestionService:
    return IngestionService(db)
```

## API Endpoints

### Manual Ingestion Trigger

```bash
POST /ingestion/trigger
POST /ingestion/trigger/{region}
```

Example:

```bash
curl -X POST http://localhost:8000/ingestion/trigger \
  -H "Content-Type: application/json" \
  -d '{"regions": ["us-east-1", "us-west-2"]}'
```

### Status Check

```bash
GET /ingestion/status
```

## Configuration

Set environment variables in `.env`:

```env
CLOUD_COLLECTOR_MODE=aws
AWS_ACCESS_KEY=your-key
AWS_SECRET_KEY=your-secret
AWS_REGION=us-east-1
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=300  # 5 minutes
```

## Database Schema

Metrics are stored in the `metrics` table:

```sql
-- Resources table
CREATE TABLE resources (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(64),              -- ec2, s3, lambda, etc
    region VARCHAR(64),
    status VARCHAR(64),
    provider VARCHAR(32),          -- aws, simulated, etc
    external_id VARCHAR(255),      -- AWS resource ID
    instance_type VARCHAR(64),
    cloud_state VARCHAR(64),
    tags_json TEXT,
    created_at TIMESTAMP
);

-- Metrics table
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY,
    resource_id INTEGER REFERENCES resources(id),
    timestamp TIMESTAMP NOT NULL,
    cpu_usage FLOAT DEFAULT 0.0,
    memory_usage FLOAT DEFAULT 0.0,
    requests INTEGER DEFAULT 0,
    storage_used FLOAT DEFAULT 0.0,
    network_in FLOAT DEFAULT 0.0,
    network_out FLOAT DEFAULT 0.0,
    
    INDEX ix_metrics_resource_timestamp (resource_id, timestamp)
);
```

## Example Usage

### Programmatic

```python
from app.db.session import SessionLocal
from app.services.ingestion_service import IngestionService

db = SessionLocal()
try:
    ingestion = IngestionService(db)
    
    # Run full cycle
    results = ingestion.run_ingestion_cycle(regions=["us-east-1"])
    print(f"Collected {results['total_metrics_collected']} metrics")
    
    # Or specific region
    results = ingestion.ingest_region("us-west-2")
    
finally:
    db.close()
```

### Via REST API

```python
import requests

# Trigger ingestion
response = requests.post(
    "http://localhost:8000/ingestion/trigger",
    json={"regions": ["us-east-1"]}
)
print(response.json())

# Check status
status = requests.get("http://localhost:8000/ingestion/status")
print(status.json())
```

## Logging

All operations are logged with levels:

- **INFO**: Cycle start/completion, job additions, scheduler state
- **DEBUG**: Individual metric collection details
- **WARNING**: Retry attempts, skipped metrics, CloudWatch failures
- **ERROR**: Collection failures, storage errors, unexpected exceptions

Example log output:

```
2024-03-28 10:00:00 | INFO | cost_intelligence | Starting ingestion cycle for regions: ['us-east-1']
2024-03-28 10:00:01 | DEBUG | cost_intelligence | EC2Collector collected 5 metrics from us-east-1
2024-03-28 10:00:02 | DEBUG | cost_intelligence | Stored metric for resource 1 (name: web-server-01)
2024-03-28 10:00:15 | INFO | cost_intelligence | Ingestion cycle finished. Results: 42 metrics, 2 resources created, 0 errors
```

## Performance Considerations

- **Batch collection**: All collectors run sequentially per region
- **Lightweight validation**: Minimal overhead during metric storage
- **Connection pooling**: Reuses database connections via SQLAlchemy
- **CloudWatch API limits**: Subject to AWS API rate limits (15 requests/second)
- **S3 list**: Limited to 1000 buckets per API call

## Troubleshooting

### No metrics collected

1. Check AWS credentials in `.env`
2. Verify IAM permissions for EC2, CloudWatch, S3, Lambda
3. Check cloud collector mode: `CLOUD_COLLECTOR_MODE=aws`
4. Review logs for specific collection errors

### High error rate

1. Check AWS API rate limits
2. Verify network connectivity
3. Review CloudWatch for API throttling
4. Check IAM policy limits

### Scheduler not running

1. Ensure `SCHEDULER_ENABLED=true`
2. Check `SCHEDULER_INTERVAL_SECONDS` setting
3. Review application startup logs
4. Verify background process is not killed

## Future Enhancements

- [ ] Azure/GCP collectors
- [ ] Batch metric insertion for better performance
- [ ] Metric aggregation before storage
- [ ] Custom metric derivation (e.g., cost per metric)
- [ ] Webhook notifications on collection failures
- [ ] Metrics caching layer
- [ ] Dead letter queue for failed collections
