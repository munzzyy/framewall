"""Core types: severities, findings, and per-image results."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class Severity(enum.IntEnum):
    """Ordered so comparisons and sorting work (higher = worse)."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, name: str) -> "Severity":
        try:
            return cls[name.strip().upper()]
        except KeyError:
            raise ValueError(f"unknown severity: {name!r}") from None


@dataclass(frozen=True)
class Region:
    """A pixel bounding box, top-left origin, used to point at where in the
    image a finding came from. Coordinates are in the original image's
    pixel space, even for findings recovered from a cropped/upscaled pass."""

    left: int
    top: int
    width: int
    height: int

    def __str__(self) -> str:
        return f"({self.left},{self.top}) {self.width}x{self.height}px"

    def as_dict(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Finding:
    rule_id: str  # FW-001..FW-005
    layer: str  # short slug, e.g. "injection-text"
    severity: Severity
    title: str
    detail: str
    region: Optional[Region] = None
    snippet: str = ""
    remediation: str = ""

    def sort_key(self):
        # Worst first, then stable by rule and title.
        return (-int(self.severity), self.rule_id, self.title)


@dataclass
class ImageResult:
    path: str
    width: int = 0
    height: int = 0
    findings: list = field(default_factory=list)
    ocr_used: bool = False
    ocr_skipped_reason: str = ""
    error: str = ""
    verdict: str = "clean"  # a verdict.Verdict value, set by the scanner

    def counts(self) -> dict:
        out = {s: 0 for s in Severity}
        for f in self.findings:
            out[f.severity] += 1
        return out
