#!/usr/bin/env python3
"""Generate disambiguation test cases for variant-keyword searches.

The premise: keywords like `ble`, `tiny`, `wifi`, `bluetooth` are
variant identifiers users add to a base board name to find a
*specific* variant. The test locks in that adding the keyword
correctly disambiguates — the keyword-variant board MUST be the top
hit, not buried under collision-set neighbours that share the rest
of the name.

Algorithm:
  1. Mine (board_id, name) via jq across the per-board JSON corpus.
  2. For each keyword K in {ble, tiny, wifi, bluetooth}:
       For each board whose name TOKENS contain K:
         short_tokens = tokens minus K  (single keyword stripped)
         collisions = OTHER boards whose name tokens are a superset
                      of short_tokens
         if len(collisions) >= 1:
             yield (long_name, this_board_id, K, collision_board_ids)
  3. Dedupe by (long_name, expected_id), sort, embed in test.

The contract:
    For each (long_name, expected_id) row, searching `long_name` via
    `board` mode must return `expected_id` at position 0.

Run:
    python tools/gen_keyword_disambig_corpus.py [--seed 0]
"""
from __future__ import annotations

import argparse
import pathlib
import random
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "site-src" / "public" / "boards"
TEST_OUT = REPO / "tests" / "test_keyword_disambig.py"

KEYWORDS = ("ble", "tiny", "wifi", "bluetooth")
_TOK_RE = re.compile(r"[A-Za-z0-9]+")


def _toks(name: str) -> list[str]:
    return [t.lower() for t in _TOK_RE.findall(name)]


