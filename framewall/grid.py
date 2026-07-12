"""Shared block-grid helpers used by the Pillow-only heuristics: split an
image into fixed-size blocks, let a caller flag some of them by whatever
predicate it likes, then group adjacent flagged blocks into bounding boxes.
"""

from __future__ import annotations


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


def group_flagged(flagged, cols: int, rows: int, block: int, width: int, height: int):
    """4-connected flood fill over a cols x rows boolean grid (flagged[row][col]).

    Returns a list of (left, top, w, h, n_blocks) pixel bounding boxes, one
    per connected group of flagged blocks.
    """
    seen = [[False] * cols for _ in range(rows)]
    regions = []
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
            rows_hit = [cell[0] for cell in cells]
            cols_hit = [cell[1] for cell in cells]
            left, top, _, _ = block_box(min(cols_hit), min(rows_hit), block, width, height)
            _, _, right, bottom = block_box(max(cols_hit), max(rows_hit), block, width, height)
            regions.append((left, top, right - left, bottom - top, len(cells)))
    return regions
