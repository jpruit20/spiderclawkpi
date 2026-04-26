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


PRODUCTS = ["Huntsman", "Giant Huntsman", "Venom", "Webcraft", "Giant Webcraft"]
DIVISIONS = ["pe", "manufacturing", "operations", None]
DATA_TYPES = ["cogs", "bom", "vendor_list", "design_spec", "drawing"]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--classify", action="store_true", help="Run filename/path classifier")
    p.add_argument("--extract-bom", action="store_true", help="Download + parse BOM/CBOM/price_list spreadsheets")
    p.add_argument("--resolve-canonical", action="store_true", help="Recompute canonical source picks for every (type, product, division)")
    p.add_argument("--force", action="store_true", help="Re-run already-processed rows")
    p.add_argument("--limit", type=int, default=None, help="Limit how many docs are processed")
    p.add_argument("--all", action="store_true", help="Shorthand for --classify --extract-bom --resolve-canonical")
    args = p.parse_args(argv)

    if args.all:
        args.classify = True
        args.extract_bom = True
        args.resolve_canonical = True

    if not (args.classify or args.extract_bom or args.resolve_canonical):
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
