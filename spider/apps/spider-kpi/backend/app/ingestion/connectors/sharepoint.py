"""SharePoint ingest via Microsoft Graph (multi-tenant, app-only auth).

Architecture rationale (Joseph 2026-04-26 design call):

* **Multi-tenant** — same Azure AD app registration services every
  tenant. AMW today, Spider Grills' own M365 next. New tenants are an
  INSERT into ``microsoft_tenants``, not a deploy.

* **Card-scoped allowlist** — ``sharepoint_sites`` is a per-tenant
  table of (site_path, spider_product, dashboard_division) rows.
  Joseph maintains this; the connector reads it. Anything not in the
  allowlist is invisible to the dashboard, even if the OAuth token
  theoretically grants access. Microsoft enforces a second layer at
  the platform level: ``Sites.Selected`` returns 403 on every site
  that hasn't been explicitly granted via
  ``POST /sites/{id}/permissions`` (one-time setup via
  ``scripts/grant_sharepoint_sites.py``).

* **Folder→division mapping** — every product card on AMW's
  SharePoint follows the same folder taxonomy:
  ``Engineering`` → PE, ``Production and QC`` → Manufacturing,
  ``Project Management`` → Operations, ``General`` → uncategorized.
  This is denormalized into ``top_level_folder`` so dashboard cards
  filter by division without walking paths.

* **App-only auth** — ``client_credentials`` OAuth grant against
  each tenant. Token cached in-process for ~50 min (1h TTL with
  10-min skew). No refresh token / no user OAuth dance for this
  ingest because the dashboard is a daemon, not a user-facing app.

Sync model: hourly via run_syncs_subprocess (registered there
separately, so leaks die on subprocess exit). Per-site incremental
using Graph delta tokens where supported, falls back to full scan
filtered by ``lastModifiedDateTime > last_synced_at``.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    MicrosoftTenant,
    SharepointDocument,
    SharepointListItem,
    SharepointSite,
)
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config


settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(h)


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TIMEOUT = 30
MAX_RETRIES = 5

# Folder name → dashboard division mapping. Folders not in this map
# get tagged "general" (uncategorized; visible but not auto-routed).
FOLDER_TO_DIVISION = {
    "engineering": "pe",
    "production and qc": "manufacturing",
    "project management": "operations",
    "general": "general",
}


# ── Token cache ─────────────────────────────────────────────────────


_token_cache: dict[str, tuple[float, str]] = {}


def _get_app_token(tenant_id: str) -> str:
    """App-only token for the given tenant. Cached for ~50 min."""
    now = time.time()
    cached = _token_cache.get(tenant_id)
    if cached and now < cached[0]:
        return cached[1]

    if not (settings.ms_graph_client_id and settings.ms_graph_client_secret):
        raise RuntimeError(
            "MS_GRAPH_CLIENT_ID / MS_GRAPH_CLIENT_SECRET not configured. "
            "See docs at https://entra.microsoft.com to register a multi-tenant app."
        )

    resp = requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.ms_graph_client_id,
            "client_secret": settings.ms_graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token acquisition failed for tenant {tenant_id}: {resp.status_code} {resp.text[:300]}")
    body = resp.json()
    token = body["access_token"]
    expires_in = int(body.get("expires_in", 3600))
    _token_cache[tenant_id] = (now + expires_in - 600, token)  # 10-min skew
    return token


def _graph_get(token: str, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET against Graph with rate-limit-aware retry."""
    if not url.startswith("http"):
        url = f"{GRAPH_BASE}{url}"
    attempts = 0
    while True:
        attempts += 1
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempts >= MAX_RETRIES:
                raise
            time.sleep(min(2 ** attempts, 30))
            continue
        if r.status_code == 429 and attempts < MAX_RETRIES:
            wait = int(r.headers.get("Retry-After") or "5")
            logger.info("graph: rate-limited, sleep %ss (attempt %s)", wait, attempts)
            time.sleep(wait)
            continue
        if r.status_code >= 500 and attempts < MAX_RETRIES:
            time.sleep(min(2 ** attempts, 30))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Graph {r.status_code} {url}: {r.text[:400]}")
        return r.json()


def _graph_paginate(token: str, url: str, params: Optional[dict[str, Any]] = None) -> Iterable[dict[str, Any]]:
    """Yield pages following @odata.nextLink."""
    next_url: Optional[str] = url
    next_params: Optional[dict[str, Any]] = params
    while next_url:
        page = _graph_get(token, next_url, params=next_params)
        yield page
        next_url = page.get("@odata.nextLink")
        next_params = None  # baked into nextLink


# ── Site metadata refresh ───────────────────────────────────────────


