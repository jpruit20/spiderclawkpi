"""Role + scoped-page access control.

The dashboard has two related concerns that live here:

1. **Role** (``admin`` / ``editor`` / ``viewer``).

   * ``admin`` — full read + write, can manage users. Joseph, effectively.
   * ``editor`` — full read + write on the feature surfaces. The old
     "logged in" default. Internal @spidergrills.com team.
   * ``viewer`` — read-only. No mutating calls succeed; mutation UI is
     hidden in the frontend.

2. **Page scope** — a route-prefix allowlist. Null = role's default set
   (admin/editor see everything; viewer sees everything viewer-safe).
   A list like ``["/division/product-engineering"]`` restricts the
   account to routes whose pathname starts with one of those prefixes.

These two fields let us on-board external collaborators (e.g. a firmware
contractor, a vendor, an investor) to a tightly scoped slice of the
dashboard without standing up a whole separate product.

The ``INVITED_USERS`` map below is an explicit, code-reviewed allowlist
of external emails permitted to create accounts outside
``settings.allowed_signup_domains``. It's intentionally hand-curated; if
we later need a UI, the data model already supports per-user role and
page_scope — just wire an admin form to ``AuthUser`` directly.
"""
from __future__ import annotations

from typing import Optional


ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"

ALL_ROLES = (ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER)

# Roles that grant write access (POST/PUT/PATCH/DELETE on app endpoints).
WRITE_ROLES = frozenset({ROLE_ADMIN, ROLE_EDITOR})


class InvitedUser:
    """Invite record for a single external email.

    ``role`` and ``page_scope`` are what the signup handler writes onto
    the ``AuthUser`` row when the invitee first creates their account.
    """

    __slots__ = ("email", "role", "page_scope", "note")

    def __init__(
        self,
        email: str,
        *,
        role: str,
        page_scope: Optional[list[str]] = None,
        note: str = "",
    ) -> None:
        if role not in ALL_ROLES:
            raise ValueError(f"InvitedUser: unknown role {role!r}")
        self.email = email.strip().lower()
        self.role = role
        self.page_scope = list(page_scope) if page_scope else None
        self.note = note


# --------------------------------------------------------------------------
# INVITED EXTERNAL USERS
# --------------------------------------------------------------------------
# Emails listed here can sign up even if their domain isn't in
# ``settings.allowed_signup_domains``. They are assigned the given role +
# page_scope on first-create. Rotate as people come and go.
INVITED_USERS: dict[str, InvitedUser] = {
    inv.email: inv for inv in [
        InvitedUser(
            email="mat.cosentini@gmail.com",
            role=ROLE_VIEWER,
            page_scope=[
                "/division/product-engineering",
                "/division/product-engineering/firmware",
            ],
            note=(
                "External collaborator — scoped to Product Engineering "
                "(Fleet Health) and Firmware Hub, view-only."
            ),
        ),
    ]
}


def find_invited_user(email: str) -> Optional[InvitedUser]:
    return INVITED_USERS.get((email or "").strip().lower())


def default_role_for_new_user(email: str, *, is_first_user: bool) -> str:
    """Role to assign on signup.

    * First-ever user boots to admin (preserves existing behaviour).
    * Pre-invited external users get the role declared in INVITED_USERS.
    * Everyone else defaults to ``editor`` — their domain was already
      whitelisted, they're internal team.
    """
    if is_first_user:
        return ROLE_ADMIN
    invite = find_invited_user(email)
    if invite:
        return invite.role
    return ROLE_EDITOR


def default_page_scope_for_new_user(email: str) -> Optional[list[str]]:
    invite = find_invited_user(email)
    if invite and invite.page_scope:
        return list(invite.page_scope)
    return None


def email_allowed_to_signup(email: str, allowed_domains: list[str]) -> bool:
    """Either the email's domain is in ``allowed_domains`` OR the email
    has an explicit invite. Keeps the domain gate as the primary path;
    invites are the narrow exception."""
    from app.services.auth import email_domain_allowed
    if email_domain_allowed(email, allowed_domains):
        return True
    return find_invited_user(email) is not None


def can_write(role: Optional[str]) -> bool:
    return (role or "") in WRITE_ROLES


def is_admin_role(role: Optional[str]) -> bool:
    return role == ROLE_ADMIN
