"""Helpers for reading ClickUp custom-field values off a synced task.

ClickUp stores each custom field as a dict inside ``custom_fields_json``
with shape::

    {
      "id": "...", "name": "Category", "type": "drop_down",
      "type_config": {"options": [{"id": "...", "name": "ECR", "orderindex": 0}, ...]},
      "value": 0  # or an option id string, or a list of them, or a raw value
    }

These helpers resolve that to something usable without every caller
re-implementing the lookup. The previous pattern (see
``app/compute/daily_insights.py`` pre-2026-04-20) inlined this logic
twice; new code should use these helpers instead.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def _fields(task: Any) -> Iterable[dict[str, Any]]:
    raw = getattr(task, "custom_fields_json", None) or []
    return [f for f in raw if isinstance(f, dict)]


def _find(task: Any, name: str) -> dict[str, Any] | None:
    target = name.lower()
    for f in _fields(task):
        if (f.get("name") or "").lower() == target:
            return f
    return None


def get_dropdown_label(task: Any, name: str) -> str | None:
    """Return the human-readable label for a single-select dropdown field,
    or None if the field is absent or has no value selected."""
    f = _find(task, name)
    if f is None:
        return None
    opts = (f.get("type_config") or {}).get("options") or []
    val = f.get("value")
    if val is None:
        return None
    # ClickUp sends either the option's orderindex (int) or its id (string)
    if isinstance(val, int) and 0 <= val < len(opts):
        return (opts[val] or {}).get("name")
    if isinstance(val, str):
        for o in opts:
            if isinstance(o, dict) and o.get("id") == val:
                return o.get("name")
    return None


def get_multi_select_labels(task: Any, name: str) -> list[str]:
    """Return the labels selected in a multi-select labels field.
    Order matches the options list; empty list if unset."""
    f = _find(task, name)
    if f is None:
        return []
    opts = (f.get("type_config") or {}).get("options") or []
    val = f.get("value")
    if not val:
        return []
    labels: list[str] = []
    # Multi-select comes back as a list of option ids (strings).
    if isinstance(val, list):
        for entry in val:
            if isinstance(entry, str):
                for o in opts:
                    if isinstance(o, dict) and o.get("id") == entry:
                        nm = o.get("name")
                        if nm:
                            labels.append(str(nm))
                        break
            elif isinstance(entry, int) and 0 <= entry < len(opts):
                nm = (opts[entry] or {}).get("name")
                if nm:
                    labels.append(str(nm))
            elif isinstance(entry, dict):
                # Some workspaces ship the expanded option dict
                nm = entry.get("name")
                if nm:
                    labels.append(str(nm))
    return labels


def get_date(task: Any, name: str) -> datetime | None:
    """Return a UTC datetime for a date field. ClickUp stores dates as
    millisecond-timestamp strings."""
    f = _find(task, name)
    if f is None:
        return None
    val = f.get("value")
    if val is None or val == "":
        return None
    try:
        ms = int(val) if not isinstance(val, dict) else int(val.get("date", 0))
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def get_text(task: Any, name: str) -> str | None:
    """Return the raw text value of a short_text / text field, or None."""
    f = _find(task, name)
    if f is None:
        return None
    val = f.get("value")
    if val is None:
        return None
    s = str(val).strip()
    return s or None
