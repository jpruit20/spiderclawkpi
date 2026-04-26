"""SharePoint Excel-BOM extractor.

Downloads a sharepoint_documents row's bytes via Graph and parses the
workbook into ``sharepoint_bom_lines``.

Spider's BOMs are remarkably consistent — most live in workbooks
named like ``ATL-SPG-00163 - Main Assembly_Rev M  BOM 20250916.xlsx``
with one or more sheets that have human-readable column headers
("Part Number", "Description", "Vendor", "Qty", "Unit Cost"). The
extractor:

1. Downloads bytes via Graph API (``GET /sites/{id}/drive/items/{id}/content``)
2. Loads the workbook (xlsx via openpyxl, xls via xlrd)
3. Walks each sheet looking for a header row — the row that contains
   at least 2 of {part, description, vendor, qty, cost, price}
4. Treats subsequent non-empty rows as part lines
5. Best-effort parses qty/cost into numbers (strips $, ¥, €, commas)
6. Writes one ``SharepointBomLine`` per part + a
   ``SharepointExtractionRun`` row capturing success/fail/lines

The parser is defensive: a single bad row never poisons the rest;
the extraction run catches the exception and stores a short error
message. Re-running on the same doc replaces previous lines (DELETE
THEN INSERT) so we always have the latest extraction.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

import requests
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ingestion.connectors.sharepoint import _get_app_token  # reuse cached token
from app.models import SharepointBomLine, SharepointDocument, SharepointExtractionRun


logger = logging.getLogger(__name__)
PARSER_VERSION = "bom-v1.0.0"


# ── Header detection ────────────────────────────────────────────────


HEADER_KEYS = {
    "part_number": ("part", "p/n", "pn", "item", "sku", "ref"),
    "description": ("description", "desc", "name", "item description"),
    "vendor_name": ("vendor", "supplier", "manufacturer", "mfg", "source"),
    "qty": ("qty", "quantity", "qnty", "count"),
    "unit": ("unit", "uom", "u/m"),
    "unit_cost_usd": ("unit cost", "unit price", "cost ea", "price each", "unit_cost"),
    "total_cost_usd": ("total cost", "extended cost", "total price", "ext price", "ext. cost"),
    "currency_raw": ("currency", "ccy", "curr"),
}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _build_header_map(row: list[Any]) -> dict[str, int]:
    """Given a row of cell values, return ``{semantic_key → col_index}``
    for every header we recognize. Empty if fewer than 2 BOM-ish
    headers are matched."""
    out: dict[str, int] = {}
    cells = [_norm(c) for c in row]
    for key, needles in HEADER_KEYS.items():
        for idx, cell in enumerate(cells):
            if not cell:
                continue
            if any(needle in cell for needle in needles):
                out.setdefault(key, idx)
                break
    return out


def _looks_like_bom_header(row: list[Any]) -> bool:
    h = _build_header_map(row)
    # Need a part column AND at least one of {qty, cost} or vendor
    return ("part_number" in h) and bool({"qty", "unit_cost_usd", "total_cost_usd", "vendor_name"} & set(h))


# ── Number coercion ─────────────────────────────────────────────────

_CURRENCY_RE = re.compile(r"[$£€¥₹]")
_NUMBER_RE = re.compile(r"^-?[\d,]*\.?\d+$")


def _coerce_number(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    s = str(v).strip()
    if not s:
        return None
    s = _CURRENCY_RE.sub("", s).replace(",", "").strip()
    if not _NUMBER_RE.match(s):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _detect_currency(*values: Any) -> Optional[str]:
    for v in values:
        if v is None:
            continue
        s = str(v)
        if "$" in s:
            return "USD"
        if "¥" in s:
            return "CNY"
        if "€" in s:
            return "EUR"
        if "£" in s:
            return "GBP"
    return None


# ── Workbook loaders ────────────────────────────────────────────────


def _iter_xlsx_rows(data: bytes) -> Iterable[tuple[str, list[list[Any]]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
        yield ws.title, rows
    wb.close()


def _iter_xls_rows(data: bytes) -> Iterable[tuple[str, list[list[Any]]]]:
    import xlrd

    wb = xlrd.open_workbook(file_contents=data)
    for sheet in wb.sheets():
        rows = [sheet.row_values(r) for r in range(sheet.nrows)]
        yield sheet.name, rows


# ── Graph file download ─────────────────────────────────────────────


def _download_doc_bytes(doc: SharepointDocument, *, timeout: int = 60) -> bytes:
    """Pull file bytes from Microsoft Graph using the stored item id."""
    token = _get_app_token(doc.tenant_id)
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{doc.graph_site_id}"
        f"/drives/{doc.graph_drive_id}/items/{doc.graph_item_id}/content"
    )
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.content


# ── Public API ──────────────────────────────────────────────────────


def extract_bom_for_document(db: Session, doc: SharepointDocument, *, max_rows_per_sheet: int = 5000) -> dict[str, Any]:
    """Download + parse one document. Replaces existing lines on success.
    Always writes a ``SharepointExtractionRun`` row.

    Returns ``{status, lines_extracted, error}`` for caller diagnostics.
    """
    run = SharepointExtractionRun(
        document_id=doc.id,
        kind="bom",
        status="running",
        parser_version=PARSER_VERSION,
        lines_extracted=0,
    )
    db.add(run)
    db.flush()
    try:
        data = _download_doc_bytes(doc)
        if doc.mime_type and "spreadsheetml.sheet" in (doc.mime_type or ""):
            sheets = _iter_xlsx_rows(data)
        elif doc.name and doc.name.lower().endswith(".xls"):
            sheets = _iter_xls_rows(data)
        elif doc.name and doc.name.lower().endswith(".xlsx"):
            sheets = _iter_xlsx_rows(data)
        else:
            raise ValueError(f"unsupported mime/extension: {doc.mime_type} / {doc.name}")

        # Replace any prior extraction for this doc — single source of
        # truth is the latest run.
        db.execute(delete(SharepointBomLine).where(SharepointBomLine.document_id == doc.id))

        total_lines = 0
        for sheet_name, rows in sheets:
            if not rows:
                continue
            # Find the header row in the first 20 rows
            header_idx = None
            header_map: dict[str, int] = {}
            for i, row in enumerate(rows[:20]):
                if _looks_like_bom_header(row):
                    header_idx = i
                    header_map = _build_header_map(row)
                    break
            if header_idx is None:
                continue

            # Walk parts
            sheet_lines = 0
            for ridx, row in enumerate(rows[header_idx + 1 : header_idx + 1 + max_rows_per_sheet], start=header_idx + 2):
                if all(c is None or _norm(c) == "" for c in row):
                    # blank — likely sheet boundary, but BOMs sometimes have spacers; skip and continue
                    continue
                line_no = sheet_lines + 1
                pn = _norm(row[header_map["part_number"]]) if "part_number" in header_map and header_map["part_number"] < len(row) else ""
                if not pn:
                    continue
                # Skip "subtotal", "total", "section header" rows
                if pn.lower() in {"total", "subtotal", "grand total"} or pn.startswith("section "):
                    continue
                desc = row[header_map["description"]] if "description" in header_map and header_map["description"] < len(row) else None
                vendor = row[header_map["vendor_name"]] if "vendor_name" in header_map and header_map["vendor_name"] < len(row) else None
                qty = _coerce_number(row[header_map["qty"]]) if "qty" in header_map and header_map["qty"] < len(row) else None
                unit = row[header_map["unit"]] if "unit" in header_map and header_map["unit"] < len(row) else None
                unit_cost = _coerce_number(row[header_map["unit_cost_usd"]]) if "unit_cost_usd" in header_map and header_map["unit_cost_usd"] < len(row) else None
                total_cost = _coerce_number(row[header_map["total_cost_usd"]]) if "total_cost_usd" in header_map and header_map["total_cost_usd"] < len(row) else None
                ccy_raw = (
                    str(row[header_map["currency_raw"]])[:8]
                    if "currency_raw" in header_map and header_map["currency_raw"] < len(row) and row[header_map["currency_raw"]]
                    else _detect_currency(
                        row[header_map["unit_cost_usd"]] if "unit_cost_usd" in header_map and header_map["unit_cost_usd"] < len(row) else None,
                        row[header_map["total_cost_usd"]] if "total_cost_usd" in header_map and header_map["total_cost_usd"] < len(row) else None,
                    )
                )
                # If qty + unit_cost present but no total → derive
                if total_cost is None and qty is not None and unit_cost is not None:
                    total_cost = qty * unit_cost

                db.add(
                    SharepointBomLine(
                        document_id=doc.id,
                        line_no=line_no,
                        part_number=pn[:255],
                        description=str(desc)[:8192] if desc else None,
                        vendor_name=str(vendor)[:255] if vendor else None,
                        qty=qty,
                        unit=str(unit)[:32] if unit else None,
                        unit_cost_usd=unit_cost,
                        total_cost_usd=total_cost,
                        currency_raw=ccy_raw,
                        raw_row_json={
                            "sheet": sheet_name,
                            "row_index": ridx,
                            "values": [str(c) if c is not None else None for c in row][:30],
                        },
                    )
                )
                sheet_lines += 1
            total_lines += sheet_lines

        run.status = "success"
        run.lines_extracted = total_lines
        run.ran_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "success", "lines_extracted": total_lines, "error": None}
    except Exception as exc:
        db.rollback()
        # Re-add the run row outside the failed txn
        try:
            db.add(
                SharepointExtractionRun(
                    document_id=doc.id,
                    kind="bom",
                    status="failed",
                    parser_version=PARSER_VERSION,
                    lines_extracted=0,
                    error_message=str(exc)[:1024],
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        logger.exception("BOM extraction failed for doc %s (%s)", doc.id, doc.name)
        return {"status": "failed", "lines_extracted": 0, "error": str(exc)[:200]}


def extract_all_bom_documents(db: Session, *, force: bool = False, limit: Optional[int] = None) -> dict[str, int]:
    """Walk every active BOM/CBOM/price_list spreadsheet and run the
    extractor. Skips docs that already have a successful run unless
    ``force=True``."""
    q = (
        select(SharepointDocument)
        .where(
            SharepointDocument.is_folder == False,  # noqa: E712
            SharepointDocument.semantic_type.in_(("bom", "cbom", "price_list")),
            SharepointDocument.archive_status == "active",
        )
        .order_by(SharepointDocument.modified_at_remote.desc().nulls_last())
    )
    if limit:
        q = q.limit(limit)
    docs = db.execute(q).scalars().all()

    counts = {"seen": 0, "success": 0, "failed": 0, "skipped": 0, "lines": 0}
    for doc in docs:
        counts["seen"] += 1
        if not force:
            last = db.execute(
                select(SharepointExtractionRun)
                .where(SharepointExtractionRun.document_id == doc.id, SharepointExtractionRun.kind == "bom")
                .order_by(SharepointExtractionRun.ran_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if last and last.status == "success":
                counts["skipped"] += 1
                continue
        result = extract_bom_for_document(db, doc)
        if result["status"] == "success":
            counts["success"] += 1
            counts["lines"] += result["lines_extracted"]
        else:
            counts["failed"] += 1
    return counts
