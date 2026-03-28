# Data Engine Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cloud Cost Intelligence                      │
│                    Data Engine Architecture                      │
└─────────────────────────────────────────────────────────────────┘

                          ┌──────────────────┐
                          │  AWS Cloud       │
                          │  (EC2, S3, etc)  │
                          └────────┬─────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    │                              │
          ┌─────────▼─────────┐        ┌──────────▼───────────┐
          │  CloudWatch       │        │  AWS APIs            │
          │  Metrics          │        │  (boto3)             │
          └────────┬──────────┘        └──────────┬───────────┘
                   │                              │
                   └──────────────┬───────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  Metric Collection        │
                    │  (ingestion layer)        │
                    │  - EC2Collector           │
                    │  - CloudWatchCollector    │
                    │  - S3Collector            │
                    │  - LambdaCollector        │
                    │  (existing, phase 1)      │
                    └────────────┬───────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Metrics Database      │
                    │  (PostgreSQL)          │
                    │  - metrics table       │
                    │  - resources table     │
                    │  - timestamp index     │
                    └────────┬───────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        │         ┌──────────▼────────────┐       │
        │         │  Data Pipeline       │       │
        │         │  Service (NEW)       │       │
        │         │                      │       │
        │         │  Orchestrator that   │       │
        │         │  runs every 40s      │       │
        │         └──┬───────────────┬───┘       │
        │            │               │           │
    ┌───▼────────┐   │   ┌───────────▼───────────▼────────┐
    │  Metrics   │   │   │  Cost Engine                   │
    │  (7-day    │   │   │  Calculator (NEW)              │
    │  rolling   │   │   │                                │
    │  window)   │   │   │  - EC2 cost formula            │
    │            │   │   │  - Lambda cost formula         │
    │  Features: │   │   │  - S3 cost formula             │
    │  - cpu     │   │   │  - Cost breakdown              │
    │  - memory  │   │   │  - Monthly/annual projection   │
    │  - storage │   │   └────────┬───────────────────────┘
    │  - network │   │            │
    │  - request │   │   ┌────────▼────────────────────┐
    │            │   │   │  Cost Records               │
    │            │   │   │  (PostgreSQL)              │
    │            │   │   │  - estimated_cost          │
    │            │   │   │  - breakdown                │
    │            │   │   └─────────────────────────────┘
    │            │   │
    │            │   │   ┌─────────────────────────────┐
    │            │   └──▶│  Feature Engineering        │
    │            │       │  Pipeline (NEW)             │
    │            │       │                             │
    │            │       │  - CostFeatures (delta, μ)  │
    │            │       │  - UsageFeatures (CPU, mem) │
    │            │       │  - NetworkFeatures          │
    │            │       │  - RequestFeatures          │
    │            │       │  - ServiceFeatures (ratio)  │
    │            │       │  - TimeFeatures (sin/cos)   │
    │            │       │  - QualityFeatures          │
    │            │       │                             │
    │            │       │  Result: 25+ features/row   │
    │            │       └────────┬────────────────────┘
    │            │                │
    └────────────┼─────────────────┼────────────────────┐
                 │                 │                    │
         ┌───────▼─────────────────▼────────────────────▼──────┐
         │  Features Database                                 │
         │  (PostgreSQL - Time-Series Optimized)             │
         │                                                    │
         │  features table:                                   │
         │  ┌──────────────────────────────────────────────┐ │
         │  │ id | resource_id | timestamp | cost_delta   │ │
         │  │ .. | ........... | ......... | cpu_avg      │ │
         │  │    |             |           | efficiency   │ │
         │  │    |             |           | ... (25+)    │ │
         │  └──────────────────────────────────────────────┘ │
         │  Indexes:                                          │
         │  - (resource_id, timestamp)  ← Query by resource   │
         │  - (timestamp)               ← Time-series queries │
         │                                                    │
         │  Statistics:                                       │
         │  - Cost trends per resource                        │
         │  - Efficiency scores                               │
         │  - Data quality metrics                            │
         └──────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
    ┌───▼──────────┐    ┌────▼─────────┐   ┌──────▼──────┐
    │  REST API    │    │  Dashboard   │   │  ML Models  │
    │  Endpoints   │    │  Frontend    │   │  (Ready to  │
    │              │    │              │   │   consume)  │
    │  - /process  │    │  - Renders   │   │             │
    │  - /stats    │    │    costs     │   │  - Anomaly  │
    │  - /cleanup  │    │  - Renders   │   │    detection│
    │  - /status   │    │    features  │   │  - Forecast │
    │              │    │  - Charts    │   │  - Optimize │
    └──────────────┘    └──────────────┘   └─────────────┘
