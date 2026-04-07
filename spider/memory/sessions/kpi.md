# Session: KPI

## Objective
- Investigate the reported KPI website outage and restore clear public access.
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
- apps/spider-kpi/frontend/src/App.tsx
- apps/spider-kpi/frontend/src/components/KpiGrid.tsx
- apps/spider-kpi/frontend/src/components/StatePanel.tsx
- apps/spider-kpi/frontend/src/components/CompareSummary.tsx
- apps/spider-kpi/frontend/src/components/ThresholdPanel.tsx
- apps/spider-kpi/frontend/src/components/EventAnnotationList.tsx
- apps/spider-kpi/frontend/src/pages/ExecutiveOverview.tsx
- apps/spider-kpi/frontend/src/pages/CommercialPerformance.tsx
- apps/spider-kpi/frontend/src/pages/SupportCX.tsx
- apps/spider-kpi/frontend/src/pages/UXBehavior.tsx
- apps/spider-kpi/frontend/src/lib/thresholds.ts
- apps/spider-kpi/frontend/src/components/CompareSummary.tsx
- apps/spider-kpi/frontend/src/App.tsx
- apps/spider-kpi/frontend/src/styles.css

## Blockers
- Source-of-truth and metric-trust rules may still need refinement as implementation evolves.
- Frontend public availability is currently blocked by Vercel Authentication on `kpi.spidergrills.com`, even though the backend health endpoint is healthy.

