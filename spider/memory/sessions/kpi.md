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
- apps/spider-kpi/.env.example

## Blockers
- Source-of-truth and metric-trust rules may still need refinement as implementation evolves.

## Next actions
- Audit current dashboard surfaces for weak interpretability.
- Promote validated KPI rules into topic memory.
- Keep implementation-specific notes here instead of polluting durable files.
- Validate the new Shopify embedded app auth shell inside Shopify admin and confirm token exchange + Admin API probe succeed on `https://kpi.spidergrills.com`.

## Current implementation notes
- Replaced the separate `spider-kpi/` Vercel auth shell from manual OAuth redirects to an embedded-app pattern using App Bridge-authenticated backend requests, server-side session-token verification, and Shopify token exchange.
- Added `spider-kpi/shopify.app.toml` with embedded=true, production application URL `https://kpi.spidergrills.com`, and required KPI scopes.
- Added a minimal embedded homepage that checks session-backed backend auth, token exchange, and an Admin API read.
- Updated the KPI backend Shopify connector to stop using the app API key as an `X-Shopify-Access-Token` directly; it now supports Shopify client-credentials token exchange with 24-hour caching/refresh and API-version config.

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