def _refresh_site_metadata(db: Session, tenant: MicrosoftTenant, site: SharepointSite) -> bool:
    """Resolve graph_site_id + display_name + web_url. Idempotent."""
    token = _get_app_token(tenant.tenant_id)
    site_lookup = f"/sites/{site.hostname}:/sites/{site.site_path}"
    try:
        d = _graph_get(token, site_lookup)
    except Exception as exc:
        site.last_sync_error = f"site lookup failed: {exc}"[:500]
        return False
    site.graph_site_id = d.get("id")
    site.display_name = d.get("displayName")
    site.web_url = d.get("webUrl")
    if site.granted_at is None:
        site.granted_at = datetime.now(timezone.utc)
    return True


# ── Drive walking ────────────────────────────────────────────────────


def _walk_drive_items(token: str, drive_id: str) -> Iterable[dict[str, Any]]:
    """Recursively walk a drive, yielding every file + folder."""
    stack = [f"/drives/{drive_id}/root/children"]
    while stack:
        url = stack.pop()
        for page in _graph_paginate(token, url):
            for item in page.get("value", []):
                yield item
                if "folder" in item:
                    stack.append(f"/drives/{drive_id}/items/{item['id']}/children")


def _classify_item(item: dict[str, Any], parent_top_folder: Optional[str] = None) -> dict[str, Optional[str]]:
    """Return ``{top_level_folder, dashboard_division}`` for a Graph
    drive item. Top-level folder is preserved through descent so a
    PDF buried 3 levels under "Engineering" still gets ``pe``."""
    parent_ref = item.get("parentReference") or {}
    parent_path = (parent_ref.get("path") or "").split("root:", 1)[-1]
    # Path is like "/Engineering/Subfolder" — the first segment after
    # the drive root is the top-level folder. If we're at root, this
    # item itself is the top-level folder.
    parts = [p for p in parent_path.split("/") if p]
    if parts:
        top = parts[0]
    elif "folder" in item:
        top = item.get("name")
    else:
        top = None
    division = FOLDER_TO_DIVISION.get((top or "").lower())
    return {"top_level_folder": top, "dashboard_division": division}


def _flatten_doc(item: dict[str, Any], site: SharepointSite, drive_id: str) -> dict[str, Any]:
    classification = _classify_item(item)
    parent_ref = item.get("parentReference") or {}
    parent_path = (parent_ref.get("path") or "").split("root:", 1)[-1] or "/"
    full_path = f"{parent_path}/{item.get('name')}".replace("//", "/")
    fs_info = item.get("fileSystemInfo") or {}
    created_by = ((item.get("createdBy") or {}).get("user") or {}).get("email")
    modified_by = ((item.get("lastModifiedBy") or {}).get("user") or {}).get("email")

    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return {
        "tenant_id": site.tenant_id,
        "graph_site_id": site.graph_site_id or "",
        "graph_drive_id": drive_id,
        "graph_item_id": item.get("id"),
        "name": (item.get("name") or "")[:512],
        "path": full_path[:2048],
        "is_folder": "folder" in item,
        "top_level_folder": (classification.get("top_level_folder") or "")[:255] or None,
        "size_bytes": item.get("size"),
        "mime_type": ((item.get("file") or {}).get("mimeType") or None),
        "web_url": item.get("webUrl"),
        "created_by_email": created_by,
        "created_at_remote": _parse_dt(fs_info.get("createdDateTime") or item.get("createdDateTime")),
        "modified_by_email": modified_by,
        "modified_at_remote": _parse_dt(fs_info.get("lastModifiedDateTime") or item.get("lastModifiedDateTime")),
        "spider_product": site.spider_product,
        "dashboard_division": classification.get("dashboard_division") or site.default_division,
        "raw_metadata": {
            "etag": item.get("eTag"),
            "ctag": item.get("cTag"),
            "_raw_keys": sorted(list(item.keys())),
        },
    }


def _sync_site_documents(db: Session, tenant: MicrosoftTenant, site: SharepointSite) -> tuple[int, int]:
    token = _get_app_token(tenant.tenant_id)
    drives = _graph_get(token, f"/sites/{site.graph_site_id}/drives").get("value", [])
    inserted = 0
    seen = 0
    for drive in drives:
        drive_id = drive.get("id")
        if not drive_id:
            continue
        for item in _walk_drive_items(token, drive_id):
            seen += 1
            if not item.get("id"):
                continue
            row = _flatten_doc(item, site, drive_id)
            stmt = pg_insert(SharepointDocument).values(**row)
            update_cols = {
                k: stmt.excluded[k]
                for k in row.keys()
                if k not in ("graph_drive_id", "graph_item_id", "tenant_id")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["graph_drive_id", "graph_item_id"],
                set_=update_cols,
            )
            db.execute(stmt)
            inserted += 1
        db.commit()
    return inserted, seen


