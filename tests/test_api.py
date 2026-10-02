"""The Python API: framewall.scan_bytes and framewall.scan_image, for callers
that hold a screenshot in memory instead of on disk."""

from __future__ import annotations

import array
import io
from pathlib import Path

import pytest
from PIL import Image

import framewall
from framewall import imageio
from tests._images import clean_screenshot

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _png_bytes(image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def test_scan_bytes_flags_the_poisoned_example():
    data = (EXAMPLES / "poisoned-screenshot.png").read_bytes()
    result = framewall.scan_bytes(data, use_ocr=False)
    assert result.error == ""
    assert result.verdict == "dangerous"
    assert result.path == "<bytes>"


def test_scan_bytes_reports_the_name_it_was_given():
    result = framewall.scan_bytes(_png_bytes(clean_screenshot()), name="frame-12", use_ocr=False)
    assert result.path == "frame-12"
    assert result.verdict == "clean"


def test_scan_bytes_matches_scan_image_on_the_same_file():
    path = EXAMPLES / "poisoned-screenshot.png"
    from_disk = framewall.scan_image(path, use_ocr=False)
    in_memory = framewall.scan_bytes(path.read_bytes(), use_ocr=False)
    assert in_memory.verdict == from_disk.verdict
    assert (in_memory.width, in_memory.height) == (from_disk.width, from_disk.height)
    assert in_memory.findings == from_disk.findings


def test_scan_bytes_returns_an_error_for_data_that_is_not_an_image():
    result = framewall.scan_bytes(b"not an image at all")
    assert "not a readable image" in result.error
    assert "BytesIO" not in result.error


def test_scan_bytes_holds_the_file_size_cap(monkeypatch):
    monkeypatch.setattr(imageio, "MAX_FILE_BYTES", 100)
    result = framewall.scan_bytes(_png_bytes(clean_screenshot()), use_ocr=False)
    assert "exceeds" in result.error


def test_scan_bytes_counts_a_memoryview_in_bytes_not_items(monkeypatch):
    data = _png_bytes(clean_screenshot())
    data += b"\0" * (-len(data) % 8)
    monkeypatch.setattr(imageio, "MAX_FILE_BYTES", len(data) - 1)
    wide = memoryview(array.array("Q", data))
    assert len(wide) * 8 == len(data)
    assert "exceeds" in framewall.scan_bytes(wide, use_ocr=False).error


def test_scan_bytes_reads_a_strided_memoryview_without_crashing():
    data = _png_bytes(clean_screenshot())
    assert framewall.scan_bytes(memoryview(data)[::1], use_ocr=False).verdict == "clean"
    assert "not a readable image" in framewall.scan_bytes(memoryview(data)[::2], use_ocr=False).error


def test_scan_bytes_holds_the_pixel_cap(monkeypatch):
    monkeypatch.setattr(imageio, "MAX_PIXELS", 1000)
    result = framewall.scan_bytes(_png_bytes(Image.new("RGB", (500, 500), "white")), use_ocr=False)
    assert "exceeds" in result.error


def test_scan_bytes_refuses_a_path_string():
    with pytest.raises(TypeError):
        framewall.scan_bytes("screenshot.png")


class _EndlessStream:
    """A pipe that never ends, counting what the reader asked for."""

    def __init__(self):
        self.consumed = 0

    def read(self, n=-1):
        assert n is not None and n >= 0, "an unbounded read would never return"
        chunk = min(n, 4096)
        self.consumed += chunk
        return b"\x89" * chunk


def test_read_capped_stops_one_byte_past_the_cap(monkeypatch):
    monkeypatch.setattr(imageio, "MAX_FILE_BYTES", 10_000)
    stream = _EndlessStream()
    with pytest.raises(imageio.ImageError, match="cap"):
        imageio.read_capped(stream)
    assert stream.consumed == 10_001


def test_read_capped_takes_a_stream_exactly_at_the_cap(monkeypatch):
    monkeypatch.setattr(imageio, "MAX_FILE_BYTES", 64)
    assert imageio.read_capped(io.BytesIO(b"x" * 64)) == b"x" * 64
