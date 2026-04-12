# Expose Spider KPI Backend API

Goal:
- keep `kpi.spidergrills.com` on Vercel for the frontend
- expose the persistent FastAPI backend on `api-kpi.spidergrills.com`
- let the Vercel frontend call the backend via `VITE_API_BASE`

## Target architecture

- Frontend: `https://kpi.spidergrills.com`
- Backend API: `https://api-kpi.spidergrills.com`
- Local backend process: `127.0.0.1:8000`

## 1. DNS

Create a DNS record for:

- `api-kpi.spidergrills.com`

Point it to the server that already runs the KPI backend.

## 2. Nginx reverse proxy

Use:

- `deploy/nginx-api-kpi.spidergrills.com.conf`

Typical install flow:

```bash
sudo cp apps/spider-kpi/deploy/nginx-api-kpi.spidergrills.com.conf /etc/nginx/sites-available/api-kpi.spidergrills.com.conf
sudo ln -s /etc/nginx/sites-available/api-kpi.spidergrills.com.conf /etc/nginx/sites-enabled/api-kpi.spidergrills.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 3. TLS certificate

After DNS resolves to the host, issue TLS:

```bash
sudo certbot --nginx -d api-kpi.spidergrills.com
```

## 4. Backend CORS

Update `apps/spider-kpi/.env` so `CORS_ORIGINS` includes the Vercel frontend:

```env
CORS_ORIGINS=["http://localhost:3000","https://kpi.spidergrills.com"]
```

If you want Vercel preview deployments to work against the live backend too, include the preview domain(s) or a broader allowlist strategy.

## 5. Restart the backend

After `.env` changes:

```bash
sudo systemctl --user restart openclaw-gateway || true
sudo systemctl restart spider-kpi || true
```

Or restart the KPI backend using the service/process manager actually used on the host.

## 6. Verify backend reachability

Expected checks:

```bash
curl -I https://api-kpi.spidergrills.com/health
curl -I https://api-kpi.spidergrills.com/api/overview
```

`/health` should return `200`.

`/api/overview` may return `401/403` if dashboard auth is enabled and no browser session or admin header is supplied; that is still a valid sign the route is reachable.

## 7. Vercel frontend env var

Set in Vercel for the `kpi_dashboard` frontend project:

```env
VITE_API_BASE=https://api-kpi.spidergrills.com
```

Do not ship `APP_PASSWORD` to the browser. Keep it server-side for `/api/admin/*` and machine-to-machine validation only.

## 8. Frontend project settings in Vercel

The frontend Vercel project should use:

- Root Directory: `apps/spider-kpi/frontend`
- Framework: `Vite`
- Build Command: `npm run build`
- Output Directory: `dist`

## 9. Final verification

Once DNS, nginx, TLS, CORS, and Vercel env vars are set:

1. redeploy the Vercel frontend
2. open `https://kpi.spidergrills.com`
3. confirm dashboard API calls succeed against `https://api-kpi.spidergrills.com`

## Notes

- The backend should remain on persistent infrastructure; do not move the scheduler/Postgres/API stack into a frontend-only Vercel deployment.
- This setup enables frontend auto deploys via GitHub→Vercel while keeping the data pipeline stable on the host.
