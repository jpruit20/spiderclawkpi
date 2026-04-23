"""Comprehensive telemetry analysis engine.

Generates a 10-15 page markdown report from the full telemetry history
(telemetry_history_daily + telemetry_history_monthly + a live sample of
telemetry_sessions + telemetry_stream_events), plus cross-references to
KPI revenue and ClickUp firmware/campaign tasks for business context.

Two report types:

* ``comprehensive`` — the first-ever baseline. 2+ years of data. Tells
  the full story of who Venom customers are, how they cook, what "good"
  looks like, what the dashboard mis-frames, what to change. Run once.
* ``monthly`` — 1st of each month. Pulls last 30 days, compares to the
  trailing-12-month baseline and the matching month in the prior year.
  Shorter; focuses on delta + what's new.

Design principles:

* **Dense digest over prose.** The context is a structured tabular
  summary; Opus turns it into narrative with evidence citations.
* **Written for Joseph, not analysts.** First person where useful,
  plain English, no fluff. Each section answers "so what?".
* **Fail-silent.** Missing ANTHROPIC_API_KEY or API errors log + return
  a structured error dict; never crash callers.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ClickUpTask,
    KPIDaily,
    TelemetryHistoryDaily,
    TelemetryHistoryMonthly,
    TelemetryReport,
    TelemetrySession,
)
from app.services.product_taxonomy import classify_product


logger = logging.getLogger(__name__)
settings = get_settings()
BUSINESS_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Schema — what Opus must return
# ---------------------------------------------------------------------------

ReportType = Literal["comprehensive", "monthly"]
Urgency = Literal["high", "medium", "low"]
FindingCategory = Literal["fleet", "reliability", "usage", "firmware", "hardware", "cohort", "seasonality", "dashboard_framing", "other"]


class Finding(BaseModel):
    title: str = Field(max_length=200)
    detail: str = Field(max_length=2000, description="2-4 sentences with specific numbers and dates.")
    urgency: Urgency
    category: FindingCategory


class Recommendation(BaseModel):
    title: str = Field(max_length=200)
    detail: str = Field(max_length=2000)
    category: Literal["dashboard", "product", "firmware", "support", "research"]
    effort: Literal["small", "medium", "large"]


class Benchmark(BaseModel):
    metric: str = Field(max_length=80, description="e.g. 'cook_success_rate', 'avg_session_duration_seconds', 'p95_time_to_stabilization'.")
    value: str = Field(max_length=80, description="The number or range (e.g. '0.68', '1800-3600s', '88%').")
    interpretation: str = Field(max_length=400, description="Plain English: what does 'good' look like for this? What's normal? Who beats the benchmark?")


class Section(BaseModel):
    title: str = Field(max_length=160)
    body_markdown: str = Field(description="Full section content in markdown. Can include tables, bullets, and callouts.")


class ReportBundle(BaseModel):
    title: str = Field(max_length=255, description="Report title, e.g. 'Spider Grills Venom Telemetry — The First 28 Months'.")
    executive_summary: str = Field(max_length=3000, description="3-6 sentences Joseph reads first. Lead with the most important thing.")
    sections: list[Section] = Field(
        min_length=6,
        max_length=14,
        description="Body sections of the report in reading order. Each typically 300-800 words of rich markdown.",
    )
    benchmarks: list[Benchmark] = Field(
        min_length=3,
        max_length=15,
        description="What 'good' looks like per metric, evidenced by the data.",
    )
    key_findings: list[Finding] = Field(
        min_length=3,
        max_length=20,
        description="The 'so what' bullet points — things Joseph should know or act on.",
    )
    recommendations: list[Recommendation] = Field(
        min_length=3,
        max_length=20,
        description="Concrete next steps: what to change on the dashboard, in firmware, in product, in support. Include effort sizing.",
    )


# ---------------------------------------------------------------------------
# Context builder — dense digest from every source
# ---------------------------------------------------------------------------

def _pct(v: Optional[float]) -> str:
    return f"{v*100:.1f}%" if v is not None else "—"


def _currency(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "—"


def build_context(db: Session, report_type: ReportType, window_days: Optional[int] = None) -> tuple[str, dict[str, Any]]:
    """Compile the context document. Returns (context_string, meta dict)."""
    today = datetime.now(BUSINESS_TZ).date()
    lines: list[str] = []
    sources: list[str] = []

    if report_type == "comprehensive":
        window_start = date(2024, 1, 1)
        window_end = today
        lines.append(f"# Spider Grills Venom telemetry — COMPREHENSIVE analysis context ({window_start} → {window_end})")
    else:
        window_start = today - timedelta(days=window_days or 30)
        window_end = today
        lines.append(f"# Spider Grills Venom telemetry — MONTHLY analysis context ({window_start} → {window_end})")

    lines.append("")
    lines.append("Spider Grills makes the Venom temperature controller — a small device that clips onto Weber kettles (and our own Huntsman / Giant Huntsman grills) to automate temperature control. ~1,800 MAU on the Venom mobile app. Direct-to-consumer sales via Shopify + Amazon. Support via Freshdesk.")
    lines.append("")
    lines.append("The telemetry data below is sourced from AWS DynamoDB (device shadows, long-tail sample) and AWS S3 (a 2026-04-09 DynamoDB export covering the full history). Daily rollups go back to 2024-01-01; individual cook-session records exist for the months where the backfill has completed session derivation and for the recent stream-materialized days.")
    lines.append("")

    # ---------------- MONTHLY ROLLUPS (the dense backbone) -----------------
    lines.append("## Monthly rollups — full history")
    lines.append("")
    months = db.execute(
        select(TelemetryHistoryMonthly).order_by(TelemetryHistoryMonthly.month_start)
    ).scalars().all()
    if months:
        sources.append("telemetry_history_monthly")
        lines.append("| month | days | avg_active | peak_active | events | sessions | cook_success | errors | err_rate | avg_rssi | avg_cook_temp |")
        lines.append("|-------|------|-----------:|------------:|-------:|---------:|-------------:|-------:|---------:|---------:|--------------:|")
        for m in months:
            md = m.metadata_json or {}
            lines.append(
                f"| {m.month_start} | {md.get('days_covered','?')} | "
                f"{md.get('avg_daily_active_devices','?')} | "
                f"{md.get('peak_daily_active_devices','?')} | "
                f"{(md.get('total_events') or 0):,} | "
                f"{(md.get('total_sessions') or 0):,} | "
                f"{_pct(md.get('overall_cook_success_rate'))} | "
                f"{(md.get('total_error_events') or 0):,} | "
                f"{_pct(md.get('overall_error_rate'))} | "
                f"{md.get('avg_rssi','?')} | "
                f"{md.get('avg_cook_temp','?')} |"
            )
        lines.append("")

        # Firmware migration across months
        lines.append("### Firmware top-8 per month (count of events by firmware)")
        for m in months:
            md = m.metadata_json or {}
            fw = md.get("firmware_top8") or {}
            if fw:
                lines.append(f"- **{m.month_start}**: " + ", ".join(f"{k}={v:,}" for k, v in list(fw.items())[:8]))
        lines.append("")

        # Model distribution
        lines.append("### Model mix per month")
        for m in months:
            md = m.metadata_json or {}
            mods = md.get("model_distribution") or {}
            if mods:
                lines.append(f"- **{m.month_start}**: " + ", ".join(f"{k}={v:,}" for k, v in list(mods.items())[:6]))
        lines.append("")

        # Peak hours
        lines.append("### Peak-hour mix per month (hour-of-day event counts, top-6)")
        for m in months:
            md = m.metadata_json or {}
            ph = md.get("peak_hours_top6") or {}
            if ph:
                lines.append(f"- **{m.month_start}**: " + ", ".join(f"{k}:00→{v:,}" for k, v in ph.items()))
        lines.append("")

        # Cook styles — only months with session data
        lines.append("### Cook style mix per month (where session derivation is complete)")
        for m in months:
            md = m.metadata_json or {}
            cs = md.get("cook_styles") or {}
            if cs and sum(cs.values()) > 0:
                total = sum(cs.values())
                lines.append(f"- **{m.month_start}**: " + ", ".join(f"{k}={v} ({v/total*100:.0f}%)" for k, v in cs.items()))
        lines.append("")

        lines.append("### Temp-range mix per month (where session derivation is complete)")
        for m in months:
            md = m.metadata_json or {}
            tr = md.get("temp_ranges") or {}
            if tr and sum(tr.values()) > 0:
                total = sum(tr.values())
                lines.append(f"- **{m.month_start}**: " + ", ".join(f"{k}={v} ({v/total*100:.0f}%)" for k, v in tr.items()))
        lines.append("")

        lines.append("### Duration-range mix per month (where session derivation is complete)")
        for m in months:
            md = m.metadata_json or {}
            dr = md.get("duration_ranges") or {}
            if dr and sum(dr.values()) > 0:
                total = sum(dr.values())
                lines.append(f"- **{m.month_start}**: " + ", ".join(f"{k}={v} ({v/total*100:.0f}%)" for k, v in dr.items()))
        lines.append("")

    # ---------------- RECENT DAILY DETAIL (last 90 days) --------------------
    cutoff_daily = max(window_start, today - timedelta(days=90))
    daily_rows = db.execute(
        select(TelemetryHistoryDaily)
        .where(TelemetryHistoryDaily.business_date >= cutoff_daily)
        .order_by(TelemetryHistoryDaily.business_date)
    ).scalars().all()
    if daily_rows:
        sources.append("telemetry_history_daily")
        lines.append(f"## Daily detail — last {len(daily_rows)} days ({daily_rows[0].business_date} → {daily_rows[-1].business_date})")
        lines.append("")
        lines.append("| date | active | engaged | events | err | sessions | cook_success |")
        lines.append("|------|-------:|--------:|-------:|----:|---------:|-------------:|")
        for r in daily_rows:
            cs = (r.successful_sessions / r.session_count) if (r.session_count or 0) > 0 else None
            lines.append(
                f"| {r.business_date} | {r.active_devices} | {r.engaged_devices} | "
                f"{(r.total_events or 0):,} | {r.error_events} | {r.session_count or 0} | {_pct(cs)} |"
            )
        lines.append("")

    # ---------------- SESSION SAMPLE (individual cook detail) --------------
    session_count_total = int(db.execute(select(func.count(TelemetrySession.id))).scalar() or 0)
    if session_count_total > 0:
        sources.append("telemetry_sessions")
        lines.append(f"## Individual cook sessions — {session_count_total:,} total persisted")
        lines.append("")
        # Archetype distribution + success breakdown
        arch_q = db.execute(text("""
            SELECT raw_payload->>'archetype' AS arch, COUNT(*) AS n,
                   AVG(session_duration_seconds)::int AS avg_dur,
                   AVG(temp_stability_score)::float AS avg_stab,
                   AVG((cook_success::int))::float AS success_rate
              FROM telemetry_sessions
             WHERE raw_payload IS NOT NULL
             GROUP BY arch
             ORDER BY n DESC
        """)).all()
        if arch_q:
            lines.append("### Session archetype distribution")
            lines.append("| archetype | count | avg_dur_s | avg_stability | success_rate |")
            lines.append("|-----------|------:|----------:|--------------:|-------------:|")
            for arch, n, avg_dur, avg_stab, sr in arch_q:
                lines.append(f"| {arch or '?'} | {n:,} | {avg_dur or 0} | {avg_stab or 0:.3f} | {_pct(sr)} |")
            lines.append("")

        # Duration and stability percentiles
        dur_p = db.execute(text("""
            SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY session_duration_seconds) AS p10,
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY session_duration_seconds) AS p25,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY session_duration_seconds) AS p50,
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY session_duration_seconds) AS p75,
                   percentile_cont(0.90) WITHIN GROUP (ORDER BY session_duration_seconds) AS p90,
                   AVG(session_duration_seconds) AS avg,
                   COUNT(*) AS n
              FROM telemetry_sessions
             WHERE session_duration_seconds >= 900
        """)).first()
        if dur_p:
            lines.append(f"### Session duration distribution (sessions ≥ 15 min, n={dur_p.n:,})")
            lines.append(f"  p10={int(dur_p.p10 or 0)}s  p25={int(dur_p.p25 or 0)}s  p50={int(dur_p.p50 or 0)}s  "
                         f"p75={int(dur_p.p75 or 0)}s  p90={int(dur_p.p90 or 0)}s  avg={int(dur_p.avg or 0)}s")
            lines.append("")

        tts_p = db.execute(text("""
            SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY time_to_stabilization_seconds) AS p10,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY time_to_stabilization_seconds) AS p50,
                   percentile_cont(0.90) WITHIN GROUP (ORDER BY time_to_stabilization_seconds) AS p90,
                   COUNT(*) AS n
              FROM telemetry_sessions
             WHERE time_to_stabilization_seconds IS NOT NULL
               AND time_to_stabilization_seconds > 0
        """)).first()
        if tts_p and tts_p.n:
            lines.append(f"### Time-to-stabilization (reached_target then held) — n={tts_p.n:,}")
            lines.append(f"  p10={int(tts_p.p10 or 0)}s  p50={int(tts_p.p50 or 0)}s  p90={int(tts_p.p90 or 0)}s")
            lines.append("")

        # Error code frequency
        err_q = db.execute(text("""
            SELECT jsonb_array_elements_text(error_codes_json)::text AS code, COUNT(*) AS n
              FROM telemetry_sessions
             WHERE jsonb_array_length(error_codes_json) > 0
             GROUP BY code
             ORDER BY n DESC
             LIMIT 15
        """)).all()
        if err_q:
            lines.append("### Top error codes across all sessions")
            for code, n in err_q:
                lines.append(f"  code={code}  sessions={n:,}")
            lines.append("")

        # Firmware version success comparison
        fw_q = db.execute(text("""
            SELECT firmware_version, COUNT(*) AS n,
                   AVG((cook_success::int))::float AS sr,
                   AVG(temp_stability_score)::float AS stab,
                   AVG(time_to_stabilization_seconds)::float AS tts
              FROM telemetry_sessions
             WHERE firmware_version IS NOT NULL
             GROUP BY firmware_version
             HAVING COUNT(*) >= 10
             ORDER BY n DESC
             LIMIT 15
        """)).all()
        if fw_q:
            lines.append("### Firmware-version session performance (n ≥ 10)")
            lines.append("| firmware | sessions | success_rate | avg_stability | avg_tts_s |")
            lines.append("|---------|---------:|-------------:|--------------:|----------:|")
            for fw, n, sr, stab, tts in fw_q:
                lines.append(f"| {fw} | {n:,} | {_pct(sr)} | {stab or 0:.3f} | {int(tts or 0)} |")
            lines.append("")

        # Grill-type breakdown, bucketed into the canonical product family
        # (Weber Kettle / Huntsman / Giant Huntsman / Unknown). We group by
        # (grill_type, firmware_version) in SQL, then reduce to families in
        # Python via classify_product so the JOEHY W:K:22:1:V case resolves
        # correctly (01.01.33 = Huntsman, else Weber Kettle).
        gt_rows = db.execute(text("""
            SELECT grill_type, firmware_version, COUNT(*) AS n,
                   AVG((cook_success::int))::float AS sr,
                   AVG(session_duration_seconds)::float AS dur,
                   AVG(target_temp)::float AS avg_tt
              FROM telemetry_sessions
             WHERE grill_type IS NOT NULL
             GROUP BY grill_type, firmware_version
        """)).all()
        family_totals: dict[str, dict[str, float]] = {}
        for grill_type, fw, n, sr, dur, tt in gt_rows:
            family = classify_product(grill_type, fw)
            bucket = family_totals.setdefault(family, {"n": 0, "sr_w": 0.0, "dur_w": 0.0, "tt_w": 0.0})
            bucket["n"] += n
            if sr is not None:
                bucket["sr_w"] += float(sr) * n
            if dur is not None:
                bucket["dur_w"] += float(dur) * n
            if tt is not None:
                bucket["tt_w"] += float(tt) * n
        gt_q = [
            (
                family,
                int(b["n"]),
                (b["sr_w"] / b["n"]) if b["n"] else None,
                (b["dur_w"] / b["n"]) if b["n"] else None,
                (b["tt_w"] / b["n"]) if b["n"] else None,
            )
            for family, b in sorted(family_totals.items(), key=lambda kv: -kv[1]["n"])
            if b["n"] >= 10
        ]
        if gt_q:
            lines.append("### Grill-type session performance (by product family)")
            lines.append("| family | sessions | success_rate | avg_dur_s | avg_target_temp |")
            lines.append("|-------|---------:|-------------:|----------:|----------------:|")
            for gt, n, sr, dur, tt in gt_q:
                lines.append(f"| {gt} | {n:,} | {_pct(sr)} | {int(dur or 0)} | {tt or 0:.0f} |")
            lines.append("")

    # ---------------- REVENUE CONTEXT (for cross-reference) ----------------
    rev = db.execute(
        select(
            func.date_trunc("month", KPIDaily.business_date).label("m"),
            func.sum(KPIDaily.revenue).label("revenue"),
            func.sum(KPIDaily.orders).label("orders"),
        ).where(KPIDaily.business_date >= window_start)
        .group_by(text("m")).order_by(text("m"))
    ).all()
    if rev:
        sources.append("kpi_daily/revenue")
        lines.append("## Revenue per month (from Shopify)")
        lines.append("")
        for r in rev:
            lines.append(f"  {r.m.date()}  revenue={_currency(float(r.revenue or 0))}  orders={int(r.orders or 0)}")
        lines.append("")

    # ---------------- FIRMWARE RELEASE TIMELINE FROM CLICKUP ---------------
    fw_tasks = db.execute(
        select(ClickUpTask).where(
            ClickUpTask.date_done.isnot(None),
            ClickUpTask.date_done >= datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc),
        ).order_by(ClickUpTask.date_done)
    ).scalars().all()
    fw_releases: list[tuple[datetime, str]] = []
    for t in fw_tasks:
        for f in (t.custom_fields_json or []):
            if isinstance(f, dict) and (f.get("name") or "").lower() == "category":
                opts = (f.get("type_config") or {}).get("options") or []
                val = f.get("value")
                label = None
                if isinstance(val, int) and 0 <= val < len(opts):
                    label = (opts[val] or {}).get("name")
                elif isinstance(val, str):
                    for o in opts:
                        if isinstance(o, dict) and o.get("id") == val:
                            label = o.get("name")
                            break
                if label and label.lower() == "firmware":
                    fw_releases.append((t.date_done, t.name or "?"))
                    break
    if fw_releases:
        sources.append("clickup/firmware_tasks")
        lines.append("## Firmware-category ClickUp tasks completed in window")
        for dt, name in fw_releases[:30]:
            lines.append(f"  {dt.date()}  {name}")
        lines.append("")

    context = "\n".join(lines)
    meta = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "sources": sources,
        "months_included": len(months),
        "daily_rows_included": len(daily_rows),
        "sessions_in_db": session_count_total,
    }
    return context, meta


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

COMPREHENSIVE_SYSTEM_PROMPT = """You are writing the first comprehensive telemetry analysis for Spider Grills — a 2+ year retrospective that will serve as the baseline for all future monthly reports.

