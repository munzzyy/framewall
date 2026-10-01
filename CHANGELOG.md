# Changelog

## 0.2.0 - unreleased

Not tagged yet. Installing from main gets this version.

### Added

- FW-006 flags high-frequency two-tone camouflage, a checkerboard or stripe
  field that text is stamped into so OCR cannot binarize it.
- Two recovery passes run when nothing else matched: one reads text a shade
  off its background, the other re-reads off-axis text counter-rotated. Thin
  strips too small for plain OCR are read again upscaled. With FW-006 that is
  7 of the 8 [injection-fixtures](https://github.com/munzzyy/injection-fixtures)
  0.1.0 techniques caught. framewall 0.1.0 catches 3 of 8 on the same corpus.
- `--lang` (and `FRAMEWALL_TESSERACT_LANG`), `--timeout` and
  `--max-scan-seconds`. Each image gets one time budget for all its OCR passes
  and frames. Flagged regions are merged and capped. Anything cut short shows
  up as a note saying the scan is partial.
- `framewall doctor` checks whether tesseract can read text in the language
  a scan would use. When it cannot, it names the package to install.
- `--require-ocr` exits 2 when any image was scanned without OCR or only in
  part, so CI cannot stay green with the core detector off.
- SARIF output lists images scanned without OCR or only in part under
  `toolExecutionNotifications`, and `--quiet` marks them `(no OCR)` or
  `(partial)`.

### Changed

- License is GPL-3.0-or-later. 0.1.0 and earlier were MIT.
- A clean result says what it rules out ("No text-shaped injection found")
  instead of reading as "safe".
- The Claude Code hook tells you when it allows a read whose scan skipped OCR
  or stopped early, and asks instead under `FRAMEWALL_GUARD_FAIL=closed`. It
  runs the scan once, with framewall's own budget inside its timeout.
- ImageMagick's date stamps, PNG's "Creation Time" and an XMP packet no
  longer make an image SUSPICIOUS on their own. They are still checked for
  injection text.
- FW-002 and FW-004 are much faster on large images.
- SARIF file locations are relative to the working directory.
- `--fail-on clean` is rejected as a usage error. It used to fail every scan.

### Fixed

- An OCR pass that fails or times out on any frame marks the scan as
  incomplete. It no longer reads as an image with no text.
- Hostile PNG metadata can no longer make the scan error out.
- Finding titles, details and `--quiet` paths are escaped the same way
  snippets are. A crafted key or file name cannot add lines to the report.

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