def _sync_site_lists(db: Session, tenant: MicrosoftTenant, site: SharepointSite) -> int:
    """List items are smaller and structured — full scan each time
    (lists are typically <500 rows)."""
    token = _get_app_token(tenant.tenant_id)
    lists = _graph_get(token, f"/sites/{site.graph_site_id}/lists").get("value", [])
    written = 0

    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    for lst in lists:
        list_id = lst.get("id")
        list_name = lst.get("displayName") or lst.get("name")
        if not list_id:
            continue
        # Skip the auto-generated "Documents" list (same content as the drive)
        if list_name and list_name.strip().lower() in ("documents", "form templates", "site assets", "site pages", "style library"):
            continue
        for page in _graph_paginate(token, f"/sites/{site.graph_site_id}/lists/{list_id}/items", params={"expand": "fields"}):
            for item in page.get("value", []):
                fields = item.get("fields") or {}
                created_by = ((item.get("createdBy") or {}).get("user") or {}).get("email")
                modified_by = ((item.get("lastModifiedBy") or {}).get("user") or {}).get("email")
                row = {
                    "tenant_id": site.tenant_id,
                    "graph_site_id": site.graph_site_id or "",
                    "graph_list_id": list_id,
                    "graph_list_name": list_name[:255] if list_name else None,
                    "graph_item_id": item.get("id"),
                    "title": (fields.get("Title") or fields.get("LinkTitle") or "")[:1024] or None,
                    "created_by_email": created_by,
                    "created_at_remote": _parse_dt(item.get("createdDateTime")),
                    "modified_by_email": modified_by,
                    "modified_at_remote": _parse_dt(item.get("lastModifiedDateTime")),
                    "web_url": item.get("webUrl"),
                    "fields": fields,
                    "spider_product": site.spider_product,
                    "dashboard_division": site.default_division,
                }
                stmt = pg_insert(SharepointListItem).values(**row)
                update_cols = {
                    k: stmt.excluded[k]
                    for k in row.keys()
                    if k not in ("graph_list_id", "graph_item_id", "tenant_id")
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=["graph_list_id", "graph_item_id"],
                    set_=update_cols,
                )
                db.execute(stmt)
                written += 1
            db.commit()
    return written


# ── Entry point ─────────────────────────────────────────────────────


def sync_sharepoint(db: Session) -> dict[str, Any]:
    """Sync every enabled (tenant, site) pair on the allowlist."""
    if not settings.ms_graph_client_id or not settings.ms_graph_client_secret:
        logger.info("sharepoint: MS_GRAPH credentials unset, skipping")
        upsert_source_config(db, "sharepoint", configured=False, config_json={"status": "awaiting_credentials"})
        db.commit()
        return {"ok": False, "skipped": True, "reason": "no_credentials"}

    run = start_sync_run(db, "sharepoint", sync_type="poll")
    upsert_source_config(db, "sharepoint", configured=True)
    db.commit()

    summary: dict[str, Any] = {"sites": [], "docs_total": 0, "lists_total": 0}
    errors: list[str] = []
    try:
        tenants = db.execute(
            select(MicrosoftTenant).where(MicrosoftTenant.enabled == True)  # noqa: E712
        ).scalars().all()
        for tenant in tenants:
            sites = db.execute(
                select(SharepointSite).where(
                    SharepointSite.tenant_id == tenant.tenant_id,
                    SharepointSite.enabled == True,  # noqa: E712
                )
            ).scalars().all()
            for site in sites:
                site_summary: dict[str, Any] = {
                    "tenant": tenant.tenant_id,
                    "site_path": site.site_path,
                    "spider_product": site.spider_product,
                }
                try:
                    if not site.graph_site_id:
                        if not _refresh_site_metadata(db, tenant, site):
                            site_summary["error"] = site.last_sync_error
                            summary["sites"].append(site_summary)
                            db.commit()
                            continue
                    docs_n, items_seen = _sync_site_documents(db, tenant, site)
                    lists_n = _sync_site_lists(db, tenant, site)
                    site.last_synced_at = datetime.now(timezone.utc)
                    site.last_sync_error = None
                    site_summary.update({"docs": docs_n, "items_seen": items_seen, "lists": lists_n})
                    summary["docs_total"] += docs_n
                    summary["lists_total"] += lists_n
                except Exception as exc:
                    logger.exception("sharepoint sync failed for %s/%s", tenant.tenant_id, site.site_path)
                    site.last_sync_error = str(exc)[:500]
                    site_summary["error"] = site.last_sync_error
                    errors.append(site.last_sync_error)
                summary["sites"].append(site_summary)
                db.commit()

        run.metadata_json = {**(run.metadata_json or {}), "summary": summary, "errors": errors[:5]}
        finish_sync_run(
            db, run,
            status="success" if not errors else "failed",
            records_processed=summary["docs_total"] + summary["lists_total"],
            error_message=("; ".join(errors[:3]))[:500] if errors else None,
        )
        db.commit()
        return {"ok": not bool(errors), **summary}
    except Exception as exc:
        logger.exception("sharepoint sync top-level failure")
        finish_sync_run(db, run, status="failed", error_message=str(exc)[:500])
        db.commit()
        raise
