# Contributing

Thanks for looking at this. It's a small, single-purpose tool and contributions are welcome.

## Setup

```
git clone https://github.com/munzzyy/framewall
cd framewall
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Pillow is the one runtime dependency. tesseract is optional - install it
(`apt install tesseract-ocr`, `brew install tesseract`, etc.) if you want the
full test suite and the core injection-text detector to run; everything
else works without it.

## Running the tests

```
.venv/bin/pytest
```

Tests that need tesseract are marked and skip cleanly if it isn't on PATH -
see `tests/conftest.py::requires_tesseract`. Run `tesseract --version` to
check whether your machine will run the full suite.

## Adding or fixing a check

Every check change lands with a fixture, so coverage only goes up:

- Missed a real attack? Add a case to `MALICIOUS_FIXTURES` in
  `tests/test_corpus.py` (or a new fixture builder in `tests/_images.py`
  if it needs a new image shape). The corpus test asserts every malicious
  fixture reaches at least its expected verdict.
- Found a false positive? Add a benign case and assert it stays CLEAN.
  `tests/_images.py::clean_screenshot` is the baseline everything else is
  built from - if you're chasing a specific false positive, isolate it into
  its own small fixture rather than growing that one.

If you fix a bug with no fixture attached, it can silently come back. A
fixture is how the fix stays fixed.

Keep checks specific. A heuristic that fires on ordinary UI is worse than
one that misses an edge case, because noise trains people to ignore the
tool. Every check module (`framewall/checks/*.py`) documents its own
thresholds and why they're set where they are - read the comments before
changing a constant.

New or changed check IDs need a matching entry in `docs/checks.md`; a test
enforces that the two stay in sync.

## Dependencies

Pillow is the only runtime dependency, and that's deliberate. tesseract is
shelled out to as an external binary, never linked in as a Python package
(no pytesseract) - that keeps the dependency surface to one pure-Python
package plus one optional, widely-packaged CLI tool. If a change needs
something more than that, it's a reason to reconsider the change.

## License

Contributions come in under the [Blue Oak Model License 1.0.0](https://blueoakcouncil.org/license/1.0.0). By opening a PR you agree your contribution is offered on those terms.
