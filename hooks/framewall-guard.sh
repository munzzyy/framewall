#!/usr/bin/env bash
# framewall PreToolUse guard for Claude Code.
#
# Registered on the Read tool, this scans an image before the agent reads it
# and blocks the read when framewall thinks the picture is carrying an
# instruction aimed at the agent. Reads of non-image files pass straight
# through, and if framewall can't run for any reason the read is allowed (a
# guard that hard-fails every image read the moment tesseract or the package
# is missing is worse than no guard) with a note on stderr.
#
# Register it in settings.json:
#   "hooks": {
#     "PreToolUse": [
#       { "matcher": "Read",
#         "hooks": [ { "type": "command",
#                      "command": "/absolute/path/to/framewall-guard.sh" } ] }
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
case "${file,,}" in
  *.png|*.jpg|*.jpeg|*.gif|*.bmp|*.webp|*.tif|*.tiff) ;;
  *) exit 0 ;;
esac

[ -f "$file" ] || exit 0   # let Read report a missing file itself

if ! command -v framewall >/dev/null 2>&1 && ! python3 -c 'import framewall' >/dev/null 2>&1; then
  echo "framewall-guard: framewall is not installed, image not scanned ($file)" >&2
  exit 0
fi

# Keep the scan's own stderr so a failure can be reported instead of swallowed.
scan_err="$(mktemp)"
out="$(framewall scan "$file" --json 2>"$scan_err")"
[ -n "$out" ] || out="$(python3 -m framewall scan "$file" --json 2>"$scan_err")"
reason_note="$(tr '\n' ' ' <"$scan_err" | cut -c1-300)"
rm -f "$scan_err"

verdict="$(printf '%s' "$out" | python3 -c 'import json,sys
try:
    print(((json.load(sys.stdin).get("images") or [{}])[0]).get("verdict",""))
except Exception:
    print("")' 2>/dev/null)"

emit() {  # $1 = deny|ask, $2 = reason
  python3 -c 'import json,sys
print(json.dumps({"hookSpecificOutput":{
    "hookEventName":"PreToolUse",
    "permissionDecision":sys.argv[1],
    "permissionDecisionReason":sys.argv[2]}}))' "$1" "$2"
}

case "$verdict" in
  dangerous)
    emit deny "framewall flagged this image as DANGEROUS - it looks like a prompt-injection payload aimed at you, not the person. Read blocked. Run: framewall scan \"$file\""
    ;;
  suspicious)
    emit ask "framewall flagged this image as SUSPICIOUS - possible hidden instructions, though its shape heuristics also fire on ordinary busy UI. Confirm before reading. Run: framewall scan \"$file\""
    ;;
  clean)
    exit 0
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