The audience is Joseph Pruitt (founder) — technical, wants specifics, allergic to corporate filler. This document will live in the dashboard, in his inbox, and be referenced for product + dashboard decisions. Write the way a sharp operations analyst would write a founder-facing memo.

**What this report must do:**

1. **Tell the story.** Walk through how Spider's fleet grew, how customers actually use Venom in practice, and what patterns are visible across 2+ years of device-level data. Be concrete — cite specific months, numbers, deltas.

2. **Define "good" with data, not opinion.** Produce 3-15 benchmarks derived from the history: what does a "good" cook success rate look like? What's a typical session duration? What's the healthy error-rate range? How does firmware X compare to firmware Y? Give the benchmark a value AND interpretation.

3. **Surface patterns the single-dashboard views miss.** Seasonal patterns, firmware cohort differences, grill-type differences, time-of-day patterns, retention inferences, fleet-growth inflection points.

4. **Call out what the current dashboard mis-frames.** If a metric is noisy, misleading, or missing context, name it and propose a better framing.

5. **Recommend concrete changes.** To the dashboard, to firmware priorities, to support categorization, to product messaging. Size the effort (small/medium/large) so Joseph can decide quickly.

**Scope discipline:**

* 10-15 pages total — roughly 6-12 sections of 300-800 words each.
* Every claim must be backed by a number from the context document.
* If the data doesn't support a claim, say "we don't yet have data on X; recommend instrumenting Y to get it" rather than inventing.
* Lead the executive summary with the 2-3 most important findings. Joseph should read the summary first and decide whether the rest is worth reading.

