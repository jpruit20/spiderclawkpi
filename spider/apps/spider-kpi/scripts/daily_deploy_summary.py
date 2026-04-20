#!/usr/bin/env python3
"""Daily deploy-summary emailer.

Reads the rolling ledger at /var/log/spider-kpi-deploys.jsonl, collects
entries from the last 24 hours (Eastern business time), and emits a
single summary email. This replaces the per-deploy success emails that
notify_deploy_outcome.py used to send — successes are now quiet and
roll up here. Rolled-back and failed deploys still page immediately
via notify_deploy_outcome.py; this summary repeats them for the record.

Run once a day via a systemd timer (see
spider-kpi-daily-deploy-summary.timer).
"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime, timedelta
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
LEDGER = Path("/var/log/spider-kpi-deploys.jsonl")
BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _load_entries(since: datetime) -> list[dict]:
    if not LEDGER.exists():
        return []
    out: list[dict] = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = datetime.fromisoformat(e.get("ts", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=BUSINESS_TZ)
            if ts >= since:
                out.append({**e, "_ts": ts})
        except Exception:
            continue
    return out


def _build_summary(entries: list[dict], since: datetime, until: datetime) -> tuple[str, str]:
    host = socket.gethostname()
    counts = {"success": 0, "rolled_back": 0, "failure": 0}
    for e in entries:
        counts[e.get("outcome", "")] = counts.get(e.get("outcome", ""), 0) + 1

    window_label = f"{since.strftime('%b %d %H:%M')} → {until.strftime('%b %d %H:%M ET')}"
    subject = (
        f"[KPI daily deploys] {counts['success']} OK"
        + (f" · {counts['rolled_back']} rolled back" if counts['rolled_back'] else '')
        + (f" · {counts['failure']} failed" if counts['failure'] else '')
        + f" · {until.strftime('%b %d')}"
    )[:180]

    lines = [
        f"Daily deploy summary — {window_label}",
        f"Host   : {host}",
        f"Totals : {counts['success']} success · {counts['rolled_back']} rolled back · {counts['failure']} failed",
        "",
    ]

    if not entries:
        lines.append("No deploys in this window.")
    else:
        lines.append(f"{'Time':<16}  {'Outcome':<12}  {'Source':<18}  {'Δ':<20}  Message")
        lines.append("-" * 100)
        for e in sorted(entries, key=lambda x: x["_ts"]):
            t = e["_ts"].strftime('%m-%d %H:%M')
            outcome = e.get("outcome", "?")
            source = (e.get("source") or "?")[:18]
            sha_delta = f"{e.get('old_sha','')[:8]}→{e.get('new_sha','')[:8]}"
            msg = (e.get("subject") or "").strip()[:80]
            lines.append(f"{t:<16}  {outcome:<12}  {source:<18}  {sha_delta:<20}  {msg}")

    failures = [e for e in entries if e.get("outcome") in ("rolled_back", "failure")]
    if failures:
        lines.append("")
        lines.append("Urgent items (rolled back / failed):")
        for e in failures:
            lines.append(f"  • {e['_ts'].strftime('%H:%M')} {e.get('outcome')} {e.get('new_sha','')[:8]}: {(e.get('error') or '').strip()[:200]}")

    return subject, "\n".join(lines)


def _send_email(subject: str, body_text: str) -> bool:
    try:
        import boto3
        from app.core.email_allowlist import assert_allowed
    except Exception as exc:
        print(f"summary: email import failed: {exc}", file=sys.stderr)
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
        print(f"summary: email send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    until = datetime.now(BUSINESS_TZ)
    since = until - timedelta(hours=24)
    entries = _load_entries(since)
    subject, body = _build_summary(entries, since, until)

    if not entries:
        # Still send — confirms the pipeline is alive — but mark empty.
        pass

    ok = _send_email(subject, body)
    print(f"summary: sent={ok} entries={len(entries)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
