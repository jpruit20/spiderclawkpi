"""Grant the AMW SharePoint app per-site read access via Microsoft Graph.

Architecture context: the dashboard's Azure AD app registration has
``Sites.Selected`` permission at the platform level. That alone grants
nothing — the app needs an explicit ``POST /sites/{id}/permissions``
call per site to actually read it. Existing per-product Spider sites
were granted via this script (the docstring in
``app/ingestion/connectors/sharepoint.py`` references it but it
hadn't been committed); committing it now to handle Kienco + Qifei
vendor-workspace sites.

Usage (on the droplet):

    cd /opt/spiderclawkpi/spider/apps/spider-kpi/backend
    python -m scripts.grant_sharepoint_sites \\
        --site-path ATL-IP-00151-KiencoFactory \\
        --display-name "Kienco Factory" \\
        --tenant-id 2e9275cf-ffd9-4f18-abdc-c0ac8d85e26f

Multiple --site-path values supported; each runs sequentially.

What it does (per site):

    1. Resolve graph_site_id via /sites/{hostname}:/sites/{path}.
    2. POST /sites/{site_id}/permissions with the AMW app's client_id
       in grantedToIdentities and roles=[read]. Idempotent — re-runs
       are no-ops because Graph dedupes on (app, role).
    3. INSERT INTO sharepoint_sites (or UPDATE if it exists) with
       spider_product=NULL, default_division=NULL, granted_at=NOW().
       NULL spider_product means "mixed-content workspace" — the
       per-document classifier handles Spider-relevance filtering.

After the script lands a row, the regular hourly sharepoint sync
will pick it up automatically; no separate trigger needed.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.connectors.sharepoint import _get_app_token, _graph_get
from app.models import MicrosoftTenant, SharepointSite

import requests


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")


def _grant_site_permission(token: str, graph_site_id: str, app_client_id: str, app_display_name: str) -> dict:
    """Call POST /sites/{id}/permissions to grant the app read access.

    Idempotent: re-running for a site already granted to the same app
    returns the existing permission row rather than erroring.
    """
    url = f"https://graph.microsoft.com/v1.0/sites/{graph_site_id}/permissions"
    body = {
        "roles": ["read"],
        "grantedToIdentities": [
            {
                "application": {
                    "id": app_client_id,
                    "displayName": app_display_name,
                }
            }
        ],
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    if resp.status_code in (200, 201):
        return resp.json()
    raise RuntimeError(f"Grant failed: {resp.status_code} {resp.text[:400]}")


def grant_one(
    tenant_id: str,
    site_path: str,
    display_name: str | None,
    spider_product: str | None,
    default_division: str | None,
    hostname: str,
) -> None:
    settings = get_settings()
    log = logging.getLogger("grant_sharepoint")

    db = SessionLocal()
    try:
        tenant = db.query(MicrosoftTenant).filter_by(tenant_id=tenant_id).one()
        token = _get_app_token(tenant.tenant_id)

        # 1) Resolve graph_site_id
        site_data = _graph_get(token, f"/sites/{hostname}:/sites/{site_path}")
        graph_site_id = site_data.get("id")
        web_url = site_data.get("webUrl")
        api_display_name = site_data.get("displayName") or display_name or site_path
        log.info("Resolved %s → graph_site_id=%s display=%s", site_path, graph_site_id, api_display_name)

        # 2) Grant the app read access
        if not settings.ms_graph_client_id:
            raise RuntimeError("MS_GRAPH_CLIENT_ID not set — cannot self-grant")
        grant_result = _grant_site_permission(
            token,
            graph_site_id,
            app_client_id=settings.ms_graph_client_id,
            app_display_name="Spider KPI Dashboard",
        )
        log.info("Grant OK: permission_id=%s roles=%s", grant_result.get("id"), grant_result.get("roles"))

        # 3) Upsert into sharepoint_sites
        existing = db.query(SharepointSite).filter_by(tenant_id=tenant_id, site_path=site_path).one_or_none()
        if existing:
            existing.graph_site_id = graph_site_id
            existing.hostname = hostname
            existing.display_name = api_display_name
            existing.web_url = web_url
            existing.spider_product = spider_product
            existing.default_division = default_division
            existing.enabled = True
            existing.granted_at = datetime.now(timezone.utc)
            log.info("Updated existing sharepoint_sites row id=%d", existing.id)
        else:
            row = SharepointSite(
                tenant_id=tenant_id,
                graph_site_id=graph_site_id,
                site_path=site_path,
                hostname=hostname,
                display_name=api_display_name,
                web_url=web_url,
                spider_product=spider_product,  # NULL = mixed-content workspace
                default_division=default_division,  # NULL = classifier-driven per doc
                enabled=True,
                granted_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.flush()
            log.info("Inserted sharepoint_sites row id=%d", row.id)

        db.commit()
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="Azure AD tenant ID (UUID).")
    parser.add_argument("--hostname", default="alignmachineworks.sharepoint.com", help="SharePoint hostname.")
    parser.add_argument("--site-path", action="append", required=True,
                        help="Site path (e.g. 'ATL-IP-00151-KiencoFactory'). Repeatable.")
    parser.add_argument("--display-name", default=None, help="Override display name (defaults to Graph's value).")
    parser.add_argument("--spider-product", default=None,
                        help="Per-product mapping (e.g. 'Huntsman'). Omit for mixed-content workspaces.")
    parser.add_argument("--default-division", default=None,
                        help="Default division tag (cx|marketing|operations|pe|manufacturing). "
                             "Omit for mixed-content workspaces — content classifier tags per-doc.")
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger("grant_sharepoint")

    fail_count = 0
    for path in args.site_path:
        try:
            grant_one(
                tenant_id=args.tenant_id,
                site_path=path,
                display_name=args.display_name,
                spider_product=args.spider_product,
                default_division=args.default_division,
                hostname=args.hostname,
            )
        except Exception as exc:
            log.exception("Failed for site_path=%s: %s", path, exc)
            fail_count += 1
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
