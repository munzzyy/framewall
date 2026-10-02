"""Render scan results as human text, JSON, or SARIF."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import __version__
from .finding import Severity
from .ocr import tesseract_path

# Snippets, titles and paths carry attacker-controlled bytes: a snippet is
# text OCR'd out of the scanned image or lifted from its metadata, an FW-005
# title names the metadata key the file chose, and a path is whatever the file
# was named. Printed raw to a terminal, an embedded ESC sequence would
# run - clearing the screen, recoloring, or forging report lines via a newline.
# Escape every C0/C1 control byte (including tab/newline/CR) plus the Unicode
# line/paragraph separators and directional-formatting characters - U+202E and
# friends visually reverse the rest of the line and U+2028/U+2029 break it in
# some viewers, both of which let a snippet forge report lines. Only the human
# and --quiet renderers need this; JSON and SARIF go through json.dumps, which
# already escapes control characters.
_CONTROL_RE = re.compile(
    "[\x00-\x1f\x7f-\x9f"
    "\u2028\u2029"  # line / paragraph separators
    "\u200e\u200f\u202a-\u202e\u2066-\u2069"  # bidi marks, overrides, isolates
    "\ufeff]"  # BOM / zero-width no-break space
)


def _safe(s) -> str:
    def esc(m):
        cp = ord(m.group())
        return f"\\x{cp:02x}" if cp <= 0xFF else f"\\u{cp:04x}"

    return _CONTROL_RE.sub(esc, str(s))


_COLOR = {
    Severity.HIGH: "\033[31m",
    Severity.MEDIUM: "\033[33m",
    Severity.LOW: "\033[36m",
}
_RESET = "\033[0m"
_VERDICT_COLOR = {
    "clean": "\033[32m",
    "suspicious": "\033[33m",
    "dangerous": "\033[1;31m",
}


def render_human(results, color: bool = True) -> str:
    def c(code, s):
        return f"{code}{s}{_RESET}" if color else s

    lines = []
    for r in results:
        lines.append("")
        lines.append(f"  framewall  {_safe(r.path)}")
        if r.error:
            lines.append(c("\033[1;31m", f"  ERROR  {_safe(r.error)}"))
            continue

        ocr_note = "used" if r.ocr_used else f"skipped ({_safe(r.ocr_skipped_reason)})"
        lines.append(f"  {r.width}x{r.height}px   OCR: {ocr_note}")
        for note in r.notes:
            lines.append(c("\033[33m", f"  note: {_safe(note)}"))
        lines.append("")

        if not r.findings:
            # Scoped on purpose: framewall looks for text and text-shaped
            # structure. "No findings" must not read as "this image is safe" -
            # a payload with no recoverable text (see the README's "What
            # framewall cannot see") returns exactly this.
            lines.append(
                c("\033[32m", "  No text-shaped injection found.")
                + " This scanner only sees text and text-like structure; it can't rule out payloads that contain neither."
            )
        for f in r.findings:
            tag = c(_COLOR[f.severity], f" {f.severity.label.upper():^8} ")
            loc = f"  @ {f.region}" if f.region else ""
            lines.append(f"  {tag} {_safe(f.title)}  [{f.rule_id}]{loc}")
            lines.append(f"           {_safe(f.detail)}")
            if f.snippet:
                lines.append(c("\033[90m", f"           > {_safe(f.snippet)}"))
            if f.remediation:
                lines.append(c("\033[90m", f"           fix: {_safe(f.remediation)}"))
            lines.append("")

        counts = r.counts()
        parts = [
            c(_COLOR[s], f"{counts[s]} {s.label}")
            for s in (Severity.HIGH, Severity.MEDIUM, Severity.LOW)
            if counts[s]
        ]
        summary = ", ".join(parts) if parts else "0 findings"
        vc = _VERDICT_COLOR.get(r.verdict, "")
        lines.append(f"  {summary}   verdict: {c(vc, r.verdict.upper())}")
    lines.append("")
    return "\n".join(lines)


def render_quiet(results) -> str:
    """One line per image. Scripts split this on lines, so a path holding a
    newline must not add one. A verdict from a degraded scan says so:
    "CLEAN (no OCR)  shot.png"."""
    return "\n".join(f"{_quiet_label(r)}  {_safe(r.path)}" for r in results)


def _quiet_label(r) -> str:
    if r.error:
        return "ERROR"
    gaps = []
    if not r.ocr_used:
        gaps.append("no OCR")
    if r.notes:
        gaps.append("partial")
    label = r.verdict.upper()
    return f"{label} ({', '.join(gaps)})" if gaps else label


def render_json(results) -> str:
    payload = {
        "tool": "framewall",
        "version": __version__,
        # The binary is on PATH, nothing more; each image's ocr_used says
        # whether OCR actually ran on it.
        "tesseract_available": tesseract_path() is not None,
        "images": [_image_payload(r) for r in results],
    }
    return json.dumps(payload, indent=2)


def _image_payload(r):
    if r.error:
        return {"path": r.path, "error": r.error}
    return {
        "path": r.path,
        "width": r.width,
        "height": r.height,
        "ocr_used": r.ocr_used,
        "ocr_skipped_reason": r.ocr_skipped_reason,
        "notes": list(r.notes),
        "verdict": r.verdict,
        "findings": [_finding_payload(f) for f in r.findings],
    }


def _finding_payload(f):
    return {
        "rule_id": f.rule_id,
        "layer": f.layer,
        "severity": f.severity.label,
        "title": f.title,
        "detail": f.detail,
        "region": f.region.as_dict() if f.region else None,
        "snippet": f.snippet,
        "remediation": f.remediation,
    }


_SARIF_LEVEL = {Severity.HIGH: "error", Severity.MEDIUM: "warning", Severity.LOW: "note"}
_SEC_SEVERITY = {Severity.HIGH: "8.0", Severity.MEDIUM: "5.0", Severity.LOW: "3.0"}
# An image framewall couldn't scan must show up in the report of record, not
# vanish from it: a security gate reading only the SARIF would otherwise treat
# an unreadable or oversized image as if it had passed. Surface each as an
# error-level result under this synthetic rule.
_SCAN_ERROR_RULE = "framewall-scan-error"
# A verdict from a degraded scan is still a verdict, so it isn't a result,
# but a reader of the SARIF alone has to be able to tell.
_OCR_SKIPPED = "framewall-ocr-skipped"
_PARTIAL_SCAN = "framewall-partial-scan"


def render_sarif(results) -> str:
    rule_ids = sorted({f.rule_id for r in results for f in r.findings})
    rules = [{"id": rid, "name": rid} for rid in rule_ids]
    if any(r.error for r in results):
        rules.append({"id": _SCAN_ERROR_RULE, "name": _SCAN_ERROR_RULE})

    sarif_results = []
    notifications = []
    for r in results:
        location = [{"physicalLocation": {"artifactLocation": {"uri": _sarif_uri(r.path)}}}]
        if not r.error and not r.ocr_used:
            notifications.append(_notification(
                _OCR_SKIPPED,
                f"OCR did not run on this image ({r.ocr_skipped_reason}), so the "
                f"injection-text check (FW-001) did not read it",
                location,
            ))
        if not r.error:
            for note in r.notes:
                notifications.append(_notification(_PARTIAL_SCAN, note, location))
        if r.error:
            sarif_results.append(
                {
                    "ruleId": _SCAN_ERROR_RULE,
                    "level": "error",
                    "message": {"text": f"framewall could not scan this image: {r.error}"},
                    "locations": location,
                }
            )
            continue
        for f in r.findings:
            props = {"security-severity": _SEC_SEVERITY[f.severity], "layer": f.layer}
            if f.region:
                props["region"] = f.region.as_dict()
            sarif_results.append(
                {
                    "ruleId": f.rule_id,
                    "level": _SARIF_LEVEL[f.severity],
                    "message": {"text": f"{f.title}: {f.detail}"},
                    "properties": props,
                    "locations": location,
                }
            )

    doc = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "framewall",
                        "informationUri": "https://github.com/munzzyy/framewall",
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "toolExecutionNotifications": notifications,
                    }
                ],
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(doc, indent=2)


def _sarif_uri(path) -> str:
    """Relative to the working directory when the file sits under it, which
    is how code scanning maps a result to a file in the repo. Otherwise a
    file:// URI, since a bare absolute path (or a Windows one) isn't one.
    An image that came in on stdin or as bytes has no file; its label loses
    the angle brackets, which a URI can't hold."""
    if path in ("<stdin>", "<bytes>"):
        return path[1:-1]
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return p.as_uri()


def _notification(rule_id, text, locations) -> dict:
    return {
        "descriptor": {"id": rule_id},
        "level": "warning",
        "message": {"text": text},
        "locations": locations,
    }
