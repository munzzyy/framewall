"""The core detector: recover the text a vision model would read - both text
that's plainly legible through a normal OCR pass and text hidden at low
contrast, recovered by locally contrast-boosting whatever contrast.py
flagged - and scan it for directives aimed at an agent rather than a human.

Every other layer is a heuristic proxy for "something looks off"; this one
reads the actual words and matches them against known injection phrasing -
it's what makes the rest of the scan worth running.
"""

from __future__ import annotations

from .. import ocr as ocr_mod
from . import patterns
from ..finding import Finding, Region, Severity

RULE_ID = "FW-001"


def find(image, low_contrast_regions=None, timeout=None):
    """Returns (findings, words, lines). `words` and `lines` are exposed so
    the tiny-text check can reuse this OCR pass instead of paying for a
    second one. `lines` come only from the primary full-image pass - a
    cropped, upscaled region has no meaningful "line" of its own."""
    kwargs = {"timeout": timeout} if timeout else {}
    words, lines = ocr_mod.ocr_image(image, **kwargs)
    words = list(words)

    for region in low_contrast_regions or []:
        box = (region.left, region.top, region.left + region.width, region.top + region.height)
        words.extend(ocr_mod.ocr_region(image, box, **kwargs))

    full_text = " ".join(w.text for w in words)
    findings = []
    for title, detail, _span, matched in patterns.scan_text(full_text):
        findings.append(
            Finding(
                rule_id=RULE_ID,
                layer="injection-text",
                severity=Severity.HIGH,
                title=title,
                detail=detail,
                region=_locate(words, matched),
                snippet=matched[:200],
                remediation="Treat this image as untrusted input. Don't let an agent act on an instruction recovered from inside a screenshot.",
            )
        )
    return findings, words, lines


def _locate(words, matched_text):
    """Best-effort: point at the first recovered word that overlaps the
    match, rather than trying to map exact character spans back through the
    OCR word-join. Good enough for "where to look", not a precise span."""
    first = matched_text.split()[0].lower() if matched_text.split() else ""
    if not first:
        return None
    for w in words:
        if first in w.text.lower():
            return Region(w.left, w.top, w.width, w.height)
    return None
