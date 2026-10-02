#!/usr/bin/env bash
# framewall PreToolUse guard for Claude Code. `framewall guard` does the same
# from any install; this script is for setups that already point at it.
#
# Registered on the Read tool, this scans an image before the agent reads it
# and blocks the read when framewall thinks the picture is carrying an
# instruction aimed at the agent. Reads of non-image files pass straight
# through. If framewall isn't installed, or the scan ran without OCR or
# stopped early, the read is allowed (a guard that hard-fails every image read
# the moment tesseract or the package is missing is worse than no guard) but
# the user sees a systemMessage saying so. Claude Code shows nothing a
# PreToolUse hook writes to stderr when it exits 0.
#
# Register it in settings.json:
#   "hooks": {
#     "PreToolUse": [
#       { "matcher": "Read",
#         "hooks": [ { "type": "command",
#                      "command": "/absolute/path/to/framewall-guard.sh",
#                      "timeout": 60 } ] }
#     ]
#   }

set -uo pipefail

input="$(cat)"

# The path the Read tool is about to open.
file="$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))
except Exception:
    print("")' 2>/dev/null)"

# Only images are worth scanning; everything else is none of this hook's business.
# Lowercase with tr, not bash 4's case-changing parameter expansion - macOS
# ships bash 3.2, where it breaks the match and lets a non-image reach the
# scanner.
case "$(printf '%s' "$file" | tr '[:upper:]' '[:lower:]')" in
  *.png|*.jpg|*.jpeg|*.gif|*.bmp|*.webp|*.tif|*.tiff) ;;
  *) exit 0 ;;
esac

[ -f "$file" ] || exit 0   # let Read report a missing file itself

emit() {  # $1 = deny|ask, $2 = reason
  python3 -c 'import json,sys
print(json.dumps({"hookSpecificOutput":{
    "hookEventName":"PreToolUse",
    "permissionDecision":sys.argv[1],
    "permissionDecisionReason":sys.argv[2]}}))' "$1" "$2"
}

tell_user() {  # allow the read, but show $1 to the user
  python3 -c 'import json,sys
print(json.dumps({"systemMessage":sys.argv[1]}))' "$1"
}

if command -v framewall >/dev/null 2>&1; then
  scanner="framewall"
elif python3 -c 'import framewall' >/dev/null 2>&1; then
  scanner="python3 -m framewall"
else
  tell_user "framewall-guard: framewall is not installed, so this image was NOT scanned ($file)"
  exit 0
fi

# A crafted image must not hang the guard: cap the scan's wall clock.
# framewall's own --max-scan-seconds sits inside this limit, so a heavy image
# ends as a partial scan with a verdict; this layer covers a framewall that
# never returns at all. GNU timeout exits 124 on expiry leaving $out empty,
# which lands in the no-verdict branch below - ask, or deny under
# FRAMEWALL_GUARD_FAIL=closed - so a hung scan degrades loudly instead of
# blocking the agent forever. macOS ships no timeout(1) by default; the scan
# runs unwrapped there and framewall's own ceiling is the bound.
guard_seconds=30
scan_seconds=20
if command -v timeout >/dev/null 2>&1; then
  run_scan() { timeout "$guard_seconds" "$@"; }
else
  run_scan() { "$@"; }
fi

# Keep the scan's own stderr so a failure can be reported instead of swallowed.
scan_err="$(mktemp)"
# $scanner is unquoted on purpose: "python3 -m framewall" is three words.
# shellcheck disable=SC2086
out="$(run_scan $scanner scan --json --max-scan-seconds "$scan_seconds" -- "$file" 2>"$scan_err")"
scan_status=$?
reason_note="$(tr '\n' ' ' <"$scan_err" | cut -c1-300)"
rm -f "$scan_err"
if [ "$scan_status" -eq 124 ] && [ -z "$out" ]; then
  reason_note="the scan did not finish within ${guard_seconds}s"
fi

# Two lines out: the verdict, then why the scan was incomplete (empty if not).
parsed="$(printf '%s' "$out" | python3 -c 'import json,sys
try:
    image = (json.load(sys.stdin).get("images") or [{}])[0]
except Exception:
    image = {}
gaps = []
if image.get("verdict") and not image.get("ocr_used"):
    gaps.append("OCR did not run: %s" % (image.get("ocr_skipped_reason") or "unknown reason"))
gaps.extend(str(n) for n in image.get("notes") or [])
print(image.get("verdict") or "")
print(" ".join("; ".join(gaps).split())[:400])' 2>/dev/null)"
verdict="$(printf '%s\n' "$parsed" | sed -n 1p)"
degraded="$(printf '%s\n' "$parsed" | sed -n 2p)"

case "$verdict" in
  dangerous)
    emit deny "framewall flagged this image as DANGEROUS - it looks like a prompt-injection payload aimed at you, not the person. Read blocked. Run: framewall scan \"$file\""
    ;;
  suspicious)
    emit ask "framewall flagged this image as SUSPICIOUS - possible hidden instructions, though its shape heuristics also fire on ordinary busy UI. Confirm before reading. Run: framewall scan \"$file\""
    ;;
  clean)
    [ -z "$degraded" ] && exit 0
    # A clean verdict from a scan that skipped OCR or stopped early isn't a full one.
    why="framewall found nothing, but the scan was incomplete ($degraded)"
    if [ "${FRAMEWALL_GUARD_FAIL:-}" = "closed" ]; then
      emit ask "$why. Confirm before reading (FRAMEWALL_GUARD_FAIL=closed). Run: framewall doctor"
    else
      tell_user "framewall-guard: $why. Read allowed. Run: framewall doctor"
    fi
    ;;
  *)
    # framewall is installed (checked above) but produced no verdict for this
    # image: it errored, timed out, or the image was unscannable (oversize,
    # corrupt, a hostile metadata chunk). File size, name, and metadata are all
    # sender-controlled, so silently allowing an unscanned image is the exact
    # bypass this guard exists to close. Ask by default; set
    # FRAMEWALL_GUARD_FAIL=closed to deny instead.
    why="framewall could not produce a verdict for this image, so it was NOT scanned"
    [ -n "$reason_note" ] && why="$why ($reason_note)"
    if [ "${FRAMEWALL_GUARD_FAIL:-}" = "closed" ]; then
      emit deny "$why. Read blocked (FRAMEWALL_GUARD_FAIL=closed). Run: framewall scan \"$file\""
    else
      emit ask "$why. Confirm before reading, or scan it yourself: framewall scan \"$file\""
    fi
    ;;
esac