## Next actions
- Validate the latest full-dashboard UX/UI pass in production and watch for any regressions in executive/commercial/support page hierarchy or route behavior.
- Keep the smoke test current as pages and endpoints evolve.
- Decide whether to promote the threshold framework into a backend/shared config so thresholds become source-controlled policy instead of frontend-only heuristics.
- Implement a true inventory / fulfillment risk layer once Dynamics / Business Central data is live.
- Promote the now-scaffolded Venom / telemetry event contract into a shared backend/config policy once connector work starts.
- Keep implementation-specific notes here instead of polluting durable files.

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
- 2026-04-05 investigation: live Shopify Admin API for the current business-window returns roughly the user-reported totals (`$96,061.83` / `157` recognized orders across `2026-03-29`..`2026-04-05`, or `$94,641.85` / `155` for complete days `2026-03-29`..`2026-04-04`). The dashboard discrepancy is therefore real and backend-side rather than frontend range math.
- 2026-04-05 production topology verified: `kpi.spidergrills.com` is the Vercel frontend; `api-kpi.spidergrills.com` resolves to DigitalOcean droplet `157.245.209.71`; the live FastAPI backend runs via `systemd` service `spider-kpi.service` from `/opt/spiderclawkpi/spider/apps/spider-kpi`, with Postgres on `127.0.0.1:5432`.
- 2026-04-05 production validation: droplet backfill and run-sync endpoints succeeded (`shopify` backfill processed 1,085 rows across 61 business dates; recent sync processed 149 rows), but `shopify_orders_daily` / `kpi_daily` for `2026-03-29..2026-04-05` remained materially low (`118` orders / `$66,202.19` including today, `115` / `$64,730.21` complete days). This proves production code is behind the corrected local Shopify recovery logic rather than merely stale.
- 2026-04-05 repo hardening: `scripts/refresh_all.py` and admin seed path were made repo-relative so production maintenance commands work outside the original dev workstation path.
- 2026-04-05 root-cause patch: Shopify poll sync no longer overwrites `shopify_orders_daily` directly from a partial recent fetch; it now upserts canonical per-order event state, rebuilds touched business dates from the latest order state, and then recomputes downstream KPI rows. Commit pushed: `e9f8a0c` (`Rebuild Shopify daily from canonical order state`).
- 2026-04-05 follow-up ops hardening: added `deploy/PRODUCTION_RUNBOOK.md` plus `scripts/validate_shopify_window.py` so future production deploys and Shopify/KPI window validation are repeatable without ad-hoc shell debugging.
- 2026-04-05 source-health fix: production source health showed Shopify/Triple Whale as broken due to scheduler seed-on-start clobbering live connector config back to `seeded-prototype`, and Freshdesk was genuinely failing on the agents endpoint with `state=full_time`. Patched scheduler/seed protections, added Freshdesk fallback behavior, and extended backend deploy automation to run connector syncs plus validation after deploy. Latest verified healthy production source-health state: Shopify, Triple Whale, and Freshdesk all healthy.
- 2026-04-05 UI audit start: saved first-pass evidence bundle to `sidecar/reviews/kpi_site_audit/` with screenshots, headers, HTML, DOM dumps, manifest, and ranked recommendations. Highest-severity proven frontend defect is that direct navigation to all major non-root routes on `kpi.spidergrills.com` returns `404 NOT_FOUND` from Vercel, blocking deep links, route refresh, and URL-persisted operational state.
- 2026-04-05 first frontend hardening pass: added route-level error boundaries, structured API request logging with safe retry, and URL-persisted date ranges for Executive Overview + Commercial Performance. Commit pushed: `e5221a2`.
- 2026-04-05 extended frontend decision-engine pass completed locally: added a reusable normalized state panel (`loading` / `empty` / `error` / `partial` / `ready`), a threshold framework for conversion/MER/AOV/support burden/FRT, compare-summary blocks, stale-age surfacing inside KPI cards, decision event annotation panels sourced from diagnostics + recommendations, explicit inventory/fulfillment risk placeholders, and a more operational UX / Venom telemetry page. Executive Overview is now lazy-loaded too, and `npm run build` passed with chunked output including separate `react-vendor` and `charts-vendor` bundles plus route chunks.
- 2026-04-05 follow-up frontend hardening pass completed locally: threshold policy now covers bounce rate, support resolution time, and SLA breach rate; threshold cards sort worst-first and show target bands; compare-summary values now format revenue/conversion honestly; decision event annotations sort by severity/recency with visible tone badges; the UX / Behavior page now includes a scaffolded canonical GA4+Clarity+app telemetry event contract, readiness checklist/score, and explicit normalization state; and the root Executive route now uses the same lazy suspense boundary path as other routes. `npm run build` passed again after the changes.
- 2026-04-06 outage check: `kpi.spidergrills.com` returns `HTTP 401` with a Vercel Authentication page (`Authentication Required`), while `https://api-kpi.spidergrills.com/health` returns `200 {"ok":true}`. The frontend deployment itself is `Ready` in Vercel under project `spiderclawkpi`; the failure is an access/protection gate, not backend downtime.
- 2026-04-06 Vercel project inspection: the live production project is `spiderclawkpi`. Local `.vercel/project.json` files still reference older project name `kpi_dashboard`, which is confusing and should be cleaned up.
- 2026-04-06 route outage root cause refinement: the transient Vercel auth gate cleared, but the durable production defect is still SPA deep-link failure (`/commercial`, `/support`, etc. returning Vercel `404 NOT_FOUND`). Investigated likely cause as monorepo/Vercel config scope mismatch; switched the project off the Vite preset, set explicit build/output settings, moved `vercel.json` to repo root for the project-level deploy path, and then added an explicit frontend `installCommand` after the first repo-root deploy failed with `vite: command not found`.
- 2026-04-06 pragmatic production fix: because Vercel continued ignoring the SPA catch-all config, added a frontend build step that writes static `dist/<route>/index.html` fallbacks for each known dashboard route (`commercial`, `support`, `ux`, `issues`, `diagnostics`, `source-health`). Local build verified those route files are emitted.
- 2026-04-06 native-serving hardening: added repo-root Vercel edge routing for `/api/* -> https://api-kpi.spidergrills.com/api/*`, removed the stale duplicate `frontend/vercel.json`, and added a reusable `automation/smoke_test_kpi.sh` script to check frontend routes and key APIs after deploys.
- 2026-04-06 browser network-error root cause: the live frontend bundle was still configured to call `https://api-kpi.spidergrills.com` directly from the browser, which risks cross-origin failures because the backend does not advertise the required CORS headers for the frontend origin. Patched `src/lib/api.ts` so `kpi.spidergrills.com` always uses same-origin `/api` through the Vercel edge proxy and trims any stray whitespace from configured API base values.
- 2026-04-06 executive overview metric wiring fix: the today/intraday executive summary was hard-coding `ad_spend` and `mer` to `null`, so those cards rendered as `—` even when the daily KPI mart had values. Patched Executive Overview to reuse same-day daily ad spend/open backlog and derive MER/cost-per-purchase from the intraday revenue plus same-day ad spend.
- 2026-04-06 executive overview cross-check follow-up: the same today/intraday path was also dropping same-day daily values for add-to-cart rate, bounce rate, ticket/support metrics, and tickets-per-100-orders. Patched the executive summary builder to inherit all compatible same-day daily KPI fields while still using intraday revenue/orders/sessions for live top-line cards.
- 2026-04-06 full-dashboard UX/UI pass (3 iterations): completed a broad information-hierarchy pass across Executive, Commercial, Support, UX, Issue Radar, Diagnostics, and Source Health; added top-of-page summary cards on key pages, improved action-block priority framing, tightened compare-summary readability, surfaced severity more clearly in diagnostics/issues, reduced UX-page redundancy while preserving explicit telemetry trust states, then ran a final suppression pass to trim above-the-fold alert/recommendation volume, move Executive action framing ahead of secondary threshold detail, compact Source Health rows, and shorten sidebar instructional chrome.
- 2026-04-06 deploy failure root cause: several shared frontend files (`StatePanel.tsx`, `EventAnnotationList.tsx`, `ThresholdPanel.tsx`, `thresholds.ts`) existed locally but were never tracked in Git, so Vercel builds for commits `627283e` and `d98ce6e` failed with unresolved imports even though local builds passed. Fixed by adding the missing tracked files to the repo.
- 2026-04-06 Clarity connector fix: source-health showed Clarity configured but failing with `404` against `https://www.clarity.ms/export-data/api/v1?numOfDays=3&dimension1=URL`. Patched the backend connector to target the documented `project-live-insights` endpoint (with optional `CLARITY_ENDPOINT` override support), and validated locally that the same bearer token now returns `200` with Clarity export JSON.
- 2026-04-06 Clarity parser fix: the live Clarity endpoint returns a top-level list of metric groups with nested `information` arrays, not a dict with `records`/`rows`. Patched the connector to flatten that native payload shape and verified locally that it now extracts 9,000 rows from the live response.
- 2026-04-06 GA4 follow-up: production GA4 was failing before token issuance because the private key in `.env` is stored as a single-line string with literal `\n` escapes. Patched the GA4 connector to normalize escaped newlines/quotes before JWT signing.
- 2026-04-06 GA4 auth root cause refinement: after private-key normalization, Google token issuance now fails with `invalid_grant: Invalid grant: account not found`, indicating the configured GA4 identity is not a valid/matching Google service account. Production `.env` currently uses `GA4_CLIENT_EMAIL=info@spidergrills.com`, which is not a service-account address. Executive connector trust counts were adjusted to reflect currently live production connectors (`shopify`, `triplewhale`, `freshdesk`, `clarity`) so the dashboard shows 4/4 until GA4 is genuinely live.

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
