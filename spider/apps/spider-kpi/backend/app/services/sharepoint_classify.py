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

import sqlalchemy as sa
from sqlalchemy import bindparam as sa_bindparam, select, update
from sqlalchemy.orm import Session

from app.models import SharepointDocument


CLASSIFIER_VERSION = "v1.2.0"  # broaden Spider keywords + Qifei doc-kind patterns (BL#/FAPIAO/API#/CTN/patent/quote/cad)


# ── Spider-relevance detection (vendor sites) ────────────────────────
#
# Kienco / Qifei / future vendor workspace sites have ``spider_product``
# left NULL at the ingest layer because the workspace contains both
# Spider-relevant docs and the vendor's own internal stuff. This
# classifier runs after the ingest and tags each document with
# ``spider_relevant`` (boolean) and ``detected_doc_kind`` (short tag)
# based on filename + path keyword matches.
#
# Why filename-only and not full-text: the vast majority of vendor
# documents put the relevant signal in the filename (vendors tend to
# be very explicit — "00163 Huntsman QA Inspection Report Apr 2026.pdf"
# is the typical pattern). PDF/Excel content extraction is available
# via app/services/sharepoint_content_extractor.py for cases where
# filenames are uninformative; we'll add it as a second pass if the
# filename pass misses too many docs in practice.

# Spider product / SKU / project-tag keywords. Case-insensitive match.
# Anything matching here flips spider_relevant=true.
_SPIDER_KEYWORDS_RE = re.compile(
    r"\b("
    # Brand mentions
    r"spider[ \-_]?grills?|spidergrills?|"
    # Product names — `huntman` is a vendor typo of `huntsman` we see
    # repeatedly in Qifei filenames; matching it broadens recall.
    r"huntsman|hunts?man|giant[ \-_]?huntsman|giant[ \-_]?hunts?man|"
    r"venom|webcraft|giant[ \-_]?webcraft|joehy|"
    # Joe-line products manufactured by Qifei before the IP transfer
    # (Kettle Joe and Pellet Joe → now SPG-branded; CN appearance
    # design + utility model patents reference these names).
    r"kettle[ \-_]?joe|pellet[ \-_]?joe|"
    # EH Oven is a Spider/Webcraft adjacent product Qifei makes parts for
    r"eh[ \-_]?oven|"
    # Common Spider SKU prefixes (SG-H-01, SG-GH-01, SG-22KC, SG-NL-HWC, etc)
    r"sg-[a-z0-9]{1,8}(?:-[a-z0-9]{1,8})*|"
    # AMW project numbers we know correspond to Spider products
    # (00116=Venom, 00163=Huntsman, 00171=Webcraft, 00176=Giant Huntsman,
    #  00177=Giant Webcraft, 00178=Spider Kettle Cart). Add new project
    #  numbers here as Spider expands its product line.
    r"00116|00163|00171|00176|00177|00178|"
    # SPG abbreviation Qifei uses on commercial invoices to AMW
    r"to[ \-_]?spg|spg[ \-_]?(?:venom|huntsman|hunts?man|kettle|webcraft)"
    r")\b",
    re.IGNORECASE,
)

# Map detected keyword → spider_product display value. First match wins.
# When multiple products are mentioned (e.g. a generic "Spider Grills
# packing list" PDF that names both Huntsman and Venom), we currently
# tag with the first-listed product; an upgrade path would be to
# detect multi-product docs and store all in parsed_metadata.
_SPIDER_PRODUCT_PATTERNS = [
    (re.compile(r"\bgiant[ \-_]?huntsman|sg-gh\b|00176\b", re.IGNORECASE), "Giant Huntsman"),
    (re.compile(r"\bgiant[ \-_]?webcraft|00177\b", re.IGNORECASE), "Giant Webcraft"),
    (re.compile(r"\bhuntsman|sg-h-01\b|00163\b", re.IGNORECASE), "Huntsman"),
    (re.compile(r"\bwebcraft|00171\b", re.IGNORECASE), "Webcraft"),
    (re.compile(r"\bvenom|00116\b", re.IGNORECASE), "Venom"),
    (re.compile(r"\bjoehy\b", re.IGNORECASE), "Huntsman"),  # Joehy is the Huntsman QC code
    (re.compile(r"\b00178\b", re.IGNORECASE), "Spider Kettle Cart"),
]


def detect_spider_relevance(name: Optional[str], path: Optional[str]) -> bool:
    """True iff filename or path contains a known Spider product /
    SKU / project tag. False positives are intentionally tolerated
    (better to surface a non-Spider doc than silently drop a real
    one); the cards downstream filter by detected_doc_kind for
    further precision."""
    haystack = f"{name or ''} {path or ''}"
    return bool(_SPIDER_KEYWORDS_RE.search(haystack))


