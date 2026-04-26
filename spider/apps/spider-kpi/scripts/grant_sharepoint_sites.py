#!/usr/bin/env python3
"""One-time SharePoint Sites.Selected grant tool.

Microsoft's ``Sites.Selected`` application permission is a "you may be
granted access to specific sites" credential — it returns 403 on every
SharePoint site by default. To actually read a site, an admin has to
explicitly POST a permissions row pointing the dashboard's client_id
at that site.

This script does that, interactively, via Microsoft Graph's
device-code OAuth flow:

  1. The script asks Microsoft for a device code
  2. Joseph (or whoever runs this) opens microsoft.com/devicelogin in
     a browser, signs in with their AMW admin account, enters the code
  3. Microsoft hands back a delegated token with SharePoint admin
     scope (because Joseph IS a SharePoint admin)
  4. The script uses that token to POST /sites/{site_id}/permissions
     for each site URL on the allowlist, granting the dashboard app
     `read`

Run once now, run again if new sites get added to the allowlist. No
permanent admin over-privilege on the dashboard app — `Sites.Selected`
stays the only permission the dashboard owns at runtime.

Usage:
    cd backend
    ../.venv/bin/python ../scripts/grant_sharepoint_sites.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests


# Microsoft's public Graph PowerShell client_id — a well-known public
# client app that anyone can use for delegated device-code flows. Means
# Joseph doesn't need to register a separate app for this script.
GRAPH_POWERSHELL_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

# Spider KPI Dashboard app — what we're granting permission TO.
DASHBOARD_CLIENT_ID = os.environ.get("MS_GRAPH_CLIENT_ID", "00dfd98f-5280-47ab-a446-59928df3352d")
DASHBOARD_DISPLAY_NAME = "Spider KPI Dashboard"

TENANT_ID = os.environ.get("MS_GRAPH_DEFAULT_TENANT_ID", "2e9275cf-ffd9-4f18-abdc-c0ac8d85e26f")

# Sites to grant. Hostname must match the tenant's SharePoint domain.
ALLOWLIST = [
    "alignmachineworks.sharepoint.com:/sites/ATL-SPG-00163-SpiderHuntsman2",
    "alignmachineworks.sharepoint.com:/sites/ATL-SPG-00176-GiantHuntsman",
    "alignmachineworks.sharepoint.com:/sites/ATL-SPG-00177-GiantWebCraft2",
    "alignmachineworks.sharepoint.com:/sites/ATL-SPG-00171-WebCraft",
    "alignmachineworks.sharepoint.com:/sites/RuggedOutdoors",
]


def device_code_login(tenant: str) -> str:
    """Run device-code flow against the tenant. Returns access_token."""
    # 1. Initiate
    init = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
        data={
            "client_id": GRAPH_POWERSHELL_CLIENT_ID,
            "scope": "https://graph.microsoft.com/Sites.FullControl.All offline_access",
        },
    )
    init.raise_for_status()
    init_d = init.json()

    print("\n" + "=" * 70)
    print(init_d["message"])
    print("=" * 70 + "\n")

    # 2. Poll
    deadline = time.time() + int(init_d.get("expires_in", 900))
    interval = int(init_d.get("interval", 5))
    while time.time() < deadline:
        time.sleep(interval)
        r = requests.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": GRAPH_POWERSHELL_CLIENT_ID,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": init_d["device_code"],
            },
        )
        body = r.json()
        if r.status_code == 200 and body.get("access_token"):
            print("✓ Signed in successfully.\n")
            return body["access_token"]
        if body.get("error") == "authorization_pending":
            continue
        if body.get("error") == "slow_down":
            interval += 5
            continue
        print(f"✗ Unexpected response: {body}", file=sys.stderr)
        sys.exit(1)
    print("✗ Sign-in timed out.", file=sys.stderr)
    sys.exit(1)


def lookup_site_id(token: str, hostname_path: str) -> str | None:
    """Resolve a hostname:/sites/path into a Graph site_id."""
    r = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{hostname_path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code == 200:
        return r.json().get("id")
    print(f"  ✗ lookup failed for {hostname_path}: {r.status_code} {r.text[:200]}")
    return None


def grant_read(token: str, site_id: str) -> bool:
    """POST a Sites.Selected `read` grant for the dashboard app on a
    specific site. Idempotent — Microsoft returns 201 the first time
    and the same row body on subsequent calls if it's already there."""
    body = {
        "roles": ["read"],
        "grantedToIdentities": [
            {
                "application": {
                    "id": DASHBOARD_CLIENT_ID,
                    "displayName": DASHBOARD_DISPLAY_NAME,
                }
            }
        ],
    }
    r = requests.post(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/permissions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    if r.status_code in (200, 201):
        return True
    print(f"  ✗ grant failed: {r.status_code} {r.text[:200]}")
    return False


def main() -> int:
    print(f"Tenant: {TENANT_ID}")
    print(f"Granting `read` to app: {DASHBOARD_DISPLAY_NAME} ({DASHBOARD_CLIENT_ID})")
    print(f"Sites to grant ({len(ALLOWLIST)}):")
    for s in ALLOWLIST:
        print(f"  - {s}")

    token = device_code_login(TENANT_ID)

    granted = 0
    for site_path in ALLOWLIST:
        print(f"→ {site_path}")
        site_id = lookup_site_id(token, site_path)
        if not site_id:
            continue
        if grant_read(token, site_id):
            print(f"  ✓ granted (site_id={site_id[:30]}...)")
            granted += 1
    print(f"\n{granted}/{len(ALLOWLIST)} sites granted.")
    return 0 if granted == len(ALLOWLIST) else 1


if __name__ == "__main__":
    raise SystemExit(main())
