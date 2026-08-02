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

  7 high, 4 medium   verdict: DANGEROUS
```

That's a real run against `examples/poisoned-screenshot.png`, trimmed to one
finding per check for the README - the summary line (`7 high, 4 medium`) is
the actual, untrimmed count; run the command yourself to see all eleven. The
image stacks five hiding techniques on purpose;
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
the motivation; the implementation here is framewall's own - six
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
pipx install git+https://github.com/munzzyy/framewall
```

framewall is not on PyPI yet, so install it straight from this repo -
`pip install framewall` will not get you this tool. For hacking on it:

```bash
git clone https://github.com/munzzyy/framewall
cd framewall
python3 -m venv .venv
.venv/bin/pip install -e .
```

Pillow is the one runtime dependency. The core injection-text detector also
wants the `tesseract` CLI on PATH (`apt install tesseract-ocr`,
`brew install tesseract`, `choco install tesseract`,
`pacman -S tesseract tesseract-data-eng`) - framewall shells out
to it as a subprocess and never links it in as a Python package, so there's
no `pytesseract` dependency to carry. On most Linux distros the language
data is a separate package from the binary (`tesseract-ocr-eng` on
Debian/Ubuntu, `tesseract-data-eng` on Arch); a tesseract without it runs
but reads nothing, which framewall detects and says out loud rather than
scanning blind (see below). Without tesseract, framewall still runs; it
just runs in heuristic-only mode.

## Usage

```bash
framewall scan screenshot.png              # one image
framewall scan ./screenshots                # every image in a directory, recursive
framewall scan "./screenshots/*.png"         # a glob (quoted so it works on Windows too)
framewall scan a.png b.png c.png             # multiple targets
framewall scan screenshot.png --no-ocr       # force heuristic-only, even if tesseract is installed
framewall scan screenshot.png --lang eng+deu # tesseract language(s); FRAMEWALL_TESSERACT_LANG works too
framewall scan huge.png --max-scan-seconds 60  # whole-image OCR ceiling (default 30; 0 lifts it)
```

Every OCR pass for one image draws on a single wall-clock budget
(`--max-scan-seconds`, default 30), and the number of flagged regions that
get their own OCR pass is capped. Without those bounds, one busy or crafted
screenshot can demand hundreds of tesseract subprocesses and stall a
synchronous caller for hours - which would turn the hook below into a
denial-of-service target. Anything the bounds cut short is reported as a
`note:` line (and a `notes` array in `--json`) saying the scan is partial,
so a truncated scan never passes itself off as a completed clean one.

### Two modes

**With tesseract** (the default when it's found): all six checks run,
including the core one - OCR the image, OCR any flagged region a second
time after a local contrast boost and upscale, and scan whatever text comes
back for directives aimed at an agent. When none of that matches, two
recovery passes take one more swing each at text built to defeat plain OCR:
a residual pass that amplifies detail sitting nearly flush with its
background (catches text one shade off white), and a deskew pass that
detects off-axis text and re-reads the image counter-rotated. This is the
only mode that actually reads the words instead of just their shape.

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
(or the equivalent language pack) and re-scan. The probe tests the language
the scan will actually use: pick one with `--lang deu` (or
`FRAMEWALL_TESSERACT_LANG=deu` for the hook), and if that pack is missing
the skip reason names it.

### In CI

```yaml
- run: pip install git+https://github.com/munzzyy/framewall
- run: framewall scan ./agent-screenshots --fail-on suspicious
```

(framewall is not on PyPI yet; pin the install to a tag or commit if you
want reproducible CI.)

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
| FW-006 | High-frequency two-tone camouflage region | no | medium |

A finding's severity feeds a single verdict per image: **CLEAN** (nothing
above low), **SUSPICIOUS** (a medium finding), or **DANGEROUS** (a high
finding) - the worst finding decides, full stop.

## Measured against a known-payload corpus

