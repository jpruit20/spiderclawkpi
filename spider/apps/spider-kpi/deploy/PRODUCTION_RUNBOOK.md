# Spider KPI production runbook

This runbook defines the exact production operating model for the KPI stack.

Goal:
- no remembered heroics
- no implied tribal knowledge
- every remaining manual step is isolated and written down

## 1. Production topology

- Frontend: Vercel
  - `https://kpi.spidergrills.com`
- Backend API: DigitalOcean droplet via nginx + uvicorn
  - `https://api-kpi.spidergrills.com`
- Backend service: `spider-kpi.service`
- Backend repo path on droplet:
  - `/opt/spiderclawkpi/spider/apps/spider-kpi`
- Database: local Postgres on droplet
  - `127.0.0.1:5432`

## 2. What is automated now

### Source of truth for deploy automation
- workflow file: `.github/workflows/deploy-kpi.yml`

### Automated on push to `master`
If the required GitHub secrets are configured, this workflow does the following:

#### Frontend
1. checkout repo
2. install frontend dependencies
3. build frontend
4. deploy frontend to Vercel production

#### Backend
1. SSH to the production droplet
2. `git fetch origin`
3. `git checkout master`
4. `git pull --ff-only origin master`
5. install backend Python requirements into `.venv`
6. run Alembic migrations to `head`
7. restart `spider-kpi.service`
8. verify service is active
9. verify `http://127.0.0.1:8000/health`

### Practical consequence
For normal application code changes, deploys + migrations are already intended to be automatic on push.

## 3. Required secrets for automation to work

### Frontend deploy secrets
- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

### Backend deploy secrets
- `DO_KPI_HOST`
- `DO_KPI_USER`
- `DO_KPI_SSH_KEY`
- optional: `DO_KPI_PORT`

## 4. Remaining manual production steps

These are the only production tasks still expected to be manual.

### Manual step A - initial infrastructure provisioning
This includes one-time setup that is not done by the app deploy workflow:
- creating the droplet
- installing system packages
- creating `spider-kpi.service`
- configuring nginx
- creating Postgres/database/user
- creating the backend `.env`
- configuring Vercel project linkage
- adding GitHub Actions secrets

This is normal infrastructure setup, not daily operation.

### Manual step B - AWS telemetry stream infrastructure changes
App deploys do not create or modify AWS telemetry resources.
These remain separate infrastructure steps:
- enable DynamoDB Streams on `sg_device_shadows`
- ensure stream view is `NEW_IMAGE`
- deploy/update Lambda package
- set Lambda env vars
- attach IAM permissions
- create/update event source mapping

These are documented in:
- `apps/spider-kpi/deploy/aws-streams/README.md`

### Manual step C - telemetry historical recovery / export
Historical telemetry backfill is intentionally not part of push deploy.
It remains a controlled manual/ops workflow because it touches AWS backup/export state and can be expensive.

This is documented in:
- `apps/spider-kpi/deploy/aws-streams/EXPORT_BACKFILL_RUNBOOK.md`

### Manual step D - incident verification when automation fails
If GitHub Actions deploy fails, recovery is manual by definition. The exact recovery procedure is documented below so it is not heroic.

## 5. Exact backend recovery runbook if GitHub Actions deploy fails

Use this only if the automated backend deploy failed or backend secrets are missing.

### 5.1 SSH to the droplet
```bash
ssh -p <PORT> <USER>@<HOST>
```

### 5.2 Pull exact code and migrate
```bash
set -euo pipefail
cd /opt/spiderclawkpi/spider/apps/spider-kpi
git fetch origin
git checkout master
git pull --ff-only origin master
if [ -x .venv/bin/pip ]; then
  .venv/bin/pip install -r backend/requirements.txt
fi
if [ -x .venv/bin/alembic ]; then
  cd backend
  ../.venv/bin/alembic upgrade head
  cd ..
fi
sudo systemctl restart spider-kpi.service
sudo systemctl is-active spider-kpi.service
curl -fsS http://127.0.0.1:8000/health
```

### 5.3 Verify running revision
```bash
cd /opt/spiderclawkpi/spider/apps/spider-kpi
git rev-parse HEAD
```

## 6. Exact telemetry live-path verification runbook

Use this after any telemetry-related deploy or AWS change.

### 6.1 Backend service health
On droplet:
```bash
curl -fsS http://127.0.0.1:8000/health
```

