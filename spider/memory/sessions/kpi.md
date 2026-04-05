# Session: KPI

## Objective
- Tune and refine the Spider Grills KPI dashboard so the data is more meaningful, actionable, and decision-grade.

## Current assumptions
- The current dashboard is directionally strong but still needs tuning.
- The main optimization target is better business meaning, not more widgets.
- Sidecar review should guide progress but not override validated repo truth.

## Active files
- memory/topics/kpi_dashboard.md
- MEMORY.md
- AGENTS.md
- TOOLS.md
- apps/spider-kpi/backend/app/core/config.py
- apps/spider-kpi/backend/app/ingestion/connectors/shopify.py
- apps/spider-kpi/frontend/src/pages/SupportCX.tsx
- apps/spider-kpi/.env.example

## Blockers
- Source-of-truth and metric-trust rules may still need refinement as implementation evolves.

## Next actions
- Audit current dashboard surfaces for weak interpretability.
- Promote validated KPI rules into topic memory.
- Keep implementation-specific notes here instead of polluting durable files.
- Validate the new Shopify embedded app auth shell inside Shopify admin and confirm token exchange + Admin API probe succeed on `https://kpi.spidergrills.com`.

## Current implementation notes
- Support / CX `Response Performance` now uses `supportAgents` daily rollups for selected-range agent FRT/resolution semantics instead of inheriting created-in-range ticket filtering.
- Freshdesk agent-name enrichment is being added at ingestion/mart rebuild time so Support / CX agent tables show human-readable names instead of responder IDs.
- Replaced the separate `spider-kpi/` Vercel auth shell from manual OAuth redirects to an embedded-app pattern using App Bridge-authenticated backend requests, server-side session-token verification, and Shopify token exchange.
- Added `spider-kpi/shopify.app.toml` with embedded=true, production application URL `https://kpi.spidergrills.com`, and required KPI scopes.
- Added a minimal embedded homepage that checks session-backed backend auth, token exchange, and an Admin API read.
- Updated the KPI backend Shopify connector to stop using the app API key as an `X-Shopify-Access-Token` directly; it now supports Shopify client-credentials token exchange with 24-hour caching/refresh and API-version config.
- Fixed same-day KPI surfacing by including current-day Triple Whale data, unioning KPI daily recompute across available source dates instead of anchoring only on Shopify daily rows, and falling back intraday sessions/revenue from Triple Whale when Shopify intraday is unavailable.
- Activated Shopify client-credentials auth after `SHOPIFY_API_SECRET` was added to `apps/spider-kpi/.env`; verified live Shopify sync and backfill are now succeeding.
- Ran Shopify historical backfill successfully: 1,075 records processed across 61 business dates, extending Shopify daily coverage to 2026-02-03 through 2026-04-04.
- Fixed a null-safety bug in Shopify intraday updates (`max(None, float)` on legacy rows) discovered during the live sync run.
- Removed fabricated Shopify analytics from the active KPI truth path, added business-timezone date attribution in Shopify/Freshdesk ingestion, shifted Freshdesk daily attribution closer to created-vs-resolved-vs-backlog semantics, corrected admin/scheduler base paths, and exposed KPI provenance/fallback flags through the overview API + frontend.
- Normalized today-mode frontend KPI summary to latest intraday snapshot semantics instead of summing cumulative rows; source health labeling is now less misleading and provenance is visible in the KPI banner.
- Follow-up cleanup completed after sidecar review: `/api/kpis/daily` now returns the same enriched source-aware KPI shape as overview, range summaries preserve provenance/fallback state, and `TrendChart` now matches the props used across overview/commercial/support pages.
- Completed three more sidecar-driven truthfulness cycles:
  1. replaced full-day Shopify order fallback in intraday KPI rows with bucket-aligned cumulative Shopify order/revenue snapshots and a guaranteed current-hour snapshot row,
  2. changed Shopify daily rollups to use financially safer recognized revenue / valid-order rules and populate refunds,
  3. changed Freshdesk daily marts to rebuild from the canonical local `FreshdeskTicket` table across the affected date range instead of overwriting from only the latest API `updated_since` slice.
- Follow-up hardening after those cycles:
  - decision-engine recompute now runs only when at least one upstream source sync actually succeeds,
  - deploy/runtime files now point at the recovered FastAPI repo path instead of the obsolete pre-recovery path,
  - `scripts/refresh_all.py` now executes the current connector + compute stack directly and was validated live.
- Final sidecar assessment: the system is good enough to stop for now; main remaining caveat is that older-order Shopify refunds/cancellations/edits outside the recent `created_at` poll window are not yet folded back into `ShopifyOrderDaily` automatically via webhook-driven daily-mart updates.

## Connector plan
- Phase 1 connectors should be implemented before widening dashboard scope.
- External listening should begin with Reddit, search discovery, and owned review feeds.
- Connector health and data trust must be visible internally during rollout.

## Current next implementation order
1. finalize normalized schemas
2. wire Shopify / Triple Whale / Freshdesk / GA4
3. add connector health panel
4. stand up VOC Phase 1 ingestion
5. tune dashboard cards using validated aggregates
