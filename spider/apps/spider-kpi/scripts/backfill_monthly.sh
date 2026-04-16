#!/usr/bin/env bash
# Monthly-chunked S3 backfill — avoids OOM on the 4GB droplet by processing
# one month at a time instead of quarterly/yearly chunks.
#
# Usage:
#   nohup bash scripts/backfill_monthly.sh > /var/log/spider-kpi-monthly-backfill.log 2>&1 &
#   tail -f /var/log/spider-kpi-monthly-backfill.log
#
# Safe to re-run — the importer upserts on business_date.
set -euo pipefail

APP_DIR="/opt/spiderclawkpi/spider/apps/spider-kpi"
PY="$APP_DIR/.venv/bin/python"
IMPORT="$APP_DIR/scripts/import_s3_history.py"

FAILED=0
TOTAL=0

# Generate monthly ranges from 2024-01 through 2026-03
for year in 2024 2025 2026; do
    end_month=12
    if [ "$year" = "2026" ]; then end_month=3; fi
    for month in $(seq 1 $end_month); do
        start=$(printf "%04d-%02d-01" "$year" "$month")
        if [ "$month" = "12" ]; then
            end_date=$(printf "%04d-01-01" $((year + 1)))
        else
            end_date=$(printf "%04d-%02d-01" "$year" $((month + 1)))
        fi
        # end-date is exclusive in date math; import uses inclusive, so subtract 1 day
        end=$(date -d "$end_date - 1 day" +%Y-%m-%d 2>/dev/null || date -v-1d -jf "%Y-%m-%d" "$end_date" +%Y-%m-%d 2>/dev/null)

        TOTAL=$((TOTAL + 1))
        echo "$(date -Iseconds) === [$TOTAL] $start -> $end ==="
        if $PY "$IMPORT" --start-date "$start" --end-date "$end" 2>&1; then
            echo "$(date -Iseconds) OK $start -> $end"
        else
            echo "$(date -Iseconds) FAIL $start -> $end (rc=$?)"
            FAILED=$((FAILED + 1))
        fi
        echo ""
    done
done

echo "$(date -Iseconds) === Complete: $((TOTAL - FAILED))/$TOTAL succeeded ==="
exit $FAILED
