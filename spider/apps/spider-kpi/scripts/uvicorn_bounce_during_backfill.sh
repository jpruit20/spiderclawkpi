#!/usr/bin/env bash
# Hourly safety net: restart the uvicorn service (spider-kpi.service)
# if — and only if — the S3 v2 backfill is currently running.
#
# Why this exists (Joseph 2026-04-18): during the 13h phase-2 run we
# observed uvicorn's RSS grow from ~650MB at deploy to 2.4GB over ~45
# min of normal production traffic. At 2.4GB + 2.2GB backfill RSS on a
# 3.8GB droplet, OOM-killer fired, terminated the backfill, and the
# heartbeat-restart loop kept re-OOMing because uvicorn was still
# hoarding memory. Cascade wiped out ~2h of phase-2 progress before
# we noticed.
#
# Rather than chase down the uvicorn memory leak mid-backfill, we
# bounce the service hourly as insurance. Users see a ~3s hiccup per
# hour — acceptable. Once the backfill completes this timer becomes
# a no-op (and I'll delete the unit once the leak is properly root-
# caused, tracked in the Operations page followup).
#
# Idempotent + safe to re-run. Matches the existing heartbeat script
# convention — logs to its own dedicated file so it doesn't pollute
# the backfill log.

set -euo pipefail

LOG=/var/log/spider-kpi-uvicorn-bounce.log
TS=$(date -u +"%Y-%m-%d %H:%M:%SZ")

if ! pgrep -f "import_s3_history_v2.py" > /dev/null; then
    echo "$TS backfill not running — skipping bounce (will become no-op)" >> "$LOG"
    exit 0
fi

RSS_KB=$(ps -o rss= -C python -U root 2>/dev/null \
    | awk 'BEGIN{max=0} {if($1>max)max=$1} END{print max+0}')

echo "$TS backfill active, largest python RSS=${RSS_KB}KB — bouncing spider-kpi" >> "$LOG"
systemctl restart spider-kpi
sleep 3
if systemctl is-active --quiet spider-kpi; then
    echo "$TS spider-kpi restart OK" >> "$LOG"
else
    echo "$TS spider-kpi FAILED to come back — manual intervention needed" >> "$LOG"
    exit 1
fi
