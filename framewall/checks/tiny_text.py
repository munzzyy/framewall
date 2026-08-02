"""Tiny text: text present but rendered too small for a human to read at a
glance while still being legible to OCR (and therefore to a vision model).

With OCR available this is precise: it reuses the line boxes tesseract
already produced for the injection-text layer and measures each line's real
height. Without OCR it falls back to a coarser, Pillow-only structural
estimate using the same block-grid technique as the low-contrast check, this
time looking for genuinely high-contrast (human-visible) detail confined to
a thin strip - noisier, and says so in the finding text. The heuristic also
backs OCR up rather than only replacing it: a strip it flags that no OCR
line covers is text tesseract could not read at all - below its recognition
floor - which used to be this check's blind spot.
"""

from __future__ import annotations

import array
import dataclasses

from PIL import Image, ImageChops

from .. import grid
from ..finding import Finding, Region, Severity

RULE_ID = "FW-003"

MIN_HEIGHT_FRACTION = 0.02  # line height below 2% of the shorter side reads as "tiny"...
MAX_HEIGHT_PX = 12.0  # ...but capped in absolute pixels, so a 4K screenshot's normal
# body text (which is many more pixels tall for the same physical size) doesn't
# start tripping this just because the whole image got bigger.
MAX_FINDINGS_REPORTED = 20


def find_from_lines(lines, image_size) -> list:
    """Flag whole text lines shorter than the legibility threshold. Lines,
    not individual words: a word's own bounding box is just its ink, so a
    short, all-lowercase word ("is", "a") in an ordinary paragraph measures
    a fraction of the line's real height and would otherwise look tiny on
    its own."""
    width, height = image_size
    threshold = min(MIN_HEIGHT_FRACTION * min(width, height), MAX_HEIGHT_PX)
    tiny = [ln for ln in lines if 0 < ln.height < threshold]

    findings = []
    for ln in tiny[:MAX_FINDINGS_REPORTED]:
        findings.append(
            Finding(
                rule_id=RULE_ID,
                layer="tiny-text",
                severity=Severity.MEDIUM,
                title="Text below legible size",
                detail=(
                    f"A line of text is {ln.height}px tall in a {width}x{height}px "
                    f"image ({ln.height / min(width, height) * 100:.2f}% of the "
                    f"shorter side) - small enough a human is unlikely to read "
                    f"it, large enough OCR still can."
                ),
                region=Region(ln.left, ln.top, ln.width, ln.height),
                snippet=ln.text[:200],
                remediation="Fine print is normal; check whether this text carries directives aimed at an agent.",
            )
        )
    return findings


MIN_CONFIRMABLE_STRIP_WIDTH = 32  # px; strips narrower than a few characters
# aren't worth an OCR subprocess in OCR mode - on a noisy image the block
# heuristic throws off speckle clusters up to ~24px wide, and real corner
# payloads are sentences, not two letters
_MIN_CONFIRM_WORDS = 2
_MIN_CONFIRM_CHARS = 8


def uncovered_by_lines(strip_findings, lines) -> list:
    """The heuristic strips no OCR line accounts for. A strip OCR *did* read
    in the primary pass is already handled precisely by find_from_lines, so
    overlapping strips are dropped rather than reported twice."""
    kept = []
    for f in strip_findings:
        r = f.region
        covered = any(
            r.left < ln.left + ln.width
            and ln.left < r.left + r.width
            and r.top < ln.top + ln.height
            and ln.top < r.top + r.height
            for ln in lines
        )
        if not covered:
            kept.append(f)
    return kept


def confirmed_uncovered(strip_findings, lines, words, image_size) -> list:
    """The OCR-mode version of the strip heuristic: only strips that
    (a) no primary-pass OCR line covers, and (b) the upscaled region-OCR
    pass actually read words out of.

    (b) is what keeps the heuristic's known weakness out of the default
    mode: on a noisy image, random speckle passes the shape gates at some
    rate, but it never comes back from OCR as words. The cost is that text
    too small for even an upscaled OCR pass stays unflagged in OCR mode,
    same as it always was - the README's limits section says so."""
    width, height = image_size
    kept = []
    for f in uncovered_by_lines(strip_findings, lines):
        r = f.region
        hits = [
            w
            for w in words
            if r.left < w.left + w.width
            and w.left < r.left + r.width
            and r.top < w.top + w.height
            and w.top < r.top + r.height
        ]
        text = " ".join(w.text for w in hits).strip()
        if len(hits) < _MIN_CONFIRM_WORDS or len(text) < _MIN_CONFIRM_CHARS:
            continue
        kept.append(
            dataclasses.replace(
                f,
                detail=(
                    f"A {r.width}x{r.height}px high-detail strip is only "
                    f"{r.height}px tall in a {width}x{height}px image - small "
                    f"enough that a human is unlikely to read it. An OCR pass "
                    f"over the upscaled strip recovered the quoted text."
                ),
                snippet=text[:200],
                remediation="Fine print is normal; check whether this text carries directives aimed at an agent.",
            )
        )
    return kept


# --- OCR-unavailable fallback -------------------------------------------------

