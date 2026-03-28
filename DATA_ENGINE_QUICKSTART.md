# Data Engine Implementation - Quick Start

## 🎯 Overview

The Data Engine transforms raw cloud metrics into:
1. **Cost Estimates** - Accurate AWS pricing calculations
2. **ML Features** - 25+ engineered features for ML models
3. **Insights** - Efficiency scores, cost trends, anomalies

**Pipeline Flow**: Metrics → Cost → Features (automated every 40 seconds)

---

## 📁 New Files Created

### Core Components
- ✅ `app/cost_engine/calculator.py` - Cost calculation engine
- ✅ `app/cost_engine/__init__.py` - Module exports
- ✅ `app/feature_engineering/pipeline.py` - Feature engineering
- ✅ `app/feature_engineering/__init__.py` - Module exports
- ✅ `app/services/data_pipeline.py` - Orchestration service

### Database
- ✅ `app/models/features.py` - ML feature model with 25+ fields
- ✅ `app/db/repositories/feature_repository.py` - Feature data access

### API & Integration
- ✅ `app/api/pipeline.py` - REST endpoints for pipeline
- ✅ Updated: `app/main.py` - Added pipeline scheduling
- ✅ Updated: `app/api/routes.py` - Added pipeline router
- ✅ Updated: `app/core/dependencies.py` - Added dependencies

### Documentation
- ✅ `DATA_ENGINE_GUIDE.md` - Complete architecture guide
- ✅ `DATA_ENGINE_QUICKSTART.md` - This file

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Application is Already Configured

The data pipeline runs automatically when you start the application. No additional configuration needed!

```bash
# Start the application (data pipeline runs automatically)
uvicorn app.main:app --reload
```

### Step 2: Verify Pipeline is Running

```bash
# Check pipeline status
curl http://localhost:8000/pipeline/status

# Response:
# {
#   "status": "operational",
#   "pipeline_stages": ["metrics_collection", "cost_estimation", "feature_engineering", "storage"],
#   "supported_features": [...]
# }
```

### Step 3: Trigger Manual Processing

```bash
# Process all resources immediately
curl -X POST http://localhost:8000/pipeline/process

# Response:
# {
#   "resources_processed": 5,
#   "costs_calculated": 5,
#   "features_engineered": 5,
#   "errors": [],
#   "timestamp": "2024-03-28T10:00:00Z"
# }
```

### Step 4: View Results

```bash
# Get pipeline statistics
curl http://localhost:8000/pipeline/stats?days=30

# Get resources with latest metrics and features
curl http://localhost:8000/resources
```

---

## 🔧 Common Operations

### Process Single Resource

```bash
curl -X POST http://localhost:8000/pipeline/process-resource/1
```

### Process Specific Providers

```bash
curl -X POST http://localhost:8000/pipeline/process-providers \
  -H "Content-Type: application/json" \
  -d '{"providers": ["aws"]}'
```

### Get Pipeline Statistics

```bash
# Last 30 days (default)
curl http://localhost:8000/pipeline/stats

# Last 7 days
curl http://localhost:8000/pipeline/stats?days=7
```

### Clean Up Old Records

```bash
# Delete features older than 90 days
curl -X POST http://localhost:8000/pipeline/cleanup?days=90
```

---

## 📊 What Gets Calculated

### Cost Estimation

| Resource Type | Cost Formula | Example |
|---|---|---|
| **EC2** | hours × $0.096 + data_transfer × $0.02/GB | $2.30/day |
| **Lambda** | invocations × $0.20M + GB-seconds × rate | $0.50/day |
| **S3** | storage × $0.023/GB-month + requests | $5.00/day |

### Feature Engineering

**25+ Features Computed:**

- **Cost Features** (3): delta, rolling_mean, rolling_std
- **CPU Features** (3): avg, rolling_mean, rolling_std  
- **Memory Features** (1): avg
- **Storage Features** (1): total
- **Network Features** (3): total, rolling_in, rolling_out
- **Request Features** (3): count, rolling_mean, rolling_std
- **Service Features** (2): service_ratio, efficiency_score
- **Time Features** (4): sin, cos, day_of_week, hour_of_day
- **Quality Features** (2): metric_count, data_quality

---

## 📈 Example Results

### Resource with Features

```json
{
  "id": 1,
  "name": "web-server-01",
  "type": "ec2",
  "latest_cpu": 45.2,
  "latest_cost": 2.30,
  "features": {
    "cost_delta": 0.05,
    "cost_rolling_mean": 2.25,
    "cpu_avg": 44.8,
    "efficiency_score": 85.5,
    "time_sin": 0.707,
    "time_cos": 0.707
  }
}
```

### Pipeline Statistics

```json
{
  "period_days": 30,
  "cost_records_count": 2160,
  "features_count": 2160,
  "total_cost_estimate": 69.00,
  "avg_cost_per_record": 0.032
}
```

---

## 🔄 Automatic Scheduling

### Default Timeline

```
Time        Event
------------------------------------------
00:00       Collection cycle 1 (metrics)
00:20       Collection cycle 2 (metrics)
00:40       Collection cycle 3 + Pipeline (costs + features)
01:00       Collection cycle 4 + Pipeline
01:20       Collection cycle 5 + Pipeline
...
```

**Key Points:**
- Collection: Every 20 seconds (configurable)
- Pipeline: Every 40 seconds (2× collection interval)
- Automatic retries on failure
- Coalescing of missed cycles

### Customize Interval

Edit `.env`:

