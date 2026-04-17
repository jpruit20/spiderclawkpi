# Spider Grills Venom Telemetry — The First 28 Months

*Generated 2026-04-17 by Claude Opus 4.7. Window: 2024-01-01 → 2026-04-17.*

## Executive summary

The Venom fleet roughly tripled in reporting activity over 28 months — avg daily active devices went from 75 in Jan 2024 to 224 in April 2026, with clean summer peaks (246 in Jun 2025) and winter troughs (117 in Jan 2025). Steady-state benchmarks are tight: cook success sits at 68-70% and error rate at 0.9-1.3%, with the July 2024 outlier (57M events, 5.2% err) confidently written off as a shadow-retention instrumentation artifact rather than real customer activity. Three things demand attention ahead of other detail: (1) firmware 01.01.94 was deployed at scale in Jan 2026 (2.4M events) then rolled back to 3,312 events by Feb — we need a post-mortem and we don't yet have the cook-success data to judge the call; (2) the Huntsman product line ramped 70x between Dec 2025 and Jan 2026 and is invisible on the current dashboard because active-device counts aren't model-segmented; (3) session derivation has only completed for 4 months out of 28, which is the single biggest reason this report hits walls whenever it tries to do cohort analysis. Everything below is detail supporting those three points, plus 13 benchmarks you can treat as baseline for future monthly reports.

## Fleet growth — three acts in 28 months

Avg daily `active_devices` (devices reporting shadow state within the day) traces a clean three-act structure:

- **Act 1 — organic ramp (Jan–Jun 2024):** 75 → 150. Feb 2024 was the first time the fleet broke a 300-device peak (318). June 2024 cleared 150 avg for the first time.
- **Act 2 — plateau with seasonal dip (Jul 2024 – Mar 2025):** 117–167 avg active. Jan 2025 at 117 is the fleet low for this window. Event volume stayed in the 5-10M/month band once the July 2024 anomaly passed.
- **Act 3 — step up (Apr 2025 – present):** Apr 2025 jumped to 186.5 avg, May 2025 to 245.8. Summer 2025 ran 233-246. Winter 2025/26 settled at 167-189 and the fleet is climbing back to 224 in April 2026.

Peak active tells a related but distinct story. Nov 2024 hit 663. Nov 2025 hit **899** — the all-time high. Peak grew ~4.1x over the period while avg grew ~3.0x. That widening peak-to-avg ratio means weekend-and-holiday spikes are outpacing everyday baseline — a signature of more casual or occasional users joining the base rather than uniform intensification.

**Caveat on what `active_devices` actually measures.** It counts devices that reported shadow state that day. App MAU is ~1,800, and daily active peaks around 600-900 on special days. So somewhere between 6-15% of the MAU base reports any given day. That range could hide fleet attrition — a device that silently stops reporting is indistinguishable from one whose owner didn't cook that week. We don't have instrumentation to separate 'churned' from 'quiet'; see recommendations.

## Seasonal and weekly rhythm

**Seasonal.** Summer peak, winter trough, and the gap is shrinking as the fleet grows:

| window | summer avg | winter avg | ratio |
|--------|-----------:|-----------:|------:|
| 2024 summer vs 2024/25 winter (Jun-Aug / Dec-Feb) | 151 | 130 | 1.2x |
| 2025 summer vs 2025/26 winter | 240 | 179 | 1.3x |
| peak-to-trough annual swing 2024 | 162 (Jul) / 75 (Jan) | — | 2.2x |
| peak-to-trough annual swing 2025 | 246 (Jun) / 117 (Jan) | — | 2.1x |

Annual swing is stable, but year-over-year the relative dip is softening. More year-round use = a sign of fleet maturity (newer customers include non-summer-only cooks).

**Weekly.** From the last 89 days of daily data:

- Sundays: avg ~380 active. Max 624 (Feb 8, 2026 — Super Bowl LX) and 623 (Apr 5, 2026 — Easter).
- Saturdays: avg ~276 active.
- Weekdays (Mon-Fri): avg ~120-160 active.

