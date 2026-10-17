#!/usr/bin/env python3
"""Dump every board's display name to a file, sorted shortest first.

Quick way to surface poor display names — too short, too generic,
all-lowercase, or missing the vendor prefix. Run, scroll the top of
the output, and the lowest-quality names jump out.

Each line:
  <len:3>  <board_id padded>  →  <name>

Run:
    python tools/list_board_names_by_length.py [--out tmp/names.txt]
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO / "site-src" / "public" / "boards"


def collect() -> list[tuple[int, str, str]]:
    """Return list of (length, board_id, name) for every board JSON."""
    paths = sorted(SOURCE.rglob("*.json"))
    JQ_PROG = r'input_filename as $f | "\($f)|\(.name // "")"'
    out: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    BATCH = 200
    for i in range(0, len(paths), BATCH):
        batch = [str(p) for p in paths[i:i + BATCH]]
        r = subprocess.run(
            ["jq", "-r", JQ_PROG, *batch],
            capture_output=True, text=True, check=True,
        )
        for line in r.stdout.splitlines():
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
            out.append((len(name), bid, name))
    # Shortest first; tie-break by board_id for determinism.
    out.sort(key=lambda r: (r[0], r[1].lower()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "tmp" / "board_names_by_length.txt")
    args = ap.parse_args()

    rows = collect()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bid_w = max(len(b) for _, b, _ in rows)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(f"# {len(rows)} boards, shortest name first\n")
        fh.write(f"# {'len':>3}  {'board_id':<{bid_w}}  →  name\n")
        fh.write("#\n")
        for length, bid, name in rows:
            fh.write(f"  {length:>3}  {bid:<{bid_w}}  →  {name}\n")
    print(f"Wrote {len(rows)} names → {args.out.relative_to(REPO)}",
          file=sys.stderr)
    print(f"Shortest: {rows[0][0]} chars   Longest: {rows[-1][0]} chars",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
