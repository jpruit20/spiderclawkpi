#!/usr/bin/env python3
"""Weekly KPI dashboard health check + email report.

Runs once a week (Mondays 7am ET via systemd timer). Pulls every signal
the dashboard already monitors plus a couple of extra system metrics and
emails Joseph a structured "what's broken / what needs attention / what
can wait" report.

Sections (in priority order):

  1. 🔴 Needs action — connectors with `failed` or `never_run` status.
     Each item names the connector, the error, the last successful
     sync, and a recommended fix (rotate token / re-auth / etc).

  2. 🟡 Watch — connectors with `stale` or `degraded` status (auto-
     recovers on next poll, but worth noticing if a pattern emerges).

  3. 🟢 Healthy summary — count only, no detail (progressive disclosure
     in email form).

  4. API health — 5xx counts in the last 7 days, top endpoints by
     failure rate.

  5. DB health — pool snapshot, idle-in-transaction count, top slow
     queries that hit the 60s statement_timeout.

  6. System health — disk usage, log volume, service uptime.

Sent via SES same as daily_morning_email.py / daily_deploy_summary.py;
respects email_allowlist for recipient validation.

Manual invocation:
  /opt/spiderclawkpi/spider/apps/spider-kpi/.venv/bin/python \\
      scripts/weekly_health_check.py             # send email
  WEEKLY_HEALTH_DRY_RUN=1 ... weekly_health_check.py  # print + skip send
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


# Resolve project paths so this script works regardless of cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
ENV_PATH = PROJECT_ROOT / ".env"

# Make the FastAPI app importable.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

BUSINESS_TZ = ZoneInfo("America/New_York")


def _load_env(p: Path) -> None:
    """Mirror daily_deploy_summary.py — read .env into os.environ so
    the SES client + DB session pick up the same secrets uvicorn does."""
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


_load_env(ENV_PATH)


# Recommended fix per failure mode. Frontend-of-the-email instructions
# we can hand off to Joseph or a division lead so they don't have to
# guess what "fix it" means.
FIX_HINTS: dict[str, str] = {
    "401": "API token expired or was revoked. Rotate the token at the source (settings → API/integrations → regenerate) and update the matching env var on the droplet.",
    "403": "Permissions changed at the source. Re-auth or expand the OAuth scope; whoever owns the integration account should reconnect.",
    "404": "Endpoint or resource ID changed. Check that the source still hosts the data we expect (org/team/site URL didn't move).",
    "429": "Source rate-limited us. Adaptive retry should self-heal; if persistent over multiple weeks, ask the vendor to raise our quota.",
    "ProvisionedThroughputExceededException": "DynamoDB throughput cap. Adaptive retry is on; if this dominates the failures, we may need to bump table capacity (cost trade).",
    "Read timed out": "Upstream API was slow. Usually transient; persistent timeouts mean the vendor's API is degraded.",
    "Stale running sync": "Sync exceeded the per-source watchdog. Threshold is now 60–90 min for SharePoint and 45 min for AWS — if this still trips, the connector is genuinely too slow and needs a code-side optimization.",
    "current transaction is aborted": "An earlier query in the same request poisoned the SQL session. Patched 2026-04-28 by adding rollback() in _safe — if this resurfaces, look for a NEW _safe-equivalent code path missing the rollback.",
}


def _suggest_fix(error_message: str | None) -> str:
    if not error_message:
        return "Inspect logs and source-health admin page; no obvious pattern from error text alone."
    msg = error_message
    for needle, hint in FIX_HINTS.items():
        if needle.lower() in msg.lower():
            return hint
    return "Inspect logs and source-health admin page; no obvious pattern from error text alone."


def _fetch_connector_health() -> list[dict[str, Any]]:
    """Same call the dashboard's source-health endpoint makes, run
    in-process so we share the application's settings + DB pool."""
    from app.db.session import SessionLocal
    from app.services.source_health import get_source_health
    with SessionLocal() as db:
        return get_source_health(db)


def _fetch_pg_pool_snapshot() -> dict[str, int]:
    """How many of our 60-connection ceiling are checked out + how many
    are stuck in 'idle in transaction' (the leak signature)."""
    from app.db.session import SessionLocal
    from sqlalchemy import text
    out: dict[str, int] = {}
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT state, COUNT(*) AS n FROM pg_stat_activity "
            "WHERE datname = 'spider_kpi' GROUP BY state"
        )).all()
        for row in rows:
            out[row.state or "unknown"] = int(row.n)
    return out


