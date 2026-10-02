"""Per-image scan orchestration: run every detection layer, merge findings,
compute the verdict.

Every OCR pass for one image draws on a single wall-clock budget
(ocr.ScanBudget), so a crafted or just enormous screenshot cannot pin the
scan for hours by fanning out tesseract subprocesses. The same budget is
checked between frames of an animated GIF or multi-page TIFF. Whatever the
budget cuts short is recorded on the result's notes: a partial scan says it
is partial instead of passing itself off as a completed clean one.
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

_ORIENTATION_DEPENDENT = {injection_text.RULE_ID, tiny_text.RULE_ID}

_STRIP_OCR_PAD = 3  # px of context around a tiny strip before it is OCR'd,
# so glyph edges the block grid clipped off stay readable


def scan_image(path, use_ocr: bool = True, ocr_timeout=None,
               max_seconds=DEFAULT_MAX_SCAN_SECONDS, lang=None) -> ImageResult:
    """Scan the image file at `path`. A file framewall can't or won't read
    comes back with `error` set, not as an exception."""
    path = Path(path)
    return _scan(path, str(path), use_ocr, ocr_timeout, max_seconds, lang)


def scan_bytes(data, name: str = "<bytes>", use_ocr: bool = True, ocr_timeout=None,
               max_seconds=DEFAULT_MAX_SCAN_SECONDS, lang=None) -> ImageResult:
    """Scan an image held in memory, such as a screenshot a computer-use loop
    just took. Same caps, decoders and checks as scan_image; `name` is what
    the result reports as its path."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"scan_bytes wants bytes, not {type(data).__name__}")
    return _scan(data, name, use_ocr, ocr_timeout, max_seconds, lang)


def _scan(source, label, use_ocr, ocr_timeout, max_seconds, lang) -> ImageResult:
    result = ImageResult(path=label)

    try:
        frames, meta, truncated, as_stored = imageio.load(source, name=label)
    except imageio.ImageError as e:
        result.error = str(e)
        return result

    budget = ocr_mod.ScanBudget(max_seconds or None)
    if truncated:
        budget.note(
            f"only the first {imageio.MAX_FRAMES} frames were scanned; the scan is partial"
        )
    findings = metadata.find(meta)
    ocr_gaps = []  # (frame index, why OCR did not cover it)
    scanned = 0
    for index, frame in frames:
        if index > 0 and budget.exhausted():
            last = frames[-1][0]
            which = f"frame {index}" if index == last else f"frames {index}-{last}"
            budget.note(f"the scan time budget ran out; {which} not scanned; the scan is partial")
            break
        scanned += 1
        if index == 0:
            result.width, result.height = frame.size
        frame_findings, skipped = _scan_frame(frame, use_ocr, ocr_timeout, budget, lang)
        if skipped:
            ocr_gaps.append((index, skipped))
        stored = (as_stored or {}).get(index)
        if stored is not None:
            stored_findings, stored_skipped = _scan_as_stored(
                stored, use_ocr, ocr_timeout, budget, lang
            )
            frame_findings.extend(stored_findings)
            if stored_skipped and not skipped:
                ocr_gaps.append((index, stored_skipped))
        if index > 0:
            # Tag which frame a finding came from so a CLEAN-looking first frame
            # can't hide an attack in a later one of an animated GIF / TIFF.
            frame_findings = [
                dataclasses.replace(f, detail=f"[frame {index}] {f.detail}")
                for f in frame_findings
            ]
        findings.extend(frame_findings)

    # One frame OCR missed leaves the whole image's OCR incomplete.
    result.ocr_used = not ocr_gaps
    if ocr_gaps:
        index, reason = ocr_gaps[0]
        if len(ocr_gaps) < scanned:
            reason = f"frame {index}: {reason}"
        result.ocr_skipped_reason = reason

    findings.sort(key=lambda f: f.sort_key())
    result.findings = findings
    result.notes = list(budget.notes)
    result.verdict = compute_verdict(findings).value
    return result


def _scan_as_stored(image, use_ocr, ocr_timeout, budget, lang):
    """The second look at a frame EXIF orientation turned: its pixels as
    stored, what a pipeline that ignores the tag shows the model. Only the
    checks that depend on which way the text runs are kept; the pixel-shape
    ones already ran on the same pixels turned."""
    if budget.exhausted():
        budget.note(
            "the scan time budget ran out before the pixels were read as stored, "
            "without their EXIF orientation; the scan is partial"
        )
        return [], ""
    found, skipped = _scan_frame(image, use_ocr, ocr_timeout, budget, lang)
    kept = [
        dataclasses.replace(f, detail=f"[as stored, before EXIF orientation] {f.detail}")
        for f in found
        if f.rule_id in _ORIENTATION_DEPENDENT
    ]
    return kept, skipped


def _scan_frame(image, use_ocr: bool, ocr_timeout, budget, lang):
    """Returns (findings, skipped): skipped is "" when the OCR passes ran on
    this frame, otherwise why they didn't."""
    gray = imageio.safe_convert(image, "L")

    findings = []
    low_contrast_findings = contrast.find(gray)
    findings.extend(low_contrast_findings)
    findings.extend(overlay.find(gray))
    findings.extend(hifreq.find(gray))
    tiny_strips = tiny_text.find_heuristic(gray)

    if not use_ocr:
        findings.extend(tiny_strips)
        return findings, "--no-ocr was passed"
    if not ocr_mod.ocr_functional(lang):
        findings.extend(tiny_strips)
        if ocr_mod.tesseract_path() is None:
            return findings, "tesseract not found on PATH"
        hint = f"missing language data for {lang!r}?" if lang else "missing language data?"
        return findings, (
            f"tesseract is installed but read no text ({hint}); "
            f"the injection-text check did not run"
        )

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
    except ocr_mod.OcrFailed as e:
        # OCR hung or failed on this image. Don't claim a completed OCR pass we
        # didn't actually finish: degrade to the heuristic fallback and say
        # why, the same way a missing tesseract does.
        findings.extend(tiny_strips)
        what = "timed out" if isinstance(e, ocr_mod.OcrTimeout) else "failed"
        return findings, (
            f"tesseract {what} on this image ({e}); the injection-text check did not run"
        )

    findings.extend(inj_findings)
    findings.extend(tiny_text.find_from_lines(lines, image.size))
    # Strips the primary pass read nothing in, but whose upscaled region-OCR
    # crop came back with words, are sub-legible text the plain pass missed -
    # the classic tiny-corner payload.
    findings.extend(tiny_text.confirmed_uncovered(tiny_strips, lines, words, image.size))
    return findings, ""


def _padded(region: Region, size) -> Region:
    width, height = size
    left = max(0, region.left - _STRIP_OCR_PAD)
    top = max(0, region.top - _STRIP_OCR_PAD)
    right = min(width, region.left + region.width + _STRIP_OCR_PAD)
    bottom = min(height, region.top + region.height + _STRIP_OCR_PAD)
    return Region(left, top, right - left, bottom - top)
