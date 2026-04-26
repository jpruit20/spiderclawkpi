"""Per-product synthesis pass.

Reads every ``sharepoint_file_analysis`` for a product and asks Opus
4.7 to produce a single coherent narrative + structured rollups. This
is what shows at the top of the SharePoint Intelligence card — not
file lists, real synthesis with citations.

The synthesis answers:

- **What is the org actually doing on this product right now?**
  (Inferred from active files' purposes, recent revisions, ECRs)
- **What is the COGS picture?** Roll up across BOMs/CBOMs/price-lists,
  flag conflicting figures, point to the canonical file.
- **Who are the key vendors?** Aggregate from all files, dedupe noisy
  cells, rank by mentions/cost.
- **Where is data quality blocking decisions?**

Citations attach every claim to specific document_ids so the UI links
through to source.
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
from app.models import SharepointDocument, SharepointFileAnalysis, SharepointProductIntelligence


logger = logging.getLogger(__name__)
SYNTHESIZER_VERSION = "synth-v1.0.0"
MODEL_ID = "claude-opus-4-7"


class CogsSummary(BaseModel):
    canonical_total_usd: Optional[float] = None
    canonical_line_count: Optional[int] = None
    canonical_document_id: Optional[int] = None
    confidence: str = Field(description="One of: high | medium | low")
    notes: Optional[str] = Field(default=None, description="Why this confidence — e.g. 'BOM has 179 lines but no costs filled in'")


class DesignStatus(BaseModel):
    latest_revision: Optional[str] = None
    latest_revision_document_id: Optional[int] = None
    active_workstreams: List[str] = Field(default_factory=list)
    notable_iterations: List[str] = Field(default_factory=list)


class VendorRollup(BaseModel):
    name: str
    mentions: int
    documents_seen: int = 0
    role: Optional[str] = None  # e.g. "fan supplier", "powder coat"


class VendorSummary(BaseModel):
    top_vendors: List[VendorRollup] = Field(default_factory=list)
    total_unique: int = 0


class DataQualityIssue(BaseModel):
    severity: str = Field(description="One of: critical | warn | info")
    issue: str
    affected_document_ids: List[int] = Field(default_factory=list)
    suggested_fix: Optional[str] = None


class Citation(BaseModel):
    claim: str
    document_id: int


class ProductSynthesis(BaseModel):
    narrative_md: str = Field(description="Markdown narrative — 4-8 short paragraphs, executive-readable. Cite specific files inline as [doc:123]. Lead with what we know is true; end with what's missing/blocked.")
    cogs_summary: CogsSummary
    design_status: DesignStatus
    vendor_summary: VendorSummary
    data_quality_issues: List[DataQualityIssue] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list, description="Every [doc:N] referenced in narrative_md, expanded.")


SYSTEM_PROMPT = """You are the synthesis pass for Spider Grills' SharePoint corpus.

You receive every analyzed file for one product (Huntsman / Giant Huntsman / Venom / Webcraft / Giant Webcraft) and produce one coherent picture for the founder/operator who reads the dashboard.

Voice: dense, concrete, founder-grade. No filler. Lead with what's true. End with what's blocking decisions.

For **narrative_md**: 4-8 short paragraphs in markdown. Cite specific files inline using [doc:N] where N is the document_id from the input. Cover (when the data supports it):

- What this product is and what's currently being worked on. Reference recent revisions, ECRs, active workstreams.
- The COGS picture. If there's a canonical BOM with real numbers, lead with the total. If costs are missing, state that clearly: "BOM Rev M has 179 lines but no cost columns filled in [doc:123]; pricing for ~40 of those parts shows up in the Vendor PL [doc:456], implying $X partial coverage."
- Vendor relationships — who supplies the most, what they supply.
- Data quality issues blocking the dashboard from giving a clean answer.
- Anything else genuinely meaningful in the corpus (test reports, tech packs, quality plans, recent design pivots).

Do NOT pad. Do NOT speculate beyond what the analyzed files say. If the corpus is thin, say so.

For **cogs_summary**: pick the file you'd treat as canonical for COGS, give your confidence (high/medium/low), and explain.

For **design_status**: latest revision label and the document it came from. List active workstreams inferred from filenames + recent activity.

For **vendor_summary**: ranked vendor list with documents_seen count.

For **data_quality_issues**: 0-8 entries. Severity = critical when it blocks a decision (e.g. "no BOM has costs"), warn when it makes a decision risky (e.g. "two BOMs disagree on vent ring cost"), info for nice-to-fix.

For **citations**: expand every [doc:N] you used in narrative_md.

