"""Turn findings into a three-tier verdict.

There is no partial credit: the verdict is the worst severity among an
image's findings, full stop. One HIGH finding sitting next to nine clean
checks is still DANGEROUS - an agent that acts on the one instruction it
found doesn't care how clean the rest of the image was.
"""

from __future__ import annotations

import enum

from .finding import Severity


class Verdict(str, enum.Enum):
    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"

    @classmethod
    def parse(cls, name: str) -> "Verdict":
        try:
            return cls(name.strip().lower())
        except ValueError:
            raise ValueError(f"unknown verdict: {name!r}") from None


_ORDER = [Verdict.CLEAN, Verdict.SUSPICIOUS, Verdict.DANGEROUS]


def rank(v: Verdict) -> int:
    return _ORDER.index(v)


def compute(findings) -> Verdict:
    worst = max((f.severity for f in findings), default=None)
    if worst is None or worst < Severity.MEDIUM:
        return Verdict.CLEAN
    if worst >= Severity.HIGH:
        return Verdict.DANGEROUS
    return Verdict.SUSPICIOUS
