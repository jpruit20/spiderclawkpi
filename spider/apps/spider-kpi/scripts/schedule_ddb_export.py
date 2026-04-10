#!/usr/bin/env python3
"""Schedule a DynamoDB full-table export to S3.

Run monthly to create a point-in-time backup of sg_device_shadows.
Requires PITR to be enabled on the table (already done).

Usage:
    python scripts/schedule_ddb_export.py
    python scripts/schedule_ddb_export.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_env(env_path: str) -> None:
    path = Path(env_path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description='Schedule DynamoDB export to S3')
    parser.add_argument('--dry-run', action='store_true', help='Print what would happen without executing')
    parser.add_argument('--bucket', default='spider-kpi-telemetry-export', help='S3 bucket for export')
    parser.add_argument('--table-arn', default=None, help='DynamoDB table ARN (auto-detected if not provided)')
    args = parser.parse_args()

    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_env(str(env_path))

    import boto3

    region = os.environ.get('AWS_REGION', os.environ.get('AWS_DEFAULT_REGION', 'us-east-2'))
    table_name = os.environ.get('AWS_TELEMETRY_DYNAMODB_TABLE', 'sg_device_shadows')

    session = boto3.Session(
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name=region,
    )
    dynamodb = session.client('dynamodb')

    if args.table_arn:
        table_arn = args.table_arn
    else:
        desc = dynamodb.describe_table(TableName=table_name)
        table_arn = desc['Table']['TableArn']

    now = datetime.now(timezone.utc)
    prefix = f'spider-kpi/sg_device_shadows-export-{now.strftime("%Y-%m-%d")}'

    print(f'Table ARN:  {table_arn}')
    print(f'S3 bucket:  {args.bucket}')
    print(f'S3 prefix:  {prefix}')
    print(f'Export time: {now.isoformat()}')

    if args.dry_run:
        print('[DRY RUN] Would call export_table_to_point_in_time. Exiting.')
        return

    response = dynamodb.export_table_to_point_in_time(
        TableArn=table_arn,
        S3Bucket=args.bucket,
        S3Prefix=prefix,
        ExportFormat='DYNAMODB_JSON',
        ExportType='FULL_EXPORT',
    )
    export_arn = response['ExportDescription']['ExportArn']
    status = response['ExportDescription']['ExportStatus']
    print(f'Export started: {export_arn}')
    print(f'Status: {status}')
    print('Monitor with:')
    print(f'  aws dynamodb describe-export --export-arn "{export_arn}"')


if __name__ == '__main__':
    main()
