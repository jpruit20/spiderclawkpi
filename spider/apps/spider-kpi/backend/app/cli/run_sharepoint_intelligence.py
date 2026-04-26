"""SharePoint semantic-layer runner.

One-shot or scheduled walk over the doc mirror that:

1. Classifies every (non-folder) row → archive_status, semantic_type,
   parsed_metadata via ``services.sharepoint_classify``
2. Pulls bytes + parses Excel BOMs into ``sharepoint_bom_lines`` via
   ``services.sharepoint_bom_extractor``
3. Resolves canonical sources for every ``(data_type, product, division)``
   tuple so the UI gets fast lookups via the materialized table.

Intended to be invoked as:

    python -m app.cli.run_sharepoint_intelligence --classify --extract-bom --resolve-canonical

Add ``--force`` to re-run on already-processed rows. ``--limit N``
is helpful for first-pass sanity-checking ("just try the latest 5").
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from app.db.session import SessionLocal
from app.services.sharepoint_classify import classify_documents
from app.services.sharepoint_bom_extractor import extract_all_bom_documents
from app.services.sharepoint_canonical import resolve_canonical
from app.services.sharepoint_content_extractor import extract_content_for_corpus
from app.services.sharepoint_ai_analyzer import analyze_corpus
from app.services.sharepoint_synthesizer import synthesize_all_products


PRODUCTS = ["Huntsman", "Giant Huntsman", "Venom", "Webcraft", "Giant Webcraft"]
DIVISIONS = ["pe", "manufacturing", "operations", None]
DATA_TYPES = ["cogs", "bom", "vendor_list", "design_spec", "drawing"]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--classify", action="store_true", help="Run filename/path classifier")
    p.add_argument("--extract-bom", action="store_true", help="Download + parse BOM/CBOM/price_list spreadsheets")
    p.add_argument("--resolve-canonical", action="store_true", help="Recompute canonical source picks for every (type, product, division)")
    p.add_argument("--extract-content", action="store_true", help="Phase 2: deep content extraction (Excel sheets/PDF/Word/PPT) for every active analyzable file")
    p.add_argument("--analyze-files", action="store_true", help="Phase 2: per-file Claude analysis on extracted content")
    p.add_argument("--synthesize", action="store_true", help="Phase 2: per-product Claude synthesis from analyzed files")
    p.add_argument("--product", default=None, help="Limit content/analyze passes to one Spider product")
    p.add_argument("--force", action="store_true", help="Re-run already-processed rows")
    p.add_argument("--limit", type=int, default=None, help="Limit how many docs are processed")
    p.add_argument("--all", action="store_true", help="Shorthand for --classify --extract-bom --resolve-canonical")
    p.add_argument("--full", action="store_true", help="Run the entire pipeline including deep analysis (--all + --extract-content + --analyze-files + --synthesize)")
    args = p.parse_args(argv)

    if args.all or args.full:
        args.classify = True
        args.extract_bom = True
        args.resolve_canonical = True
    if args.full:
        args.extract_content = True
        args.analyze_files = True
        args.synthesize = True

    if not (args.classify or args.extract_bom or args.resolve_canonical or args.extract_content or args.analyze_files or args.synthesize):
        p.print_help()
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("sp-intel")

    db = SessionLocal()
    try:
        if args.classify:
            log.info("Classifying documents (force=%s, limit=%s)...", args.force, args.limit)
            counts = classify_documents(db, force=args.force, limit=args.limit)
            log.info("classify: %s", counts)

        if args.extract_bom:
            log.info("Extracting BOM lines (force=%s, limit=%s)...", args.force, args.limit)
            counts = extract_all_bom_documents(db, force=args.force, limit=args.limit)
            log.info("extract_bom: %s", counts)

        if args.extract_content:
            log.info("Extracting deep content (force=%s, limit=%s, product=%s)...", args.force, args.limit, args.product)
            counts = extract_content_for_corpus(db, spider_product=args.product, limit=args.limit, force=args.force)
            log.info("extract_content: %s", counts)

        if args.analyze_files:
            log.info("Analyzing files with Claude (force=%s, limit=%s, product=%s)...", args.force, args.limit, args.product)
            from app.services.sharepoint_ai_analyzer import analyze_corpus as _analyze
            counts = _analyze(db, spider_product=args.product, limit=args.limit, force=args.force)
            log.info("analyze_files: %s", counts)

        if args.synthesize:
            log.info("Synthesizing per-product narratives (force=%s)...", args.force)
            results = synthesize_all_products(db, force=args.force)
            for prod, r in results.items():
                log.info("synthesize[%s]: %s", prod, r)

        if args.resolve_canonical:
            log.info("Resolving canonical sources for %d data_types × %d products × %d divisions...",
                     len(DATA_TYPES), len(PRODUCTS), len(DIVISIONS))
            picked = 0
            empty = 0
            for dt in DATA_TYPES:
                for prod in PRODUCTS:
                    for div in DIVISIONS:
                        doc = resolve_canonical(
                            db,
                            data_type=dt,
                            spider_product=prod,
                            dashboard_division=div,
                            auto_persist=True,
                        )
                        if doc:
                            picked += 1
                        else:
                            empty += 1
            log.info("resolve_canonical: picked=%d empty=%d", picked, empty)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
