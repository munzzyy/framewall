"""Fake system/overlay UI detector (FW-004). Pillow only, no tesseract."""

from __future__ import annotations

from framewall.checks import overlay
from tests._images import clean_screenshot, fake_system_overlay, solid_color


def test_clean_screenshot_has_no_overlay_findings():
    gray = clean_screenshot().convert("L")
    assert overlay.find(gray) == []


def test_flat_color_image_has_no_overlay_findings():
    gray = solid_color(400, 400).convert("L")
    assert overlay.find(gray) == []


def test_fake_overlay_box_is_flagged():
    gray = fake_system_overlay().convert("L")
    findings = overlay.find(gray)
    assert findings
    assert all(f.rule_id == "FW-004" for f in findings)


def test_full_width_header_bar_is_not_flagged():
    """A page-spanning top bar with a title is ordinary app chrome, not an
    injected message box - it shouldn't look the same as one."""
    from PIL import ImageDraw, ImageFont

    img = solid_color(1000, 700, (245, 245, 248))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1000, 60], fill=(20, 20, 30))
    d.text((20, 18), "My Application Header Title", fill="white", font=ImageFont.load_default(size=20))
    gray = img.convert("L")
    assert overlay.find(gray) == []


def test_two_adjacent_flat_panels_of_different_color_stay_separate():
    """A light background panel directly touching a differently-colored flat
    panel (a very common layout) must not merge into one giant region just
    because each panel is independently uniform."""
    img = solid_color(400, 400, (245, 245, 248))
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 150, 400], fill=(20, 20, 25))
    gray = img.convert("L")
    # Neither panel alone is box-shaped-with-text, so nothing should fire.
    assert overlay.find(gray) == []


def test_overlay_region_matches_drawn_box():
    gray = fake_system_overlay().convert("L")
    findings = overlay.find(gray)
    region = findings[0].region
    assert 240 <= region.left <= 280
    assert 420 <= region.top <= 460



def _reference_fill_regions(gray_image):
    """_fill_regions() as it was before it moved to grid.block_stats: one
    crop and ImageStat per block, then the same seed-anchored flood fill."""
    from PIL import ImageStat

    from framewall import grid

    block = overlay.FLAT_BLOCK
    width, height = gray_image.size
    cols, rows = grid.block_grid(width, height, block)
    mean = [[0.0] * cols for _ in range(rows)]
    flat = [[False] * cols for _ in range(rows)]
    detailed = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            stat = ImageStat.Stat(gray_image.crop(grid.block_box(c, r, block, width, height)))
            stddev = stat.stddev[0]
            mean[r][c] = stat.mean[0]
            if stddev <= overlay.FLAT_STDDEV_MAX:
                flat[r][c] = True
            elif stddev >= overlay.DETAIL_STDDEV_MIN:
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
                        and abs(mean[nr][nc] - seed_mean) <= overlay.FILL_TOLERANCE
                    ):
                        seen[nr][nc] = True
                        stack.append((nr, nc))
            rows_hit = [cell[0] for cell in cells]
            cols_hit = [cell[1] for cell in cells]
            left, top, _, _ = grid.block_box(min(cols_hit), min(rows_hit), block, width, height)
            _, _, right, bottom = grid.block_box(max(cols_hit), max(rows_hit), block, width, height)
            regions.append((left, top, right - left, bottom - top))
    return regions, detailed, cols, rows


def test_fill_regions_match_the_per_block_reference_exactly():
    from tests._images import parity_set

    for name, gray in parity_set():
        assert overlay._fill_regions(gray) == _reference_fill_regions(gray), name


def test_find_matches_the_per_block_reference_exactly(monkeypatch):
    from tests._images import parity_set

    for name, gray in parity_set():
        got = overlay.find(gray)
        with monkeypatch.context() as m:
            m.setattr(overlay, "_fill_regions", _reference_fill_regions)
            want = overlay.find(gray)
        assert got == want, name