```env
# Faster (10 second collection, 20 second pipeline)
SCHEDULER_INTERVAL_SECONDS=10

# Slower (120 second collection, 240 second pipeline)
SCHEDULER_INTERVAL_SECONDS=120
```

---

## 📊 Viewing Data

### In Database

```sql
-- See latest features for a resource
SELECT f.* FROM features f
WHERE f.resource_id = 1
ORDER BY f.timestamp DESC
LIMIT 10;

-- Cost trends
SELECT f.timestamp, c.estimated_cost, f.efficiency_score
FROM cost_records c
JOIN features f ON c.resource_id = f.resource_id 
  AND c.timestamp = f.timestamp
WHERE c.resource_id = 1
ORDER BY c.timestamp DESC;

-- Average efficiency by resource
SELECT r.name, AVG(f.efficiency_score) as avg_efficiency
FROM features f
JOIN resources r ON f.resource_id = r.id
GROUP BY r.id
ORDER BY avg_efficiency DESC;
```

### Via Dashboard

The frontend connects to `/resources` endpoint which returns:
- Latest metrics
- Latest costs
- Latest features
- Efficiency scores
- All data needed for visualizations

---

## 📝 Configuration

### Pricing Settings

Default values in `app/core/config.py`:

| Setting | Default | Use |
|---------|---------|-----|
| `ec2_hourly_rate` | $0.096 | EC2 cost calculation |
| `lambda_request_cost_per_million` | $0.20 | Lambda invocation cost |
| `lambda_duration_cost_per_gb_second` | $0.0000166667 | Lambda compute cost |
| `s3_storage_cost_per_gb_month` | $0.023 | S3 storage cost |

Override in `.env`:

```env
EC2_HOURLY_RATE=0.12
LAMBDA_REQUEST_COST_PER_MILLION=0.25
S3_STORAGE_COST_PER_GB_MONTH=0.03
```

### Feature Engineering

Rolling window for statistics:

```python
# In feature_engineering/pipeline.py
ROLLING_WINDOW_DAYS = 7  # 7-day rolling average
MIN_SAMPLES_FOR_ROLLING = 10  # Minimum metrics to compute
```

---

## 🔍 Monitoring & Debugging

### Check Logs

```bash
# View recent pipeline executions
grep "Data pipeline" app.log

# Example output:
# Data pipeline cycle completed: 5 resources processed, 
# 5 costs, 5 features, 0 errors
```

### Check for Errors

```bash
# Monitor for pipeline errors
curl http://localhost:8000/pipeline/process | jq '.errors'

# Result: [] (no errors) or list of error messages
```

### Performance Check

```bash
# How many resources are processing?
curl http://localhost:8000/pipeline/stats | jq '.features_count'

# If this keeps growing steadily, pipeline is working correctly
```

---

## 🛠️ Troubleshooting

### No Costs Calculated

1. Check that there are metrics:
   ```bash
   curl http://localhost:8000/resources | jq '.[0].latest_cpu'
   ```

2. Check logs for errors:
   ```bash
   grep "Cost calculation\|Pipeline\|ERROR" app.log
   ```

3. Trigger manual pipeline:
   ```bash
   curl -X POST http://localhost:8000/pipeline/process
   ```

### Features Show as 0

1. Features require rolling window data (7 days)
2. New resources may take time to accumulate
3. Check data_quality field:
   ```bash
   curl http://localhost:8000/pipeline/stats | jq '.avg_cost_per_record'
   ```

### High CPU/Memory Usage

1. Reduce collection interval:
   ```env
   # Less frequent (240 seconds instead of 20)
   SCHEDULER_INTERVAL_SECONDS=240
   ```

2. Clean up old records:
   ```bash
   curl -X POST http://localhost:8000/pipeline/cleanup?days=60
   ```

---

## 📚 Next Steps

1. **Explore Features** - See `DATA_ENGINE_GUIDE.md` for detailed documentation
2. **Integrate with Anomaly Detection** - Use `cost_delta` feature
3. **Create Visualizations** - Dashboard shows cost trends
4. **Set Up Alerts** - Alert on high efficiency_score drops
5. **Optimize Resources** - Use insights for scaling decisions

---

## 🎓 Understanding the Features

### Efficiency Score

```
efficiency_score = (service_ratio / cpu_pct) × 10
```

Ranges from 0-100:
- 80+: Very efficient (many requests, low CPU)
- 60-80: Good efficiency
- 40-60: Normal
- <40: Low efficiency (high CPU, few requests)

### Cost Delta

Difference between current and previous period cost:
- Positive: Cost increased
- Negative: Cost decreased
- Large swings: Potential anomalies

### Time Encoding

Sin/Cos of hour enables neural networks to understand:
- Hour 0 and Hour 23 are close (just before/after midnight)
- Hour 12 is 180° away (opposite of hour 0)

Used by time-series models for seasonality.

---

## 💡 Tips & Best Practices

1. **Always have metrics first** - Pipeline needs data to work
2. **Check data_quality** - Ensure metrics are being collected properly
3. **Use rolling statistics** - More reliable than single points
4. **Clean up old records** - Prevents database bloat
5. **Monitor error rates** - Address issues early
6. **Test manual triggers** - Ensure pipeline works before going live

---

## 🆘 Support

For issues or questions:

1. Check `DATA_ENGINE_GUIDE.md` for architecture details
2. Review logs: `grep -i "pipeline\|error" app.log`
3. Test manual endpoints: `curl http://localhost:8000/pipeline/process`
4. Check database: Connect to PostgreSQL and query directly

---

**Status**: ✅ **READY TO USE**

The data pipeline is fully integrated and runs automatically. Start collecting costs and features today!
