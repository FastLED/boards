#!/usr/bin/env python3
"""Mine display-name self-find cases where the corpus contains
similar competitor names (token-Jaccard ≥ threshold). These are the
cases where ranking quality matters — when multiple boards plausibly
match a query, the right one needs to be at the top.

For each qualifying board, embed (board_id, name, similar_peer_ids)
into a test that asserts the board's exact display name returns
either itself or a name-twin at position 0.

Run:
    python tools/gen_similar_names_corpus.py [--threshold 0.5] [--n 200]
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
TEST_OUT = REPO / "tests" / "test_similar_names_top1.py"

_TOK_RE = re.compile(r"[A-Za-z0-9]+")


def _toks(name: str) -> frozenset[str]:
    return frozenset(t.lower() for t in _TOK_RE.findall(name))


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


def find_similar_groups(
    boards: list[tuple[str, str]],
    threshold: float,
) -> list[tuple[str, str, list[str]]]:
    """For each board with ≥1 peer at Jaccard ≥ threshold, return
    (board_id, name, sorted_peer_ids)."""
    tok_by_bid = {bid: _toks(name) for bid, name in boards}
    out: list[tuple[str, str, list[str]]] = []
    for bid, name in boards:
        my = tok_by_bid[bid]
        if len(my) < 2:
            continue
        peers: list[str] = []
        for other_bid, other_name in boards:
            if other_bid == bid:
                continue
            other = tok_by_bid[other_bid]
            if not other:
                continue
            union = my | other
            if not union:
                continue
            jac = len(my & other) / len(union)
            if jac >= threshold:
                peers.append(other_bid)
        if peers:
            out.append((bid, name, sorted(peers)))
    return out


def emit_test(sample: list[tuple[str, str, list[str]]],
              threshold: float, seed: int) -> None:
    py_cases = ",\n    ".join(
        f"({bid!r}, {name!r}, {peers!r})" for bid, name, peers in sample
    )
    body = f'''"""Auto-generated similar-names self-find corpus.

Each entry is (board_id, name, similar_peer_ids) where the peers'
names share ≥ {threshold:.0%} of their tokens with `name`. This is the
contention zone where ranking quality matters — multiple boards
plausibly match a query, but the queried board's exact display name
must still come back at position 0 (or tie via a duplicate
board_id under another upstream).

Regenerate with:
    python tools/gen_similar_names_corpus.py --threshold {threshold} --n {len(sample)} --seed {seed}

Sample: {len(sample)}.

METRIC
  top_1_pct: of the {len(sample)} cases, fraction where rank-1 result
             has the SAME display name (case-insensitive) as the
             query. Captures both exact self-find and PlatformIO/
             Arduino duplicates (same physical board).
  mrr:       mean reciprocal rank — average of 1/rank where rank is
             the 1-based position of the first same-name hit. 0 if
             not in top 20.

The test asserts a floor on top_1_pct so a future change that
degrades ranking fails CI. Tune the floor when weights change.
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


# (board_id, name, similar_peer_board_ids)
SIMILAR_NAME_CASES: list[tuple[str, str, list[str]]] = [
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
            capture_output=True, text=True, timeout=600, check=True,
        )
    finally:
        os.unlink(batch_path)
    return json.loads(proc.stdout)


def _compute_metrics(cases, results):
    """top_1 % + MRR over (case, result) pairs. A hit is a returned
    board whose name matches the queried name (case-insensitive)."""
    top1_hits = 0
    rr_sum = 0.0
    misses = []
    for (bid, name, peers), r in zip(cases, results):
        boards = r["data"]["boards"]
        want_lc = name.lower()
        rank = None
        for i, b in enumerate(boards):
            if b["row"]["name"].lower() == want_lc:
                rank = i + 1
                break
        if rank == 1:
            top1_hits += 1
        if rank is not None:
            rr_sum += 1.0 / rank
        else:
            misses.append((name, bid, [b["row"]["board_id"]
                                       for b in boards[:3]]))
    n = len(cases)
    return {{
        "top_1_pct": 100 * top1_hits / n,
        "mrr": rr_sum / n,
        "misses": misses,
    }}


@unittest.skipIf(BUN is None, "bun runtime not installed")
class SimilarNamesTop1Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        items = [{{"text": name, "mode": "board"}}
                 for _, name, _ in SIMILAR_NAME_CASES]
        results = _run_batch(items)
        assert len(results) == len(SIMILAR_NAME_CASES)
        cls.metrics = _compute_metrics(SIMILAR_NAME_CASES, results)
        print(f"\\n[similar-names] cases={{len(SIMILAR_NAME_CASES)}} "
              f"top_1={{cls.metrics['top_1_pct']:.1f}}% "
              f"mrr={{cls.metrics['mrr']:.3f}}",
              file=sys.stderr)

    def test_corpus_size(self) -> None:
        self.assertEqual(len(SIMILAR_NAME_CASES), {len(sample)})

    def test_top_1_floor(self) -> None:
        # Floor set at 80% — the current default-BM25 baseline. Move
        # this floor up after a tuning PR proves the new weights are
        # stable.
        FLOOR = 80.0
        self.assertGreaterEqual(
            self.metrics["top_1_pct"], FLOOR,
            f"top-1 hit rate {{self.metrics['top_1_pct']:.1f}}% < {{FLOOR}}% floor.\\n"
            + (f"First {{min(len(self.metrics['misses']), 10)}} misses:\\n"
               + "\\n".join(f"  {{n!r}} (want {{b}}) → top: {{g}}"
                            for n, b, g in self.metrics["misses"][:10])
               if self.metrics["misses"] else "")
        )


if __name__ == "__main__":
    unittest.main()
'''
    TEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    TEST_OUT.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    boards = collect_boards()
    print(f"Scanned {len(boards)} boards", file=sys.stderr)
    groups = find_similar_groups(boards, args.threshold)
    print(f"Boards with ≥1 peer at Jaccard ≥ {args.threshold}: {len(groups)}",
          file=sys.stderr)

    groups.sort()
    n = min(args.n, len(groups))
    sample = sorted(random.Random(args.seed).sample(groups, n))
    emit_test(sample, args.threshold, args.seed)
    print(f"Wrote {TEST_OUT.relative_to(REPO)} with {n} cases",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
