"""Safe image loading. Every scan starts here: a size cap on the file itself
and on the decoded pixel grid, checked before the pixels are decoded, so a
hostile or just enormous input fails with a clear error instead of eating
memory or hanging the OCR pass downstream.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB on disk
MAX_PIXELS = 40_000_000  # ~40 megapixels decoded (e.g. 8000x5000)


class ImageError(Exception):
    """Raised for any input image framewall refuses to scan."""


def load_image(path) -> Image.Image:
    """Load `path` as an RGB Pillow image, or raise ImageError with a message
    safe to print directly. Dimensions are checked against the header before
    the pixel data is decoded, so an oversized image never gets fully loaded
    into memory just to be rejected."""
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
        return img.convert("RGB")
    except ImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise ImageError(f"{path}: not a readable image ({e})") from e
