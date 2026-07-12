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
            # a determiner before any of the four nouns, OR no determiner before
            # the two that only ever mean the hidden prompt - so "output system
            # prompt" fires without an article, but a bare "show instructions"
            # (ordinary UI copy) still needs one.
            r"(?:(?:your|the)\s+(?:system\s+prompt|initial\s+instructions|instructions|prompt)"
            r"|(?:system\s+prompt|initial\s+instructions|system\s+message))\b",
            _I,
        ),
        "System-prompt disclosure attempt",
        "Tries to get the reader to reveal its system prompt or hidden instructions.",
    ),
    (
        re.compile(
            r"\bforget\s+(?:everything|all|your|the)\s+(?:previous\s+|prior\s+|above\s+)?"
            r"(?:instructions?|rules?|guidelines?|context|you\s+(?:were\s+)?told)",
            _I,
        ),
        "Instruction-reset phrasing",
        "Tells the reader to forget its prior instructions.",
    ),
    (
        re.compile(
            r"\bwithout\s+(?:telling|informing|notifying|asking|alerting)\s+(?:the\s+)?(?:user|them|him|her)\b",
            _I,
        ),
        "Act-without-consent directive",
        "Instructs the reader to act without informing or asking the user.",
    ),
    (
        re.compile(
            r"\bregardless\s+of\s+(?:what|any|whatever)\s+(?:the\s+user|instructions?|guidelines?|"
            r"rules?|you\s+(?:are|were)\s+told)",
            _I,
        ),
        "Guideline-bypass phrasing",
        "Tells the reader to act regardless of its instructions or the user's wishes.",
    ),
    (
        re.compile(
            r"\balways\s+(?:run|execute|use|call|invoke)\b[^\n.]*\bwithout\s+(?:asking|confirming|prompting|checking)",
            _I,
        ),
        "Silent tool-execution directive",
        "Tells the reader to always run something without asking.",
    ),
    (
        re.compile(
            r"\b(?:with\s+)?no\s+(?:safety|content|ethical|moral)\s+"
            r"(?:rules?|guidelines?|filters?|restrictions?|limits?|boundaries)\b",
            _I,
        ),
        "Safety-bypass phrasing",
        "Asserts the reader has no safety, content, or ethical rules - a jailbreak framing.",
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
