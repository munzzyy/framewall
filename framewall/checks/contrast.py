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
MIN_REGION_BLOCKS = 6  # textured blocks (detail across and down) in one run; a straight rule has none
MIN_REGION_WIDTH = BLOCK * 3  # a single-column seam between two flat UI panels
# is also "structured but low contrast" - requiring some width rules out a
# panel-edge false positive while still catching a word's worth of text.


def find(gray_image) -> list:
    width, height = gray_image.size
    stats = grid.block_stats(gray_image, BLOCK, extrema=True)
    cols, rows = stats.cols, stats.rows
    hits = [
        i for i, (lo, hi) in enumerate(zip(stats.lo, stats.hi))
        if 0 < hi - lo <= MAX_LOCAL_CONTRAST and stats.stddev(i) >= MIN_STDDEV
    ]
    if not hits:
        return []
    across, down = grid.axis_detail(gray_image, BLOCK)
    flagged = [[False] * cols for _ in range(rows)]
    textured = [[False] * cols for _ in range(rows)]
    for i in hits:
        flagged[i // cols][i % cols] = True
        textured[i // cols][i % cols] = bool(across[i] and down[i])

    findings = []
    for cells in grid.group_cells(flagged, cols, rows):
        if not _has_cluster(cells, textured, MIN_REGION_BLOCKS):
            continue
        left, top, w, h = grid.cells_box(cells, BLOCK, width, height)
        if w < MIN_REGION_WIDTH:
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


def _has_cluster(cells, textured, size: int) -> bool:
    """Whether a 4-connected run of textured blocks in this region reaches
    `size`. Textured blocks are flagged ones too, so a run never leaves the
    region it starts in."""
    rows, cols = len(textured), len(textured[0])
    seen = set()
    for start in cells:
        if start in seen or not textured[start[0]][start[1]]:
            continue
        seen.add(start)
        stack = [start]
        count = 0
        while stack:
            r, c = stack.pop()
            count += 1
            if count >= size:
                return True
            for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= nr < rows and 0 <= nc < cols and textured[nr][nc] and (nr, nc) not in seen:
                    seen.add((nr, nc))
                    stack.append((nr, nc))
    return False
