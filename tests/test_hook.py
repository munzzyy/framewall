"""The Claude Code PreToolUse guard in hooks/framewall-guard.sh.

POSIX only. The tests exec the .sh directly, build PATH with ':', and rely on
the executable bit, none of which mean anything on Windows - so the whole
module skips there rather than failing on WinError 193.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.conftest import OCR_WORKS

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the guard is a POSIX shell hook; nothing to exec on Windows"
)

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "framewall-guard.sh"
POISONED = REPO / "examples" / "poisoned-screenshot.png"
CLEAN = REPO / "examples" / "clean-screenshot.png"


def run(payload, env=None, cwd=None):
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
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
    if OCR_WORKS:
        assert r.stdout.strip() == ""
    else:
        # No English OCR data on this machine: still allowed, but the user is told.
        out = json.loads(r.stdout)
        assert "hookSpecificOutput" not in out
        assert "OCR did not run" in out["systemMessage"]


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


def _stub_framewall(tmp_path, body):
    stub = tmp_path / "framewall"
    stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    img = tmp_path / "shot.png"
    img.write_bytes(b"not really a png")
    return stub, img


def test_no_verdict_asks_by_default(tmp_path):
    # framewall present but emitting no readable verdict (a scan error, a crash,
    # an unscannable image) must NOT silently allow the read - that's the whole
    # bypass this guard closes. Default to ask.
    _stub, img = _stub_framewall(tmp_path, 'echo "tesseract exploded, not json" >&2')
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    env.pop("FRAMEWALL_GUARD_FAIL", None)
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(img)}}, env=env)
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask"
    assert "not scanned" in out["permissionDecisionReason"].lower() or "no" in out["permissionDecisionReason"].lower()


def test_no_verdict_denies_when_fail_closed(tmp_path):
    # Opt-in strict mode turns the same no-verdict outcome into a hard block.
    _stub, img = _stub_framewall(tmp_path, 'echo "boom" >&2')
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", FRAMEWALL_GUARD_FAIL="closed")
    r = run({"tool_name": "Read", "tool_input": {"file_path": str(img)}}, env=env)
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"


def _read(img):
    return {"tool_name": "Read", "tool_input": {"file_path": str(img)}}


def _stub_env(tmp_path, report, fail=None):
    _stub, img = _stub_framewall(tmp_path, f"echo '{json.dumps(report)}'")
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    env.pop("FRAMEWALL_GUARD_FAIL", None)
    if fail:
        env["FRAMEWALL_GUARD_FAIL"] = fail
    return img, env


DEGRADED_CLEAN = {
    "no-ocr": {"images": [{"verdict": "clean", "ocr_used": False,
                           "ocr_skipped_reason": "tesseract not found on PATH", "notes": []}]},
    "partial": {"images": [{"verdict": "clean", "ocr_used": True, "notes": [
        "3 candidate region(s) beyond the 24-region OCR cap went unread; the scan is partial"]}]},
}


@pytest.mark.parametrize("case", sorted(DEGRADED_CLEAN))
def test_degraded_clean_scan_is_allowed_but_shown_to_the_user(tmp_path, case):
    # Exit 0 stderr never reaches the user from a PreToolUse hook; a
    # systemMessage does. No permission decision, so the read goes ahead.
    img, env = _stub_env(tmp_path, DEGRADED_CLEAN[case])
    r = run(_read(img), env=env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "hookSpecificOutput" not in out
    assert "incomplete" in out["systemMessage"]
    assert ("tesseract not found" if case == "no-ocr" else "partial") in out["systemMessage"]


@pytest.mark.parametrize("case", sorted(DEGRADED_CLEAN))
def test_degraded_clean_scan_asks_when_fail_closed(tmp_path, case):
    img, env = _stub_env(tmp_path, DEGRADED_CLEAN[case], fail="closed")
    r = run(_read(img), env=env)
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask"
    assert "incomplete" in out["permissionDecisionReason"]


def test_full_clean_scan_stays_silent(tmp_path):
    img, env = _stub_env(
        tmp_path, {"images": [{"verdict": "clean", "ocr_used": True, "notes": []}]}
    )
    r = run(_read(img), env=env)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_missing_framewall_is_shown_to_the_user(tmp_path):
    # A PATH holding only what the guard needs to get that far, and a
    # framewall package that fails to import, so the real install (if any)
    # can't be found.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("bash", "cat", "python3", "tr"):
        found = shutil.which(tool)
        assert found, f"{tool} is needed to run the guard"
        (bindir / tool).symlink_to(found)
    shadow = tmp_path / "shadow" / "framewall"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("raise ImportError('not installed')\n")
    img = tmp_path / "shot.png"
    img.write_bytes(b"not really a png")
    env = dict(os.environ, PATH=str(bindir), PYTHONPATH=str(shadow.parent))
    r = run(_read(img), env=env, cwd=tmp_path)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "hookSpecificOutput" not in out
    assert "not installed" in out["systemMessage"]


@pytest.mark.skipif(shutil.which("timeout") is None, reason="no timeout(1) to cut the scan off")
def test_a_scan_that_times_out_runs_once(tmp_path):
    # The guard used to re-run a scan that printed nothing via python3 -m
    # framewall, so a timed-out scan cost two full timeouts. Both entry points
    # are stubbed to log and hang; only one may run. timeout(1) is shimmed
    # down to 1 s so the test doesn't wait out the real limit.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    hang = f'echo "$0 $*" >> "{log}"\nsleep 10\n'
    stub = bindir / "framewall"
    stub.write_text(f"#!/usr/bin/env bash\n{hang}")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    shim = bindir / "timeout"
    shim.write_text(f'#!/usr/bin/env bash\nshift\nexec "{shutil.which("timeout")}" 1 "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    pkg = tmp_path / "cwd" / "framewall"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(
        f"import sys, time\nopen({str(log)!r}, 'a').write('module ' + ' '.join(sys.argv[1:]) + '\\n')\ntime.sleep(10)\n"
    )
    img = tmp_path / "shot.png"
    img.write_bytes(b"not really a png")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    env.pop("FRAMEWALL_GUARD_FAIL", None)
    r = run(_read(img), env=env, cwd=pkg.parent)
    calls = log.read_text().splitlines()
    assert len(calls) == 1, calls
    args = calls[0].split()
    limit = float(args[args.index("--max-scan-seconds") + 1])
    assert 0 < limit < 30
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask"
    assert "did not finish" in out["permissionDecisionReason"]
