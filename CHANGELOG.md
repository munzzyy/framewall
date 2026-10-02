# Changelog

## 0.2.0 - unreleased

Not tagged yet. Installing from main gets this version.

### Added

- FW-006 flags high-frequency two-tone camouflage: a checkerboard or stripe
  field that text is stamped into so OCR cannot binarize it.
- Two recovery passes run when nothing else matched. One reads text a shade
  off its background and the other re-reads off-axis text counter-rotated. Thin
  strips too small for plain OCR are read again upscaled. With FW-006 that is
  7 of the 8 [injection-fixtures](https://github.com/munzzyy/injection-fixtures)
  0.1.0 techniques caught. framewall 0.1.0 catches 3 of 8 on the same corpus.
- `--lang` (and `FRAMEWALL_TESSERACT_LANG`), `--timeout` and
  `--max-scan-seconds`. Each image gets one time budget for all its OCR passes
  and frames. Flagged regions are merged and capped. Anything cut short shows
  up as a note saying the scan is partial.
- `framewall guard` is the Claude Code hook as a subcommand. It works from
  any install (Windows included) and behaves like `hooks/framewall-guard.sh`.
- `framewall doctor` checks whether tesseract can read text in the language
  a scan would use. When it cannot, it names the package to install.
- `--require-ocr` exits 2 when any image was scanned without OCR or only in
  part. CI cannot stay green with the core detector off.
- SARIF output lists images scanned without OCR or only in part under
  `toolExecutionNotifications`. `--quiet` marks them `(no OCR)` or
  `(partial)`.
- `framewall scan -` reads one image from stdin and `framewall.scan_bytes`
  scans one held in memory. Agent loops that never write their screenshots to
  disk can use either. Both go through the same caps and checks as a file.
  The README documents the Python API.

### Changed

- License is GPL-3.0-or-later. 0.1.0 and earlier were MIT.
- A clean result says what it rules out ("No text-shaped injection found")
  instead of reading as "safe".
- The Claude Code hook tells you when it allows a read whose scan skipped OCR
  or stopped early. It asks instead under `FRAMEWALL_GUARD_FAIL=closed`. It
  runs the scan once with framewall's own budget inside its timeout.
- ImageMagick's date stamps, PNG's "Creation Time" and an XMP packet no
  longer make an image SUSPICIOUS on their own. They are still checked for
  injection text.
- FW-002 and FW-004 are much faster on large images.
- FW-002 no longer flags straight borders, dividers and panel seams. A
  region needs a run of blocks that change both across and down, the way
  text does. On a set of real app screenshots that cut its regions by about
  a fifth.
- SARIF file locations are relative to the working directory.
- The published catch rate is measured on injection-fixtures 0.2.0 and split
  by verdict: 11 of 14 techniques flagged, 7 of them DANGEROUS. CI pins that
  corpus and holds both numbers as floors.
- `--fail-on clean` is rejected as a usage error. It used to fail every scan.

### Fixed

- An OCR pass that fails or times out on any frame marks the scan as
  incomplete. It no longer reads as an image with no text.
- Hostile PNG metadata can no longer make the scan error out.
- Finding titles, details and `--quiet` paths are escaped the same way
  snippets are. A crafted key or file name cannot add lines to the report.
- An image with an EXIF orientation tag is read the way a browser shows it
  and again as stored. Text stored sideways under the tag used to come back
  CLEAN. A recovery pass also reads text turned a quarter with no tag at all.
- Files are decoded only as one of the formats SECURITY.md lists. A file in
  any other format is refused whatever it is named. It no longer goes to
  whichever of Pillow's decoders matches its bytes.

## 0.1.0 - 2026-07-28

First tagged release, under MIT.

- Five checks: injection text read by OCR (FW-001), low-contrast text-shaped
  regions (FW-002), text below legible size (FW-003), fake system overlay
  boxes (FW-004) and injection text in PNG or EXIF metadata (FW-005).
- Human, `--json`, `--sarif` and `--quiet` output, and `--fail-on` for CI.
- Size caps on the file and the decoded image, and every frame of an
  animated GIF or multi-page TIFF up to 32.
- A tesseract with no language data is reported instead of scanning blind.
- `hooks/framewall-guard.sh`, a Claude Code `PreToolUse` hook that blocks a
  DANGEROUS image and asks on a SUSPICIOUS one.
