#!/usr/bin/env python3
"""Sweep 10 BM25 column-weight configurations against the
similar-names test corpus and a harder ablation corpus. Reports
top-1, top-3, MRR for each config under both metrics.

Why two metrics:
  - Exact-name self-find tops out at 100% under default weights — no
    headroom for weight tuning to win. Reported to confirm no
    weight config DEGRADES it.
  - Ablation (drop one token from each name) creates ranking
    contention — multiple boards plausibly match, so weight balance
    matters. This is where tuning visibly helps or hurts.

boards_fts column order (from build_sqlite.py):
  board_id, name, vendor, mcu, architecture, sublayer,
  frameworks, connectivity, aliases, keywords

Run:
    python tools/bm25_weight_sweep.py
"""
from __future__ import annotations

import os
import pathlib
import random
import re
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get(
    "BOARDS_DB",
    str(pathlib.Path(os.environ["TEMP" if os.name == "nt" else "TMPDIR"])
        / "fastled-boards-local.db"),
)

# Same JS-side ftsQuery() + same stop words as the live engine.
_STOP = frozenset({
    "info", "warn", "error", "verbose",
    "default", "disable", "disabled", "enable", "enabled",
    "none", "on", "off", "all", "custom",
    "minimal", "small", "fast",
    "boot", "mode", "port", "os", "sdk", "ld", "fp",
})


def fts_query(s: str) -> str | None:
    tokens = re.sub(r"[^a-z0-9_\s]", " ", s.lower()).split()
    tokens = [t for t in tokens if t and t not in _STOP]
    if not tokens:
        return None
    return " ".join(t + "*" for t in tokens)


# Weights ordered to match the boards_fts column declaration.
COLS = ["board_id", "name", "vendor", "mcu", "architecture", "sublayer",
        "frameworks", "connectivity", "aliases", "keywords"]
def make_order_clause(weights: list[float]) -> str:
    assert len(weights) == len(COLS)
    return "ORDER BY bm25(boards_fts, " + ", ".join(f"{w}" for w in weights) + ")"


# Higher weight → matches in that column contribute more to relevance
# (higher BM25 score → higher rank). Default is 1.0 across the board.
CONFIGS: list[tuple[str, list[float]]] = [
    # name              board_id name vendor mcu arch sub frameworks conn aliases keywords
    ("baseline_default",  [ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
    ("name_5x",           [ 1.0, 5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
    ("name_10x",          [ 1.0,10.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
    ("name+id_5x",        [ 5.0, 5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
    ("keywords_quiet",    [ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.1]),
    ("aliases+name_kw_q", [ 1.0, 5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 0.2]),
    ("strict_name_only",  [ 0.1,10.0, 0.1, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0, 0.1]),
    ("identity_heavy",    [10.0, 5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 5.0, 0.5]),
    ("balanced_moderate", [ 1.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5]),
    ("vendor+name",       [ 1.0, 5.0, 3.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.2]),
]


def load_cases():
    """Read SIMILAR_NAME_CASES from the generated test file."""
    spec = __import__("importlib.util").util.spec_from_file_location(
        "snt", str(REPO / "tests" / "test_similar_names_top1.py")
    )
    mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SIMILAR_NAME_CASES


def evaluate(conn, cases, order_clause: str, ablate: bool):
    """Run each case with the given ORDER BY clause; compute top-1,
    top-3, MRR. If ablate=True, drop the LAST token of the query (a
    harder query that exposes ranking quality)."""
    top1 = top3 = 0
    rr_sum = 0.0
    for bid, name, _peers in cases:
        tokens = re.findall(r"[A-Za-z0-9]+", name)
        if ablate:
            if len(tokens) < 2:
                continue  # skip un-ablatable
            tokens = tokens[:-1]
        query_text = " ".join(tokens)
        q = fts_query(query_text)
        if q is None:
            continue
        sql = (
            f"SELECT b.board_id, b.name FROM boards b "
            f"JOIN boards_fts f ON f.rowid = b.rowid "
            f"WHERE boards_fts MATCH ? {order_clause} LIMIT 20"
        )
        try:
            rows = conn.execute(sql, (q,)).fetchall()
        except sqlite3.OperationalError:
            return None
        # For non-ablated, accept any board with same NAME as a hit.
        # For ablated, accept the exact source board_id (the harder
        # criterion since multiple boards match the truncated query).
        want_name_lc = name.lower()
        rank = None
        for i, (got_bid, got_name) in enumerate(rows):
            if ablate:
                if got_bid == bid:
                    rank = i + 1; break
            else:
                if got_name.lower() == want_name_lc:
                    rank = i + 1; break
        if rank is not None:
            if rank == 1: top1 += 1
            if rank <= 3: top3 += 1
            rr_sum += 1.0 / rank
    n_evaluated = sum(1 for _, name, _ in cases
                      if len(re.findall(r"[A-Za-z0-9]+", name))
                         >= (2 if ablate else 1))
    return {
        "n":     n_evaluated,
        "top_1": 100 * top1 / n_evaluated,
        "top_3": 100 * top3 / n_evaluated,
        "mrr":   rr_sum / n_evaluated,
    }


def main() -> int:
    cases = load_cases()
    conn = sqlite3.connect(DB_PATH)

    print(f"Loaded {len(cases)} similar-name cases from "
          "tests/test_similar_names_top1.py")
    print(f"DB: {DB_PATH}")
    print()

    for metric_label, ablate in (("EXACT_NAME", False),
                                 ("ABLATED (drop last token)", True)):
        print(f"=== {metric_label} ===")
        print(f"  {'config':>22} {'top_1':>8} {'top_3':>8} {'MRR':>8}")
        print(f"  {'-'*22} {'-'*8} {'-'*8} {'-'*8}")
        for name, weights in CONFIGS:
            order = make_order_clause(weights)
            m = evaluate(conn, cases, order, ablate)
            if m is None:
                print(f"  {name!r:>22} (skipped — SQL error)")
                continue
            print(f"  {name:>22} {m['top_1']:>7.1f}% "
                  f"{m['top_3']:>7.1f}% {m['mrr']:>7.3f}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
