"""Render scan results as human text, JSON, or SARIF."""

from __future__ import annotations

import json

from . import __version__
from .finding import Severity
from .ocr import tesseract_path

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
        lines.append(f"  framewall  {r.path}")
        if r.error:
            lines.append(c("\033[1;31m", f"  ERROR  {r.error}"))
            continue

        ocr_note = "used" if r.ocr_used else f"skipped ({r.ocr_skipped_reason})"
        lines.append(f"  {r.width}x{r.height}px   OCR: {ocr_note}")
        lines.append("")

        if not r.findings:
            lines.append(c("\033[32m", "  No findings. Nothing suspicious surfaced."))
        for f in r.findings:
            tag = c(_COLOR[f.severity], f" {f.severity.label.upper():^8} ")
            loc = f"  @ {f.region}" if f.region else ""
            lines.append(f"  {tag} {f.title}  [{f.rule_id}]{loc}")
            lines.append(f"           {f.detail}")
            if f.snippet:
                lines.append(c("\033[90m", f"           > {f.snippet}"))
            if f.remediation:
                lines.append(c("\033[90m", f"           fix: {f.remediation}"))
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


def render_json(results) -> str:
    payload = {
        "tool": "framewall",
        "version": __version__,
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


def render_sarif(results) -> str:
    rule_ids = sorted({f.rule_id for r in results for f in r.findings})
    rules = [{"id": rid, "name": rid} for rid in rule_ids]

    sarif_results = []
    for r in results:
        if r.error:
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
                    "locations": [
                        {"physicalLocation": {"artifactLocation": {"uri": r.path}}}
                    ],
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
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(doc, indent=2)
