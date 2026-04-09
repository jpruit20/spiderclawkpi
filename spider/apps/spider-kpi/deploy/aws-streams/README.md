# Production telemetry stream architecture

This document is the cold-start handoff for Spider KPI telemetry in production.

It explains:
- the live stream source
- the Lambda normalization/forwarding shape
- the KPI ingest endpoint
- the storage tables
- the telemetry summary/fallback path
- where historical backfill fits

## 1. Production objective

The production telemetry path is split into two separate jobs:

1. *live-forward telemetry visibility*
   - keep recent device activity flowing into KPI continuously
   - support live Product / Engineering and System Health views

2. *historical recovery / backfill*
   - recover longer device history without stressing the live DynamoDB table
   - keep this offline and separate from the live stream path

Do not mix these two paths mentally.

## 2. Stream source

### Upstream source of live telemetry
- DynamoDB table: `sg_device_shadows`
- AWS feature: DynamoDB Streams
- required stream view: `NEW_IMAGE`

### Why this source exists
`sg_device_shadows` is the operational state feed for device updates.
The stream path captures new state changes as they happen instead of repeatedly deep-scanning the table.

## 3. Lambda shape

There are two handler shapes in the repo:

### A. backend-local handler
- file: `apps/spider-kpi/backend/app/streaming/lambda_handler.py`
- handler: `app.streaming.lambda_handler.handler`
- use case: same codebase/local runtime scenarios where Lambda writes through the backend package directly

### B. production standalone handler
- file: `apps/spider-kpi/deploy/aws-streams/lambda_handler_standalone.py`
- packaged zip output lives under: `apps/spider-kpi/deploy/aws-streams/build/`
- use case: production AWS Lambda

### Production Lambda contract
The working production model is the standalone Lambda that:
1. accepts DynamoDB Streams `Records[]`
2. ignores non-`aws:dynamodb` records
3. reads `dynamodb.NewImage`
4. normalizes each record into KPI ingest payload shape
5. POSTs the normalized batch to the KPI API ingest endpoint

### Normalized payload fields sent to KPI API
Each normalized record contains:
- `source_event_id`
- `device_id`
- `sample_timestamp`
- `stream_event_name`
- `engaged`
- `firmware_version`
- `grill_type`
- `target_temp`
- `current_temp`
- `heating`
- `intensity`
- `rssi`
- `error_codes_json`
- `raw_payload`

### Required Lambda env vars
- `KPI_API_BASE_URL`
- `KPI_API_PASSWORD`

### Why production uses API ingestion instead of direct Postgres writes
Production Postgres is droplet-local and not a practical direct Lambda target.
The Lambda should forward over authenticated HTTP to the KPI API instead.

## 4. KPI ingest endpoint

### Endpoint
- route: `/api/admin/ingest/telemetry-stream`
- implementation: `apps/spider-kpi/backend/app/api/routes/admin.py`

### Behavior
The ingest endpoint now does all of the following:
- upserts source-health config row `aws_telemetry_stream`
- records an ingest run in `source_sync_runs`
- writes normalized rows into `telemetry_stream_events`
- records inserted/skipped counts
- records batch metadata such as:
  - `records_received`
  - `distinct_devices_received`
  - `oldest_sample_timestamp`
  - `newest_sample_timestamp`

### Auth
- header: `X-App-Password`
- value: KPI backend `APP_PASSWORD`

## 5. Storage tables

### Raw live stream store
- table: `telemetry_stream_events`
- purpose: raw landing table for normalized stream rows
- migration files:
  - `backend/alembic/versions/20260408_0006_telemetry_stream_events.py`
  - `backend/alembic/versions/20260408_0007_telemetry_stream_events_updated_at.py`

### Derived bounded-scan session store
- table: `telemetry_sessions`
- purpose: derived session-level telemetry from the bounded `aws_telemetry` connector path

### Derived bounded-scan daily store
- table: `telemetry_daily`
- purpose: daily telemetry aggregates from the bounded `aws_telemetry` connector path

### Source-health / run tracking tables involved
- `source_config`
- `source_sync_runs`

## 6. Summary path used by the KPI API

### Primary path
`app/services/telemetry.py` now prefers stream-backed telemetry when fresh stream rows exist:
- checks for `telemetry_stream_events`
- loads recent stream rows
- calls `summarize_stream_telemetry()`