def detect_spider_product(name: Optional[str], path: Optional[str]) -> Optional[str]:
    """Returns the canonical Spider product display name when a
    specific product is detected, else None. Used to backfill
    ``spider_product`` on docs that came from a NULL-spider_product
    site."""
    haystack = f"{name or ''} {path or ''}"
    for pattern, product in _SPIDER_PRODUCT_PATTERNS:
        if pattern.search(haystack):
            return product
    return None


# ── Document-kind detection (QA / freight / shipping) ────────────────
#
# Joseph asked specifically for QA reports and ocean / air freight
# tracking from the vendor sites. These tags drive the Operations and
# Manufacturing dashboard cards. Match order matters — more specific
# patterns first so a "Air Freight QA Report" isn't double-tagged.

_DOC_KIND_PATTERNS = [
    # Patent / IP filings (must match BEFORE generic shipping/invoice
    # because some patent files mention "invoice" or "shipping" in
    # context). Qifei has a lot of these: utility model patents,
    # appearance designs, IP transfer agreements, FTO opinions.
    (re.compile(
        r"\b(patent|utility[ \-_]?model|appearance[ \-_]?design|"
        r"ip[ \-_]?(?:certificate|transfer|assignment|transition|"
        r"notice|filing|application|opinion|agency)|"
        r"trademark[ \-_]?(?:application|registration|notice)|"
        r"freedom[ \-_]?to[ \-_]?operate|\bfto\b|"
        r"customs[ \-_]?recordation)",
        re.IGNORECASE,
    ), "patent_ip"),
    # Air freight (most specific freight type — match before generic shipping)
    (re.compile(
        r"\b(air[ \-_]?waybill|airway[ \-_]?bill|\bawb\b|air[ \-_]?freight|air[ \-_]?cargo)",
        re.IGNORECASE,
    ), "freight_air"),
    # Ocean freight — broadened to capture Qifei's BL#/HBL/MBL/CTN
    # patterns on Chinese vendor shipping docs.
    (re.compile(
        r"\b(bill[ \-_]?of[ \-_]?lading|\bbol\b|\bb/l\b|"
        r"\bbl[ \-_]?#|\bhbl\b|\bmbl\b|"  # BL#xxxxx, HBL (House BL), MBL (Master BL)
        r"ocean[ \-_]?freight|sea[ \-_]?freight|"
        r"container[ \-_]?(?:#|number|no)|vessel|"
        r"shipping[ \-_]?manifest|port[ \-_]?of[ \-_]?(?:loading|discharge)|"
        r"ctn[0-9]{2,}|ctn[ \-_]?\d|\bcarton\b|debit[ \-_]?note)",
        re.IGNORECASE,
    ), "freight_ocean"),
    # QA / inspection (very specific to product quality, not fire safety etc.)
    (re.compile(
        r"\b(qc[ \-_]?report|qa[ \-_]?report|first[ \-_]?article[ \-_]?inspection|"
        r"\bfai\b|\bppap\b|incoming[ \-_]?inspection|outgoing[ \-_]?inspection|"
        r"product[ \-_]?inspection|quality[ \-_]?report|test[ \-_]?report|"
        r"dim(?:ensional)?[ \-_]?report|cmm[ \-_]?report|control[ \-_]?plan|"
        r"non[ \-_]?conformance|\bncr\b|\bcpk\b|defect[ \-_]?rate)",
        re.IGNORECASE,
    ), "qa"),
    # Generic shipping / packing lists (not specifically tagged ocean or air)
    (re.compile(
        r"\b(packing[ \-_]?list|packing[ \-_]?slip|shipping[ \-_]?list|"
        r"shipment[ \-_]?(?:advice|notice|notification)|loading[ \-_]?(?:list|plan))",
        re.IGNORECASE,
    ), "shipping"),
    # Commercial invoices (vendor billing us — distinct from FedEx invoices).
    # Includes API# (Asia Pacific Invoice prefix Qifei uses), FAPIAO
    # (Chinese tax invoice), and proforma variants.
    (re.compile(
        r"\b(commercial[ \-_]?invoice|proforma|pro[ \-_]?forma|"
        r"vendor[ \-_]?invoice|fapiao|api[ \-_]?#|api[ \-_]?dne|"
        r"\binv[0-9]{6,}|sample[ \-_]?invoice|receivable|payable)",
        re.IGNORECASE,
    ), "invoice"),
    # Quotes / cost proposals (forward-looking — what would the vendor
    # charge if we ordered X). Useful for Operations sourcing.
    (re.compile(
        r"\b(quote|quotation|cost[ \-_]?(?:proposal|breakdown|estimate)|"
        r"price[ \-_]?list|rfq|request[ \-_]?for[ \-_]?quote)",
        re.IGNORECASE,
    ), "quote"),
    # Engineering / CAD drawings (Kienco's primary contribution — they
    # produce CAD files for Spider parts before tooling).
    (re.compile(
        r"\.(dxf|dwg|step|stp|iges|igs|stl|prt|sldprt|sldasm|ipt|idw|iam|f3d)$",
        re.IGNORECASE,
    ), "cad_drawing"),
]


