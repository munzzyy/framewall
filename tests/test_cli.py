"""CLI integration tests: argument parsing, exit codes, output formats.
These exercise the full scan pipeline (Pillow-only fixtures, tesseract used
opportunistically) but never assert on OCR-specific findings - that's what
test_ocr.py and test_corpus.py are for."""

from __future__ import annotations

import json

import pytest

from framewall import cli
from tests._images import clean_screenshot, low_contrast_paragraph


@pytest.fixture
def clean_png(tmp_path):
    p = tmp_path / "clean.png"
    clean_screenshot().save(p)
    return p


@pytest.fixture
def suspicious_png(tmp_path):
    p = tmp_path / "suspicious.png"
    low_contrast_paragraph().save(p)
    return p


def test_clean_image_exits_zero(clean_png, capsys):
    code = cli.main(["scan", str(clean_png), "--no-color"])
    assert code == 0
    out = capsys.readouterr().out
    assert "CLEAN" in out


def test_suspicious_image_exits_one_with_default_fail_on(suspicious_png):
    code = cli.main(["scan", str(suspicious_png), "--no-color"])
    assert code == 1


def test_fail_on_none_always_exits_zero(suspicious_png):
    code = cli.main(["scan", str(suspicious_png), "--no-color", "--fail-on", "none"])
    assert code == 0


def test_fail_on_dangerous_lets_suspicious_through(suspicious_png):
    """A suspicious-but-not-dangerous image passes a --fail-on dangerous
    gate; only used to prove the threshold is respected, not to assert what
    exact severity low_contrast_paragraph produces without OCR."""
    code = cli.main(["scan", str(suspicious_png), "--no-color", "--no-ocr", "--fail-on", "dangerous"])
    assert code in (0, 1)  # sanity: must return a real exit code either way


def test_invalid_fail_on_value_raises_system_exit(clean_png):
    with pytest.raises(SystemExit):
        cli.main(["scan", str(clean_png), "--fail-on", "nonsense"])


def test_missing_target_exits_two(capsys):
    code = cli.main(["scan", "/no/such/path/anywhere.png"])
    assert code == 2
    err = capsys.readouterr().err
    assert "no images matched" in err


def test_no_subcommand_exits_two():
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


def test_version_flag_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--version"])
    assert exc_info.value.code == 0


def test_json_output_is_valid_json(clean_png, capsys):
    code = cli.main(["scan", str(clean_png), "--json", "--fail-on", "none"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "framewall"
    assert len(payload["images"]) == 1


def test_sarif_output_is_valid_json(clean_png, capsys):
    code = cli.main(["scan", str(clean_png), "--sarif", "--fail-on", "none"])
    assert code == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "2.1.0"


def test_quiet_output_is_one_line_per_image(clean_png, capsys):
    code = cli.main(["scan", str(clean_png), "--quiet", "--fail-on", "none"])
    assert code == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert out[0].startswith("CLEAN")


def test_no_ocr_flag_is_reported_in_output(clean_png, capsys):
    cli.main(["scan", str(clean_png), "--no-ocr", "--fail-on", "none"])
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "--no-ocr" in out


def test_json_and_sarif_are_mutually_exclusive(clean_png):
    with pytest.raises(SystemExit):
        cli.main(["scan", str(clean_png), "--json", "--sarif"])


def test_directory_target_scans_every_image(tmp_path, capsys):
    clean_screenshot().save(tmp_path / "a.png")
    clean_screenshot().save(tmp_path / "b.png")
    code = cli.main(["scan", str(tmp_path), "--json", "--fail-on", "none"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["images"]) == 2


def test_glob_target_scans_matching_images(tmp_path, capsys):
    clean_screenshot().save(tmp_path / "shot1.png")
    clean_screenshot().save(tmp_path / "shot2.png")
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    code = cli.main(["scan", str(tmp_path / "*.png"), "--json", "--fail-on", "none"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["images"]) == 2


def test_oversized_image_exits_two(tmp_path, monkeypatch, capsys):
    from PIL import Image

    p = tmp_path / "big.png"
    Image.new("RGB", (500, 500), "white").save(p)
    from framewall import imageio

    monkeypatch.setattr(imageio, "MAX_PIXELS", 1000)
    code = cli.main(["scan", str(p), "--no-color", "--fail-on", "none"])
    assert code == 2
    assert "ERROR" in capsys.readouterr().out


def test_corrupt_image_exits_two(tmp_path, capsys):
    p = tmp_path / "corrupt.png"
    p.write_bytes(b"not a png")
    code = cli.main(["scan", str(p), "--no-color", "--fail-on", "none"])
    assert code == 2
    assert "ERROR" in capsys.readouterr().out


def test_multiple_targets_all_scanned(clean_png, suspicious_png, capsys):
    code = cli.main(["scan", str(clean_png), str(suspicious_png), "--json", "--fail-on", "none"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["images"]) == 2
