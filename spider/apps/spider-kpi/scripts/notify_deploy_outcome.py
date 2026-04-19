#!/usr/bin/env python3
"""Deploy-outcome notifier.

Invoked at the end of every backend deploy path (cron auto-pull + the two
GitHub Actions workflows) to tell Joseph what happened — green, rolled
back, or outright failed — via SES email + Slack DM. Respects the KPI
recipient allowlist so the same guardrail that protects KPI digests also
gates ops notifications.

Usage:
    notify_deploy_outcome.py \\
        --outcome success|rolled_back|failure \\
        --old-sha <sha> --new-sha <sha> \\
        --source auto-pull|gha-auto-promote|gha-deploy-backend \\
        [--run-url <url>] [--error <one-line message>]

Exit 0 on any send attempt that succeeded (email OR slack). Exit 1 only
when both channels failed — so deploy scripts can tolerate notification
flakiness without failing the overall deploy.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


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

BUSINESS_TZ = ZoneInfo("America/New_York")
BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


OUTCOME_SUBJECTS = {
    "success": "[KPI deploy OK]",
    "rolled_back": "[KPI deploy ROLLED BACK]",
    "failure": "[KPI deploy FAILED — service may be degraded]",
}

OUTCOME_SLACK_PREFIX = {
    "success": ":white_check_mark: *KPI deploy OK*",
    "rolled_back": ":warning: *KPI deploy rolled back*",
    "failure": ":rotating_light: *KPI deploy FAILED*",
}


def _git_subject(sha: str) -> str:
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--pretty=%s", sha],
            capture_output=True, text=True, timeout=5, check=False,
            cwd="/opt/spiderclawkpi/spider",
        )
        return (r.stdout or "").strip()[:180]
    except Exception:
        return ""


def _build_bodies(args: argparse.Namespace) -> tuple[str, str, str]:
    now = datetime.now(BUSINESS_TZ)
    host = socket.gethostname()
    commit_subject = _git_subject(args.new_sha) or "(unknown — git log failed)"
    outcome = args.outcome

    subject = (
        f"{OUTCOME_SUBJECTS.get(outcome, '[KPI deploy ?]')} "
        f"{args.new_sha[:8]} · {args.source} · {now.strftime('%b %d %H:%M ET')}"
    )[:180]

    lines = [
        f"Outcome   : {outcome}",
        f"Host      : {host}",
        f"Source    : {args.source}",
        f"Old SHA   : {args.old_sha[:8]} → {args.new_sha[:8]}",
        f"Message   : {commit_subject}",
    ]
    if args.run_url:
        lines.append(f"Run       : {args.run_url}")
    if args.error:
        lines.append(f"Error     : {args.error}")
    if outcome == "rolled_back":
        lines.append("")
        lines.append(
            "NOTE: application code reverted to the previous SHA. Database "
            "migrations applied during the failed deploy were NOT reverted "
            "— assumption is they are forward-compatible. Inspect before "
            "re-deploying."
        )
    if outcome == "failure":
        lines.append("")
        lines.append(
            "NOTE: deploy failed AND rollback failed. Service may be in a "
            "broken state. Check systemctl status spider-kpi.service + "
            "journalctl and consider manual intervention."
        )
    body_text = "\n".join(lines)

    slack_lines = [
        f"{OUTCOME_SLACK_PREFIX.get(outcome, '*KPI deploy?*')}",
        f"`{args.old_sha[:8]}` → `{args.new_sha[:8]}` · {args.source} · {host}",
        f"> {commit_subject}",
    ]
    if args.run_url:
        slack_lines.append(f"<{args.run_url}|View run>")
    if args.error:
        slack_lines.append(f"_error:_ `{args.error[:200]}`")
    slack_text = "\n".join(slack_lines)

    return subject, body_text, slack_text


def _send_email(subject: str, body_text: str) -> bool:
    try:
        import boto3
        from app.core.email_allowlist import assert_allowed
    except Exception as exc:
        print(f"notify: email import failed: {exc}", file=sys.stderr)
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
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            }},
        )
        return True
    except Exception as exc:
        print(f"notify: email send failed: {exc}", file=sys.stderr)
        return False


def _send_slack(slack_text: str, subject_id: str) -> bool:
    try:
        from app.db.session import SessionLocal
        from app.services.push_alerts import send_slack_dm_to_email
    except Exception as exc:
        print(f"notify: slack import failed: {exc}", file=sys.stderr)
        return False
    try:
        recipient = os.environ.get("PUSH_ALERTS_RECIPIENT_EMAIL", "joseph@spidergrills.com")
        db = SessionLocal()
        try:
            return bool(send_slack_dm_to_email(
                db,
                recipient_email=recipient,
                subject_type="deploy_outcome",
                subject_id=subject_id,
                text=slack_text,
                bypass_quiet_hours=True,
                bypass_rate_limit=True,
            ))
        finally:
            db.close()
    except Exception as exc:
        print(f"notify: slack send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--outcome", required=True, choices=["success", "rolled_back", "failure"])
    p.add_argument("--old-sha", required=True)
    p.add_argument("--new-sha", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--run-url", default="")
    p.add_argument("--error", default="")
    args = p.parse_args()

    subject, body_text, slack_text = _build_bodies(args)
    subject_id = f"deploy:{args.source}:{args.new_sha[:12]}:{args.outcome}"

    email_ok = _send_email(subject, body_text)
    slack_ok = _send_slack(slack_text, subject_id)

    if email_ok or slack_ok:
        print(f"notify: email={email_ok} slack={slack_ok}")
        return 0
    print("notify: both channels failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
