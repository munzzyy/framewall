"""docs/checks.md drift check: every RULE_ID in the code appears as a
heading in the doc, and the doc documents nothing that no longer exists."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _rule_ids_in_code():
    ids = set()
    for py in (ROOT / "framewall" / "checks").glob("*.py"):
        if py.name in ("__init__.py", "patterns.py"):
            continue
        m = re.search(r'^RULE_ID\s*=\s*["\']([^"\']+)["\']', py.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            ids.add(m.group(1))
    return ids


def _rule_ids_in_doc():
    doc = (ROOT / "docs" / "checks.md").read_text(encoding="utf-8")
    return set(re.findall(r"^##\s+(FW-\d+)", doc, re.MULTILINE))


def test_every_rule_is_documented():
    undocumented = _rule_ids_in_code() - _rule_ids_in_doc()
    assert not undocumented, f"in code but not docs/checks.md: {sorted(undocumented)}"


def test_doc_has_no_ghost_rules():
    ghosts = _rule_ids_in_doc() - _rule_ids_in_code()
    assert not ghosts, f"in docs/checks.md but not code: {sorted(ghosts)}"


def test_doc_is_not_empty():
    assert len(_rule_ids_in_doc()) >= 5


def test_readme_references_the_checks_doc():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/checks.md" in readme
