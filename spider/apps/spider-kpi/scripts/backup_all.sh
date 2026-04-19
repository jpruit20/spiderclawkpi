#!/usr/bin/env bash
# Comprehensive backup pipeline — daily safeguard for all critical data.
#
# Built 2026-04-19 after Joseph flagged that we'd built up a lot of
# critical, non-reconstructable data (2.5 years of telemetry sessions,
# full TW archive, Opus-generated reports) sitting on one droplet
# with no off-box copy.
#
# What this script backs up (in order of criticality):
#   1. Postgres database            (all tables, compressed pg_dump)
#   2. TW archive                   (/data/tw-archive/*.json.gz)
#   3. Telemetry reports + markdown (/opt/spiderclawkpi/spider/docs/)
#   4. .env file                    (contains API keys — losing it is days of rebuild)
#   5. Systemd unit files           (quick to reconstruct but cheap to include)
#
# Storage:
#   - Local:  /data/backups/ with rotation (14 days of pg_dumps, all others overwritten)
#   - Remote: s3://spider-kpi-telemetry-export/backups/  (same bucket, different prefix;
#             keeps perms simple, bucket is already account-private)
#
# Integrity:
#   - pg_dump uses --clean --if-exists → restore via `gunzip -c | psql`
#   - sha256sum manifest for each snapshot → catches silent corruption
#   - S3 bucket versioning (enabled separately) → accidental delete recovery
#   - Log + non-zero exit triggers spider-kpi-job-failure@.service

set -euo pipefail

APP_DIR=/opt/spiderclawkpi/spider/apps/spider-kpi
BACKUP_DIR=/data/backups
PG_DIR=$BACKUP_DIR/postgres
MISC_DIR=$BACKUP_DIR/misc
LOG=/var/log/spider-kpi-backup.log
S3_BUCKET=s3://spider-kpi-telemetry-export/backups

mkdir -p "$PG_DIR" "$MISC_DIR"
TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
DATE=$(date -u +"%Y-%m-%d")

log() {
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ')  $*" | tee -a "$LOG"
}

fail() {
    log "FAIL: $*"
    exit 1
}

# S3 operations can fail for reasons we recover from (IAM policy not
# yet in place — known state today). Warn but don't kill the whole run;
# local backup is still useful. When permissions land, S3 sync
# activates transparently.
s3_try() {
    local what=$1
    shift
    if "$@"; then
        log "s3 $what: ok"
    else
        log "WARN: s3 $what failed — continuing with local-only backup (likely IAM not yet configured; see docs/BACKUPS.md)"
        S3_FAILURES=$((S3_FAILURES + 1))
    fi
}
S3_FAILURES=0

# --- AWS credentials -------------------------------------------------
# Re-use the .env so we don't duplicate config. Just the AWS bits —
# don't leak the whole file into this process's environment.
set -a
# shellcheck disable=SC1091
. <(grep -E '^AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|REGION)=' "$APP_DIR/.env")
set +a
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"

AWS_CLI="$APP_DIR/.venv/bin/aws"

log "=== backup run start: $TS ==="

# --- Step 1: Postgres dump -------------------------------------------
DUMP_FILE="$PG_DIR/spider_kpi_$DATE.sql.gz"
log "postgres: dumping to $DUMP_FILE"
if ! sudo -u postgres pg_dump \
        --clean --if-exists \
        --format=plain \
        spider_kpi \
    | gzip -9 > "$DUMP_FILE.tmp"; then
    rm -f "$DUMP_FILE.tmp"
    fail "pg_dump failed"
fi
mv "$DUMP_FILE.tmp" "$DUMP_FILE"
DUMP_SIZE=$(stat -c%s "$DUMP_FILE")
log "postgres: dump complete, $DUMP_SIZE bytes"

# Sanity: dump smaller than 1MB would mean something's wrong.
if [ "$DUMP_SIZE" -lt 1048576 ]; then
    fail "pg_dump suspiciously small ($DUMP_SIZE bytes) — not uploading"
fi

