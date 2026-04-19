#!/bin/bash
# Auto-pull backend changes from master and restart if new commits found.
# Runs every minute via cron on the production droplet.
#
# Safety:
#   * Captures the current SHA before pulling.
#   * If the post-restart health check fails, reverts to that SHA and
#     restarts again.
#   * Fires a deploy-outcome notification (email + Slack DM) on every
#     non-noop outcome: success, rolled_back, or double-failure.
#
# Install:
#   chmod +x /opt/spiderclawkpi/spider/apps/spider-kpi/deploy/auto-pull-backend.sh
#   echo "* * * * * /opt/spiderclawkpi/spider/apps/spider-kpi/deploy/auto-pull-backend.sh >> /var/log/spider-kpi-autopull.log 2>&1" | crontab -

set -euo pipefail
REPO_DIR="/opt/spiderclawkpi/spider"
APP_DIR="$REPO_DIR/apps/spider-kpi"
SERVICE="spider-kpi.service"
LOCK="/tmp/spider-kpi-autopull.lock"
NOTIFIER="$APP_DIR/scripts/notify_deploy_outcome.py"
VENV_PY="$APP_DIR/.venv/bin/python"
HEALTH_URL="http://127.0.0.1:8000/health"
SOURCE_TAG="auto-pull"

# Prevent concurrent runs (also guards against overlap with GH-Actions deploys).
exec 200>"$LOCK"
flock -n 200 || exit 0

cd "$REPO_DIR"

git fetch origin master --quiet 2>/dev/null || exit 0

OLD_SHA=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$OLD_SHA" = "$REMOTE" ]; then
    exit 0
fi

log() { echo "$(date -Iseconds) [autopull] $*"; }

notify() {
    # notify <outcome> [error_msg]
    local outcome="$1"; shift
    local error_msg="${1:-}"
    if [ ! -x "$VENV_PY" ] || [ ! -f "$NOTIFIER" ]; then
        log "notifier unavailable — skipping notification ($outcome)"
        return 0
    fi
    "$VENV_PY" "$NOTIFIER" \
        --outcome "$outcome" \
        --old-sha "$OLD_SHA" \
        --new-sha "$NEW_SHA" \
        --source "$SOURCE_TAG" \
        ${error_msg:+--error "$error_msg"} || log "notify failed (outcome=$outcome)"
}

health_ok() {
    for _ in $(seq 1 20); do
        if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

log "new commits detected: $OLD_SHA → $REMOTE"
git pull --ff-only origin master
NEW_SHA=$(git rev-parse HEAD)
log "pulled to $NEW_SHA. Restarting $SERVICE..."

if systemctl restart "$SERVICE" && health_ok; then
    log "new SHA healthy"
    notify success
    exit 0
fi

log "NEW SHA UNHEALTHY — rolling back to $OLD_SHA"
if git checkout "$OLD_SHA" --quiet \
    && systemctl restart "$SERVICE" \
    && health_ok; then
    log "rollback healthy — staying on $OLD_SHA"
    notify rolled_back "post-restart health check failed on $NEW_SHA"
    # Stay on OLD_SHA; next run will try to re-pull. If master still has
    # the broken commit, we will roll back again (and renotify).
    exit 1
fi

log "ROLLBACK ALSO FAILED — service is likely down"
notify failure "deploy + rollback both failed; investigate on droplet"
exit 2