### Stream-backed summary behavior
The stream summary currently produces:
- active devices in recent windows (`5m`, `15m`, `60m`, `24h`)
- distinct devices observed in the loaded slice
- engaged latest-state devices
- low-RSSI and error-vector proxies
- latest sample freshness
- stream-backed coverage metadata

This path is explicitly device-proxy telemetry, not users.

### Fallback path
If no fresh stream rows exist, summary falls back to bounded-scan telemetry:
- `telemetry_daily`
- `telemetry_sessions`
- latest successful `aws_telemetry` sync metadata

This fallback is allowed for degraded continuity, but it is not equivalent to the live stream path.

## 7. How to tell which path production is using

### Stream-backed mode
Telemetry summary metadata should show:
- `source = sg_device_shadows_stream`
- `sample_source = dynamodb_stream`

### Fallback mode
Telemetry summary is no longer stream-backed if `sample_source != dynamodb_stream`.
In that case production has effectively fallen back to bounded-scan telemetry again.

## 8. Stream-path health checks now in place

### Source health row
A dedicated source-health row now exists for:
- `aws_telemetry_stream`

### Health details exposed
Source health now tracks for the stream path:
- latest sample timestamp
- latest landed row creation time
- latest stream row age in minutes
- rows inserted in last `15m`
- rows inserted in last `60m`
- rows inserted in last `24h`
- distinct devices seen in those windows
- lambda-processing health proxy
- ingest-endpoint health proxy

### Admin debug endpoint
- route: `/api/admin/debug/telemetry-stream`

It reports:
- total landed stream rows
- rows landed in last `15m`
- rows landed in last `60m`
- latest sample timestamp
- `fallback_active`
- `fallback_reason`
- latest few landed rows

## 9. Business interpretation rules

### What the live stream path is good for
- recent device activity visibility
- active-device proxy counts
- latest-state engagement visibility
- early reliability signals
- Product / Engineering operational monitoring

### What it is not yet good for
- installed base counts
- customer/user counts
- canonical cook-session truth
- long-range historical fleet history

### Permanent labeling rule
Use `device_id` as the current unique-device proxy.
Do not label these counts as users unless an account/device join exists later.

## 10. Historical backfill path

Historical backfill is intentionally separate from the live stream architecture.

### Do not use as primary backfill path
Do not use deep live scans of `sg_device_shadows` as the primary 12-month recovery path.
Observed AWS constraints made that non-credible for full history recovery.

### Recommended history path
1. enable PITR on `sg_device_shadows`
2. export DynamoDB table to S3
3. process export offline
4. compute distinct `device_id` history offline
5. optionally write compact derived history back into KPI later

### Runbook
- `apps/spider-kpi/deploy/aws-streams/EXPORT_BACKFILL_RUNBOOK.md`

### Audit script
- `apps/spider-kpi/scripts/telemetry_export_audit.py`

## 11. Production mental model

Use this sentence as the shortest correct summary:

> Live telemetry in production is `sg_device_shadows` DynamoDB Streams -> standalone Lambda -> authenticated KPI ingest endpoint -> `telemetry_stream_events`, and KPI summary prefers that stream-backed path before falling back to bounded-scan telemetry; historical recovery remains a separate DynamoDB export/offline workflow.

## 12. Minimal verification checklist

When resuming this tomorrow, verify in this order:

1. DynamoDB Streams is enabled on `sg_device_shadows`
2. Lambda env uses `KPI_API_BASE_URL` and `KPI_API_PASSWORD`
3. Lambda event source mapping is attached to the table stream
4. KPI backend has the telemetry stream migrations applied
5. `/api/admin/debug/telemetry-stream` shows landed rows growing
6. source health shows `aws_telemetry_stream`
7. telemetry summary metadata shows `sample_source = dynamodb_stream`
8. System Health does not show bounded-scan fallback warning

## 13. Failure modes to remember

### If Lambda is running but KPI shows no fresh stream rows
Likely causes:
- wrong Lambda handler/package
- bad API base URL
- bad app password
- network reachability issue from Lambda to KPI API
- ingest endpoint errors

### If telemetry still appears but mode is bounded-scan
Likely cause:
- stream landing stopped, and summary fell back to `telemetry_daily` / `telemetry_sessions`

### If counts feel low even while stream path is healthy
Likely causes:
- recent-activity window semantics
- sparse device heartbeat/update behavior
- no account joins
- expectation mismatch versus installed base
