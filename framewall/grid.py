"""Shared block-grid helpers used by the Pillow-only heuristics: split an
image into fixed-size blocks, let a caller flag some of them by whatever
predicate it likes, then group adjacent flagged blocks into bounding boxes.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageStat


def block_grid(width: int, height: int, block: int):
    cols = max(1, -(-width // block))  # ceil division
    rows = max(1, -(-height // block))
    return cols, rows


def block_box(col: int, row: int, block: int, width: int, height: int):
    left = col * block
    top = row * block
    right = min(left + block, width)
    bottom = min(top + block, height)
    return left, top, right, bottom


def group_cells(flagged, cols: int, rows: int):
    """4-connected flood fill over a cols x rows boolean grid (flagged[row][col]).

    Returns one list of (row, col) cells per connected group of flagged
    blocks, in row-major order of each group's first cell.
    """
    seen = [[False] * cols for _ in range(rows)]
    groups = []
    for r0 in range(rows):
        for c0 in range(cols):
            if not flagged[r0][c0] or seen[r0][c0]:
                continue
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
                        and flagged[nr][nc]
                        and not seen[nr][nc]
                    ):
                        seen[nr][nc] = True
                        stack.append((nr, nc))
            groups.append(cells)
    return groups


def cells_box(cells, block: int, width: int, height: int):
    """Pixel bounding box (left, top, w, h) of a group of (row, col) cells."""
    rows_hit = [cell[0] for cell in cells]
    cols_hit = [cell[1] for cell in cells]
    left, top, _, _ = block_box(min(cols_hit), min(rows_hit), block, width, height)
    _, _, right, bottom = block_box(max(cols_hit), max(rows_hit), block, width, height)
    return left, top, right - left, bottom - top


def group_flagged(flagged, cols: int, rows: int, block: int, width: int, height: int):
    """Returns a list of (left, top, w, h, n_blocks) pixel bounding boxes, one
    per 4-connected group of flagged blocks (see group_cells).
    """
    return [
        (*cells_box(cells, block, width, height), len(cells))
        for cells in group_cells(flagged, cols, rows)
    ]


@dataclass
class BlockStats:
    """Per-block pixel statistics over the cols x rows grid, row-major."""

    cols: int
    rows: int
    count: list
    total: list  # sum of pixel values
    total_sq: list  # sum of squared pixel values
    lo: list  # min value; empty unless extrema were asked for
    hi: list

    def mean(self, i: int) -> float:
        return self.total[i] / self.count[i]

    def stddev(self, i: int) -> float:
        # ImageStat's own formula, so a block clears a threshold here exactly
        # when an ImageStat.Stat of its crop would.
        n = self.count[i]
        return math.sqrt((self.total_sq[i] - self.total[i] ** 2.0 / n) / n)


def block_stats(gray_image, block: int, extrema: bool = False) -> BlockStats:
    """BlockStats for an L image, the same numbers a crop plus ImageStat per
    block gives, without the per-block crop. That loop cost 44 s on a 40 MP
    image. Here whole blocks go through Pillow's C core in a few full-image
    passes: reduce() averages each block, and pixel values scaled by the
    block area first turn that average into the exact integer sum. Extrema
    come from max/min pooling over shifted copies. Only the partial blocks
    on the right and bottom edges are cropped one at a time."""
    width, height = gray_image.size
    cols, rows = block_grid(width, height, block)
    full_cols, full_rows = width // block, height // block
    size = cols * rows
    area = block * block
    count = array.array("q", [0]) * size
    total = array.array("q", [0]) * size
    total_sq = array.array("q", [0]) * size
    lo = array.array("B", [0]) * size if extrema else array.array("B")
    hi = array.array("B", [0]) * size if extrema else array.array("B")

    if full_cols and full_rows:
        whole = gray_image.crop((0, 0, full_cols * block, full_rows * block))
        sums = _block_sums(whole, block, [v * area for v in range(256)])
        sums_sq = _block_sums(whole, block, [v * v * area for v in range(256)])
        if extrema:
            highs = _block_pool(whole, block, ImageChops.lighter)
            lows = _block_pool(whole, block, ImageChops.darker)
        for r in range(full_rows):
            src = slice(r * full_cols, (r + 1) * full_cols)
            dst = slice(r * cols, r * cols + full_cols)
            count[dst] = array.array("q", [area]) * full_cols
            total[dst] = sums[src]
            total_sq[dst] = sums_sq[src]
            if extrema:
                hi[dst] = highs[src]
                lo[dst] = lows[src]

    edge = [(c, r) for r in range(rows) for c in range(full_cols, cols)]
    edge += [(c, r) for r in range(full_rows, rows) for c in range(full_cols)]
    for c, r in edge:
        crop = gray_image.crop(block_box(c, r, block, width, height))
        stat = ImageStat.Stat(crop)
        i = r * cols + c
        count[i], total[i], total_sq[i] = stat.count[0], int(stat.sum[0]), int(stat.sum2[0])
        if extrema:
            lo[i], hi[i] = crop.getextrema()
    return BlockStats(cols, rows, count, total, total_sq, lo, hi)


def axis_detail(gray_image, block: int):
    """Per-block (across, down) flags, row-major over the block grid: nonzero
    when some pixel differs from its right-hand neighbour, or from the one
    below it, counting only pairs inside one block. A horizontal edge or rule
    has no detail across, a vertical one none down."""
    return (
        _any_per_block(_inner_changes(gray_image, block, across=True), block),
        _any_per_block(_inner_changes(gray_image, block, across=False), block),
    )


def _inner_changes(gray_image, block: int, across: bool):
    """255 where a pixel differs from the next one along the axis, 0 where it
    doesn't or where the next pixel is in another block or past the edge."""
    width, height = gray_image.size
    dx, dy = (1, 0) if across else (0, 1)
    nxt = gray_image.crop((dx, dy, width + dx, height + dy))
    changed = ImageChops.difference(gray_image, nxt).point([0] + [255] * 255)
    length = width if across else height
    keep = bytes(0 if (i % block == block - 1 or i == length - 1) else 255 for i in range(length))
    line = (width, 1) if across else (1, height)
    mask = Image.frombytes("L", line, keep).resize((width, height), Image.NEAREST)
    return ImageChops.darker(changed, mask)


