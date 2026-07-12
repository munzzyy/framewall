"""Tiny text: text present but rendered too small for a human to read at a
glance while still being legible to OCR (and therefore to a vision model).

With OCR available this is precise: it reuses the line boxes tesseract
already produced for the injection-text layer and measures each line's real
height. Without OCR it falls back to a coarser, Pillow-only structural
estimate using the same block-grid technique as the low-contrast check, this
time looking for genuinely high-contrast (human-visible) detail confined to
a thin strip - noisier, and says so in the finding text.
"""

from __future__ import annotations

from PIL import ImageStat

from .. import grid
from ..finding import Finding, Region, Severity

RULE_ID = "FW-003"

MIN_HEIGHT_FRACTION = 0.02  # line height below 2% of the shorter side reads as "tiny"...
MAX_HEIGHT_PX = 12.0  # ...but capped in absolute pixels, so a 4K screenshot's normal
# body text (which is many more pixels tall for the same physical size) doesn't
# start tripping this just because the whole image got bigger.
MAX_FINDINGS_REPORTED = 20


def find_from_lines(lines, image_size) -> list:
    """Flag whole text lines shorter than the legibility threshold. Lines,
    not individual words: a word's own bounding box is just its ink, so a
    short, all-lowercase word ("is", "a") in an ordinary paragraph measures
    a fraction of the line's real height and would otherwise look tiny on
    its own."""
    width, height = image_size
    threshold = min(MIN_HEIGHT_FRACTION * min(width, height), MAX_HEIGHT_PX)
    tiny = [ln for ln in lines if 0 < ln.height < threshold]

    findings = []
    for ln in tiny[:MAX_FINDINGS_REPORTED]:
        findings.append(
            Finding(
                rule_id=RULE_ID,
                layer="tiny-text",
                severity=Severity.MEDIUM,
                title="Text below legible size",
                detail=(
                    f"A line of text is {ln.height}px tall in a {width}x{height}px "
                    f"image ({ln.height / min(width, height) * 100:.2f}% of the "
                    f"shorter side) - small enough a human is unlikely to read "
                    f"it, large enough OCR still can."
                ),
                region=Region(ln.left, ln.top, ln.width, ln.height),
                snippet=ln.text[:200],
                remediation="Fine print is normal; check whether this text carries directives aimed at an agent.",
            )
        )
    return findings


# --- OCR-unavailable fallback -------------------------------------------------

_BLOCK = 4  # small enough that a ~9-11px line's height quantizes to close to
# its real size instead of overshooting into the next multiple of the block.
_DETAIL_STDDEV_MIN = 18  # real, human-visible contrast (unlike the low-contrast check)
_MIN_BLOCKS = 3
_MIN_ASPECT = 2.0  # a legible text line reads wider than it is tall
_MAX_WIDTH_FRACTION = 0.5  # a single hidden line of text isn't going to span
# half the screen - something that wide and this thin is almost always a
# divider, a card edge, or a header/body boundary, not text.
_MAX_FILL_RATIO = 0.85  # a straight edge lights up *every* block along its
# length with no gaps; real text has letter- and word-shaped gaps in it.
# Rejecting near-total fill is what tells the two apart without OCR.


def find_heuristic(gray_image) -> list:
    """Pillow-only estimate used when tesseract isn't available. Flags thin,
    wide, gap-containing strips of high-detail content - the rough shape of
    a small line of text - without ever reading what they say. Straight
    edges (panel borders, button outlines, header dividers) are exactly as
    thin and wide as text, so ruling those out is most of the work here."""
    width, height = gray_image.size
    threshold_px = min(MIN_HEIGHT_FRACTION * min(width, height), MAX_HEIGHT_PX)
    cols, rows = grid.block_grid(width, height, _BLOCK)
    flagged = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            box = grid.block_box(c, r, _BLOCK, width, height)
            stddev = ImageStat.Stat(gray_image.crop(box)).stddev[0]
            if stddev >= _DETAIL_STDDEV_MIN:
                flagged[r][c] = True

    findings = []
    for left, top, w, h, n_blocks in grid.group_flagged(flagged, cols, rows, _BLOCK, width, height):
        if n_blocks < _MIN_BLOCKS or h == 0:
            continue
        if w > width * _MAX_WIDTH_FRACTION:
            continue
        cols_span = max(1, -(-w // _BLOCK))
        rows_span = max(1, -(-h // _BLOCK))
        fill_ratio = n_blocks / (cols_span * rows_span)
        if fill_ratio > _MAX_FILL_RATIO:
            continue
        if h <= threshold_px and w >= h * _MIN_ASPECT:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    layer="tiny-text",
                    severity=Severity.MEDIUM,
                    title="Text-shaped region below legible size (heuristic)",
                    detail=(
                        f"A {w}x{h}px high-detail strip is only {h}px tall in a "
                        f"{width}x{height}px image - shaped like a line of text "
                        f"this small. No OCR was available to confirm this is "
                        f"actual text or read what it says."
                    ),
                    region=Region(left, top, w, h),
                    remediation="Install tesseract and re-scan to confirm and read this text.",
                )
            )
    return findings[:MAX_FINDINGS_REPORTED]
