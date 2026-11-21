#!/usr/bin/env python3
"""Mine the corpus's dictionary KEYS (not values) so we can probe
whether JSON schema labels accidentally surface boards through
search. Companion to tools/gen_search_corpus.py which samples VALUES.

Walks per-board JSON manifests + curated rules. Recursively gathers
every dict KEY that is a non-empty string, dedupes via set, sorts,
then samples N (default 50) with a fixed --seed. Writes the sample
as a literal list into tests/test_search_keys_corpus.py and prints
the chosen keys.

Hypothesis to test against the result: most keys are schema labels
(`build`, `menu`, `frameworks`, `hwids`, `vendor`, ...) that shouldn't
return any boards. A few are de-facto board IDs surfaced as keys
(STM32duino `menu.pnum.<part>` substructure) and SHOULD hit thanks
to the aliases work in extract_boards.py.

Run:
    python tools/gen_search_keys_corpus.py [--n 50] [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCES = [
    REPO / "site-src" / "public" / "boards",
    REPO / ".extern-repos" / "boards-other",
]
TEST_OUT = REPO / "tests" / "test_search_keys_corpus.py"


def walk_keys(obj, sink: set[str]) -> None:
    """Walk obj and add every dict KEY to sink. The empty-string key
    is skipped — Arduino board.txt uses `""` to hold a menu's display
    label and that's a value-search, not a key-search."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k:
                sink.add(k)
            walk_keys(v, sink)
    elif isinstance(obj, list):
        for v in obj:
            walk_keys(v, sink)


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
            walk_keys(doc, sink)
    return sorted(sink), json_files, len(sink)


def emit_test(sample: list[str], seed: int, total_unique: int, files_scanned: int) -> None:
    py_terms = ",\n    ".join(repr(t) for t in sample)
    TEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    body = f'''"""Auto-generated dict-KEY corpus from the per-board JSON manifests
and curated rules.

Sampled from dict-KEY positions only (not values). Reproducible:

    python tools/gen_search_keys_corpus.py --n {len(sample)} --seed {seed}

Generation stats at last regen:
    JSON files scanned:                {files_scanned}
    unique dict keys (non-empty):      {total_unique}
    sample size:                       {len(sample)}
    seed:                              {seed}
"""

import unittest


SEARCH_KEYS = [
    {py_terms},
]


class SearchKeysCorpusTests(unittest.TestCase):
    def test_corpus_size(self) -> None:
        self.assertEqual(len(SEARCH_KEYS), {len(sample)})

    def test_corpus_unique(self) -> None:
        self.assertEqual(len(set(SEARCH_KEYS)), len(SEARCH_KEYS))


if __name__ == "__main__":
    unittest.main()
'''
    TEST_OUT.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    sorted_keys, json_files, unique = collect()
    n = min(args.n, len(sorted_keys))
    # When --n covers the whole set, emit the sorted list verbatim
    # (set → list → sort, no shuffle — user wants deterministic order).
    # Sample only when the user asked for a strict subset.
    if n >= len(sorted_keys):
        sample = sorted_keys
    else:
        sample = random.Random(args.seed).sample(sorted_keys, n)

    print(f"Scanned {json_files} JSON files")
    print(f"Unique dict keys: {unique}")
    print(f"Sampled {n} with seed={args.seed}")
    print(f"Writing → {TEST_OUT.relative_to(REPO)}")
    emit_test(sample, args.seed, unique, json_files)
    print()
    print("Sample (random.sample order):")
    for i, t in enumerate(sample, 1):
        print(f"  {i:>3}. {t!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
