# Ingestion Layer - Quick Start Guide

## 🚀 5-Minute Setup

### Step 1: Configure AWS Credentials

Edit `.env` file:

```env
# AWS Configuration
CLOUD_COLLECTOR_MODE=aws
AWS_ACCESS_KEY=your-aws-access-key
AWS_SECRET_KEY=your-aws-secret-key
AWS_REGION=us-east-1

# Scheduler (already configured in defaults)
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=300  # 5 minutes
```

### Step 2: Verify IAM Permissions

Your AWS IAM user needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation",
        "lambda:ListFunctions",
        "lambda:GetFunction"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 3: Run the Application

```bash
# Start the FastAPI server
uvicorn app.main:app --reload

# Or with Python
python -m uvicorn app.main:app --reload
```

The ingestion will automatically start collecting every 5 minutes.

### Step 4: Check Status

```bash
# Check if ingestion is running
curl http://localhost:8000/ingestion/status

# Response:
# {
#   "status": "operational",
#   "supported_collectors": ["ec2", "cloudwatch", "s3", "lambda"],
#   ...
# }
```

### Step 5: View Collected Data

```bash
# Get all resources with latest metrics
curl http://localhost:8000/resources

# Response will show:
# [
#   {
#     "id": 1,
#     "name": "web-server-01",
#     "type": "ec2",
#     "region": "us-east-1",
#     "latest_cpu": 45.2,
#     "latest_network_in": 1024000.0,
#     ...
#   },
#   ...
# ]
```

## 🔧 Common Operations

### Manually Trigger Collection

```bash
# For default region (us-east-1)
curl -X POST http://localhost:8000/ingestion/trigger

# For specific region
curl -X POST http://localhost:8000/ingestion/trigger/us-west-2

# For multiple regions
curl -X POST http://localhost:8000/ingestion/trigger \
  -H "Content-Type: application/json" \
  -d '{"regions": ["us-east-1", "us-west-2"]}'
```

### Response Format

```json
{
  "total_metrics_collected": 42,
  "resources_created": 2,
  "resources_updated": 5,
  "metrics_stored": 42,
  "errors": [],
  "timestamp": "2024-03-28T10:00:00Z"
}
```

### Programmatic Usage

```python
from app.db.session import SessionLocal
from app.services.ingestion_service import IngestionService

db = SessionLocal()
try:
    ingestion = IngestionService(db)
    
    # One-liner: trigger collection
    results = ingestion.run_ingestion_cycle()
    
    # Check if successful
    if results["errors"]:
        print(f"Errors: {results['errors']}")
    else:
        print(f"✓ Collected {results['metrics_stored']} metrics")
        
finally:
    db.close()
```

## 📊 What Gets Collected

### EC2 Instances
- Instance ID, name, type, state
- CPU utilization (last 5 minutes)
- Instance metadata and tags

### CloudWatch Metrics
- Network in/out (last 5 minutes)
- Per-instance statistics

### S3 Buckets
- Bucket name and size
- Storage metrics

### Lambda Functions
- Function name and ARN
- Invocations (last 5 minutes)
- Duration metrics
- Runtime and memory configuration

## 📝 Monitoring

### View Application Logs

```bash
# Logs will show:
# - Collection cycle start/completion
# - Individual collector results
# - Resource creation/updates
# - Any errors or warnings
```

Example log output:

```
2024-03-28 10:00:00 | INFO | cost_intelligence | Starting ingestion cycle for regions: ['us-east-1']
2024-03-28 10:00:01 | DEBUG | cost_intelligence | EC2Collector collected 5 metrics from us-east-1
2024-03-28 10:00:02 | DEBUG | cost_intelligence | Stored metric for resource 1 (name: web-server-01)
2024-03-28 10:00:03 | INFO | cost_intelligence | Ingestion cycle finished. Results: 42 metrics, 2 created, 0 errors
```

### Database Queries

Check what was collected:

