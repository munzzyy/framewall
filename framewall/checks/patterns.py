"""The injection-pattern engine: text is scanned for imperative directives
aimed at an agent reading it, not at the human looking at the same pixels.
Shared by the OCR-recovered-text layer and the metadata layer - anywhere
framewall pulls text out of an image, it gets scanned the same way.

Patterns need an explicit object ("instructions", "the user", a URL) so
ordinary copy like "ignore the warning icon" or "system requirements" doesn't
trip them. They're deliberately narrow: a pattern that fires on ordinary
screenshot text is worse than one that misses an obfuscated attack, because
noise is what trains people to stop reading the report.
"""

from __future__ import annotations

import re

_I = re.IGNORECASE

# (compiled pattern, title, detail)
_MODIFIERS = r"(?:(?:all|any|the|your|previous|prior|above|earlier|preceding|foregoing|system)\s+){0,3}"

_PATTERNS = [
    (
        re.compile(
            r"\bignore\s+" + _MODIFIERS + r"(?:instructions?|prompts?|context|rules?|directions?|messages?)",
            _I,
        ),
        "Instruction-override phrasing",
        "Tells the reader to ignore its previous instructions, the standard prompt-injection opener.",
    ),
    (
        re.compile(
            r"\bdisregard\s+" + _MODIFIERS + r"(?:instructions?|prompts?|rules?|guidelines?|context)",
            _I,
        ),
        "Instruction-override phrasing",
        "Tells the reader to disregard its instructions or guidelines.",
    ),
    (
        re.compile(r"\byou\s+are\s+now\s+(?:a|an|in|the|no\s+longer)\b", _I),
        "Persona-override phrasing",
        "Attempts to redefine what the reader is, a common jailbreak opener.",
    ),
    (
        re.compile(
            r"^\s*(?:new|updated|real|actual|true)\s+"
            r"(?:instructions?|task|directive|system\s+prompt)\s*:",
            _I | re.MULTILINE,
        ),
        "Injected-instruction header",
        "Poses as a fresh set of instructions for the reader to follow instead.",
    ),
    (
        re.compile(r"^\s*system\s*:", _I | re.MULTILINE),
        "Fake system-role label",
        "Opens with a 'system:' label, imitating a system message the reader is meant to trust.",
    ),
    (
        re.compile(
            r"\bdo\s+not\s+(?:tell|inform|mention|alert|notify|warn|show)\s+(?:the\s+)?user\b",
            _I,
        ),
        "Hide-from-user directive",
        "Instructs the reader to conceal an action from the user.",
    ),
    (
        re.compile(
            r"\b(?:reveal|print|show|repeat|output|disclose|leak|dump)\s+"
            r"(?:your|the)\s+(?:system\s+prompt|initial\s+instructions|instructions|prompt)\b",
            _I,
        ),
        "System-prompt disclosure attempt",
        "Tries to get the reader to reveal its system prompt or hidden instructions.",
    ),
    (
        re.compile(
            r"\b(?:send|upload|forward|transmit|exfiltrate)\b\s+"
            r"(?:the\s+|this\s+|your\s+|all\s+|any\s+)?(?:user'?s?\s+)?"
            r"(?:data|information|details|credentials|files?|contents?|"
            r"screen(?:shot)?s?|clipboard|passwords?|sessions?|cookies|"
            r"everything|history|conversation)\b"
            r"[^\n.]{0,60}\bhttps?://",
            _I,
        ),
        "Exfiltration directive",
        "Pairs a send/upload verb, a sensitive-data noun, and a nearby URL - the shape of a data-exfiltration instruction.",
    ),
    (
        re.compile(r"<\s*tool[_-]?call\b|\"tool_call\"\s*:|\"function_call\"\s*:", _I),
        "Tool-call-looking string",
        "Formatted like a tool invocation; some agents will parse and act on text shaped like this.",
    ),
    (
        re.compile(
            r"\boverride\s+(?:your|the|all|any)\s+"
            r"(?:instructions?|guidelines?|rules?|safety|system\s+prompt|restrictions?)",
            _I,
        ),
        "Instruction-override phrasing",
        "Tells the reader to override its guidelines, safety rules, or system prompt.",
    ),
]


def scan_text(text: str):
    """Return [(title, detail, match_span, matched_text)] for every hit."""
    hits = []
    for rx, title, detail in _PATTERNS:
        for m in rx.finditer(text):
            hits.append((title, detail, m.span(), m.group(0)))
    return hits
