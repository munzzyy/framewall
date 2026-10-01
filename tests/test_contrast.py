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
    """The per-block crop loop find() used before it moved to
    grid.block_stats: one crop, getextrema and ImageStat per block."""
    from PIL import ImageStat

    from framewall import grid

    width, height = gray_image.size
    cols, rows = grid.block_grid(width, height, contrast.BLOCK)
    flagged = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            crop = gray_image.crop(grid.block_box(c, r, contrast.BLOCK, width, height))
            lo, hi = crop.getextrema()
            if hi - lo == 0:
                continue
            stddev = ImageStat.Stat(crop).stddev[0]
            if stddev >= contrast.MIN_STDDEV and hi - lo <= contrast.MAX_LOCAL_CONTRAST:
                flagged[r][c] = True
    return [
        (left, top, w, h)
        for left, top, w, h, n in grid.group_flagged(flagged, cols, rows, contrast.BLOCK, width, height)
        if n >= contrast.MIN_REGION_BLOCKS and w >= contrast.MIN_REGION_WIDTH
    ]


def test_find_matches_the_per_block_reference_exactly():
    from tests._images import parity_set

    for name, gray in parity_set():
        got = [(f.region.left, f.region.top, f.region.width, f.region.height) for f in contrast.find(gray)]
        assert got == _reference_find(gray), name
