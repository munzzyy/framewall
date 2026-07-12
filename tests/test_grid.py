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