Sunday runs ~3x typical weekday. Holiday Sundays push the ratio to ~5x. Feb 8, 2026 (Super Bowl) logged 1,205,595 events — the single biggest telemetry day in the 89-day window. Apr 5, 2026 (Easter) logged 1,245,372 events — biggest day of 2026 YTD. These are real and worth annotating on the dashboard.

**Hour-of-day.** Monotonous across 28 months: every month peaks at 21:00 or 22:00 local, with the 18:00-23:00 block carrying most activity. '0:00' showing up in top-6 in some months is a UTC-vs-local artifact from late-night East Coast cooks. Localization would resolve it. Spring and early-fall months show a tighter 18-22 window; peak summer stretches the envelope to 17-23.

## Reliability — what 'good' looks like

**Error rate.** Excluding the July-Aug 2024 anomaly (see Section 7), monthly error rate is remarkably tight:

- Min: **0.7%** (Jun, Oct 2024; Sep, Oct 2025)
- Median: **1.05%**
- 75th percentile: **1.2%**
- Max (normal ops): **1.9%** (Dec 2025)

22 of the 26 non-anomalous months fall inside 0.7-1.4%. Useful thresholds:

| band | label | action |
|------|-------|--------|
| ≤1.3% | healthy | none |
| 1.4-1.7% | investigate | check fw cohort, connectivity |
| ≥1.8% | incident | root cause required |

Dec 2025 at 1.9% is our highest normal-ops month, and it coincides with firmware 01.01.93 first appearing at non-trivial volume (398,290 events). Not a smoking gun, but a reason to add a firmware-segmented err-rate panel to the dashboard (see recommendations).

**Cook success.** Only computable for the 4 months where session derivation is complete:

| month | cook_success | sessions |
|-------|-------------:|---------:|
| 2024-01 | 68.1% | 2,461 |
| 2024-02 | 69.8% | 2,834 |
| 2024-03 | 70.2% | 3,459 |
| 2026-04 (partial) | 68.8% | 1,593 |

A 2.1-point band across 26 months is a meaningful finding by itself — cook success is a stable fleet characteristic, not a volatile one. Treat monthly rollups below 65% as unusual and above 73% as unusually good.

Daily cook success in Apr 2026 ranged from 43.6% (4/8, n=39, a pipeline boundary day) to 73.5% (4/12, n=483). The four high-volume days (n≥160) all landed 65-73%, consistent with the monthly figure. Low-n days are not signal. For the dashboard, suppress cook_success daily when sessions < ~50.

## Firmware cohorts and the 01.01.94 rollback

**High-level timeline** from firmware event shares:

- **Early 2024 (Jan-Jun):** fragmented. 01.01.23 (30-40%), 01.01.25 (25-35%), 01.01.10 (5-8%), 01.01.27 rising from 0 to 48% of events by Jun 2024.
- **Late 2024 (Aug-Nov):** 01.01.27 dominant (45-65%), 01.01.33 ramping (6% → 20%). 01.01.34 launches in Nov 2024 and immediately carries 29% of events that month — a fast, broad OTA.
- **2025 (steady):** Three-way split — 01.01.34 (~50-58%), 01.01.33 (~30-35%), 01.01.27 (~10-17%). This is the most stable fw distribution in the whole history.
- **Oct 2025:** A new family appears — 01.01.75, 01.01.76, 01.01.83 — all small volumes.
- **Dec 2025 – Apr 2026 (rapid release cadence):** 01.01.93 (Dec), 01.01.94 (Jan), 01.01.97 (Feb), 01.01.98 (Mar).

**The 01.01.94 story** is the cleanest rollback signature in the entire dataset:

| month | 01.01.94 events | 01.01.97 events |
|-------|----------------:|----------------:|
| 2026-01 | 2,421,085 | 54,590 |
| 2026-02 | 3,312 | 610,631 |
| 2026-03 | — | 16,887 |

