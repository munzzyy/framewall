"""The block-grid helper is shared by every Pillow-only heuristic, so it gets
its own direct tests independent of any image."""

from __future__ import annotations

from framewall import grid


def test_block_grid_covers_the_whole_image():
    cols, rows = grid.block_grid(100, 50, 10)
    assert cols == 10
    assert rows == 5


def test_block_grid_rounds_up_for_partial_blocks():
    cols, rows = grid.block_grid(101, 41, 10)
    assert cols == 11
    assert rows == 5


def test_block_grid_minimum_one():
    cols, rows = grid.block_grid(3, 3, 10)
    assert (cols, rows) == (1, 1)


def test_block_box_clips_to_image_bounds():
    box = grid.block_box(9, 4, 10, 95, 45)
    assert box == (90, 40, 95, 45)


def test_group_flagged_no_flags_returns_empty():
    flagged = [[False, False], [False, False]]
    assert grid.group_flagged(flagged, 2, 2, 10, 20, 20) == []


def test_group_flagged_single_block():
    flagged = [[True, False], [False, False]]
    regions = grid.group_flagged(flagged, 2, 2, 10, 20, 20)
    assert regions == [(0, 0, 10, 10, 1)]


def test_group_flagged_merges_adjacent_blocks():
    flagged = [[True, True], [False, False]]
    regions = grid.group_flagged(flagged, 2, 2, 10, 20, 20)
    assert len(regions) == 1
    left, top, w, h, n = regions[0]
    assert (left, top, w, h, n) == (0, 0, 20, 10, 2)


def test_group_flagged_keeps_diagonal_blocks_separate():
    # Diagonal-only adjacency shouldn't merge - group_flagged is 4-connected.
    flagged = [[True, False], [False, True]]
    regions = grid.group_flagged(flagged, 2, 2, 10, 20, 20)
    assert len(regions) == 2


def test_group_flagged_two_separate_regions():
    flagged = [
        [True, True, False, False],
        [False, False, False, True],
    ]
    regions = grid.group_flagged(flagged, 4, 2, 5, 20, 10)
    assert len(regions) == 2
    sizes = sorted(r[4] for r in regions)
    assert sizes == [1, 2]


def _reference_axis_detail(gray, block):
    width, height = gray.size
    cols, rows = grid.block_grid(width, height, block)
    across, down = [], []
    for r in range(rows):
        for c in range(cols):
            crop = gray.crop(grid.block_box(c, r, block, width, height))
            px = crop.load()
            w, h = crop.size
            across.append(any(px[x, y] != px[x + 1, y] for y in range(h) for x in range(w - 1)))
            down.append(any(px[x, y] != px[x, y + 1] for y in range(h - 1) for x in range(w)))
    return across, down


def test_axis_detail_matches_a_per_block_reference():
    from tests._images import parity_set

    for name, gray in parity_set():
        across, down = grid.axis_detail(gray, 8)
        want_across, want_down = _reference_axis_detail(gray, 8)
        assert [bool(v) for v in across] == want_across, name
        assert [bool(v) for v in down] == want_down, name


def test_axis_detail_sees_lines_on_one_axis_only():
    from PIL import Image, ImageDraw

    img = Image.new("L", (32, 32), 200)
    ImageDraw.Draw(img).line([(0, 3), (31, 3)], fill=190)
    ImageDraw.Draw(img).line([(19, 16), (19, 31)], fill=190)
    across, down = grid.axis_detail(img, 8)
    assert not any(across[0:4]) and all(down[0:4])
    assert across[2 * 4 + 2] and not down[2 * 4 + 2]


def test_group_cells_and_cells_box_agree_with_group_flagged():
    flagged = [
        [True, True, False, False],
        [False, True, False, True],
    ]
    groups = grid.group_cells(flagged, 4, 2)
    assert sorted(len(g) for g in groups) == [1, 3]
    boxes = [(*grid.cells_box(g, 5, 20, 10), len(g)) for g in groups]
    assert boxes == grid.group_flagged(flagged, 4, 2, 5, 20, 10)
