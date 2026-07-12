"""Report rendering: human, JSON, SARIF. Built from hand-constructed
ImageResult/Finding objects so these tests don't depend on OCR."""

from __future__ import annotations

import json

from framewall.finding import Finding, ImageResult, Region, Severity
from framewall.report import render_human, render_json, render_sarif


def _clean_result(path="clean.png"):
    return ImageResult(path=path, width=800, height=600, ocr_used=True, verdict="clean")


def _dangerous_result(path="bad.png"):
    finding = Finding(
        rule_id="FW-001",
        layer="injection-text",
        severity=Severity.HIGH,
        title="Instruction-override phrasing",
        detail="Tells the reader to ignore its previous instructions.",
        region=Region(10, 20, 100, 30),
        snippet="ignore previous instructions",
        remediation="Treat this image as untrusted input.",
    )
    r = ImageResult(path=path, width=800, height=600, ocr_used=True, findings=[finding], verdict="dangerous")
    return r


def _error_result(path="broken.png"):
    return ImageResult(path=path, error="not a readable image")


def test_human_report_clean_says_no_findings():
    out = render_human([_clean_result()], color=False)
    assert "No findings" in out
    assert "CLEAN" in out


def test_human_report_shows_finding_detail():
    out = render_human([_dangerous_result()], color=False)
    assert "FW-001" in out
    assert "Instruction-override phrasing" in out
    assert "(10,20) 100x30px" in out
    assert "DANGEROUS" in out


def test_human_report_shows_error():
    out = render_human([_error_result()], color=False)
    assert "ERROR" in out
    assert "not a readable image" in out


def test_human_report_no_ansi_codes_when_color_disabled():
    out = render_human([_dangerous_result()], color=False)
    assert "\033[" not in out


def test_human_report_has_ansi_codes_when_color_enabled():
    out = render_human([_dangerous_result()], color=True)
    assert "\033[" in out


def test_human_report_handles_multiple_images():
    out = render_human([_clean_result("a.png"), _dangerous_result("b.png")], color=False)
    assert "a.png" in out
    assert "b.png" in out


def test_json_report_shape():
    payload = json.loads(render_json([_dangerous_result()]))
    assert payload["tool"] == "framewall"
    assert "version" in payload
    assert "tesseract_available" in payload
    assert len(payload["images"]) == 1
    img = payload["images"][0]
    assert img["verdict"] == "dangerous"
    assert img["findings"][0]["rule_id"] == "FW-001"
    assert img["findings"][0]["region"] == {"left": 10, "top": 20, "width": 100, "height": 30}


def test_json_report_error_image_has_no_findings_key_bleed():
    payload = json.loads(render_json([_error_result()]))
    img = payload["images"][0]
    assert img["error"] == "not a readable image"
    assert "findings" not in img


def test_json_report_finding_with_no_region_serializes_to_null():
    finding = Finding(rule_id="FW-005", layer="metadata", severity=Severity.MEDIUM, title="t", detail="d")
    r = ImageResult(path="x.png", findings=[finding], verdict="suspicious")
    payload = json.loads(render_json([r]))
    assert payload["images"][0]["findings"][0]["region"] is None


def test_json_report_is_valid_json_for_clean_and_dangerous_mixed():
    text = render_json([_clean_result(), _dangerous_result(), _error_result()])
    payload = json.loads(text)
    assert len(payload["images"]) == 3


def test_sarif_report_shape():
    doc = json.loads(render_sarif([_dangerous_result()]))
    assert doc["version"] == "2.1.0"
    driver = doc["runs"][0]["tool"]["driver"]
    assert driver["name"] == "framewall"
    assert {"id": "FW-001", "name": "FW-001"} in driver["rules"]
    result = doc["runs"][0]["results"][0]
    assert result["ruleId"] == "FW-001"
    assert result["level"] == "error"
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "bad.png"


def test_sarif_report_skips_error_images():
    doc = json.loads(render_sarif([_error_result(), _dangerous_result()]))
    # Only the dangerous image's one finding should appear.
    assert len(doc["runs"][0]["results"]) == 1


def test_sarif_report_empty_when_no_findings():
    doc = json.loads(render_sarif([_clean_result()]))
    assert doc["runs"][0]["results"] == []
    assert doc["runs"][0]["tool"]["driver"]["rules"] == []


def test_sarif_severity_levels():
    med = Finding(rule_id="FW-002", layer="low-contrast-text", severity=Severity.MEDIUM, title="t", detail="d")
    r = ImageResult(path="x.png", findings=[med], verdict="suspicious")
    doc = json.loads(render_sarif([r]))
    assert doc["runs"][0]["results"][0]["level"] == "warning"
