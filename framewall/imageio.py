"""Safe image loading. Every scan starts here: a size cap on the file itself
and on the decoded pixel grid, checked before the pixels are decoded, so a
hostile or just enormous input fails with a clear error instead of eating
memory or hanging the OCR pass downstream.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import NamedTuple, Optional

from PIL import Image, ImageSequence, UnidentifiedImageError

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB on disk
MAX_PIXELS = 40_000_000  # ~40 megapixels decoded (e.g. 8000x5000)
MAX_FRAMES = 32  # animated GIF / multi-page TIFF frames scanned before stopping

# The only decoders Pillow may pick, whatever the file is named. MPO is
# reached through JPEG's opener; naming it here makes Pillow raise KeyError.
FORMATS = ("PNG", "JPEG", "GIF", "BMP", "DIB", "TIFF", "WEBP")


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


def _open_checked(source, name=None) -> tuple:
    """Open `source`, a path or the file's bytes, enforce the file-size and
    pixel-count caps against the header before decoding, and return the loaded
    Pillow image (still in its original mode, possibly multi-frame) with the
    turn Pillow applied to its first frame while loading it, or None. `name`
    labels bytes in error messages. Raises ImageError on anything it refuses
    to scan."""
    in_memory = isinstance(source, (bytes, bytearray, memoryview))
    if in_memory:
        label = name or "<bytes>"
        size = memoryview(source).nbytes  # len() counts items, not bytes
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
    if in_memory:
        fp = io.BytesIO(source if isinstance(source, bytes) else memoryview(source).tobytes())

    try:
        img = Image.open(fp, formats=FORMATS)
        width, height = img.size
        pixels = width * height
        if pixels > MAX_PIXELS:
            raise ImageError(
                f"{label}: {width}x{height} ({pixels:,} px) exceeds the "
                f"{MAX_PIXELS:,} px cap"
            )
        turned = _turned_by_pillow(img)
        img.load()
        return img, turned
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
    rgb = safe_convert(_open_checked(source, name)[0], "RGB")
    rgb.info = {}
    return rgb


# EXIF Orientation value -> the transpose that shows the image upright, the
# same table ImageOps.exif_transpose uses.
_UPRIGHT = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


# Every transpose above undoes itself except the quarter turns, which undo
# each other.
_UNDO = {turn: turn for turn in _UPRIGHT.values()}
_UNDO[Image.Transpose.ROTATE_90] = Image.Transpose.ROTATE_270
_UNDO[Image.Transpose.ROTATE_270] = Image.Transpose.ROTATE_90


def _upright_transpose(frame):
    """The transpose an EXIF-aware viewer applies to `frame`, or None. A tag
    Pillow can't parse counts as no tag; the stored pixels get scanned anyway."""
    try:
        return _UPRIGHT.get(frame.getexif().get(0x0112))
    except Exception:
        return None


def _turned_by_pillow(frame):
    """The turn Pillow applies to `frame` itself when it loads, read before
    the load: the TIFF loader runs exif_transpose and then drops the tag."""
    return _upright_transpose(frame) if frame.format == "TIFF" else None


class Loaded(NamedTuple):
    frames: list  # (index, rgb_frame) pairs, turned the way a viewer shows them
    metadata: Image.Image  # 1x1 stand-in carrying the file's info dict
    truncated: bool = False  # the file has frames past MAX_FRAMES
    as_stored: Optional[dict] = None  # index -> rgb pixels before EXIF orientation,
    # only for frames whose Orientation tag turned them


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
    apart, nothing that touches the pixels ever reads those values.

    A frame with an EXIF Orientation tag is turned the way a browser shows
    it, so text stored sideways and displayed level gets read level. Its
    pixels as stored come back too, in `as_stored`: a pipeline that ignores
    the tag hands those to the model instead, and the scan has to cover
    both."""
    img, turned = _open_checked(source, name)
    metadata = Image.new("1", (1, 1))
    metadata.info = dict(img.info)
    frames = []
    as_stored = {}
    for index, frame in enumerate(ImageSequence.Iterator(img)):
        if index >= MAX_FRAMES:
            return Loaded(frames, metadata, True, as_stored)
        if index > 0:
            turned = _turned_by_pillow(frame)
        rgb = safe_convert(frame, "RGB")
        rgb.info = {}
        turn = _upright_transpose(frame)
        if turn is not None:
            as_stored[index] = rgb
            rgb = rgb.transpose(turn)
        elif turned is not None:
            as_stored[index] = rgb.transpose(_UNDO[turned])
        frames.append((index, rgb))
    return Loaded(frames, metadata, False, as_stored)
