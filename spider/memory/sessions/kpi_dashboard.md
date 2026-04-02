# KPI Dashboard Session Memory

## Current objective
Stand up and debug the Spider KPI dashboard.

## Working rules
- check source-of-truth data first
- read sidecar feedback when available
- capture validated findings only

## Facts
- 2026-04-02 — Sidecar is configured to watch the Spider workspace and can now process direct inbox requests.
- Sidecar writes latest feedback to `sidecar/outbox/latest_feedback.md` and keeps timestamped JSON replies in `sidecar/outbox/`.
- Sidecar moves handled requests into `sidecar/inbox/processed/`.

## Decisions
- 2026-04-02 — Keep Sidecar file-driven via `sidecar/inbox/` and `sidecar/outbox/` for KPI debugging support.
- 2026-04-02 — Exclude the `sidecar/` directory from file watching to avoid self-trigger loops.

## Next actions
- Use Sidecar for targeted KPI dashboard debugging requests during implementation.
- If the actual dashboard app lives outside this workspace later, update `sidecar/.env` `TARGET_REPO` accordingly.
