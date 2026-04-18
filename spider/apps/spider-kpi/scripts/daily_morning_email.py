#!/usr/bin/env python3
"""Daily morning brief email — sent 7am ET via cron.

Renders the same data that powers the Command Center morning view into an
HTML email and delivers it via SES. Dedupes on (email, YYYY-MM-DD) so a
cron re-run in the same day is a no-op.

Install:
    # Add to /etc/crontab (or user crontab via `crontab -e`):
    0 7 * * * jpruit20 /opt/spiderclawkpi/spider/apps/spider-kpi/.venv/bin/python \
        /opt/spiderclawkpi/spider/apps/spider-kpi/scripts/daily_morning_email.py \
        >> /var/log/spider-kpi-morning-email.log 2>&1
    # 0 7 * * * = 07:00 UTC daily. For 7am ET use 0 11 * * * (UTC-5) or
    # 0 12 * * * (UTC-4 during DST). Simpler: use `CRON_TZ=America/New_York`.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


# --- .env loading ---
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

BUSINESS_TZ = ZoneInfo("America/New_York")
BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import boto3

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.api.routes.executive import morning_brief
from app.models import NotificationSend
from sqlalchemy import select


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _fmt_currency(n) -> str:
    try:
        return f"${float(n):,.0f}"
    except Exception:
        return "—"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    return f"{float(n) * 100:.0f}%"


def _escape(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_html(brief: dict) -> str:
    h = brief.get("headline", {})
    rev = brief.get("revenue", {})
    velo = brief.get("clickup_velocity", {})
    tel = brief.get("telemetry")
    comp = brief.get("compliance") or {}
    slack_hot = brief.get("slack_hot")
    now = datetime.now(BUSINESS_TZ)

    rev_wow = h.get("revenue_wow_pct")
    rev_color = "#16a34a" if (rev_wow or 0) >= 0 else "#b91c1c"
    velo_wow = h.get("clickup_wow_delta", 0)
    velo_color = "#16a34a" if velo_wow >= 0 else "#b91c1c"

    parts = [
        '<html><body style="font-family:Arial,sans-serif;color:#111827;line-height:1.55;max-width:640px;margin:0 auto;padding:24px">',
        '<div style="text-align:center;margin-bottom:20px">',
        '<h2 style="margin:0;color:#111827">☕ Spider Grills — Morning brief</h2>',
        f'<p style="color:#6b7280;margin:4px 0 0;font-size:13px">{_escape(now.strftime("%A, %B %d, %Y · %-I:%M %p ET"))}</p>',
        '</div>',
        '<table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:18px">',
        '<tr>',
    ]
    wismo_7 = h.get("wismo_last_7", 0) or 0
    wismo_delta = h.get("wismo_wow_delta", 0) or 0
    wismo_color = "#16a34a" if wismo_7 == 0 else ("#f59e0b" if wismo_7 <= 3 else "#b91c1c")
    kpi_items = [
        ("Drafts to review", _fmt_int(h.get("drafts_awaiting_review", 0)), "#4a7aff" if h.get("drafts_awaiting_review", 0) > 0 else "#9ca3af"),
        ("Critical signals (24h)", _fmt_int(h.get("critical_signals_24h", 0)), "#b91c1c" if h.get("critical_signals_24h", 0) > 0 else "#9ca3af"),
        ("Overdue urgent/high", _fmt_int(h.get("overdue_urgent_or_high", 0)), "#b91c1c" if h.get("overdue_urgent_or_high", 0) > 0 else "#9ca3af"),
        ("Revenue WoW", f'{"+" if (rev_wow or 0) >= 0 else ""}{rev_wow:.0f}%' if rev_wow is not None else "—", rev_color if rev_wow is not None else "#9ca3af"),
        ("Tasks closed WoW", f'{"+" if velo_wow >= 0 else ""}{velo_wow}', velo_color),
        ("WISMO 7d (target 0)", f"{wismo_7} ({'+' if wismo_delta > 0 else ''}{wismo_delta})", wismo_color),
    ]
    for label, value, color in kpi_items:
        parts.append(
            f'<td align="center" style="padding:8px 4px">'
            f'<div style="font-size:11px;color:#6b7280;margin-bottom:2px">{_escape(label)}</div>'
            f'<div style="font-size:22px;font-weight:700;color:{color}">{_escape(value)}</div>'
            f'</td>'
        )
    parts.append('</tr></table>')

    # AI Insights — cross-source observations (top of fold, below KPI strip)
    insights = brief.get("insights") or []
    if insights:
        parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #b88bff;padding-bottom:6px;margin-top:20px">AI insights — cross-source observations ({len(insights)})</h3>')
        for ins in insights:
            urgency = (ins.get("urgency") or "medium").lower()
            bg = "#fef2f2" if urgency == "high" else "#fffbeb" if urgency == "medium" else "#f8fafc"
            accent = "#b91c1c" if urgency == "high" else "#f59e0b" if urgency == "medium" else "#6b7280"
            conf_pct = int(round(float(ins.get("confidence") or 0) * 100))
            evidence = ins.get("evidence") or []
            sources = ins.get("sources_used") or []
            sug = ins.get("suggested_action")
            ev_html = ""
            if evidence:
                ev_items = "".join(f"<li>{_escape(e)}</li>" for e in evidence[:4])
                ev_html = f'<ul style="margin:6px 0 0;padding-left:18px;color:#4b5563;font-size:11px">{ev_items}</ul>'
            sug_html = (
                f'<div style="color:#1f2937;font-size:11px;margin-top:6px"><strong style="color:#4a7aff">Suggested:</strong> {_escape(sug)}</div>'
                if sug else ""
            )
            src_html = ""
            if sources:
                src_html = (
                    '<div style="margin-top:6px;font-size:10px;color:#6b7280">' +
                    " · ".join(_escape(s) for s in sources) +
                    '</div>'
                )
            parts.append(
                f'<div style="padding:10px 12px;background:{bg};border-left:3px solid {accent};border-radius:4px;margin-bottom:10px">'
                f'<div><strong style="color:#111827;font-size:13px">{_escape(ins.get("title") or "")}</strong>'
                f' <span style="color:{accent};font-size:11px;margin-left:6px;font-weight:600;text-transform:uppercase">{_escape(urgency)}</span>'
                f' <span style="color:#6b7280;font-size:11px;margin-left:6px">{conf_pct}% conf</span>'
                f'</div>'
                f'<p style="color:#374151;font-size:12px;margin:6px 0 0">{_escape(ins.get("observation") or "")}</p>'
                f'{ev_html}'
                f'{sug_html}'
                f'{src_html}'
                f'</div>'
            )

    # Drafts
    drafts = brief.get("drafts") or []
    if drafts:
        parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #4a7aff;padding-bottom:6px;margin-top:20px">Drafts awaiting your review ({h.get("drafts_awaiting_review", len(drafts))})</h3>')
        for d in drafts:
            origin = (d.get("origin_signal_type") or "").split(".")[0]
            parts.append(
                f'<div style="padding:10px 12px;background:#f8fafc;border-left:3px solid #4a7aff;border-radius:4px;margin-bottom:8px">'
                f'<strong style="color:#374151;font-size:13px">{_escape(d.get("title") or "(untitled)")}</strong>'
                f' <span style="color:#6b7280;font-size:11px;margin-left:6px">{_escape(origin)} · {_escape(d.get("priority"))}'
                f'{f" · {_escape(d.get(chr(0x22)+chr(0x64)+chr(0x65)+chr(0x70)+chr(0x61)+chr(0x72)+chr(0x74)+chr(0x6d)+chr(0x65)+chr(0x6e)+chr(0x74)+chr(0x22)))}" if d.get("department") else ""}'
                f'</span></div>'
            )

    # Critical signals + stale tasks
    crits = brief.get("critical_signals") or []
    if crits:
        parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #b91c1c;padding-bottom:6px;margin-top:20px">Critical signals — last 24h</h3>')
        for s in crits:
            url = (s.get("metadata") or {}).get("url")
            title = s.get("title") or ""
            link = f'<a href="{_escape(url)}" style="color:#b91c1c" target="_blank">{_escape(title)}</a>' if url else _escape(title)
            parts.append(
                f'<div style="padding:8px 12px;background:#fef2f2;border-left:3px solid #b91c1c;border-radius:4px;margin-bottom:6px;font-size:12px">'
                f'<strong>{link}</strong>'
                f' <span style="color:#6b7280;font-size:11px">· {_escape(s.get("source"))}</span>'
                f'<div style="color:#4b5563;margin-top:2px">{_escape((s.get("summary") or "")[:180])}</div>'
                f'</div>'
            )

    stale = brief.get("stale_tasks") or []
    if stale:
        parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #f59e0b;padding-bottom:6px;margin-top:20px">Overdue urgent/high tasks</h3>')
        for t in stale:
            url = t.get("url")
            title = t.get("name") or "(untitled)"
            link = f'<a href="{_escape(url)}" style="color:#b91c1c" target="_blank">{_escape(title)}</a>' if url else _escape(title)
            pri_color = "#b91c1c" if t.get("priority") == "urgent" else "#f59e0b"
            parts.append(
                f'<div style="padding:8px 12px;background:#fffbeb;border-left:3px solid {pri_color};border-radius:4px;margin-bottom:6px;font-size:12px">'
                f'<strong>{link}</strong>'
                f' <span style="color:{pri_color};font-weight:600">{_escape(t.get("priority"))}</span>'
                f' <span style="color:#b91c1c">· {t.get("days_overdue", 0)}d overdue</span>'
                f'<div style="color:#6b7280;font-size:11px;margin-top:2px">'
                f'{_escape(t.get("space_name"))} · {_escape(t.get("list_name"))}'
                f'{(" · " + ", ".join(filter(None, t.get("assignees") or []))) if t.get("assignees") else ""}'
                f'</div>'
                f'</div>'
            )

    # Revenue + telemetry + velocity + slack hot
    parts.append('<h3 style="color:#111827;border-bottom:2px solid #16a34a;padding-bottom:6px;margin-top:20px">By the numbers</h3>')
    parts.append('<ul style="margin:6px 0;padding-left:18px;font-size:13px;color:#374151">')
    parts.append(
        f'<li><strong>Revenue</strong>: {_fmt_currency(rev.get("trailing_7"))} last 7d'
        f' vs {_fmt_currency(rev.get("prior_7"))} prior 7d'
        f' (<span style="color:{rev_color}">{"+" if (rev.get("wow_delta") or 0) >= 0 else ""}{_fmt_currency(rev.get("wow_delta"))}</span>)'
        f'</li>'
    )
    parts.append(
        f'<li><strong>ClickUp velocity</strong>: {_fmt_int(velo.get("closed_last_7"))} tasks closed last 7d'
        f' (<span style="color:{velo_color}">{"+" if (velo.get("wow_delta") or 0) >= 0 else ""}{velo.get("wow_delta")}</span> vs prior 7d)'
        f'</li>'
    )
    if tel:
        parts.append(
            f'<li><strong>Fleet ({_escape(tel.get("business_date"))})</strong>: {_fmt_int(tel.get("active_devices"))} active devices, '
            f'{_fmt_int(tel.get("engaged_devices"))} actively cooking. '
            f'Cook success: <strong>{_fmt_pct(tel.get("cook_success_rate"))}</strong> · '
            f'error rate: <strong>{_fmt_pct(tel.get("error_rate"))}</strong>'
            f'</li>'
        )
    if comp.get("taxonomy_configured"):
        parts.append(
            f'<li><strong>Tagging compliance</strong>: {_fmt_pct(comp.get("rate_closed_in_window"))} of closed tasks tagged (14-day window)</li>'
        )
    parts.append('</ul>')

    if slack_hot:
        parts.append(f'<h3 style="color:#111827;border-bottom:2px solid #4a154b;padding-bottom:6px;margin-top:20px">Hottest Slack thread</h3>')
        parts.append(
            f'<div style="padding:8px 12px;background:#faf7fb;border-left:3px solid #4a154b;border-radius:4px;font-size:12px">'
            f'<strong>{_escape(slack_hot.get("user_name"))}</strong> '
            f'<span style="color:#6b7280">· {slack_hot.get("reactions")} reactions</span>'
            f'<div style="color:#374151;margin-top:4px">{_escape(slack_hot.get("text"))}</div>'
            f'</div>'
        )

    parts.append(
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">'
        '<p style="color:#9ca3af;font-size:11px;text-align:center">'
        '<a href="https://kpi.spidergrills.com/" style="color:#4a7aff">Open the dashboard ↗</a>'
        ' · Auto-generated every morning from the KPI dashboard.</p>'
        '</body></html>'
    )
    return "\n".join(parts)


def _render_text(brief: dict) -> str:
    h = brief.get("headline", {})
    lines = [
        "Spider Grills — Morning brief",
        "=" * 45,
        "",
        f"  {h.get('drafts_awaiting_review', 0)} drafts to review",
        f"  {h.get('critical_signals_24h', 0)} critical signals (24h)",
        f"  {h.get('overdue_urgent_or_high', 0)} overdue urgent/high tasks",
    ]
    rev_wow = h.get("revenue_wow_pct")
    if rev_wow is not None:
        lines.append(f"  Revenue {'+' if rev_wow >= 0 else ''}{rev_wow:.0f}% WoW")
    lines.append(f"  Tasks closed WoW: {'+' if h.get('clickup_wow_delta', 0) >= 0 else ''}{h.get('clickup_wow_delta', 0)}")
    lines.append("")
    insights = brief.get("insights") or []
    if insights:
        lines.append(f"AI insights ({len(insights)}):")
        for ins in insights:
            lines.append(f"  [{(ins.get('urgency') or '?').upper()}] {ins.get('title') or ''}")
        lines.append("")
    lines.append("Open: https://kpi.spidergrills.com/")
    return "\n".join(lines)


def send_morning_email() -> None:
    settings = get_settings()
    if not settings.push_alerts_enabled:
        print("push_alerts_enabled=false — skipping")
        return

    recipient = settings.push_alerts_recipient_email
    today = datetime.now(BUSINESS_TZ).date().isoformat()

    db = SessionLocal()
    try:
        # Dedup — one morning email per recipient per day.
        already = db.execute(
            select(NotificationSend.id).where(
                NotificationSend.channel == "email",
                NotificationSend.subject_type == "morning_digest",
                NotificationSend.subject_id == today,
                NotificationSend.recipient == recipient,
            ).limit(1)
        ).first()
        if already is not None:
            print(f"morning digest for {recipient} already sent today — skipping")
            return

        brief = morning_brief(db=db)
        body_html = _render_html(brief)
        body_text = _render_text(brief)

        h = brief.get("headline", {})
        flags = []
        if h.get("insights_high_urgency", 0):
            flags.append(f"{h['insights_high_urgency']} high-urgency insights")
        if h.get("critical_signals_24h", 0):
            flags.append(f"{h['critical_signals_24h']} critical")
        if h.get("overdue_urgent_or_high", 0):
            flags.append(f"{h['overdue_urgent_or_high']} overdue")
        if h.get("drafts_awaiting_review", 0):
            flags.append(f"{h['drafts_awaiting_review']} drafts")
        if h.get("wismo_last_7", 0):
            flags.append(f"{h['wismo_last_7']} WISMO this week")
        flags_str = " · ".join(flags) if flags else "all quiet"

        now = datetime.now(BUSINESS_TZ)
        subject = f"Spider Grills morning brief — {now.strftime('%b %d')} ({flags_str})"

        sender = os.environ.get("AUTH_EMAIL_FROM", "no-reply@spidergrills.app")
        region = os.environ.get("AUTH_EMAIL_REGION") or os.environ.get("AWS_REGION") or "us-east-2"

        client = boto3.client(
            "sesv2",
            region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )
        try:
            client.send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [recipient]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": body_text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    }
                },
            )
            db.add(NotificationSend(
                channel="email",
                recipient=recipient,
                subject_type="morning_digest",
                subject_id=today,
                sent_at=datetime.now(timezone.utc),
                success=True,
                metadata_json={"subject": subject},
            ))
            db.commit()
            print(f"morning brief sent to {recipient}")
        except Exception as exc:
            db.add(NotificationSend(
                channel="email",
                recipient=recipient,
                subject_type="morning_digest",
                subject_id=today,
                sent_at=datetime.now(timezone.utc),
                success=False,
                error=str(exc),
            ))
            db.commit()
            raise
    finally:
        db.close()


if __name__ == "__main__":
    send_morning_email()
