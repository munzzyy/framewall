"""Low-contrast hidden text (Pillow only, no OCR needed).

Splits the image into small blocks and flags ones that have real internal
structure (a non-trivial standard deviation - edges, strokes) but a narrow
value range (max minus min) - the fingerprint of text rendered a few shades
off its background so a human skims past it while a vision model still
reads it at full fidelity. This is a shape-only heuristic: it does not know
what the text says, only that something text-shaped is sitting at
suspiciously low contrast. The injection-text layer OCRs these regions after
a local contrast boost to try to read them.
"""

from __future__ import annotations

from .. import grid
from ..finding import Finding, Region, Severity

RULE_ID = "FW-002"

BLOCK = 8
MIN_STDDEV = 1.0  # some internal structure, not a flat noise floor
MAX_LOCAL_CONTRAST = 30  # max-min within the block, out of 255
MIN_REGION_BLOCKS = 6  # ignore stray single-block antialiasing noise
MIN_REGION_WIDTH = BLOCK * 3  # a single-column seam between two flat UI panels
# is also "structured but low contrast" - requiring some width rules out a
# panel-edge false positive while still catching a word's worth of text.


def find(gray_image) -> list:
    width, height = gray_image.size
    stats = grid.block_stats(gray_image, BLOCK, extrema=True)
    cols, rows = stats.cols, stats.rows
    flagged = [[False] * cols for _ in range(rows)]
    for i, (lo, hi) in enumerate(zip(stats.lo, stats.hi)):
        if 0 < hi - lo <= MAX_LOCAL_CONTRAST and stats.stddev(i) >= MIN_STDDEV:
            flagged[i // cols][i % cols] = True

    findings = []
    for left, top, w, h, n_blocks in grid.group_flagged(flagged, cols, rows, BLOCK, width, height):
        if n_blocks < MIN_REGION_BLOCKS or w < MIN_REGION_WIDTH:
            continue
        # This is a shape-only heuristic - it never reads the region, so it
        # can't tell hidden instructions from an ordinary low-contrast photo or
        # UI. Cap it at MEDIUM (verdict: suspicious). A hard DANGEROUS is
        # reserved for the checks that actually recover an injection string
        # (FW-001 re-OCRs these same regions; FW-005 reads metadata).
        findings.append(
            Finding(
                rule_id=RULE_ID,
                layer="low-contrast-text",
                severity=Severity.MEDIUM,
                title="Low-contrast text-shaped region",
                detail=(
                    f"A {w}x{h}px region has the texture of text (real internal "
                    f"structure) but a pixel value range of {MAX_LOCAL_CONTRAST} "
                    f"shades or less - the classic way to hide text from a human "
                    f"reader while a vision model still reads it in full."
                ),
                region=Region(left, top, w, h),
                remediation="Boost local contrast on this region (or re-scan with OCR) to see what it says.",
            )
        )
    return findings
