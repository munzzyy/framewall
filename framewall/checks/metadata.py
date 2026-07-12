"""Metadata / steganography-lite (Pillow only, no OCR needed).

PNG tEXt/zTXt/iTXt chunks, JPEG comment segments, and EXIF text fields are a
cheap, real channel for smuggling instructions into an image: a human never
opens "image properties" before pasting a screenshot into an agent, but
Pillow (and plenty of vision pipelines that read metadata for orientation or
captions) sees every byte of it. Pillow surfaces all of this through
`Image.info` and `Image.getexif()` without any extra dependency.
"""

from __future__ import annotations

from PIL import ExifTags

from . import patterns
from ..finding import Finding, Severity

RULE_ID = "FW-005"

# Keys Pillow populates for ordinary, non-textual image plumbing. Skipped so
# a ten-line JFIF/ICC blob doesn't get reported as "unexpected text".
_BENIGN_KEYS = {
    "dpi", "jfif", "jfif_version", "jfif_unit", "jfif_density",
    "icc_profile", "exif", "transparency", "gamma", "srgb", "chromaticity",
    "photoshop", "adobe", "progressive", "progression", "loop", "duration",
    "background", "version", "aspect", "interlace", "software",
}
_MIN_TEXT_LEN = 8


def _decode(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return value.decode("utf-16-le" if b"\x00" in value else "latin-1")
            except (UnicodeDecodeError, LookupError):
                return None
    return value


def _text_fields(image) -> dict:
    fields = {}
    for key, raw in (image.info or {}).items():
        if key.lower() in _BENIGN_KEYS:
            continue
        value = _decode(raw)
        if isinstance(value, str) and len(value.strip()) >= _MIN_TEXT_LEN:
            fields[f"png:{key}"] = value.strip()

    try:
        exif = dict(image.getexif())
    except Exception:
        exif = {}
    for tag_id, raw in exif.items():
        tag = ExifTags.TAGS.get(tag_id, str(tag_id))
        value = _decode(raw)
        if value is None:
            continue
        value = str(value).strip().strip("\x00").strip()
        if len(value) >= _MIN_TEXT_LEN:
            fields[f"exif:{tag}"] = value
    return fields


def find(image) -> list:
    findings = []
    for field_name, text in _text_fields(image).items():
        hits = patterns.scan_text(text)
        if hits:
            for title, detail, _span, matched in hits:
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        layer="metadata",
                        severity=Severity.HIGH,
                        title=f"Injection text in image metadata ({field_name})",
                        detail=detail,
                        snippet=matched[:200],
                        remediation="Strip metadata before this image reaches an agent.",
                    )
                )
        else:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    layer="metadata",
                    severity=Severity.MEDIUM,
                    title=f"Unexpected embedded text in image metadata ({field_name})",
                    detail=(
                        "A metadata field carries free text a screenshot has no "
                        "ordinary reason to include. Not proven malicious, but it's "
                        "a real, cheap channel for smuggling text past a human who "
                        "never opens image properties."
                    ),
                    snippet=text[:200],
                    remediation="Confirm this metadata is expected for this image's source, or strip it.",
                )
            )
    return findings