```sql
-- List all collected resources
SELECT id, name, type, region, provider, created_at 
FROM resources 
WHERE provider = 'aws'
ORDER BY created_at DESC;

-- List latest metrics
SELECT r.name, r.type, m.cpu_usage, m.network_in, m.network_out, m.timestamp
FROM metrics m
JOIN resources r ON m.resource_id = r.id
WHERE r.provider = 'aws'
ORDER BY m.timestamp DESC
LIMIT 100;

-- Count metrics by resource type
SELECT r.type, COUNT(m.id) as metric_count
FROM metrics m
JOIN resources r ON m.resource_id = r.id
WHERE r.provider = 'aws'
GROUP BY r.type;
```

## 🔍 Troubleshooting

### No metrics collected

**Check 1: AWS credentials**
```bash
# Verify .env has valid credentials
grep -E "AWS_ACCESS_KEY|AWS_SECRET_KEY" .env
```

**Check 2: Collector mode**
```bash
# Must be set to 'aws'
grep CLOUD_COLLECTOR_MODE .env
# Should output: CLOUD_COLLECTOR_MODE=aws
```

**Check 3: Scheduler status**
```bash
# Check logs for scheduler initialization
grep -i scheduler /var/log/app.log
# Look for "Background scheduler started"
```

**Check 4: IAM permissions**
- Log into AWS console
- Verify IAM user has required permissions
- Test with AWS CLI:
  ```bash
  aws ec2 describe-instances --region us-east-1
  aws s3 ls
  aws lambda list-functions --region us-east-1
  ```

### API endpoint not responding

```bash
# Check if server is running
curl -I http://localhost:8000/docs

# Check specific endpoint
curl -I http://localhost:8000/ingestion/status

# If 404: endpoint may not be registered
# If 500: check server logs for errors
```

### High error rate

**Likely causes:**
- AWS rate limiting (add delay between calls)
- Insufficient IAM permissions
- Network connectivity issues
- AWS service disruption

**Solution:**
1. Check CloudWatch for API throttling
2. Review IAM policy
3. Test AWS CLI connectivity
4. Verify AWS service status

## 💡 Tips & Best Practices

1. **Start with simulation mode first**
   ```env
   CLOUD_COLLECTOR_MODE=simulated
   ```
   Then switch to AWS after verifying everything works.

2. **Adjust collection interval**
   ```env
   # More frequent (1 minute)
   SCHEDULER_INTERVAL_SECONDS=60
   
   # Less frequent (30 minutes)
   SCHEDULER_INTERVAL_SECONDS=1800
   ```

3. **Use manual triggers during setup**
   ```bash
   # Before enabling scheduler, test manually
   curl -X POST http://localhost:8000/ingestion/trigger
   ```

4. **Monitor database size**
   Metrics accumulate over time. Consider:
   - Archiving old metrics
   - Setting retention policies
   - Running nightly cleanup jobs

5. **Scale for large deployments**
   - Use connection pooling
   - Batch metric inserts
   - Consider metric aggregation before storage

## 📚 Next Steps

1. **Explore the dashboard**
   - Frontend will display collected metrics
   - See resource trends over time

2. **Set up cost analysis**
   - Use collected metrics for cost calculations
   - Enable anomaly detection

3. **Configure alerts**
   - Set thresholds for metric values
   - Get notified of anomalies

4. **Automate optimization**
   - Use insights from metrics
   - Execute recommended actions

## 📖 Full Documentation

For detailed information, see:
- `app/ingestion/README.md` - Complete architectural details
- `INGESTION_IMPLEMENTATION.md` - Implementation summary
- `scripts/example_ingestion.py` - Runnable example code

## 🆘 Support

If you encounter issues:

1. **Check logs** - Most issues are visible in application logs
2. **Review configuration** - Verify .env settings
3. **Test AWS connectivity** - Use AWS CLI to verify access
4. **Check IAM permissions** - Ensure user has required policies
5. **Run example script** - `python scripts/example_ingestion.py`

---

**Ready to start?** Follow the 5-minute setup above, then trigger collection and watch the data flow in!
