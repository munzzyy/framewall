"""`framewall guard`: the Claude Code PreToolUse hook, shipped in the package.

Registered on the Read tool, it reads the hook's JSON on stdin, scans the
image the agent is about to open, and prints the hook decision: deny on
DANGEROUS, ask on SUSPICIOUS, ask when no verdict came back. A CLEAN verdict
from a scan that skipped OCR or stopped early is allowed with a systemMessage
saying so, or asked about under FRAMEWALL_GUARD_FAIL=closed. Anything that
isn't an image passes straight through. It behaves exactly like
hooks/framewall-guard.sh, without needing a checkout or bash.

The scan runs as a child process so a hung decoder can be killed, the same
way the shell guard wraps it in timeout(1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from .targets import IMAGE_EXTS

GUARD_SECONDS = 30
SCAN_SECONDS = 20  # framewall's own budget, inside GUARD_SECONDS so a heavy
# image ends as a partial scan with a verdict rather than a kill


def _scan_command(path: str, seconds: int) -> list:
    return [sys.executable, "-m", "framewall", "scan", "--json",
            "--max-scan-seconds", str(seconds), "--", path]


def _requested_path(raw: str) -> str:
    try:
        path = (json.loads(raw).get("tool_input") or {}).get("file_path", "")
    except Exception:
        return ""
    return path if isinstance(path, str) else ""


def _first_image(out: str) -> dict:
    try:
        image = (json.loads(out).get("images") or [{}])[0]
    except Exception:
        return {}
    return image if isinstance(image, dict) else {}


def _gaps(image: dict) -> str:
    """Why a verdict came from an incomplete scan, or "" for a full one."""
    gaps = []
    if image.get("verdict") and not image.get("ocr_used"):
        gaps.append("OCR did not run: %s" % (image.get("ocr_skipped_reason") or "unknown reason"))
    gaps.extend(str(n) for n in image.get("notes") or [])
    return " ".join("; ".join(gaps).split())[:400]


def _decision(kind: str, reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": kind,
        "permissionDecisionReason": reason,
    }}


def decide(path: str, out: str, err: str, timed_out: bool):
    """The hook output for one scan, or None to allow the read silently."""
    image = _first_image(out)
    verdict = image.get("verdict") or ""
    fail_closed = os.environ.get("FRAMEWALL_GUARD_FAIL", "") == "closed"
    if verdict == "dangerous":
        return _decision("deny", (
            "framewall flagged this image as DANGEROUS - it looks like a prompt-injection "
            "payload aimed at you, not the person. Read blocked. "
            f'Run: framewall scan "{path}"'
        ))
    if verdict == "suspicious":
        return _decision("ask", (
            "framewall flagged this image as SUSPICIOUS - possible hidden instructions, "
            "though its shape heuristics also fire on ordinary busy UI. Confirm before "
            f'reading. Run: framewall scan "{path}"'
        ))
    if verdict == "clean":
        degraded = _gaps(image)
        if not degraded:
            return None
        why = f"framewall found nothing, but the scan was incomplete ({degraded})"
        if fail_closed:
            return _decision("ask", f"{why}. Confirm before reading (FRAMEWALL_GUARD_FAIL=closed). Run: framewall doctor")
        return {"systemMessage": f"framewall-guard: {why}. Read allowed. Run: framewall doctor"}

    # No verdict: the scan errored, timed out, or the image was unscannable.
    # Every one of those is something the sender controls, so it is never a
    # silent allow.
    note = (err or "").replace("\n", " ")[:300]
    if timed_out and not out:
        note = f"the scan did not finish within {GUARD_SECONDS}s"
    why = "framewall could not produce a verdict for this image, so it was NOT scanned"
    if note:
        why = f"{why} ({note})"
    if fail_closed:
        return _decision("deny", f'{why}. Read blocked (FRAMEWALL_GUARD_FAIL=closed). Run: framewall scan "{path}"')
    return _decision("ask", f'{why}. Confirm before reading, or scan it yourself: framewall scan "{path}"')


def main(stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    path = _requested_path(stdin.read())
    if not path.lower().endswith(tuple(IMAGE_EXTS)):
        return 0
    if not os.path.isfile(path):
        return 0  # let Read report a missing file itself

    try:
        proc = subprocess.run(
            _scan_command(path, SCAN_SECONDS),
            capture_output=True, text=True, errors="replace",
            timeout=GUARD_SECONDS, check=False,
        )
        out, err, timed_out = proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired:
        out, err, timed_out = "", "", True
    except OSError as e:
        out, err, timed_out = "", str(e), False

    result = decide(path, out, err, timed_out)
    if result is not None:
        print(json.dumps(result), file=stdout)
    return 0