Respond with JSON conforming to ProductSynthesis."""


def _build_user_message(spider_product: str, analyses: list[tuple[SharepointDocument, SharepointFileAnalysis]]) -> str:
    lines: list[str] = [
        f"PRODUCT: {spider_product}",
        f"FILES_ANALYZED: {len(analyses)}",
        "",
        "=== ANALYZED FILES ===",
        "",
    ]
    for doc, an in analyses:
        meta = doc.parsed_metadata or {}
        lines.append(f"[doc:{doc.id}] {doc.name}")
        lines.append(f"  path: {doc.path}")
        lines.append(f"  semantic_type: {doc.semantic_type} · archive_status: {doc.archive_status} · division: {doc.dashboard_division}")
        lines.append(f"  filename-parsed: SKU={meta.get('sku_code')} rev={meta.get('revision_letter')} doc_date={meta.get('doc_date')} assembly={meta.get('assembly_name')}")
        lines.append(f"  modified: {doc.modified_at_remote.isoformat() if doc.modified_at_remote else '?'} by {doc.modified_by_email or '?'}")
        lines.append(f"  purpose: {an.purpose or '(none)'}")
        if an.key_facts:
            lines.append("  key_facts:")
            for f in an.key_facts[:12]:
                kind = f.get('kind') if isinstance(f, dict) else getattr(f, 'kind', '?')
                summary = f.get('summary') if isinstance(f, dict) else getattr(f, 'summary', '')
                source_loc = f.get('source_location') if isinstance(f, dict) else getattr(f, 'source_location', None)
                loc = f" @ {source_loc}" if source_loc else ""
                lines.append(f"    - [{kind}] {summary}{loc}")
        if an.cost_data:
            cd = an.cost_data
            lines.append(f"  cost_data: total=${cd.get('total_cost_usd')} lines={cd.get('line_count')} completeness={cd.get('cost_completeness')} notes={cd.get('notes')}")
        if an.related_vendors:
            lines.append(f"  vendors: {', '.join(an.related_vendors[:15])}")
        if an.related_part_numbers:
            lines.append(f"  parts: {', '.join(an.related_part_numbers[:15])}")
        if an.decisions:
            lines.append(f"  decisions: {'; '.join(an.decisions[:5])}")
        if an.data_quality_flags:
            lines.append(f"  data_quality_flags: {'; '.join(an.data_quality_flags[:5])}")
        lines.append("")
    return "\n".join(lines)


def synthesize_product(
    db: Session,
    *,
    spider_product: str,
    dashboard_division: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run the synthesizer for one product. Skips if a fresh synthesis
    exists and no underlying analyses have advanced."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return {"status": "skipped", "reason": "no anthropic_api_key"}

    # Pull every (doc, analysis) pair for this product
    rows = db.execute(
        select(SharepointDocument, SharepointFileAnalysis)
        .join(SharepointFileAnalysis, SharepointFileAnalysis.document_id == SharepointDocument.id)
        .where(
            SharepointDocument.spider_product == spider_product,
            SharepointDocument.archive_status == "active",
        )
        .order_by(SharepointDocument.modified_at_remote.desc().nulls_last())
    ).all()
    if not rows:
        return {"status": "skipped", "reason": "no analyzed files for product"}

    existing = db.execute(
        select(SharepointProductIntelligence).where(
            SharepointProductIntelligence.spider_product == spider_product,
            SharepointProductIntelligence.dashboard_division.is_(dashboard_division) if dashboard_division is None
                else SharepointProductIntelligence.dashboard_division == dashboard_division,
        )
    ).scalar_one_or_none()

    latest_analysis_at = max(
        (an.analyzed_at for _, an in rows if an.analyzed_at is not None),
        default=None,
    )
    if (
        existing is not None
        and not force
        and existing.synthesizer_version == SYNTHESIZER_VERSION
        and existing.synthesized_at is not None
        and latest_analysis_at is not None
        and existing.synthesized_at >= latest_analysis_at
    ):
        return {"status": "cached", "id": existing.id}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=300, max_retries=1)
    user_msg = _build_user_message(spider_product, [(d, a) for d, a in rows])

    try:
        response = client.messages.parse(
            model=MODEL_ID,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
            output_format=ProductSynthesis,
        )
    except Exception as exc:
        logger.exception("synthesis failed for %s", spider_product)
        return {"status": "failed", "error": str(exc)[:500]}

    syn: Optional[ProductSynthesis] = response.parsed_output
    if syn is None:
        return {"status": "failed", "error": "parsed_output is None"}

    now = datetime.now(timezone.utc)
    if existing is None:
        existing = SharepointProductIntelligence(spider_product=spider_product, dashboard_division=dashboard_division)
        db.add(existing)
    existing.narrative_md = syn.narrative_md
    existing.cogs_summary = syn.cogs_summary.model_dump()
    existing.design_status = syn.design_status.model_dump()
    existing.vendor_summary = syn.vendor_summary.model_dump()
    existing.data_quality_issues = [i.model_dump() for i in syn.data_quality_issues]
    existing.citations = [c.model_dump() for c in syn.citations]
    existing.files_analyzed = len(rows)
    existing.model_used = MODEL_ID
    existing.synthesizer_version = SYNTHESIZER_VERSION
    existing.synthesized_at = now
    db.commit()

    return {
        "status": "ok",
        "id": existing.id,
        "files_analyzed": len(rows),
        "narrative_chars": len(syn.narrative_md or ""),
    }


PRODUCTS = ["Huntsman", "Giant Huntsman", "Venom", "Webcraft", "Giant Webcraft"]


def synthesize_all_products(db: Session, *, force: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prod in PRODUCTS:
        out[prod] = synthesize_product(db, spider_product=prod, force=force)
    return out