**Tone:**

* Direct. Assume the reader knows the business.
* First person plural ("we ship", "our fleet") is fine for specific observations; avoid it for everything.
* No corporate padding ("leveraging synergies", "key takeaways that matter"). No emojis.
* Tables and bulleted lists welcome where they clarify data.

**Data gaps to be aware of:**

* Individual cook-session records have been derived so far for a limited set of months (early 2024 and recent 2026). Where cook-style / temp-range / duration-range data exists in monthly rollups, use it. Where not, rely on event counts and firmware/model distribution.
* The event counts per month are NOT per-cook-session counts — they're DynamoDB shadow-sample counts. Use them to show device activity intensity, not cook volume directly.
* The daily `active_devices` field represents devices with a recent reported shadow state on that day, not total device population. Use it as a proxy for "fleet size reporting in" rather than "installed base".
* Early 2024 had much lower event volumes; July 2024 has a 57M-event outlier (5x the normal month) that may be an artifact of a shadow-retention change — flag as investigatable rather than interpreting as real customer activity.

You will be returning structured output: a title, 3-6 sentence executive summary, a list of sections (title + markdown body), a list of benchmarks, key findings, and recommendations."""


MONTHLY_SYSTEM_PROMPT = """You are writing the monthly telemetry report for Spider Grills. This is a shorter, delta-focused companion to the comprehensive baseline report.