```

---

## Pipeline Execution Flow

### Background Scheduling

```
┌─────────────────────────────────────────────────────────┐
│  APScheduler (existing in application)                 │
└──┬──────────────────────────────────────────────────────┘
   │
   ├─ every 20s ──┬─► Metric Collection
   │              │   (Phase 1)
   │              │   Output: metrics table
   │
   ├─ every 40s ──┬─► Data Pipeline  ◄─── NEW
   │              │   Service.process_all_resources()
   │              │   - Reads recent metrics
   │              │   - Calculates costs
   │              │   - Engineers features
   │              │   - Stores results
   │              │   - Returns statistics
   │
   └─ manual API ─┬─► /pipeline/process
                  │   /pipeline/process-resource/{id}
                  │   /pipeline/process-providers
                  │   /pipeline/cleanup
                  │   /pipeline/stats
```

### Single Resource Processing (Per Pipeline Execution)

```
┌──────────────────────────────────┐
│  Pipeline.process_metrics_for_   │
│  resource(resource_id)           │
└────────────┬─────────────────────┘
             │
    ┌────────▼────────────┐
    │ Step 1: Get Recent  │
    │ Metrics             │
    │ (Last 1 hour)       │
    │ Query: metrics where│
    │ resource_id = id    │
    │ and timestamp >     │
    │ now() - 1 hour      │
    │                     │
    │ Result: List of     │
    │ MetricRecord        │
    └────────┬────────────┘
             │
    ┌────────▼──────────────────┐
    │ Step 2: Calculate Cost    │
    │ CostCalculator.estimate() │
    │                           │
    │ Input: resource + metrics │
    │ - get resource.type       │
    │ - route to handler        │
    │ - calculate cost formula  │
    │ - return CostEstimate     │
    │ (with breakdown)          │
    └────────┬──────────────────┘
             │
    ┌────────▼────────────────────┐
    │ Step 3: Store Cost Record  │
    │ cost_repo.create()         │
    │                            │
    │ Inserts: CostRecord        │
    │ - resource_id              │
    │ - estimated_cost           │
    │ - breakdown (JSON)         │
    │ - timestamp                │
    └────────┬────────────────────┘
             │
    ┌────────▼──────────────────┐
    │ Step 4: Get Rolling       │
    │ Metrics                   │
    │ (Last 7 days)             │
    │                           │
    │ Query: metrics where      │
    │ resource_id = id          │
    │ and timestamp >           │
    │ now() - 7 days            │
    │                           │
    │ Result: All recent        │
    │ metrics for aggregation   │
    └────────┬──────────────────┘
             │
    ┌────────▼────────────────────┐
    │ Step 5: Engineer Features  │
    │ FeatureEngineer.engineer() │
    │                            │
    │ Input: metrics (7-day)     │
    │        cost (current)      │
    │                            │
    │ Computes 25+ features:     │
    │ - cost_delta               │
    │ - cpu_avg, cpu_rolling_... │
    │ - memory_avg, ...          │
    │ - network_total, ...       │
    │ - request_count, ...       │
    │ - service_ratio, ...       │
    │ - time_sin, time_cos, ...  │
    │ - metric_count, ...        │
    │                            │
    │ Result: Feature object     │
    └────────┬────────────────────┘
             │
    ┌────────▼─────────────────┐
    │ Step 6: Store Feature    │
    │ feature_repo.create()    │
    │                          │
    │ Inserts: Feature record  │
    │ - resource_id            │
    │ - All 25+ fields         │
    │ - timestamp              │
    │ - created_at             │
    └────────┬─────────────────┘
             │
    ┌────────▼──────────────────┐
    │ Return Results            │
    │ {                         │
    │   "resource_processed": 1 │
    │   "cost_calculated": 1    │
    │   "features_engineered": 1│
    │   "errors": []            │
    │   "timestamp": "..."      │
    │ }                         │
    └──────────────────────────┘
