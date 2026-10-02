"""The recovery transforms: residual amplification for near-background text,
skew detection + counter-rotation for off-axis text. The transforms are pure
Pillow, so most of this runs everywhere; only the tests that read the
recovered text back need tesseract."""

from __future__ import annotations


from framewall import imageio, recover
from framewall import ocr as ocr_mod
from framewall.checks import injection_text
from tests import _images
from tests.conftest import requires_tesseract


# --- skew detection (no OCR needed) ------------------------------------------


def test_detect_skew_finds_the_rotated_payload_angle():
    gray = imageio.safe_convert(_images.rotated_injection(angle=22), "L")
    angle = recover.detect_skew(gray)
    assert angle is not None
    # The sweep is in SKEW_STEP_DEGREES increments, so the detected angle
    # lands near -22 (counter-rotation), not exactly on it.
    assert -22 - recover.SKEW_STEP_DEGREES <= angle <= -22 + recover.SKEW_STEP_DEGREES


def test_detect_skew_is_none_on_upright_content():
    """An ordinary screenshot's profile decays symmetrically away from
    upright; treating that as a rotated payload would buy a useless OCR pass
    on every clean image. This is the regression test for the original
    acceptance rule, which compared rotated scores against the unrotated
    baseline - rotation pays an interpolation-and-expand tax the baseline
    doesn't, so real peaks were structurally suppressed while the fix must
    not overcorrect into flagging upright text."""
    gray = imageio.safe_convert(_images.clean_screenshot(), "L")
    assert recover.detect_skew(gray) is None


def test_detect_skew_is_none_on_a_blank_image():
    gray = imageio.safe_convert(_images.solid_color(400, 300), "L")
    assert recover.detect_skew(gray) is None


def test_deskewed_counter_rotates():
    gray = imageio.safe_convert(_images.rotated_injection(angle=22), "L")
    angle = recover.detect_skew(gray)
    out = recover.deskewed(gray, angle)
    # expand=True: the counter-rotated canvas grows, never crops.
    assert out.width >= gray.width and out.height >= gray.height


def test_looks_sideways_on_text_turned_a_quarter():
    gray = imageio.safe_convert(_images.sideways_injection(), "L")
    assert recover.looks_sideways(gray)
    turned_back = recover.quarter_turned(gray, 90)
    assert not recover.looks_sideways(turned_back)


def test_looks_sideways_is_false_on_ordinary_images():
    """The sideways pass costs up to two OCR passes, so every upright image
    the suite builds has to stay out of it."""
    for name, gray in _images.parity_set():
        if name.startswith("sideways"):
            continue
        assert not recover.looks_sideways(gray), name


def test_quarter_turned_is_exact():
    gray = imageio.safe_convert(_images.sideways_injection(), "L")
    upright = imageio.safe_convert(_images.upright_banner(), "L")
    assert recover.quarter_turned(gray, 270).tobytes() == upright.tobytes()
    assert recover.quarter_turned(recover.quarter_turned(gray, 90), 270).tobytes() == gray.tobytes()


# --- residual amplification (no OCR needed) -----------------------------------


def test_residual_amplifies_near_background_text():
    """One shade of contrast in, near-full contrast out: the residual image
    must separate ink from background far more than the source did."""
    gray = imageio.safe_convert(_images.white_on_white_injection(), "L")
    lo, hi = gray.getextrema()
    assert hi - lo <= 2  # the fixture really is imperceptible to start with
    residual = recover.residual_text(gray)
    lo, hi = residual.getextrema()
    # One shade in, RESIDUAL_GAIN shades out - enough separation for
    # tesseract's binarization, from text a human cannot see at all.
    assert hi - lo >= recover.RESIDUAL_GAIN * 0.9


# --- reading the recovered text back (needs tesseract) -------------------------


@requires_tesseract
def test_residual_pass_reads_white_on_white_injection():
    image = _images.white_on_white_injection()
    gray = imageio.safe_convert(image, "L")
    findings, _words, _lines = injection_text.find(image, gray=gray)
    assert findings, "the residual recovery pass should read one-shade-off text"
    assert all(f.rule_id == "FW-001" for f in findings)


@requires_tesseract
def test_deskew_pass_reads_rotated_injection():
    image = _images.rotated_injection()
    gray = imageio.safe_convert(image, "L")
    findings, _words, _lines = injection_text.find(image, gray=gray)
    assert findings, "the deskew recovery pass should read 22-degree text"


@requires_tesseract
def test_sideways_pass_reads_text_turned_a_quarter():
    image = _images.sideways_injection()
    findings, _words, _lines = injection_text.find(image)
    assert findings, "the sideways recovery pass should read quarter-turned text"
    assert all("turning the image" in f.detail for f in findings)


@requires_tesseract
def test_sideways_pass_does_not_run_on_a_clean_screenshot(monkeypatch):
    turned = []
    real = recover.quarter_turned
    monkeypatch.setattr(
        recover, "quarter_turned", lambda gray, degrees: turned.append(degrees) or real(gray, degrees)
    )
    findings, _words, _lines = injection_text.find(_images.clean_screenshot())
    assert findings == []
    assert turned == []


@requires_tesseract
def test_recovery_passes_do_not_run_when_the_primary_pass_matched(monkeypatch):
    """Recovery is a last swing, not a parallel detector: when the plain OCR
    pass already matched, the extra passes must not run (they would double
    the scan cost of every malicious image for nothing)."""
    called = []
    monkeypatch.setattr(
        recover, "residual_text", lambda gray: called.append("residual") or gray
    )
    image = _images.fake_system_overlay()
    findings, _words, _lines = injection_text.find(image)
    assert findings
    assert called == []


def test_recovery_skipped_when_budget_is_spent():
    """An exhausted budget must skip recovery loudly, not silently - a
    partial scan that says nothing is a fail-open."""
    budget = ocr_mod.ScanBudget(0.000001)
    while not budget.exhausted():
        pass
    image = _images.white_on_white_injection()
    gray = imageio.safe_convert(image, "L")
    findings = injection_text._recovery_findings(gray, 20, None, budget)
    assert findings == []
    assert any("partial" in note for note in budget.notes)
