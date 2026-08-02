"""The core detector: recover the text a vision model would read - both text
that's plainly legible through a normal OCR pass and text hidden at low
contrast, recovered by locally contrast-boosting whatever contrast.py
flagged - and scan it for directives aimed at an agent rather than a human.

Every other layer is a heuristic proxy for "something looks off"; this one
reads the actual words and matches them against known injection phrasing -
it's what makes the rest of the scan worth running.

Region passes are bounded two ways: nearby candidate regions are merged and
capped at MAX_OCR_REGIONS (each region is its own tesseract subprocess, and
without a cap a busy or crafted screenshot can demand hundreds of them), and
every pass is charged against the scan's wall-clock budget. Anything skipped
for either reason lands in the budget's notes so a truncated scan reports
itself as truncated.
"""

from __future__ import annotations

from .. import ocr as ocr_mod
from . import patterns
from ..finding import Finding, Region, Severity

RULE_ID = "FW-001"

MAX_OCR_REGIONS = 24  # biggest regions first; the largest hidden-text region
# is the most likely payload, and 24 subprocesses is already a generous scan
REGION_MERGE_GAP = 12  # px; regions closer than this are one payload split
# by the block grid, and reading them as one crop is both faster and better
# for OCR than reading fragments


def find(image, low_contrast_regions=None, timeout=None, lang=None, budget=None):
    """Returns (findings, words, lines). `words` and `lines` are exposed so
    the tiny-text check can reuse this OCR pass instead of paying for a
    second one. `lines` come only from the primary full-image pass - a
    cropped, upscaled region has no meaningful "line" of its own."""
    budget = budget if budget is not None else ocr_mod.ScanBudget()
    per_pass = timeout if timeout else ocr_mod.DEFAULT_TIMEOUT

    words, lines = ocr_mod.ocr_image(image, timeout=budget.clamp(per_pass), lang=lang)
    words = list(words)

    # Keep tesseract's line grouping in the text we scan. Several patterns
    # anchor to the start of a line (a "system:" header, "new instructions:")
    # with re.MULTILINE; joining every word into one space-separated blob
    # collapses the whole screenshot onto a single line, so a header sitting
    # anywhere but the very top could never match. Reconstruct line breaks from
    # the line boxes, and fall back to the flat join only if tesseract gave us
    # words but no line structure.
    segments = [ln.text for ln in lines] if lines else [" ".join(w.text for w in words)]

    boxes = _bounded_boxes(low_contrast_regions, None, budget)
    for index, box in enumerate(boxes):
        if budget.exhausted():
            budget.note(
                f"the scan time budget ran out with {len(boxes) - index} flagged "
                f"region(s) unread; the scan is partial"
            )
            break
        try:
            region_words = ocr_mod.ocr_region(image, box, timeout=budget.clamp(per_pass), lang=lang)
        except ocr_mod.OcrTimeout:
            budget.note("tesseract timed out on a flagged region; that region went unread")
            continue
        words.extend(region_words)
        if region_words:
            # A locally-boosted region is its own recovered line: give it its
            # own line so a header hidden at low contrast anchors too.
            segments.append(" ".join(w.text for w in region_words))

    full_text = "\n".join(segments)
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


def _bounded_boxes(low_contrast_regions, extra_regions, budget) -> list:
    """Candidate regions merged, biggest first, capped at MAX_OCR_REGIONS.

    Each surviving box costs one tesseract subprocess, so this is the line
    between "scan finishes" and "crafted screenshot pins the CPU for hours".
    Dropping past the cap is recorded as a note, never done silently.
    """
    regions = list(low_contrast_regions or []) + list(extra_regions or [])
    boxes = _merge_boxes(
        [(r.left, r.top, r.left + r.width, r.top + r.height) for r in regions]
    )
    boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    if len(boxes) > MAX_OCR_REGIONS:
        budget.note(
            f"{len(boxes) - MAX_OCR_REGIONS} candidate region(s) beyond the "
            f"{MAX_OCR_REGIONS}-region OCR cap went unread; the scan is partial"
        )
        boxes = boxes[:MAX_OCR_REGIONS]
    return boxes


def _merge_boxes(boxes, gap: int = REGION_MERGE_GAP) -> list:
    """Union boxes that overlap or sit within `gap` px of each other, to a
    fixpoint. The block grid loves splitting one paragraph of hidden text
    into several adjacent regions; one merged crop OCRs better and cheaper
    than each fragment alone."""
    boxes = list(boxes)
    merged = True
    while merged:
        merged = False
        out = []
        for box in boxes:
            for i, other in enumerate(out):
                if (
                    box[0] <= other[2] + gap
                    and other[0] <= box[2] + gap
                    and box[1] <= other[3] + gap
                    and other[1] <= box[3] + gap
                ):
                    out[i] = (
                        min(box[0], other[0]),
                        min(box[1], other[1]),
                        max(box[2], other[2]),
                        max(box[3], other[3]),
                    )
                    merged = True
                    break
            else:
                out.append(box)
        boxes = out
    return boxes


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
