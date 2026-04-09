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
- PostgreSQL table: `telemetry_stream_events`
- Alembic migration: `apps/spider-kpi/backend/alembic/versions/20260408_0006_telemetry_stream_events.py`

## Required Lambda env vars
- `KPI_DATABASE_URL` (supported explicitly by backend settings; `DATABASE_URL` also works)
- `AWS_REGION`

## Required AWS activation steps
1. Enable DynamoDB Streams on `sg_device_shadows`
2. Use stream view type: `NEW_IMAGE`
3. Deploy Lambda package containing backend app code
4. Attach IAM permissions for DynamoDB Streams read + CloudWatch logs + VPC access if DB is private
5. Create event source mapping from stream ARN to Lambda
6. Run Alembic upgrade on KPI backend DB to create `telemetry_stream_events`
7. Validate the Lambda can reach the KPI Postgres host/network path used by `KPI_DATABASE_URL` before enabling the mapping at scale

## Migration coexistence
- Keep current bounded scan path active as fallback during migration
- Stream path writes raw event facts continuously
- KPI backend can read raw event store for recency-critical views while bounded scan remains parity/backfill path
