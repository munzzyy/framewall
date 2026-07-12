"""Tests that need a real tesseract binary: the OCR wrapper itself, and the
injection-text layer that depends on it. Skipped cleanly wherever tesseract
isn't installed - see tests/conftest.py::requires_tesseract. Run
`tesseract --version` to check whether this machine will run them.
"""

from __future__ import annotations

import subprocess

import pytest

from framewall import ocr as ocr_mod
from framewall.checks import injection_text
from tests._images import clean_screenshot, fake_system_overlay, low_contrast_injection
from tests.conftest import requires_tesseract


@requires_tesseract
def test_tesseract_path_is_found():
    assert ocr_mod.tesseract_path() is not None


@requires_tesseract
def test_ocr_image_reads_plain_text():
    img = clean_screenshot()
    words, lines = ocr_mod.ocr_image(img)
    joined = " ".join(w.text for w in words).lower()
    assert "welcome" in joined
    assert lines


@requires_tesseract
def test_ocr_image_returns_line_boxes_with_real_dimensions():
    img = clean_screenshot()
    _words, lines = ocr_mod.ocr_image(img)
    assert all(ln.height > 0 and ln.width > 0 for ln in lines)


@requires_tesseract
def test_ocr_region_recovers_low_contrast_text():
    img = low_contrast_injection().convert("RGB")
    # The text was drawn at (280, 400); OCR a generous box around it after a
    # local contrast boost.
    words = ocr_mod.ocr_region(img, (260, 385, 900, 435))
    joined = " ".join(w.text for w in words).lower()
    assert "ignore" in joined
    assert "instructions" in joined


@requires_tesseract
def test_ocr_region_empty_box_returns_nothing():
    img = clean_screenshot().convert("RGB")
    assert ocr_mod.ocr_region(img, (10, 10, 10, 10)) == []


@requires_tesseract
def test_ocr_image_without_tesseract_on_path_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: None)
    words, lines = ocr_mod.ocr_image(clean_screenshot())
    assert words == []
    assert lines == []


@requires_tesseract
def test_ocr_image_survives_a_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1)

    monkeypatch.setattr(ocr_mod.subprocess, "run", fake_run)
    words, lines = ocr_mod.ocr_image(clean_screenshot())
    assert words == []
    assert lines == []


@requires_tesseract
def test_parse_tsv_handles_empty_output():
    words, lines = ocr_mod._parse_tsv("")
    assert words == []
    assert lines == []


@requires_tesseract
def test_parse_tsv_handles_header_only():
    words, lines = ocr_mod._parse_tsv("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
    assert words == []
    assert lines == []


@requires_tesseract
def test_parse_tsv_ignores_malformed_rows():
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    bad = "5\t1\t1\t1\t1\t1\tnotanumber\t0\t10\t10\t99\thello"
    words, _lines = ocr_mod._parse_tsv(header + "\n" + bad)
    assert words == []


# --- the injection-text layer end to end -------------------------------------


@requires_tesseract
def test_injection_text_finds_plainly_visible_directive():
    img = fake_system_overlay()
    findings, words, lines = injection_text.find(img)
    assert findings
    assert all(f.rule_id == "FW-001" for f in findings)
    assert words


@requires_tesseract
def test_injection_text_recovers_hidden_low_contrast_directive():
    from framewall.checks import contrast

    img = low_contrast_injection().convert("RGB")
    gray = img.convert("L")
    regions = [f.region for f in contrast.find(gray) if f.region]
    assert regions, "the low-contrast layer should have flagged something to feed OCR"
    findings, _words, _lines = injection_text.find(img, low_contrast_regions=regions)
    assert findings
    titles = {f.title for f in findings}
    assert "Instruction-override phrasing" in titles


@requires_tesseract
def test_injection_text_clean_image_has_no_findings():
    img = clean_screenshot()
    findings, _words, _lines = injection_text.find(img)
    assert findings == []


@requires_tesseract
def test_injection_text_finding_has_a_located_region():
    img = fake_system_overlay()
    findings, _words, _lines = injection_text.find(img)
    assert findings
    located = [f for f in findings if f.region is not None]
    assert located, "expected at least one finding to be located to a word box"
