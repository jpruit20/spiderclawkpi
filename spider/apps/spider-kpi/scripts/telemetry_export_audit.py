#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DDB_TYPES = {'S', 'N', 'BOOL', 'NULL', 'M', 'L'}


def deserialize_attribute(value: Any) -> Any:
    if not isinstance(value, dict) or len(value) != 1:
        return value
    key, payload = next(iter(value.items()))
    if key == 'S':
        return payload
    if key == 'N':
        return float(payload) if '.' in str(payload) else int(payload)
    if key == 'BOOL':
        return bool(payload)
    if key == 'NULL':
        return None
    if key == 'M':
        return {k: deserialize_attribute(v) for k, v in payload.items()}
    if key == 'L':
        return [deserialize_attribute(v) for v in payload]
    return payload


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    if all(isinstance(v, dict) and len(v) == 1 and next(iter(v.keys())) in DDB_TYPES for v in item.values()):
        return {k: deserialize_attribute(v) for k, v in item.items()}
    return item


def dt_from_epoch_ms(value: Any) -> datetime | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 10_000_000_000:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob('*'):
        if path.is_file() and (path.suffix in {'.json', '.jsonl', '.gz'} or 'data' in path.name.lower()):
            yield path


def iter_export_rows(root: Path) -> Iterable[dict[str, Any]]:
    for path in iter_files(root):
        opener = gzip.open if path.suffix == '.gz' else open
        mode = 'rt'
        try:
            with opener(path, mode, encoding='utf-8') as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(parsed, dict):
                        continue
                    item = parsed.get('Item') if isinstance(parsed.get('Item'), dict) else parsed
                    if isinstance(item, dict):
                        yield normalize_item(item)
        except OSError:
            continue


@dataclass
class AuditResult:
    rows_read: int
    rows_in_window: int
    distinct_devices: int
    distinct_engaged_devices: int
    monthly_distinct_devices: dict[str, int]
    monthly_distinct_engaged_devices: dict[str, int]
    observed_mac_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            'rows_read': self.rows_read,
            'rows_in_window': self.rows_in_window,
            'distinct_devices': self.distinct_devices,
            'distinct_engaged_devices': self.distinct_engaged_devices,
            'monthly_distinct_devices': self.monthly_distinct_devices,
            'monthly_distinct_engaged_devices': self.monthly_distinct_engaged_devices,
            'observed_mac_count': self.observed_mac_count,
        }


def audit_export(root: Path, window_days: int) -> AuditResult:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    rows_read = 0
    rows_in_window = 0
    all_devices: set[str] = set()
    engaged_devices: set[str] = set()
    macs: set[str] = set()
    monthly_devices: dict[str, set[str]] = {}
    monthly_engaged_devices: dict[str, set[str]] = {}

    for row in iter_export_rows(root):
        rows_read += 1
        device_id = str(row.get('device_id') or '').strip()
        sample_time = dt_from_epoch_ms(row.get('sample_time'))
        if not device_id or not sample_time or sample_time < cutoff:
            continue
        rows_in_window += 1
        month_key = sample_time.strftime('%Y-%m')
        monthly_devices.setdefault(month_key, set()).add(device_id)
        all_devices.add(device_id)

        reported = ((row.get('device_data') or {}).get('reported') or {}) if isinstance(row.get('device_data'), dict) else {}
        if str(reported.get('mac') or '').strip():
            macs.add(str(reported.get('mac')).strip())
        if bool(reported.get('engaged', False)):
            engaged_devices.add(device_id)
            monthly_engaged_devices.setdefault(month_key, set()).add(device_id)

    return AuditResult(
        rows_read=rows_read,
        rows_in_window=rows_in_window,
        distinct_devices=len(all_devices),
        distinct_engaged_devices=len(engaged_devices),
        monthly_distinct_devices={k: len(v) for k, v in sorted(monthly_devices.items())},
        monthly_distinct_engaged_devices={k: len(v) for k, v in sorted(monthly_engaged_devices.items())},
        observed_mac_count=len(macs),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit DynamoDB export files for distinct telemetry device history.')
    parser.add_argument('--input', required=True, help='Directory containing DynamoDB export files')
    parser.add_argument('--window-days', type=int, default=365)
    parser.add_argument('--output', help='Optional output JSON path')
    args = parser.parse_args()

    result = audit_export(Path(args.input), args.window_days)
    payload = result.as_dict()
    text = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
