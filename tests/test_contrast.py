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


def test_large_hidden_block_is_high_severity():
    gray = low_contrast_paragraph().convert("L")
    findings = contrast.find(gray)
    assert findings
    assert any(f.severity == Severity.HIGH for f in findings)


def test_delta_near_default_max_contrast_is_still_caught():
    gray = low_contrast_injection(delta=28).convert("L")
    assert contrast.find(gray)
