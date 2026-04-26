"""Canonical source-of-truth resolver for SharePoint-derived data.

For each ``(data_type, spider_product, dashboard_division)`` triple,
resolve the file that should be the source of truth. Order:

1. Human override pinned in ``sharepoint_canonical_sources`` always wins
2. Otherwise auto-pick from active (non-archived) docs of the right
   semantic type, sorted by parsed doc_date desc, then revision_letter
   desc, then modified_at_remote desc.

Joseph (admin) and per-page owners can pin/unpin via
``set_canonical_override(...)``. Auto-picks are written back to the
table so the API can return the same shape for both — the
``auto_chosen`` flag tells the UI whether to show the override pencil
in the "auto" or "pinned" state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, desc, nulls_last
from sqlalchemy.orm import Session

from app.models import SharepointCanonicalSource, SharepointDocument


# Semantic types that count as a candidate for each data_type the
# dashboard cares about. The order in the tuple is preference rank.
DATA_TYPE_TO_SEMANTICS: dict[str, tuple[str, ...]] = {
    "cogs":         ("cbom", "bom", "price_list"),
    "bom":          ("cbom", "bom"),
    "vendor_list":  ("vendor_doc", "price_list", "cbom"),
    "design_spec":  ("tech_pack", "drawing", "design_doc"),
    "drawing":      ("drawing", "tech_pack"),
}


def _candidate_query(db: Session, data_type: str, spider_product: Optional[str], dashboard_division: Optional[str]):
    semantics = DATA_TYPE_TO_SEMANTICS.get(data_type, (data_type,))
    q = (
        select(SharepointDocument)
        .where(
            SharepointDocument.is_folder == False,  # noqa: E712
            SharepointDocument.archive_status == "active",
            SharepointDocument.semantic_type.in_(semantics),
        )
    )
    if spider_product:
        q = q.where(SharepointDocument.spider_product == spider_product)
    if dashboard_division:
        q = q.where(SharepointDocument.dashboard_division == dashboard_division)
    # Heuristic ordering: docs with parsed doc_date sort first, then
    # revision letter (Z > A is "more recent rev"), then modified time.
    q = q.order_by(
        desc(SharepointDocument.parsed_metadata["doc_date"].as_string()).nulls_last() if False  # placeholder
        else desc(SharepointDocument.modified_at_remote).nulls_last()
    )
    return q


def _pick_best(candidates: list[SharepointDocument]) -> Optional[SharepointDocument]:
    """Pick the most-current candidate. Sorts by:
        (1) parsed_metadata.doc_date  (newest first; missing sorts last)
        (2) parsed_metadata.revision_letter (Z > A)
        (3) modified_at_remote (newest first)
    """
    if not candidates:
        return None

    def key(d: SharepointDocument):
        meta = d.parsed_metadata or {}
        return (
            meta.get("doc_date") or "",
            meta.get("revision_letter") or "",
            (d.modified_at_remote or datetime.min.replace(tzinfo=timezone.utc)).isoformat(),
        )

    return sorted(candidates, key=key, reverse=True)[0]


def resolve_canonical(
    db: Session,
    *,
    data_type: str,
    spider_product: Optional[str],
    dashboard_division: Optional[str],
    auto_persist: bool = True,
) -> Optional[SharepointDocument]:
    """Return the canonical document for the scope. Honors human
    override; otherwise auto-picks. If ``auto_persist`` is True, the
    auto-pick is written back so the override UI has a row to point at.
    """
    # 1. Human override?
    pinned = db.execute(
        select(SharepointCanonicalSource).where(
            SharepointCanonicalSource.data_type == data_type,
            SharepointCanonicalSource.spider_product.is_(spider_product) if spider_product is None else SharepointCanonicalSource.spider_product == spider_product,
            SharepointCanonicalSource.dashboard_division.is_(dashboard_division) if dashboard_division is None else SharepointCanonicalSource.dashboard_division == dashboard_division,
        )
    ).scalar_one_or_none()
    if pinned and not pinned.auto_chosen and pinned.document_id:
        doc = db.get(SharepointDocument, pinned.document_id)
        if doc:
            return doc

    # 2. Auto pick
    candidates = db.execute(_candidate_query(db, data_type, spider_product, dashboard_division)).scalars().all()
    chosen = _pick_best(list(candidates))

    if auto_persist:
        if pinned is None:
            db.add(
                SharepointCanonicalSource(
                    data_type=data_type,
                    spider_product=spider_product,
                    dashboard_division=dashboard_division,
                    document_id=chosen.id if chosen else None,
                    auto_chosen=True,
                )
            )
        elif pinned.auto_chosen:
            # auto picks update freely — they always reflect latest computation
            pinned.document_id = chosen.id if chosen else None
            pinned.updated_at = datetime.now(timezone.utc)
        db.commit()

    return chosen


def set_canonical_override(
    db: Session,
    *,
    data_type: str,
    spider_product: Optional[str],
    dashboard_division: Optional[str],
    document_id: Optional[int],
    user: str,
    note: Optional[str] = None,
) -> SharepointCanonicalSource:
    """Pin a specific file as the source of truth for this scope.
    Pass ``document_id=None`` to revert to auto."""
    row = db.execute(
        select(SharepointCanonicalSource).where(
            SharepointCanonicalSource.data_type == data_type,
            SharepointCanonicalSource.spider_product.is_(spider_product) if spider_product is None else SharepointCanonicalSource.spider_product == spider_product,
            SharepointCanonicalSource.dashboard_division.is_(dashboard_division) if dashboard_division is None else SharepointCanonicalSource.dashboard_division == dashboard_division,
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None:
        row = SharepointCanonicalSource(
            data_type=data_type,
            spider_product=spider_product,
            dashboard_division=dashboard_division,
        )
        db.add(row)

    row.document_id = document_id
    if document_id is None:
        # Reverting to auto
        row.auto_chosen = True
        row.override_user = None
        row.override_note = None
        row.override_at = None
    else:
        row.auto_chosen = False
        row.override_user = user
        row.override_note = note
        row.override_at = now
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def doc_summary_dict(doc: Optional[SharepointDocument]) -> Optional[dict[str, Any]]:
    """Tight dict shape for API responses. Includes the click-through
    URL so the dashboard can render it inline."""
    if doc is None:
        return None
    meta = doc.parsed_metadata or {}
    return {
        "id": doc.id,
        "name": doc.name,
        "path": doc.path,
        "web_url": doc.web_url,
        "spider_product": doc.spider_product,
        "dashboard_division": doc.dashboard_division,
        "top_level_folder": doc.top_level_folder,
        "modified_at": doc.modified_at_remote.isoformat() if doc.modified_at_remote else None,
        "modified_by_email": doc.modified_by_email,
        "semantic_type": doc.semantic_type,
        "archive_status": doc.archive_status,
        "sku_code": meta.get("sku_code"),
        "revision_letter": meta.get("revision_letter"),
        "doc_date": meta.get("doc_date"),
        "assembly_name": meta.get("assembly_name"),
    }
