"""Fake system/overlay UI (Pillow only, no OCR needed).

A heuristic guess at a solid-fill box with contrasting text inside it,
positioned near an edge or centered - the shape a fake "System message" or
"AI notice" overlay takes when someone paints one onto a screenshot to talk
to the agent instead of the human looking at it.

This is shape-only and honestly heuristic: it has no idea what the box says
and will happily flag a real toast notification, cookie banner, or tooltip
that happens to be the same shape. Treat a hit here as "worth a second
look", not a verdict on its own - dense real UI is exactly what trips it.
"""

from __future__ import annotations

from PIL import ImageStat

from .. import grid
from ..finding import Finding, Region, Severity

RULE_ID = "FW-004"

FLAT_BLOCK = 20
FLAT_STDDEV_MAX = 10  # near-solid fill
FILL_TOLERANCE = 20  # how close a neighbor's mean value must stay to the
# seed block's to count as "the same fill" - without this, two independently
# flat but differently-colored panels (a light background next to a dark
# sidebar, say) merge into one giant region just because each is internally
# uniform and they happen to sit grid-adjacent.
DETAIL_STDDEV_MIN = 22  # clearly higher-detail than the flat fill (text-like)
MIN_AREA_FRACTION = 0.015
MAX_AREA_FRACTION = 0.55
MIN_TEXT_FRACTION = 0.03  # some of the box must look like it contains text
MAX_TEXT_FRACTION = 0.55
EDGE_BAND = 0.15  # within this fraction of width/height counts as "near an edge"
CENTER_BAND = 0.2  # within this fraction of center counts as "centered"
FULL_BLEED_FRACTION = 0.85  # a box spanning nearly the whole width or height reads
# as page chrome (a nav bar, a toolbar, a status bar) rather than an injected
# message box, which is almost always inset with visible margin on the sides.


def _fill_regions(gray_image):
    """Group adjacent same-colored flat blocks. Same-colored, not just each
    independently flat: a seed-anchored flood fill only grows into a
    neighbor if that neighbor's own mean value is close to the seed's,
    so it tracks one fill color rather than sweeping across a whole
    multi-panel UI."""
    width, height = gray_image.size
    cols, rows = grid.block_grid(width, height, FLAT_BLOCK)
    mean = [[0.0] * cols for _ in range(rows)]
    flat = [[False] * cols for _ in range(rows)]
    detailed = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            box = grid.block_box(c, r, FLAT_BLOCK, width, height)
            stat = ImageStat.Stat(gray_image.crop(box))
            stddev = stat.stddev[0]
            mean[r][c] = stat.mean[0]
            if stddev <= FLAT_STDDEV_MAX:
                flat[r][c] = True
            elif stddev >= DETAIL_STDDEV_MIN:
                detailed[r][c] = True

    seen = [[False] * cols for _ in range(rows)]
    regions = []
    for r0 in range(rows):
        for c0 in range(cols):
            if not flat[r0][c0] or seen[r0][c0]:
                continue
            seed_mean = mean[r0][c0]
            stack = [(r0, c0)]
            seen[r0][c0] = True
            cells = []
            while stack:
                r, c = stack.pop()
                cells.append((r, c))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = r + dr, c + dc
                    if (
                        0 <= nr < rows
                        and 0 <= nc < cols
                        and flat[nr][nc]
                        and not seen[nr][nc]
                        and abs(mean[nr][nc] - seed_mean) <= FILL_TOLERANCE
                    ):
                        seen[nr][nc] = True
                        stack.append((nr, nc))
            rows_hit = [cell[0] for cell in cells]
            cols_hit = [cell[1] for cell in cells]
            left, top, _, _ = grid.block_box(min(cols_hit), min(rows_hit), FLAT_BLOCK, width, height)
            _, _, right, bottom = grid.block_box(max(cols_hit), max(rows_hit), FLAT_BLOCK, width, height)
            regions.append((left, top, right - left, bottom - top))
    return regions, detailed, cols, rows


def find(gray_image) -> list:
    width, height = gray_image.size
    regions, detailed, cols, rows = _fill_regions(gray_image)

    findings = []
    for left, top, w, h in regions:
        area_fraction = (w * h) / (width * height)
        if not (MIN_AREA_FRACTION <= area_fraction <= MAX_AREA_FRACTION):
            continue
        if w >= width * FULL_BLEED_FRACTION or h >= height * FULL_BLEED_FRACTION:
            continue

        c0, r0 = left // FLAT_BLOCK, top // FLAT_BLOCK
        c1 = min(cols, -(-(left + w) // FLAT_BLOCK))
        r1 = min(rows, -(-(top + h) // FLAT_BLOCK))
        footprint = max(1, (r1 - r0) * (c1 - c0))
        inner_detail = sum(1 for r in range(r0, r1) for c in range(c0, c1) if detailed[r][c])
        text_fraction = inner_detail / footprint
        if not (MIN_TEXT_FRACTION <= text_fraction <= MAX_TEXT_FRACTION):
            continue

        near_edge = (
            top <= height * EDGE_BAND
            or (top + h) >= height * (1 - EDGE_BAND)
            or left <= width * EDGE_BAND
            or (left + w) >= width * (1 - EDGE_BAND)
        )
        centered = (
            abs((left + w / 2) - width / 2) <= width * CENTER_BAND
            and abs((top + h / 2) - height / 2) <= height * CENTER_BAND
        )
        if not (near_edge or centered):
            continue

        where = "near an edge" if near_edge else "centered"
        findings.append(
            Finding(
                rule_id=RULE_ID,
                layer="fake-overlay",
                severity=Severity.MEDIUM,
                title="Solid-fill box with embedded text, shaped like a system overlay",
                detail=(
                    f"A {w}x{h}px near-solid-fill box ({where}) contains patches of "
                    f"higher-detail content consistent with text - the shape a fake "
                    f"'system message' or 'AI notice' overlay takes. Heuristic only: "
                    f"real UI (toasts, banners, tooltips, cookie notices) has this "
                    f"same shape and will trip this check too."
                ),
                region=Region(left, top, w, h),
                remediation="Look at this region directly. If the text addresses an agent rather than a human, treat the image as untrusted.",
            )
        )
    return findings
