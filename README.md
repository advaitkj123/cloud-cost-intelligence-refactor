# Cloud Cost Intelligence Platform

A production-style SaaS application for simulated cloud cost observability, anomaly detection, optimization recommendations, and savings tracking.

## Architecture Overview

The system is organized into clean layers:

- **API Layer**: FastAPI endpoints for metrics, costs, anomalies, actions, and resources
- **Service Layer**: orchestration for ingestion, pricing, ML evaluation, and optimization decisions
- **Repository Layer**: SQLAlchemy-backed persistence with PostgreSQL/TimescaleDB-ready timestamped tables
- **ML Layer**: Isolation Forest anomaly detection using metrics plus cost signals
- **Cost Engine**: configurable pricing logic for EC2, Lambda, and S3
- **Optimization Layer**: dry-run or executable mock cloud actions with savings logging
- **Frontend**: React + TypeScript + Tailwind SaaS dashboard with charts and polling-based live updates

Pipeline:

`Ingestion -> Cost Estimation -> Anomaly Detection -> Decision Engine -> Optimization -> Logging -> API -> Frontend`

## Backend stack

- FastAPI
- PostgreSQL
- SQLAlchemy ORM
- Pydantic
- APScheduler
- scikit-learn (Isolation Forest)

## Frontend stack

- React + Vite
- TypeScript
- TailwindCSS
- Recharts

## Project Structure

```text
cost-intelligence/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── metrics.py
│   │   ├── anomalies.py
│   │   ├── actions.py
│   │   ├── cost.py
│   │   └── resources.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── logger.py
│   │   └── dependencies.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── session.py
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── action_repository.py
│   │       ├── anomaly_repository.py
│   │       ├── cost_repository.py
│   │       ├── metric_repository.py
│   │       └── resource_repository.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── resource.py
│   │   ├── metrics.py
│   │   ├── cost.py
│   │   ├── anomalies.py
│   │   └── actions.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── resource.py
│   │   ├── metrics.py
│   │   ├── cost.py
│   │   ├── anomalies.py
│   │   └── actions.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── collector.py
│   │   ├── cost_engine.py
│   │   ├── anomaly_detector.py
│   │   ├── decision_engine.py
│   │   ├── optimizer.py
│   │   └── orchestrator.py
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── postcss.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── tsconfig.app.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── index.css
│       ├── main.tsx
│       ├── types.ts
│       ├── lib/api.ts
│       ├── components/
│       │   ├── CostTrendChart.tsx
│       │   ├── ErrorState.tsx
│       │   ├── Layout.tsx
│       │   ├── LoadingState.tsx
│       │   ├── Panel.tsx
│       │   ├── ResourceCostBarChart.tsx
│       │   ├── StatCard.tsx
│       │   └── StatusBadge.tsx
│       └── pages/
│           ├── ActionsPage.tsx
│           ├── AnomaliesPage.tsx
│           ├── DashboardPage.tsx
│           └── ResourcesPage.tsx
├── scripts/
│   ├── seed_data.py
│   └── simulate_metrics.py
├── .env.example
├── package.json
├── requirements.txt
└── README.md
```

## API Endpoints

- `GET /` health
- `POST /metrics` ingest metrics and run the full pipeline
- `GET /metrics` fetch metrics
- `GET /cost` cost summary, trend, savings, and per-resource totals
- `GET /anomalies` anomaly feed
- `GET /actions` action log
- `POST /actions` manually trigger optimization
- `GET /resources` resource inventory with latest telemetry

## Local Setup

### 1) Start PostgreSQL

If you have Docker available:

```bash
docker run --name cost-intelligence-postgres \
  -e POSTGRES_DB=cost_intelligence \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -d postgres:16
```

TimescaleDB is compatible as a drop-in replacement for this schema.

### 2) Configure environment

```bash
cp .env.example .env
```

### 3) Start backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/seed_data.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4) Start frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:5173` and proxies API traffic to `http://localhost:8000`.

## Simulation

You can simulate metrics in two ways:

1. **Automatic background job**: enabled by default and runs every 20 seconds
2. **Manual simulation script**:

```bash
python scripts/simulate_metrics.py
```

## Optimization Behavior

- EC2 instances with low CPU and sustained cost can be recommended for stop
- Lambda spikes can be throttled
- S3 growth can trigger cleanup recommendations
- All actions are logged
- Dry-run mode is enabled by default for safe executive demos

## Notes for Production Hardening

- Add Alembic migrations
- Add authn/authz and tenant isolation
- Add Redis/Celery for distributed jobs
- Expose webhooks and cloud adapters for AWS/GCP/Azure execution
- Add TimescaleDB hypertables and retention policies for large-scale telemetry