def _any_per_block(changes, block: int) -> bytearray:
    """Nonzero per block where `changes` has any 255. reduce() rounds the
    block's mean, and one 255 in 64 pixels still rounds to 4."""
    width, height = changes.size
    cols, rows = block_grid(width, height, block)
    full_cols, full_rows = width // block, height // block
    out = bytearray(cols * rows)
    if full_cols and full_rows:
        whole = changes.crop((0, 0, full_cols * block, full_rows * block))
        means = whole.reduce(block).tobytes()
        for r in range(full_rows):
            out[r * cols:r * cols + full_cols] = means[r * full_cols:(r + 1) * full_cols]
    edge = [(c, r) for r in range(rows) for c in range(full_cols, cols)]
    edge += [(c, r) for r in range(full_rows, rows) for c in range(full_cols)]
    for c, r in edge:
        out[r * cols + c] = changes.crop(block_box(c, r, block, width, height)).getextrema()[1]
    return out


def _block_sums(whole, block: int, table) -> array.array:
    """Exact per-block sums of table[value]. Each table entry is already
    multiplied by the block area, so reduce()'s rounded average is the sum."""
    reduced = whole.point(table, "I").reduce(block)
    out = array.array("i")
    out.frombytes(reduced.tobytes())
    return array.array("q", out)


def _block_pool(whole, block: int, pick) -> array.array:
    """Max (pick=lighter) or min (darker) of each block. Each pass folds in a
    copy shifted by up to the span covered so far, so after a few passes a
    pixel holds the max over the block that starts at it. The shifted copy
    is a crop that runs past the edge; the padding it brings in only ever
    reaches pixels that don't start a block."""
    pooled = whole
    width, height = whole.size
    for dx, dy in ((1, 0), (0, 1)):
        span = 1
        while span < block:
            shift = min(span, block - span)
            moved = pooled.crop((shift * dx, shift * dy, width + shift * dx, height + shift * dy))
            pooled = pick(pooled, moved)
            span += shift
    data = pooled.tobytes()
    width = whole.width
    out = array.array("B")
    for r in range(whole.height // block):
        start = r * block * width
        out.frombytes(data[start:start + width:block])
    return out
