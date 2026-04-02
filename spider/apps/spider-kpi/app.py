#!/usr/bin/env python3
import json
import os
import subprocess
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for


BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider-kpi")
DATA_DIR = BASE_DIR / "data" / "processed"
SCRIPTS_DIR = BASE_DIR / "scripts"
LOG_FILE = BASE_DIR / "logs" / "webapp.log"
REFRESH_SCRIPT = SCRIPTS_DIR / "refresh_all.py"
PASSWORD_ENV = "SPIDER_KPI_PASSWORD"
DEFAULT_PASSWORD = "spider-kpi"
REFRESH_INTERVAL_SECONDS = 300

PAGES = {
    "sales-marketing": {
        "title": "Sales & Marketing",
        "subtitle": "Revenue, orders, traffic, conversion, spend, and operating efficiency.",
    },
    "customer-service": {
        "title": "Customer Service",
        "subtitle": "Support load, service quality signals, and operational response metrics.",
    },
    "ui-ux": {
        "title": "UI / UX",
        "subtitle": "Website behavior signals to uncover friction and improvement opportunities.",
    },
}

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "spider-kpi-secret")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def require_login(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("authenticated"):
            return view_func(*args, **kwargs)
        return redirect(url_for("login", next=request.path))

    return wrapped


def load_orders_daily() -> List[Dict[str, Any]]:
    data = read_json(DATA_DIR / "orders_daily.json", [])
    return data if isinstance(data, list) else []


def load_kpi_daily() -> List[Dict[str, Any]]:
    data = read_json(DATA_DIR / "kpi_daily.json", [])
    return data if isinstance(data, list) else []


def load_tw_metrics() -> Dict[str, Any]:
    data = read_json(DATA_DIR / "tw_metrics.json", {})
    return data if isinstance(data, dict) else {}


def latest_record(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return rows[-1] if rows else {}


def pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 1)


def build_sales_marketing_payload() -> Dict[str, Any]:
    kpis = load_kpi_daily()
    latest = latest_record(kpis)
    previous = kpis[-2] if len(kpis) >= 2 else {}
    tw = load_tw_metrics()

    revenue = safe_float(latest.get("revenue"))
    orders = safe_int(latest.get("orders"))
    aov = safe_float(latest.get("aov"))
    sessions_value = safe_float(tw.get("sessions"))
    conversion_rate = safe_float(tw.get("conversion_rate"))
    ad_spend = safe_float(tw.get("ad_spend"))
    mer = round(revenue / ad_spend, 2) if ad_spend > 0 else 0.0
    revenue_per_session = round(revenue / sessions_value, 2) if sessions_value > 0 else 0.0

    return {
        "page": "sales-marketing",
        "title": PAGES["sales-marketing"]["title"],
        "updated_at": now_iso(),
        "auto_refresh_seconds": REFRESH_INTERVAL_SECONDS,
        "cards": [
            {"label": "Revenue", "value": revenue, "format": "currency", "delta": latest.get("revenue_change_pct")},
            {"label": "Orders", "value": orders, "format": "integer", "delta": latest.get("order_change_pct")},
            {"label": "AOV", "value": aov, "format": "currency", "delta": pct_change(aov, safe_float(previous.get("aov")))},
            {"label": "Sessions", "value": sessions_value, "format": "integer", "delta": None},
            {"label": "Conversion Rate", "value": conversion_rate, "format": "percent", "delta": None},
            {"label": "Ad Spend", "value": ad_spend, "format": "currency", "delta": None},
            {"label": "MER", "value": mer, "format": "ratio", "delta": None},
            {"label": "Revenue / Session", "value": revenue_per_session, "format": "currency", "delta": None},
        ],
        "series": {
            "labels": [row.get("date") for row in kpis],
            "revenue": [safe_float(row.get("revenue")) for row in kpis],
            "orders": [safe_int(row.get("orders")) for row in kpis],
            "aov": [safe_float(row.get("aov")) for row in kpis],
        },
        "highlights": [
            f"Latest Shopify business date: {latest.get('date', 'n/a')}",
            f"Triple Whale sessions: {safe_int(tw.get('sessions'))}",
            f"Triple Whale bounce rate: {safe_float(tw.get('bounce_rate')):.2f}%",
            f"Triple Whale add-to-cart rate: {safe_float(tw.get('add_to_cart_rate')):.2f}%",
        ],
        "alerts": [latest.get("alert")] if latest.get("alert") else [],
    }


def build_customer_service_payload() -> Dict[str, Any]:
    tw = load_tw_metrics()
    tickets_created = safe_float(tw.get("gorgiasSensoryTicketsCreated", 0))
    tickets_replied = safe_float(tw.get("gorgiasSensoryTicketsReplied", 0))
    avg_response = safe_float(tw.get("gorgiasSensoryAvgResponseTime", 0))
    avg_resolution = safe_float(tw.get("gorgiasSensoryAvgResolutionTime", 0))

    return {
        "page": "customer-service",
        "title": PAGES["customer-service"]["title"],
        "updated_at": now_iso(),
        "auto_refresh_seconds": REFRESH_INTERVAL_SECONDS,
        "cards": [
            {"label": "Tickets Created", "value": tickets_created, "format": "integer", "delta": None},
            {"label": "Tickets Replied", "value": tickets_replied, "format": "integer", "delta": None},
            {"label": "Avg Response Time", "value": avg_response, "format": "hours", "delta": None},
            {"label": "Avg Resolution Time", "value": avg_resolution, "format": "hours", "delta": None},
        ],
        "series": {
            "labels": ["Current"],
            "tickets_created": [tickets_created],
            "tickets_replied": [tickets_replied],
        },
        "highlights": [
            "Customer service page is using current Triple Whale / Gorgias-style support signals when available.",
            "This page should later be upgraded with dedicated Gorgias, Help Scout, or Zendesk history.",
        ],
        "alerts": [],
    }


def build_ui_ux_payload() -> Dict[str, Any]:
    tw = load_tw_metrics()
    sessions_value = safe_float(tw.get("sessions"))
    users_value = safe_float(tw.get("users"))
    bounce_rate = safe_float(tw.get("bounce_rate"))
    add_to_cart_rate = safe_float(tw.get("add_to_cart_rate"))
    conversion_rate = safe_float(tw.get("conversion_rate"))
    page_views = safe_float(tw.get("page_views"))
    pages_per_session = round(page_views / sessions_value, 2) if sessions_value > 0 else 0.0

    friction_notes: List[str] = []
    if bounce_rate > 70:
        friction_notes.append("Bounce rate is elevated. Review landing page relevance and first-screen clarity.")
    if add_to_cart_rate < 3:
        friction_notes.append("Add-to-cart is weak. Product pages likely need clearer offers, trust, and pricing presentation.")
    if conversion_rate < 1:
        friction_notes.append("Conversion is low. Audit checkout friction, shipping messaging, and mobile experience.")
    if not friction_notes:
        friction_notes.append("No acute UI/UX failure signal detected from current traffic metrics.")

    return {
        "page": "ui-ux",
        "title": PAGES["ui-ux"]["title"],
        "updated_at": now_iso(),
        "auto_refresh_seconds": REFRESH_INTERVAL_SECONDS,
        "cards": [
            {"label": "Sessions", "value": sessions_value, "format": "integer", "delta": None},
            {"label": "Users", "value": users_value, "format": "integer", "delta": None},
            {"label": "Bounce Rate", "value": bounce_rate, "format": "percent", "delta": None},
            {"label": "Add to Cart Rate", "value": add_to_cart_rate, "format": "percent", "delta": None},
            {"label": "Conversion Rate", "value": conversion_rate, "format": "percent", "delta": None},
            {"label": "Pages / Session", "value": pages_per_session, "format": "ratio", "delta": None},
        ],
        "series": {
            "labels": ["Current"],
            "bounce_rate": [bounce_rate],
            "add_to_cart_rate": [add_to_cart_rate],
            "conversion_rate": [conversion_rate],
        },
        "highlights": friction_notes,
        "alerts": friction_notes if friction_notes and "No acute" not in friction_notes[0] else [],
    }


def refresh_data() -> Dict[str, Any]:
    if not REFRESH_SCRIPT.exists():
        return {
            "ok": False,
            "message": f"Missing refresh script: {REFRESH_SCRIPT}",
            "ran_at": now_iso(),
        }

    result = subprocess.run(
        [sys.executable, str(REFRESH_SCRIPT)],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )

    return {
        "ok": result.returncode == 0,
        "ran_at": now_iso(),
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


@app.route("/login", methods=["GET", "POST"])
def login() -> Response:
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = os.getenv(PASSWORD_ENV, DEFAULT_PASSWORD)
        if password == expected:
            session["authenticated"] = True
            next_url = request.args.get("next") or url_for("dashboard_page", page_name="sales-marketing")
            return redirect(next_url)
        error = "Incorrect password."
    return Response(render_template("login.html", error=error), mimetype="text/html")


@app.route("/logout")
def logout() -> Response:
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_login
def home() -> Response:
    return redirect(url_for("dashboard_page", page_name="sales-marketing"))


@app.route("/page/<page_name>")
@require_login
def dashboard_page(page_name: str) -> Response:
    if page_name not in PAGES:
        return Response("Not found", status=404)
    return Response(
        render_template(
            "dashboard.html",
            pages=PAGES,
            current_page=page_name,
            refresh_seconds=REFRESH_INTERVAL_SECONDS,
        ),
        mimetype="text/html",
    )


@app.route("/api/page/<page_name>")
@require_login
def api_page(page_name: str):
    if page_name == "sales-marketing":
        return jsonify(build_sales_marketing_payload())
    if page_name == "customer-service":
        return jsonify(build_customer_service_payload())
    if page_name == "ui-ux":
        return jsonify(build_ui_ux_payload())
    return jsonify({"error": "Not found"}), 404


@app.route("/api/refresh", methods=["POST"])
@require_login
def api_refresh():
    return jsonify(refresh_data())


@app.route("/health")
def health():
    return jsonify({"ok": True, "time": now_iso()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787, debug=False)
