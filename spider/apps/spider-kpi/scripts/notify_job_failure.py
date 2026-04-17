#!/usr/bin/env python3
"""Send a Slack DM (and fallback email) when a systemd unit fails.

Invoked by ``spider-kpi-job-failure@<unit>.service`` via ``OnFailure=``
on each of our scheduled jobs (daily insights, morning email, monthly
telemetry report, etc.). Reads the last ~40 log lines from journalctl
for the failed unit, formats them into a DM, and pushes.

Dedupes at the ``NotificationSend`` layer (subject = unit+timestamp) so
accidental double-fires don't spam.

Usage:
    notify_job_failure.py <systemd-unit-name>

Example:
    notify_job_failure.py spider-kpi-daily-insights.service
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(p: Path) -> None:
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
BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.push_alerts import send_slack_dm_to_email  # noqa: E402


def _journal_tail(unit: str, n: int = 40) -> str:
    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(n), "--no-pager", "--output=short-iso"],
            capture_output=True, text=True, timeout=15,
        )
        return (r.stdout or r.stderr or "").strip()
    except Exception as exc:
        return f"(journalctl failed: {exc})"


def _ses_email_fallback(recipient: str, subject: str, body: str) -> None:
    try:
        import boto3
        region = os.environ.get("AUTH_EMAIL_REGION") or os.environ.get("AWS_REGION") or "us-east-2"
        sender = os.environ.get("AUTH_EMAIL_FROM", "no-reply@spidergrills.app")
        client = boto3.client(
            "sesv2", region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        client.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [recipient]},
            Content={"Simple": {
                "Subject": {"Data": subject[:200], "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body[:20000], "Charset": "UTF-8"}},
            }},
        )
    except Exception as exc:
        print(f"SES fallback failed: {exc}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: notify_job_failure.py <unit-name>")
        return 2
    unit = sys.argv[1]
    settings = get_settings()
    recipient = settings.push_alerts_recipient_email

    host = os.environ.get("HOSTNAME") or subprocess.getoutput("hostname").strip()
    now = datetime.now(timezone.utc)
    tail = _journal_tail(unit)
    # Truncate tail to keep DMs readable
    MAX_TAIL = 1800
    tail_snippet = tail[-MAX_TAIL:] if len(tail) > MAX_TAIL else tail
    if len(tail) > MAX_TAIL:
        tail_snippet = "…\n" + tail_snippet

    subject_id = f"job_failure:{unit}:{now.strftime('%Y%m%d%H%M')}"
    slack_text = (
        f":rotating_light: *Scheduled job failed:* `{unit}`\n"
        f"_{host} · {now.isoformat(timespec='seconds')}_\n\n"
        f"```\n{tail_snippet}\n```"
    )

    db = SessionLocal()
    try:
        sent = send_slack_dm_to_email(
            db,
            recipient_email=recipient,
            subject_type="job_failure",
            subject_id=subject_id,
            text=slack_text,
            bypass_quiet_hours=True,  # failures should wake you up
            bypass_rate_limit=True,
        )
    finally:
        db.close()

    print(f"slack_dm_sent={sent} unit={unit}")

    # Always send email fallback — if Slack DM failed OR succeeded, email
    # is a persistent record we can revisit. Dedupe handled by SES idempotency
    # only loosely; real dedup is the NotificationSend row for slack above.
    if not sent:
        _ses_email_fallback(
            recipient,
            subject=f"[Spider KPI] Job failed: {unit}",
            body=f"Scheduled job failed on {host} at {now.isoformat()}.\n\nUnit: {unit}\n\nLast log lines:\n\n{tail}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
