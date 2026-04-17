# App backend (spidergrills.app) — persistent SSH tunnel runbook

The KPI backend reads from the Spider Grills app database via a long-lived,
read-only SSH tunnel. The DB is never exposed to the public internet; all
traffic is encrypted inside SSH between the KPI droplet and the app server.

## Topology

```
[KPI droplet]              [app server (firewalled)]
157.245.209.71  --ssh-->   ${APP_BACKEND_SSH_HOST}:22
                             │
                             └─── localhost:${APP_BACKEND_DB_PORT}
                                   (e.g. Postgres 5432)

Inside the KPI droplet the connector connects to
  127.0.0.1:${APP_BACKEND_TUNNEL_LOCAL_PORT}
which autossh forwards through the SSH channel.
```

## One-time setup

### On the KPI droplet (done — tracked here for reference)

```bash
# SSH key for the tunnel (generated at /root/.ssh/spider_tunnel_key)
ssh-keygen -t ed25519 -C "spider-kpi-tunnel@kpi.spidergrills.com" \
  -f /root/.ssh/spider_tunnel_key -N ""

apt-get install -y autossh
```

### On the app server (your team does this)

1. Create a dedicated unix user with no shell:
   ```bash
   adduser --disabled-password --shell /usr/sbin/nologin spider_tunnel
   ```
2. Install our public key into `~spider_tunnel/.ssh/authorized_keys` with
   restrictions so the key can ONLY open a tunnel to the DB port:
   ```
   no-pty,no-agent-forwarding,no-X11-forwarding,no-user-rc,permitopen="127.0.0.1:<DB_PORT>",from="157.245.209.71" ssh-ed25519 AAAA... spider-kpi-tunnel@kpi.spidergrills.com
   ```
3. Allow the KPI droplet's outbound IP on port 22:
   - Source IP: `157.245.209.71`
4. Create a read-only DB user `spider_kpi_ro` with `SELECT` on the tables we need.

## Droplet env vars

Populate in `/opt/spiderclawkpi/spider/apps/spider-kpi/.env`:

```
APP_BACKEND_SSH_HOST=app.spidergrills.app
APP_BACKEND_SSH_USER=spider_tunnel
APP_BACKEND_SSH_PORT=22
APP_BACKEND_DB_HOST=127.0.0.1          # as seen from app server
APP_BACKEND_DB_PORT=5432               # real DB port
APP_BACKEND_TUNNEL_LOCAL_PORT=15432    # chosen per-droplet to avoid collision
APP_BACKEND_DB_URL=postgresql+psycopg://spider_kpi_ro:PASS@127.0.0.1:15432/appdb
APP_BACKEND_SYNC_INTERVAL_MINUTES=30
APP_BACKEND_LOOKBACK_DAYS=120
```

## Bring up the tunnel

```bash
# One-time host-key cache (accept new host key)
ssh -i /root/.ssh/spider_tunnel_key -o StrictHostKeyChecking=accept-new \
    -p $APP_BACKEND_SSH_PORT -N -o BatchMode=yes \
    -L ${APP_BACKEND_TUNNEL_LOCAL_PORT}:${APP_BACKEND_DB_HOST}:${APP_BACKEND_DB_PORT} \
    $APP_BACKEND_SSH_USER@$APP_BACKEND_SSH_HOST &
# Ctrl-C after "Entering interactive session" is shown; known_hosts is now primed.

# Install systemd unit
cp deploy/spider-kpi-tunnel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now spider-kpi-tunnel.service
systemctl status spider-kpi-tunnel.service

# Verify the forward is live
ss -lnt | grep 15432
```

## Testing from the droplet

```bash
# Using psql (adjust for engine):
apt-get install -y postgresql-client
psql "$APP_BACKEND_DB_URL" -c "SELECT 1"
```

## Restart the KPI backend so it picks up the new env

```bash
systemctl restart spider-kpi.service
journalctl -u spider-kpi.service --since "1 min ago" | grep -i app_backend
```

## Rotation

- **Tunnel key**: regenerate `/root/.ssh/spider_tunnel_key`, send the new
  public key to the app team, swap in `authorized_keys`.
- **DB password**: rotate on the app server, update
  `APP_BACKEND_DB_URL` in `.env`, `systemctl restart spider-kpi.service`.
