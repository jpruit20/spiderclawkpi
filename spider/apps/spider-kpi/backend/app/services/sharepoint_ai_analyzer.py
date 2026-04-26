"""Per-file Claude analysis layer.

Reads cached ``sharepoint_file_content`` text + structure and asks
Claude to produce a structured analysis: what is this file *for*,
what claims does it make, what parts/vendors/costs does it document.

Output is stored as ``sharepoint_file_analysis``. The synthesizer
reads many of these per product and writes the cross-file narrative.

Cost shape (Haiku-class model is fine for the per-file pass):
- ~3-15k input tokens per file
- ~500-1500 output tokens per file
- ~500 active files in the corpus
- => roughly $1-2 per full corpus pass
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SharepointDocument, SharepointFileAnalysis, SharepointFileContent


logger = logging.getLogger(__name__)
ANALYZER_VERSION = "analysis-v1.0.0"
MODEL_ID = "claude-haiku-4-5"


class KeyFact(BaseModel):
    kind: str = Field(description="One of: cost, part, vendor, dimension, decision, revision, date, scope, dependency, risk")
    summary: str = Field(description="One-sentence statement of the fact, written for an executive reader")
    detail: Optional[str] = Field(default=None, description="Optional supporting detail or numbers")
    source_location: Optional[str] = Field(default=None, description="Sheet name / page / section where this is stated")


class CostData(BaseModel):
    total_cost_usd: Optional[float] = None
    line_count: Optional[int] = None
    currency_observed: Optional[str] = None
    cost_completeness: str = Field(description="One of: complete | partial | empty | not_applicable")
    notes: Optional[str] = None


class DesignData(BaseModel):
    revision_label: Optional[str] = None
    assemblies_named: List[str] = Field(default_factory=list)
    materials_named: List[str] = Field(default_factory=list)
    dimensions_summary: Optional[str] = None


class FileAnalysis(BaseModel):
    purpose: str = Field(description="One sentence: what this file is for in the Spider Grills product org")
    key_facts: List[KeyFact] = Field(default_factory=list, description="Concrete claims this file makes; up to 12")
    related_part_numbers: List[str] = Field(default_factory=list)
    related_vendors: List[str] = Field(default_factory=list)
    cost_data: CostData
    design_data: DesignData
    decisions: List[str] = Field(default_factory=list, description="Decisions / conclusions the file documents")
    data_quality_flags: List[str] = Field(default_factory=list, description="Issues a reader should be aware of (missing costs, conflicting figures, draft status, etc.)")


SYSTEM_PROMPT = """You are the analysis pass for Spider Grills' SharePoint corpus.

Spider Grills makes premium grills (Huntsman, Giant Huntsman, Venom, Webcraft, Giant Webcraft). Their files live in a SharePoint mirror parsed and presented to a single-user dashboard. You are NOT writing for a casual reader — you are writing for the founder/operator who needs concrete, citable facts to drive decisions.

For each file, you must return:

- **purpose**: What this specific file is *for*. One sentence. Be specific. "Bill of Materials for Huntsman Main Assembly Rev M, used by manufacturing for procurement" is good. "A spreadsheet about Huntsman" is bad.

- **key_facts**: Up to 12 concrete claims this file makes. Each is typed (cost / part / vendor / dimension / decision / revision / date / scope / dependency / risk) so the dashboard can group them. Cite the sheet name or page in source_location when available.

- **related_part_numbers**: Part numbers (SKUs, internal codes) mentioned. Up to 30. Include both Spider's own (ATL-SPG-…) and vendor codes.

- **related_vendors**: Vendor / supplier names mentioned. Clean them up — "Vendor:JIAYI\\nPower adapter" should be just "JIAYI".

- **cost_data**: If the file has cost columns, fill in totals. cost_completeness = empty when columns exist but aren't populated; partial when some are filled; complete when all are; not_applicable for non-cost files.

- **design_data**: Revision label, assemblies referenced by name (e.g. "Main Assembly", "Vent Ring", "Lift Kit"), key materials/finishes, brief dimensional summary.

- **decisions**: Decisions or conclusions documented (e.g. "Switched fan vendor from X to Y", "Approved Rev M for production"). Empty list if none.

- **data_quality_flags**: What a careful reader should be aware of. Examples: "BOM has 179 line items but no cost columns filled in", "two different totals on different sheets ($X and $Y)", "marked DRAFT", "vendor cell is multi-line with notes mixed in".

Do not invent facts. If something isn't in the file, leave it out. If the file is mostly empty or unparseable, say so in purpose and flag it.

Respond with JSON conforming to the FileAnalysis schema."""


def _build_user_message(doc: SharepointDocument, content: SharepointFileContent) -> str:
    meta = doc.parsed_metadata or {}
    structure_summary = ""
    if isinstance(content.structure_json, dict):
        s = content.structure_json
        if s.get("format") in ("xlsx", "xls"):
            sheets = s.get("sheets") or []
            structure_summary = f"\nFormat: {s['format']} workbook with {len(sheets)} sheets: " + ", ".join(
                f"{sh['name']} ({sh['rows_sampled']} rows × {sh['max_columns_seen']} cols)" for sh in sheets[:20]
            )
        elif s.get("format") == "pdf":
            structure_summary = f"\nFormat: PDF, {s.get('n_pages', '?')} pages, {s.get('pages_extracted', '?')} pages with text."
        elif s.get("format") == "docx":
            structure_summary = f"\nFormat: Word doc, {s.get('n_paragraphs', '?')} paragraphs, {s.get('n_tables', 0)} tables."
        elif s.get("format") == "pptx":
            structure_summary = f"\nFormat: PowerPoint, {s.get('n_slides', '?')} slides."

    return f"""FILE METADATA
