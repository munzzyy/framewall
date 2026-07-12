"""How a scan reports OCR that cannot run. The dangerous case for a detector
is a tesseract that is installed but reads nothing (no language data): it must
not look like a clean image. These tests fake that state, so they need no real
tesseract and run everywhere."""

from __future__ import annotations

import tempfile
from pathlib import Path

from framewall import ocr as ocr_mod
from framewall.scanner import scan_image
from tests import _images


def _save(img) -> str:
    fh = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fh.close()
    img.save(fh.name)
    return fh.name


def test_present_but_nonfunctional_ocr_is_reported_not_silent(monkeypatch):
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda: False)
    path = _save(_images.clean_screenshot())
    try:
        result = scan_image(path, use_ocr=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert result.ocr_used is False
    assert "read no text" in result.ocr_skipped_reason
    assert "did not run" in result.ocr_skipped_reason


def test_missing_binary_still_reads_as_not_on_path(monkeypatch):
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: None)
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda: False)
    path = _save(_images.clean_screenshot())
    try:
        result = scan_image(path, use_ocr=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert result.ocr_used is False
    assert "not found on PATH" in result.ocr_skipped_reason


def test_no_ocr_flag_wins_over_availability(monkeypatch):
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda: True)
    path = _save(_images.clean_screenshot())
    try:
        result = scan_image(path, use_ocr=False)
    finally:
        Path(path).unlink(missing_ok=True)
    assert result.ocr_used is False
    assert result.ocr_skipped_reason == "--no-ocr was passed"
