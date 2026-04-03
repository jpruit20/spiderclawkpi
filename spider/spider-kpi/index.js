const express = require('express');
const crypto = require('crypto');
const { URL } = require('url');

const app = express();
app.use(express.json());

const APP_NAME = process.env.SHOPIFY_APP_NAME || 'Spider KPI Dashboard';
const APP_URL = process.env.SHOPIFY_APP_URL || 'https://kpi.spidergrills.com';
const API_KEY = process.env.SHOPIFY_API_KEY;
const API_SECRET = process.env.SHOPIFY_API_SECRET;
const SCOPES = process.env.SHOPIFY_SCOPES || [
  'read_orders',
  'read_all_orders',
  'read_products',
  'read_customers',
  'read_inventory',
  'read_fulfillments',
  'read_locations',
  'read_reports',
  'read_returns',
  'read_markets',
].join(',');
const SHOPIFY_API_VERSION = process.env.SHOPIFY_API_VERSION || '2025-01';
const TOKEN_CACHE_TTL_MS = Number(process.env.SHOPIFY_TOKEN_CACHE_TTL_MS || 55 * 1000);

const tokenCache = new Map();

function assertConfig() {
  const missing = [];
  if (!API_KEY) missing.push('SHOPIFY_API_KEY');
  if (!API_SECRET) missing.push('SHOPIFY_API_SECRET');
  if (!APP_URL) missing.push('SHOPIFY_APP_URL');
  return missing;
}

function setSecurityHeaders(res) {
  res.setHeader('Content-Security-Policy', "frame-ancestors https://admin.shopify.com https://*.myshopify.com;");
  res.setHeader('X-Frame-Options', 'ALLOWALL');
  res.setHeader('Referrer-Policy', 'same-origin');
}

function base64UrlDecode(input) {
  const normalized = input.replace(/-/g, '+').replace(/_/g, '/');
  const padding = '='.repeat((4 - (normalized.length % 4 || 4)) % 4);
  return Buffer.from(normalized + padding, 'base64').toString('utf8');
}

function verifySessionToken(token) {
  if (!token) throw new Error('Missing session token');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('Malformed session token');

  const [encodedHeader, encodedPayload, encodedSignature] = parts;
  const header = JSON.parse(base64UrlDecode(encodedHeader));
  const payload = JSON.parse(base64UrlDecode(encodedPayload));

  if (header.alg !== 'HS256') throw new Error(`Unexpected token algorithm: ${header.alg}`);

  const expectedSignature = crypto
    .createHmac('sha256', API_SECRET)
    .update(`${encodedHeader}.${encodedPayload}`)
    .digest('base64url');

  if (!crypto.timingSafeEqual(Buffer.from(encodedSignature), Buffer.from(expectedSignature))) {
    throw new Error('Invalid token signature');
  }

  const now = Math.floor(Date.now() / 1000);
  if (payload.nbf && payload.nbf > now + 5) throw new Error('Session token is not yet valid');
  if (payload.exp && payload.exp < now - 5) throw new Error('Session token is expired');
  if (payload.aud !== API_KEY) throw new Error('Session token audience mismatch');

  const issuer = payload.iss ? new URL(payload.iss) : null;
  const destination = payload.dest ? new URL(payload.dest) : null;
  if (!issuer || !destination) throw new Error('Session token missing issuer or destination');
  const issuerHost = issuer.hostname.replace(/^admin\./, '');
  const destinationHost = destination.hostname.replace(/^admin\./, '');
  if (!issuerHost.endsWith('shopify.com')) throw new Error('Unexpected token issuer');
  if (!destinationHost.endsWith('myshopify.com')) throw new Error('Unexpected destination host');

  return {
    raw: token,
    payload,
    shop: destination.hostname,
    userId: payload.sub,
  };
}

