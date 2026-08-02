"""Per-image scan orchestration: run every detection layer, merge findings,
compute the verdict.

Every OCR pass for one image draws on a single wall-clock budget
(ocr.ScanBudget), so a crafted or just enormous screenshot cannot pin the
scan for hours by fanning out tesseract subprocesses. Whatever the budget
cuts short is recorded on the result's notes: a partial scan says it is
partial instead of passing itself off as a completed clean one.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from . import imageio
from . import ocr as ocr_mod
from .checks import contrast, hifreq, injection_text, metadata, overlay, tiny_text
from .finding import ImageResult, Region
from .verdict import compute as compute_verdict

DEFAULT_MAX_SCAN_SECONDS = 30  # whole-image ceiling across every OCR pass;
# generous for a real scan, fatal for the hang-the-hook attack. 0/None lifts it.

_STRIP_OCR_PAD = 3  # px of context around a tiny strip before it is OCR'd,
# so glyph edges the block grid clipped off stay readable


def scan_image(path, use_ocr: bool = True, ocr_timeout=None,
               max_seconds=DEFAULT_MAX_SCAN_SECONDS, lang=None) -> ImageResult:
    path = Path(path)
    result = ImageResult(path=str(path))

    try:
        frames = list(imageio.load_frames(path))
    except imageio.ImageError as e:
        result.error = str(e)
        return result

    budget = ocr_mod.ScanBudget(max_seconds or None)
    findings = []
    for index, frame in frames:
        if index == 0:
            result.width, result.height = frame.size
        frame_findings = _scan_frame(frame, use_ocr, ocr_timeout, result, budget, lang)
        if index > 0:
            # Tag which frame a finding came from so a CLEAN-looking first frame
            # can't hide an attack in a later one of an animated GIF / TIFF.
            frame_findings = [
                dataclasses.replace(f, detail=f"[frame {index}] {f.detail}")
                for f in frame_findings
            ]
        findings.extend(frame_findings)

    findings.sort(key=lambda f: f.sort_key())
    result.findings = findings
    result.notes = list(budget.notes)
    result.verdict = compute_verdict(findings).value
    return result


def _scan_frame(image, use_ocr: bool, ocr_timeout, result, budget, lang) -> list:
    gray = imageio.safe_convert(image, "L")

    findings = []
    low_contrast_findings = contrast.find(gray)
    findings.extend(low_contrast_findings)
    findings.extend(overlay.find(gray))
    findings.extend(hifreq.find(gray))
    findings.extend(metadata.find(image))
    tiny_strips = tiny_text.find_heuristic(gray)

    if use_ocr and ocr_mod.ocr_functional(lang):
        try:
            low_contrast_regions = [f.region for f in low_contrast_findings if f.region]
            strip_regions = [
                _padded(f.region, image.size)
                for f in tiny_strips
                if f.region and f.region.width >= tiny_text.MIN_CONFIRMABLE_STRIP_WIDTH
            ]
            inj_findings, words, lines = injection_text.find(
                image,
                gray=gray,
                low_contrast_regions=low_contrast_regions,
                extra_regions=strip_regions,
                timeout=ocr_timeout,
                lang=lang,
                budget=budget,
            )
        except ocr_mod.OcrTimeout as e:
            # OCR hung on this image. Don't claim a completed OCR pass we didn't
            # actually finish: degrade to the heuristic fallback and say why,
            # the same way a missing tesseract does.
            result.ocr_used = False
            result.ocr_skipped_reason = (
                f"tesseract timed out on this image ({e}); the injection-text check did not run"
            )
            findings.extend(tiny_strips)
        else:
            result.ocr_used = True
            findings.extend(inj_findings)
            findings.extend(tiny_text.find_from_lines(lines, image.size))
            # Strips the primary pass read nothing in, but whose upscaled
            # region-OCR crop came back with words, are sub-legible text the
            # plain pass missed - the classic tiny-corner payload.
            findings.extend(
                tiny_text.confirmed_uncovered(tiny_strips, lines, words, image.size)
            )
    else:
        result.ocr_used = False
        if not use_ocr:
            result.ocr_skipped_reason = "--no-ocr was passed"
        elif ocr_mod.tesseract_path() is None:
            result.ocr_skipped_reason = "tesseract not found on PATH"
        else:
            hint = (
                f"missing language data for {lang!r}?" if lang else "missing language data?"
            )
            result.ocr_skipped_reason = (
                f"tesseract is installed but read no text ({hint}); "
                f"the injection-text check did not run"
            )
        findings.extend(tiny_strips)

    return findings


def _padded(region: Region, size) -> Region:
    width, height = size
    left = max(0, region.left - _STRIP_OCR_PAD)
    top = max(0, region.top - _STRIP_OCR_PAD)
    right = min(width, region.left + region.width + _STRIP_OCR_PAD)
    bottom = min(height, region.top + region.height + _STRIP_OCR_PAD)
    return Region(left, top, right - left, bottom - top)
