#!/usr/bin/env python3
"""Email the latest telemetry report via SES.

Reads the most recent telemetry_reports row of the given type, renders
a clean HTML email from its markdown body + key findings + benchmarks,
and sends via AWS SES. Dedupes on (recipient, report_id).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
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

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import boto3  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.email_allowlist import assert_allowed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import NotificationSend, TelemetryReport  # noqa: E402
from sqlalchemy import select  # noqa: E402


BUSINESS_TZ = ZoneInfo("America/New_York")


def _escape(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_to_html_minimal(md: str) -> str:
    """Very lightweight markdown → HTML. Good enough for the body rendering
    without pulling in a markdown lib. Handles: headings, lists, bold, italic,
    inline code, blockquotes, paragraphs."""
    lines = md.split("\n")
    out: list[str] = []
    in_list = False
    in_table = False
    table_rows: list[str] = []

    def _flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            in_table = False
            return
        out.append('<table style="border-collapse:collapse;margin:12px 0;width:100%;font-size:12px">')
        header = re.split(r"\s*\|\s*", table_rows[0].strip().strip("|"))
        out.append("<thead><tr>" + "".join(f'<th style="border:1px solid #e5e7eb;padding:6px 8px;background:#f8fafc;text-align:left">{_escape(h)}</th>' for h in header) + "</tr></thead>")
        out.append("<tbody>")
        for row in table_rows[2:]:  # skip separator
            cells = re.split(r"\s*\|\s*", row.strip().strip("|"))
            out.append("<tr>" + "".join(f'<td style="border:1px solid #e5e7eb;padding:6px 8px">{_escape(c)}</td>' for c in cells) + "</tr>")
        out.append("</tbody></table>")
        table_rows = []
        in_table = False

    def _close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if re.match(r"^\|.*\|$", line) and "|" in line:
            in_table = True
            table_rows.append(line)
            continue
        if in_table and not line.startswith("|"):
            _flush_table()

        stripped = line.strip()
        if not stripped:
            _close_list()
            out.append("")
            continue

        if line.startswith("# "):
            _close_list()
            out.append(f'<h1 style="color:#111827;margin:22px 0 10px;font-size:22px">{_escape(line[2:])}</h1>')
        elif line.startswith("## "):
            _close_list()
            out.append(f'<h2 style="color:#111827;border-bottom:2px solid #4a7aff;padding-bottom:4px;margin:18px 0 8px;font-size:18px">{_escape(line[3:])}</h2>')
        elif line.startswith("### "):
            _close_list()
            out.append(f'<h3 style="color:#111827;margin:14px 0 6px;font-size:15px">{_escape(line[4:])}</h3>')
        elif line.lstrip().startswith("- "):
            if not in_list:
                out.append('<ul style="margin:6px 0;padding-left:22px;font-size:13px;color:#374151">')
                in_list = True
            item = line.lstrip()[2:]
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _escape(item))
            item = re.sub(r"\*(.+?)\*", r"<em>\1</em>", item)
            item = re.sub(r"`([^`]+)`", r'<code style="background:#f3f4f6;padding:1px 4px;border-radius:3px">\1</code>', item)
            out.append(f"<li>{item}</li>")
        else:
            _close_list()
            rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _escape(line))
            rendered = re.sub(r"\*(.+?)\*", r"<em>\1</em>", rendered)
            rendered = re.sub(r"`([^`]+)`", r'<code style="background:#f3f4f6;padding:1px 4px;border-radius:3px">\1</code>', rendered)
            out.append(f'<p style="margin:8px 0;font-size:13px;color:#374151;line-height:1.55">{rendered}</p>')

    if in_table:
        _flush_table()
    _close_list()
    return "\n".join(out)


def _render_html(report: TelemetryReport) -> str:
    findings_html = ""
    if report.key_findings_json:
        findings_html = '<h2 style="color:#111827;border-bottom:2px solid #b91c1c;padding-bottom:4px;margin-top:20px;font-size:18px">Key findings at a glance</h2>'
        for f in report.key_findings_json:
            urg = (f.get("urgency") or "medium").lower()
            color = "#b91c1c" if urg == "high" else "#f59e0b" if urg == "medium" else "#6b7280"
            cat = f.get("category") or ""
            findings_html += (
                f'<div style="padding:8px 12px;border-left:3px solid {color};background:#fafafa;border-radius:4px;margin:6px 0;font-size:13px">'
                f'<strong style="color:{color};font-size:11px;text-transform:uppercase">{_escape(urg)}</strong>'
                f' <strong style="color:#6b7280;font-size:11px">[{_escape(cat)}]</strong>'
                f' <strong>{_escape(f.get("title"))}</strong>'
                f' <div style="color:#374151;margin-top:4px">{_escape(f.get("detail"))}</div>'
                f'</div>'
            )

    body_html = _md_to_html_minimal(report.body_markdown)

    return f"""<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:720px;margin:0 auto;padding:28px;color:#111827">
