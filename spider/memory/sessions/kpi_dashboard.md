# KPI Dashboard Session Memory

## Current objective
Stand up and debug the Spider KPI dashboard.

## Working rules
- check source-of-truth data first
- read sidecar feedback when available
- capture validated findings only

## Facts
- 2026-04-02 — Sidecar is configured to watch the migrated KPI app at `apps/spider-kpi` and can process direct inbox requests.
- 2026-04-02 — The Spider KPI app was recovered into `apps/spider-kpi` by replaying historical OpenClaw write/edit operations from prior sessions.
- The recovered app includes a FastAPI backend, React/Vite frontend, Alembic migrations, deployment docs, and ingestion connectors for Shopify, Triple Whale, and Freshdesk.
- Backend Python modules compile, frontend installs/builds, and the recovered backend starts successfully with a local `.env` copied from `.env.example`.

## Decisions
- 2026-04-02 — Keep Sidecar file-driven via `sidecar/inbox/` and `sidecar/outbox/` for KPI debugging support.
- 2026-04-02 — Exclude the `sidecar/` directory from file watching to avoid self-trigger loops.
- 2026-04-02 — Standardize the KPI application location to `apps/spider-kpi` inside the Spider workspace.
- 2026-04-11 — Dashboard access should be owned by the KPI app itself, not by Vercel project password protection.
- 2026-04-11 — Browser access should use account-based auth with allowed-domain signup (`spidergrills.com`, `alignmachineworks.com`), while server-side admin/machine routes may continue using `APP_PASSWORD` headers.

## Open items
- Confirm whether a separate Google Ads connector existed outside the recovered transcript-backed repo.
- Tighten account auth further if needed with mailbox verification or SSO; current production signup is domain-restricted by email address but not mailbox-verified.

## Next actions
- Use Sidecar for targeted KPI dashboard debugging requests during implementation.
- Bring up the migrated KPI app with real credentials and database access.
- Verify admin sync endpoints and source health against live Spider data.
