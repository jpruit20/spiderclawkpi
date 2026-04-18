"""Probe-failure classifier — identifies CX tickets where a customer is
reporting an actual hardware probe failure (needs a replacement / the
probe stopped working), as distinct from setup/usage questions.

Thesis (Joseph, 2026-04-18): the telemetry-derived "probe error rate"
in PE is misleading because a shadow "probe error" fires both when
hardware fails AND when the user simply didn't install a probe. No
pit probe installed = user hasn't finished setup. No meat probe = a
valid use case (not every cook needs one).

Real probe-failure rate comes from the CX side: customers writing in
saying "my probe stopped working, I need a new one". That gets
normalized against the deployed fleet (active devices in window, with
an ~13k installed-base context) to yield a meaningful failure rate.

Classifier is keyword-based — fast, deterministic, explainable. Can
layer an AI pass later if precision is insufficient.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# Phrases that strongly imply a hardware probe failure report.
PROBE_FAILURE_PHRASES = [
    r"\bprobe (stopped|quit|isn'?t|is not) (working|reading|responding)\b",
    r"\bprobe (failed|died|broke|broken|is broken)\b",
    r"\bprobe (is )?(defective|faulty|bad|dead)\b",
    r"\bprobe (no longer|doesn'?t|does not) (work|read|respond)\b",
    r"\b(need|want|requesting|send me a?) (a )?(new |replacement )?probe\b",
    r"\breplacement (for (my|the) )?probe\b",
    r"\bprobe replacement\b",
    r"\bnew probe\b.*(needed|please|required|send)",
    r"\b(meat|pit|temperature) probe (stopped|isn'?t|is not|failed|broken|died|dead|doesn'?t)\b",
    r"\bprobe (came|is|arrived) (broken|damaged|defective|dead)\b",
    r"\bprobe (shows|reading|showing) (wrong|incorrect|way off|ERR|NaN|dashes|--)",
    r"\bprobe (wire|cable|cord) (is )?(broken|damaged|cut|frayed|severed)\b",
    r"\bprobe .{0,20}(inaccurate|wildly (off|wrong)|stuck at)",
    r"\b(my |the )?probe (just )?(stopped|quit)\b",
    r"\bprobe (won'?t|will not) (read|connect|pair|work)\b",
    r"\bfood probe (stopped|failed|broken|not working)\b",
    r"\bwarranty .{0,20}probe\b",
    r"\bprobe .{0,20}warranty\b",
    r"\bprobe (is )?(fried|burnt|melted)\b",
]

# Phrases that indicate this is a setup/usage question, not a failure.
NON_PROBE_FAILURE_OVERRIDES = [
    r"how (do|can) i (install|use|connect|pair|set ?up|calibrate) .{0,30}probe",
    r"probe .{0,20}(installation|install|setup|set ?up|calibration) (help|question|instructions)",
    r"which probes? (are|is) compatible",
    r"what probes? (do|does|can|should)",
    r"can i (use|add|buy) .{0,20}(additional|more|another|extra) probes?",
    r"probe .{0,20}(compatible|compatibility)",
    r"where (do|should|can) i (plug|put|insert) .{0,20}probe",
    r"probe order(ed)? (status|update)",
    r"buy (an? )?extra probe",
    r"purchase .{0,20}probe",
    # Order-tracking / shipping threads that mention probes incidentally.
    r"tracking (info|number) .{0,30}probe",
]

# Tags that signal CX has already classified this as a probe hardware issue.
PROBE_FAILURE_TAGS = {
    "probe-failure",
    "probe-replacement",
    "probe-warranty",
    "broken-probe",
    "defective-probe",
    "hardware-probe",
}

# Outbound-notification reply markers (suppress replies to our own threads).
OUTBOUND_THREAD_MARKERS = [
    r"^re:\s*.*spider grills .*shipping update",
    r"^re:\s*.*your probe replacement .*is on the way",
    r"^re:\s*.*replacement .*(has been )?shipped",
]


@dataclass
class ProbeFailureResult:
    is_probe_failure: bool
    confidence: float  # 0.0 - 1.0
    matched_rule: Optional[str]
    override_rule: Optional[str]


def _any_match(text: str, patterns: list[str]) -> Optional[str]:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


def classify_probe_failure(
    subject: Optional[str],
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> ProbeFailureResult:
    """Return ProbeFailureResult. ``is_probe_failure=True`` if the ticket
    reports an actual hardware probe failure needing replacement/repair."""
    subject = (subject or "").strip()
    description = (description or "").strip()
    tags = tags or []

    combined = f"{subject}\n{description}".lower()
    tag_lower = [str(t).lower() for t in tags]

    # 1) Explicit CX tags win (CX triage trusted).
    if any(t in PROBE_FAILURE_TAGS for t in tag_lower):
        return ProbeFailureResult(True, 0.95, matched_rule="explicit_tag", override_rule=None)

    # 2) Setup/usage overrides — question about how probes work, not a failure.
    override = _any_match(combined, NON_PROBE_FAILURE_OVERRIDES)
    if override:
        return ProbeFailureResult(False, 0.0, matched_rule=None, override_rule=override)

    # 3) Outbound-thread reply markers.
    outbound = _any_match(subject.lower(), OUTBOUND_THREAD_MARKERS)
    if outbound:
        return ProbeFailureResult(False, 0.0, matched_rule=None, override_rule=f"outbound_thread: {outbound}")

    # 4) Strong failure phrases.
    rule = _any_match(combined, PROBE_FAILURE_PHRASES)
    if rule:
        subj_has = _any_match(subject.lower(), PROBE_FAILURE_PHRASES)
        return ProbeFailureResult(True, 0.9 if subj_has else 0.7, matched_rule=rule, override_rule=None)

    return ProbeFailureResult(False, 0.0, matched_rule=None, override_rule=None)
