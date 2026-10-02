"""Safe image loading. Every scan starts here: a size cap on the file itself
and on the decoded pixel grid, checked before the pixels are decoded, so a
hostile or just enormous input fails with a clear error instead of eating
memory or hanging the OCR pass downstream.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import NamedTuple

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


def read_capped(stream, name="<stdin>") -> bytes:
    """Read an image from a binary stream, never more than MAX_FILE_BYTES + 1
    bytes of it, so an endless pipe can't fill memory before the cap check."""
    chunks = []
    total = 0
    while total <= MAX_FILE_BYTES:
        chunk = stream.read(MAX_FILE_BYTES + 1 - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > MAX_FILE_BYTES:
        raise ImageError(
            f"{name}: more than the {MAX_FILE_BYTES / 1_048_576:.0f} MB cap"
        )
    return b"".join(chunks)


def _open_checked(source, name=None) -> Image.Image:
    """Open `source`, a path or the file's bytes, enforce the file-size and
    pixel-count caps against the header before decoding, and return the loaded
    Pillow image (still in its original mode, possibly multi-frame). `name`
    labels bytes in error messages. Raises ImageError on anything it refuses
    to scan."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        label = name or "<bytes>"
        size = len(source)
        fp = io.BytesIO(source)
    else:
        fp = label = Path(source)
        try:
            size = fp.stat().st_size
        except OSError as e:
            raise ImageError(f"cannot read {label}: {e}") from e
    if size > MAX_FILE_BYTES:
        raise ImageError(
            f"{label}: {size / 1_048_576:.1f} MB exceeds the "
            f"{MAX_FILE_BYTES / 1_048_576:.0f} MB cap"
        )

    try:
        img = Image.open(fp)
        width, height = img.size
        pixels = width * height
        if pixels > MAX_PIXELS:
            raise ImageError(
                f"{label}: {width}x{height} ({pixels:,} px) exceeds the "
                f"{MAX_PIXELS:,} px cap"
            )
        img.load()
        return img
    except ImageError:
        raise
    except UnidentifiedImageError as e:
        # Pillow's own message names the file object, a BytesIO repr for bytes.
        raise ImageError(f"{label}: not a readable image (cannot identify image file)") from e
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ImageError(f"{label}: not a readable image ({e})") from e


def load_image(source, name=None) -> Image.Image:
    """Load `source` (a path or bytes) as an RGB Pillow image (its first
    frame), or raise ImageError with a message safe to print directly.
    Dimensions are checked
    against the header before the pixel data is decoded, so an oversized image
    never gets fully loaded into memory just to be rejected. Pixels only: the
    file's info dict is left behind, for the reason load() gives."""
    rgb = safe_convert(_open_checked(source, name), "RGB")
    rgb.info = {}
    return rgb


class Loaded(NamedTuple):
    frames: list  # (index, rgb_frame) pairs
    metadata: Image.Image  # 1x1 stand-in carrying the file's info dict
    truncated: bool = False  # the file has frames past MAX_FRAMES


def load(source, name=None) -> Loaded:
    """Decode `source`, a path or the file's bytes, into its frames, up to
    MAX_FRAMES, and its metadata.

    Animated GIFs and multi-page TIFFs carry a payload just as easily in frame
    2 as in frame 1, so a scan that only ever looked at the first frame would
    return a confident CLEAN on a file whose later frame is the attack. Same
    size guards as load_image.

    The frames hold pixels and nothing else. The container's info dict (PNG
    text chunks, GIF and JPEG comments, EXIF) rides on a separate 1x1 stand-in
    for the metadata check. Every key in that dict can come from a text chunk
    the sender named, and Pillow trusts some names: a chunk called
    "transparency" or "icc_profile" makes convert() or a PNG save raise. Kept
    apart, nothing that touches the pixels ever reads those values."""
    img = _open_checked(source, name)
    metadata = Image.new("1", (1, 1))
    metadata.info = dict(img.info)
    frames = []
    for index, frame in enumerate(ImageSequence.Iterator(img)):
        if index >= MAX_FRAMES:
            return Loaded(frames, metadata, truncated=True)
        rgb = safe_convert(frame, "RGB")
        rgb.info = {}
        frames.append((index, rgb))
    return Loaded(frames, metadata)
