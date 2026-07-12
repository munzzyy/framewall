"""Per-image scan orchestration: run every detection layer, merge findings,
compute the verdict."""

from __future__ import annotations

from pathlib import Path

from . import imageio
from . import ocr as ocr_mod
from .checks import contrast, injection_text, metadata, overlay, tiny_text
from .finding import ImageResult
from .verdict import compute as compute_verdict


def scan_image(path, use_ocr: bool = True, ocr_timeout=None) -> ImageResult:
    path = Path(path)
    result = ImageResult(path=str(path))

    try:
        image = imageio.load_image(path)
    except imageio.ImageError as e:
        result.error = str(e)
        return result

    result.width, result.height = image.size
    gray = image.convert("L")

    findings = []
    low_contrast_findings = contrast.find(gray)
    findings.extend(low_contrast_findings)
    findings.extend(overlay.find(gray))
    findings.extend(metadata.find(image))

    tesseract_found = ocr_mod.tesseract_path() is not None
    if use_ocr and tesseract_found:
        result.ocr_used = True
        low_contrast_regions = [f.region for f in low_contrast_findings if f.region]
        inj_findings, _words, lines = injection_text.find(
            image, low_contrast_regions=low_contrast_regions, timeout=ocr_timeout
        )
        findings.extend(inj_findings)
        findings.extend(tiny_text.find_from_lines(lines, image.size))
    else:
        result.ocr_used = False
        result.ocr_skipped_reason = (
            "--no-ocr was passed" if not use_ocr else "tesseract not found on PATH"
        )
        findings.extend(tiny_text.find_heuristic(gray))

    findings.sort(key=lambda f: f.sort_key())
    result.findings = findings
    result.verdict = compute_verdict(findings).value
    return result
