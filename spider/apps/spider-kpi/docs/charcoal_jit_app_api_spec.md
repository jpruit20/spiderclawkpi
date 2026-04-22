# Charcoal JIT — App-side API spec (M1)

**Audience:** Agustin (Spider Grills app lead)
**Status:** Ready for implementation — backend endpoints live on
`kpi.spidergrills.com` as of 2026-04-22.
**Scope:** The M1 private beta — 50 invitations, top-25% power users,
self-fulfilled from warehouse-held Jealous Devil pallets.

This doc covers only the app-side surface. Admin-side endpoints
(batch creation, invitation management) are driven from the dashboard
and don't need to be mirrored in the app.

---

## 1. High-level flow

```
┌─────────────────────┐      ┌────────────────────┐      ┌────────────────────┐
│ Dashboard (Joseph)  │──1──▶│ KPI backend        │◀─2──│ Spider Grills app  │
│ /charcoal → Beta    │      │ (FastAPI on DO)    │      │ (Agustin)          │
│ rollout             │      │                    │      │                    │
└─────────────────────┘      └─┬──────────────────┘      └────────────────────┘
                                │
                        batch_id + N invitations
                                │
                                ▼
                          invitation_token (UUID) → pushed to device via app
```

1. **Dashboard side (done):** admin selects a cohort (SKU, lookback,
   percentile floor, max invites), previews, and sends. This creates
   one `charcoal_jit_invitations` row per targeted device with a
   unique `invitation_token`.
2. **App side (this spec):** the app is responsible for:
   - detecting that a paired device has a pending invitation
   - rendering an opt-in screen
   - POSTing the user's decision (accept / decline) back to the KPI
     backend

**Token delivery (open question for discussion).** Two implementations
to choose between:

- **Option A — Polling (M1 default, live now):** app polls
  `GET /api/charcoal/jit/invitations/for-device/{mac}` on app launch
  (and on each grill pairing). Returns the pending invitation if one
  exists. Simplest; no push infra needed. Endpoint is implemented —
  see §2.2.
- **Option B — Push:** KPI backend fires a push notification on batch
  creation. Requires app-side push-token registration. Better UX once
  wired, but more moving parts for M1.

Both paths converge on `invitation_token` — the opt-in screen and the
accept/decline calls work identically either way.

---

## 2. Endpoints

**Host:** `https://kpi.spidergrills.com`
**Auth:** All endpoints sit behind the same dashboard-session cookie
the app already uses for KPI calls. If the app hits these from an
unauthenticated context, we'll need to add an app-token auth path —
flag if that's needed.

### 2.1 Resolve invitation by token

```
GET /api/charcoal/jit/invitations/by-token/{token}
```

**Purpose:** app renders the opt-in screen using this payload.

**Returns 200:**

```json
{
  "ok": true,
  "invitation": {
    "id": 42,
    "batch_id": "8b2f…",
    "invitation_token": "d1b7-4a9c-…",
    "device_id": "abc123…",
    "mac_normalized": "aabbccddeeff",
    "user_key": null,
    "partner_product_id": 17,
    "bag_size_lb": 35,
    "fuel_preference": "lump",
    "margin_pct": 10.0,
    "addressable_lb_per_month": 18.4,
    "percentile_at_invite": 87.3,
    "sessions_in_window_at_invite": 24,
    "product_family_at_invite": "Huntsman",
    "cohort_params": { "lookback_days": 90, "target_percentile_floor": 75.0, … },
    "status": "pending",
    "invited_at": "2026-04-22T15:00:00Z",
    "expires_at": "2026-05-06T15:00:00Z",
    "accepted_at": null,
    "declined_at": null,
    "revoked_at": null,
    "subscription_id": null,
    "sku": {
      "id": 17,
      "partner": "jealous_devil",
      "title": "Jealous Devil Onyx Hardwood Lump Charcoal — XL 35lb",
      "fuel_type": "lump",
      "bag_size_lb": 35,
      "retail_price_usd": 69.99,
      "available": true,
      …
    }
  }
}
```

**Returns 404** if the token is unknown.

**App-side behaviour:**

- Show opt-in screen only when `status == "pending"` AND
  `expires_at > now`.
- If `status` is anything else (accepted / declined / expired /
  revoked), show a read-only summary or no UI at all.

### 2.2 Look up pending invitation by MAC

```
GET /api/charcoal/jit/invitations/for-device/{mac}
```

