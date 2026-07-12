"""Target resolution: files, directories, and globs, cross-platform-safe
(never relies on the shell having already expanded a glob)."""

from __future__ import annotations

from framewall.targets import resolve
from tests._images import clean_screenshot


def _make(tmp_path, *names):
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            clean_screenshot().save(p)
        else:
            p.write_text("not an image", encoding="utf-8")


def test_single_file(tmp_path):
    _make(tmp_path, "a.png")
    paths, missing = resolve([str(tmp_path / "a.png")])
    assert len(paths) == 1
    assert missing == []


def test_directory_finds_all_images(tmp_path):
    _make(tmp_path, "a.png", "b.png", "sub/c.png")
    (tmp_path / "notes.txt").write_text("not an image", encoding="utf-8")
    paths, missing = resolve([str(tmp_path)])
    assert len(paths) == 3
    assert missing == []


def test_directory_is_recursive(tmp_path):
    _make(tmp_path, "top.png", "deep/nested/dir/bottom.png")
    paths, _ = resolve([str(tmp_path)])
    assert len(paths) == 2


def test_glob_pattern(tmp_path):
    _make(tmp_path, "shot1.png", "shot2.png", "notes.txt")
    paths, missing = resolve([str(tmp_path / "*.png")])
    assert len(paths) == 2
    assert missing == []


def test_recursive_glob_pattern(tmp_path):
    _make(tmp_path, "a.png", "sub/b.png")
    paths, missing = resolve([str(tmp_path / "**" / "*.png")])
    assert len(paths) == 2


def test_missing_path_is_reported_unmatched(tmp_path):
    paths, missing = resolve([str(tmp_path / "does-not-exist.png")])
    assert paths == []
    assert missing == [str(tmp_path / "does-not-exist.png")]


def test_missing_glob_is_reported_unmatched(tmp_path):
    paths, missing = resolve([str(tmp_path / "*.png")])
    assert paths == []
    assert len(missing) == 1


def test_duplicate_matches_are_deduplicated(tmp_path):
    _make(tmp_path, "a.png")
    target = str(tmp_path / "a.png")
    paths, _ = resolve([target, target])
    assert len(paths) == 1


def test_multiple_targets_combine(tmp_path):
    _make(tmp_path, "a.png", "b.png")
    paths, missing = resolve([str(tmp_path / "a.png"), str(tmp_path / "b.png")])
    assert len(paths) == 2
    assert missing == []


def test_non_image_extension_in_directory_is_skipped(tmp_path):
    _make(tmp_path, "a.png")
    (tmp_path / "readme.md").write_text("hi", encoding="utf-8")
    paths, _ = resolve([str(tmp_path)])
    assert len(paths) == 1


def test_directory_matches_uppercase_extensions(tmp_path):
    # On a case-sensitive filesystem a per-extension "*.png" glob skips a file
    # named "payload.PNG"; a security scan of a directory must still find it.
    _make(tmp_path, "shot.png")
    clean_screenshot().save(tmp_path / "payload.PNG")
    (tmp_path / "sub").mkdir(parents=True, exist_ok=True)
    clean_screenshot().save(tmp_path / "sub" / "hidden.JPEG")
    paths, _ = resolve([str(tmp_path)])
    names = {p.name for p in paths}
    assert "payload.PNG" in names
    assert "hidden.JPEG" in names
    assert len(paths) == 3
