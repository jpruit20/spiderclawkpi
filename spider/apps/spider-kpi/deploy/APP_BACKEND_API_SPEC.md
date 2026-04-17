# Spider Grills App backend → KPI dashboard API spec

**Version:** 0.1 draft — for alignment with the app team, 2026-04-17
**Consumer:** `https://api-kpi.spidergrills.com` (Spider KPI FastAPI backend)
**Producer:** spidergrills.app backend (aggregates Postgres + Firebase/GA + Klaviyo)
**Contact:** Joseph Pruitt (joseph@spidergrills.com)

---

## Why this exists

The Spider Grills KPI dashboard is the company's long-term operational
cockpit. It already integrates Shopify, Triple Whale, DynamoDB (device
telemetry), S3 (historical cook data), Freshdesk, ClickUp, Slack, GitHub
issues, GA4, Microsoft Clarity, Reddit, Amazon, and YouTube.

The **last major gap** is app-side user behavior: signups, DAU/MAU,
device pairings, retention cohorts, in-app events. That data lives across
your Postgres + Firebase/GA + Klaviyo stack, which makes a direct DB
tunnel insufficient. A small set of purpose-built HTTPS endpoints on
your side is the cleanest path.

This document proposes that contract. Everything here is negotiable —
it's a starting point so the Tuesday call is a working session, not a
discovery session.

---

## Transport + auth

- **Protocol:** HTTPS, JSON request/response bodies.
- **Auth:** static bearer token in `Authorization: Bearer <token>` header.
  One token per consumer. Rotatable without code change (we pull it from
  `.env`). Tokens are shared out-of-band (1Password / encrypted message).
- **No IP whitelisting required** — auth is by token, source IP can drift.
- **Base URL:** your pick. Suggest `https://api.spidergrills.app/kpi/v1/...`
  or a dedicated subdomain. We don't care; we store it in our config.

## Conventions

- **Timestamps:** ISO 8601 UTC, e.g. `2026-04-17T16:04:00Z`. Always UTC.
- **Date-only fields:** `YYYY-MM-DD`.
- **IDs:** opaque strings. Stable, not reused.
- **Email PII:** fine to return raw emails over HTTPS with auth, or
  `sha256(lower(email))` if your privacy stance prefers that. We already
  dedupe users by `sha256(lower(email))` for cross-source joins, so either
  works. Declare whichever you pick in the response payload — we'll
  detect it.
- **Pagination:** cursor-based for list endpoints. Response includes
  `next_cursor` (string, null when exhausted) and optional `total`.
  Clients pass `?cursor=...` on the next request. Page size = server
  default (~500), client can request `?limit=N` up to 2000.
- **Incremental sync:** list endpoints accept `?updated_since=<ISO8601>`
  so we only re-pull changed rows. Server should return rows whose
  "last significant update" timestamp is strictly greater than the
  passed value. Leaving the param out means "full pull".
- **Caching:** responses that are safe to cache should include
  `ETag` / `Last-Modified` headers; we'll honor `If-None-Match` and
  `If-Modified-Since` where available. Optional.
- **Rate limits:** soft expectation — we'd call at most 60 times per hour
  total, mostly nightly batch pulls. If you want hard limits, return
  `429 Too Many Requests` with a `Retry-After` header and we'll back off.

## Error shape

Recommended, not required:

```json
{
  "error": {
    "code": "bad_cursor",
    "message": "Cursor has expired, re-fetch from the start.",
    "detail": null
  }
}
```

With an appropriate 4xx/5xx status.

---

## Endpoints

### 1. `GET /health`

Readiness probe. Cheap. No auth required (optional).

```json
{
  "ok": true,
  "last_refreshed_at": "2026-04-17T15:30:00Z",
  "sources_available": ["postgres", "firebase", "klaviyo"]
}
```

We call this at startup + every sync to confirm the consumer can skip a
fetch if nothing's changed.

---

### 2. `GET /kpi/users/summary?days=N`

Headline user metrics over a rolling window. Used on the Product /
Engineering + Executive overview pages.

**Request:** `?days=30` (default 30, max 365)

**Response:**

