# Spider KPI Production Runbook

## Production topology

- Frontend: Vercel (`https://kpi.spidergrills.com`)
- Backend API: DigitalOcean droplet via nginx + uvicorn (`https://api-kpi.spidergrills.com`)
- Backend service: `spider-kpi.service`
- Backend repo path on droplet: `/opt/spiderclawkpi/spider/apps/spider-kpi`
- Database: local Postgres on droplet (`127.0.0.1:5432`)

## Current deploy model

### Frontend
Frontend changes pushed to GitHub can be auto-deployed by Vercel if the Vercel project is connected to the repo/branch.

### Backend
Backend changes are **not yet fully automatic** unless an external deploy hook / GitHub Action / pull-on-push mechanism is configured on the droplet.

Current reliable backend deploy flow:
1. push code to GitHub
2. SSH to droplet
3. pull latest `origin/master`
4. restart `spider-kpi.service`
5. run admin backfill/sync if needed
6. validate DB + API output

## Standard backend deploy

On the droplet:

```bash
cd /opt/spiderclawkpi/spider/apps/spider-kpi
git fetch origin
git checkout master
git pull --ff-only origin master
git rev-parse HEAD
systemctl restart spider-kpi.service
systemctl is-active spider-kpi.service
curl -i http://127.0.0.1:8000/health
```

## Shopify truth recovery / validation

### Authenticate for admin endpoints

```bash
APP_PASSWORD=$(grep '^APP_PASSWORD=' /opt/spiderclawkpi/spider/apps/spider-kpi/.env | cut -d= -f2-)
```

### Run backfill and recent sync

```bash
python3 - <<'PY'
from urllib.request import Request, urlopen
from pathlib import Path
pw = Path('/opt/spiderclawkpi/spider/apps/spider-kpi/.env').read_text().split('APP_PASSWORD=',1)[1].splitlines()[0].strip()
for url in [
    'http://127.0.0.1:8000/api/admin/backfill/shopify',
    'http://127.0.0.1:8000/api/admin/run-sync/shopify',
]:
    r = Request(url, method='POST')
    r.add_header('X-App-Password', pw)
    print(url, urlopen(r).read().decode())
PY
```

### Validate DB rows directly

```bash
python3 scripts/validate_shopify_window.py --db-url "$(grep '^DATABASE_URL=' .env | cut -d= -f2-)" --start 2026-03-29 --end 2026-04-05
```

## Fast validation targets

After a Shopify deploy/backfill, validate all of these:
- `shopify_orders_daily`
- `kpi_daily`
- `GET /api/overview`
- dashboard UI 7-day window

## Known important rule

Shopify polling must rebuild touched dates from canonical latest per-order state.
Do **not** overwrite `shopify_orders_daily` directly from a partial recent poll window.

## Backend automation status

Implemented:
- GitHub Actions deploy workflow for backend code deploys (`Deploy KPI Backend`)
- GitHub Actions manual Shopify backfill workflow (`Backfill KPI Shopify`)
- GitHub Actions manual connector sync workflow (`Run KPI Connectors`)

Current model:
- backend code changes can auto-deploy on push to `master`
- historical Shopify repair/backfill is manually triggerable from GitHub Actions with explicit window inputs

## Manual backfill workflow

Use the `Backfill KPI Shopify` workflow in GitHub Actions when you need to:
- repair historical Shopify days
- repopulate a wider historical window after connector logic changes
- validate `shopify_orders_daily` and `kpi_daily` for a specific date range
