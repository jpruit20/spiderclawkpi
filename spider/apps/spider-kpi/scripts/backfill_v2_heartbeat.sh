#!/usr/bin/env bash
# Self-healing heartbeat for the v2 S3 telemetry backfill.
#
# Runs every 10 minutes via systemd timer. Detects one of three states
# for the long-running Phase 2 backfill and takes the appropriate action:
#
#   state                                  action
#   -----------------------------------    ----------------------------
#   running                                no-op (all good)
#   completed (temp dir empty)             no-op (auto_regen_watcher fires)
#   flagged done (marker file present)     no-op (already handled)
#   dead but work remains                  restart, log the incident
#
# Restart uses the same invocation as the original launch (--skip-phase1)
# so temp files aren't re-extracted. psycopg writes are idempotent so
# re-running mid-day is safe.

set -euo pipefail

APP_DIR=/opt/spiderclawkpi/spider/apps/spider-kpi
TEMP_DIR=/tmp/s3_backfill
DONE_FLAG=/var/lib/spider-kpi/comprehensive-regen-done
LOG=/var/log/spider-kpi-backfill-v2.log
HEARTBEAT_LOG=/var/log/spider-kpi-backfill-heartbeat.log
PIDFILE=/var/run/spider-kpi-backfill-v2.pid

mkdir -p "$(dirname "$PIDFILE")" /var/lib/spider-kpi
TS=$(date -u +"%Y-%m-%d %H:%M:%SZ")

# Running?
if pgrep -f "import_s3_history_v2.py" > /dev/null; then
    echo "$TS running, no action" >> "$HEARTBEAT_LOG"
    exit 0
fi

# Completion markers
if [ ! -d "$TEMP_DIR" ] || [ -z "$(ls -A "$TEMP_DIR" 2>/dev/null || true)" ]; then
    echo "$TS temp dir empty — backfill complete, auto_regen_watcher will finalize" >> "$HEARTBEAT_LOG"
    exit 0
fi

if [ -f "$DONE_FLAG" ]; then
    echo "$TS done-flag present — treating as terminally complete, not restarting" >> "$HEARTBEAT_LOG"
    exit 0
fi

# Work remains + process is gone. Restart.
N_FILES=$(ls -A "$TEMP_DIR" 2>/dev/null | wc -l)
echo "$TS *** restarting backfill (files remaining=$N_FILES) ***" | tee -a "$HEARTBEAT_LOG" >> "$LOG"

cd "$APP_DIR"
nohup "$APP_DIR/.venv/bin/python" scripts/import_s3_history_v2.py --skip-phase1 \
    >> "$LOG" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PIDFILE"
disown "$NEW_PID" 2>/dev/null || true
echo "$TS relaunched as PID $NEW_PID" >> "$HEARTBEAT_LOG"