```

---

## Data Model Relationships

```
┌────────────────────────┐
│  Resource              │
├────────────────────────┤
│ id (Primary Key)       │
│ name                   │
│ type (ec2|s3|lambda)   │
│ provider               │
│ tags (JSON)            │
│ created_at             │
└────────────────────────┘
         ▲
    1    │    *
         │ has many
         │
    ┌────┴────────────────━━┐
    │ (Cascade Delete)      │
    │                       │
    ┌─▼──────────────┐  ┌──▼────────────────┐
    │ Metrics        │  │ Features          │
    ├────────────────┤  ├───────────────────┤
    │ id              │  │ id                │
    │ resource_id ───────│ resource_id       │
    │ timestamp       │  │ timestamp         │
    │ cpu_percent     │  │ cost_delta        │
    │ memory_mb       │  │ cpu_avg           │
    │ disk_gb         │  │ effort_score      │
    │ network_bytes   │  │ efficiency_score  │
    │ request_count   │  │ time_sin          │
    │ error_count     │  │ (25+ fields)      │
    │ metadata (JSON) │  │ created_at        │
    │ created_at      │  │ metadata (JSON)   │
    └─────────────────┘  └───────────────────┘
    Indexes:             Indexes:
    - (resource_id,      - (resource_id,
      timestamp)           timestamp)
    - (timestamp)        - (timestamp)
    - (created_at)       - (created_at)


    ┌──────────────────────┐
    │ CostRecord           │  [Calculated, not raw]
    ├──────────────────────┤
    │ id                   │
    │ resource_id ─────────┬─────► Resource
    │ estimated_cost       │
    │ breakdown (JSON)     │
    │ timestamp            │
    │ created_at           │
    └──────────────────────┘
    Indexes:
    - (resource_id,
      timestamp)
    - (timestamp)
```

---

## Cost Calculation Flow

```
Input: Resource + Recent Metrics
       │
       ├─ Resource type?
       │
       ├─→ EC2
       │   ├─ Get hourly_rate ($0.096 default)
       │   ├─ Calculate: hours_running × hourly_rate
       │   ├─ Add: data_transfer_gb × $0.02/gb
       │   └─ Result: instance_cost
       │
       ├─→ Lambda  
       │   ├─ Get pricing constants
       │   ├─ Calculate: 
       │   │   (invocations / 1_000_000) × $0.20
       │   │   + (gb_seconds) × rate
       │   └─ Result: function_cost
       │
       └─→ S3
           ├─ Get storage_rate ($0.023/gb/month)
           ├─ Calculate:
           │   (storage_gb × rate) / 30
           │   + request_cost
           └─ Result: bucket_cost

Output: CostEstimate
        ├─ estimated_cost (total $)
        └─ breakdown:
           - service-specific costs
           - component costs
           - projected monthly
           - projected annual
```

---

## Feature Engineering Logic

```
Input: Metrics (7-day rolling window) + Current Cost
       │
       ├─ Cost Features
       │  ├─ Delta: current_cost - previous_cost
       │  ├─ Rolling Mean: mean(last_7_days_costs)
       │  └─ Rolling Std: std_dev(last_7_days_costs)
       │
       ├─ Usage Features
       │  ├─ CPU Avg: mean(cpu_readings)
       │  ├─ CPU Rolling Mean: mean(rolling_window(cpu))
       │  ├─ CPU Rolling Std: std_dev(rolling_window(cpu))
       │  ├─ Memory Avg: mean(memory_readings)
       │  ├─ Storage Total: sum(storage_readings)
       │  └─ Storage Rolling Mean: mean(rolling_window(storage))
       │
       ├─ Network Features
       │  ├─ Network Total: sum(network_bytes)
       │  ├─ Network In Rolling Mean: mean(rolling_in)
       │  └─ Network Out Rolling Mean: mean(rolling_out)
       │
       ├─ Request Features
       │  ├─ Request Count: sum(requests)
       │  ├─ Request Rolling Mean: mean(rolling_window(requests))
       │  └─ Request Rolling Std: std_dev(rolling_window(requests))
       │
       ├─ Service Features
       │  ├─ Service Ratio: requests / cpu_percent (if cpu > 0)
       │  └─ Efficiency Score: (service_ratio / cpu) × 10 (0-100)
       │
       ├─ Time Features
       │  ├─ Time Sin: sin(hour * 2π / 24)
       │  ├─ Time Cos: cos(hour * 2π / 24)
       │  ├─ Day of Week: 0=Mon, 1=Tue, ..., 6=Sun
       │  └─ Hour of Day: 0-23
       │
       └─ Quality Features
          ├─ Metric Count: count(metrics_in_window)
          └─ Data Quality: (metrics / expected) × 100%

