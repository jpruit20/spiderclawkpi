# Spider KPI Embedded Shopify App

This Vercel app replaces the prior hand-rolled OAuth redirect flow with a Shopify embedded app shell that relies on:

- Shopify-managed installation
- App Bridge authenticated `fetch()` to the app backend
- Backend session token verification
- Shopify token exchange for Admin API access

## Required environment variables

- `SHOPIFY_API_KEY`
- `SHOPIFY_API_SECRET`
- `SHOPIFY_APP_URL` (default: `https://kpi.spidergrills.com`)
- `SHOPIFY_APP_NAME` (default: `Spider KPI Dashboard`)
- `SHOPIFY_API_VERSION` (default: `2025-01`)
- `SHOPIFY_SCOPES`
- `SHOPIFY_TOKEN_CACHE_TTL_MS` (optional)

## Local run

```bash
cd spider-kpi
npm install
cp .env.example .env
npm start
```

Then expose the app over HTTPS (for example with Vercel preview or a tunnel) and point the Shopify app configuration at that URL while testing.

## Vercel deploy

1. Create/update the Vercel project rooted at `spider-kpi/`.
2. Add the environment variables from `.env.example` in Vercel.
3. Deploy.
4. Keep the production domain mapped to `https://kpi.spidergrills.com`.
5. Push the matching `shopify.app.toml` config to Shopify with Shopify CLI.

## Runtime test

Open the embedded app inside Shopify Admin. The home page automatically verifies:

1. request arrives with a valid session token
2. backend token exchange succeeds
3. GraphQL Admin API `shop` query succeeds
