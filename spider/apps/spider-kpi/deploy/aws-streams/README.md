# DynamoDB Streams -> Lambda -> KPI telemetry store

## Handler
- File: `apps/spider-kpi/backend/app/streaming/lambda_handler.py`
- Handler: `app.streaming.lambda_handler.handler`

## Event shape consumed
- AWS DynamoDB Streams event
- Uses `Records[]`
- Expects `eventSource = aws:dynamodb`
- Reads `dynamodb.NewImage`

## Write target
- KPI API endpoint: `/api/admin/ingest/telemetry-stream`
- Backend persists into PostgreSQL table: `telemetry_stream_events`
- Alembic migrations:
  - `apps/spider-kpi/backend/alembic/versions/20260408_0006_telemetry_stream_events.py`
  - `apps/spider-kpi/backend/alembic/versions/20260408_0007_telemetry_stream_events_updated_at.py`

## Required Lambda env vars
- `KPI_API_BASE_URL`
- `KPI_API_PASSWORD`

## Required AWS activation steps
1. Enable DynamoDB Streams on `sg_device_shadows`
2. Use stream view type: `NEW_IMAGE`
3. Deploy Lambda zip with handler `app.streaming.lambda_handler.handler`
4. Attach IAM permissions for DynamoDB Streams read + CloudWatch logs
5. Create event source mapping from stream ARN to Lambda
6. Run Alembic upgrade on KPI backend DB to create `telemetry_stream_events`
7. Verify Lambda can POST to the KPI API and that `/api/admin/debug/telemetry-stream` starts increasing

## Migration coexistence
- Keep current bounded scan path active as fallback during migration
- Stream path writes raw event facts continuously
- KPI backend can read raw event store for recency-critical views while bounded scan remains parity/backfill path

## Historical backfill note
Do not use the bounded `aws_telemetry` connector as the primary 12-month history-recovery path.
Production evidence shows the live table is too large and too low-throughput for aggressive historical scans.
Use the export/offline path documented in `deploy/aws-streams/EXPORT_BACKFILL_RUNBOOK.md`.
