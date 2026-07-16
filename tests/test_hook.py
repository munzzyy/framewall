"""The Claude Code PreToolUse guard in hooks/framewall-guard.sh."""

import json
import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "framewall-guard.sh"
POISONED = REPO / "examples" / "poisoned-screenshot.png"
CLEAN = REPO / "examples" / "clean-screenshot.png"


def run(payload, env=None):
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


def test_dangerous_image_is_denied():
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(POISONED)}})
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "DANGEROUS" in out["permissionDecisionReason"]


def test_clean_image_passes_through():
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(CLEAN)}})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_non_image_is_ignored():
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(REPO / "README.md")}})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_missing_file_is_ignored():
    r = run({"tool_name": "Read", "tool_input": {"file_path": "/no/such/image.png"}})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_suspicious_verdict_asks(tmp_path):
    # Stub framewall on PATH so the ask branch is exercised without needing a
    # real image that lands on SUSPICIOUS.
    stub = tmp_path / "framewall"
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'echo \'{"images":[{"verdict":"suspicious"}]}\'\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    img = tmp_path / "shot.png"
    img.write_bytes(b"not really a png")
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(img)}}, env=env)
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask"


def test_unparseable_output_allows(tmp_path):
    # framewall present but emitting something the hook can't read as a verdict
    # must fail open, not block the read on a parse error.
    stub = tmp_path / "framewall"
    stub.write_text('#!/usr/bin/env bash\necho "tesseract exploded, not json"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    img = tmp_path / "shot.png"
    img.write_bytes(b"not really a png")
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(img)}}, env=env)
    assert r.returncode == 0
    assert r.stdout.strip() == ""