def detect_doc_kind(name: Optional[str], path: Optional[str], semantic_type: Optional[str]) -> Optional[str]:
    """Tag the document's purpose: 'qa' | 'freight_ocean' | 'freight_air'
    | 'shipping' | 'invoice' | None. Filename + path scan; falls back
    to None when no pattern matches (most documents). Pure function
    so unit-testable without DB."""
    haystack = f"{name or ''} {path or ''}"
    for pattern, kind in _DOC_KIND_PATTERNS:
        if pattern.search(haystack):
            return kind
    return None


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


def classify_documents(
    db: Session,
    *,
    force: bool = False,
    limit: Optional[int] = None,
    batch_size: int = 500,
) -> dict[str, int]:
    """Walk every (non-folder) sharepoint_document and write classification
    columns. Bulk UPDATE in batches of ``batch_size`` so 12k rows
    process in seconds, not minutes.

    For sites where ``spider_product`` is already set at the site level
    (per-product Spider sites: Huntsman/Webcraft/etc), spider_relevant
    is forced true and the per-row spider_product is preserved.

    For vendor sites (Kienco, Qifei, future) where the site-level
    ``spider_product`` is NULL, the per-row spider_product is backfilled
    from filename detection, and spider_relevant is set based on
    keyword match.
    """
    # Pull site-level spider_product so we know whether a row came
    # from a per-product Spider site (always-relevant) or a vendor
    # workspace (needs content classification).
    q = (
        select(
            SharepointDocument.id,
            SharepointDocument.name,
            SharepointDocument.path,
            SharepointDocument.mime_type,
            SharepointDocument.spider_product,
        )
        .where(SharepointDocument.is_folder == False)  # noqa: E712
    )
    if not force:
        q = q.where(SharepointDocument.classified_at.is_(None))
    if limit:
        q = q.limit(limit)

    rows = db.execute(q).all()
    counts = {"seen": 0, "updated": 0, "spider_relevant": 0, "doc_kinds_tagged": 0}
    now = datetime.now(timezone.utc)
    payload: list[dict[str, Any]] = []
    for row in rows:
        counts["seen"] += 1
        semantic = classify_semantic_type(row.name, row.mime_type)
        # Spider-relevance: per-product Spider sites are always true;
        # vendor sites depend on filename match.
        if row.spider_product:
            spider_relevant = True
            detected_product = None  # don't overwrite the per-site value
        else:
            spider_relevant = detect_spider_relevance(row.name, row.path)
            detected_product = (
                detect_spider_product(row.name, row.path) if spider_relevant else None
            )
        if spider_relevant:
            counts["spider_relevant"] += 1
        doc_kind = detect_doc_kind(row.name, row.path, semantic)
        if doc_kind:
            counts["doc_kinds_tagged"] += 1
        payload.append({
            "_id": row.id,
            "archive_status": classify_archive_status(row.path),
            "semantic_type": semantic,
            "parsed_metadata": parse_filename_metadata(row.name),
            "spider_relevant": spider_relevant,
            "detected_doc_kind": doc_kind,
            "detected_product": detected_product,  # only used for vendor-site backfill
            "classified_at": now,
        })
        if len(payload) >= batch_size:
            _flush_classify_batch(db, payload)
            counts["updated"] += len(payload)
            payload.clear()
    if payload:
        _flush_classify_batch(db, payload)
        counts["updated"] += len(payload)
    db.commit()
    return counts


def _flush_classify_batch(db: Session, payload: list[dict[str, Any]]) -> None:
    """Bulk UPDATE via Core (not ORM) — one prepared statement, many
    parameter sets. Uses ``__table__`` to bypass SA 2.0's "ORM bulk by
    PK" path which has stricter requirements on the parameter names.

    spider_product is backfilled with COALESCE so vendor-site rows
    (which arrived NULL) get the detected product, while per-product
    Spider site rows keep their original site-level value.
    """
    tbl = SharepointDocument.__table__
    stmt = (
        update(tbl)
        .where(tbl.c.id == sa_bindparam("_id"))
        .values(
            archive_status=sa_bindparam("archive_status"),
            semantic_type=sa_bindparam("semantic_type"),
            parsed_metadata=sa_bindparam("parsed_metadata"),
            spider_relevant=sa_bindparam("spider_relevant"),
            detected_doc_kind=sa_bindparam("detected_doc_kind"),
            # Only overwrite spider_product when the row currently has
            # NULL (vendor-site path). Per-product Spider sites already
            # have spider_product set at ingest from the site row;
            # don't clobber it.
            spider_product=sa.func.coalesce(tbl.c.spider_product, sa_bindparam("detected_product")),
            classified_at=sa_bindparam("classified_at"),
        )
    )
    db.execute(stmt, payload)
