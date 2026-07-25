"""Safe image loading. Every scan starts here: a size cap on the file itself
and on the decoded pixel grid, checked before the pixels are decoded, so a
hostile or just enormous input fails with a clear error instead of eating
memory or hanging the OCR pass downstream.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB on disk
MAX_PIXELS = 40_000_000  # ~40 megapixels decoded (e.g. 8000x5000)
MAX_FRAMES = 32  # animated GIF / multi-page TIFF frames scanned before stopping


class ImageError(Exception):
    """Raised for any input image framewall refuses to scan."""


def safe_convert(image, mode) -> Image.Image:
    """`image.convert(mode)` that can't be crashed by a poisoned info dict.

    A PNG tEXt chunk can be named "transparency", and Pillow copies its
    attacker-chosen string value straight into Image.info. A mode conversion
    then tries to read info["transparency"] as a pixel color and blows up with
    "color must be int or tuple", aborting the scan on an attacker-controlled
    chunk name. Pop any transparency value that isn't a real color for the
    duration of the convert, then restore it so the metadata check still reads
    (and flags) the smuggled text.
    """
    trans = image.info.get("transparency")
    if trans is not None and not isinstance(trans, (int, tuple, bytes)):
        saved = image.info.pop("transparency")
        try:
            return image.convert(mode)
        finally:
            image.info["transparency"] = saved
    return image.convert(mode)


def _open_checked(path) -> Image.Image:
    """Open `path`, enforce the file-size and pixel-count caps against the
    header before decoding, and return the loaded Pillow image (still in its
    original mode, possibly multi-frame). Raises ImageError on anything it
    refuses to scan."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as e:
        raise ImageError(f"cannot read {path}: {e}") from e
    if size > MAX_FILE_BYTES:
        raise ImageError(
            f"{path}: {size / 1_048_576:.1f} MB exceeds the "
            f"{MAX_FILE_BYTES / 1_048_576:.0f} MB cap"
        )

    try:
        img = Image.open(path)
        width, height = img.size
        pixels = width * height
        if pixels > MAX_PIXELS:
            raise ImageError(
                f"{path}: {width}x{height} ({pixels:,} px) exceeds the "
                f"{MAX_PIXELS:,} px cap"
            )
        img.load()
        return img
    except ImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise ImageError(f"{path}: not a readable image ({e})") from e


def load_image(path) -> Image.Image:
    """Load `path` as an RGB Pillow image (its first frame), or raise
    ImageError with a message safe to print directly. Dimensions are checked
    against the header before the pixel data is decoded, so an oversized image
    never gets fully loaded into memory just to be rejected."""
    return safe_convert(_open_checked(path), "RGB")


def load_frames(path):
    """Yield (index, rgb_frame) for each frame of `path`, up to MAX_FRAMES.

    A single-frame image yields exactly one. Animated GIFs and multi-page
    TIFFs carry a payload just as easily in frame 2 as in frame 1, so a scan
    that only ever looked at the first frame would return a confident CLEAN on
    a file whose later frame is the attack. Same size guards as load_image; the
    first frame keeps the container's Image.info (where PNG/GIF metadata lives)
    so the metadata check still sees it."""
    img = _open_checked(path)
    for index, frame in enumerate(ImageSequence.Iterator(img)):
        if index >= MAX_FRAMES:
            break
        rgb = safe_convert(frame, "RGB")
        if index == 0:
            # convert() drops the container-level info dict; put it back so the
            # metadata check reads GIF/PNG chunks off the frame it scans.
            rgb.info = dict(img.info)
        yield index, rgb