```json
{
  "window": { "start": "2026-03-18", "end": "2026-04-17", "days": 30 },
  "signups_total": 412,
  "signups_per_day": [
    { "date": "2026-03-18", "count": 14 },
    { "date": "2026-03-19", "count": 9 }
  ],
  "deletions_total": 3,
  "mau": 1847,
  "wau": 623,
  "dau_current": 91,
  "dau_7d_avg": 88,
  "dau_7d_prev_avg": 82,
  "notification_opt_in_rate": 0.74
}
```

**Frequency we'd call:** nightly at 1am ET.

---

### 3. `GET /kpi/users/list?updated_since=T&cursor=C&limit=N`

Incremental list of user records that signed up, had state changes, or
were deleted since `T`.

**Response:**

```json
{
  "users": [
    {
      "user_id": "usr_abc123",
      "email": "person@example.com",
      "email_sha256": "a1b2c3...",
      "signup_at": "2026-04-10T14:22:11Z",
      "deleted_at": null,
      "last_seen_at": "2026-04-17T09:02:17Z",
      "fcm_token_present": true,
      "marketing_opt_in": true,
      "locale": "en-US",
      "platform": "ios",
      "app_version_latest": "1.17.3"
    }
  ],
  "next_cursor": "eyJvZmZzZXQiOjUwMH0",
  "total": 1847
}
```

Either `email` or `email_sha256` is sufficient — one is enough for us to
dedupe across Freshdesk + ClickUp + app. Include both if you can; we
default to the hash.

**Frequency:** nightly.

---

### 4. `GET /kpi/devices/pairings?updated_since=T&cursor=C`

The critical missing link between users and devices. Each row represents
a user-↔-device association event.

**Response:**

```json
{
  "pairings": [
    {
      "pairing_id": "pair_xyz789",
      "user_id": "usr_abc123",
      "device_identifier": "02:00:11:22:33:44",
      "device_identifier_type": "mac_address",
      "thing_name": "sg22-huntsman-0413a",
      "model": "huntsman_22",
      "firmware_version_at_pair": "1.2.5",
      "paired_at": "2026-04-11T18:12:09Z",
      "unpaired_at": null,
      "pairing_source": "app.android.1.17.3"
    }
  ],
  "next_cursor": null
}
```

`device_identifier_type` declares what the ID is — `mac_address`,
`thing_name`, or both. If you can return both MAC and the AWS IoT
`thing_name`, that's ideal — it lets us join pairings to our DynamoDB
cook-session stream instantly.

**Frequency:** every 30 min (higher than most endpoints — pairings are
the highest-value event type for the funnel dashboard).

---

### 5. `GET /kpi/sessions/starts?updated_since=T&cursor=C`

**Metadata-only** cook session starts. We already have the detailed
temperature curves from DynamoDB — we just need the "this session was
started from the app" signal so we can split app-started vs
device-started cooks.

**Response:**

```json
{
  "sessions": [
    {
      "session_id": "sess_q7r8s9",
      "user_id": "usr_abc123",
      "device_identifier": "sg22-huntsman-0413a",
      "started_at": "2026-04-17T14:03:22Z",
      "ended_at": null,
      "source": "app",
      "app_version": "1.17.3",
      "started_from_recipe_id": null
    }
  ],
  "next_cursor": null
}
```

`source` is one of `app` | `device` | `unknown`. We'll null-merge this
against the DynamoDB stream by matching on `device_identifier` +
`started_at`.

