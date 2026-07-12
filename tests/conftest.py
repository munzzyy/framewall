"""Shared fixtures. HAS_TESSERACT gates every test that needs a real OCR
pass; everything else (the Pillow-only heuristics, CLI plumbing, report
rendering) runs on any machine, tesseract or not."""

from __future__ import annotations

import shutil

import pytest

HAS_TESSERACT = shutil.which("tesseract") is not None

requires_tesseract = pytest.mark.skipif(
    not HAS_TESSERACT, reason="tesseract is not installed on this machine"
)