Output: Feature Record (25+ fields ready for ML)
```

---

## API Request/Response Flow

```
Client Request:
┌─────────────────────────────────────┐
│ POST /pipeline/process              │
└────────────┬────────────────────────┘
             │
             ▼
        ┌────────────────┐
        │ API Router     │
        │ (api/routes.py)│
        │ (api/pipeline..py)
        └────────┬───────┘
                 │
                 ▼
        ┌─────────────────────────────┐
        │ FastAPI Endpoint            │
        │ process_pipeline_handler()  │
        │                             │
        │ 1. Get DataPipeline         │
        │    from dependencies        │
        │ 2. Call pipeline.           │
        │    process_all_resources()  │
        │ 3. Catch exceptions         │
        │ 4. Return results           │
        └────────┬────────────────────┘
                 │
                 ▼
        ┌─────────────────────────────┐
        │ DataPipeline Service        │
        │ process_all_resources()     │
        │                             │
        │ - Iterate all resources     │
        │ - Call process_metrics_for_ │
        │   resource(id) for each     │
        │ - Aggregate results         │
        │ - Return statistics         │
        └────────┬────────────────────┘
                 │
                 ▼ (for each resource)
        ┌─────────────────────────────┐
        │ DataPipeline.               │
        │ process_metrics_for_resource│
        │                             │
        │ - Get metrics               │
        │ - Calculate cost            │
        │ - Store cost                │
        │ - Aggregate metrics         │
        │ - Engineer features         │
        │ - Store features            │
        │ - Return result             │
        └────────┬────────────────────┘
                 │
                 ▼
        ┌─────────────────────────────┐
        │ Return to API Handler       │
        │ with aggregated results     │
        └────────┬────────────────────┘
                 │
                 ▼
Client Response:
┌─────────────────────────────────────┐
│ 200 OK                              │
│ {                                   │
│   "resources_processed": 5,         │
│   "costs_calculated": 5,            │
│   "features_engineered": 5,         │
│   "errors": [],                     │
│   "timestamp": "2024-03-28T..."    │
│ }                                   │
└─────────────────────────────────────┘
```

---

## Database Query Patterns

### Get Latest Features for Resource

```sql
SELECT f.* FROM features f
WHERE f.resource_id = 5
ORDER BY f.timestamp DESC
LIMIT 1;
-- Uses index: (resource_id, timestamp)
-- Time: <10ms
```

### Get Cost Trends

```sql
SELECT DATE_TRUNC('day', f.timestamp) as day,
       AVG(f.cost_delta) as avg_cost_delta,
       AVG(f.efficiency_score) as avg_efficiency
FROM features f
WHERE f.resource_id = 5
  AND f.timestamp > NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', f.timestamp)
ORDER BY day DESC;
-- Uses index: (resource_id, timestamp)
-- Time: ~50ms for 3000 records
```

### Resource Efficiency Ranking

```sql
SELECT r.id, r.name,
       AVG(f.efficiency_score) as avg_efficiency,
       COUNT(f.id) as feature_count
FROM resources r
LEFT JOIN features f ON r.id = f.resource_id
  AND f.timestamp > NOW() - INTERVAL '7 days'
GROUP BY r.id
ORDER BY avg_efficiency DESC;
-- Uses index: (resource_id, timestamp)
-- Time: ~100ms for 20 resources
```

### Cleanup Old Records

```sql
DELETE FROM features
WHERE timestamp < NOW() - INTERVAL '90 days';
-- Uses index: (timestamp)
-- Time: ~200ms for 100k records
```

---

## Error Handling Architecture

```
Pipeline Execution
│
├─ Try:
│  ├─ Get metrics (catch: NoMetricsError)
│  ├─ Calculate cost (catch: CostCalculationError)
│  ├─ Store cost (catch: DatabaseError)
│  ├─ Engineer features (catch: FeatureEngineeringError)
│  ├─ Store features (catch: DatabaseError)
│  │
│  └─ Success: Add to results["processed"]
│
├─ Except SpecificError:
│  ├─ Rollback transaction
│  ├─ Add to results["errors"] list
│  ├─ Log error with context
│  └─ Continue to next resource
│
└─ Finally:
   ├─ Close database session
   └─ Return results
      - resources_processed (count)
      - costs_calculated (count)
      - features_engineered (count)
      - errors (list)
      - timestamp (UTC)
