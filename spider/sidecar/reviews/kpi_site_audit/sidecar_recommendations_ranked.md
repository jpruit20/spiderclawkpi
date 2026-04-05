# KPI Site Audit — Ranked Recommendations

## 1. Fix live SPA deep-link routing on Vercel
- **Impact:** Very high
- **Effort:** Low to medium
- **Confidence:** High
- **Why:** Direct-route 404s break operational bookmarking, shared investigations, route-refresh resilience, and URL-persisted filter strategy.
- **Primary KPI effect:** trust, decision latency, engineering reliability

## 2. Add metric provenance panels to executive and commercial KPI surfaces
- **Impact:** High
- **Effort:** Medium
- **Confidence:** High
- **Why:** Executives need explicit source, refresh cadence, time window, and caveats before acting on a metric.
- **Primary KPI effect:** trust, decision quality

## 3. Re-structure the top layer into fewer executive decision cards with explicit next actions
- **Impact:** High
- **Effort:** Medium
- **Confidence:** Medium-high
- **Why:** Current surfaces still skew toward reporting rather than what changed / why / what to do next.
- **Primary KPI effect:** decision latency, conversion of data into action

## 4. Add stale-data banners and source-age framing to every major section
- **Impact:** High
- **Effort:** Medium
- **Confidence:** High
- **Why:** Silent freshness drift can create false certainty.
- **Primary KPI effect:** trust, engineering reliability

## 5. Add safe response-schema validation and controlled empty/error states everywhere
- **Impact:** High
- **Effort:** Medium
- **Confidence:** High
- **Why:** Prevents misleading zeros, blank charts, and fragile assumptions when backend payloads drift.
- **Primary KPI effect:** trust, engineering reliability

## 6. Add compare modes (prior period / target / same day last week)
- **Impact:** Medium-high
- **Effort:** Medium
- **Confidence:** Medium
- **Why:** Decision quality improves when deltas are contextualized, not just displayed as point values.
- **Primary KPI effect:** decision quality, decision latency

## 7. Add annotation markers for stockouts, campaign launches, pricing changes, site changes, inventory receipts
- **Impact:** Medium-high
- **Effort:** Medium-high
- **Confidence:** Medium
- **Why:** Without annotations, the dashboard explains too little about why movement occurred.
- **Primary KPI effect:** decision quality, trust

## 8. Reduce visual clutter and defer lower-information cards beneath the first decision layer
- **Impact:** Medium
- **Effort:** Medium
- **Confidence:** High
- **Why:** Executive attention should be spent on the few signals that change decisions, not broad metric sprawl.
- **Primary KPI effect:** decision latency
