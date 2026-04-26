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

from pydantic import BaseModel

from app.api.deps import db_session, require_auth
from app.models import (
    MicrosoftTenant,
    SharepointBomLine,
    SharepointCanonicalSource,
    SharepointDocument,
    SharepointExtractionRun,
    SharepointListItem,
    SharepointSite,
)
from app.services.sharepoint_canonical import (
    DATA_TYPE_TO_SEMANTICS,
    doc_summary_dict,
    resolve_canonical,
    set_canonical_override,
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


# ── Intelligence layer ──────────────────────────────────────────────


@router.get("/intelligence/active-archive")
def active_archive_split(
    division: Optional[str] = Query(None),
    spider_product: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Active vs archived counts plus per-semantic-type breakdown.
    Powers the "12,237 files — 11,621 active / 616 archived" header
    on division Sharepoint cards."""
    base = select(SharepointDocument).where(SharepointDocument.is_folder == False)  # noqa: E712
    if division:
        base = base.where(SharepointDocument.dashboard_division == division)
    if spider_product:
        base = base.where(SharepointDocument.spider_product == spider_product)

    by_status_q = (
        select(SharepointDocument.archive_status, func.count(SharepointDocument.id))
        .where(SharepointDocument.is_folder == False)  # noqa: E712
    )
    by_type_q = (
        select(SharepointDocument.semantic_type, SharepointDocument.archive_status, func.count(SharepointDocument.id))
        .where(SharepointDocument.is_folder == False)  # noqa: E712
    )
    if division:
        by_status_q = by_status_q.where(SharepointDocument.dashboard_division == division)
        by_type_q = by_type_q.where(SharepointDocument.dashboard_division == division)
    if spider_product:
        by_status_q = by_status_q.where(SharepointDocument.spider_product == spider_product)
        by_type_q = by_type_q.where(SharepointDocument.spider_product == spider_product)

    by_status = {row[0] or "unknown": int(row[1]) for row in db.execute(by_status_q.group_by(SharepointDocument.archive_status)).all()}
    type_rows = db.execute(by_type_q.group_by(SharepointDocument.semantic_type, SharepointDocument.archive_status)).all()
    by_type: dict[str, dict[str, int]] = {}
    for sem, status, n in type_rows:
        b = by_type.setdefault(sem or "other", {"active": 0, "archived": 0, "total": 0})
        b[status or "active"] = b.get(status or "active", 0) + int(n)
        b["total"] = b.get("total", 0) + int(n)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {"division": division, "spider_product": spider_product},
        "by_status": by_status,
        "by_semantic_type": [
            {"semantic_type": k, **v}
            for k, v in sorted(by_type.items(), key=lambda kv: -kv[1].get("total", 0))
        ],
    }


@router.get("/intelligence/cogs")
def cogs_rollup(
    spider_product: str = Query(..., description="Huntsman / Giant Huntsman / Venom / Webcraft / Giant Webcraft"),
    division: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """COGS rollup for a product. Resolves the canonical BOM/CBOM
    file for the product, then sums extracted line items. Returns
    the source-of-truth file with a click-through URL plus an
    indication of whether it was auto-picked or admin-pinned."""
    canonical = resolve_canonical(
        db,
        data_type="cogs",
        spider_product=spider_product,
        dashboard_division=division,
    )
    pinned_row = db.execute(
        select(SharepointCanonicalSource).where(
            SharepointCanonicalSource.data_type == "cogs",
            SharepointCanonicalSource.spider_product == spider_product,
            SharepointCanonicalSource.dashboard_division.is_(division) if division is None else SharepointCanonicalSource.dashboard_division == division,
        )
    ).scalar_one_or_none()

    lines: list[dict[str, Any]] = []
    total_cost: float = 0.0
    line_count = 0
    vendor_breakdown: dict[str, dict[str, float]] = {}
    if canonical is not None:
        rows = db.execute(
            select(SharepointBomLine)
            .where(SharepointBomLine.document_id == canonical.id)
            .order_by(SharepointBomLine.line_no.asc().nulls_last())
        ).scalars().all()
        for r in rows:
            line_count += 1
            total = float(r.total_cost_usd or 0)
            total_cost += total
            if r.vendor_name:
                vb = vendor_breakdown.setdefault(r.vendor_name, {"cost": 0.0, "lines": 0})
                vb["cost"] += total
                vb["lines"] += 1
            lines.append({
                "line_no": r.line_no,
                "part_number": r.part_number,
                "description": r.description,
                "vendor_name": r.vendor_name,
                "qty": float(r.qty) if r.qty is not None else None,
                "unit": r.unit,
                "unit_cost_usd": float(r.unit_cost_usd) if r.unit_cost_usd is not None else None,
                "total_cost_usd": total if r.total_cost_usd is not None else None,
                "currency_raw": r.currency_raw,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spider_product": spider_product,
        "dashboard_division": division,
        "source_file": doc_summary_dict(canonical),
        "source_pin_state": {
            "auto_chosen": pinned_row.auto_chosen if pinned_row else True,
            "override_user": pinned_row.override_user if pinned_row else None,
            "override_at": pinned_row.override_at.isoformat() if pinned_row and pinned_row.override_at else None,
            "override_note": pinned_row.override_note if pinned_row else None,
        },
        "rollup": {
            "total_cost_usd": round(total_cost, 2),
            "line_count": line_count,
            "vendor_count": len(vendor_breakdown),
            "vendors": [
                {"vendor": v, **{k: round(val, 2) if isinstance(val, float) else val for k, val in stats.items()}}
                for v, stats in sorted(vendor_breakdown.items(), key=lambda kv: -kv[1]["cost"])
            ],
        },
        "lines": lines,
    }


@router.get("/intelligence/vendors")
def vendor_directory(
    spider_product: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Cross-BOM vendor list — every vendor mentioned in any extracted
    BOM line, with line counts + total cost across products. Powers the
    "who do we buy from" intelligence card."""
    q = (
        select(
            SharepointBomLine.vendor_name,
            func.count(SharepointBomLine.id).label("lines"),
            func.sum(SharepointBomLine.total_cost_usd).label("cost"),
            func.count(func.distinct(SharepointBomLine.document_id)).label("docs"),
        )
        .where(SharepointBomLine.vendor_name.is_not(None))
        .group_by(SharepointBomLine.vendor_name)
        .order_by(func.count(SharepointBomLine.id).desc())
    )
    if spider_product:
        q = (
            q.join(SharepointDocument, SharepointDocument.id == SharepointBomLine.document_id)
            .where(SharepointDocument.spider_product == spider_product)
        )
    rows = db.execute(q).all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spider_product": spider_product,
        "vendors": [
            {
                "vendor": r.vendor_name,
                "line_count": int(r.lines or 0),
                "doc_count": int(r.docs or 0),
                "total_cost_usd": float(r.cost or 0),
            }
            for r in rows
        ],
    }


@router.get("/intelligence/revisions")
def revision_history(
    spider_product: str = Query(...),
    semantic_type: str = Query("bom"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Revision history of a doc family — all the BOMs for ``Main
    Assembly`` of ``Huntsman``, ordered newest-first. Helps page
    owners verify the canonical pick is the right one."""
    rows = db.execute(
        select(SharepointDocument)
        .where(
            SharepointDocument.is_folder == False,  # noqa: E712
            SharepointDocument.spider_product == spider_product,
            SharepointDocument.semantic_type == semantic_type,
        )
        .order_by(SharepointDocument.modified_at_remote.desc().nulls_last())
        .limit(80)
    ).scalars().all()
    by_assembly: dict[str, list[dict[str, Any]]] = {}
    for d in rows:
        meta = d.parsed_metadata or {}
        key = meta.get("assembly_name") or "(unknown assembly)"
        by_assembly.setdefault(key, []).append(doc_summary_dict(d))  # type: ignore[arg-type]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spider_product": spider_product,
        "semantic_type": semantic_type,
        "by_assembly": [
            {"assembly_name": k, "revisions": v}
            for k, v in sorted(by_assembly.items())
        ],
    }


class CanonicalOverrideIn(BaseModel):
    data_type: str
    spider_product: Optional[str] = None
    dashboard_division: Optional[str] = None
    document_id: Optional[int] = None  # null reverts to auto
    note: Optional[str] = None


@router.post("/canonical-sources", dependencies=[Depends(require_auth)])
def upsert_canonical_override(
    payload: CanonicalOverrideIn,
    db: Session = Depends(db_session),
    user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Pin a specific file as the source of truth for a (data_type,
    product, division) scope, or revert to auto by passing
    ``document_id=null``. Joseph and per-page owners hit this when
    editing the source link on a card."""
    user_email = (user or {}).get("email") if isinstance(user, dict) else "unknown"
    row = set_canonical_override(
        db,
        data_type=payload.data_type,
        spider_product=payload.spider_product,
        dashboard_division=payload.dashboard_division,
        document_id=payload.document_id,
        user=user_email or "unknown",
        note=payload.note,
    )
    doc = db.get(SharepointDocument, row.document_id) if row.document_id else None
    return {
        "status": "ok",
        "scope": {
            "data_type": row.data_type,
            "spider_product": row.spider_product,
            "dashboard_division": row.dashboard_division,
        },
        "auto_chosen": row.auto_chosen,
        "override_user": row.override_user,
        "override_at": row.override_at.isoformat() if row.override_at else None,
        "source_file": doc_summary_dict(doc),
    }


@router.get("/canonical-sources")
def list_canonical_sources(
    data_type: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Every pinned + auto-resolved canonical source. UI uses this to
    render the "manage sources of truth" admin table."""
    q = select(SharepointCanonicalSource)
    if data_type:
        q = q.where(SharepointCanonicalSource.data_type == data_type)
    rows = db.execute(q).scalars().all()
    out = []
    for r in rows:
        doc = db.get(SharepointDocument, r.document_id) if r.document_id else None
        out.append({
            "id": r.id,
            "data_type": r.data_type,
            "spider_product": r.spider_product,
            "dashboard_division": r.dashboard_division,
            "auto_chosen": r.auto_chosen,
            "override_user": r.override_user,
            "override_at": r.override_at.isoformat() if r.override_at else None,
            "override_note": r.override_note,
            "source_file": doc_summary_dict(doc),
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "supported_data_types": list(DATA_TYPE_TO_SEMANTICS.keys()),
        "rows": out,
    }


@router.get("/extraction-status")
def extraction_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Tells the dashboard how much of the corpus has been parsed.
    Powers the "127/200 BOMs extracted" chip on division cards."""
    bom_docs = db.execute(
        select(func.count())
        .select_from(SharepointDocument)
        .where(
            SharepointDocument.is_folder == False,  # noqa: E712
            SharepointDocument.semantic_type.in_(("bom", "cbom", "price_list")),
            SharepointDocument.archive_status == "active",
        )
    ).scalar() or 0
    successful = db.execute(
        select(func.count(func.distinct(SharepointExtractionRun.document_id)))
        .where(SharepointExtractionRun.kind == "bom", SharepointExtractionRun.status == "success")
    ).scalar() or 0
    failed = db.execute(
        select(func.count(func.distinct(SharepointExtractionRun.document_id)))
        .where(SharepointExtractionRun.kind == "bom", SharepointExtractionRun.status == "failed")
    ).scalar() or 0
    total_lines = db.execute(select(func.count()).select_from(SharepointBomLine)).scalar() or 0
    last_run = db.execute(
        select(func.max(SharepointExtractionRun.ran_at))
    ).scalar()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_bom_docs": int(bom_docs),
        "extracted_successfully": int(successful),
        "extraction_failures": int(failed),
        "bom_lines_total": int(total_lines),
        "last_extraction_at": last_run.isoformat() if last_run else None,
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
