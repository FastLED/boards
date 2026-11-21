#!/usr/bin/env python3
"""Mine search-term corpora from per-board JSON manifests + curated rules.

For each *.json under site-src/public/boards/ and
.extern-repos/boards-other/, recursively walk the value tree and collect
every string that:

  - is NOT convertible to int / float / 0x-hex (so "16000000",
    "0x303a", "1.0" are excluded)
  - has len > 4 (filters short tokens like "wifi", "avr", 4-hex VIDs)
  - is not whitespace-only

Dedupes via set, sorts, samples N (default 100) entries with a fixed
RNG seed so the chosen sample is stable across runs (regenerating the
test file is a no-op unless --n or --seed changes). Writes the sample
as a literal list into tests/test_search_corpus.py and prints the
chosen items to stdout.

Run:
    python tools/gen_search_corpus.py [--n 100] [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

# Corpus sources. Both are real data:
#   - site-src/public/boards: the per-board JSONs the orchestrator stages
#     for the portal (one file per board, ~2000 files). This is the
#     canonical search-relevant corpus — every board name, MCU,
#     framework, connectivity flag, homepage URL, etc. lives here.
#   - .extern-repos/boards-other: a worktree of the `other` data branch,
#     carrying the curated overrides (Teensy USB-mode polyfills,
#     vendor re-attribution rules, USB-misc entries).
SOURCES = [
    REPO / "site-src" / "public" / "boards",
    REPO / ".extern-repos" / "boards-other",
]
TEST_OUT = REPO / "tests" / "test_search_corpus.py"


def is_numeric(s: str) -> bool:
    """True iff s parses as an int (decimal, 0x-hex, 0o-oct, 0b-bin) or
    a float. Used to drop "16000000", "0x303a", "1.0" from the corpus —
    those aren't useful free-text search terms.
    """
    s = s.strip()
    if not s:
        return False
    try:
        int(s)
        return True
    except ValueError:
        pass
    try:
        int(s, 0)  # honours 0x / 0o / 0b prefixes
        return True
    except (ValueError, TypeError):
        pass
    try:
        float(s)
        return True
    except ValueError:
        pass
    return False


def walk(value, sink: set[str]) -> None:
    """Recursively collect every string value that passes the filter
    into `sink`. Dict KEYS are deliberately ignored — they're schema
    labels (board_id, mcu, frameworks, …), not searchable content."""
    if isinstance(value, str):
        if (
            len(value) > 4
            and value.strip()
            and not is_numeric(value)
        ):
            sink.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            walk(v, sink)
    elif isinstance(value, list):
        for v in value:
            walk(v, sink)
    # int/float/bool/None — ignored (we only mine strings)


def collect() -> tuple[list[str], int, int]:
    sink: set[str] = set()
    json_files = 0
    for root in SOURCES:
        if not root.exists():
            print(f"  note: corpus root missing — skipping: {root}", file=sys.stderr)
            continue
        for path in root.rglob("*.json"):
            json_files += 1
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                print(f"  warn: failed to parse {path}: {e}", file=sys.stderr)
                continue
            walk(doc, sink)
    return sorted(sink), json_files, len(sink)


def emit_test(sample: list[str], seed: int, total_unique: int, files_scanned: int) -> None:
    """Write tests/test_search_corpus.py with the literal sample
    embedded. Stable formatting so re-running with the same --n/--seed
    yields a byte-identical file."""
    py_terms = ",\n    ".join(repr(t) for t in sample)
    TEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    body = f'''"""Auto-generated search-term corpus.

Sampled from per-board JSON manifests + curated rules under
site-src/public/boards/ and .extern-repos/boards-other/. Sampling is
reproducible:

    python tools/gen_search_corpus.py --n {len(sample)} --seed {seed}

Generation stats at last regen:
    JSON files scanned: {files_scanned}
    unique strings (len > 4, non-numeric): {total_unique}
    sample size:        {len(sample)}
    seed:               {seed}

Do not edit the SEARCH_TERMS list by hand — regenerate via the tool
above so the sample stays linked to a deterministic seed.
"""

import unittest


SEARCH_TERMS = [
    {py_terms},
]


class SearchCorpusTests(unittest.TestCase):
    def test_corpus_size(self) -> None:
        self.assertEqual(len(SEARCH_TERMS), {len(sample)})

    def test_corpus_unique(self) -> None:
        self.assertEqual(len(set(SEARCH_TERMS)), len(SEARCH_TERMS))


if __name__ == "__main__":
    unittest.main()
'''
    TEST_OUT.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    sorted_terms, json_files, unique = collect()
    if len(sorted_terms) < args.n:
        print(
            f"error: only {len(sorted_terms)} unique terms — can't sample {args.n}",
            file=sys.stderr,
        )
        return 1
    sample = random.Random(args.seed).sample(sorted_terms, args.n)

    print(f"Scanned {json_files} JSON files")
    print(f"Unique strings (len > 4, non-numeric, non-whitespace): {unique}")
    print(f"Sampled {len(sample)} with seed={args.seed}")
    print(f"Writing → {TEST_OUT.relative_to(REPO)}")
    emit_test(sample, args.seed, unique, json_files)
    print()
    print("Sample (in random.sample() order — not sorted):")
    for i, t in enumerate(sample, 1):
        print(f"  {i:>3}. {t!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
