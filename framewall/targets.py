"""Resolve CLI targets - a file, a directory, or a glob - into a sorted,
de-duplicated list of image paths.

Globs are matched with the standard library rather than relying on shell
expansion, since Windows shells don't expand `*` before handing it to the
process; a quoted glob like "screenshots/*.png" needs to work the same way
on every platform this ships CI for.
"""

from __future__ import annotations

import glob as globmod
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_GLOB_CHARS = set("*?[")


def resolve(raw_targets):
    """Returns (paths, unmatched) - unmatched holds any target string that
    named nothing on disk, so the caller can warn about it."""
    found = set()
    unmatched = []
    for target in raw_targets:
        if _GLOB_CHARS & set(target):
            matches = globmod.glob(target, recursive=True)
            if not matches:
                unmatched.append(target)
                continue
            for m in matches:
                p = Path(m)
                if p.is_file():
                    found.add(p.resolve())
            continue

        p = Path(target)
        if p.is_dir():
            for ext in IMAGE_EXTS:
                found.update(fp.resolve() for fp in p.rglob(f"*{ext}"))
        elif p.is_file():
            found.add(p.resolve())
        else:
            unmatched.append(target)
    return sorted(found), unmatched
