"""High-frequency two-tone camouflage (Pillow only, no OCR needed).

Text stamped into a fine checkerboard or stripe pattern defeats OCR outright:
the binarization step sees maximal edges everywhere and never finds the
glyphs, which is exactly why the pattern gets used as camouflage. The pattern
itself is detectable, though. A camouflage patch is three things at once that
almost nothing legitimate is: (1) maximal contrast inside a small block, (2)
a palette of essentially two values with both well represented, and (3)
periodic, repeating exactly under a small pixel shift in both axes. Real
text is two-tone and high-contrast but aperiodic; photos and noise are not
two-tone; gradients and flat fills have no contrast; error-diffusion dither
is two-tone but aperiodic. An ordered (Bayer-style) dither patch is the one
honest collision, and a screenshot region carrying one deserves the same
second look.

Like the other shape checks this never reads any text; it flags the region
so a human (or an OCR pass on a cleaned copy) looks at it. Severity stays
MEDIUM for the same reason as FW-002: shape alone recovers no instruction.
"""

from __future__ import annotations

from PIL import ImageChops

from .. import grid
from ..finding import Finding, Region, Severity
from .tiny_text import _high_detail_blocks

RULE_ID = "FW-006"

BLOCK = 16
MIN_STDDEV = 60  # cheap C-speed pre-filter; a balanced two-tone block with
# MIN_CONTRAST between its tones has a standard deviation far above this.
MIN_CONTRAST = 150  # the two tones must sit far apart, out of 255
MAX_DISTINCT_VALUES = 4  # two tones plus a little edge bleed
MIN_MINOR_FRACTION = 0.28  # both tones carry real weight - rules out sparse
# ink on a plain field, which is just text, not camouflage
PERIODS = (2, 4, 6, 8)  # pixel shifts tested for self-similarity
PERIODIC_MATCH_FRACTION = 0.9  # how much of the block must repeat under the shift
PERIODIC_TOLERANCE = 16  # per-pixel value slack when comparing shifted copies
MIN_REGION_BLOCKS = 8
MIN_REGION_DIM = 32  # px; a camouflage patch is an area, not a line - keeps
# single-row repeats like table rules and box-drawing borders out


def _is_periodic_two_tone(crop) -> bool:
    lo, hi = crop.getextrema()
    if hi - lo < MIN_CONTRAST:
        return False
    colors = crop.getcolors(MAX_DISTINCT_VALUES)
    if colors is None:  # more distinct values than a two-tone palette allows
        return False
    counts = sorted((n for n, _ in colors), reverse=True)
    pixels = crop.width * crop.height
    if len(counts) < 2 or counts[1] / pixels < MIN_MINOR_FRACTION:
        return False
    for period in PERIODS:
        matches = 0
        for dx, dy in ((period, 0), (0, period)):
            shifted = ImageChops.offset(crop, dx, dy)
            diff = ImageChops.difference(crop, shifted)
            close = sum(1 for v in diff.tobytes() if v < PERIODIC_TOLERANCE)
            if close / pixels >= PERIODIC_MATCH_FRACTION:
                matches += 1
        if matches == 2:
            return True
    return False


def find(gray_image) -> list:
    width, height = gray_image.size
    cols, rows = grid.block_grid(width, height, BLOCK)
    # C-speed variance pre-pass so the per-block Python work below only ever
    # touches blocks that could possibly qualify.
    candidates = _high_detail_blocks(gray_image, BLOCK, cols, rows, MIN_STDDEV)

    flagged = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            if not candidates[r][c]:
                continue
            left, top, right, bottom = grid.block_box(c, r, BLOCK, width, height)
            if right - left < BLOCK or bottom - top < BLOCK:
                continue  # partial edge blocks distort the periodicity test
            if _is_periodic_two_tone(gray_image.crop((left, top, right, bottom))):
                flagged[r][c] = True

    findings = []
    for left, top, w, h, n_blocks in grid.group_flagged(flagged, cols, rows, BLOCK, width, height):
        if n_blocks < MIN_REGION_BLOCKS or w < MIN_REGION_DIM or h < MIN_REGION_DIM:
            continue
        findings.append(
            Finding(
                rule_id=RULE_ID,
                layer="hifreq-camouflage",
                severity=Severity.MEDIUM,
                title="High-frequency two-tone pattern region",
                detail=(
                    f"A {w}x{h}px region is a periodic, maximal-contrast two-tone "
                    f"pattern (a fine checkerboard or stripe). Patterns like this "
                    f"defeat OCR binarization, which makes them a known way to "
                    f"camouflage text from a scanner while a vision model still "
                    f"reads it. An ordered-dither image region looks the same and "
                    f"will also trip this."
                ),
                region=Region(left, top, w, h),
                remediation="Look at this region directly, or re-render the screenshot without the patterned area, before letting an agent read it.",
            )
        )
    return findings
