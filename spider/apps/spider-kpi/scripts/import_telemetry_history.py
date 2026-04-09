#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import date
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Import telemetry export audit JSON into KPI backend history flow.')
    parser.add_argument('--input', required=True, help='Path to telemetry_export_audit.json')
    parser.add_argument('--api-base', required=True, help='KPI API base, e.g. https://api-kpi.spidergrills.com')
    parser.add_argument('--app-password', required=True, help='KPI APP_PASSWORD for admin ingest endpoint')
    parser.add_argument('--export-bucket', help='Optional export bucket name')
    parser.add_argument('--export-prefix', help='Optional export prefix')
    parser.add_argument('--export-arn', help='Optional export ARN')
    parser.add_argument('--notes', help='Optional operator notes')
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding='utf-8'))
    monthly_devices = payload.get('monthly_distinct_devices') or {}
    monthly_engaged = payload.get('monthly_distinct_engaged_devices') or {}
    monthly = []
    for month_key, device_count in sorted(monthly_devices.items()):
        month_start = date.fromisoformat(f'{month_key}-01')
        monthly.append({
            'month_start': month_start.isoformat(),
            'distinct_devices': int(device_count or 0),
            'distinct_engaged_devices': int(monthly_engaged.get(month_key) or 0),
        })

    body = {
        'window_days': int(payload.get('window_days') or 365),
        'distinct_devices': int(payload.get('distinct_devices') or 0),
        'distinct_engaged_devices': int(payload.get('distinct_engaged_devices') or 0),
        'observed_mac_count': int(payload.get('observed_mac_count') or 0),
        'monthly': monthly,
        'source': 'ddb_export_backfill',
        'export_bucket': args.export_bucket,
        'export_prefix': args.export_prefix,
        'export_arn': args.export_arn,
        'notes': args.notes,
    }

    request = urllib.request.Request(
        url=f"{args.api_base.rstrip('/')}/api/admin/ingest/telemetry-history",
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'X-App-Password': args.app_password,
        },
        method='POST',
    )
    with urllib.request.urlopen(request) as response:
        print(response.read().decode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
