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
