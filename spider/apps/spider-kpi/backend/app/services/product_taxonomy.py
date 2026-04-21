"""Map raw AWS device ``grill_type`` strings to a human product family.

Per Joseph (2026-04-20), the actual fleet today is three product lines:

* **Weber Kettle (with Venom)** — older JOEHY firmware (``W:K:22:1:V``
  AWS model) *and* newer ADN V2 firmware that reports ``Kettle`` or legacy
  ``Kettle22``. The word "Weber" was intentionally dropped from firmware
  to avoid trademark issues, so the AWS side says "Kettle" even though
  the grill is a Weber Kettle. The same ADN firmware binary covers
  Kettle 22, Kettle 26, and Webcraft.
* **Huntsman** — ADN V2 firmware reporting ``Huntsman``, *and* JOEHY
  firmware ``01.01.33`` running on ``W:K:22:1:V`` (factory flashed 01.01.33
  for Huntsman to get the 0-700°F range, 01.01.34 for Weber Kettle).
* **Giant Huntsman** — reserved. Maps from future AWS model strings;
  today's data doesn't distinguish it from Huntsman yet.

Deprecated / never use (will be treated as Unknown so a data error is
visible rather than silently rolled into another family):

* ``kettle_22``
* ``C:G:XT:1:D``
"""
from __future__ import annotations

from typing import Optional


FAMILY_WEBER_KETTLE = "Weber Kettle"
FAMILY_HUNTSMAN = "Huntsman"
FAMILY_GIANT_HUNTSMAN = "Giant Huntsman"
FAMILY_UNKNOWN = "Unknown"

ALL_FAMILIES = (FAMILY_WEBER_KETTLE, FAMILY_HUNTSMAN, FAMILY_GIANT_HUNTSMAN, FAMILY_UNKNOWN)

# Deprecated AWS grill_type tokens — should not appear on any current
# device. Surface them as Unknown so bad data is visible.
DEPRECATED_GRILL_TYPES = frozenset({"kettle_22", "C:G:XT:1:D"})

# JOEHY's single AWS model — used for both Huntsman and Weber Kettle,
# distinguished only by which firmware the factory flashed.
JOEHY_MODEL = "W:K:22:1:V"

# JOEHY firmware versions the factory uses for Huntsman (0-700°F range).
# 01.01.33 is the primary; include variants defensively.
JOEHY_HUNTSMAN_FIRMWARE = frozenset({"01.01.33"})


def classify_product(
    grill_type: Optional[str],
    firmware_version: Optional[str] = None,
) -> str:
    """Return the product family label for a given AWS grill_type.

    Case-insensitive on the family names ("kettle" == "Kettle"), but
    preserves the exact ``W:K:22:1:V`` match for the JOEHY path.
    """
    if not grill_type:
        return FAMILY_UNKNOWN

    raw = str(grill_type).strip()
    if raw in DEPRECATED_GRILL_TYPES:
        return FAMILY_UNKNOWN

    if raw == JOEHY_MODEL:
        # JOEHY firmware flavour tells us which product.
        fw = (firmware_version or "").strip()
        if fw in JOEHY_HUNTSMAN_FIRMWARE:
            return FAMILY_HUNTSMAN
        return FAMILY_WEBER_KETTLE

    low = raw.lower()
    if low == "huntsman":
        return FAMILY_HUNTSMAN
    if low == "giant huntsman" or low == "giant_huntsman":
        return FAMILY_GIANT_HUNTSMAN
    if low in {"kettle", "kettle22"}:
        return FAMILY_WEBER_KETTLE

    return FAMILY_UNKNOWN
