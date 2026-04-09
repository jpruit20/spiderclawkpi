# DynamoDB export -> offline telemetry backfill runbook

## Goal
Recover 12-month device-level telemetry history from `sg_device_shadows` without stressing the live DynamoDB table.

Use `device_id` as the durable unique proxy for active grills.
Do not label this as users unless an account join is added later.

## Why this path
The production table is currently too large and too low-throughput for truthful one-shot historical scans from the KPI app runtime.

Observed AWS facts:
- table: `sg_device_shadows`
- item count: ~314M
- size: ~169 GB
- provisioned read capacity: 4 RCUs
- direct deeper scan attempt triggered `ProvisionedThroughputExceededException`
- PITR currently disabled
- no prior exports listed

Because of that, the recommended history-recovery path is:
1. enable PITR on the table
2. export to S3
3. process the export offline
4. compute distinct `device_id` counts and optional backfill artifacts

## Preconditions
- AWS permissions to update DynamoDB backup settings
- AWS permissions to export DynamoDB table data
- target S3 bucket in the same account/region or an allowed destination bucket
- enough S3 space for exported table data

## Step 1 - enable PITR
CLI:

```bash
aws dynamodb update-continuous-backups \
  --table-name sg_device_shadows \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-east-2
```

Verify:

```bash
aws dynamodb describe-continuous-backups \
  --table-name sg_device_shadows \
  --region us-east-2
```

Expected:
- `ContinuousBackupsStatus = ENABLED`
- `PointInTimeRecoveryStatus = ENABLED`

## Step 2 - choose an export time
For a full current snapshot:
- use `EXPORT_TABLE_TO_POINT_IN_TIME`
- choose the latest restorable time

If a historical point is important, choose a timestamp within the PITR retention window.

## Step 3 - export to S3
Example CLI:

```bash
aws dynamodb export-table-to-point-in-time \
  --table-arn arn:aws:dynamodb:us-east-2:363841321269:table/sg_device_shadows \
  --s3-bucket <your-export-bucket> \
  --s3-prefix spider-kpi/sg_device_shadows-export-$(date +%F) \
  --export-format DYNAMODB_JSON \
  --region us-east-2
```

Capture the returned `ExportArn`.

## Step 4 - monitor export
```bash
aws dynamodb describe-export \
  --export-arn <ExportArn> \
  --region us-east-2
```

Wait for:
- `ExportStatus = COMPLETED`

## Step 5 - download or process in place
You can either:
- process directly from S3
- sync the export locally / to a worker

Example sync:

```bash
aws s3 sync s3://<your-export-bucket>/spider-kpi/sg_device_shadows-export-YYYY-MM-DD ./tmp/sg_device_shadows_export
```

## Step 6 - compute 12-month distinct device counts offline
Use the included script:
- `apps/spider-kpi/scripts/telemetry_export_audit.py`

Example:

```bash
python apps/spider-kpi/scripts/telemetry_export_audit.py \
  --input ./tmp/sg_device_shadows_export \
  --window-days 365 \
  --output ./tmp/telemetry_export_audit.json
```

Expected outputs include:
- total rows read
- rows in window
- distinct `device_id`
- distinct engaged `device_id`
- monthly distinct device counts
- monthly distinct engaged-device counts
- optional observed MAC-like values when present in payload

## Step 7 - decide what to backfill into KPI DB
Recommended immediate outputs:
- 12-month distinct device counts by month
- 12-month engaged-device counts by month
- optional sampled latest-state device metadata for QA

Do not automatically write the full raw export into the live KPI Postgres instance until storage/retention expectations are reviewed.

## KPI-safe backfill recommendation
Prefer writing compact derived history such as:
- monthly distinct devices
- monthly engaged devices
- optional daily distinct devices

instead of duplicating the full raw export into KPI Postgres.

## Guardrails
- Do not run large live-table scans against `sg_device_shadows` as the primary backfill path under current RCUs.
- Do not call `device_id` counts users.
- Treat `device_id` as a proxy for unique active grills unless an account join exists.
- Preserve the live stream pipeline separately from historical export processing.

## When to revisit direct scans
Only revisit live direct scans if one of these changes materially:
- RCUs are increased significantly
- a GSI exists that supports time-bounded access
- a dedicated historical backfill table or archive becomes available
