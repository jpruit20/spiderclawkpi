# Spider KPI Vercel Frontend Deploy

## Recommended production shape

Use **Vercel for the React/Vite frontend only**.

Keep the backend on persistent infrastructure because it requires:
- PostgreSQL
- APScheduler
- long-running source syncs
- webhook handling

Production split:
- **Frontend:** Vercel
- **Backend API:** persistent host/VPS/container
- **Domain:** `kpi.spidergrills.com` on the Vercel frontend
- **API base:** external backend URL via `VITE_API_BASE`

## Why not deploy the full app to Vercel?

The backend is not just a stateless request handler. It also runs recurring sync jobs and stores source-health/run state. That makes it a poor fit for a frontend-only Vercel deployment model.

## Required condition for auto deploys

Vercel auto deploys require the project to be connected to a Git provider:
- GitHub
- GitLab
- Bitbucket

If the repo is not connected to a Git remote/provider, Vercel can still deploy manually, but future updates will **not** auto deploy.

## Vercel project settings

Create or update the Vercel project with:

- **Root Directory:** `apps/spider-kpi/frontend`
- **Framework Preset:** Vite
- **Install Command:** `npm install`
- **Build Command:** `npm run build`
- **Output Directory:** `dist`

`frontend/vercel.json` already provides SPA rewrites for React Router and long-cache headers for built assets.

## Required Vercel environment variables

Set these in Vercel for Production (and Preview if desired):

- `VITE_API_BASE=https://<your-backend-api-origin>`
- `VITE_APP_PASSWORD=<app-password-if-auth-enabled>`

Examples:

- `VITE_API_BASE=https://api-kpi.spidergrills.com`
- or `VITE_API_BASE=https://kpi-api.spidergrills.com`

For the current Spider KPI deployment, prefer:

- `VITE_API_BASE=https://api-kpi.spidergrills.com`

If backend auth is disabled, `VITE_APP_PASSWORD` can be omitted.

## Backend requirements for the Vercel frontend

The backend must:
- be publicly reachable by the browser
- serve the current FastAPI API
- allow CORS from the frontend origin(s)

Recommended backend CORS values should include at minimum:
- `https://kpi.spidergrills.com`
- relevant Vercel preview domains if previews should work against the live backend

## Domain setup

Point `kpi.spidergrills.com` to the Vercel frontend project.

The backend should live on a separate API domain such as:
- `api-kpi.spidergrills.com`
- `kpi-api.spidergrills.com`

This avoids mixing static frontend hosting and persistent API hosting on the same Vercel frontend project.

## Auto deploy workflow

Once the project is connected to Git and the custom domain is attached:

1. push changes to the tracked branch
2. Vercel auto-builds the frontend from `apps/spider-kpi/frontend`
3. `kpi.spidergrills.com` updates automatically on successful production deploys

## Operational note

Frontend auto deploys do **not** deploy backend connector/scheduler changes.

Backend changes still require deployment to the persistent API host.

So the long-term clean model is:
- frontend UI changes -> auto deploy via Vercel
- backend API/data-pipeline changes -> deploy to persistent backend host
