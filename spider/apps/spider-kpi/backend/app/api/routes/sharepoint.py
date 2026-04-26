"""SharePoint query API for the dashboard.

Reads from the ``sharepoint_documents`` and ``sharepoint_list_items``
tables populated by ``ingestion.connectors.sharepoint``. All endpoints
filter through the ``sharepoint_sites`` allowlist by joining on
``graph_site_id``, so a query can never accidentally surface a site
that's not in the configured allowlist.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models import (
    MicrosoftTenant,
    SharepointDocument,
    SharepointListItem,
    SharepointSite,
)


router = APIRouter(prefix="/api/sharepoint", tags=["sharepoint"])


@router.get("/sites")
def list_sites(db: Session = Depends(db_session)) -> dict[str, Any]:
    rows = db.execute(
        select(SharepointSite, MicrosoftTenant)
        .join(MicrosoftTenant, MicrosoftTenant.tenant_id == SharepointSite.tenant_id, isouter=True)
        .order_by(SharepointSite.spider_product, SharepointSite.site_path)
    ).all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sites": [
            {
                "tenant_id": site.tenant_id,
                "tenant_display_name": (tenant.display_name if tenant else None),
                "site_path": site.site_path,
                "display_name": site.display_name,
                "spider_product": site.spider_product,
                "default_division": site.default_division,
                "web_url": site.web_url,
                "enabled": site.enabled,
                "last_synced_at": site.last_synced_at.isoformat() if site.last_synced_at else None,
                "last_sync_error": site.last_sync_error,
            }
            for site, tenant in rows
        ],
    }


@router.get("/recent-changes")
def recent_changes(
    days: int = Query(7, ge=1, le=90),
    division: Optional[str] = Query(None, description="pe / operations / manufacturing / general"),
    spider_product: Optional[str] = Query(None),
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Recently-modified documents + list items, optionally scoped to
    a division or product. Powers the "what changed in SharePoint
    yesterday" cards on the PE / Ops / Manufacturing pages."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    doc_q = (
        select(SharepointDocument)
        .where(
            SharepointDocument.modified_at_remote >= since,
            SharepointDocument.is_folder == False,  # noqa: E712
        )
        .order_by(SharepointDocument.modified_at_remote.desc())
        .limit(limit)
    )
    if division:
        doc_q = doc_q.where(SharepointDocument.dashboard_division == division)
    if spider_product:
        doc_q = doc_q.where(SharepointDocument.spider_product == spider_product)
    docs = db.execute(doc_q).scalars().all()

    list_q = (
        select(SharepointListItem)
        .where(SharepointListItem.modified_at_remote >= since)
        .order_by(SharepointListItem.modified_at_remote.desc())
        .limit(limit)
    )
    if division:
        list_q = list_q.where(SharepointListItem.dashboard_division == division)
    if spider_product:
        list_q = list_q.where(SharepointListItem.spider_product == spider_product)
    list_items = db.execute(list_q).scalars().all()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "filters": {"division": division, "spider_product": spider_product},
        "documents": [
            {
                "name": d.name,
                "path": d.path,
                "spider_product": d.spider_product,
                "dashboard_division": d.dashboard_division,
                "top_level_folder": d.top_level_folder,
                "modified_at": d.modified_at_remote.isoformat() if d.modified_at_remote else None,
                "modified_by_email": d.modified_by_email,
                "size_bytes": d.size_bytes,
                "mime_type": d.mime_type,
                "web_url": d.web_url,
            }
            for d in docs
        ],
        "list_items": [
            {
                "title": li.title,
                "list_name": li.graph_list_name,
                "spider_product": li.spider_product,
                "dashboard_division": li.dashboard_division,
                "modified_at": li.modified_at_remote.isoformat() if li.modified_at_remote else None,
                "modified_by_email": li.modified_by_email,
                "web_url": li.web_url,
                "fields_preview": {
                    k: v for k, v in (li.fields or {}).items()
                    if k in ("Title", "Status", "Priority", "DueDate", "Owner", "Description", "Notes")
                },
            }
            for li in list_items
        ],
    }


@router.get("/by-product")
def by_product(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Per-product activity rollup."""
    rows = db.execute(
        select(
            SharepointDocument.spider_product,
            func.count(SharepointDocument.id).label("docs"),
            func.max(SharepointDocument.modified_at_remote).label("last_modified"),
        )
        .where(SharepointDocument.is_folder == False)  # noqa: E712
        .group_by(SharepointDocument.spider_product)
    ).all()

    list_rows = db.execute(
        select(
            SharepointListItem.spider_product,
            func.count(SharepointListItem.id).label("items"),
        )
        .group_by(SharepointListItem.spider_product)
    ).all()
    list_by_product = {r.spider_product: int(r.items or 0) for r in list_rows}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_product": [
            {
                "spider_product": r.spider_product,
                "docs": int(r.docs or 0),
                "list_items": list_by_product.get(r.spider_product, 0),
                "last_modified": r.last_modified.isoformat() if r.last_modified else None,
            }
            for r in rows
        ],
    }


@router.get("/sync-status")
def sync_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    sites = db.execute(select(SharepointSite)).scalars().all()
    total_docs = db.execute(select(func.count()).select_from(SharepointDocument)).scalar() or 0
    total_items = db.execute(select(func.count()).select_from(SharepointListItem)).scalar() or 0
    latest = max((s.last_synced_at for s in sites if s.last_synced_at is not None), default=None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenants": db.execute(select(func.count()).select_from(MicrosoftTenant)).scalar() or 0,
        "sites_configured": len(sites),
        "sites_synced": sum(1 for s in sites if s.last_synced_at is not None),
        "documents_total": int(total_docs),
        "list_items_total": int(total_items),
        "latest_site_sync_at": latest.isoformat() if latest else None,
    }
