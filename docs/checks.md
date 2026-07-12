# Checks reference

Every detection layer framewall runs, what it looks for, and what it needs
to run at all. A test keeps this file in sync with the code, so a check
cannot exist without being documented here.

## FW-001

Injection text. Severity: high, always.

Needs OCR. Reads the image with tesseract - once at full resolution, and
again on any region FW-002 flagged, after a local contrast boost - then
scans the recovered text for directives aimed at an agent rather than a
human: "ignore previous instructions", "disregard your prior instructions",
"you are now a...", "new instructions:", a `system:` label, "do not tell the
user", "reveal your system prompt", a send/upload verb paired with a nearby
URL, and tool-call-shaped strings like `<tool_call>` or `"function_call":`.

This is the core detector - everything else is a proxy for "something looks
off", and this one reads the actual words.

Don't feed the image to an agent once this fires. If the text is legitimate
(a tutorial screenshot showing a prompt-injection example, say) it's still
worth a human's eyes before an agent sees it unsupervised.

## FW-002

Low-contrast text-shaped region. Severity: medium, or high for a large
region.

Pillow only, no OCR needed. Splits the image into small blocks and flags
ones with real internal structure (some standard deviation - edges, strokes)
but a narrow value range (a few shades of max-min) - the fingerprint of text
rendered a few shades off its own background. A single-block-wide seam
between two flat, similarly-colored UI panels is filtered out on purpose;
real hidden text is at least a few characters wide.

Contrast-boost the region, or re-scan with OCR, to see what it actually says.

## FW-003

Text below legible size. Severity: medium.

With OCR, this measures tesseract's own line boxes (not individual word
boxes - a short lowercase word like "is" reads far shorter than the line
it's actually sitting on and would look tiny on its own). Without OCR it
falls back to a coarser, Pillow-only estimate: thin, gap-containing strips
of high-contrast detail, with straight edges (panel borders, button
outlines) explicitly excluded since a solid line and a line of text are the
same shape at this resolution.

Fine print is normal on its own - check whether the recovered text, or
without OCR the flagged region, carries directives aimed at an agent.

## FW-004

Fake system/overlay UI. Severity: medium.

Pillow only, no OCR needed. Looks for a solid-fill box with patches of
higher-detail content (text-like) inside it, positioned near an edge or
centered - the shape a fake "System message" or "AI notice" overlay takes.
Adjacent flat panels of different colors are grouped separately (a
seed-anchored flood fill only grows into neighbors close to its own fill
color), and boxes that span nearly the full width or height are treated as
ordinary page chrome (a header, a toolbar) rather than an injected box.

Purely a shape heuristic - it has no idea what the box says and will flag a
real toast notification, cookie banner, or tooltip that happens to land in
the same shape.

Look at the region directly. Treat the image as untrusted if the text
addresses an agent rather than a human.

## FW-005

Metadata / steganography-lite. Severity: medium, or high if the embedded
text matches an injection pattern.

Pillow only, no OCR needed. Reads PNG tEXt/iTXt chunks and EXIF text fields
(comment, description, user comment, and similar) and scans anything
non-trivial for injection phrasing. Ordinary plumbing fields (ICC profiles,
DPI, software version strings) are skipped so a normal export doesn't get
flagged just for having metadata at all.

Strip metadata before the image reaches an agent, or confirm the embedded
text is expected for wherever this image came from.
