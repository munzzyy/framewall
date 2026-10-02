"""Low-contrast text detector (FW-002). Pillow only, no tesseract - these
tests run everywhere."""

from __future__ import annotations

from framewall.checks import contrast
from framewall.finding import Severity
from tests._images import clean_screenshot, low_contrast_injection, low_contrast_paragraph, solid_color


def test_clean_screenshot_has_no_low_contrast_regions():
    gray = clean_screenshot().convert("L")
    assert contrast.find(gray) == []


def test_flat_color_image_has_no_low_contrast_regions():
    gray = solid_color(300, 300, (250, 250, 250)).convert("L")
    assert contrast.find(gray) == []


def test_hidden_text_is_flagged():
    gray = low_contrast_injection().convert("L")
    findings = contrast.find(gray)
    assert findings, "expected the pale injected text to be flagged"
    assert all(f.rule_id == "FW-002" for f in findings)


def test_finding_region_covers_the_hidden_text():
    gray = low_contrast_injection().convert("L")
    findings = contrast.find(gray)
    region = findings[0].region
    assert region is not None
    # The text was drawn starting at (280, 400); the flagged region should
    # land in that neighborhood, not somewhere else in the image.
    assert 250 <= region.left <= 320
    assert 380 <= region.top <= 420


def test_a_thin_panel_seam_is_not_flagged():
    """Two flat panels that differ by a few shades (a very common, entirely
    benign UI pattern) shouldn't look like hidden text just because their
    shared edge is technically 'low contrast, non-zero variance'."""
    img = solid_color(400, 400, (245, 245, 248))
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 150, 400], fill=(235, 235, 240))
    gray = img.convert("L")
    assert contrast.find(gray) == []


def test_a_horizontal_panel_seam_is_not_flagged():
    """The same seam turned on its side: a header band a few shades off the
    page. MIN_REGION_WIDTH never covered this one."""
    img = solid_color(400, 400, (245, 245, 248))
    from PIL import ImageDraw

    ImageDraw.Draw(img).rectangle([0, 0, 400, 150], fill=(235, 235, 240))
    assert contrast.find(img.convert("L")) == []


def test_a_one_pixel_divider_is_not_flagged():
    img = solid_color(400, 400, (245, 245, 248))
    from PIL import ImageDraw

    ImageDraw.Draw(img).line([(0, 100), (400, 100)], fill=(225, 225, 230), width=1)
    assert contrast.find(img.convert("L")) == []


def test_a_dark_mode_button_border_is_not_flagged():
    from tests._images import dark_mode_button

    assert contrast.find(dark_mode_button().convert("L")) == []


def test_hidden_text_touching_a_divider_is_still_flagged():
    """A straight rule doesn't count toward a region, and it must not hide
    the text it touches either."""
    img = low_contrast_injection()
    from PIL import ImageDraw

    ImageDraw.Draw(img).line([(0, 424), (1000, 424)], fill=(225, 225, 225), width=1)
    findings = contrast.find(img.convert("L"))
    assert findings
    assert any(f.region.left <= 280 and f.region.top <= 400 for f in findings)


def test_small_hidden_region_is_medium_severity():
    gray = low_contrast_injection().convert("L")
    findings = contrast.find(gray)
    assert findings
    assert all(f.severity == Severity.MEDIUM for f in findings)


def test_large_hidden_block_is_never_high_severity():
    # A shape-only heuristic that never reads the region must not reach HIGH
    # (verdict: dangerous) on area alone - that would hard-block ordinary
    # low-contrast photos and screenshots. A hard DANGEROUS is reserved for the
    # checks that actually recover an injection string (FW-001, FW-005).
    gray = low_contrast_paragraph().convert("L")
    findings = contrast.find(gray)
    assert findings
    assert all(f.severity == Severity.MEDIUM for f in findings)


def test_delta_near_default_max_contrast_is_still_caught():
    gray = low_contrast_injection(delta=28).convert("L")
    assert contrast.find(gray)


def _reference_find(gray_image):
    """find() written the slow, obvious way: one crop per block for the
    extrema, the stddev and whether any pixel differs from its neighbour
    across or down, then one flood fill over the textured blocks."""
    from PIL import ImageStat

    from framewall import grid

    width, height = gray_image.size
    cols, rows = grid.block_grid(width, height, contrast.BLOCK)
    flagged = [[False] * cols for _ in range(rows)]
    textured = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            crop = gray_image.crop(grid.block_box(c, r, contrast.BLOCK, width, height))
            lo, hi = crop.getextrema()
            if hi - lo == 0:
                continue
            stddev = ImageStat.Stat(crop).stddev[0]
            if stddev >= contrast.MIN_STDDEV and hi - lo <= contrast.MAX_LOCAL_CONTRAST:
                flagged[r][c] = True
                px = crop.load()
                w, h = crop.size
                across = any(px[x, y] != px[x + 1, y] for y in range(h) for x in range(w - 1))
                down = any(px[x, y] != px[x, y + 1] for y in range(h - 1) for x in range(w))
                textured[r][c] = across and down
    runs = grid.group_cells(textured, cols, rows)
    big = {cell for run in runs if len(run) >= contrast.MIN_REGION_BLOCKS for cell in run}
    out = []
    for cells in grid.group_cells(flagged, cols, rows):
        left, top, w, h = grid.cells_box(cells, contrast.BLOCK, width, height)
        if big.intersection(cells) and w >= contrast.MIN_REGION_WIDTH:
            out.append((left, top, w, h))
    return out


def test_find_matches_the_per_block_reference_exactly():
    from tests._images import parity_set

    for name, gray in parity_set():
        got = [(f.region.left, f.region.top, f.region.width, f.region.height) for f in contrast.find(gray)]
        assert got == _reference_find(gray), name
