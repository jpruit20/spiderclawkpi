#!/bin/bash
# Auto-pull backend changes from master and restart if new commits found.
# Runs every minute via cron on the production droplet.
#
# Safety:
#   * Captures the current SHA before pulling.
#   * If the post-restart health check fails, reverts to that SHA (via
#     ``git reset --hard`` so we stay on ``master``, NOT ``checkout`` which
#     detaches HEAD and soft-bricks future cron runs).
#   * Writes the bad SHA to a rejection marker. Future deploy runs skip
#     pulling until ``origin/master`` advances past that SHA — avoids the
#     infinite redeploy/rollback loop when master still has the bad tip.
#   * Install deps + run migrations on every pull so a new package or
#     schema change doesn't silently break the service (the commit message
#     that shipped the rollback initially claimed this ran here — it
#     didn't, was a real gap).
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
REJECTED_MARKER="/var/lib/spider-kpi/.deploy-rejected-sha"
NOTIFIER="$APP_DIR/scripts/notify_deploy_outcome.py"
VENV_PY="$APP_DIR/.venv/bin/python"
VENV_PIP="$APP_DIR/.venv/bin/pip"
VENV_ALEMBIC="$APP_DIR/.venv/bin/alembic"
HEALTH_URL="http://127.0.0.1:8000/health"
SOURCE_TAG="auto-pull"

mkdir -p "$(dirname "$REJECTED_MARKER")"

# Prevent concurrent runs (also guards against overlap with GH-Actions
# deploys — both participate in the same lock by convention, see the
# deploy workflows).
exec 200>"$LOCK"
flock -n 200 || exit 0

cd "$REPO_DIR"

log() { echo "$(date -Iseconds) [autopull] $*"; }

# If a prior rollback left us in detached HEAD, return to master before
# doing anything else. Old code used ``git checkout $SHA --quiet`` for
# rollback, which detaches; future cron runs then errored on ``git pull``
# with "You are not currently on a branch" and silently looped.
if ! git symbolic-ref -q HEAD >/dev/null; then
    log "detached HEAD detected — returning to master"
    git checkout master --quiet || {
        log "FATAL: could not return to master; manual intervention needed"
        exit 3
    }
fi

git fetch origin master --quiet 2>/dev/null || exit 0

OLD_SHA=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$OLD_SHA" = "$REMOTE" ]; then
    exit 0
fi

# Poison-pill check: if origin/master is exactly a SHA we already rolled
# back from, don't redeploy it. Wait for master to advance to a new SHA
# (implicitly a fix). Marker is cleared on successful deploy below.
if [ -f "$REJECTED_MARKER" ]; then
    REJECTED=$(tr -d '[:space:]' < "$REJECTED_MARKER" 2>/dev/null || true)
    if [ -n "$REJECTED" ] && [ "$REMOTE" = "$REJECTED" ]; then
        # Log hourly, not every minute, to avoid log spam.
        if [ "$(date +%M)" = "07" ]; then
            log "origin/master ($REMOTE) matches rejected SHA — skipping (marker will clear when master advances)"
        fi
        exit 0
    fi
fi

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

install_deps() {
    # Idempotent when nothing changed (pip checks installed versions).
    "$VENV_PIP" install -q -r "$APP_DIR/backend/requirements.txt"
}

run_migrations() {
    if [ -x "$VENV_ALEMBIC" ]; then
        (cd "$APP_DIR/backend" && "$VENV_ALEMBIC" upgrade head)
    fi
}

log "new commits detected: $OLD_SHA → $REMOTE"
git pull --ff-only origin master
NEW_SHA=$(git rev-parse HEAD)

# Install deps + migrations BEFORE restart so the service comes up on
# the correct environment. Previously the cron script skipped this,
# which meant a commit introducing a new Python dep or alembic revision
# would deploy broken state if cron won the race against GH-Actions.
log "pulled to $NEW_SHA — installing deps + migrations"
if ! install_deps; then
    log "pip install FAILED on $NEW_SHA — rolling back before restart"
    git reset --hard "$OLD_SHA" --quiet
    install_deps || true  # best effort; OLD_SHA's deps should already be there
    echo "$NEW_SHA" > "$REJECTED_MARKER"
    notify rolled_back "pip install failed for $NEW_SHA"
    exit 1
fi
if ! run_migrations; then
    log "alembic upgrade FAILED on $NEW_SHA — rolling back code, LEAVING migrations in place"
    git reset --hard "$OLD_SHA" --quiet
    install_deps || true
    echo "$NEW_SHA" > "$REJECTED_MARKER"
    notify rolled_back "alembic upgrade failed for $NEW_SHA — DB may be in an intermediate state, investigate"
    exit 1
fi

log "restarting $SERVICE..."
if systemctl restart "$SERVICE" && health_ok; then
    log "new SHA healthy"
    # Successful deploy — clear any stale rejection marker.
    rm -f "$REJECTED_MARKER"
    notify success
    exit 0
fi

log "NEW SHA UNHEALTHY — rolling back to $OLD_SHA"
# git reset --hard, NOT checkout — keeps us on the master branch so
# subsequent cron runs can ff-pull cleanly once master advances.
if git reset --hard "$OLD_SHA" --quiet \
    && install_deps \
    && systemctl restart "$SERVICE" \
    && health_ok; then
    log "rollback healthy — staying on $OLD_SHA; marking $NEW_SHA as rejected"
    echo "$NEW_SHA" > "$REJECTED_MARKER"
    notify rolled_back "post-restart health check failed on $NEW_SHA"
    exit 1
fi

log "ROLLBACK ALSO FAILED — service is likely down"
notify failure "deploy + rollback both failed; investigate on droplet"
exit 2
