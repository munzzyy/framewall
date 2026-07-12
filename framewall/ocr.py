"""tesseract integration. Shells out to the `tesseract` CLI so Pillow stays
the only runtime dependency (never pytesseract, which would add one). Every
call uses a fixed argv list, a timeout, and a real file on disk via tempfile -
no shell=True, nothing piped in from network or user-controlled strings.

tesseract is optional. Callers check tesseract_path() up front and degrade to
heuristics-only when it's missing; the functions here never raise for that,
they just return no words.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw, ImageOps

DEFAULT_TIMEOUT = 20  # seconds, per OCR pass


def tesseract_path() -> Optional[str]:
    return shutil.which("tesseract")


@lru_cache(maxsize=1)
def ocr_functional() -> bool:
    """Whether tesseract can actually read text right now, not just whether the
    binary is on PATH. A tesseract install missing its language data or the tsv
    config runs fine and returns nothing, which for a detector would look like a
    clean image. Render one known word and confirm it comes back."""
    tess_bin = tesseract_path()
    if tess_bin is None:
        return False
    probe = Image.new("RGB", (240, 80), "white")
    ImageDraw.Draw(probe).text((12, 24), "framewall", fill="black")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        probe_path = fh.name
    try:
        probe.save(probe_path)
        out = _run_tsv(tess_bin, probe_path, timeout=DEFAULT_TIMEOUT)
    except (subprocess.SubprocessError, OSError):
        return False
    finally:
        try:
            os.unlink(probe_path)
        except OSError:
            pass
    return any(row.split("\t")[-1].strip() for row in out.splitlines()[1:])


@dataclass(frozen=True)
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float


@dataclass(frozen=True)
class Line:
    """A whole text line's bounding box, spanning the full ascender-to-
    descender range of every word on it. Far more stable than any single
    word's box for judging "how tall does this text read" - a short,
    all-lowercase word like "is" measures a fraction of the height of the
    line it sits on, and would look like tiny text in isolation even in an
    ordinary paragraph."""

    text: str
    left: int
    top: int
    width: int
    height: int


def _run_tsv(tess_bin: str, image_path: str, timeout: int) -> str:
    cmd = [tess_bin, image_path, "stdout", "--psm", "3", "tsv"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return proc.stdout


def _parse_tsv(output: str):
    """Tesseract's TSV is hierarchical: a level-4 row gives a line's own
    bounding box, immediately followed by the level-5 (word) rows that make
    up that line. We walk it once and build both views."""
    words: list = []
    lines: list = []
    raw_lines = output.splitlines()
    if not raw_lines:
        return words, lines
    header = raw_lines[0].split("\t")
    wanted = ("level", "left", "top", "width", "height", "conf", "text")
    if not all(name in header for name in wanted):
        return words, lines
    idx = {name: header.index(name) for name in wanted}

    current_line = None  # Line built from tesseract's own level-4 box, plus accumulated word text
    for raw in raw_lines[1:]:
        cols = raw.split("\t")
        if len(cols) <= max(idx.values()):
            continue
        try:
            level = int(cols[idx["level"]])
            left = int(cols[idx["left"]])
            top = int(cols[idx["top"]])
            width = int(cols[idx["width"]])
            height = int(cols[idx["height"]])
        except ValueError:
            continue

        if level == 4:
            if current_line is not None:
                _flush_line(current_line, lines)
            # Trust tesseract's own line box rather than re-deriving one from
            # word boxes: a single misread glyph can give one word a wildly
            # oversized box, which would blow up a union-based estimate.
            current_line = {"left": left, "top": top, "width": width, "height": height, "words": []}
            continue

        if level == 5:
            text = cols[idx["text"]].strip()
            if not text:
                continue
            try:
                conf = float(cols[idx["conf"]])
            except ValueError:
                conf = -1.0
            words.append(Word(text=text, left=left, top=top, width=width, height=height, conf=conf))
            if current_line is not None:
                current_line["words"].append(text)

    if current_line is not None:
        _flush_line(current_line, lines)
    return words, lines


def _flush_line(current_line: dict, lines: list) -> None:
    if not current_line["words"]:
        return
    lines.append(
        Line(
            text=" ".join(current_line["words"]),
            left=current_line["left"],
            top=current_line["top"],
            width=current_line["width"],
            height=current_line["height"],
        )
    )


def ocr_image(image: Image.Image, timeout: int = DEFAULT_TIMEOUT):
    """Run tesseract on a full Pillow image. Returns (words, lines); both are
    empty if tesseract is missing, times out, or fails to run - callers that
    need to tell "no text" apart from "OCR unavailable" should check
    tesseract_path() themselves first."""
    tess_bin = tesseract_path()
    if tess_bin is None:
        return [], []
    fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="framewall-")
    try:
        os.close(fd)
        image.save(tmp_path, format="PNG")
        output = _run_tsv(tess_bin, tmp_path, timeout)
        return _parse_tsv(output)
    except (subprocess.TimeoutExpired, OSError):
        return [], []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def ocr_region(image: Image.Image, box, timeout: int = DEFAULT_TIMEOUT, upscale: int = 3):
    """OCR a cropped region after a local contrast stretch. Returns just the
    word list (line boxes aren't meaningful once a region has been cropped
    and upscaled in isolation).

    A whole-image autocontrast does nothing for text that's only a few
    shades off its background, because the image's black-to-white range is
    already maxed out by everything else on the page. Stretched over just
    the small crop, that same few-shade gap becomes the crop's *entire*
    dynamic range, which is what recovers text a human would skim past but a
    vision model - which doesn't care about contrast - reads anyway.
    """
    tess_bin = tesseract_path()
    if tess_bin is None:
        return []
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return []
    crop = image.convert("L").crop((left, top, right, bottom))
    boosted = ImageOps.autocontrast(crop, cutoff=0)
    if upscale > 1:
        boosted = boosted.resize(
            (boosted.width * upscale, boosted.height * upscale), Image.LANCZOS
        )
    words, _lines = ocr_image(boosted, timeout=timeout)
    mapped = []
    for w in words:
        mapped.append(
            Word(
                text=w.text,
                left=left + w.left // upscale,
                top=top + w.top // upscale,
                width=max(1, w.width // upscale),
                height=max(1, w.height // upscale),
                conf=w.conf,
            )
        )
    return mapped
