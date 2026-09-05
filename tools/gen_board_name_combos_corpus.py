#!/usr/bin/env python3
"""Mine 2-token combinations from board display names via jq, then
for each combo record which boards it could plausibly match.

A 2-token combo for a name like "Adafruit Feather M0" is one of:
  ("Adafruit", "Feather"), ("Adafruit", "M0"), ("Feather", "M0").
Joined with a space to form the query string. The "expected boards"
for the combo is the set of all boards whose name contains BOTH
tokens (case-insensitive substring), since multiple boards can
satisfy a single 2-token query.

Sample 100 combos with a fixed seed and embed in the test. The
contract: searching "tok1 tok2" must return AT LEAST ONE board
from the expected set in the top 20 results.

Run:
    python tools/gen_board_name_combos_corpus.py [--n 100] [--seed 0]
"""
from __future__ import annotations

import argparse
import itertools
import pathlib
import random
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "site-src" / "public" / "boards"
TEST_OUT = REPO / "tests" / "test_board_name_combos.py"

# Reject combos whose tokens are too short (e.g. "M0", "V1") or
# pure-numeric (would only land via prefix and likely match many
# unrelated boards). Keep ≥2 char tokens — `m7`, `m4`, `m0` are real
# microcontroller family tokens users might combine.
_NOISE_TOKEN_RE = re.compile(r"^[\d\W_]+$")

# Tokens too common to discriminate — they appear in dozens or
# hundreds of board names (sometimes via the frameworks column too)
# and a combo containing one of them is effectively a single-token
# query for the other token. Filtering these doesn't lose any
# search signal: a user who really wants "Arduino" + something can
# still find their board by typing just the something.
_UNIVERSAL_TOKENS: frozenset[str] = frozenset({
    # Pure schema / generic labels — neither a brand nor a variant
    # name. These don't disambiguate ("Arduino X" matches every
    # Arduino-framework board; "Pro" / "Mini" / "Plus" / "Lite" are
    # marketing modifiers that show up everywhere).
    "arduino", "generic", "pro", "mini", "plus", "lite",
    "board", "module", "kit", "dev",
    # NOTE: `ble`, `tiny`, `wifi`, `bluetooth`, `usb`, `otg`,
    # `nordic` are NOT filtered here — they ARE real variant /
    # connectivity / vendor tokens. "esp ble" and "sparkfun wifi"
    # are intended-to-work searches. The fact that they currently
    # miss is a ranking problem (engine.js orders by name not by
    # FTS5 rank), not a stop-word problem.
})


def _norm_for_substring(s: str) -> str:
    """Lower + strip hyphens/spaces so 'ESP32S3' matches 'ESP32-S3'
    when probing whether a board name contains both combo tokens."""
    return re.sub(r"[\s\-]+", "", s.lower())


def _tokenize(name: str) -> list[str]:
    """Split a board name into search-shaped tokens. Drops parenthesized
    groups (they're usually frequency/voltage annotations like
    `(ATmega1284P@8M,5V)` that aren't useful for query construction)."""
    no_parens = re.sub(r"\([^)]*\)", " ", name)
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", no_parens)
              if len(t) >= 2 and not _NOISE_TOKEN_RE.match(t)]
    return tokens


def collect_boards() -> list[tuple[str, str]]:
    paths = sorted(SOURCE.rglob("*.json"))
    JQ_PROG = r'input_filename as $f | "\($f)|\(.name // "")"'
    pairs: list[tuple[str, str]] = []
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
            pairs.append((bid, name))
    pairs.sort()
    return pairs


def build_combos(boards: list[tuple[str, str]]) -> dict[str, set[str]]:
    """For each unique 2-token combo, the set of board_ids whose name
    contains both tokens (case-insensitive, after hyphen-stripping —
    so 'ESP32S3' matches a board named 'ESP32-S3 Touch'). Filters out
    combos containing universal tokens that wouldn't discriminate.
    """
    combo_to_boards: dict[str, set[str]] = {}
    for bid, name in boards:
        toks = _tokenize(name)
        if len(toks) < 2:
            continue
        for a, b in itertools.combinations(toks, 2):
            if a.lower() in _UNIVERSAL_TOKENS or b.lower() in _UNIVERSAL_TOKENS:
                continue
            combo = f"{a} {b}"
            combo_to_boards.setdefault(combo, set()).add(bid)
    # Resolve "expected boards" via hyphen-normalized substring search
    # — a combo derived from board X might also be satisfied by board
    # Y if Y's name (after stripping hyphens/spaces) contains both
    # tokens.
    name_norm = [(bid, _norm_for_substring(name)) for bid, name in boards]
    for combo, sources in list(combo_to_boards.items()):
        a, b = combo.lower().split(" ", 1)
        an, bn = _norm_for_substring(a), _norm_for_substring(b)
        for bid, nn in name_norm:
            if an in nn and bn in nn:
                sources.add(bid)
    return combo_to_boards


