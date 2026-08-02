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


def test_ocr_image_raises_on_timeout(monkeypatch):
    # A hung tesseract must surface, not be swallowed into an empty "no text"
    # result that a caller would read as a clean image. Self-contained: the
    # binary is faked, so this runs even where tesseract can't read.
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1)

    monkeypatch.setattr(ocr_mod.subprocess, "run", fake_run)
    with pytest.raises(ocr_mod.OcrTimeout):
        ocr_mod.ocr_image(clean_screenshot())


def test_ocr_region_raises_timeout(monkeypatch):
    # A region pass timing out must surface to the caller, who notes the
    # unread region and carries on - swallowing it here would let a partial
    # scan pass itself off as a completed one.
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")

    def boom(*args, **kwargs):
        raise ocr_mod.OcrTimeout("timed out")

    monkeypatch.setattr(ocr_mod, "ocr_image", boom)
    with pytest.raises(ocr_mod.OcrTimeout):
        ocr_mod.ocr_region(clean_screenshot(), (0, 0, 100, 40))


def test_ocr_region_caps_the_upscale_buffer(monkeypatch):
    # A large flagged region must not be blown up past the buffer cap: the
    # image handed to the OCR pass stays within MAX_UPSCALED_PIXELS.
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")
    seen = {}

    def capture(image, timeout=ocr_mod.DEFAULT_TIMEOUT, lang=None):
        seen["pixels"] = image.width * image.height
        return [], []

    monkeypatch.setattr(ocr_mod, "ocr_image", capture)
    big = clean_screenshot().resize((3000, 2000))
    ocr_mod.ocr_region(big, (0, 0, 3000, 2000), upscale=3)
    assert seen["pixels"] <= ocr_mod.MAX_UPSCALED_PIXELS


def test_injection_text_preserves_line_anchors(monkeypatch):
    # A "system:" header on its own line (not the first) must still match the
    # ^-anchored fake-system-role pattern. That only works if the scanned text
    # keeps tesseract's line breaks instead of collapsing every word onto one
    # line. Synthetic OCR output, so this runs without a real tesseract.
    words = [
        ocr_mod.Word("Welcome", 0, 0, 60, 10, 90.0),
        ocr_mod.Word("System:", 0, 20, 60, 10, 90.0),
        ocr_mod.Word("do", 65, 20, 20, 10, 90.0),
        ocr_mod.Word("this", 90, 20, 25, 10, 90.0),
    ]
    lines = [
        ocr_mod.Line("Welcome", 0, 0, 60, 10),
        ocr_mod.Line("System: do this", 0, 20, 115, 10),
    ]
    monkeypatch.setattr(ocr_mod, "ocr_image", lambda *a, **k: (words, lines))
    findings, _w, _l = injection_text.find(object())
    assert any(f.title == "Fake system-role label" for f in findings)


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


def test_run_tsv_passes_lang_to_tesseract(monkeypatch):
    """--lang must become tesseract's own -l argument, placed among the
    options (after the outputbase, before the config name), and stay absent
    entirely when no language was chosen so tesseract's compiled-in default
    still applies."""
    seen = []

    class FakeProc:
        stdout = ""

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return FakeProc()

    monkeypatch.setattr(ocr_mod.subprocess, "run", fake_run)
    ocr_mod._run_tsv("/usr/bin/tesseract", "img.png", timeout=5, lang="eng+deu")
    ocr_mod._run_tsv("/usr/bin/tesseract", "img.png", timeout=5)
    with_lang, without_lang = seen
    i = with_lang.index("-l")
    assert with_lang[i + 1] == "eng+deu"
    assert i > with_lang.index("stdout")
    assert i < with_lang.index("tsv")
    assert "-l" not in without_lang


def test_ocr_functional_probes_the_selected_language(monkeypatch):
    """The fail-loud probe must test the language the scan will actually
    use: a working eng install with a missing deu pack has to fail the probe
    for deu, not pass it on eng and then silently read nothing."""
    seen = []

    def fake_run_tsv(tess_bin, image_path, timeout, lang=None):
        seen.append(lang)
        return ""

    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_mod, "_run_tsv", fake_run_tsv)
    ocr_mod.ocr_functional.cache_clear()
    try:
        assert ocr_mod.ocr_functional("zzz-fake-lang") is False
        assert seen == ["zzz-fake-lang"]
    finally:
        ocr_mod.ocr_functional.cache_clear()


@requires_tesseract
def test_scan_names_the_missing_language_in_the_skip_reason(tmp_path):
    """Selecting a language whose data isn't installed must degrade loudly,
    with the reason naming the language, never scan as if OCR ran."""
    from framewall.scanner import scan_image

    p = tmp_path / "clean.png"
    clean_screenshot().save(p)
    result = scan_image(p, lang="zzz-no-such-lang")
    assert result.ocr_used is False
    assert "zzz-no-such-lang" in result.ocr_skipped_reason
    assert "did not run" in result.ocr_skipped_reason