A 731x collapse in .94 while .97 simultaneously jumped ~11x. Classic 'ship X, pull X, ship Y' pattern. We don't have fw-cohort cook_success or err-rate to judge whether .94 was buggy or simply superseded, but given Dec 2025's elevated err rate (1.9%) and the speed of the replacement, the working hypothesis is 'some regression in .93/.94 addressed by .97'. The Feb 2026 fleet-wide err rate did drop to 0.9% (from 1.3% in Jan), consistent with .97 being healthier.

Four releases in four months (.93/.94/.97/.98) is fast. A plaintext firmware release log paired with telemetry would make this kind of analysis 10x cheaper — see recommendations.

## Hardware — the Huntsman ramp is the 2026 story

Pre-September 2025, model mix was 100% `W:K:22:1:V` (Weber Kettle 22-inch clip-on). Then:

| month | Huntsman | Kettle22 | W:K:22:1:V |
|-------|---------:|---------:|-----------:|
| 2025-09 | 2,546 | — | 8,822,748 |
| 2025-10 | 51,350 | 40,021 | 7,391,768 |
| 2025-11 | 44,180 | 34,437 | 10,131,042 |
| 2025-12 | 34,562 | 374,558 | 8,557,024 |
| **2026-01** | **2,411,560** | 214,733 | 7,129,461 |
| 2026-02 | 339,896 | 286,878 | 6,687,127 |
| 2026-03 | 549,791 | 59,637 | 8,716,783 |

Two stories:

1. **Kettle22** appears in Oct 2025 as a distinct model ID from `W:K:22:1:V`. Likely a SKU rename or a new variant. Dec 2025 spiked to 374K events, then settled at 200-300K/month.
2. **Huntsman** is the bigger story. Small footprint through fall 2025 (2K to 51K events), then a **70x jump** in Jan 2026 (2,411,560 events, 24% of that month's telemetry). Feb 2026 settled into a steady state of ~340K events/month, Mar at ~550K. That's a real product launch signature — not noise.

The current dashboard doesn't chart model mix. That means the single biggest product story of 2026 is invisible to anyone reading the fleet page. Adding a stacked-area by model to the main chart is a small engineering lift with outsized explanatory value — it will also let you segment avg_cook_temp, err rate, and cook success by model once session derivation catches up.

## How people actually cook — and how that's changing

Four months of session derivation give us a 2-year-apart comparison. The deltas are substantial.

**Cook style:**

| | Q1 2024 avg | 2026-04 | Δ |
|-|------------:|--------:|--:|
| low_and_slow | 44% | 39% | -5pp |
| medium_heat | 27% | 26% | -1pp |
| hot_and_fast | 17% | **29%** | **+12pp** |
| startup_only | 11% | **5%** | **-6pp** |

Hot-and-fast nearly doubled. Startup-only (cooks that never got past setup) halved. Fleet is using the device more deliberately.

**Temperature range:**

| | Q1 2024 avg | 2026-04 | Δ |
|-|------------:|--------:|--:|
| under_250 | 25% | 22% | -3pp |
| 250-300 | 34% | 27% | -7pp |
| 300-400 | 27% | 31% | +4pp |
| over_400 | 14% | **21%** | **+7pp** |

Over-400°F cooks rose 50% as a share. Consistent with hot-and-fast rising.

**Duration range:**

| | Q1 2024 avg | 2026-04 | Δ |
|-|------------:|--------:|--:|
| under_30m | 19% | **12%** | **-7pp** |
| 30m-2h | 42% | 46% | +4pp |
| 2h-4h | 17% | 20% | +3pp |
| over_4h | 22% | 23% | +1pp |

Short abandons dropped. Medium-length cooks absorbed the difference. Long cooks stable.

**Avg cook temp** (monthly rollup):

- 2024 median: 285°F
- 2025 median: 288°F
- 2026 YTD: **303°F**

A +15-18°F shift year-over-year, and it happened right when Huntsman volume ramped. Two candidate explanations: (a) Huntsman users cook hotter than Weber clip-on users, or (b) firmware 01.01.93+ changed how 'cook' gets detected or what temp readings get averaged. We can't separate these without model-segmented or fw-segmented cook data. Split the chart by model + firmware once the dashboard supports it (both small engineering efforts).

## The July 2024 anomaly and other data quality issues

**July 2024 doesn't fit anything.** Side by side with June and August:

| metric | Jun 2024 | **Jul 2024** | Aug 2024 |
|--------|---------:|-------------:|---------:|
| events | 10,748,428 | **57,174,955** | 8,585,767 |
| errors | 74,970 | **2,979,626** | 573,570 |
| err rate | 0.7% | **5.2%** | 6.7% |
| avg cook temp | 288.9°F | **374.7°F** | 286.4°F |
| avg RSSI | -66.9 | **-72.0** | -60.5 |
| fw 01.01.23 events | 4,890,376 | **47,797,967** | 2,016,656 |

Firmware 01.01.23 alone accounts for 83% of July 2024 events. The shape — concentrated in a single firmware version, with extreme event volume plus broken-looking avg temp and RSSI — is consistent with a shadow-retention policy change (either at the firmware or backend layer) that caused devices on 01.01.23 to retain far more samples per unit time. August's elevated err rate is the tail of the same effect as that cohort's event volume deflates from 48M to 2M.

This is not real customer activity. **Dashboard rolling averages are currently polluted by including this month** (averaging err rate over 2024 gives 1.8% vs. a corrected 1.0%). Banner it, exclude from baselines, and add a release/incident annotation layer so future anomalies are captioned rather than mis-read.

**Other data quality notes:**

- **Session counts = 0 for 24 of 28 months** — backfill incomplete. Biggest single analytical gap.
- **Only 7 individual `cook_session` records persisted**, all archetype `?`. Either the classifier isn't running, its output isn't being persisted, or the persistence layer is dropping the field. The archetype panel on the dashboard is currently unusable.
- **Shopify revenue** has $177,854 / $162,428 / $171,138 for Nov/Dec 2025 / Jan 2026 but 0 orders — a data-source gap, not a business event.
- **Apr 8 and Apr 15, 2026** daily rows (39 and 11 active) are pipeline boundary days, not real low days.
- **avg_cook_temp** as a single fleet-level line is now telling two stories simultaneously (model mix + firmware). Needs to be split.

## What the dashboard currently gets wrong

Specific mis-framings the data makes obvious:

1. **The active-device chart lacks seasonal context.** '190 active today' means very different things in January vs June. Overlay seasonal bands (winter ≈180, summer ≈240) and annotate known spikes (Super Bowl, Easter, firmware rollouts).

2. **`events_per_day` is not cook volume.** It's DynamoDB shadow-sample count. The July 2024 anomaly proves the correlation to real usage breaks whenever sampling or retention changes. Rename to 'device telemetry volume' and add an `events_per_active_device_per_day` panel (steady-state runs ~40-50K). Sampling-policy changes then become visible instead of invisible.

3. **Error rate isn't normalized by firmware.** A fleet running mostly .27 vs. a fleet running mostly .94 will have different baseline error rates. Dashboard should allow fw-segmented err rate.

4. **Cook success shows as empty/zero for 24 of 28 months.** Label these 'pending derivation' to distinguish from 'real zero' — otherwise it reads as a catastrophic drop.

5. **Model mix is absent.** The Huntsman ramp (Section 5) is currently invisible. Add a stacked-area by model to the main fleet page.

6. **Peak-hour table is UTC-indexed.** '0:00' appearing as a top-6 hour is East Coast 9pm-midnight cooks showing up after UTC rollover. Localize.

7. **Session archetype panel shows noise.** 7 sessions all `?` is not a chart. Suppress the panel or fix the classifier — both are small lifts.

8. **Orders missing from Shopify rollup Nov 2025 - Jan 2026.** Fill or mark as 'unavailable'.

9. **avg_cook_temp is a single line.** It's now blending model mix and firmware effects. Split by model (small) and eventually by firmware (medium).

10. **July-Aug 2024 is included in rolling averages.** Banner and exclude.

None of these are architectural changes. Most are one-evening engineering tasks. The cumulative effect is a dashboard that answers questions instead of raising them.

## Gaps worth closing

**Session derivation backfill is the single biggest unlock.** With only 4 of 28 months computed, we cannot:

- Compute fw-cohort cook success (which would resolve the 01.01.94 question)
- Track sessions-per-active-device over time
- Segment cook behavior by model (Huntsman vs Weber clip-on)
- Build retention curves or cohort time-to-value

A back-of-envelope finding that this gap nearly hides: in Jan-Mar 2024, sessions per active device per day hovered at **1.06**. In Apr 2026 (partial), it's **0.47** — less than half. Three possible explanations:

- (a) Real usage decline per device as the fleet dilutes with casual users
- (b) Session derivation logic changed between 2024 and 2026 (likely, given the 28-month coverage gap)
- (c) One month of 2026 data isn't representative

We can't pick without backfill. If (a), it's a product signal. If (b), it's a methodology note. Either way, we need to know.

**Other gaps:**

- **RSSI distribution.** We have avg (hovering at -60 dBm, classified 'fair'), but no percentiles. If 25% of the fleet is at -70 dBm or worse, that plausibly accounts for meaningful cook abandonment and some share of the err rate. Instrument P10/P50/P90 monthly.
- **Session termination reason.** 'Abandoned' vs 'connection lost' vs 'user canceled' vs 'completed' is not currently distinguished. Without it, cook_success misses can't be attributed to root cause — and we can't tell whether weak WiFi is causing what looks like user abandonment.
- **Device onboarding timestamp and first-cook time.** Without device-level registration data, we can't compute time-to-value for new buyers, nor distinguish 'quiet' from 'churned' devices.
- **Firmware release log.** A simple markdown file (version → release date → change notes → rollout %) committed to a repo the dashboard can read. Would turn firmware cohort analysis from detective work into a lookup.
- **Orders by model.** Once Huntsman volume is meaningful, we need Shopify orders segmented by SKU so AOV and revenue mix stories resolve.

Everything above is instrumentation, not analysis. The analysis is blocked until the instrumentation exists.

## Benchmarks — what 'good' looks like

| Metric | Value | Interpretation |
|---|---|---|
| cook_success_rate_monthly | 68-70% | Observed across the 4 months with session derivation (Jan-Mar 2024 and Apr 2026 partial). The 2.1-point band across 26 months suggests this is a stable fleet characteristic. Treat monthly rollups <65% as unusual and worth investigation; >73% is unusually good. Daily cook_success on low-n days (<50 sessions) should be suppressed. |
| error_rate_monthly_steady_state | 0.7-1.4% | 22 of 26 non-anomalous months fall in this band. ≤1.3% healthy, 1.4-1.7% investigate (check fw cohort and connectivity), ≥1.8% incident. Dec 2025 at 1.9% is our highest normal-ops month. July-Aug 2024 (5.2% / 6.7%) is an instrumentation artifact and should be excluded from rolling averages. |
| avg_active_devices_summer_baseline | ~240/day | June-August 2025 average. Summer 2024 baseline was ~150. Use ~240 as 'normal summer' entering summer 2026 with growth adjustment. Summer 2024 → 2025 grew +60% avg active; a similar 2025 → 2026 lift would put summer 2026 around 300-340. |
| avg_active_devices_winter_baseline | ~180/day | Dec 2025 - Feb 2026 average. Previous winter (2024/25) baseline was ~130. A winter month under 150 going forward would suggest something is wrong given fleet growth trajectory. |
| summer_to_winter_active_ratio | 1.3-1.5x | Seasonal swing is compressing as the fleet matures. Was 1.7x in 2024; 1.3-1.5x now. Increased year-round usage is a sign of the customer base broadening beyond summer-only grillers. |
| sunday_vs_weekday_active_ratio | ~3x (holiday Sundays ~5x) | Sundays average ~380 active vs weekday ~120 over the last 89 days. Super Bowl (Feb 8, 2026: 624 active) and Easter (Apr 5, 2026: 623 active) push the ratio to ~5x. Holiday-cooking is a real demand driver and should be annotated on the fleet chart. |
| peak_hour_of_day | 21:00-22:00 local | Consistent across all 28 months. 18:00-23:00 carries most activity. UTC 0:00 appearing as top-6 peak is a late-night East Coast rollover artifact — localize the chart and it resolves cleanly. |
| avg_cook_temp_2026_baseline | 300-306°F | Up from ~285°F in 2024-25. Coincides with Huntsman ramp and fw 01.01.93+ releases. Can't yet attribute between model mix, firmware detection logic, and user shift without segmented data. Treat as new 2026 baseline for now. |
| hot_and_fast_session_share | 29% (Apr 2026) vs 17% (Q1 2024) | Hot-and-fast cooks nearly doubled as a share of sessions. Startup-only (abandoned) halved from 11% to 5%. Fleet is using the device more deliberately over time. Low-and-slow remains the plurality at ~40%. |
| session_duration_p50 | ~1738s (~29 min) | From the 7 persisted sessions. p25=1733, p75=2587, p90=3425. Sample is small; treat as directional. Aligns with monthly duration-range mix where 30m-2h is the 41-46% plurality. |
| time_to_stabilization_p50 | ~286s (~5 min) | Half of cooks reach target and hold within 5 minutes. p10=89s, p90=1032s (~17 min). Based on n=4 — not yet a real benchmark, but a credible early read of a core Venom value-prop metric. Needs session derivation backfill to firm up. |
| avg_wifi_rssi_fleet | -60 dBm | Classified 'fair' (not 'good'). Range across 28 months: -54 to -72 (worst was July 2024 anomaly). Without percentile instrumentation we can't size the weak-signal tail, but 20-25% at -70 or worse is plausible and would be a credible cause of cook abandonment and ambiguous connection-loss errors. |
| shopify_aov_2026 | $475-623 | Feb 2026 $475 (360 orders), Mar 2026 $623 (625 orders), Apr 2026 $549 (partial, 424 orders). March's higher AOV plausibly reflects Huntsman mix. Orders data only reliable from Feb 2026 forward — Nov 2025 - Jan 2026 show revenue without orders counts, a data-source gap. |

## Key findings

- **[LOW] [fleet]** Fleet tripled over 28 months; peak growing faster than avg — Avg daily active went from 75 (Jan 2024) to 224 (Apr 2026) — 3.0x. Peak active went from 217 to 899 (Nov 2025) — 4.1x. Widening peak-to-avg gap means weekend/holiday spikes are outgrowing everyday baseline, consistent with more casual/occasional users joining the base rather than uniform intensification of existing users.
- **[HIGH] [firmware]** Firmware 01.01.94 was rolled back between Jan and Feb 2026 — Jan 2026 events for fw 01.01.94: 2,421,085. Feb 2026: 3,312 — a 731x collapse. In the same window, 01.01.97 went from 54,590 to 610,631 events. Classic rollback/supersede signature. Fleet err rate dropped from 1.3% (Jan) to 0.9% (Feb), consistent with .97 being healthier, but without fw-cohort cook_success we can't judge whether .94 shipped a real regression or was simply superseded.
- **[HIGH] [hardware]** Huntsman product line ramped 70x Dec 2025 → Jan 2026 — Huntsman events: Sep 2025 2,546 → Dec 2025 34,562 → Jan 2026 2,411,560 (70x from Dec). Feb 2026 settled at ~340K/month steady state; Mar at ~550K. This is the biggest 2026 product story in telemetry and is currently invisible on the dashboard because active-device counts aren't model-segmented.
- **[MEDIUM] [reliability]** July 2024 is a 57M-event instrumentation artifact, not real activity — Events 5x normal (57,174,955), errors 30x normal (err rate 5.2%), avg cook temp 374°F (vs ~285°F normal), avg RSSI -72 (worst in series). 83% of events came from a single firmware version (01.01.23 at 47,797,967). Almost certainly a shadow-retention policy change, not customer behavior. Dashboard rolling averages are currently polluted by including this month.
- **[HIGH] [usage]** Session derivation complete for only 4 of 28 months — #1 analytical gap — Monthly session counts are zero for all months except Jan-Mar 2024 and Apr 2026 (partial). This blocks firmware cohort analysis, sessions-per-device trends over time, retention curves, and model-segmented cook success. Until the backfill runs, most cohort questions this report tries to ask have no data-backed answer.
- **[LOW] [usage]** Cook behavior shifted: hot-and-fast nearly doubled, abandons halved — Hot-and-fast share rose from 17% (Q1 2024 avg) to 29% (Apr 2026). Over-400°F cooks rose from 14% to 21%. Startup-only (abandoned) dropped from 11% to 5%. Under-30m sessions dropped from 19% to 12%. Fleet is using the device more deliberately — fewer failed setups, more committed cooks, and higher temperatures than in 2024.
- **[MEDIUM] [reliability]** Dec 2025 had highest normal-ops error rate (1.9%), possibly fw-related — Excluding July-Aug 2024, Dec 2025 at 1.9% is the worst error-rate month in 26. It coincides with firmware 01.01.93 first appearing at non-trivial volume (398,290 events) and the Kettle22 model variant jumping to 374,558 events. Not conclusive without fw-cohort data, but worth a breakdown.
- **[MEDIUM] [dashboard_framing]** Session archetype classifier appears broken — All 7 persisted cook_session records bucket to archetype '?'. Either the classifier isn't running, its output isn't being persisted correctly, or the persistence layer is dropping the field. The dashboard archetype panel is currently unusable and should be suppressed until it produces signal.
- **[MEDIUM] [usage]** Sessions-per-active-device appears to have halved since 2024 — unverified — Jan-Mar 2024 averaged ~1.06 sessions per active device per day (2,461 / 31 / 75 = 1.06; Mar 2024 = 1.07). Apr 2026 partial: 1,593 / 15 / 223.7 = 0.47. Could be real usage dilution as the fleet broadens, could be derivation logic drift between 2024 and 2026 code paths, could be a one-off. Cannot separate without the 24-month backfill.
- **[LOW] [seasonality]** Holiday-Sunday effect is real and sets telemetry records — Feb 8, 2026 (Super Bowl LX) logged 624 active, 1,205,595 events — the highest single day in the 89-day window. Apr 5, 2026 (Easter) logged 623 active, 1,245,372 events — biggest day of 2026 YTD. Sundays overall run ~3x weekday activity; holiday Sundays ~5x.
- **[LOW] [usage]** Avg cook temp jumped +15-18°F between 2025 and 2026 — 2024 median monthly avg_cook_temp ~285°F. 2025 median ~288°F. 2026 YTD: 300-306°F (Jan 306, Feb 306, Mar 300, Apr 301). Shift coincides with Huntsman volume ramp and fw 01.01.93+ releases. Can't yet attribute between model mix, firmware detection logic, and user shift without segmented data.
- **[LOW] [hardware]** Fleet wifi RSSI averages -60 dBm ('fair') — weak-signal tail invisible — Across 28 months avg RSSI ranges -54 to -72 with median -60. -60 is 'fair', -70 is 'weak'. Without percentile instrumentation we can't size the weak-signal tail, but ~20-25% of the fleet at -70 or worse is plausible — a candidate contributor to cook abandonment and ambiguous 'connection lost' errors.

## Recommendations

- **[research] [large]** Complete session derivation backfill for 24 missing months — This is the single biggest unlock for future analysis. Until it runs, we cannot compute fw-cohort cook_success (which would resolve the 01.01.94 question), model-segmented cook success (Huntsman vs Weber clip-on), sessions-per-device trends, or retention curves. Run the derivation on the full history using current logic. Also document the logic in a versioned README so future methodology changes are auditable and we can distinguish 'methodology drift' from 'real behavior change'.
- **[firmware] [small]** Fix or suppress the session archetype classifier — All 7 persisted sessions bucket to '?'. Either the classifier is broken, its writes aren't persisting, or the field isn't being read back in the dashboard query. Triage this before spending UI real estate on an archetype panel. If it's fixable quickly, fix it; otherwise suppress the panel until it produces signal. A broken panel is worse than no panel.
- **[dashboard] [small]** Add model-segmented charts to the dashboard — Active-devices, events, and cook_success should split by W:K:22:1:V / Huntsman / Kettle22. The Huntsman ramp is the biggest 2026 story and is currently invisible. A stacked-area by model on the main fleet page would fix this in an evening of work. Also enables per-model err rate and avg_cook_temp breakdowns once session derivation catches up.
- **[dashboard] [medium]** Add firmware-cohort error-rate panel — Current dashboard shows fleet-wide error rate. A fw breakdown would immediately attribute Dec 2025's 1.9% spike, let us confirm or refute the 01.01.94 regression hypothesis, and give us regression detection on future releases. Also add a cohort-size context (e.g., don't show err rate for a fw with <50K events that month).
- **[dashboard] [small]** Annotate known anomalies and release events on time-series charts — July-Aug 2024 is a 57M-event shadow-retention artifact and should be banner-excluded from rolling averages. Also add callouts for firmware releases (e.g., '01.01.34 rolled out Nov 2024', '01.01.94 pulled Feb 2026'), Super Bowl, Easter, and major product launches (Huntsman Jan 2026). Cheap to implement, pays forward for every future analyst looking at these charts.
- **[research] [medium]** Post-mortem firmware 01.01.94 — 2.4M events deployed in Jan 2026, 3,312 events by Feb — a 731x collapse. Replaced by 01.01.97, which got 611K events in Feb. Document what .94 shipped, what got pulled, what .97 fixed, rollout/rollback timeline. Pair with telemetry observations (err rate moved from 1.3% → 0.9%, avg cook temp stayed at 306°F). Do this now while the context is fresh.
- **[product] [small]** Publish a plaintext firmware release log — A simple markdown file mapping firmware version → release date → change notes → rollout percentage, committed to a repo the dashboard can read. Would make firmware cohort analysis 10x cheaper and let anyone on the team (not just you) read these reports with full context. Pairs naturally with the fw-cohort err-rate panel.
- **[dashboard] [small]** Rename 'events' metric and add per-active-device normalization — 'Events' are DynamoDB shadow samples, not cook volume. The July 2024 anomaly proves the correlation breaks on sampling changes. Rename to 'device telemetry volume' and add an events-per-active-device-per-day panel (steady-state ~40-50K). Sampling-policy changes then become visible as step changes on the normalized chart.
- **[dashboard] [small]** Localize peak-hour chart to local time — UTC-indexed peak hour shows 0:00 as a top-6 peak in many months — that's late-night East Coast cooks rolling into UTC next-day. Default to PT (or user's browser timezone) and the peak cleanly resolves to 21:00-22:00 every month. Small, high-impact clarity fix.
- **[firmware] [medium]** Instrument RSSI percentile distribution and session termination reason — We track avg RSSI but not distribution. Add P10/P50/P90 monthly to size the weak-signal tail. Separately, add termination reason to sessions (completed / connection lost / user canceled / abandoned / timed out). Together these would let us attribute cook_success misses to root cause and separate weak-wifi cook losses from genuine user abandonment. Both sharpen the reliability story dramatically.
- **[dashboard] [small]** Label months with incomplete session derivation as 'pending' not '0' — Current dashboard shows 0 sessions for 24 months, indistinguishable from real zero activity. Relabel as 'pending derivation' (or hide the column for those months) so readers don't misread it as a catastrophic usage collapse. One-line fix once the data source exposes the distinction.
- **[dashboard] [small]** Fill Shopify orders data for Nov 2025 - Jan 2026 and track orders-by-model — Revenue appears for these months but orders = 0 — a data-source pull gap, not a business event. Complete the backfill so AOV is computable across the full window. Also start tracking orders by SKU (Weber clip-on vs Huntsman vs Giant Huntsman) so we can correlate telemetry Huntsman ramp with sales — the dashboard currently can't tell that story either.