_BLOCK = 4  # small enough that a ~9-11px line's height quantizes to close to
# its real size instead of overshooting into the next multiple of the block.
_DETAIL_STDDEV_MIN = 18  # real, human-visible contrast (unlike the low-contrast check)
_MIN_BLOCKS = 3
_MIN_ASPECT = 2.0  # a legible text line reads wider than it is tall
_MAX_WIDTH_FRACTION = 0.5  # a single hidden line of text isn't going to span
# half the screen - something that wide and this thin is almost always a
# divider, a card edge, or a header/body boundary, not text.
_MAX_FILL_RATIO = 0.85  # a straight edge lights up *every* block along its
# length with no gaps; real text has letter- and word-shaped gaps in it.
# Rejecting near-total fill is what tells the two apart without OCR.
_MIN_TRANSITION_DENSITY = 0.16  # rescue path for strips over the fill cap:
# text small enough (7px and under) fills every 4px block, exactly like a
# solid bar does, but at pixel level its strokes still alternate constantly.
# Horizontal neighbor-pixel transitions per strip pixel measure that: tiny
# text lands around 0.2+, a solid or antialiased bar at ~0, a dashed rule
# around 0.12. Strips past the fill cap survive only above this density.
_TRANSITION_STEP = 40  # min value jump between neighbors that counts
_MAX_RESCUE_HEIGHT = 2 * _BLOCK  # the rescue only applies to strips in the
# sub-legible band. Ordinary body text that block-quantizes to the legibility
# threshold is also transition-dense and also fills its blocks; without this
# gate the rescue would resurrect exactly the false positive the fill cap
# exists to reject.

_SQUARES = [v * v for v in range(256)]  # 8-bit value -> its square


def _high_detail_blocks(gray_image, block, cols, rows, min_stddev) -> list:
    """Boolean rows x cols grid marking blocks whose internal contrast
    (population standard deviation) is at least min_stddev.

    Same math as an ImageStat pass per block, but the per-block mean and mean-
    of-squares are computed by Pillow's C core (a BOX-filter downscale) rather
    than a Python crop + Stat object per block. A 24 MP screenshot has ~1.5M of
    these blocks, and the object-per-block loop is what made such a scan take
    close to two minutes; this runs it in a fraction of a second. variance =
    E[x^2] - E[x]^2, so a block clears the bar when that is >= min_stddev^2."""
    mean = gray_image.convert("F").resize((cols, rows), Image.BOX)
    mean_sq = gray_image.point(_SQUARES, "I").convert("F").resize((cols, rows), Image.BOX)
    means = array.array("f")
    means.frombytes(mean.tobytes())
    mean_squares = array.array("f")
    mean_squares.frombytes(mean_sq.tobytes())

    threshold_sq = min_stddev * min_stddev
    flagged = [[False] * cols for _ in range(rows)]
    for i, (m, s) in enumerate(zip(means, mean_squares)):
        if s - m * m >= threshold_sq:
            flagged[i // cols][i % cols] = True
    return flagged


def find_heuristic(gray_image) -> list:
    """Pillow-only estimate: flags thin, wide strips of high-detail content -
    the rough shape of a small line of text - without ever reading what they
    say. With tesseract missing this is the whole tiny-text check; with
    tesseract present the scanner still runs it and keeps whatever strips no
    OCR line covers (see uncovered_by_lines), because text too small for OCR
    to read is exactly the text most worth pointing at. Straight edges
    (panel borders, button outlines, header dividers) are exactly as thin
    and wide as text, so ruling those out is most of the work here."""
    width, height = gray_image.size
    threshold_px = min(MIN_HEIGHT_FRACTION * min(width, height), MAX_HEIGHT_PX)
    cols, rows = grid.block_grid(width, height, _BLOCK)
    flagged = _high_detail_blocks(gray_image, _BLOCK, cols, rows, _DETAIL_STDDEV_MIN)

    findings = []
    for left, top, w, h, n_blocks in grid.group_flagged(flagged, cols, rows, _BLOCK, width, height):
        if n_blocks < _MIN_BLOCKS or h == 0:
            continue
        if w > width * _MAX_WIDTH_FRACTION:
            continue
        cols_span = max(1, -(-w // _BLOCK))
        rows_span = max(1, -(-h // _BLOCK))
        fill_ratio = n_blocks / (cols_span * rows_span)
        if fill_ratio > _MAX_FILL_RATIO and not (
            h <= _MAX_RESCUE_HEIGHT and _transition_dense(gray_image, left, top, w, h)
        ):
            continue
        if h <= threshold_px and w >= h * _MIN_ASPECT:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    layer="tiny-text",
                    severity=Severity.MEDIUM,
                    title="Text-shaped region below legible size (heuristic)",
                    detail=(
                        f"A {w}x{h}px high-detail strip is only {h}px tall in a "
                        f"{width}x{height}px image - shaped like a line of text "
                        f"this small. No OCR was available to confirm this is "
                        f"actual text or read what it says."
                    ),
                    region=Region(left, top, w, h),
                    remediation="Install tesseract and re-scan to confirm and read this text.",
                )
            )
    return findings[:MAX_FINDINGS_REPORTED]


def _transition_dense(gray_image, left, top, w, h) -> bool:
    """Whether a strip's pixels alternate like text strokes rather than a
    solid or smoothly-shaded bar. Counts horizontal neighbor pairs that jump
    by at least _TRANSITION_STEP, per pixel of strip area."""
    if w < 2 or h < 1:
        return False
    crop = gray_image.crop((left, top, left + w, top + h))
    shifted = ImageChops.offset(crop, 1, 0)
    # Drop the first column: offset() wraps around, so that column compares
    # the strip's two opposite edges, which is not a real transition.
    diff = ImageChops.difference(crop, shifted).crop((1, 0, crop.width, crop.height))
    transitions = sum(1 for v in diff.tobytes() if v >= _TRANSITION_STEP)
    return transitions / (diff.width * diff.height) >= _MIN_TRANSITION_DENSITY
