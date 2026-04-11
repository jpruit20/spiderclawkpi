# Spider KPI Decision Engine

Production-oriented KPI and decision engine for Spider Grills.

## Current status

The backend-backed KPI stack is now the primary path.
It ingests Shopify, Triple Whale, and Freshdesk into PostgreSQL, computes KPI rows, and exposes source-health / alert visibility through the API.

## What this system does

This stack is designed to ingest, store, compute, and serve company-wide operating intelligence for:
- ecommerce performance
- marketing efficiency
- support / CX health
- issue detection
- recommendation generation
- source health visibility

## Architecture

### Backend
- FastAPI
- SQLAlchemy
- Alembic
- APScheduler
- PostgreSQL

### Frontend
- React + Vite

### Sources
Integrated:
- Shopify polling
- Shopify webhook scaffold
- Triple Whale polling
- Freshdesk polling

Scaffolded for future:
- Reddit
- Discord
- reviews
- generic public web mentions

## Directory structure

- `backend/` FastAPI app, models, migrations, ingestion, compute layer
- `frontend/` React dashboard
- `data/` prototype data and bootstrap artifacts
- `deploy/` deployment notes and service artifacts
- `docker-compose.yml` local orchestration attempt

## Main API surface

- `GET /health`
- `GET /api/overview`
- `GET /api/kpis/daily`
- `GET /api/kpis/intraday`
- `GET /api/diagnostics`
- `GET /api/alerts`
- `GET /api/recommendations`
- `GET /api/issues`
- `GET /api/support/overview`
- `GET /api/support/tickets`
- `GET /api/source-health`
- `POST /api/admin/run-sync/{source}`
- `POST /api/admin/backfill/{source}`
- `POST /api/admin/seed`

## Source-health behavior

Every source now tracks:
- configured vs not configured
- latest run status
- latest success/failure time
- records processed
- derived health state
- stale sync detection
- surfaced failure summaries

This is intended to push broken connectors to the top instead of hiding them.

## Local development

### 1. Create env and venv

```bash
cd /home/jpruit20/.openclaw/workspace/spider-kpi
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. Ensure PostgreSQL is reachable

Set `DATABASE_URL` in `.env`.

### 3. Run migrations

```bash
cd backend
PYTHONPATH=../backend alembic -c alembic.ini upgrade head
```

### 4. Start backend

```bash
cd backend
source ../.venv/bin/activate
PYTHONPATH=../backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. Start frontend

```bash
cd frontend
npm install
npm run dev
```

## Current deployment recommendation

Use:
- PostgreSQL
- FastAPI backend via uvicorn/systemd
- Vite frontend behind nginx
- `.env` for credentials
- API-backed source health as the operational truth

See `DEPLOYMENT.md` for the locked deploy path.
See `deploy/PRODUCTION_RUNBOOK.md` for the current Vercel + DigitalOcean production deploy and validation workflow.

## Git / deployment flow

Production deploys from `master`.

For Claude-authored KPI updates, the repo now supports an auto-promotion path:
- push the KPI change to a branch matching `claude/**`
- if the change touches `apps/spider-kpi/**`, GitHub Actions runs frontend build validation and backend import validation
- the workflow auto-creates or reuses a PR from that Claude branch into `master`
- if validation passes, the workflow auto-merges into `master`
- deploy then runs from either:
  - a normal `push` to `master`, or
  - a successful completion of `Auto-promote Claude KPI branches`

This closes the GitHub Actions token handoff gap where an action-driven merge to `master` may not reliably trigger a second workflow via the usual `push` event alone.

## Notes

- The old Flask dashboard and JSON prototype files remain in-repo, but they are now legacy/prototype artifacts.
- Docker compose is present, but local Docker access may still depend on host permissions.
- The database-backed backend is the preferred path forward.

## Deployment test log

- 2026-04-11: Deployment flow test from `claude/slack-session-M2Y3u`

- 2026-04-11 smoke test: fresh Claude branches from current master should validate, merge, and deploy without PR creation.