**Frequency:** nightly. (We have near-realtime from DynamoDB already;
this is just to attribute the *start* event's origin.)

---

### 6. `GET /kpi/app-versions/distribution?days=N`

Histogram of app versions active in the window. Used on Product /
Engineering for "firmware + app version cohort" analysis.

**Response:**

```json
{
  "window": { "start": "2026-03-18", "end": "2026-04-17", "days": 30 },
  "distribution": [
    { "platform": "ios",     "version": "1.17.3", "users": 612, "sessions": 4203 },
    { "platform": "ios",     "version": "1.17.2", "users": 88,  "sessions": 327 },
    { "platform": "android", "version": "1.17.3", "users": 389, "sessions": 2711 },
    { "platform": "android", "version": "1.17.1", "users": 42,  "sessions": 180 }
  ]
}
```

**Frequency:** nightly.

---

### 7. `GET /kpi/retention/cohorts?cohort_unit=month&months=6`

D1/D7/D30 retention per signup cohort. Derived from Firebase/GA session
data joined with Postgres users, whatever's cleanest on your side.

**Response:**

```json
{
  "cohorts": [
    {
      "cohort": "2026-01",
      "cohort_size": 328,
      "d1_retained": 218,
      "d7_retained": 154,
      "d30_retained": 89,
      "d1_pct": 0.665,
      "d7_pct": 0.47,
      "d30_pct": 0.27
    }
  ]
}
```

**Frequency:** nightly.

---

### 8. `GET /kpi/pairing-funnel?days=N`

Conversion funnel: signed up → paired first device → first cook session
started. Derived from Postgres + DynamoDB on your side.

**Response:**

```json
{
  "window": { "start": "2026-03-18", "end": "2026-04-17", "days": 30 },
  "cohort_size_signups": 412,
  "paired_first_device": { "count": 289, "pct_of_signups": 0.70, "median_days_to_pair": 1.2 },
  "had_first_cook":     { "count": 221, "pct_of_signups": 0.54, "median_days_to_first_cook": 2.8 },
  "repeat_cooker":      { "count": 168, "pct_of_signups": 0.41, "definition": "2+ sessions in first 30d" }
}
```

**Frequency:** nightly.

---

### Optional — `POST` webhook callback

If you'd rather push events than have us poll, expose a config where we
register a webhook URL + shared secret, and you `POST` to us on user /
pairing / session-start events. We already have receivers for Slack,
ClickUp, and Shopify — adding yours is ~an hour on our side.

```http
POST https://api-kpi.spidergrills.com/api/webhooks/app-backend/events
X-Signature: sha256=<hmac of body with shared secret>
Content-Type: application/json

{
  "event_type": "pairing_created",
  "event_id": "evt_unique_id",
  "occurred_at": "2026-04-17T14:03:22Z",
  "payload": { "user_id": "...", "device_identifier": "...", ... }
}
```

Polling + push can coexist — webhooks for immediacy, polling as a safety
net for the ~1% of dropped events.

---

## What we already have (no need to duplicate)

So you can scope what's actually needed from your side:

- **DynamoDB cook-session stream** — we poll via AWS IoT Core credentials,
  have live data back to April 2023, 314M items. Temps, curves, error
  codes, firmware versions reported by the device itself. This is why
  endpoint **5** is metadata-only.
- **Freshdesk tickets** — fully integrated via Freshdesk API.
- **Shopify orders, Triple Whale attribution, GA4 web analytics, Microsoft
  Clarity** — all separately integrated on the web/commerce side.
- **ClickUp + Slack** — fully integrated on the internal-ops side.

So from your end, what we're really after is the **Postgres layer
(users + pairings + session metadata) + the Firebase/GA/Klaviyo signals
(DAU/MAU, installs, retention, opt-ins, app versions)**. That's the full
scope.

---

## Prioritization if you want to ship incrementally

If building all 8 endpoints at once is too much, here's the order that
unblocks the most dashboard value:

1. **`/kpi/users/list` + `/kpi/devices/pairings`** — phase 1, the
   highest-value unlock. Lets us compute signups, pairings, and bridge
   to the existing DynamoDB stream for user-attributed cook sessions.
2. **`/kpi/users/summary`** — phase 2, headline metrics.
3. **`/kpi/app-versions/distribution` + `/kpi/sessions/starts`** —
   phase 3, cohort + attribution detail.
4. **`/kpi/retention/cohorts` + `/kpi/pairing-funnel`** — phase 4, the
   derived/analytical endpoints. Could also be computed on our side
   from #1/#2/#3.

Phase 1 alone closes 80% of the dashboard gap.

---

## Call agenda (Tuesday 5:30pm)

- 5 min: confirm the above high-level approach
- 10 min: walk through the endpoint list, cut / reshape as needed
- 5 min: auth + token handoff
- 5 min: ship order + rough timeline
- 5 min: webhook vs polling decision

Goal: end the call with a written shortlist of endpoints + shapes + owner
+ target date. I'll draft it on a Google Doc during the call so we both
sign off on the same artifact.
