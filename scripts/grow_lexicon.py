"""Teach the parser vocabulary from a corpus of audits.

Run offline, never inside a request:

    backend/.venv/bin/python -m scripts.grow_lexicon tests/fixtures/dars_synthetic
    backend/.venv/bin/python -m scripts.grow_lexicon DARS --dry-run

Parsing a student's report must not mutate shared state, and a web process
should not be writing into the deployment bundle — so growth is a deliberate
step someone takes, with a diff they can read before committing it.

Only non-identifying vocabulary is retained: subject prefixes, designation
codes, and lowercase phrase shapes that contain an academic token. See
``backend/lexicon.py`` for the filters. Anything the parser learns here is an
*additive prior* — it can improve a genuinely ambiguous line and can never
override what a document says about itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.lexicon import LEXICON_PATH, Lexicon, learn_from  # noqa: E402
from backend.pdf_parser import parse_dars_pdf  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="PDF files or directories")
    parser.add_argument("--out", type=Path, default=LEXICON_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be learned without writing the lexicon.",
    )
    args = parser.parse_args()

    pdfs: list[Path] = []
    for source in args.sources:
        if source.is_dir():
            pdfs.extend(sorted(source.glob("*.pdf")))
        elif source.is_file():
            pdfs.append(source)
        else:
            print(f"skipped (not found): {source}", file=sys.stderr)
    if not pdfs:
        print("No PDFs found.", file=sys.stderr)
        return 1

    audits = []
    for path in pdfs:
        try:
            audits.append(parse_dars_pdf(str(path)))
        except Exception as failure:  # A corpus will contain awkward files.
            print(f"skipped {path.name}: {type(failure).__name__}", file=sys.stderr)

    if not audits:
        print("Nothing parsed.", file=sys.stderr)
        return 1

    before = Lexicon.load(args.out).summary()
    if args.dry_run:
        preview = learn_from(audits, Path("/dev/null"))
        after = preview.summary()
    else:
        after = learn_from(audits, args.out).summary()

    print(f"Parsed {len(audits)} audit(s) from {len(pdfs)} file(s).")
    for key in sorted(after):
        delta = after[key] - before.get(key, 0)
        print(f"  {key:<18} {after[key]:>4}  ({delta:+d})")
    # New designation codes are the signal worth acting on: they mean this
    # catalog year uses vocabulary the shipped table has never seen.
    unknown = sorted(
        code
        for audit in audits
        for entry in audit.get("designations", [])
        if (code := entry["code"]) and entry.get("era") == "discovered"
    )
    if unknown:
        print(f"\n  designations new to the built-in table: {', '.join(sorted(set(unknown)))}")
    print(f"\n{'Would write' if args.dry_run else 'Wrote'} {args.out}")
    if not args.dry_run:
        print(json.dumps(json.loads(args.out.read_text())["subjects"], indent=1)[:200] + " ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
