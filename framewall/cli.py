"""Command-line interface for framewall."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .report import render_human, render_json, render_sarif
from .scanner import scan_image
from .targets import resolve
from .verdict import Verdict, rank


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="framewall",
        description="Scan images for visually-embedded prompt injection before a vision or computer-use agent reads them.",
    )
    p.add_argument("--version", action="version", version=f"framewall {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan one or more images")
    scan.add_argument("targets", nargs="+", help="image file(s), a directory, or a glob")
    scan.add_argument(
        "--no-ocr", action="store_true", help="skip the tesseract OCR pass; run heuristics only"
    )
    out = scan.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="machine-readable JSON output")
    out.add_argument("--sarif", action="store_true", help="SARIF 2.1.0 (for GitHub code scanning)")
    scan.add_argument(
        "--fail-on",
        default="suspicious",
        metavar="VERDICT",
        help="exit non-zero at or above this verdict (suspicious|dangerous|none; default: suspicious)",
    )
    scan.add_argument("--no-color", action="store_true", help="disable ANSI color")
    scan.add_argument("--quiet", action="store_true", help="only print one verdict line per image")
    return p


def _fail_threshold(value: str):
    value = value.strip().lower()
    if value in ("none", "off", "never"):
        return None
    try:
        return Verdict.parse(value)
    except ValueError:
        raise SystemExit(f"framewall: invalid --fail-on value {value!r}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "scan":
        return 2

    threshold = _fail_threshold(args.fail_on)

    paths, unmatched = resolve(args.targets)
    if not paths:
        print(f"framewall: no images matched: {', '.join(unmatched) or ', '.join(args.targets)}", file=sys.stderr)
        return 2
    for m in unmatched:
        print(f"framewall: warning: no match for {m}", file=sys.stderr)

    use_ocr = not args.no_ocr
    results = [scan_image(p, use_ocr=use_ocr) for p in paths]

    color = not args.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    if args.json:
        print(render_json(results))
    elif args.sarif:
        print(render_sarif(results))
    elif args.quiet:
        for r in results:
            label = "ERROR" if r.error else r.verdict.upper()
            print(f"{label}  {r.path}")
    else:
        print(render_human(results, color=color))

    if any(r.error for r in results):
        return 2
    if threshold is None:
        return 0
    worst_rank = max((rank(Verdict(r.verdict)) for r in results), default=-1)
    if worst_rank >= rank(threshold):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