# --- Step 2: rotate local pg_dumps (keep 14) -------------------------
log "postgres: rotating local dumps"
# shellcheck disable=SC2012
ls -1t "$PG_DIR"/spider_kpi_*.sql.gz 2>/dev/null | tail -n +15 | while read -r OLD; do
    log "  rm $OLD"
    rm -f "$OLD"
done

# --- Step 3: misc snapshot (env, unit files) -------------------------
log "misc: snapshotting secrets + systemd units"
ENV_SNAPSHOT="$MISC_DIR/env_$DATE.txt.gz"
cp "$APP_DIR/.env" /tmp/.env.backup.$$
gzip -9 -c /tmp/.env.backup.$$ > "$ENV_SNAPSHOT"
rm -f /tmp/.env.backup.$$

UNITS_SNAPSHOT="$MISC_DIR/systemd_units_$DATE.tar.gz"
tar -czf "$UNITS_SNAPSHOT" \
    -C /etc/systemd/system \
    $(ls /etc/systemd/system | grep -E '^spider-kpi') \
    2>/dev/null || log "WARN: systemd units snapshot partial"

# --- Step 4: sha256 manifest ------------------------------------------
MANIFEST="$BACKUP_DIR/manifest_$DATE.sha256"
(
    cd "$BACKUP_DIR" && find postgres misc -type f -newer "$BACKUP_DIR/last_manifest" 2>/dev/null -print 2>/dev/null | sort | xargs -r sha256sum > "$MANIFEST" || true
)
if [ ! -s "$MANIFEST" ]; then
    (cd "$BACKUP_DIR" && find postgres misc -type f | sort | xargs sha256sum > "$MANIFEST")
fi
touch "$BACKUP_DIR/last_manifest"
log "manifest: $MANIFEST ($(wc -l < "$MANIFEST") files)"

# --- Step 5: sync everything to S3 -----------------------------------
s3_try "postgres dumps" "$AWS_CLI" s3 sync "$PG_DIR"/ "$S3_BUCKET/postgres/" \
    --only-show-errors --exclude '*.tmp'

s3_try "misc (env + systemd units)" "$AWS_CLI" s3 sync "$MISC_DIR"/ "$S3_BUCKET/misc/" \
    --only-show-errors

s3_try "TW archive" "$AWS_CLI" s3 sync /data/tw-archive/ "$S3_BUCKET/tw-archive/" \
    --only-show-errors --size-only

s3_try "telemetry reports + docs" "$AWS_CLI" s3 sync /opt/spiderclawkpi/spider/docs/ "$S3_BUCKET/docs/" \
    --only-show-errors --exclude '.git/*' --exclude '*.draft.*'

s3_try "manifest upload" "$AWS_CLI" s3 cp "$MANIFEST" "$S3_BUCKET/manifests/" \
    --only-show-errors

# --- Step 6: verify S3 has the latest dump (only if S3 works) --------
if [ "$S3_FAILURES" -eq 0 ]; then
    DUMP_NAME=$(basename "$DUMP_FILE")
    S3_CHECK=$("$AWS_CLI" s3 ls "$S3_BUCKET/postgres/$DUMP_NAME" 2>&1 | grep "$DUMP_NAME" || true)
    if [ -z "$S3_CHECK" ]; then
        fail "verification: $DUMP_NAME not found in S3 after sync"
    fi
    log "verification: $DUMP_NAME confirmed in S3 — FULLY PROTECTED (local + off-droplet)"
else
    log "WARN: $S3_FAILURES S3 operation(s) failed — local backup complete at $BACKUP_DIR; off-droplet copy MISSING. See docs/BACKUPS.md to unlock S3 sync."
fi

log "=== backup run complete: $(date -u +'%Y-%m-%dT%H:%M:%SZ'), s3_failures=$S3_FAILURES ==="
# Exit non-zero on S3 failure so the systemd job-failure handler notices
# we're running in degraded mode — we still WANT alerts about this.
[ "$S3_FAILURES" -eq 0 ] || exit 2