```

---

## Dependency Injection Wiring

```
FastAPI Application
│
├─ Lifespan Event (startup)
│  ├─ Initialize APScheduler
│  ├─ Add Metric Collection Job
│  └─ Add Data Pipeline Job ◄─── NEW
│
├─ Request Handler (e.g., POST /pipeline/process)
│  │
│  └─ @app.post("/pipeline/process")
│     def process_pipeline(
│        db: Session = Depends(get_database),
│        pipeline: DataPipeline = Depends(get_data_pipeline)
│     ):
│        ▲
│        └─ FastAPI Dependency Injection
│           ├─ get_database()
│           │  ├─ Create session from SessionLocal
│           │  ├─ Yield to handler
│           │  └─ Close on completion
│           │
│           └─ get_data_pipeline(db)
│              ├─ Receive injected db session
│              ├─ Create DataPipeline(db)
│              └─ Return instance
```

---

## Scaling Considerations

### Current Performance (Per Cycle)

```
Metrics: 10/sec (collection)
Pipeline: 1 cycle each 40 seconds

Processing:
├─ 5 resources
│  ├─ 1 resource: 15-20ms
│  ├─ 5 resources: 75-100ms
│  └─ Total pipeline: < 1 second
│
├─ 10 resources: ~150-200ms
├─ 20 resources: ~300-400ms
├─ 50 resources: ~750ms - 1s
└─ 100 resources: ~1.5-2s
```

### Bottlenecks & Solutions

```
❌ Bottleneck: Database Inserts
   ✅ Solution: Use bulk_create() for batch inserts
   ✅ Solution: Connection pooling (SQLAlchemy)

❌ Bottleneck: Feature Aggregation (7-day window)
   ✅ Solution: Aggregate on feature store
   ✅ Solution: Use TimescaleDB aggregations

❌ Bottleneck: Network calls to AWS
   ✅ Solution: Async boto3 calls
   ✅ Solution: Cache pricing info
   ✅ Solution: Reduce API call frequency

❌ Bottleneck: Scheduler congestion
   ✅ Solution: Increase pipeline interval
   ✅ Solution: Use async Celery tasks
   ✅ Solution: Distribute across workers
```

### Scale to 1000+ Resources

```
Recommended Changes:
1. Use Celery for distributed pipeline tasks
   └─ Pool of workers (10 workers × 100 tasks = 1000)

2. Use TimescaleDB (PostgreSQL extension)
   └─ Automatic chunking by time
   └─ Better compression
   └─ Faster aggregations

3. Implement feature caching
   └─ Cache 7-day aggregates
   └─ Invalidate on new metrics

4. Use async AWS API calls
   └─ AioBotos3 instead of boto3
   └─ Parallel metric fetching

5. Separate pipeline into stages
   └─ Collection → Storage → Processing
   └─ Each stage can scale independently
```

---

## Monitoring Dashboard Metrics

```
System Health
├─ Pipeline Execution
│  ├─ Last run timestamp
│  ├─ Resources processed count
│  ├─ Execution time (ms)
│  ├─ Error count
│  └─ Error rate (%)
│
├─ Data Quality
│  ├─ Metrics collected
│  ├─ Costs calculated
│  ├─ Features generated
│  └─ Feature completeness (%)
│
├─ Performance
│  ├─ Avg cost per resource
│  ├─ Avg features per resource
│  ├─ Database query times
│  └─ Pipeline throughput
│
└─ Resource Insights
   ├─ Most efficient resources
   ├─ Highest cost resources
   ├─ Cost trends (7-day)
   ├─ Anomalies detected
   └─ Top features affecting cost
```

---

This architecture enables:
- ✅ Automatic cost calculation
- ✅ ML-ready feature engineering
- ✅ Scalable to 100+ resources
- ✅ Fast queries for dashboards
- ✅ Extensible to more services
- ✅ Production-ready reliability