**Purpose:** app polls this on launch and on each grill pairing. This
is the happy-path "is there anything for me?" question — no 404s on
misses, the empty response is a normal answer.

**MAC format:** accepts any of `AA:BB:CC:DD:EE:FF`, `aa-bb-cc-dd-ee-ff`,
or `aabbccddeeff`. The endpoint normalizes internally — app-side
normalization is a nice-to-have but not required.

**Returns 200 (pending invite exists):**

```json
{
  "ok": true,
  "pending": true,
  "invitation": { …same shape as 2.1, including sku… }
}
```

**Returns 200 (nothing live):**

```json
{ "ok": true, "pending": false }
```

**Returns 400** if the mac isn't 12 hex chars after normalization —
signals an app-side bug rather than a silent miss.

**What counts as "pending":** `status == "pending"` AND
(`expires_at` is null OR `expires_at > now`). Accepted, declined,
revoked, and expired invitations are never returned. If multiple
matches exist (edge case), the most recently invited row wins.

### 2.3 Accept invitation

```
POST /api/charcoal/jit/invitations/by-token/{token}/accept
```

**Body:**

```json
{
  "user_key": "customer@example.com",
  "shipping_zip": "80302",          // optional — auto-filled from Shopify if omitted
  "shipping_lat": 40.0176,          // optional
  "shipping_lon": -105.2797,        // optional
  "lead_time_days": 5,              // optional, default 5
  "safety_stock_days": 7            // optional, default 7
}
```

**Returns 200:**

```json
{
  "ok": true,
  "invitation": { …updated, status="accepted", subscription_id set… },
  "subscription_id": 101
}
```

**Error cases (400):**

- Invitation not pending (already accepted/declined/expired/revoked)
- Invitation expired (server auto-flips to expired at this point)
- `user_key` missing

**Side effects:**

- A `charcoal_jit_subscriptions` row is created or upserted with
  `status='active'`, `partner_product_id` pinned to the SKU, and the
  invitation's `bag_size_lb` + `fuel_preference` + `margin_pct`
  copied over.
- An initial forecast is computed so the subscription has a real
  `next_ship_after` the moment accept returns.

### 2.4 Decline invitation

```
POST /api/charcoal/jit/invitations/by-token/{token}/decline
```

**Body:**

```json
{ "reason": "not interested" }     // optional
```

**Returns 200:**

```json
{
  "ok": true,
  "invitation": { …updated, status="declined", declined_at set… }
}
```

---

## 3. Suggested app-side UX

- **Home screen banner:** `"You've been invited to the Charcoal auto-ship
  beta"` → opens opt-in screen.
- **Opt-in screen fields (from `/by-token`):**
  - `sku.partner` + `sku.title` — what they'll receive
  - `sku.bag_size_lb` + `sku.retail_price_usd` — what each ship costs
  - `addressable_lb_per_month` — "based on your grilling you burn through
    X lb/month" (social proof for why we picked them)
  - `expires_at` — countdown to create urgency
- **Two CTAs:** `[Opt in]` → 2.3, `[Not interested]` → 2.4
- **Decline reason:** free text, max 256 chars.

---

## 4. What we don't ship to the app

- Admin-only fields (`invited_by`, `notes`) are redacted by the
  `/by-token` endpoint.
- We don't expose other devices' invitations — each token only works
  for its own device/user.
- No direct Shopify integration from the app. Shipments are drafted
  from the KPI backend's subscription forecast and push into Shopify
  from there.

---

## 5. Open items for our call

1. **Polling vs push (§1).** Polling endpoint is live — app can start
   integrating against it immediately. If you want push on top, we
   need app-side push-token registration; let me know and I'll scope
   the backend side.
2. **Auth.** If the app doesn't already have the dashboard-session
   cookie, we need an app-token auth path. I can extend
   `require_dashboard_session` to accept an app-signed token if
   helpful.
3. **MAC format.** The `/for-device/{mac}` endpoint normalizes
   internally, so the app can send any of `AA:BB:CC:DD:EE:FF`,
   `aa-bb-cc-dd-ee-ff`, or `aabbccddeeff`. Normalizing client-side is
   fine but not required.
4. **Shipping defaults.** If a customer has shipping on file via a
   prior Shopify order, we auto-fill `shipping_zip` / `shipping_lat` /
   `shipping_lon` from the most recent address — app can omit those
   fields from the accept payload entirely.

---

_Generated 2026-04-22. Backend commit `d19e176`._