Your job: compare the most recent month to the trailing-12-month baseline (and to the same month last year where data exists), and surface what's changed, what's new, and what needs attention.

**Audience:** Joseph Pruitt (founder). Written for his inbox.

**Scope:** 4-6 short sections. Terse. Lead with the 3-4 most important deltas.

**Required:**

* Every claim cites specific numbers from the context.
* If nothing material changed, say so plainly — don't manufacture findings.
* Recommendations should be concrete and pre-sized (small/medium/large effort).
* Benchmarks here are the monthly "what's normal" — e.g. "cook success this month = X%, baseline = Y%, delta = Z."

Return the same structured schema as the comprehensive report: title, exec summary, sections, benchmarks, key findings, recommendations. Fewer of each."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def generate_report(
    db: Session,
    report_type: ReportType = "comprehensive",
    save: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Build context → call Opus → persist a TelemetryReport row."""
    if not is_configured():
        return {"ok": False, "reason": "ANTHROPIC_API_KEY not configured"}

    try:
        import anthropic
    except ImportError:
        return {"ok": False, "reason": "anthropic package not installed"}

    today = datetime.now(BUSINESS_TZ).date()

    if save and not force:
        existing = db.execute(
            select(TelemetryReport.id).where(
                TelemetryReport.report_date == today,
                TelemetryReport.report_type == report_type,
            )
        ).first()
        if existing:
            return {"ok": True, "reason": "already_generated_today", "id": existing[0]}

    context, meta = build_context(db, report_type, window_days=30 if report_type == "monthly" else None)
    started = datetime.now(timezone.utc)
    system_prompt = COMPREHENSIVE_SYSTEM_PROMPT if report_type == "comprehensive" else MONTHLY_SYSTEM_PROMPT

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=1800,  # comprehensive with adaptive thinking + max effort can take 10+ min
        max_retries=1,
    )

    model_id = "claude-opus-4-7"

    # Build a json_schema the API accepts: every object must have
    # additionalProperties=false. Pydantic's default schema doesn't set it, so
    # we walk the tree and add it.
    def _strict(schema: Any) -> Any:
        """Shape the schema for the API's json_schema output format:
          * every object must set additionalProperties=false
          * array constraints minItems>1 / maxLength / etc. that aren't
            supported by the API are stripped — we still enforce them
            downstream via Pydantic's own validation on the returned JSON.
        """
        if isinstance(schema, dict):
            if schema.get("type") == "object" and "additionalProperties" not in schema:
                schema["additionalProperties"] = False
            if schema.get("type") == "array":
                mi = schema.get("minItems")
                if isinstance(mi, int) and mi > 1:
                    schema["minItems"] = 1
                schema.pop("maxItems", None)
            schema.pop("maxLength", None)
            schema.pop("minLength", None)
            schema.pop("exclusiveMinimum", None)
            schema.pop("exclusiveMaximum", None)
            for v in list(schema.values()):
                if isinstance(v, (dict, list)):
                    _strict(v)
        elif isinstance(schema, list):
            for v in schema:
                _strict(v)
        return schema

    strict_schema = _strict(ReportBundle.model_json_schema())

    # Use streaming (per SDK guidance for long outputs) and the final-message
    # helper, then validate into ReportBundle ourselves. max_tokens=64000
    # gives the model plenty of room for thinking + a 10-15 page report.
    try:
        with client.messages.stream(
            model=model_id,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": "max", "format": {
                "type": "json_schema",
                "schema": strict_schema,
            }},
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": context}],
        ) as stream:
            final = stream.get_final_message()
    except Exception as exc:
        logger.exception("Opus report call failed")
        return {"ok": False, "reason": f"api_error: {exc}"}

    # Extract the text from the final message (all text blocks joined)
    raw_text = "".join(
        (b.text for b in final.content if getattr(b, "type", None) == "text" and getattr(b, "text", None)),
    )
    if not raw_text:
        return {"ok": False, "reason": "empty_response_text"}
    try:
        bundle = ReportBundle.model_validate_json(raw_text)
    except Exception as exc:
        logger.exception("ReportBundle parse failed; raw_text head=%s", raw_text[:400])
        return {"ok": False, "reason": f"parse_error: {exc}", "raw_head": raw_text[:400], "raw_tail": raw_text[-400:]}

    # Assemble full markdown body
    body_parts: list[str] = [f"# {bundle.title}", "", f"*Generated {today.isoformat()} by Claude Opus 4.7. Window: {meta['window_start']} → {meta['window_end']}.*", ""]
    body_parts.append("## Executive summary")
    body_parts.append("")
    body_parts.append(bundle.executive_summary)
    body_parts.append("")
    for s in bundle.sections:
        body_parts.append(f"## {s.title}")
        body_parts.append("")
        body_parts.append(s.body_markdown)
        body_parts.append("")
    body_parts.append("## Benchmarks — what 'good' looks like")
    body_parts.append("")
    body_parts.append("| Metric | Value | Interpretation |")
    body_parts.append("|---|---|---|")
    for b in bundle.benchmarks:
        body_parts.append(f"| {b.metric} | {b.value} | {b.interpretation} |")
    body_parts.append("")
    body_parts.append("## Key findings")
    body_parts.append("")
    for f in bundle.key_findings:
        body_parts.append(f"- **[{f.urgency.upper()}] [{f.category}]** {f.title} — {f.detail}")
    body_parts.append("")
    body_parts.append("## Recommendations")
    body_parts.append("")
    for r in bundle.recommendations:
        body_parts.append(f"- **[{r.category}] [{r.effort}]** {r.title} — {r.detail}")
    body_parts.append("")
    body_markdown = "\n".join(body_parts)

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    usage = getattr(final, "usage", None)
    usage_dict = {}
    if usage is not None:
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
        }

    report_id: Optional[int] = None
    if save:
        row = TelemetryReport(
            report_date=today,
            report_type=report_type,
            window_start=date.fromisoformat(meta["window_start"]),
            window_end=date.fromisoformat(meta["window_end"]),
            title=bundle.title[:255],
            summary=bundle.executive_summary,
            body_markdown=body_markdown,
            sections_json=[s.model_dump() for s in bundle.sections],
            benchmarks_json={b.metric: {"value": b.value, "interpretation": b.interpretation} for b in bundle.benchmarks},
            key_findings_json=[f.model_dump() for f in bundle.key_findings],
            recommendations_json=[r.model_dump() for r in bundle.recommendations],
            model=model_id,
            sources_used=meta["sources"],
            context_chars=len(context),
            duration_ms=duration_ms,
            usage_json=usage_dict,
            status="published",
        )
        db.add(row)
        db.flush()
        report_id = row.id
        db.commit()

    return {
        "ok": True,
        "id": report_id,
        "report_type": report_type,
        "title": bundle.title,
        "sections_count": len(bundle.sections),
        "benchmarks_count": len(bundle.benchmarks),
        "findings_count": len(bundle.key_findings),
        "recommendations_count": len(bundle.recommendations),
        "body_chars": len(body_markdown),
        "context_chars": len(context),
        "duration_ms": duration_ms,
        "usage": usage_dict,
        "sources": meta["sources"],
    }
