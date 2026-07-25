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

# EXIF sub-directories the text-bearing tags actually live in. Image.getexif()
# only returns IFD0; UserComment (0x9286) sits in the Exif sub-IFD behind the
# 0x8769 pointer, so reading IFD0 alone silently misses the standard JPEG
# comment field.
_EXIF_SUBIFDS = (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo, ExifTags.IFD.Interop)

# UserComment (and a couple of other Exif fields) prefix the text with an
# 8-byte character-code so the reader knows the encoding. Strip it before
# scanning, or the payload never matches.
_USERCOMMENT_CODES = {
    b"ASCII\x00\x00\x00": "ascii",
    b"UNICODE\x00": "utf-16",
    b"JIS\x00\x00\x00\x00\x00": "shift_jis",
    b"\x00\x00\x00\x00\x00\x00\x00\x00": "latin-1",
}


def _utf16_encoding(data: bytes):
    """Return the UTF-16 variant `data` is in, or None. A BOM is decisive;
    failing that, a run of NUL bytes at alternating offsets is the fingerprint
    of ASCII-range text encoded as UTF-16 (which is also valid UTF-8, so it has
    to be caught before the UTF-8 attempt or the interior NULs survive and
    break every pattern)."""
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if len(data) >= 4 and data.count(0) >= len(data) // 3:
        even_nuls = data[0::2].count(0)
        odd_nuls = data[1::2].count(0)
        if odd_nuls > even_nuls:
            return "utf-16-le"
        if even_nuls > odd_nuls:
            return "utf-16-be"
    return None


def _decode(value):
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        enc = _utf16_encoding(data)
        candidates = [enc] if enc else []
        candidates += ["utf-8", "latin-1"]
        for candidate in candidates:
            try:
                text = data.decode(candidate)
            except (UnicodeDecodeError, LookupError):
                continue
            # Drop any surviving NULs (interior ones defeat the regexes; an
            # odd-length or mis-detected UTF-16 string can leave some behind).
            return text.replace("\x00", "")
        return None
    return value


def _decode_usercomment(raw):
    """UserComment carries an 8-byte character-code prefix; strip it and decode
    the body with the encoding it names, then fall back to the generic path."""
    if isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
        for code, enc in _USERCOMMENT_CODES.items():
            if data.startswith(code):
                body = data[len(code):]
                try:
                    return body.decode(enc).replace("\x00", "")
                except (UnicodeDecodeError, LookupError):
                    return _decode(body)
    return _decode(raw)


def _exif_fields(image) -> dict:
    try:
        exif = image.getexif()
    except Exception:
        return {}
    # Keep each IFD separate. Sub-IFD tag_ids share the same small integer
    # space as IFD0 (a GPS tag 0x0001 and an IFD0 tag 0x0001 are different
    # fields), so merging every IFD into one tag_id-keyed dict lets a sub-IFD
    # value silently overwrite - and thereby hide from the scanner - a
    # colliding IFD0 value. Scan each IFD on its own so nothing is dropped
    # before it reaches scan_text.
    ifds = [(None, dict(exif))]
    for ifd_id in _EXIF_SUBIFDS:
        try:
            sub = exif.get_ifd(ifd_id)
        except Exception:
            continue
        if sub:
            ifds.append((ifd_id, dict(sub)))

    fields = {}
    for ifd_id, items in ifds:
        gps = ifd_id == ExifTags.IFD.GPSInfo
        for tag_id, value in items.items():
            if gps:
                tag = ExifTags.GPSTAGS.get(tag_id) or ExifTags.TAGS.get(tag_id) or str(tag_id)
            else:
                tag = ExifTags.TAGS.get(tag_id) or ExifTags.GPSTAGS.get(tag_id) or str(tag_id)
            decoded = _decode_usercomment(value) if tag == "UserComment" else _decode(value)
            if decoded is None:
                continue
            decoded = str(decoded).strip()
            if len(decoded) >= _MIN_TEXT_LEN:
                name = f"exif:{tag}"
                # Two IFDs can still resolve to the same tag name; keep both so
                # one can't erase the other before scanning.
                if name in fields and fields[name] != decoded:
                    name = f"{name}#{tag_id}"
                fields[name] = decoded
    return fields


def _text_fields(image):
    """Yield (field_name, text, benign_key) for every readable metadata value.

    Every value is scanned for injection phrasing regardless of its key - PNG
    tEXt keys and EXIF tags are attacker-chosen, so a payload hides just as
    easily under "Software" as under "Comment". benign_key only decides whether
    a *no-hit* value is worth reporting as unexpected text."""
    for key, raw in (image.info or {}).items():
        value = _decode(raw)
        if isinstance(value, str) and len(value.strip()) >= _MIN_TEXT_LEN:
            yield f"png:{key}", value.strip(), key.lower() in _BENIGN_KEYS

    for field_name, text in _exif_fields(image).items():
        tag = field_name.split(":", 1)[1]
        yield field_name, text, tag.lower() in _BENIGN_KEYS


def find(image) -> list:
    findings = []
    for field_name, text, benign_key in _text_fields(image):
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
        elif not benign_key:
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
