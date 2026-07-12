"""Safe-loading tests: size caps and malformed input never raise a bare
traceback, they raise ImageError with a message a CLI can print."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from framewall import imageio
from tests._images import clean_screenshot


def test_loads_a_real_image(tmp_path):
    p = tmp_path / "clean.png"
    clean_screenshot().save(p)
    img = imageio.load_image(p)
    assert img.mode == "RGB"
    assert img.size == (1000, 700)


def test_missing_file_raises_image_error(tmp_path):
    with pytest.raises(imageio.ImageError):
        imageio.load_image(tmp_path / "does-not-exist.png")


def test_corrupt_file_raises_image_error(tmp_path):
    p = tmp_path / "corrupt.png"
    p.write_bytes(b"this is not a png file at all")
    with pytest.raises(imageio.ImageError):
        imageio.load_image(p)


def test_oversized_file_bytes_rejected(tmp_path, monkeypatch):
    p = tmp_path / "small.png"
    clean_screenshot().save(p)
    monkeypatch.setattr(imageio, "MAX_FILE_BYTES", 10)  # smaller than any real PNG
    with pytest.raises(imageio.ImageError, match="exceeds"):
        imageio.load_image(p)


def test_oversized_pixel_count_rejected(tmp_path, monkeypatch):
    p = tmp_path / "big.png"
    Image.new("RGB", (500, 500), "white").save(p)
    monkeypatch.setattr(imageio, "MAX_PIXELS", 1000)  # 500x500 = 250,000 > 1,000
    with pytest.raises(imageio.ImageError, match="exceeds"):
        imageio.load_image(p)


def test_pixel_count_checked_before_full_decode(tmp_path, monkeypatch):
    """The pixel cap must be enforced from the header, before img.load()
    decodes the full pixel grid - otherwise the cap doesn't protect against
    a small, highly-compressed file that decodes to something huge."""
    p = tmp_path / "big.png"
    Image.new("RGB", (4000, 4000), "white").save(p, optimize=True)
    monkeypatch.setattr(imageio, "MAX_PIXELS", 1000)
    calls = []
    real_load = Image.Image.load

    def spy_load(self):
        calls.append(True)
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", spy_load)
    with pytest.raises(imageio.ImageError):
        imageio.load_image(p)
    assert not calls, "img.load() should not run once the header-only size check fails"


def test_non_image_file_with_image_extension(tmp_path):
    p = tmp_path / "fake.jpg"
    p.write_text("hello, this is just text", encoding="utf-8")
    with pytest.raises(imageio.ImageError):
        imageio.load_image(p)


def test_grayscale_and_palette_images_convert_to_rgb(tmp_path):
    p = tmp_path / "gray.png"
    Image.new("L", (50, 50), 128).save(p)
    img = imageio.load_image(p)
    assert img.mode == "RGB"
