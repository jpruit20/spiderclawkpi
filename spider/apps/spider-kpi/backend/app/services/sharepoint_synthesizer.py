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
SYNTHESIZER_VERSION = "synth-v2.0.0"
MODEL_ID = "claude-opus-4-7"


class CogsBreakdownItem(BaseModel):
    category: str
    cost_usd: float
    source_document_id: Optional[int] = None
    notes: Optional[str] = None


class CogsSummary(BaseModel):
    canonical_total_usd: Optional[float] = None
    canonical_line_count: Optional[int] = None
    canonical_document_id: Optional[int] = None
    confidence: str
    notes: Optional[str] = None
    breakdown: List[CogsBreakdownItem] = Field(default_factory=list)
    coated_total_usd: Optional[float] = None
    uncoated_total_usd: Optional[float] = None
    currency_notes: Optional[str] = None


class DesignStatus(BaseModel):
    latest_revision: Optional[str] = None
    latest_revision_document_id: Optional[int] = None
    active_workstreams: List[str] = Field(default_factory=list)
    notable_iterations: List[str] = Field(default_factory=list)


class VendorRollup(BaseModel):
    name: str
    mentions: int
    documents_seen: int = 0
    role: Optional[str] = None
    estimated_spend_usd: Optional[float] = None


class VendorSummary(BaseModel):
    top_vendors: List[VendorRollup] = Field(default_factory=list)
    total_unique: int = 0


class DataQualityIssue(BaseModel):
    severity: str
    issue: str
    affected_document_ids: List[int] = Field(default_factory=list)
    suggested_fix: Optional[str] = None


class Citation(BaseModel):
    claim: str
    document_id: int


class HeadlineMetric(BaseModel):
    label: str
    value: str
    unit: Optional[str] = None
    tone: str
    source_document_id: Optional[int] = None


class TimelineEvent(BaseModel):
    date: str
    label: str
    document_id: Optional[int] = None
    kind: str


class ProductSynthesis(BaseModel):
    headline_metrics: List[HeadlineMetric] = Field(default_factory=list)
    narrative_md: str
    cogs_summary: CogsSummary
    design_status: DesignStatus
    vendor_summary: VendorSummary
    data_quality_issues: List[DataQualityIssue] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the synthesis pass for Spider Grills' SharePoint corpus.

You receive every analyzed file for one product (Huntsman / Giant Huntsman / Venom / Webcraft / Giant Webcraft) and produce one coherent picture for a founder/operator dashboard.

Voice: dense, concrete, founder-grade. No filler. Lead with what's true. End with what's blocking decisions.

This is rendered as a KPI dashboard, not a memo. Most of the value lives in the **structured fields** (headline_metrics, cogs_summary.breakdown, vendor_summary, timeline, data_quality_issues). The narrative_md is a secondary read.

## headline_metrics — 3-6 tile-ready stats

Pick the numbers a busy operator would scan first. Examples:
  { label: "COGS per unit", value: "$281.12", unit: "uncoated · CBOM Rev J", tone: "good", source_document_id: 873 }
  { label: "Active vendors", value: "15", unit: "across analyzed files", tone: "neutral" }
  { label: "Latest design rev", value: "Rev M02", unit: "Tech Pack · 2026-02-28", tone: "neutral", source_document_id: 5836 }
  { label: "Open quality issues", value: "5 of 43", unit: "lots marked pass with defects", tone: "bad", source_document_id: 934 }
  { label: "BOM cost coverage", value: "0%", unit: "Tech Pack BOM", tone: "bad", source_document_id: 5836 }

Tone drives color: good=green, warn=orange, bad=red, neutral=blue.

## cogs_summary — RECONCILE ACROSS FILES, don't just pick one

This is the most-watched dashboard number. Spider's BOMs frequently have empty cost columns; their costed view lives in **CBOMs (consolidated BOMs)**, **price-list quotes**, and **invoices/POs**. Your job is to reconcile across them.

- canonical_total_usd: best estimate of per-unit COGS in USD
- canonical_document_id: the file you treated as the canonical reference
- confidence:
  - **high** when a CBOM with full pricing is at the same design rev as the current Tech Pack
  - **medium** when the costed BOM is one design rev behind, or you reconciled across CBOM + quotes
  - **low** when costs come from invoices/POs you summed but couldn't verify against a BOM line list
- coated_total_usd / uncoated_total_usd: when the CBOM separates them, fill both
- breakdown: 4-12 categories that roughly sum to canonical_total_usd. Examples for Huntsman:
  - Main Assembly steel · $X
  - Hardware (XJ fasteners) · $X
  - Venom controller subassembly · $X
  - Door + fiberglass gaskets · $X
  - Door handles + latches · $X
  - Packaging · $X
- notes: explain reconciliation. "CBOM Rev J quotes from May 2025; Tech Pack now Rev M02. Cross-checked hardware total against XJ PO QPO2026-032 ($3,598.96) — matches within 2%."

If the price-list / vendor quote files cover only a subset of the BOM, SAY SO and quantify: "Vendor PL covers 42 of ~140 BOM line items, ~30% of the dollar value."

## design_status

latest_revision (e.g. "Tech Pack Rev M02"). active_workstreams should be specific, not generic — "Charcoal grate rod-spacing 10→8mm + double-thickness reinforcement" not just "Charcoal grate redesign".

## vendor_summary

Ranked vendors. estimated_spend_usd when you can sum quotes/invoices for that vendor across files, even partial. 'role' = what they supply (fasteners, controller, gaskets, etc.).

## data_quality_issues

The dashboard renders these as severity-colored alerts. Be specific. Examples:
  - "Tech Pack Rev M02 BOM has 100+ lines, zero costs filled in" (critical)
  - "CTN002 shipment has $28,906 / $29,406 / $29,546 across three customs docs" (warn)
  - "5 of 43 inspection lots marked 'pass' despite documented defects" (warn)

## timeline

Chronological events with ISO dates. Used to render a horizontal revision/decision timeline.

## narrative_md

4-8 short paragraphs. Inline cite as [doc:N]. Don't repeat the structured fields verbatim — the narrative is for *connecting* the dots ("the sub-304 stainless finding [doc:6248] is consistent with the latch electrolysis defects in QC [doc:934]").

## Cross-checking expectations

- **CBOM/BOM costs vs price-list quotes**: when both exist for the same parts, reconcile and flag deltas >5% as data quality issues.
- **Invoice totals vs BOM totals**: invoices are real money paid; BOMs are budgeted. Differences are expected but big gaps should be flagged.
- **Customs declared values vs invoice values**: should match to the dollar. Differences are flags.
- **Pass rates vs defect logs**: a "pass" row with documented defects is a flag.

Do NOT invent numbers. Do NOT hallucinate vendors. If a number isn't in the analyzed files, leave the field null.

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
    existing.headline_metrics = [m.model_dump() for m in syn.headline_metrics]
    existing.timeline = [t.model_dump() for t in syn.timeline]
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