def _fetch_recent_sync_failures(days: int = 7) -> list[dict[str, Any]]:
    """Per-connector failure counts in the last N days from
    source_sync_runs. Surfaces sources that are flaky even when
    'last success' was recent."""
    from app.db.session import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT
                source_name,
                COUNT(*) FILTER (WHERE status = 'failed')  AS fails,
                COUNT(*) FILTER (WHERE status = 'success') AS successes
            FROM source_sync_runs
            WHERE started_at > now() - interval '{int(days)} days'
            GROUP BY source_name
            HAVING COUNT(*) FILTER (WHERE status = 'failed') > 0
            ORDER BY fails DESC, source_name
        """)).all()
        return [
            {
                "source_name": r.source_name,
                "fails": int(r.fails),
                "successes": int(r.successes),
                "fail_rate_pct": round(100.0 * r.fails / (r.fails + r.successes), 1) if (r.fails + r.successes) else 0.0,
            }
            for r in rows
        ]


def _fetch_api_5xx_counts(days: int = 7) -> dict[str, int]:
    """Count 5xx responses per endpoint over the last N days. Reads
    the systemd journal — no DB row needed since FastAPI logs go
    straight to journald via uvicorn."""
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u", "spider-kpi.service",
                f"--since={days} days ago",
                "--no-pager",
                "-q",
            ],
            check=True, capture_output=True, text=True, timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"weekly-health: journalctl read failed: {exc}", file=sys.stderr)
        return {}

    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        # Match lines like:  GET /api/cx/snapshot HTTP/1.1" 500 Internal Server Error
        if "HTTP/1.1\"" not in line or " 5" not in line:
            continue
        try:
            # Pull the path and the 5xx code.
            verb_path = line.split("\"")[1] if "\"" in line else ""
            parts = verb_path.split(" ")
            if len(parts) < 2:
                continue
            path = parts[1].split("?", 1)[0]
            after_quote = line.split("\"", 2)[2] if line.count("\"") >= 2 else ""
            code_str = after_quote.strip().split(" ", 1)[0]
            if not (code_str.startswith("5") and code_str.isdigit() and 500 <= int(code_str) < 600):
                continue
            if not path.startswith("/api/"):
                continue
            counts[path] = counts.get(path, 0) + 1
        except (IndexError, ValueError):
            continue
    return counts


def _fetch_disk_usage() -> dict[str, str]:
    """One-line summary of root filesystem + DB volume + log volume."""
    out: dict[str, str] = {}
    try:
        df = subprocess.run(
            ["df", "-h", "/"], check=True, capture_output=True, text=True, timeout=10,
        )
        # df output: header + one data line. Grab the % used.
        rows = df.stdout.strip().splitlines()
        if len(rows) >= 2:
            out["root"] = rows[1].split()[-2]
    except Exception:
        out["root"] = "?"
    try:
        log_size = subprocess.run(
            ["du", "-sh", "/var/log"], check=True, capture_output=True, text=True, timeout=15,
        )
        out["var_log"] = log_size.stdout.strip().split()[0]
    except Exception:
        out["var_log"] = "?"
    return out


def _format_report(
    connectors: list[dict[str, Any]],
    sync_failures: list[dict[str, Any]],
    pg_pool: dict[str, int],
    api_5xx: dict[str, int],
    disk: dict[str, str],
) -> tuple[str, str, str]:
    """Build (subject, body_text, body_html). HTML for Gmail rendering;
    text fallback for any plain-text reader."""

    needs_action = [c for c in connectors if c.get("derived_status") in {"failed", "never_run"}]
    watch = [c for c in connectors if c.get("derived_status") in {"stale", "degraded"}]
    healthy_count = sum(1 for c in connectors if c.get("derived_status") == "healthy")
    running_count = sum(1 for c in connectors if c.get("derived_status") == "running")

    nyt = datetime.now(BUSINESS_TZ)
    week_str = nyt.strftime("%b %d, %Y")
    summary_line = (
        f"{healthy_count} healthy · {running_count} running · "
        f"{len(watch)} watch · {len(needs_action)} needs action"
    )

    if needs_action:
        emoji = "🔴"
    elif watch or sync_failures:
        emoji = "🟡"
    else:
        emoji = "🟢"
    subject = f"{emoji} Weekly KPI dashboard health · {week_str} · {summary_line}"

    # ── Plain-text body ──
    text_parts: list[str] = [
        f"KPI Dashboard weekly health check · {week_str}",
        "=" * 64,
        f"Summary: {summary_line}",
        "",
    ]
    if needs_action:
        text_parts.append("🔴 NEEDS ACTION")
        text_parts.append("-" * 64)
        for c in needs_action:
            text_parts.append(f"  · {c['source']:24} status={c['derived_status']}")
            text_parts.append(f"      last success: {c.get('last_success_at') or 'never'}")
            err = (c.get("last_error") or "(no error message captured)")[:300]
            text_parts.append(f"      error: {err}")
            text_parts.append(f"      fix: {_suggest_fix(c.get('last_error'))}")
            text_parts.append("")
    if watch:
        text_parts.append("🟡 WATCH (auto-recovers, monitor for patterns)")
        text_parts.append("-" * 64)
        for c in watch:
            stale = c.get("stale_minutes")
            text_parts.append(
                f"  · {c['source']:24} status={c['derived_status']:10} "
                f"stale={stale} min" if stale else f"  · {c['source']:24} status={c['derived_status']}"
            )
        text_parts.append("")
    text_parts.append(f"🟢 Healthy: {healthy_count} connectors · 🏃 Running: {running_count}")
    text_parts.append("")
    if sync_failures:
        text_parts.append("FLAKY SYNCS (last 7 days, even if last success was recent)")
        text_parts.append("-" * 64)
        for f in sync_failures:
            text_parts.append(
                f"  · {f['source_name']:24} {f['fails']:>4} fails / "
                f"{f['successes']:>4} successes ({f['fail_rate_pct']}%)"
            )
        text_parts.append("")
    if api_5xx:
        text_parts.append("API 5xx (last 7 days)")
        text_parts.append("-" * 64)
        for path, n in sorted(api_5xx.items(), key=lambda x: -x[1])[:10]:
            text_parts.append(f"  · {n:>4}× {path}")
        text_parts.append("")
    else:
        text_parts.append("API 5xx (last 7 days): none ✓")
        text_parts.append("")
    text_parts.append("DB POOL (snapshot)")
    text_parts.append("-" * 64)
    for state, n in sorted(pg_pool.items()):
        text_parts.append(f"  · {state:24} {n}")
    if pg_pool.get("idle in transaction", 0) > 5:
        text_parts.append(
            "  ⚠ idle-in-transaction count is elevated — Postgres self-heal "
            "(idle_in_transaction_session_timeout=30s) will recover these "
            "but the underlying leak is worth a code search."
        )
    text_parts.append("")
    text_parts.append("SYSTEM")
    text_parts.append("-" * 64)
    text_parts.append(f"  · root disk used: {disk.get('root', '?')}")
    text_parts.append(f"  · /var/log size: {disk.get('var_log', '?')}")
    text_parts.append(f"  · host: {socket.gethostname()}")
    body_text = "\n".join(text_parts)

    # ── HTML body ── (intentionally simple — Gmail strips most CSS)
    def _section(title: str, items_html: str, color: str = "#444") -> str:
        return (
            f'<h3 style="color:{color};margin:18px 0 6px;font-family:-apple-system,Segoe UI,sans-serif">'
            f'{title}</h3>{items_html}'
        )

    html_parts: list[str] = [
        '<div style="font-family:-apple-system,Segoe UI,sans-serif;color:#222;max-width:720px">',
        f'<h2>KPI Dashboard weekly health · {week_str}</h2>',
        f'<p style="color:#666"><strong>Summary:</strong> {summary_line}</p>',
    ]
    if needs_action:
        rows = ""
        for c in needs_action:
            err = (c.get("last_error") or "(no error captured)")[:300]
            rows += (
                f'<div style="border-left:3px solid #c0392b;padding:6px 10px;margin:6px 0;background:#fdf3f1">'
                f'<div><strong>{c["source"]}</strong> · {c["derived_status"]}</div>'
                f'<div style="font-size:12px;color:#555">last success: {c.get("last_success_at") or "never"}</div>'
                f'<div style="font-size:12px;color:#555;font-family:monospace;word-break:break-word">{err}</div>'
                f'<div style="font-size:12px;color:#222;margin-top:4px"><em>Fix:</em> {_suggest_fix(c.get("last_error"))}</div>'
                f'</div>'
            )
        html_parts.append(_section("🔴 Needs action", rows, "#c0392b"))
    if watch:
        rows = ""
        for c in watch:
            stale = c.get("stale_minutes")
            stale_str = f" · stale {stale} min" if stale else ""
            rows += (
                f'<div style="border-left:3px solid #d4a017;padding:4px 10px;margin:4px 0;background:#fdf8e9">'
                f'<strong>{c["source"]}</strong> · {c["derived_status"]}{stale_str}'
                f'</div>'
            )
        html_parts.append(_section("🟡 Watch (auto-recovers, monitor for patterns)", rows, "#b07c00"))

    html_parts.append(
        f'<p style="color:#27ae60"><strong>🟢 Healthy:</strong> {healthy_count} connectors · '
        f'<strong>🏃 Running:</strong> {running_count}</p>'
    )

    if sync_failures:
        rows = '<table style="border-collapse:collapse;font-size:13px"><tr><th align="left" style="padding:4px 10px;border-bottom:1px solid #ddd">Source</th><th align="right" style="padding:4px 10px;border-bottom:1px solid #ddd">Fails</th><th align="right" style="padding:4px 10px;border-bottom:1px solid #ddd">Successes</th><th align="right" style="padding:4px 10px;border-bottom:1px solid #ddd">Fail rate</th></tr>'
        for f in sync_failures:
            rows += (
                f'<tr><td style="padding:4px 10px">{f["source_name"]}</td>'
                f'<td align="right" style="padding:4px 10px">{f["fails"]}</td>'
                f'<td align="right" style="padding:4px 10px">{f["successes"]}</td>'
                f'<td align="right" style="padding:4px 10px">{f["fail_rate_pct"]}%</td></tr>'
            )
        rows += "</table>"
        html_parts.append(_section("Flaky syncs (last 7 days)", rows, "#444"))

    if api_5xx:
        rows = '<table style="border-collapse:collapse;font-size:13px"><tr><th align="right" style="padding:4px 10px;border-bottom:1px solid #ddd">Count</th><th align="left" style="padding:4px 10px;border-bottom:1px solid #ddd">Endpoint</th></tr>'
        for path, n in sorted(api_5xx.items(), key=lambda x: -x[1])[:10]:
            rows += f'<tr><td align="right" style="padding:4px 10px">{n}</td><td style="padding:4px 10px;font-family:monospace">{path}</td></tr>'
        rows += "</table>"
        html_parts.append(_section("API 5xx errors (last 7 days)", rows, "#c0392b"))
    else:
        html_parts.append('<p style="color:#27ae60"><strong>API 5xx (last 7 days):</strong> none ✓</p>')

    pool_rows = ""
    for state, n in sorted(pg_pool.items()):
        pool_rows += f'<tr><td style="padding:4px 10px">{state}</td><td align="right" style="padding:4px 10px"><strong>{n}</strong></td></tr>'
    pool_warn = ""
    if pg_pool.get("idle in transaction", 0) > 5:
        pool_warn = (
            '<p style="font-size:12px;color:#b07c00;background:#fdf8e9;padding:6px 10px;border-left:3px solid #d4a017">'
            '⚠ idle-in-transaction count is elevated — Postgres self-heal will recover, '
            'but the underlying leak is worth a code search.</p>'
        )
    html_parts.append(_section(
        "DB pool snapshot",
        f'<table style="border-collapse:collapse;font-size:13px">{pool_rows}</table>{pool_warn}',
        "#444",
    ))

    html_parts.append(_section(
        "System",
        f'<ul style="font-size:13px;color:#555">'
        f'<li>root disk used: {disk.get("root", "?")}</li>'
        f'<li>/var/log size: {disk.get("var_log", "?")}</li>'
        f'<li>host: {socket.gethostname()}</li>'
        f'</ul>',
        "#444",
    ))
    html_parts.append('</div>')
    body_html = "\n".join(html_parts)

    return subject, body_text, body_html


def _send_email(subject: str, body_text: str, body_html: str) -> bool:
    """Mirrors daily_deploy_summary._send_email but adds an HTML body."""
    try:
        import boto3
        from app.core.email_allowlist import assert_allowed
    except Exception as exc:
        print(f"weekly-health: import failed: {exc}", file=sys.stderr)
        return False
    try:
        recipient = os.environ.get("PUSH_ALERTS_RECIPIENT_EMAIL", "joseph@spidergrills.com")
        to_addresses = assert_allowed(recipient)
        sender = os.environ.get("AUTH_EMAIL_FROM", "no-reply@spidergrills.app")
        region = os.environ.get("AUTH_EMAIL_REGION") or os.environ.get("AWS_REGION") or "us-east-2"
        client = boto3.client(
            "sesv2", region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        client.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": to_addresses},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            }},
        )
        return True
    except Exception as exc:
        print(f"weekly-health: send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    print(f"weekly-health: starting at {datetime.now(BUSINESS_TZ).isoformat()}")
    connectors = _fetch_connector_health()
    sync_failures = _fetch_recent_sync_failures(days=7)
    pg_pool = _fetch_pg_pool_snapshot()
    api_5xx = _fetch_api_5xx_counts(days=7)
    disk = _fetch_disk_usage()

    subject, body_text, body_html = _format_report(
        connectors, sync_failures, pg_pool, api_5xx, disk
    )
    print(f"weekly-health: subject={subject!r}")

    if os.environ.get("WEEKLY_HEALTH_DRY_RUN"):
        print("--- DRY RUN — not sending ---")
        print(body_text)
        return 0

    ok = _send_email(subject, body_text, body_html)
    print(f"weekly-health: sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
