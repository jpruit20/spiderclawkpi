"""Access-control mapping for the AI dashboard editor.

Maps authenticated user emails to the division pages they are allowed to edit.
Each non-admin user can WRITE only their own division page .tsx file but may
READ any file under ``frontend/src/`` for context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

# ── scope definitions ──

DIVISION_TO_FILE: dict[str, str] = {
    "marketing": "frontend/src/pages/MarketingDivision.tsx",
    "customer-experience": "frontend/src/pages/CustomerExperienceDivision.tsx",
    "product-engineering": "frontend/src/pages/ProductEngineeringDivision.tsx",
    "operations": "frontend/src/pages/OperationsDivision.tsx",
    "production-manufacturing": "frontend/src/pages/ProductionManufacturingDivision.tsx",
}

DIVISION_LABELS: dict[str, str] = {
    "marketing": "Marketing",
    "customer-experience": "Customer Experience",
    "product-engineering": "Product / Engineering",
    "operations": "Operations",
    "production-manufacturing": "Production / Manufacturing",
}

EMAIL_TO_DIVISIONS: dict[str, list[str]] = {
    "bailey@spidergrills.com": ["marketing"],
    "jeremiah@spidergrills.com": ["customer-experience"],
    "conor@spidergrills.com": ["operations"],
    "kyle@alignmachineworks.com": ["product-engineering"],
    "david@alignmachineworks.com": ["production-manufacturing"],
    "joseph@spidergrills.com": list(DIVISION_TO_FILE.keys()),  # admin – all divisions
}

# Paths that are always blocked from reading or writing, even for admins.
BLOCKED_PATTERNS: set[str] = {
    ".env",
    ".git",
    "node_modules",
    "backend",
    "deploy",
    "bridge",
    "scripts",
    "dist",
    "__pycache__",
}


@dataclass(frozen=True)
class UserScope:
    """Resolved scope for a single AI request."""

    email: str
    is_admin: bool
    division: str
    division_label: str
    editable_file: str          # relative to workspace root
    readable_prefix: str        # e.g. "frontend/src/"


def get_user_divisions(email: str, is_admin: bool = False) -> list[str]:
    """Return the division slugs a user may access."""
    normalized = email.strip().lower()
    if is_admin:
        return list(DIVISION_TO_FILE.keys())
    return EMAIL_TO_DIVISIONS.get(normalized, [])


def resolve_scope(email: str, is_admin: bool, division: str) -> Optional[UserScope]:
    """Build a ``UserScope`` for *email* targeting *division*, or ``None``."""
    allowed = get_user_divisions(email, is_admin)
    if division not in allowed:
        return None
    return UserScope(
        email=email.strip().lower(),
        is_admin=is_admin,
        division=division,
        division_label=DIVISION_LABELS.get(division, division),
        editable_file=DIVISION_TO_FILE[division],
        readable_prefix="frontend/src/",
    )


# ── path validation ──

def _workspace_root() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "workspace_root", ".")).resolve()


def resolve_safe_path(relative: str) -> Optional[Path]:
    """Resolve *relative* against the workspace root.

    Returns ``None`` if the resolved path escapes the workspace or hits a
    blocked directory segment.
    """
    root = _workspace_root()
    try:
        resolved = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    # Must stay inside workspace
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    # Check each path component against the block list
    parts = resolved.relative_to(root).parts
    for part in parts:
        if part in BLOCKED_PATTERNS or part.startswith(".env"):
            return None
    return resolved


def is_path_readable(scope: UserScope, relative: str) -> bool:
    """Can the user read *relative* within the workspace?"""
    resolved = resolve_safe_path(relative)
    if resolved is None:
        return False
    root = _workspace_root()
    rel = str(resolved.relative_to(root))
    return rel.startswith(scope.readable_prefix)


def is_path_editable(scope: UserScope, relative: str) -> bool:
    """Can the user write to *relative* within the workspace?"""
    resolved = resolve_safe_path(relative)
    if resolved is None:
        return False
    root = _workspace_root()
    rel = str(resolved.relative_to(root))
    if scope.is_admin:
        # Admin may edit any page or component under frontend/src/
        return rel.startswith("frontend/src/pages/") or rel.startswith("frontend/src/components/")
    return rel == scope.editable_file
