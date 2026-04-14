#!/usr/bin/env bash
#
# Run import_s3_history.py across the full historical range as quarterly
# chunks, writing a separate log file per range plus a summary log.
#
# Intended for the production droplet:
#   cd /opt/spiderclawkpi/spider/apps/spider-kpi
#   nohup bash scripts/backfill_all_quarters.sh >/dev/null 2>&1 &
#   tail -f logs/backfill/summary_*.log      # overall progress
#   tail -f logs/backfill/2024_Q1_*.log      # individual quarter progress
#
# Safe to re-run — the importer upserts on business_date.
# Exits non-zero if any quarter failed (count = exit code, capped at 255).

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$APP_DIR/logs/backfill"
PY="$APP_DIR/.venv/bin/python"
IMPORT_SCRIPT="$SCRIPT_DIR/import_s3_history.py"

if [ ! -x "$PY" ]; then
  echo "error: venv python not found at $PY" >&2
  exit 2
fi
if [ ! -f "$IMPORT_SCRIPT" ]; then
  echo "error: import script not found at $IMPORT_SCRIPT" >&2
  exit 2
fi

mkdir -p "$LOG_DIR"

# Each line: <start-date> <end-date> <label>
RANGES=(
  "2024-01-01 2024-03-31 2024_Q1"
  "2024-04-01 2024-06-30 2024_Q2"
  "2024-07-01 2024-09-30 2024_Q3"
  "2024-10-01 2024-12-31 2024_Q4"
  "2025-01-01 2025-06-30 2025_H1"
  "2025-07-01 2025-12-31 2025_H2"
  "2026-01-01 2026-04-08 2026_YTD"
)

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SUMMARY="$LOG_DIR/summary_${STAMP}.log"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" | tee -a "$SUMMARY"
}

log "=== Starting quarterly backfill ==="
log "APP_DIR   : $APP_DIR"
log "Log dir   : $LOG_DIR"
log "Summary   : $SUMMARY"
log "Ranges    : ${#RANGES[@]}"

total=${#RANGES[@]}
failures=0
t_start=$(date +%s)

for idx in "${!RANGES[@]}"; do
  read -r start end label <<<"${RANGES[$idx]}"
  log "--- [$((idx+1))/$total] $label : $start -> $end ---"

  quarter_log="$LOG_DIR/${label}_${STAMP}.log"

  # -u: unbuffered stdout so `tail -f` stays live
  if "$PY" -u "$IMPORT_SCRIPT" \
        --start-date "$start" \
        --end-date "$end" \
        >"$quarter_log" 2>&1; then
    log "OK   $label (log: $(basename "$quarter_log"))"
  else
    rc=$?
    failures=$((failures + 1))
    log "FAIL $label rc=$rc (log: $(basename "$quarter_log"))"
  fi
done

t_end=$(date +%s)
elapsed=$((t_end - t_start))
log "=== Backfill complete in ${elapsed}s. $((total - failures))/$total ranges succeeded. ==="

if [ "$failures" -gt 255 ]; then failures=255; fi
exit "$failures"
