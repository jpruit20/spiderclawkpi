"""SharePoint document classifier.

Pure-Python, IO-free heuristics that turn the 12k+ raw file mirror
into something queryable:

- ``classify_archive_status(path)`` → ``active`` | ``archived``
  Looks for ``Archive``, ``ARCHIVE``, ``Archive CAD``, ``older``,
  ``deprecated`` segments in the path.

- ``classify_semantic_type(name, mime)`` → one of:
  ``cbom``, ``bom``, ``price_list``, ``tech_pack``, ``drawing``,
  ``cad``, ``design_doc``, ``vendor_doc``, ``image``, ``video``,
  ``presentation``, ``spreadsheet``, ``pdf``, ``other``.

- ``parse_filename_metadata(name)`` →
  ``{"sku_code", "revision_letter", "doc_date", "assembly_name"}``.
  Spider's filename convention is highly consistent
  (``ATL-SPG-00163 - Main Assembly_Rev M  BOM 20250916.xlsx``),
  so a regex set extracts the parts we want without false positives.

The service has no side effects; ``classify_documents()`` is the
batch caller that walks the table and writes the columns. It's safe
to run repeatedly — already-classified rows that haven't changed
get short-circuited via ``classified_at`` vs ``modified_at_remote``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import SharepointDocument


CLASSIFIER_VERSION = "v1.0.0"


# ── Archive classification ──────────────────────────────────────────

_ARCHIVE_PATH_RE = re.compile(
    r"(?:^|/)(archive|ARCHIVE|Archive|deprecated|DEPRECATED|Old|OLD|older|olds?(?=/|$))(?:/|$)",
)


def classify_archive_status(path: Optional[str]) -> str:
    """``active`` | ``archived``. Path-based: if ANY segment is an
    archive marker, the file is archived."""
    if not path:
        return "active"
    if _ARCHIVE_PATH_RE.search(path):
        return "archived"
    return "active"


# ── Semantic type classification ────────────────────────────────────

# Order matters — more specific patterns first.
_SEMANTIC_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bCBOM\b|\bC[\s_-]?BOM\b", re.IGNORECASE), "cbom"),
    (re.compile(r"\bBOM\b", re.IGNORECASE), "bom"),
    (re.compile(r"price[\s_-]?list", re.IGNORECASE), "price_list"),
    (re.compile(r"vendor[\s_-]?(list|pl|directory)?|supplier", re.IGNORECASE), "vendor_doc"),
    (re.compile(r"tech[\s_-]?pack|techpack", re.IGNORECASE), "tech_pack"),
    (re.compile(r"\bECR\b|engineering[\s_-]?change", re.IGNORECASE), "ecr"),
    (re.compile(r"\bDFM\b|design[\s_-]?for[\s_-]?manufactur", re.IGNORECASE), "dfm"),
    (re.compile(r"\bQA\b|quality[\s_-]?(plan|spec|insp)", re.IGNORECASE), "qa_doc"),
    (re.compile(r"drawing|\bdwg\b|technical[\s_-]?draw", re.IGNORECASE), "drawing"),
    (re.compile(r"assembly[\s_-]?(instruction|guide|manual)|user[\s_-]?manual|owner.*manual", re.IGNORECASE), "manual"),
    (re.compile(r"test[\s_-]?(report|data|results?)|validation", re.IGNORECASE), "test_report"),
    (re.compile(r"firmware|\bfw[\s_-]?[0-9]", re.IGNORECASE), "firmware_doc"),
    (re.compile(r"packag(e|ing)|carton[\s_-]?spec|epp[\s_-]?box", re.IGNORECASE), "packaging"),
    (re.compile(r"label|warning|certif", re.IGNORECASE), "label_or_cert"),
]

# CAD / drawing extensions
_CAD_EXTS = {"step", "stp", "iges", "igs", "stl", "obj", "dwg", "dxf", "x_t", "sldprt", "sldasm", "ipt", "iam", "f3d", "3mf", "prt"}

# Image / video / presentation by mime
_MIME_BUCKETS = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/bmp": "image",
    "image/gif": "image",
    "image/tiff": "image",
    "image/webp": "image",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/x-msvideo": "video",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
    "application/vnd.ms-powerpoint": "presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word_doc",
    "application/msword": "word_doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "spreadsheet",
    "application/vnd.ms-excel": "spreadsheet",
    "application/postscript": "vector_art",
}


def classify_semantic_type(name: Optional[str], mime: Optional[str]) -> str:
    """Best-effort doc type. Filename rules win over mime — a BOM
    still classifies as ``bom`` even though its mime is just
    ``spreadsheet``."""
    name = (name or "").strip()
    if not name:
        return "other"

    # 1. Filename-substring rules (specific intent overrides generic mime)
    for pattern, label in _SEMANTIC_RULES:
        if pattern.search(name):
            # Spreadsheets that ALSO match BOM/Tech Pack stay typed as such
            return label

    # 2. CAD by extension (case-insensitive)
    base, _, ext = name.rpartition(".")
    if base and ext.lower() in _CAD_EXTS:
        return "cad"

    # 3. Mime fallback
    if mime and mime in _MIME_BUCKETS:
        return _MIME_BUCKETS[mime]

    return "other"


# ── Filename metadata parser ────────────────────────────────────────

# Capture: SKU like ATL-SPG-00163, ATL-APG-00116, ATL-00177
_SKU_RE = re.compile(r"\b(ATL[-_](?:[A-Z]{1,4}[-_])?[0-9]{4,6})\b")
# Capture: Rev letter (Rev A, _Rev B, RevC, Rev_M)
_REV_RE = re.compile(r"\bRev[\s_]?([A-Z]\d?)\b", re.IGNORECASE)
# Capture: trailing date YYYYMMDD (preceded by space/_/-) — last match wins
_DATE_RE = re.compile(r"(?:^|[\s_\-])(20\d{6})(?:[\s_\-.]|$)")
# Optional 6-digit YYMMDD form ("CBOM-250523")
_DATE_RE_SHORT = re.compile(r"(?:^|[\s_\-])(2[0-9])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(?:[\s_\-.]|$)")
# Capture: assembly name — between SKU+dash and the _Rev marker
_ASSEMBLY_AFTER_SKU_RE = re.compile(
    r"ATL[-_](?:[A-Z]{1,4}[-_])?[0-9]{4,6}\s*[-_\s]+(.+?)(?=[_\s]Rev[\s_]?[A-Z]\d?|[_\s]\d{6,8}|[_\s]+(BOM|CBOM)\b|\.[a-z0-9]+$)",
    re.IGNORECASE,
)


def parse_filename_metadata(name: Optional[str]) -> dict[str, Any]:
    """Return ``{sku_code, revision_letter, doc_date, assembly_name}``.
    Missing fields just don't appear in the dict — callers can ``.get()``
    safely."""
    out: dict[str, Any] = {}
    if not name:
        return out

    # Drop extension early
    base = name.rsplit(".", 1)[0]

    if m := _SKU_RE.search(base):
        out["sku_code"] = m.group(1).upper().replace("_", "-")

    if m := _REV_RE.search(base):
        out["revision_letter"] = m.group(1).upper()

    # Prefer YYYYMMDD; fall back to YYMMDD if present
    if m := _DATE_RE.search(base):
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            out["doc_date"] = d.isoformat()
        except ValueError:
            pass
    elif m := _DATE_RE_SHORT.search(base):
        try:
            yy, mm, dd = m.group(1), m.group(2), m.group(3)
            d = datetime.strptime(f"20{yy}{mm}{dd}", "%Y%m%d").date()
            out["doc_date"] = d.isoformat()
        except ValueError:
            pass

    if m := _ASSEMBLY_AFTER_SKU_RE.search(base):
        assembly = m.group(1).strip(" -_")
        # Strip trailing decorations (multiple spaces, "Rev", etc.)
        assembly = re.sub(r"\s+", " ", assembly)
        if assembly and len(assembly) <= 255:
            out["assembly_name"] = assembly

    return out


# ── Batch runner ────────────────────────────────────────────────────


def classify_documents(db: Session, *, force: bool = False, limit: Optional[int] = None) -> dict[str, int]:
    """Walk every (non-folder) sharepoint_document and write classification
    columns. Idempotent — ``classified_at`` short-circuits unchanged rows
    unless ``force=True``."""
    q = (
        select(SharepointDocument)
        .where(SharepointDocument.is_folder == False)  # noqa: E712
    )
    if not force:
        q = q.where(SharepointDocument.classified_at.is_(None))
    if limit:
        q = q.limit(limit)

    docs = db.execute(q).scalars().all()
    counts = {"seen": 0, "updated": 0, "skipped": 0}
    now = datetime.now(timezone.utc)
    for doc in docs:
        counts["seen"] += 1
        archive = classify_archive_status(doc.path)
        sem = classify_semantic_type(doc.name, doc.mime_type)
        meta = parse_filename_metadata(doc.name)
        # Skip if all values match (true no-op)
        if (
            doc.archive_status == archive
            and doc.semantic_type == sem
            and (doc.parsed_metadata or {}) == meta
            and doc.classified_at is not None
            and not force
        ):
            counts["skipped"] += 1
            continue
        db.execute(
            update(SharepointDocument)
            .where(SharepointDocument.id == doc.id)
            .values(
                archive_status=archive,
                semantic_type=sem,
                parsed_metadata=meta,
                classified_at=now,
            )
        )
        counts["updated"] += 1
    db.commit()
    return counts