def collect_boards() -> list[tuple[str, str]]:
    paths = sorted(SOURCE.rglob("*.json"))
    JQ_PROG = r'input_filename as $f | "\($f)|\(.name // "")"'
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    BATCH = 200
    for i in range(0, len(paths), BATCH):
        batch = [str(p) for p in paths[i:i + BATCH]]
        result = subprocess.run(
            ["jq", "-r", JQ_PROG, *batch],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            if "|" not in line:
                continue
            path, name = line.split("|", 1)
            name = name.strip()
            if not name:
                continue
            bid = pathlib.Path(path).stem
            if bid in seen:
                continue
            seen.add(bid)
            out.append((bid, name))
    return sorted(out)


def build_cases(boards: list[tuple[str, str]]) -> list[tuple[str, list[str], str, list[str]]]:
    """One case per (long_name, keyword). The "expected" field is the
    SET of board_ids whose name matches the long_name verbatim — many
    boards in the corpus are duplicated under both a PlatformIO ID
    and an Arduino ID (e.g. `unor4wifi` vs `uno_r4_wifi`, both named
    "Arduino UNO R4 WiFi"), so any of them counts as the correct top
    hit.

    Collisions = OTHER boards whose name tokens are a superset of
    `long_name minus keyword` — these are the false candidates the
    keyword has to disambiguate against. A case is only emitted if
    real (non-duplicate) collisions exist."""
    by_bid_toks = {bid: _toks(name) for bid, name in boards}
    # token-tuple → set of board_ids sharing it. Token-tuple dedupe
    # catches case-only variants like ("Arduino UNO R4 WiFi"
    # board_id=unor4wifi) vs ("Arduino Uno R4 WiFi" board_id=uno_r4_wifi)
    # which are the same physical board under PlatformIO + Arduino IDs.
    toks_to_ids: dict[tuple[str, ...], list[str]] = {}
    for bid, name in boards:
        toks_to_ids.setdefault(tuple(by_bid_toks[bid]), []).append(bid)

    cases: list[tuple[str, list[str], str, list[str]]] = []
    seen_keys: set[tuple[tuple[str, ...], str]] = set()
    for bid, name in boards:
        my_toks = by_bid_toks[bid]
        my_toks_tuple = tuple(my_toks)
        for kw in KEYWORDS:
            if kw not in my_toks:
                continue
            if (my_toks_tuple, kw) in seen_keys:
                continue
            seen_keys.add((my_toks_tuple, kw))
            short_set = [t for t in my_toks if t != kw]
            if len(short_set) < 2:
                continue
            short_set_set = set(short_set)
            expected_ids = set(toks_to_ids[my_toks_tuple])
            collisions: list[str] = []
            for other_bid, other_toks in by_bid_toks.items():
                if other_bid in expected_ids:
                    continue
                if short_set_set.issubset(set(other_toks)):
                    collisions.append(other_bid)
            if collisions:
                cases.append((name, sorted(expected_ids), kw, sorted(collisions)))
    return cases


def emit_test(cases: list[tuple[str, list[str], str, list[str]]]) -> None:
    py_cases = ",\n    ".join(
        f"({long_name!r}, {expected!r}, {kw!r}, {collisions!r})"
        for long_name, expected, kw, collisions in cases
    )
    body = f'''"""Auto-generated keyword-disambiguation test cases.

For each row, the long form `<long_name>` MUST return `<expected>` at
position 0 in `board` mode. The `<collisions>` list is the OTHER
boards whose name tokens are a superset of (long_name minus keyword)
— proof that the short form alone wouldn't pick the right variant.

Locks in that adding `ble` / `tiny` / `wifi` / `bluetooth` to a
search actually selects the keyword-variant board, not just any
collision-set neighbour with the same base name.

Regenerate with:
    python tools/gen_keyword_disambig_corpus.py

Cases: {len(cases)}.

Honors BOARDS_DB env override for local iteration; falls back to the
live published URL otherwise.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = pathlib.Path(__file__).resolve().parents[1]
BUN = shutil.which("bun")
QUERY_MJS = REPO / "tools" / "query.mjs"
LIVE_URL = "https://fastled.github.io/boards/boards.db"


# (long_name, expected_top_board_ids, keyword_that_disambiguates,
#  collision_set_of_other_board_ids)
# expected_top_board_ids is a list because the same display name can
# back multiple board_ids (PlatformIO + Arduino variants of the same
# physical board) — any of them counts as a correct top hit.
DISAMBIG_CASES: list[tuple[str, list[str], str, list[str]]] = [
    {py_cases},
]


def _db_arg() -> str:
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    return LIVE_URL


def _run_batch(items: list[dict]) -> list[dict]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(items, fh)
        batch_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, str(QUERY_MJS), "--db", _db_arg(), "--batch", batch_path],
            capture_output=True, text=True, timeout=300, check=True,
        )
    finally:
        os.unlink(batch_path)
    return json.loads(proc.stdout)


@unittest.skipIf(BUN is None, "bun runtime not installed")
class KeywordDisambigTests(unittest.TestCase):
    """The long-form (with keyword) MUST return the keyword-variant
    board at position 0. Otherwise the keyword didn't actually
    disambiguate from collision-set neighbours."""

    def test_corpus_size(self) -> None:
        self.assertEqual(len(DISAMBIG_CASES), {len(cases)})

    def test_long_form_returns_keyword_variant_at_top(self) -> None:
        items = [{{"text": long_name, "mode": "board"}}
                 for long_name, *_ in DISAMBIG_CASES]
        results = _run_batch(items)
        self.assertEqual(len(results), len(DISAMBIG_CASES))

        misses = []
        for (long_name, expected_ids, kw, collisions), r in zip(DISAMBIG_CASES, results):
            boards = r["data"]["boards"]
            if not boards:
                misses.append((long_name, expected_ids, kw, "no rows", collisions[:3]))
                continue
            top_bid = boards[0]["row"]["board_id"]
            if top_bid not in expected_ids:
                misses.append((long_name, expected_ids, kw,
                               f"top was {{top_bid!r}}", collisions[:3]))
        if misses:
            self.fail(
                f"\\n{{len(misses)}}/{{len(DISAMBIG_CASES)}} keyword-variant searches "
                f"did NOT top-result the variant board:\\n"
                + "\\n".join(
                    f"  {{n!r}} (kw={{k!r}}) | want top={{e!r}} | got: {{g}} "
                    f"| collides w/ {{c}}"
                    for n, e, k, g, c in misses
                )
            )


if __name__ == "__main__":
    unittest.main()
'''
    TEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    TEST_OUT.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    boards = collect_boards()
    print(f"Scanned {len(boards)} boards", file=sys.stderr)
    cases = build_cases(boards)
    cases.sort()
    print(f"Cases with collisions: {len(cases)}", file=sys.stderr)

    emit_test(cases)
    print(f"Wrote {TEST_OUT.relative_to(REPO)}", file=sys.stderr)
    print()
    print("Cases (long_name → expected_top | collides_with_N_other_boards):")
    for long_name, expected, kw, collisions in cases:
        print(f"  {long_name!r:>55}  →  {expected!r:>30}  | kw={kw!r:>10} "
              f"| collides w/ {len(collisions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
