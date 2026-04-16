#!/bin/bash
# Auto-pull backend changes from master and restart if new commits found.
# Runs every minute via cron on the production droplet.
#
# Install:
#   chmod +x /opt/spiderclawkpi/spider/apps/spider-kpi/deploy/auto-pull-backend.sh
#   echo "* * * * * /opt/spiderclawkpi/spider/apps/spider-kpi/deploy/auto-pull-backend.sh >> /var/log/spider-kpi-autopull.log 2>&1" | crontab -

set -euo pipefail
REPO_DIR="/opt/spiderclawkpi/spider"
SERVICE="spider-kpi.service"
LOCK="/tmp/spider-kpi-autopull.lock"

# Prevent concurrent runs
exec 200>"$LOCK"
flock -n 200 || exit 0

cd "$REPO_DIR"

# Fetch latest from origin without modifying working tree
git fetch origin master --quiet 2>/dev/null || exit 0

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "$(date -Iseconds) New commits detected: $LOCAL → $REMOTE"
git pull --ff-only origin master
echo "$(date -Iseconds) Pulled. Restarting $SERVICE..."
systemctl restart "$SERVICE"
echo "$(date -Iseconds) Service restarted."
