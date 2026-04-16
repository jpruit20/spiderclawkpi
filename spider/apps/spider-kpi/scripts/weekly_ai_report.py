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


def _build_report(commits: list[dict], escalations: list[dict]) -> tuple[str, str]:
    """Build plain-text and HTML versions of the weekly report."""
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

    if not commits and not escalations:
        text_parts.append("Quiet week — no AI edits or escalation requests.\n")
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
    body_text, body_html = _build_report(commits, escalations)

    now = datetime.now(BUSINESS_TZ)
    week_end = now.strftime("%b %d")
    subject = f"KPI Dashboard AI Weekly — {week_end} ({len(commits)} edits, {len(escalations)} escalations)"

    client = boto3.client(
        "sesv2",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    try:
        client.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
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
