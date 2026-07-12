"""Shared fixtures. OCR_WORKS gates every test that needs a real OCR pass;
everything else (the Pillow-only heuristics, CLI plumbing, report rendering)
runs on any machine. The gate probes whether tesseract can actually read text,
not just whether the binary exists, so a half-installed tesseract (no language
data) skips these cleanly instead of failing them."""

from __future__ import annotations

import pytest

from framewall.ocr import ocr_functional

OCR_WORKS = ocr_functional()

requires_tesseract = pytest.mark.skipif(
    not OCR_WORKS, reason="tesseract cannot read text on this machine (missing or no language data)"
)
