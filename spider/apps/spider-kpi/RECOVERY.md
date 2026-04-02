# Spider KPI Recovery Notes

## Current location

This recovered KPI dashboard app now lives at:
- `/home/jpruit20/.openclaw/workspace/spider/apps/spider-kpi`

## Recovery source

This app was reconstructed by replaying historical OpenClaw session `write` and `edit` operations that originally targeted:
- `/home/jpruit20/.openclaw/workspace/spider-kpi`

The replay output is recorded in:
- `_recovery_manifest.txt`

## Recovery status

Recovered successfully:
- backend FastAPI app
- frontend React/Vite app
- ingestion connectors for Shopify, Triple Whale, Freshdesk
- migrations
- deployment docs
- admin/scheduler scaffolding

Validated locally after recovery:
- backend Python modules compile
- frontend installs and production build succeeds

## Remaining caveats

- Secrets were not migrated into this repo.
- A local `.env` still needs to be created from `.env.example`.
- Database/runtime state from the old environment was not migrated automatically.
- If Google Ads integration existed separately, it has not yet been recovered from transcript-backed source reconstruction.

## Recommended next steps

1. Create `.env` from `.env.example`
2. Run Postgres or point `DATABASE_URL` at an existing instance
3. Run Alembic migrations
4. Start backend
5. Start frontend
6. Validate source health and sync endpoints
