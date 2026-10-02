"""The Claude Code PreToolUse guard, through both entry points: `framewall
guard` and hooks/framewall-guard.sh. They must behave the same.

The shell script only runs where there is a shell to exec it, so its cases
skip on Windows. The `framewall guard` cases run everywhere: they call the
guard in-process and point its scan at a stub framewall, a small Python
script that prints whatever scan output the test wants. The shell cases put
that same stub on PATH as `framewall`.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from framewall import guard
from tests.conftest import OCR_WORKS

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "framewall-guard.sh"
POISONED = REPO / "examples" / "poisoned-screenshot.png"
CLEAN = REPO / "examples" / "clean-screenshot.png"

POSIX_ONLY = pytest.mark.skipif(
    os.name == "nt", reason="the shell guard is a POSIX script; nothing to exec on Windows"
)
ENTRY_POINTS = [pytest.param("sh", marks=POSIX_ONLY), "py"]


def _read(path):
    return {"tool_name": "Read", "tool_input": {"file_path": str(path)}}


def _stub(tmp_path, body):
    """A fake framewall: Python that gets the scan's argv and does `body`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "framewall"
    stub.write_text(f"#!/usr/bin/env python3\nimport json, sys, time\n{body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def _printing(tmp_path, report):
    return _stub(tmp_path, f"print(json.dumps({report!r}))")


def _image(tmp_path, name="shot.png"):
    img = tmp_path / name
    img.write_bytes(b"not really a png")
    return img


def run(entry, payload, monkeypatch, stub=None, fail=None, cwd=None):
    """(exit code, stdout) of one guard run."""
    if fail:
        monkeypatch.setenv("FRAMEWALL_GUARD_FAIL", fail)
    else:
        monkeypatch.delenv("FRAMEWALL_GUARD_FAIL", raising=False)
    if entry == "sh":
        env = dict(os.environ)
        # The hook works from $HOME now, so the checkout is no longer on the
        # child's sys.path by accident; an installed framewall is what real
        # users have, and PYTHONPATH stands in for that install here.
        env["PYTHONPATH"] = str(REPO)
        if stub is not None:
            env["PATH"] = f"{stub.parent}{os.pathsep}{env['PATH']}"
        r = subprocess.run(
            [str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
            env=env, cwd=cwd,
        )
        return r.returncode, r.stdout
    if stub is not None:
        real = guard._scan_command
        monkeypatch.setattr(
            guard, "_scan_command", lambda path, seconds: [sys.executable, str(stub)] + real(path, seconds)[3:]
        )
    out = io.StringIO()
    code = guard.main(io.StringIO(json.dumps(payload)), out)
    return code, out.getvalue()


def _decision(stdout):
    return json.loads(stdout)["hookSpecificOutput"]


# --- the working directory is the agent's project, which must not get to run ----------


def _planted(tmp_path):
    """A project that ships code under the names the guard's children import."""
    marker = tmp_path / "ran.marker"
    pkg = tmp_path / "framewall"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(
        f"import json, pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n"
        "print(json.dumps({'images': [{'path': 'p', 'verdict': 'CLEAN', 'findings': []}]}))\n"
    )
    (tmp_path / "json.py").write_text(f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n")
    return marker


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_the_projects_own_framewall_or_json_never_runs(entry, monkeypatch, tmp_path):
    marker = _planted(tmp_path)
    monkeypatch.chdir(tmp_path)
    code, out = run(entry, _read(CLEAN), monkeypatch, cwd=tmp_path)
    assert code == 0
    assert not marker.exists(), "a file in the agent's cwd was imported by the guard"
    assert "DANGEROUS" not in out


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_a_relative_image_path_still_resolves_from_the_project(entry, monkeypatch, tmp_path):
    marker = _planted(tmp_path)
    monkeypatch.chdir(tmp_path)
    shutil.copy(POISONED, tmp_path / "shot.png")
    code, out = run(entry, _read("shot.png"), monkeypatch, cwd=tmp_path)
    assert code == 0
    assert not marker.exists()
    assert _decision(out)["permissionDecision"] == "deny"


# --- real scans, no stub ---------------------------------------------------------


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_dangerous_image_is_denied(entry, monkeypatch):
    monkeypatch.chdir(REPO)
    code, out = run(entry, _read(POISONED), monkeypatch)
    assert code == 0
    decision = _decision(out)
    assert decision["permissionDecision"] == "deny"
    assert "DANGEROUS" in decision["permissionDecisionReason"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_clean_image_passes_through(entry, monkeypatch):
    monkeypatch.chdir(REPO)
    code, out = run(entry, _read(CLEAN), monkeypatch)
    assert code == 0
    if OCR_WORKS:
        assert out.strip() == ""
    else:
        # No English OCR data on this machine: still allowed, but the user is told.
        message = json.loads(out)
        assert "hookSpecificOutput" not in message
        assert "OCR did not run" in message["systemMessage"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_non_image_is_ignored(entry, monkeypatch, tmp_path):
    stub = _stub(tmp_path, "raise SystemExit('a non-image must not be scanned')")
    code, out = run(entry, _read(REPO / "README.md"), monkeypatch, stub=stub)
    assert (code, out.strip()) == (0, "")


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_missing_file_is_ignored(entry, monkeypatch):
    code, out = run(entry, _read("/no/such/image.png"), monkeypatch)
    assert (code, out.strip()) == (0, "")


# --- every verdict branch, through a stub scanner ---------------------------------


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_uppercase_extension_is_scanned(entry, monkeypatch, tmp_path):
    stub = _printing(tmp_path, {"images": [{"verdict": "dangerous"}]})
    _code, out = run(entry, _read(_image(tmp_path, "SHOT.PNG")), monkeypatch, stub=stub)
    assert _decision(out)["permissionDecision"] == "deny"


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_suspicious_verdict_asks(entry, monkeypatch, tmp_path):
    stub = _printing(tmp_path, {"images": [{"verdict": "suspicious"}]})
    code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub)
    assert code == 0
    decision = _decision(out)
    assert decision["permissionDecision"] == "ask"
    assert "SUSPICIOUS" in decision["permissionDecisionReason"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_no_verdict_asks_by_default(entry, monkeypatch, tmp_path):
    # framewall present but emitting no readable verdict (a scan error, a crash,
    # an unscannable image) must NOT silently allow the read - that's the whole
    # bypass this guard closes. Default to ask.
    stub = _stub(tmp_path, "print('tesseract exploded, not json', file=sys.stderr)")
    code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub)
    assert code == 0
    decision = _decision(out)
    assert decision["permissionDecision"] == "ask"
    assert "NOT scanned (tesseract exploded, not json" in decision["permissionDecisionReason"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_no_verdict_denies_when_fail_closed(entry, monkeypatch, tmp_path):
    # Opt-in strict mode turns the same no-verdict outcome into a hard block.
    stub = _stub(tmp_path, "print('boom', file=sys.stderr)")
    code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub, fail="closed")
    assert code == 0
    assert _decision(out)["permissionDecision"] == "deny"


DEGRADED_CLEAN = {
    "no-ocr": {"images": [{"verdict": "clean", "ocr_used": False,
                           "ocr_skipped_reason": "tesseract not found on PATH", "notes": []}]},
    "partial": {"images": [{"verdict": "clean", "ocr_used": True, "notes": [
        "3 candidate region(s) beyond the 24-region OCR cap went unread; the scan is partial"]}]},
}


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("case", sorted(DEGRADED_CLEAN))
def test_degraded_clean_scan_is_allowed_but_shown_to_the_user(entry, case, monkeypatch, tmp_path):
    # Exit 0 stderr never reaches the user from a PreToolUse hook; a
    # systemMessage does. No permission decision, so the read goes ahead.
    stub = _printing(tmp_path, DEGRADED_CLEAN[case])
    code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub)
    assert code == 0
    message = json.loads(out)
    assert "hookSpecificOutput" not in message
    assert "incomplete" in message["systemMessage"]
    assert ("tesseract not found" if case == "no-ocr" else "partial") in message["systemMessage"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("case", sorted(DEGRADED_CLEAN))
def test_degraded_clean_scan_asks_when_fail_closed(entry, case, monkeypatch, tmp_path):
    stub = _printing(tmp_path, DEGRADED_CLEAN[case])
    code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub, fail="closed")
    assert code == 0
    decision = _decision(out)
    assert decision["permissionDecision"] == "ask"
    assert "incomplete" in decision["permissionDecisionReason"]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_full_clean_scan_stays_silent(entry, monkeypatch, tmp_path):
    stub = _printing(tmp_path, {"images": [{"verdict": "clean", "ocr_used": True, "notes": []}]})
    code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub)
    assert (code, out.strip()) == (0, "")


CASES = {
    "dangerous": ({"images": [{"verdict": "dangerous"}]}, None),
    "suspicious": ({"images": [{"verdict": "suspicious"}]}, None),
    "clean": ({"images": [{"verdict": "clean", "ocr_used": True, "notes": []}]}, None),
    "no-ocr": (DEGRADED_CLEAN["no-ocr"], None),
    "no-ocr-closed": (DEGRADED_CLEAN["no-ocr"], "closed"),
    "partial": (DEGRADED_CLEAN["partial"], None),
    "garbage": ("not json", None),
    "garbage-closed": ("not json", "closed"),
}


@POSIX_ONLY
@pytest.mark.parametrize("case", sorted(CASES))
def test_both_entry_points_print_the_same_thing(case, monkeypatch, tmp_path):
    report, fail = CASES[case]
    stub = _printing(tmp_path, report) if isinstance(report, dict) else _stub(tmp_path, f"print({report!r})")
    img = _image(tmp_path)
    sh = run("sh", _read(img), monkeypatch, stub=stub, fail=fail)
    py = run("py", _read(img), monkeypatch, stub=stub, fail=fail)
    assert sh == py


# --- timeouts and a missing install -------------------------------------------


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_a_scan_that_times_out_runs_once(entry, monkeypatch, tmp_path):
    # The guard used to re-run a scan that printed nothing via python3 -m
    # framewall, so a timed-out scan cost two full timeouts. Every way it
    # could run framewall is stubbed to log and hang; only one may run. The
    # limit is cut to 1 s so the test doesn't wait out the real one.
    if entry == "sh" and shutil.which("timeout") is None:
        pytest.skip("no timeout(1) to cut the scan off")
    log = tmp_path / "calls.log"
    stub = _stub(tmp_path, f"open({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\ntime.sleep(10)")
    pkg = tmp_path / "cwd" / "framewall"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(
        f"import sys, time\nopen({str(log)!r}, 'a').write('module ' + ' '.join(sys.argv[1:]) + '\\n')\ntime.sleep(10)\n"
    )
    if entry == "sh":
        shim = stub.parent / "timeout"
        shim.write_text(f'#!/usr/bin/env bash\nshift\nexec "{shutil.which("timeout")}" 1 "$@"\n')
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(guard, "GUARD_SECONDS", 1)
    _code, out = run(entry, _read(_image(tmp_path)), monkeypatch, stub=stub, cwd=pkg.parent)
    calls = log.read_text().splitlines()
    assert len(calls) == 1, calls
    args = calls[0].split()
    limit = float(args[args.index("--max-scan-seconds") + 1])
    assert 0 < limit < 30
    decision = _decision(out)
    assert decision["permissionDecision"] == "ask"
    assert "did not finish" in decision["permissionDecisionReason"]


@POSIX_ONLY
def test_missing_framewall_is_shown_to_the_user(tmp_path, monkeypatch):
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
    env = dict(os.environ, PATH=str(bindir), PYTHONPATH=str(shadow.parent))
    r = subprocess.run(
        [str(HOOK)], input=json.dumps(_read(_image(tmp_path))), capture_output=True,
        text=True, env=env, cwd=tmp_path,
    )
    assert r.returncode == 0
    message = json.loads(r.stdout)
    assert "hookSpecificOutput" not in message
    assert "not installed" in message["systemMessage"]


def test_framewall_guard_runs_from_the_cli(monkeypatch, tmp_path):
    # The subcommand end to end in a child process, the way Claude Code runs it.
    env = dict(os.environ, PYTHONPATH=str(REPO))
    env.pop("FRAMEWALL_GUARD_FAIL", None)
    r = subprocess.run(
        [sys.executable, "-m", "framewall", "guard"], input=json.dumps(_read(POISONED)),
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert _decision(r.stdout)["permissionDecision"] == "deny"
