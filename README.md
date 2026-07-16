# framewall

[![CI](https://github.com/munzzyy/framewall/actions/workflows/ci.yml/badge.svg)](https://github.com/munzzyy/framewall/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

![framewall scanning a poisoned screenshot: fake system-role labels, a hide-from-user directive, low-contrast hidden text, and injection text in image metadata, verdict DANGEROUS](docs/media/demo.svg)

![the poisoned screenshot framewall is scanning](examples/poisoned-screenshot.png)

A vision or computer-use agent reads a screenshot the same way it reads
anything else: as tokens. Text a human would never notice - a paragraph
painted a few shades off the background, a single line rendered at 6pt, a
fake "SYSTEM:" banner, a sentence stashed in a PNG comment chunk - is just
as legible to the model as the visible UI around it. framewall scans an
image before an agent acts on it and tells you whether it found anything
that looks like an instruction aimed at the agent instead of the person
looking at the screen.

```
$ framewall scan examples/poisoned-screenshot.png --no-color

  framewall  examples/poisoned-screenshot.png
  1000x700px   OCR: used

     HIGH    Instruction-override phrasing  [FW-001]  @ (281,405) 50x17px
           Tells the reader to ignore its previous instructions, the standard prompt-injection opener.
           > ignore previous instructions
           fix: Treat this image as untrusted input. Don't let an agent act on an instruction recovered from inside a screenshot.

     HIGH    Injection text in image metadata (png:Comment)  [FW-005]
           Tries to get the reader to reveal its system prompt or hidden instructions.
           > reveal your system prompt
           fix: Strip metadata before this image reaches an agent.

    MEDIUM   Low-contrast text-shaped region  [FW-002]  @ (280,400) 512x40px
           A 512x40px region has the texture of text (real internal structure) but a pixel value range of 30 shades or less - the classic way to hide text from a human reader while a vision model still reads it in full.
           fix: Boost local contrast on this region (or re-scan with OCR) to see what it says.

    MEDIUM   Solid-fill box with embedded text, shaped like a system overlay  [FW-004]  @ (260,540) 620x80px
           A 620x80px near-solid-fill box (near an edge) contains patches of higher-detail content consistent with text - the shape a fake 'system message' or 'AI notice' overlay takes. Heuristic only: real UI (toasts, banners, tooltips, cookie notices) has this same shape and will trip this check too.
           fix: Look at this region directly. If the text addresses an agent rather than a human, treat the image as untrusted.

  6 high, 4 medium   verdict: DANGEROUS
```

That's a real run against `examples/poisoned-screenshot.png`, trimmed to one
finding per check for the README - the summary line (`6 high, 4 medium`) is
the actual, untrimmed count; run the command yourself to see all ten. The
image stacks all five techniques framewall looks for on purpose;
`examples/clean-screenshot.png` is the same mockup with none of them, and
comes back CLEAN. Both are committed, built by `examples/generate.py`, so
you can see exactly what's in them and regenerate them yourself.

## Why this exists

2026 research on agents that act on screenshots has been consistently
finding the same gap: text embedded in an image is an attack surface most
agent pipelines don't check at all. [SnapGuard](https://arxiv.org/abs/2604.25562)
frames prompt injection detection for screenshot-based web agents as a
signal-detection problem over the rendered page. [WAInjectBench](https://arxiv.org/abs/2510.01354)
benchmarks detectors against both text- and image-based injection and finds
most of them fail once the payload stops being an obvious, high-contrast
sentence. [MIRAGE](https://arxiv.org/abs/2605.28116) shows that realistic,
context-blended payloads dropped into ordinary user-generated content
regions of a screenshot fool every vision-language agent it tests. That's
the motivation; the implementation here is framewall's own - five
independent, from-scratch checks: compiled regex patterns over OCR'd text,
plus pixel and geometry heuristics for the rest. Not a reproduction of any
of those papers' methods, and not an NLP or semantic model - the patterns
are string matching, the rest is Pillow.

## Where it fits

Lakera Guard, LLM Guard, and NeMo Guardrails all work on plaintext - they
sit after a vision model has already turned the image into a description
or after OCR has already run, and they scan what came out. framewall runs
earlier: it looks at the image itself, before any model has looked at it,
which is the only place you catch a payload that's built specifically to
survive being looked at but not read - text 30 shades off the background,
a box shaped like a system overlay, a comment chunk in the file's own
metadata. None of that has a plaintext form until something already
decided to extract it. Run framewall as the gate before a screenshot
reaches the agent; a text-layer guardrail downstream is still worth having
for everything else the agent produces.

## Install

```bash
git clone https://github.com/munzzyy/framewall
cd framewall
python3 -m venv .venv
.venv/bin/pip install -e .
```

Pillow is the one runtime dependency. The core injection-text detector also
wants the `tesseract` CLI on PATH (`apt install tesseract-ocr`,
`brew install tesseract`, `choco install tesseract`) - framewall shells out
to it as a subprocess and never links it in as a Python package, so there's
no `pytesseract` dependency to carry. Without tesseract, framewall still
runs; it just runs in heuristic-only mode (see below).

## Usage

```bash
framewall scan screenshot.png              # one image
framewall scan ./screenshots                # every image in a directory, recursive
framewall scan "./screenshots/*.png"         # a glob (quoted so it works on Windows too)
framewall scan a.png b.png c.png             # multiple targets
framewall scan screenshot.png --no-ocr       # force heuristic-only, even if tesseract is installed
```

### Two modes

**With tesseract** (the default when it's found): all five checks run,
including the core one - OCR the image, OCR any low-contrast region a
second time after a local contrast boost, and scan whatever text comes back
for directives aimed at an agent. This is the only mode that actually reads
the words instead of just their shape.

**Without tesseract** (`--no-ocr`, or tesseract just isn't installed): the
image-analysis heuristics still run - low-contrast region shape, fake
overlay boxes, PNG/JPEG metadata, and a coarser Pillow-only estimate of
"is there a suspiciously small, gap-containing strip of text here". You
lose the ability to read exactly what a hidden phrase says, but you don't
lose the ability to notice something's there. The report says plainly which
mode ran (`OCR: used` or `OCR: skipped (...)`), and `--json` carries
`ocr_used` / `ocr_skipped_reason` for scripts that need to know.

framewall checks that tesseract can actually read text, not just that the
binary is on PATH. A tesseract install with no language data runs fine and
returns nothing, which would make every image look clean; when that happens
the report says `OCR: skipped (tesseract is installed but read no text...)`
rather than passing the image silently, so a clean verdict never hides a
detector that failed to run. Fix it with `apt install tesseract-ocr-eng`
(or the equivalent language pack) and re-scan.

### In CI

```yaml
- run: pip install framewall
- run: framewall scan ./agent-screenshots --fail-on suspicious
```

`--fail-on` takes `suspicious`, `dangerous`, or `none` (default
`suspicious`). It also speaks SARIF for the GitHub Security tab:

```yaml
- run: framewall scan ./agent-screenshots --sarif > framewall.sarif
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: framewall.sarif
```

This repo's own CI (`.github/workflows/ci.yml`) installs `tesseract-ocr` on
the Linux job so the full suite, OCR layer included, runs there; macOS and
Windows jobs run the tesseract-independent subset, which is most of the
test suite - only `tests/test_ocr.py` and the OCR-gated half of
`tests/test_corpus.py` need it, and they skip cleanly (see Tests below).

### As a Claude Code hook

CI scans images you already have. A hook scans the ones an agent is about to
read, at the moment it tries. [`hooks/framewall-guard.sh`](hooks/framewall-guard.sh)
is a `PreToolUse` guard: register it on the `Read` tool and it runs framewall
on any image the agent opens, blocks the read when the verdict is
`DANGEROUS`, and asks you to confirm when it's `SUSPICIOUS`. This is the piece
[What it does not do](#what-it-does-not-do) has always pointed at - the gate
before a screenshot reaches the agent, not after.

Register it in `~/.claude/settings.json` (use the absolute path to the script):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          { "type": "command", "command": "/absolute/path/to/framewall/hooks/framewall-guard.sh" }
        ]
      }
    ]
  }
}
```

It only scans image files and passes everything else straight through. The
`SUSPICIOUS` verdict asks rather than denies on purpose: the overlay and
low-contrast checks are shape heuristics that also fire on ordinary busy UI
(see below), so a hard block there would get in your way for no good reason -
a hard `DANGEROUS` block is reserved for the checks that actually read an
injection string. If framewall isn't installed the read is allowed with a
note on stderr, not blocked, so a missing dependency can't wall you off from
every screenshot.

### Output formats

- default - a colored, per-finding human report
- `--json` - every finding, region, and the OCR-availability flags, for scripting
- `--sarif` - SARIF 2.1.0
- `--quiet` - one verdict line per image (`DANGEROUS  path/to/file.png`)

## What it checks

Full detail, thresholds, and the reasoning behind each one:
[docs/checks.md](docs/checks.md).

| ID | Check | Needs OCR | Severity |
|---|---|---|---|
| FW-001 | Injection text recovered from the image | yes | high |
| FW-002 | Low-contrast, text-shaped region | no | medium/high |
| FW-003 | Text below legible size | no (better with) | medium |
| FW-004 | Fake system/overlay UI box | no | medium |
| FW-005 | Injection text in PNG/EXIF metadata | no | medium/high |

A finding's severity feeds a single verdict per image: **CLEAN** (nothing
above low), **SUSPICIOUS** (a medium finding), or **DANGEROUS** (a high
finding) - the worst finding decides, full stop.

## Measured against a known-payload corpus

[injection-fixtures](https://github.com/munzzyy/injection-fixtures) ships
eight known visual-injection techniques as pytest fixtures. Run against all
of them, framewall 0.1.0 catches 2 of 8 and false-positives on 1 of 4
benign controls - the real number, not a cherry-picked one. Full
per-technique table, what tripped the false positive, and the caveats that
come with a one-run benchmark: [injection-fixtures' docs/benchmarks/framewall.md](https://github.com/munzzyy/injection-fixtures/blob/main/docs/benchmarks/framewall.md).

## What it does not do

- **The overlay and low-contrast checks are shape heuristics, not readers.**
  They flag "this looks like a hidden or spoofed text region," not "this
  text says X." A busy, legitimately dense UI (toolbars, cookie banners,
  toast notifications, tightly packed dashboards) will trip FW-004 and
  sometimes FW-002 without anything malicious being present. Read the
  flagged region before trusting a high-severity read on it.
- **The `system:` and generic phrasing patterns in FW-001 are broad on
  purpose and will misfire on unusual but legitimate text**, like a
  document that's itself teaching prompt-injection concepts. A clean scan
  means nothing obvious tripped, not that the image is safe to feed an
  agent unsupervised.
- **Tiny text needs to still be OCR-legible to be read exactly.** Below
  roughly 8-9px, tesseract stops recognizing text at all; framewall then
  has no line to measure, so extremely tiny text falls through FW-003 even
  though it's exactly the kind of thing an attacker would want to hide.
  The heuristic fallback (`--no-ocr`) trades precision for not needing OCR
  at all, and is the noisiest of the five checks by design.
- **Some hiding techniques slip past every check.** The detectors are tuned
  for text an agent reads straight on: low contrast, tiny size, a fake system
  box, metadata. Text rotated well off-axis, painted into a nearly-transparent
  alpha layer, or broken up by high-frequency noise can defeat the shape
  heuristics and read poorly under OCR, so framewall can miss it. It raises the
  cost of hiding a payload; it doesn't make hiding one impossible. A clean scan
  is one layer, not a guarantee.
- **This is a scanner, not a sandbox.** It reads pixels and metadata; it
  never executes anything, and it does nothing to stop an agent from acting
  on text it already saw before framewall ran. The right place for this is
  a gate *before* a screenshot reaches the agent, not a replacement for treating
  screenshots from an untrusted source as untrusted input in the first
  place.
- **It only looks at what's in front of it.** It doesn't fetch, render, or
  re-screenshot anything - no network access at scan time, ever.

## Exit codes

- `0` - scan completed, worst verdict stayed below `--fail-on`
- `1` - scan completed, worst verdict reached `--fail-on`
- `2` - usage error: bad arguments, no target matched, or an image couldn't
  be read at all (corrupt file, or over the size cap)

## Tests

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

154 tests. Every test that needs a real tesseract binary is marked and
skips cleanly when one isn't on PATH (`tests/conftest.py::requires_tesseract`) -
run `tesseract --version` to check whether your machine runs the full
suite or the heuristic subset. `tests/test_corpus.py` is the floor that
matters: a labeled set of malicious fixtures that must each be flagged, and
a benign one that must stay CLEAN, built fresh with Pillow inside the test
suite itself rather than checked in as opaque binaries. `tests/_images.py`
is the fixture factory both the tests and `examples/generate.py` share the
approach with (not the code - `examples/` is deliberately standalone).

## Contributing

Found an attack shape that should have been flagged and wasn't, or a false
positive on ordinary UI? Open an issue with the smallest image that
reproduces it. See [CONTRIBUTING.md](CONTRIBUTING.md) - new checks land with
a fixture in `tests/_images.py` and an entry in `tests/test_corpus.py`, so
coverage only goes up.

## License

MIT — free to use, change, and ship, commercial or not. See [LICENSE](LICENSE).

## Support

If framewall caught a poisoned screenshot before your agent acted on it, [sponsoring](https://github.com/sponsors/munzzyy) is what keeps the payload corpus growing.