- Name: {doc.name}
- Path: {doc.path}
- Spider product: {doc.spider_product or '?'}
- Dashboard division: {doc.dashboard_division or '?'}
- Top folder: {doc.top_level_folder or '?'}
- Semantic type (auto-classified): {doc.semantic_type or '?'}
- Archive status: {doc.archive_status or '?'}
- Last modified: {doc.modified_at_remote.isoformat() if doc.modified_at_remote else '?'} by {doc.modified_by_email or '?'}
- Filename-parsed: SKU={meta.get('sku_code', '?')} rev={meta.get('revision_letter', '?')} doc_date={meta.get('doc_date', '?')} assembly={meta.get('assembly_name', '?')}
{structure_summary}

EXTRACTED CONTENT (truncated to fit context):

{content.text_content or '(no text extracted)'}
"""


def analyze_document(db: Session, doc: SharepointDocument, *, force: bool = False) -> dict[str, Any]:
    """Run Claude analysis on one document. Skips if a fresh analysis
    exists for the current extractor version + content sha."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {"status": "skipped", "reason": "no anthropic_api_key"}

    content = db.execute(
        select(SharepointFileContent).where(SharepointFileContent.document_id == doc.id)
    ).scalar_one_or_none()
    if content is None or content.extraction_status != "ok":
        return {"status": "skipped", "reason": "no extracted content"}
    if not (content.text_content or "").strip():
        return {"status": "skipped", "reason": "empty extraction"}

    existing = db.execute(
        select(SharepointFileAnalysis).where(SharepointFileAnalysis.document_id == doc.id)
    ).scalar_one_or_none()
    if (
        existing is not None
        and not force
        and existing.analyzer_version == ANALYZER_VERSION
        and existing.analyzed_at is not None
        and content.extracted_at is not None
        and existing.analyzed_at >= content.extracted_at
    ):
        return {"status": "cached", "id": existing.id}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120, max_retries=1)
    user_msg = _build_user_message(doc, content)

    try:
        response = client.messages.parse(
            model=MODEL_ID,
            max_tokens=4096,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
            output_format=FileAnalysis,
        )
    except Exception as exc:
        logger.warning("file analysis failed for doc %s (%s): %s", doc.id, doc.name, exc)
        return {"status": "failed", "error": str(exc)[:500]}

    analysis: Optional[FileAnalysis] = response.parsed_output
    if analysis is None:
        return {"status": "failed", "error": "parsed_output is None"}

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", None) if usage else None
    out_tok = getattr(usage, "output_tokens", None) if usage else None

    now = datetime.now(timezone.utc)
    if existing is None:
        existing = SharepointFileAnalysis(document_id=doc.id)
        db.add(existing)
    existing.purpose = analysis.purpose
    existing.key_facts = [f.model_dump() for f in analysis.key_facts]
    existing.related_part_numbers = analysis.related_part_numbers[:50]
    existing.related_vendors = analysis.related_vendors[:30]
    existing.cost_data = analysis.cost_data.model_dump()
    existing.design_data = analysis.design_data.model_dump()
    existing.decisions = analysis.decisions[:30]
    existing.data_quality_flags = analysis.data_quality_flags[:20]
    existing.model_used = MODEL_ID
    existing.input_tokens = in_tok
    existing.output_tokens = out_tok
    existing.analyzer_version = ANALYZER_VERSION
    existing.analyzed_at = now
    db.commit()

    return {
        "status": "ok",
        "id": existing.id,
        "facts": len(analysis.key_facts),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


def analyze_corpus(
    db: Session,
    *,
    spider_product: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
) -> dict[str, int]:
    """Walk every doc that has fresh content but no fresh analysis."""
    q = (
        select(SharepointDocument)
        .join(SharepointFileContent, SharepointFileContent.document_id == SharepointDocument.id)
        .where(
            SharepointFileContent.extraction_status == "ok",
            SharepointDocument.archive_status == "active",
        )
        .order_by(SharepointDocument.modified_at_remote.desc().nulls_last())
    )
    if spider_product:
        q = q.where(SharepointDocument.spider_product == spider_product)
    if limit:
        q = q.limit(limit)

    docs = db.execute(q).scalars().all()
    counts = {"seen": 0, "ok": 0, "cached": 0, "failed": 0, "skipped": 0, "input_tokens": 0, "output_tokens": 0}
    for doc in docs:
        counts["seen"] += 1
        result = analyze_document(db, doc, force=force)
        s = result.get("status")
        if s == "ok":
            counts["ok"] += 1
            counts["input_tokens"] += result.get("input_tokens") or 0
            counts["output_tokens"] += result.get("output_tokens") or 0
        elif s == "cached":
            counts["cached"] += 1
        elif s == "skipped":
            counts["skipped"] += 1
        else:
            counts["failed"] += 1
    return counts