[injection-fixtures](https://github.com/munzzyy/injection-fixtures) ships
eight known visual-injection techniques as pytest fixtures. Run against all
of them (2026-08-02, corpus 0.1.0), framewall 0.2.0 catches 7 of 8 and
false-positives on 1 of 4 benign controls - the real numbers from a fresh
run of that repo's `benchmark/run_framewall.py`, not cherry-picked ones.
The one miss is `low-opacity` (text at ~11% alpha over per-pixel noise; see
the limits below), and the one false positive is `benign-ui` tripping the
FW-004 shape heuristic, which is the documented cost of flagging
overlay-shaped UI at all. framewall 0.1.0 scored 2 of 8; re-run today it
scores 3 of 8 (the corpus's noise rendering changed and its `caption-chrome`
now OCRs directly), so the honest attribution is four catches added by
0.2.0: the recovery passes (white-on-white, rotated-skew), the upscaled
strip OCR (tiny-corner), and FW-006 (edge-noise).
`tests/test_benchmark_floor.py` re-measures this floor in CI so it can't
silently regress. Per-technique history and caveats:
[injection-fixtures' docs/benchmarks/framewall.md](https://github.com/munzzyy/injection-fixtures/blob/main/docs/benchmarks/framewall.md).

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
- **Tiny text needs to survive an upscale to be read exactly.** Below
  roughly 8-9px, tesseract stops recognizing text at native size. framewall
  flags thin, text-shaped strips anyway and re-reads them upscaled with a
  local contrast boost, which recovers a lot of sub-legible text - but text
  small or degraded enough that even the upscaled pass reads nothing still
  falls through FW-003. The strip heuristic on its own (`--no-ocr` mode) is
  the noisiest of the six checks by design.
- **Some hiding techniques still slip past every check.** 0.2.0 closed the
  three gaps this section used to name (off-axis rotation, one-shade-off
  text, high-frequency two-tone camouflage), but others remain: text painted
  into a nearly-transparent alpha layer is flattened away before the checks
  run, and text at very low opacity over a noisy background (the corpus's
  `low-opacity` miss) sits below what OCR can recover from the pixels.
  framewall raises the cost of hiding a payload; it doesn't make hiding one
  impossible. A clean scan is one layer, not a guarantee.
- **This is a scanner, not a sandbox.** It reads pixels and metadata; it
  never executes anything, and it does nothing to stop an agent from acting
  on text it already saw before framewall ran. The right place for this is
  a gate *before* a screenshot reaches the agent, not a replacement for treating
  screenshots from an untrusted source as untrusted input in the first
  place.
- **It only looks at what's in front of it.** It doesn't fetch, render, or
  re-screenshot anything - no network access at scan time, ever.

## What framewall cannot see

Every check keys on text or text-like structure: injection phrasing, hidden
or tiny text shapes, overlay boxes, metadata strings, camouflage patterns.
There is a published attack class with none of that. MIRAGE
([arXiv 2606.20717](https://arxiv.org/abs/2606.20717) - a different paper
from the MIRAGE cited above) uses diffusion-guided adversarial perturbation
to steer a vision agent with images that are perceptually benign and contain
no recoverable text at all, confined to a region an unprivileged attacker
controls, like an ad slot. A screenshot carrying that payload comes back
with no findings here, and no amount of OCR or shape heuristics changes
that - the signal isn't text.

That's why a clean result reads `No text-shaped injection found` rather
than "safe": absence of findings means the text-shaped attack surface came
up empty, and nothing more. If your threat model includes adversarial
perturbation attacks, you need a defense aimed at that class (input
sanitization at the model layer, region provenance, or not feeding
untrusted image regions to the agent at all); no text scanner covers it.

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

Every test that needs a real tesseract binary is marked and
skips cleanly when one isn't on PATH (`tests/conftest.py::requires_tesseract`) -
run `tesseract --version` to check whether your machine runs the full
suite or the heuristic subset. `tests/test_corpus.py` is the floor that
matters: a labeled set of malicious fixtures that must each be flagged, and
a benign one that must stay CLEAN, built fresh with Pillow inside the test
suite itself rather than checked in as opaque binaries.
`tests/test_benchmark_floor.py` holds the second floor: the measured
injection-fixtures catch rate above, re-asserted in CI so it can't quietly
slide back. `tests/_images.py`
is the fixture factory both the tests and `examples/generate.py` share the
approach with (not the code - `examples/` is deliberately standalone).

## Contributing

Found an attack shape that should have been flagged and wasn't, or a false
positive on ordinary UI? Open an issue with the smallest image that
reproduces it. See [CONTRIBUTING.md](CONTRIBUTING.md) - new checks land with
a fixture in `tests/_images.py` and an entry in `tests/test_corpus.py`, so
coverage only goes up.

## License

MIT - free to use, change, and ship, commercial or not. See [LICENSE](LICENSE).

## Support

If framewall caught a poisoned screenshot before your agent acted on it, [sponsoring](https://github.com/sponsors/munzzyy) is what keeps the payload corpus growing.