def emit_test(sample: list[tuple[str, list[str]]], seed: int,
              total_combos: int, total_boards: int) -> None:
    items_py = ",\n    ".join(
        f"({combo!r}, {sorted(expected)!r})"
        for combo, expected in sample
    )
    body = f'''"""Auto-generated: {len(sample)} randomly-sampled 2-token name
combinations. Mined from per-board display names via jq + tokenizer.

For each combo, the expected-board list is the set of all boards
whose name contains BOTH tokens (case-insensitive substring). The
contract: searching the combo via `board` mode MUST return at least
one expected board in the top 20.

HISTORICAL CONTEXT: this test was originally failing 4 of 100 combos
(Tiny BLE, Nordic nRF52, WiFi Bluetooth, USB OTG) because engine.js
had been degraded from `ORDER BY rank` (FTS5 BM25) to `ORDER BY name`,
allegedly for perf. The alphabetical slice was dropping the most
relevant boards out of the LIMIT-20 window. Restoring BM25 in
site-src/src/search/engine.js fixed every failure. Perf cost was
real but livable then; same expected now. If a future refactor
removes ORDER BY rank, this test exists to catch the regression.

Regenerate with:
    python tools/gen_board_name_combos_corpus.py --n {len(sample)} --seed {seed}

Generation stats:
    boards scanned:        {total_boards}
    unique 2-token combos: {total_combos}
    sample size:           {len(sample)}
    seed:                  {seed}

Honors BOARDS_DB env override for local iteration; otherwise hits
the live published URL.
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


# (combo_text, expected_board_ids)
COMBOS: list[tuple[str, list[str]]] = [
    {items_py},
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
class BoardNameCombosTests(unittest.TestCase):
    """100 random 2-token name combinations must each surface at
    least one of the boards whose name contains both tokens."""

    def test_corpus_size(self) -> None:
        self.assertEqual(len(COMBOS), {len(sample)})

    def test_every_combo_finds_an_expected_board(self) -> None:
        items = [{{"text": combo, "mode": "board"}} for combo, _ in COMBOS]
        results = _run_batch(items)
        self.assertEqual(len(results), len(COMBOS))

        misses = []
        for (combo, expected), r in zip(COMBOS, results):
            got_ids = {{b["row"]["board_id"] for b in r["data"]["boards"]}}
            expected_set = set(expected)
            if not (got_ids & expected_set):
                misses.append((combo, sorted(expected)[:5], list(got_ids)[:5]))
        if misses:
            self.fail(
                f"\\n{{len(misses)}}/{{len(COMBOS)}} combos returned no expected board:\\n"
                + "\\n".join(f"  {{c!r}} | want one of {{e}} | got {{g}}"
                             for c, e, g in misses)
            )


if __name__ == "__main__":
    unittest.main()
'''
    TEST_OUT.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    boards = collect_boards()
    print(f"Scanned {len(boards)} boards", file=sys.stderr)
    combos = build_combos(boards)
    print(f"Unique 2-token combos: {len(combos)}", file=sys.stderr)

    # Sample combos directly (dedupe was already done by the dict).
    combo_keys = sorted(combos.keys())
    n = min(args.n, len(combo_keys))
    sample_keys = random.Random(args.seed).sample(combo_keys, n)
    sample_keys.sort()
    sample = [(k, sorted(combos[k])) for k in sample_keys]

    emit_test(sample, args.seed, len(combos), len(boards))
    print(f"Wrote {TEST_OUT.relative_to(REPO)}", file=sys.stderr)
    print()
    print("Sample (combo  →  #expected boards  →  first few):")
    for combo, expected in sample:
        first = ", ".join(expected[:3])
        more = f" +{len(expected)-3} more" if len(expected) > 3 else ""
        print(f"  {combo!r:>45}  →  {len(expected):>3}  →  {first}{more}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