async function exchangeToken({ shop, sessionToken, requestedTokenType = 'urn:shopify:params:oauth:token-type:online-access-token' }) {
  const cacheKey = `${shop}:${requestedTokenType}`;
  const cached = tokenCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.value;
  }

  const body = new URLSearchParams({
    client_id: API_KEY,
    client_secret: API_SECRET,
    grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange',
    subject_token: sessionToken,
    subject_token_type: 'urn:ietf:params:oauth:token-type:id_token',
    requested_token_type: requestedTokenType,
  });

  const response = await fetch(`https://${shop}/admin/oauth/access_token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body,
  });

  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }

  if (!response.ok) {
    const detail = payload?.error_description || payload?.error || payload?.errors || payload?.raw || response.statusText;
    const error = new Error(`Token exchange failed (${response.status}): ${detail}`);
    error.statusCode = response.status;
    error.details = payload;
    throw error;
  }

  const result = {
    accessToken: payload.access_token,
    scope: payload.scope,
    expiresIn: payload.expires_in || TOKEN_CACHE_TTL_MS / 1000,
    associatedUserScope: payload.associated_user_scope,
    associatedUser: payload.associated_user,
  };

  tokenCache.set(cacheKey, {
    expiresAt: Date.now() + Math.max(1000, (result.expiresIn - 5) * 1000),
    value: result,
  });

  return result;
}

async function callAdminApi({ shop, accessToken, query }) {
  const response = await fetch(`https://${shop}/admin/api/${SHOPIFY_API_VERSION}/graphql.json`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Shopify-Access-Token': accessToken,
      Accept: 'application/json',
    },
    body: JSON.stringify({ query }),
  });

  const payload = await response.json();
  if (!response.ok || payload.errors) {
    const detail = JSON.stringify(payload.errors || payload);
    const error = new Error(`Admin API request failed (${response.status}): ${detail}`);
    error.statusCode = response.status;
    error.details = payload;
    throw error;
  }

  return payload.data;
}

function getBearerToken(req) {
  const header = req.headers.authorization || req.headers.Authorization;
  if (!header) return null;
  const [scheme, value] = header.split(' ');
  if ((scheme || '').toLowerCase() !== 'bearer') return null;
  return value;
}

function requireEmbeddedAuth(req, res, next) {
  try {
    const token = getBearerToken(req);
    req.shopifySession = verifySessionToken(token);
    return next();
  } catch (error) {
    return res.status(401).json({ ok: false, error: error.message });
  }
}

