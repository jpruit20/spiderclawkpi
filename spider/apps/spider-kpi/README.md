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
- `GET /api/auth/status`
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout`
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

Dashboard routes now require an authenticated browser session.
Account signup is restricted to the email domains configured in `ALLOWED_SIGNUP_DOMAINS`.
`APP_PASSWORD` is still used for admin/machine routes such as `/api/admin/*` and internal deploy validation.

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
- if the change touches `spider/apps/spider-kpi/**`, GitHub Actions runs frontend build validation and backend import validation
- if validation passes, the live root workflow `.github/workflows/claude-kpi-auto-promote.yml` merges that Claude branch directly into `master`
- the same workflow then deploys the KPI backend on the droplet and runs post-deploy sync + validation

Important repo-layout note:
- the authoritative live automation files are the repo-root workflows under `.github/workflows/`
- any duplicate copies under `spider/.github/workflows/` are non-authoritative local leftovers and should not be used as source of truth

This avoids the GitHub Actions PR-permission failure mode (`createPullRequest`) and removes the need to rely on a second downstream workflow firing after an action-authored merge.

## Notes

- The old Flask dashboard and JSON prototype files remain in-repo, but they are now legacy/prototype artifacts.
- Docker compose is present, but local Docker access may still depend on host permissions.
- The database-backed backend is the preferred path forward.
