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


def test_readme_does_not_hardcode_a_test_count():
    """The README once said "154 tests" while the suite had 204. A hardcoded
    count is a permanent drift source with no reader value, so the guard is
    simpler than keeping one fresh: don't state one."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claims = re.findall(r"\b\d+\s+tests\b", readme)
    assert not claims, (
        f"README hardcodes a test count ({claims}); it goes stale with every "
        f"added test - describe the suite, don't number it"
    )


def test_readme_benchmark_claim_matches_the_enforced_floor():
    """The README's measured catch rate and tests/test_benchmark_floor.py
    must state the same numbers, or the published claim drifts from what CI
    actually enforces."""
    from tests import test_benchmark_floor as floor

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"catches (\d+) of (\d+)", readme)
    assert m, "README no longer states the measured catch rate"
    assert (int(m.group(1)), int(m.group(2))) == (floor.FLOOR, len(floor.TECHNIQUES))
    fp = re.search(r"false-positives on (\d+) of (\d+)", readme)
    assert fp, "README no longer states the benign false-positive rate"
    assert (int(fp.group(1)), int(fp.group(2))) == (
        len(floor.ALLOWED_FALSE_POSITIVES),
        len(floor.BENIGN_CONTROLS),
    )
