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
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from PIL import Image, ImageDraw, ImageOps

DEFAULT_TIMEOUT = 20  # seconds, per OCR pass

# Cap the buffer a region OCR pass may allocate. A low-contrast region can be
# most of the page, and upscaling it 3x is a 9x area blow-up; without a bound a
# ~36-megapixel region would ask Pillow to LANCZOS-resize a 300+ megapixel
# image. Shrink the upscale factor to keep the resized buffer under this.
MAX_UPSCALED_PIXELS = 8_000_000


class OcrTimeout(Exception):
    """tesseract exceeded its per-pass timeout on a specific image. Raised
    rather than swallowed so the scanner can report the image as not fully
    scanned instead of silently treating a hung OCR pass as 'no text found'."""


class ScanBudget:
    """Wall-clock budget for one image's OCR work, shared by every pass.

    Without this, the number of tesseract subprocesses an image can demand is
    bounded only by its content - a busy or crafted screenshot can yield
    hundreds of candidate regions, each worth a subprocess with its own
    timeout, which adds up to hours. The budget turns that into a hard
    ceiling. Passes that get skipped when time runs out are recorded in
    `notes` so a truncated scan reports itself as truncated, never as a
    completed scan that found nothing.
    """

    def __init__(self, seconds: Optional[float] = None):
        self.deadline = (time.monotonic() + seconds) if seconds else None
        self.notes: list = []

    def remaining(self) -> Optional[float]:
        if self.deadline is None:
            return None
        return self.deadline - time.monotonic()

    def exhausted(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0

    def clamp(self, timeout: float) -> float:
        """`timeout` reduced to what is left of the budget."""
        remaining = self.remaining()
        if remaining is None:
            return timeout
        return max(0.1, min(timeout, remaining))

    def note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)


def tesseract_path() -> Optional[str]:
    return shutil.which("tesseract")


@lru_cache(maxsize=8)
def ocr_functional(lang: Optional[str] = None) -> bool:
    """Whether tesseract can actually read text right now, not just whether the
    binary is on PATH. A tesseract install missing its language data or the tsv
    config runs fine and returns nothing, which for a detector would look like a
    clean image. Render one known word and confirm it comes back.

    The probe runs with the same `lang` the scan will use, so selecting a
    language whose data is missing fails loud here instead of silently reading
    nothing later. The probe word is ASCII, which every Latin-script pack
    reads; a non-Latin-only pack fails the probe and the scan says so rather
    than guessing."""
    tess_bin = tesseract_path()
    if tess_bin is None:
        return False
    probe = Image.new("RGB", (240, 80), "white")
    ImageDraw.Draw(probe).text((12, 24), "framewall", fill="black")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        probe_path = fh.name
    try:
        probe.save(probe_path)
        out = _run_tsv(tess_bin, probe_path, timeout=DEFAULT_TIMEOUT, lang=lang)
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


def _run_tsv(tess_bin: str, image_path: str, timeout: float, lang: Optional[str] = None) -> str:
    cmd = [tess_bin, image_path, "stdout", "--psm", "3", "tsv"]
    if lang:
        # tesseract's own -l syntax, including "eng+deu" multi-language packs.
        # Options go after the outputbase and before the tsv config name.
        cmd[3:3] = ["-l", lang]
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


def ocr_image(image: Image.Image, timeout: float = DEFAULT_TIMEOUT, lang: Optional[str] = None):
    """Run tesseract on a full Pillow image. Returns (words, lines); both are
    empty if tesseract is missing or fails to run - callers that need to tell
    "no text" apart from "OCR unavailable" should check tesseract_path()
    themselves first. Raises OcrTimeout if tesseract exceeds `timeout` on this
    image, so a hung pass surfaces as an incomplete scan rather than a clean
    one."""
    tess_bin = tesseract_path()
    if tess_bin is None:
        return [], []
    fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="framewall-")
    try:
        os.close(fd)
        image.save(tmp_path, format="PNG")
        output = _run_tsv(tess_bin, tmp_path, timeout, lang=lang)
        return _parse_tsv(output)
    except subprocess.TimeoutExpired as e:
        raise OcrTimeout(f"tesseract exceeded {timeout}s on this image") from e
    except OSError:
        return [], []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def ocr_region(image: Image.Image, box, timeout: float = DEFAULT_TIMEOUT, upscale: int = 3,
               lang: Optional[str] = None):
    """OCR a cropped region after a local contrast stretch. Returns just the
    word list (line boxes aren't meaningful once a region has been cropped
    and upscaled in isolation).

    A whole-image autocontrast does nothing for text that's only a few
    shades off its background, because the image's black-to-white range is
    already maxed out by everything else on the page. Stretched over just
    the small crop, that same few-shade gap becomes the crop's *entire*
    dynamic range, which is what recovers text a human would skim past but a
    vision model - which doesn't care about contrast - reads anyway.

    Raises OcrTimeout when tesseract exceeds `timeout` on the region: the
    caller decides whether to press on with the other regions, and notes the
    gap, rather than this function silently reporting the region as empty.
    """
    tess_bin = tesseract_path()
    if tess_bin is None:
        return []
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return []
    crop = image.convert("L").crop((left, top, right, bottom))
    boosted = ImageOps.autocontrast(crop, cutoff=0)
    # Shrink the upscale factor until the resized buffer fits the cap, so a
    # huge flagged region can't drive a runaway LANCZOS allocation.
    factor = upscale
    while factor > 1 and crop.width * crop.height * factor * factor > MAX_UPSCALED_PIXELS:
        factor -= 1
    if factor > 1:
        boosted = boosted.resize((crop.width * factor, crop.height * factor), Image.LANCZOS)
    words, _lines = ocr_image(boosted, timeout=timeout, lang=lang)
    mapped = []
    for w in words:
        mapped.append(
            Word(
                text=w.text,
                left=left + w.left // factor,
                top=top + w.top // factor,
                width=max(1, w.width // factor),
                height=max(1, w.height // factor),
                conf=w.conf,
            )
        )
    return mapped
