"""Division ownership: who can edit KPIs, recommendations, and other
division-scoped artifacts.

Canonical mapping pulled from ai_scoping.py division→email so we have
one source of truth across the codebase. Joseph is the platform owner
and can edit any division.
"""
from __future__ import annotations

from typing import Optional


# Canonical division code → owner email. Aligned to ai_scoping.py +
# the operator's stated structure. New divisions get added here.
DIVISION_OWNERS: dict[str, str] = {
    "marketing":     "bailey@spidergrills.com",
    "cx":            "jeremiah@spidergrills.com",
    "operations":    "conor@spidergrills.com",
    "pe":            "kyle@alignmachineworks.com",
    "manufacturing": "david@alignmachineworks.com",
}

# Reverse: email → division. Useful when the request user is a lead
# and we need to scope what they see.
OWNER_DIVISION: dict[str, str] = {v.lower(): k for k, v in DIVISION_OWNERS.items()}

PLATFORM_OWNER_EMAIL = "joseph@spidergrills.com"


def is_platform_owner(email: Optional[str]) -> bool:
    return (email or "").lower() == PLATFORM_OWNER_EMAIL


def can_edit_division(email: Optional[str], division: Optional[str]) -> bool:
    """Platform owner can edit anything. A division lead can only edit
    their own division. ``division=None`` (global target) is platform-
    owner-only."""
    e = (email or "").lower()
    if is_platform_owner(e):
        return True
    if division is None:
        return False
    return DIVISION_OWNERS.get(division, "").lower() == e


def editable_divisions_for(email: Optional[str]) -> list[str]:
    """Return the list of divisions this user can manage. Platform
    owner gets all; division leads get their one. Empty list = read-only."""
    if is_platform_owner(email):
        return list(DIVISION_OWNERS.keys()) + [None]  # type: ignore[list-item]
    e = (email or "").lower()
    if e in OWNER_DIVISION:
        return [OWNER_DIVISION[e]]
    return []


def division_label(division: Optional[str]) -> str:
    return {
        None: "All Divisions (Global)",
        "marketing": "Marketing",
        "cx": "Customer Experience",
        "operations": "Operations",
        "pe": "Product Engineering",
        "manufacturing": "Production & Manufacturing",
    }.get(division, division or "Global")
