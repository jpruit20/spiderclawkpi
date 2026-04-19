#!/usr/bin/env python3
"""Weekly AI activity report — runs Friday 3pm ET via cron.

Queries git log for AI-authored commits and journalctl for escalation
events from the past 7 days, then sends a formatted HTML digest to
joseph@spidergrills.com via SES.

No persistent storage — all data comes from git history and systemd
journal, both of which naturally retain well beyond 7 days.

Install:
    # crontab -e
    0 15 * * 5 /opt/spiderclawkpi/spider/apps/spider-kpi/.venv/bin/python /opt/spiderclawkpi/spider/apps/spider-kpi/scripts/weekly_ai_report.py >> /var/log/spider-kpi-weekly-report.log 2>&1
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ── .env loading ──
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)

_load_dotenv(ENV_PATH)

import boto3
from botocore.exceptions import BotoCoreError, ClientError

BUSINESS_TZ = ZoneInfo("America/New_York")
REPO_DIR = "/opt/spiderclawkpi/spider"
SERVICE_NAME = "spider-kpi.service"
RECIPIENT = "joseph@spidergrills.com"
SENDER = os.environ.get("AUTH_EMAIL_FROM", "no-reply@spidergrills.app")
AWS_REGION = os.environ.get("AUTH_EMAIL_REGION") or os.environ.get("AWS_REGION") or "us-east-2"

# Allowlist enforcement — hard-fails if RECIPIENT is ever edited to an
# address not approved in backend/app/core/email_allowlist.py.
_backend = Path(__file__).resolve().parents[1] / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))
from app.core.email_allowlist import assert_allowed  # noqa: E402


def _run(cmd: list[str], cwd: str = REPO_DIR) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def _get_ai_commits(since_days: int = 7) -> list[dict]:
    """Parse git log for AI-authored commits in the last N days."""
    since = (datetime.now(BUSINESS_TZ) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    raw = _run([
        "git", "log", f"--since={since}", "--grep=AI edit:",
        "--format=%H|%ai|%s", "--no-merges",
    ])
    if not raw:
        return []
    commits = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        sha, timestamp, message = parts
        # Extract email from commit message: "AI edit: ... (by user@example.com)"
        email_match = re.search(r'\(by\s+(\S+@\S+)\)', message)
        email = email_match.group(1) if email_match else "unknown"
        commits.append({
            "sha": sha[:8],
            "timestamp": timestamp.strip(),
            "message": message.strip(),
            "email": email,
        })
    return commits


def _get_slack_digest(since_days: int = 7) -> list[dict]:
    """Per-channel activity summary from the Slack archive — top N most-active
    channels with headline metrics and the most-reacted-to message of the week.

    DB access is lazy so this module still imports cleanly even when Slack
    isn't configured or the backend venv isn't primed for alembic use.
    """
    try:
        # Path in so the script can import the backend package.
        backend = Path(__file__).resolve().parents[1] / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.db.session import SessionLocal
        from app.models import SlackActivityDaily, SlackMessage, SlackUser
        from sqlalchemy import desc, select, func
    except Exception:
        return []

    digest: list[dict] = []
    cutoff_date = (datetime.now(BUSINESS_TZ) - timedelta(days=since_days)).date()
    cutoff_dt = datetime.now(BUSINESS_TZ) - timedelta(days=since_days)

    db = SessionLocal()
    try:
        # Aggregate per channel over the window
        rows = db.execute(
            select(
                SlackActivityDaily.channel_id,
                SlackActivityDaily.channel_name,
                func.sum(SlackActivityDaily.message_count).label("messages"),
                func.sum(SlackActivityDaily.unique_users).label("users"),
                func.sum(SlackActivityDaily.reaction_count).label("reactions"),
                func.sum(SlackActivityDaily.file_count).label("files"),
            )
            .where(SlackActivityDaily.business_date >= cutoff_date)
            .group_by(SlackActivityDaily.channel_id, SlackActivityDaily.channel_name)
            .order_by(desc(func.sum(SlackActivityDaily.message_count)))
            .limit(8)
        ).all()

        for r in rows:
            # Most-reacted message in this channel this week
            top_msg = db.execute(
                select(SlackMessage)
                .where(
                    SlackMessage.channel_id == r.channel_id,
                    SlackMessage.ts_dt >= cutoff_dt,
                    SlackMessage.is_deleted == False,  # noqa: E712
                )
                .order_by(desc(SlackMessage.reaction_count))
                .limit(1)
            ).scalars().first()
            top_user_name = None
            if top_msg and top_msg.user_id:
                u = db.execute(select(SlackUser).where(SlackUser.user_id == top_msg.user_id)).scalars().first()
                if u:
                    top_user_name = u.display_name or u.real_name or u.name
            digest.append({
                "channel_id": r.channel_id,
                "channel_name": r.channel_name,
                "messages": int(r.messages or 0),
                "users": int(r.users or 0),
                "reactions": int(r.reactions or 0),
                "files": int(r.files or 0),
                "top_message": {
                    "user": top_user_name,
                    "text": (top_msg.text or "")[:200] if top_msg else None,
                    "reactions": int(top_msg.reaction_count) if top_msg else 0,
                } if top_msg else None,
            })
        return digest
    except Exception:
        return []
    finally:
        db.close()


def _get_clickup_digest(since_days: int = 7) -> list[dict]:
    """Per-space throughput digest from ClickUp: tasks closed this week, top
    closers, cycle time, and a headline completed task.
    """
    try:
        backend = Path(__file__).resolve().parents[1] / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.db.session import SessionLocal
        from app.models import ClickUpTask, ClickUpTasksDaily
        from sqlalchemy import desc, select, func
    except Exception:
        return []

    digest: list[dict] = []
    cutoff_date = (datetime.now(BUSINESS_TZ) - timedelta(days=since_days)).date()
    cutoff_dt = datetime.now(BUSINESS_TZ) - timedelta(days=since_days)

    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                ClickUpTasksDaily.space_id,
                ClickUpTasksDaily.space_name,
                func.sum(ClickUpTasksDaily.tasks_created).label("created"),
                func.sum(ClickUpTasksDaily.tasks_completed).label("completed"),
            )
            .where(ClickUpTasksDaily.business_date >= cutoff_date)
            .group_by(ClickUpTasksDaily.space_id, ClickUpTasksDaily.space_name)
            .order_by(desc(func.sum(ClickUpTasksDaily.tasks_completed)))
        ).all()

        for r in rows:
            if not r.space_id:
                continue
            # Cycle-time sample + top closers from the raw tasks table
            tasks_window = db.execute(
                select(ClickUpTask)
                .where(
                    ClickUpTask.space_id == r.space_id,
                    ClickUpTask.date_done.isnot(None),
                    ClickUpTask.date_done >= cutoff_dt,
                    ClickUpTask.date_created.isnot(None),
                )
            ).scalars().all()

            durations = []
            closer_counts: dict[str, int] = {}
            for t in tasks_window:
                try:
                    d = (t.date_done - t.date_created).total_seconds()
                    if d > 0:
                        durations.append(d)
                except Exception:
                    pass
                for a in (t.assignees_json or []):
                    n = (a or {}).get("username") or (a or {}).get("email")
                    if n:
                        closer_counts[n] = closer_counts.get(n, 0) + 1

            median_days = None
            if durations:
                s = sorted(durations)
                median_days = s[len(s) // 2] / 86400.0

            top_closers = sorted(closer_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]

            headline_task = None
            if tasks_window:
                headline = max(tasks_window, key=lambda t: (t.priority == "urgent", t.priority == "high"))
                headline_task = {
                    "name": headline.name,
                    "url": headline.url,
                    "priority": headline.priority,
                    "list": headline.list_name,
                }

            digest.append({
                "space_id": r.space_id,
                "space_name": r.space_name,
                "created": int(r.created or 0),
                "completed": int(r.completed or 0),
                "cycle_time_median_days": round(median_days, 1) if median_days is not None else None,
                "top_closers": [{"user": u, "count": c} for u, c in top_closers],
                "headline_task": headline_task,
            })

        return digest
    except Exception:
        return []
    finally:
        db.close()


def _get_clickup_compliance(since_days: int = 7) -> dict:
    """Compliance grade for ClickUp tasks closed in the last N days against
    the required-field taxonomy (Division / Customer Impact / Category).

    Returns an empty ``{}`` when the taxonomy isn't configured yet so the
    email section hides cleanly.
    """
    try:
        backend = Path(__file__).resolve().parents[1] / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.db.session import SessionLocal
        from app.api.routes.clickup import clickup_compliance
    except Exception:
        return {}

    db = SessionLocal()
    try:
        resp = clickup_compliance(days=since_days, space_id=None, db=db)
        if not resp.get("taxonomy_configured"):
            return {"taxonomy_configured": False, "field_presence": resp.get("taxonomy_field_presence") or {}}
        closed = resp.get("closed_in_window") or {}
        # Compact payload for the email — headline stats + top offenders + top compliers
        return {
            "taxonomy_configured": True,
            "total": closed.get("total", 0),
            "compliant": closed.get("compliant", 0),
            "rate": closed.get("rate"),
            "wow_delta_rate": resp.get("wow_delta_rate"),
            "open_rate": (resp.get("open_now") or {}).get("rate"),
            "by_missing_field": closed.get("by_missing_field") or {},
            "top_compliers": [r for r in (closed.get("by_assignee") or []) if (r.get("rate") or 0) >= 0.9][:5],
            "top_offenders": sorted(
                [r for r in (closed.get("by_assignee") or []) if r.get("total", 0) > 0 and (r.get("rate") or 0) < 0.9],
                key=lambda r: r.get("rate") or 0,
            )[:5],
            "non_compliant": (closed.get("non_compliant") or [])[:5],
        }
    except Exception:
        return {}
    finally:
        db.close()


def _get_escalations(since_days: int = 7) -> list[dict]:
    """Parse journalctl for escalation email events in the last N days."""
    since = (datetime.now(BUSINESS_TZ) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    try:
        raw = _run([
            "journalctl", "-u", SERVICE_NAME, f"--since={since}",
            "--no-pager", "-o", "short-iso",
        ])
    except Exception:
        return []
    escalations = []
    for line in raw.splitlines():
        if "Escalation email sent" not in line:
            continue
        # Extract: "Escalation email sent to X for request from Y"
        match = re.search(
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*'
            r'Escalation email sent to (\S+) for request from (\S+)',
            line,
        )
        if match:
            escalations.append({
                "timestamp": match.group(1),
                "to": match.group(2),
                "from": match.group(3),
            })
    return escalations


def _build_report(
    commits: list[dict],
    escalations: list[dict],
    slack_digest: list[dict] | None = None,
    clickup_digest: list[dict] | None = None,
    clickup_compliance: dict | None = None,
) -> tuple[str, str]:
    """Build plain-text and HTML versions of the weekly report."""
    slack_digest = slack_digest or []
    clickup_digest = clickup_digest or []
    clickup_compliance = clickup_compliance or {}
    now = datetime.now(BUSINESS_TZ)
    week_start = (now - timedelta(days=7)).strftime("%b %d")
    week_end = now.strftime("%b %d, %Y")

    # Group commits by person
    by_person: dict[str, list[dict]] = defaultdict(list)
    for c in commits:
        by_person[c["email"]].append(c)

    # ── Plain text ──
    text_parts = [
        f"Spider Grills KPI Dashboard — Weekly AI Activity Report",
        f"{week_start} – {week_end}",
        f"{'=' * 50}\n",
    ]

    if not commits and not escalations and not slack_digest and not clickup_digest:
        text_parts.append("Quiet week — no AI edits, escalations, Slack, or ClickUp activity.\n")
    else:
        text_parts.append(f"DASHBOARD CHANGES ({len(commits)} total)\n")
        if commits:
            for email, person_commits in sorted(by_person.items()):
                text_parts.append(f"  {email} ({len(person_commits)} edit{'s' if len(person_commits) != 1 else ''}):")
                for c in person_commits:
                    text_parts.append(f"    [{c['sha']}] {c['message']}")
                text_parts.append("")
        else:
            text_parts.append("  None this week.\n")

        text_parts.append(f"ESCALATION REQUESTS ({len(escalations)} total)\n")
        if escalations:
            for e in escalations:
                text_parts.append(f"  {e['timestamp']}  from {e['from']}")
        else:
            text_parts.append("  None this week.")

        if slack_digest:
            total_msgs = sum(d["messages"] for d in slack_digest)
            text_parts.append(f"\nSLACK ACTIVITY ({total_msgs} messages across {len(slack_digest)} channels)\n")
            for d in slack_digest:
                ch = d["channel_name"] or d["channel_id"]
                text_parts.append(
                    f"  #{ch}: {d['messages']} msgs · {d['users']} users · "
                    f"{d['reactions']} reactions · {d['files']} files"
                )
                if d.get("top_message") and d["top_message"].get("text"):
                    tm = d["top_message"]
                    text_parts.append(
                        f"    ★ Top (reactions={tm['reactions']}) {tm['user'] or '?'}: "
                        f"{tm['text'][:140].strip()}"
                    )

        if clickup_compliance:
            if not clickup_compliance.get("taxonomy_configured"):
                missing_fields = [k for k, v in (clickup_compliance.get("field_presence") or {}).items() if not v]
                if missing_fields:
                    text_parts.append("\nCLICKUP TAGGING COMPLIANCE\n")
                    text_parts.append(f"  Taxonomy not yet detected in any task. Missing fields: {', '.join(missing_fields)}")
                    text_parts.append("  Setup runbook: deploy/CLICKUP_TAGGING_SETUP.md")
            else:
                rate = clickup_compliance.get("rate")
                wow = clickup_compliance.get("wow_delta_rate")
                rate_pct = f"{rate * 100:.0f}%" if rate is not None else "—"
                wow_pct = ""
                if wow is not None:
                    wow_pct = f" ({'+' if wow >= 0 else ''}{wow * 100:.0f}pp vs prior)"
                text_parts.append(
                    f"\nCLICKUP TAGGING COMPLIANCE  {rate_pct}{wow_pct}  "
                    f"({clickup_compliance.get('compliant', 0)}/{clickup_compliance.get('total', 0)} closed tasks tagged)"
                )
                missed = clickup_compliance.get("by_missing_field") or {}
                top_missed = [(k, v) for k, v in missed.items() if v > 0]
                if top_missed:
                    text_parts.append(
                        "  Most-missed: " +
                        ", ".join(f"{k} ({v})" for k, v in sorted(top_missed, key=lambda kv: -kv[1])[:3])
                    )
                if clickup_compliance.get("top_offenders"):
                    text_parts.append("  Offenders:")
                    for o in clickup_compliance["top_offenders"]:
                        r = o.get("rate") or 0
                        text_parts.append(f"    {o.get('user', '?')}: {r * 100:.0f}% ({o.get('compliant', 0)}/{o.get('total', 0)})")
                if clickup_compliance.get("top_compliers"):
                    text_parts.append("  100% club: " + ", ".join(c.get("user", "?") for c in clickup_compliance["top_compliers"]))

        if clickup_digest:
            total_closed = sum(d["completed"] for d in clickup_digest)
            text_parts.append(f"\nCLICKUP THROUGHPUT ({total_closed} closed across {len(clickup_digest)} spaces)\n")
            for d in clickup_digest:
                name = d["space_name"] or d["space_id"]
                cycle = f" · median cycle {d['cycle_time_median_days']}d" if d.get("cycle_time_median_days") is not None else ""
                text_parts.append(
                    f"  {name}: {d['completed']} closed · {d['created']} opened{cycle}"
                )
                if d.get("top_closers"):
                    closers = ", ".join(f"{c['user']} ({c['count']})" for c in d["top_closers"])
                    text_parts.append(f"    Top closers: {closers}")
                ht = d.get("headline_task")
                if ht and ht.get("name"):
                    priority = f" [{ht['priority']}]" if ht.get("priority") else ""
                    text_parts.append(f"    ★ {ht['name'][:140]}{priority}  {ht.get('url') or ''}")

    body_text = "\n".join(text_parts)

    # ── HTML ──
    html_parts = [
        '<html><body style="font-family:Arial,sans-serif;color:#111827;line-height:1.6;max-width:600px;margin:0 auto;padding:24px">',
        '<div style="text-align:center;margin-bottom:24px">',
        '<h2 style="margin:0;color:#111827">Weekly AI Activity Report</h2>',
        f'<p style="color:#6b7280;margin:4px 0 0">{week_start} – {week_end}</p>',
        '</div>',
    ]

    if not commits and not escalations:
        html_parts.append('<p style="text-align:center;color:#6b7280">Quiet week — no AI edits or escalation requests.</p>')
    else:
        # Changes section
        html_parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #4a7aff;padding-bottom:6px">Dashboard Changes ({len(commits)})</h3>')
        if commits:
            for email, person_commits in sorted(by_person.items()):
                name = email.split("@")[0].title()
                html_parts.append(
                    f'<div style="margin-bottom:16px">'
                    f'<strong style="color:#374151">{name}</strong> '
                    f'<span style="color:#6b7280;font-size:13px">({email}) — {len(person_commits)} edit{"s" if len(person_commits) != 1 else ""}</span>'
                    f'<ul style="margin:4px 0;padding-left:20px">'
                )
                for c in person_commits:
                    clean_msg = c["message"].replace(f"(by {email})", "").strip()
                    html_parts.append(
                        f'<li style="font-size:13px;color:#374151;margin:2px 0">'
                        f'<code style="background:#f3f4f6;padding:1px 4px;border-radius:3px;font-size:12px">{c["sha"]}</code> '
                        f'{_escape(clean_msg)}'
                        f'</li>'
                    )
                html_parts.append('</ul></div>')
        else:
            html_parts.append('<p style="color:#6b7280">None this week.</p>')

        # Escalations section
        html_parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #f59e0b;padding-bottom:6px">Backend Requests Escalated to You ({len(escalations)})</h3>')
        if escalations:
            for e in escalations:
                name = e["from"].split("@")[0].title()
                html_parts.append(
                    f'<div style="background:#fff7ed;border-left:3px solid #f59e0b;padding:8px 12px;margin:6px 0;border-radius:4px;font-size:13px">'
                    f'<strong>{name}</strong> ({e["from"]}) — {e["timestamp"]}'
                    f'</div>'
                )
        else:
            html_parts.append('<p style="color:#6b7280">None this week.</p>')

        # ClickUp tagging compliance
        if clickup_compliance:
            if not clickup_compliance.get("taxonomy_configured"):
                missing_fields = [k for k, v in (clickup_compliance.get("field_presence") or {}).items() if not v]
                if missing_fields:
                    html_parts.append(
                        '<h3 style="color:#111827;border-bottom:2px solid #b91c1c;padding-bottom:6px">'
                        'ClickUp Tagging Compliance</h3>'
                    )
                    html_parts.append(
                        f'<div style="padding:10px 12px;background:#fef2f2;border-left:3px solid #b91c1c;border-radius:4px;font-size:13px">'
                        f'Taxonomy not yet detected. Missing fields: <strong>{_escape(", ".join(missing_fields))}</strong>.'
                        f' See <code>deploy/CLICKUP_TAGGING_SETUP.md</code> for setup steps.'
                        f'</div>'
                    )
            else:
                rate = clickup_compliance.get("rate")
                wow = clickup_compliance.get("wow_delta_rate")
                rate_pct = f"{rate * 100:.0f}%" if rate is not None else "—"
                rate_color = "#16a34a" if (rate or 0) >= 0.9 else ("#f59e0b" if (rate or 0) >= 0.7 else "#b91c1c")
                wow_badge = ""
                if wow is not None:
                    color = "#16a34a" if wow >= 0 else "#b91c1c"
                    wow_badge = f'<span style="color:{color};font-size:12px;margin-left:8px">{"+" if wow >= 0 else ""}{wow * 100:.0f}pp vs prior</span>'
                html_parts.append(
                    f'<h3 style="color:#111827;border-bottom:2px solid {rate_color};padding-bottom:6px">'
                    f'ClickUp Tagging Compliance <span style="color:{rate_color}">{rate_pct}</span>'
                    f'{wow_badge}</h3>'
                )
                html_parts.append(
                    f'<p style="font-size:12px;color:#6b7280;margin:2px 0 10px">'
                    f'{clickup_compliance.get("compliant", 0)}/{clickup_compliance.get("total", 0)} tasks closed this week with required taxonomy.'
                    f'</p>'
                )
                missed = [(k, v) for k, v in (clickup_compliance.get("by_missing_field") or {}).items() if v > 0]
                if missed:
                    missed_html = ", ".join(f'<strong>{_escape(k)}</strong> ({v})' for k, v in sorted(missed, key=lambda kv: -kv[1])[:3])
                    html_parts.append(f'<div style="font-size:12px;color:#4b5563;margin-bottom:6px">Most-missed: {missed_html}</div>')
                if clickup_compliance.get("top_offenders"):
                    html_parts.append('<div style="font-size:12px;color:#4b5563;margin-bottom:4px">Offenders:</div>')
                    html_parts.append('<ul style="margin:0 0 8px;padding-left:18px;font-size:12px;color:#374151">')
                    for o in clickup_compliance["top_offenders"]:
                        r = o.get("rate") or 0
                        html_parts.append(
                            f'<li>{_escape(o.get("user", "?"))}: <strong>{r * 100:.0f}%</strong> '
                            f'({o.get("compliant", 0)}/{o.get("total", 0)})</li>'
                        )
                    html_parts.append('</ul>')
                if clickup_compliance.get("top_compliers"):
                    compliers = ", ".join(f'<strong>{_escape(c.get("user", "?"))}</strong>' for c in clickup_compliance["top_compliers"])
                    html_parts.append(f'<div style="font-size:12px;color:#16a34a;margin-bottom:8px">100% club: {compliers}</div>')

        # ClickUp throughput section
        if clickup_digest:
            total_closed = sum(d["completed"] for d in clickup_digest)
            html_parts.append(
                f'<h3 style="color:#111827;border-bottom:2px solid #7b68ee;padding-bottom:6px">'
                f'ClickUp Throughput ({total_closed} closed · {len(clickup_digest)} spaces)</h3>'
            )
            for d in clickup_digest:
                name = d["space_name"] or d["space_id"] or "(unnamed)"
                cycle_bit = ""
                if d.get("cycle_time_median_days") is not None:
                    cycle_bit = f" · median cycle {d['cycle_time_median_days']}d"
                html_parts.append(
                    f'<div style="margin:10px 0;padding:8px 12px;background:#f7f5ff;border-left:3px solid #7b68ee;border-radius:4px">'
                    f'<strong style="color:#374151">{_escape(name)}</strong>'
                    f' <span style="color:#6b7280;font-size:12px">'
                    f'{d["completed"]} closed · {d["created"]} opened{cycle_bit}'
                    f'</span>'
                )
                if d.get("top_closers"):
                    closers_str = ", ".join(f'<strong>{_escape(c["user"])}</strong> ({c["count"]})' for c in d["top_closers"])
                    html_parts.append(
                        f'<div style="margin-top:4px;font-size:12px;color:#4b5563">Top closers: {closers_str}</div>'
                    )
                ht = d.get("headline_task")
                if ht and ht.get("name"):
                    priority = f' <span style="color:#b91c1c;font-weight:600">[{_escape(ht["priority"])}]</span>' if ht.get("priority") else ""
                    url = ht.get("url")
                    link = f'<a href="{_escape(url)}" style="color:#4338ca" target="_blank">{_escape(ht["name"][:140])}</a>' if url else _escape(ht["name"][:140])
                    html_parts.append(
                        f'<div style="margin-top:6px;padding:6px 8px;background:#fff;border-radius:3px;font-size:12px;color:#374151">'
                        f'<span style="color:#6b7280">★ Notable:</span> {link}{priority}'
                        f'</div>'
                    )
                html_parts.append('</div>')

        # Slack activity section
        if slack_digest:
            total_msgs = sum(d["messages"] for d in slack_digest)
            html_parts.append(
                f'<h3 style="color:#111827;border-bottom:2px solid #4a154b;padding-bottom:6px">'
                f'Slack Activity ({total_msgs} msgs · {len(slack_digest)} channels)</h3>'
            )
            for d in slack_digest:
                ch = d["channel_name"] or d["channel_id"]
                html_parts.append(
                    f'<div style="margin:10px 0;padding:8px 12px;background:#faf7fb;border-left:3px solid #4a154b;border-radius:4px">'
                    f'<strong style="color:#374151">#{_escape(ch)}</strong>'
                    f' <span style="color:#6b7280;font-size:12px">'
                    f'{d["messages"]} msgs · {d["users"]} users · {d["reactions"]} reactions · {d["files"]} files'
                    f'</span>'
                )
                tm = d.get("top_message") or {}
                if tm.get("text"):
                    html_parts.append(
                        f'<div style="margin-top:6px;padding:6px 8px;background:#fff;border-radius:3px;font-size:12px;color:#374151">'
                        f'<span style="color:#6b7280">★ Top (reactions={tm.get("reactions", 0)})</span> '
                        f'<strong>{_escape(tm.get("user") or "?")}</strong>: {_escape(tm["text"][:200])}'
                        f'</div>'
                    )
                html_parts.append('</div>')

    html_parts.append(
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">'
        '<p style="color:#9ca3af;font-size:11px;text-align:center">Auto-generated weekly report from the KPI dashboard AI system.</p>'
        '</body></html>'
    )
    body_html = "\n".join(html_parts)

    return body_text, body_html


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_report() -> None:
    commits = _get_ai_commits(since_days=7)
    escalations = _get_escalations(since_days=7)
    slack_digest = _get_slack_digest(since_days=7)
    clickup_digest = _get_clickup_digest(since_days=7)
    clickup_compliance = _get_clickup_compliance(since_days=7)
    body_text, body_html = _build_report(commits, escalations, slack_digest, clickup_digest, clickup_compliance)

    now = datetime.now(BUSINESS_TZ)
    week_end = now.strftime("%b %d")
    subject = f"KPI Dashboard AI Weekly — {week_end} ({len(commits)} edits, {len(escalations)} escalations)"

    to_addresses = assert_allowed(RECIPIENT)

    client = boto3.client(
        "sesv2",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    try:
        client.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": to_addresses},
            Content={
                "Simple": {
                    "Subject": {"Data": subject},
                    "Body": {
                        "Text": {"Data": body_text},
                        "Html": {"Data": body_html},
                    },
                }
            },
        )
        print(f"[{now.isoformat()}] Weekly report sent: {len(commits)} commits, {len(escalations)} escalations")
    except (ClientError, BotoCoreError) as exc:
        print(f"[{now.isoformat()}] Failed to send weekly report: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    send_report()