function renderHtml() {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="shopify-api-key" content="${API_KEY || ''}" />
    <title>${APP_NAME}</title>
    <script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>
    <style>
      :root { color-scheme: light dark; }
      body { font-family: Inter, ui-sans-serif, system-ui, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
      main { max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }
      h1 { margin: 0 0 8px; font-size: 28px; }
      p { line-height: 1.5; }
      .grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); margin-top: 24px; }
      .card { background: #111827; border: 1px solid #334155; border-radius: 14px; padding: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.18); }
      .card h2 { margin: 0 0 8px; font-size: 16px; color: #93c5fd; }
      .status { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; }
      .dot { width: 10px; height: 10px; border-radius: 999px; display: inline-block; background: #64748b; }
      .ok .dot { background: #22c55e; }
      .bad .dot { background: #ef4444; }
      pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; background: #020617; border-radius: 10px; padding: 12px; overflow: auto; }
      button { background: #2563eb; color: white; border: 0; border-radius: 10px; padding: 10px 14px; font-weight: 600; cursor: pointer; }
      button:disabled { opacity: .55; cursor: wait; }
      .meta { color: #94a3b8; font-size: 14px; }
    </style>
  </head>
  <body>
    <main>
      <h1>${APP_NAME}</h1>
      <p class="meta">Embedded auth test shell for <strong>${APP_URL}</strong>. This page verifies session-token-backed requests, backend token exchange, and an authenticated Admin API read.</p>
      <button id="refresh">Run embedded auth check</button>
      <div class="grid">
        <section class="card">
          <h2>Session token</h2>
          <div id="session-status" class="status"><span class="dot"></span><span>Waiting</span></div>
          <pre id="session-output">No request yet.</pre>
        </section>
        <section class="card">
          <h2>Token exchange</h2>
          <div id="exchange-status" class="status"><span class="dot"></span><span>Waiting</span></div>
          <pre id="exchange-output">No request yet.</pre>
        </section>
        <section class="card">
          <h2>Admin API read</h2>
          <div id="admin-status" class="status"><span class="dot"></span><span>Waiting</span></div>
          <pre id="admin-output">No request yet.</pre>
        </section>
      </div>
    </main>
    <script>
      const setStatus = (prefix, ok, text, payload) => {
        const status = document.getElementById(prefix + '-status');
        const output = document.getElementById(prefix + '-output');
        status.className = 'status ' + (ok ? 'ok' : 'bad');
        status.innerHTML = '<span class="dot"></span><span>' + text + '</span>';
        output.textContent = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
      };

      async function runChecks() {
        const btn = document.getElementById('refresh');
        btn.disabled = true;
        setStatus('session', false, 'Running', 'Calling /api/embedded/status ...');
        setStatus('exchange', false, 'Running', 'Waiting on backend token exchange ...');
        setStatus('admin', false, 'Running', 'Waiting on Admin API test ...');
        try {
          const statusRes = await fetch('/api/embedded/status');
          const statusPayload = await statusRes.json();
          setStatus('session', statusRes.ok && statusPayload.ok, statusRes.ok ? 'Verified' : 'Failed', statusPayload);
          setStatus('exchange', statusRes.ok && statusPayload.tokenExchange?.ok, statusPayload.tokenExchange?.ok ? 'Working' : 'Failed', statusPayload.tokenExchange || statusPayload);

          const adminRes = await fetch('/api/admin/shop');
          const adminPayload = await adminRes.json();
          setStatus('admin', adminRes.ok && adminPayload.ok, adminRes.ok ? 'Admin call succeeded' : 'Failed', adminPayload);
        } catch (error) {
          setStatus('session', false, 'Failed', String(error));
          setStatus('exchange', false, 'Failed', String(error));
          setStatus('admin', false, 'Failed', String(error));
        } finally {
          btn.disabled = false;
        }
      }

      document.getElementById('refresh').addEventListener('click', runChecks);
      runChecks();
    </script>
  </body>
</html>`;
}

app.use((req, res, next) => {
  setSecurityHeaders(res);
  next();
});

app.get('/health', (_req, res) => {
  const missing = assertConfig();
  res.json({ ok: missing.length === 0, appUrl: APP_URL, embedded: true, missing });
});

app.get('/api/config', (_req, res) => {
  res.json({
    ok: true,
    embedded: true,
    applicationUrl: APP_URL,
    scopes: SCOPES.split(','),
    apiVersion: SHOPIFY_API_VERSION,
    missing: assertConfig(),
  });
});

app.get('/api/embedded/status', requireEmbeddedAuth, async (req, res) => {
  try {
    const exchange = await exchangeToken({
      shop: req.shopifySession.shop,
      sessionToken: req.shopifySession.raw,
      requestedTokenType: 'urn:shopify:params:oauth:token-type:online-access-token',
    });

    return res.json({
      ok: true,
      session: {
        shop: req.shopifySession.shop,
        userId: req.shopifySession.userId,
        iss: req.shopifySession.payload.iss,
        dest: req.shopifySession.payload.dest,
      },
      tokenExchange: {
        ok: true,
        scope: exchange.scope,
        expiresIn: exchange.expiresIn,
        associatedUserScope: exchange.associatedUserScope,
      },
    });
  } catch (error) {
    return res.status(error.statusCode || 500).json({
      ok: false,
      session: {
        shop: req.shopifySession.shop,
        userId: req.shopifySession.userId,
      },
      tokenExchange: {
        ok: false,
        error: error.message,
        details: error.details || null,
      },
    });
  }
});

app.get('/api/admin/shop', requireEmbeddedAuth, async (req, res) => {
  try {
    const exchange = await exchangeToken({
      shop: req.shopifySession.shop,
      sessionToken: req.shopifySession.raw,
      requestedTokenType: 'urn:shopify:params:oauth:token-type:online-access-token',
    });

    const data = await callAdminApi({
      shop: req.shopifySession.shop,
      accessToken: exchange.accessToken,
      query: `query EmbeddedProbe { shop { name myshopifyDomain primaryDomain { url host } } }`,
    });

    return res.json({
      ok: true,
      shop: data.shop,
      scope: exchange.scope,
      associatedUserScope: exchange.associatedUserScope,
    });
  } catch (error) {
    return res.status(error.statusCode || 500).json({
      ok: false,
      error: error.message,
      details: error.details || null,
    });
  }
});

app.get('/', (_req, res) => {
  const missing = assertConfig();
  if (missing.length) {
    return res.status(500).send(`Missing required environment variables: ${missing.join(', ')}`);
  }
  res.type('html').send(renderHtml());
});

app.get('/auth', (_req, res) => {
  res.status(410).json({
    ok: false,
    message: 'Manual OAuth redirect is retired. Use Shopify-managed installation with embedded session tokens and token exchange.',
  });
});

app.get('/auth/callback', (_req, res) => {
  res.status(410).json({
    ok: false,
    message: 'Manual OAuth callback is retired. Use Shopify-managed installation with embedded session tokens and token exchange.',
  });
});

const port = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(port, () => {
    console.log(`Spider KPI embedded auth app listening on port ${port}`);
  });
}

module.exports = app;