### 6.2 Confirm telemetry stream table exists after migrations
On droplet:
```bash
cd /opt/spiderclawkpi/spider/apps/spider-kpi/backend
../.venv/bin/alembic current
../.venv/bin/alembic heads
```

Expected:
- current revision includes telemetry stream migrations
- DB is at `head`

### 6.3 Get app password for admin endpoints
On droplet:
```bash
APP_PASSWORD=$(grep '^APP_PASSWORD=' /opt/spiderclawkpi/spider/apps/spider-kpi/.env | cut -d= -f2-)
```

### 6.4 Check stream landing endpoint state
On droplet:
```bash
python3 - <<'PY'
from urllib.request import Request, urlopen
from pathlib import Path
import json
pw = Path('/opt/spiderclawkpi/spider/apps/spider-kpi/.env').read_text().split('APP_PASSWORD=',1)[1].splitlines()[0].strip()
r = Request('http://127.0.0.1:8000/api/admin/debug/telemetry-stream')
r.add_header('X-App-Password', pw)
print(urlopen(r).read().decode())
PY
```

Expected signals:
- `total > 0`
- `rows_last_15m` or `rows_last_60m` grows when traffic exists
- `fallback_active = false` during healthy stream flow

### 6.5 Check source health / summary mode in UI or API
Expected telemetry metadata:
- `source = sg_device_shadows_stream`
- `sample_source = dynamodb_stream`

If `sample_source != dynamodb_stream`, production has fallen back to bounded-scan telemetry.

## 7. Exact telemetry AWS infrastructure update runbook

This is the exact manual path when AWS telemetry infra itself must be changed.

### 7.1 Stream source requirements
- table: `sg_device_shadows`
- DynamoDB Streams enabled
- view type: `NEW_IMAGE`

### 7.2 Lambda requirements
- standalone handler file:
  - `apps/spider-kpi/deploy/aws-streams/lambda_handler_standalone.py`
- env vars:
  - `KPI_API_BASE_URL`
  - `KPI_API_PASSWORD`

### 7.3 Required post-change verification
After any Lambda or event-source change, verify all of these:
1. Lambda invocation succeeds in CloudWatch
2. `/api/admin/debug/telemetry-stream` shows new landed rows
3. Source Health shows `aws_telemetry_stream`
4. System Health does not show bounded-scan fallback warning

Reference doc:
- `apps/spider-kpi/deploy/aws-streams/README.md`

## 8. Exact telemetry historical recovery runbook

Historical telemetry recovery is not part of application deploy.
It is a separate ops action and must stay that way.

Use:
- `apps/spider-kpi/deploy/aws-streams/EXPORT_BACKFILL_RUNBOOK.md`

That runbook covers:
1. enabling PITR
2. exporting DynamoDB to S3
3. monitoring export completion
4. processing export offline
5. computing distinct `device_id` history

## 9. Failure-mode matrix

### Case: push deploy succeeded
- no manual action needed
- verify dashboard/API only if the change was sensitive

### Case: frontend deploy skipped
Cause:
- missing Vercel secrets

Action:
- configure `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`

### Case: backend deploy skipped
Cause:
- missing droplet SSH secrets

Action:
- configure `DO_KPI_HOST`, `DO_KPI_USER`, `DO_KPI_SSH_KEY`
- temporary fallback: run the backend recovery runbook in section 5

### Case: backend deploy ran but backend unhealthy
Action:
- run section 5 exactly
- verify migrations reached `head`
- check service logs

### Case: app healthy but telemetry not stream-backed
Action:
- run section 6
- then section 7
- determine whether stream landing stopped or summary fell back

### Case: need 12-month telemetry history
Action:
- do not deep-scan live table as primary path
- run section 8

## 10. Operational rule

The KPI stack should be treated as:
- *application deploy automation* via GitHub Actions
- *telemetry AWS infrastructure* via explicit runbook
- *historical telemetry recovery* via explicit export/offline runbook

If a step cannot be automated safely yet, it must stay written here exactly.

## 11. Current blunt assessment

### Already eliminated
- remembered backend deploy / migration sequence
- remembered telemetry architecture details
- remembered fallback interpretation

### Still intentionally manual
- AWS telemetry infrastructure changes
- historical DynamoDB export/backfill operations
- incident recovery when platform secrets or infrastructure are missing

Those are now isolated and documented rather than hidden in memory.