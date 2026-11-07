#!/usr/bin/env python3
"""Mine (board_id, name) tuples from per-board JSONs via jq, dedupe,
sort, randomly sample N=100 with a fixed seed, and embed in the
self-find test.

The self-find contract this corpus locks in: typing a board's
display name into the portal MUST return that board. Sample is
fixed by --seed for stable assertions.

Run:
    python tools/gen_board_names_corpus.py [--n 100] [--seed 0]
"""
from __future__ import annotations

import argparse
import pathlib
import random
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "site-src" / "public" / "boards"
TEST_OUT = REPO / "tests" / "test_board_names_self_find.py"


def collect_names() -> list[tuple[str, str]]:
    """One jq invocation per chunk of files. jq emits
    `<filename>|<name>` per file; we split, take board_id = basename
    without `.json`, drop empties."""
    paths = sorted(SOURCE.rglob("*.json"))
    print(f"Scanning {len(paths)} board JSONs via jq...", file=sys.stderr)

    JQ_PROG = r'input_filename as $f | "\($f)|\(.name // "")"'
    pairs: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
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
            if bid in seen_ids:
                continue
            seen_ids.add(bid)
            pairs.append((bid, name))

    pairs.sort()
    return pairs


def emit_test(sample: list[tuple[str, str]], seed: int, total: int) -> None:
    py_pairs = ",\n    ".join(f"({bid!r}, {name!r})" for bid, name in sample)
    body = f'''"""Auto-generated: {len(sample)} randomly-sampled (board_id, name)
pairs from the per-board JSON corpus. The contract this test locks
in — typing a board's display name into the portal's search MUST
return that board. 100/100 self-find or the build fails.

Regenerate with:
    python tools/gen_board_names_corpus.py --n {len(sample)} --seed {seed}

Mined via jq from site-src/public/boards/. Generation stats:
    total unique boards with names: {total}
    sample size:                    {len(sample)}
    seed:                           {seed}

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


# (board_id, expected_display_name)
BOARD_NAMES: list[tuple[str, str]] = [
    {py_pairs},
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
class BoardNamesSelfFindTests(unittest.TestCase):
    """100 random boards must each be findable by their display name
    via the portal's `board` mode (FTS5 boards_fts MATCH, LIMIT 20)."""

    def test_corpus_size(self) -> None:
        self.assertEqual(len(BOARD_NAMES), {len(sample)})

    def test_every_board_name_self_finds(self) -> None:
        items = [{{"text": name, "mode": "board"}} for _, name in BOARD_NAMES]
        results = _run_batch(items)
        self.assertEqual(len(results), len(BOARD_NAMES))

        misses = []
        for (want_bid, name), r in zip(BOARD_NAMES, results):
            ids = [b["row"]["board_id"] for b in r["data"]["boards"]]
            if want_bid not in ids:
                misses.append((name, want_bid, ids[:5]))
        if misses:
            self.fail(
                f"\\n{{len(misses)}}/{{len(BOARD_NAMES)}} board names failed to self-find:\\n"
                + "\\n".join(f"  {{n!r}} → want {{w!r}}, got top: {{g}}"
                             for n, w, g in misses)
            )


if __name__ == "__main__":
    unittest.main()
'''
    TEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    TEST_OUT.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    pairs = collect_names()
    n = min(args.n, len(pairs))
    sample = sorted(random.Random(args.seed).sample(pairs, n))

    print(f"Mined {len(pairs)} unique (board_id, name) pairs", file=sys.stderr)
    print(f"Sampled {n} with seed={args.seed}", file=sys.stderr)
    emit_test(sample, args.seed, len(pairs))
    print(f"Wrote {TEST_OUT.relative_to(REPO)}", file=sys.stderr)
    print()
    print("Sample (board_id → name):")
    for bid, name in sample:
        print(f"  {bid!r:>40}  →  {name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