<div style="text-align:center;margin-bottom:22px">
<h1 style="margin:0;font-size:24px">🍖 Spider Grills telemetry report</h1>
<p style="color:#6b7280;margin:6px 0 0;font-size:13px">{_escape(report.title)}</p>
<p style="color:#9ca3af;margin:2px 0 0;font-size:11px">{_escape(report.report_date)} · {_escape(report.window_start)} → {_escape(report.window_end)} · {_escape(report.report_type)}</p>
</div>
<div style="padding:14px 18px;background:#f0f7ff;border-left:4px solid #4a7aff;border-radius:4px;margin-bottom:16px">
<h2 style="color:#111827;margin:0 0 6px;font-size:16px">Executive summary</h2>
<div style="font-size:13px;color:#374151;line-height:1.6">{_escape(report.summary).replace(chr(10), '<br>')}</div>
</div>
{findings_html}
{body_html}
<hr style="border:none;border-top:1px solid #e5e7eb;margin:28px 0">
<p style="color:#9ca3af;font-size:11px;text-align:center">
<a href="https://kpi.spidergrills.com/division/product-engineering" style="color:#4a7aff">Open in the dashboard ↗</a>
 · Generated by Claude Opus 4.7 from {len(report.sources_used or [])} data sources.</p>
</body></html>"""


def _render_text(report: TelemetryReport) -> str:
    return f"""{report.title}
{'='*len(report.title)}

{report.summary}

Full report: https://kpi.spidergrills.com/division/product-engineering
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--type", choices=["comprehensive", "monthly"], default="monthly")
    p.add_argument("--id", type=int, help="Explicit report ID (otherwise pick latest of --type).")
    args = p.parse_args()

    settings = get_settings()
    if not settings.push_alerts_enabled:
        print("push_alerts_enabled=false — skipping")
        return 0

    recipient = assert_allowed(settings.push_alerts_recipient_email)[0]
    db = SessionLocal()
    try:
        if args.id:
            report = db.get(TelemetryReport, args.id)
        else:
            report = db.execute(
                select(TelemetryReport)
                .where(TelemetryReport.report_type == args.type, TelemetryReport.status == "published")
                .order_by(TelemetryReport.report_date.desc(), TelemetryReport.id.desc())
                .limit(1)
            ).scalars().first()
        if report is None:
            print(f"No {args.type} report found to email.")
            return 1

        subject_id = f"telemetry_report:{report.id}"
        already = db.execute(
            select(NotificationSend.id).where(
                NotificationSend.channel == "email",
                NotificationSend.subject_type == "telemetry_report",
                NotificationSend.subject_id == subject_id,
                NotificationSend.recipient == recipient,
            ).limit(1)
        ).first()
        if already is not None:
            print(f"Report {report.id} already emailed to {recipient} — skipping")
            return 0

        subject = f"Spider Grills telemetry report — {report.title}"[:200]
        body_html = _render_html(report)
        body_text = _render_text(report)

        sender = os.environ.get("AUTH_EMAIL_FROM", "no-reply@spidergrills.app")
        region = os.environ.get("AUTH_EMAIL_REGION") or os.environ.get("AWS_REGION") or "us-east-2"
        client = boto3.client(
            "sesv2",
            region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        client.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": [recipient]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            }},
        )
        db.add(NotificationSend(
            channel="email",
            recipient=recipient,
            subject_type="telemetry_report",
            subject_id=subject_id,
            sent_at=datetime.now(timezone.utc),
            success=True,
            metadata_json={"subject": subject, "report_id": report.id, "report_type": report.report_type},
        ))
        db.commit()
        print(f"emailed report {report.id} ({report.report_type}) to {recipient}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
