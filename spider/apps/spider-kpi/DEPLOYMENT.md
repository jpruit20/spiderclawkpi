# Spider KPI Deployment

## Recommended deploy path

Use the **database-backed FastAPI backend + Vite frontend** as the primary deploy path.

Do not treat the old Flask app as the long-term production path anymore.
It can stay around as legacy/prototype code, but the locked deploy path is now:

1. PostgreSQL
2. FastAPI backend
3. React/Vite frontend
4. Nginx reverse proxy
5. systemd services for backend process and scheduled syncs

## Why this path

This path gives you:
- real persisted source sync history
- source-health visibility
- obvious failure surfacing
- API-backed dashboards instead of JSON-only prototypes
- cleaner long-term extension for support/CX and diagnostics

## Runtime shape

### Backend
- Runs FastAPI via uvicorn
- Reads credentials from `.env`
- Connects to PostgreSQL
- Serves KPI, diagnostics, alerts, recommendations, support, and source-health APIs

### Frontend
- Runs Vite build output behind Nginx
- Talks to backend over `/api`
- Uses `X-App-Password` when app auth is enabled

### Sources now integrated
- Shopify
- Triple Whale
- Freshdesk

## Environment

Expected env vars in `.env`:
- `DATABASE_URL`
- `CORS_ORIGINS`
- `AUTH_DISABLED`
- `APP_PASSWORD`
- `JWT_SECRET`
- `SHOPIFY_STORE_URL`
- `SHOPIFY_API_KEY`
- `SHOPIFY_WEBHOOK_SECRET`
- `TRIPLEWHALE_API_KEY`
- `FRESHDESK_DOMAIN`
- `FRESHDESK_API_KEY`
- `FRESHDESK_API_USER`
- `SYNC_INTERVAL_MINUTES`
- `BACKFILL_DAYS`

## Local bring-up

### 1. Python env

```bash
cd /home/jpruit20/.openclaw/workspace/spider-kpi
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. PostgreSQL

Run Postgres however you prefer, but ensure `DATABASE_URL` points to a reachable host.

### 3. Migrations

```bash
cd /home/jpruit20/.openclaw/workspace/spider-kpi/backend
PYTHONPATH=../backend alembic -c alembic.ini upgrade head
```

### 4. Start backend

```bash
cd /home/jpruit20/.openclaw/workspace/spider-kpi/backend
source ../.venv/bin/activate
PYTHONPATH=../backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. Run syncs

You can use the API admin endpoints or import connector jobs directly.

Examples:
- `POST /api/admin/run-sync/shopify`
- `POST /api/admin/run-sync/triplewhale`
- `POST /api/admin/run-sync/freshdesk`
- `POST /api/admin/backfill/{source}`

## Failure visibility

Failure modes are surfaced in three places:

1. `source_configs` / `source_sync_runs` in Postgres
2. `/api/source-health`
3. generated source-health alerts in `/api/alerts`

### Source health states
- `healthy`
- `failed`
- `stale`
- `not_configured`
- `never_run`
- `running`
- `disabled`

## Production recommendation

### Backend service
Run uvicorn as a systemd service.

Suggested command:

```bash
/home/jpruit20/.openclaw/workspace/spider-kpi/.venv/bin/python -m uvicorn app.main:app --app-dir /home/jpruit20/.openclaw/workspace/spider-kpi/backend --host 127.0.0.1 --port 8000
```

### Scheduler
You have two acceptable options:
- keep APScheduler inside the backend process
- or use a separate systemd timer hitting admin sync endpoints / runner scripts

For this repo, the simplest locked path is:
- backend process stays always-on
- APScheduler performs recurring syncs
- systemd just keeps the backend alive

## Nginx

Recommended topology:
- `server_name kpi.spidergrills.com`
- `/` -> built frontend
- `/api/` -> proxy to `127.0.0.1:8000`
- `/docs` optional internal-only access

## Current reality check

As of this build-out:
- Shopify sync is working
- Triple Whale sync is working
- Freshdesk sync is working
- KPI rows are materializing in Postgres
- source health is being computed from real sync runs

## Repo hygiene

The repo should ignore:
- `.env`
- virtualenvs
- `__pycache__`
- local logs
- `.openclaw/`

## Legacy notes

The old Flask app and JSON dashboard are still in the repo for reference/prototype continuity, but they are no longer the preferred production path.
