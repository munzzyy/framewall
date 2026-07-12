"""Verdict computation: worst severity wins, full stop."""

from __future__ import annotations

import pytest

from framewall.finding import Finding, Severity
from framewall.verdict import Verdict, compute, rank


def _finding(sev):
    return Finding(rule_id="FW-000", layer="test", severity=sev, title="t", detail="d")


def test_no_findings_is_clean():
    assert compute([]) == Verdict.CLEAN


def test_low_only_is_clean():
    assert compute([_finding(Severity.LOW)]) == Verdict.CLEAN


def test_medium_is_suspicious():
    assert compute([_finding(Severity.MEDIUM)]) == Verdict.SUSPICIOUS


def test_high_is_dangerous():
    assert compute([_finding(Severity.HIGH)]) == Verdict.DANGEROUS


def test_worst_severity_wins_even_with_many_low_findings():
    findings = [_finding(Severity.LOW)] * 10 + [_finding(Severity.HIGH)]
    assert compute(findings) == Verdict.DANGEROUS


def test_mixed_medium_and_low_is_suspicious_not_clean():
    findings = [_finding(Severity.LOW), _finding(Severity.MEDIUM)]
    assert compute(findings) == Verdict.SUSPICIOUS


def test_rank_orders_clean_below_suspicious_below_dangerous():
    assert rank(Verdict.CLEAN) < rank(Verdict.SUSPICIOUS) < rank(Verdict.DANGEROUS)


def test_verdict_parse_accepts_known_values():
    assert Verdict.parse("clean") == Verdict.CLEAN
    assert Verdict.parse("SUSPICIOUS") == Verdict.SUSPICIOUS
    assert Verdict.parse("  Dangerous  ") == Verdict.DANGEROUS


def test_verdict_parse_rejects_unknown_value():
    with pytest.raises(ValueError):
        Verdict.parse("catastrophic")


def test_severity_parse_and_label():
    assert Severity.parse("high") == Severity.HIGH
    assert Severity.HIGH.label == "high"
    with pytest.raises(ValueError):
        Severity.parse("critical")
