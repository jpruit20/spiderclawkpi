# KPI Site Audit — Sidecar Summary

## Major defects
- Direct navigation to all major non-root routes on `kpi.spidergrills.com` returns `404 NOT_FOUND` from Vercel (`/commercial`, `/support`, `/issues`, `/diagnostics`, `/source-health`). This breaks deep linking, route refresh, operational bookmarks, and URL-persisted filters.
- The root route loads, but route-level availability is deployment-config inconsistent with the SPA router.
- Source-health correctness recently depended on backend fixes; without those, UI trust would have remained materially broken.
- The executive overview and commercial pages lacked URL-persisted date range state, which increases decision latency and makes shared investigations non-reproducible.
- The frontend lacked route-level error boundaries, so chart/render failures could collapse whole sections without a controlled state.
- The frontend API layer had timeout handling but no structured telemetry and no retry path for safe transient failures.

## Probable root causes
- Vercel SPA rewrite configuration is not being honored for live non-root routes, despite `frontend/vercel.json` existing in-repo.
- Frontend state management is still report/dashboard shaped rather than decision-operation shaped: filters are local state, provenance is mostly implicit, and actionable next-step framing is incomplete.
- Observability is thin at the UI layer; route load, request timing, and render failures were not being logged in a structured way.

## Business impact
- Broken direct routes materially reduce trust and increase decision latency because operators cannot reliably bookmark/share the exact investigative view they are using.
- Missing URL-persisted state makes collaborative debugging and executive review slower and less reproducible.
- Lack of controlled error boundaries and request telemetry makes silent degradation more likely under partial API or render failures.

## Fixes applied
- Added route-level React error boundaries.
- Added structured frontend API request logging (`start` / `success` / `fail`) and one safe retry path.
- Added URL-persisted date range state on the main Executive Overview and Commercial Performance pages.
- Saved first-pass audit artifacts under `sidecar/reviews/kpi_site_audit/`.
- Generated `audit_manifest.json` with route-level render status and evidence paths.

## Fixes deferred
- Live Vercel route rewrite/deep-link production fix still needs to be validated on the frontend deployment path.
- Full metric provenance panels are not yet implemented.
- Stale-data banner, schema validation of API payloads, and compare modes still need explicit implementation.
- Inventory / fulfillment risk and Venom/product telemetry layers still need product/data design work before UI promotion.
