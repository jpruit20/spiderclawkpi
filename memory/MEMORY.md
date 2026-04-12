# Cross-Topic Operating Rules

## Deployment Workflow

**Auto-deploy on completion**: When changes are finished and build passes, automatically:
1. Commit changes with clear message
2. Push to feature branch
3. Create PR and merge to master
4. Do NOT ask for permission to deploy — just deploy

Frontend auto-deploys to kpi.spidergrills.com via Vercel when merged to master.

## Memory Protocol (KPI Dashboard Workstream)

After every meaningful discussion or decision:
- Update `memory/sessions/kpi.md` with a concise checkpoint
- Promote durable rules/definitions to `memory/topics/kpi_dashboard.md` when validated
- Promote cross-topic operating rules to this file (`MEMORY.md`)
- Do not store raw transcript unless explicitly requested

## Repository Structure

- Frontend: `spider/apps/spider-kpi/frontend/`
- Backend: `spider/apps/spider-kpi/backend/`
- Live dashboard: kpi.spidergrills.com
