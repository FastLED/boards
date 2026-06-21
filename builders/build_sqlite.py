#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Build a SQLite database from the merged record set produced by merge.py.

Schema (per-table indexes + FTS5 mirrors so both keys AND name fields are
fuzzy-searchable from the client, matching the design lifted from fbuild's
online-data SQLite + zackees memex sqlite-over-HTTP patterns):

    vid_vendor:
      vid    TEXT PRIMARY KEY    -- "303a" lowercase 4-hex
      vendor TEXT NOT NULL
      source TEXT NOT NULL        -- audit: where the entry came from

    vidpid:
      vidpid TEXT PRIMARY KEY    -- "303a4002" concatenated 8-hex
      vid    TEXT NOT NULL
      pid    TEXT NOT NULL
      product TEXT NOT NULL
      source  TEXT NOT NULL

    vid_vendor_fts: FTS5(vid, vendor)        -- indexes BOTH key & vendor
    vidpid_fts:     FTS5(vidpid, vid, pid, product)

Output is `<out>/site.db` (read by sql.js in the browser via HTTP range
requests; the file is intentionally small enough to download in full —
~200KB at the time of writing).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys


SCHEMA_SQL = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous  = OFF;

CREATE TABLE vid_vendor (
  vid    TEXT PRIMARY KEY,
  vendor TEXT NOT NULL,
  source TEXT NOT NULL
);
CREATE INDEX idx_vid_vendor_vendor ON vid_vendor (vendor COLLATE NOCASE);

CREATE TABLE vidpid (
  vidpid  TEXT PRIMARY KEY,
  vid     TEXT NOT NULL,
  pid     TEXT NOT NULL,
  product TEXT NOT NULL,
  source  TEXT NOT NULL
);
CREATE INDEX idx_vidpid_vid     ON vidpid (vid);
CREATE INDEX idx_vidpid_product ON vidpid (product COLLATE NOCASE);

-- FTS5 mirrors: external-content tables that follow the base tables.
-- Both the key columns (vid/vidpid/pid) and the human-name columns are
-- indexed so the demo HTML can fuzzy-match either side.
CREATE VIRTUAL TABLE vid_vendor_fts
  USING fts5(vid, vendor, content='vid_vendor', content_rowid='rowid');

CREATE VIRTUAL TABLE vidpid_fts
  USING fts5(vidpid, vid, pid, product, content='vidpid', content_rowid='rowid');
"""


def build(merged_path: pathlib.Path, out_path: pathlib.Path) -> dict[str, int]:
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    vid_vendor = merged.get("vid_vendor") or {}
    vidpid     = merged.get("vidpid") or {}

    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(out_path)
    try:
        conn.executescript(SCHEMA_SQL)

        conn.executemany(
            "INSERT INTO vid_vendor (vid, vendor, source) VALUES (?, ?, ?)",
            [(vid, rec["vendor"], rec.get("source", "")) for vid, rec in vid_vendor.items()],
        )
        conn.executemany(
            "INSERT INTO vidpid (vidpid, vid, pid, product, source) "
            "VALUES (?, ?, ?, ?, ?)",
            [(key, rec["vid"], rec["pid"], rec["product"], rec.get("source", ""))
             for key, rec in vidpid.items()],
        )
        # Populate the FTS mirrors.
        conn.execute(
            "INSERT INTO vid_vendor_fts (rowid, vid, vendor) "
            "SELECT rowid, vid, vendor FROM vid_vendor"
        )
        conn.execute(
            "INSERT INTO vidpid_fts (rowid, vidpid, vid, pid, product) "
            "SELECT rowid, vidpid, vid, pid, product FROM vidpid"
        )
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()

    size = out_path.stat().st_size
    print(f"build_sqlite: wrote {out_path} ({size:,} bytes, "
          f"{len(vid_vendor)} vendors, {len(vidpid)} products)",
          file=sys.stderr)
    return {"vendors": len(vid_vendor), "products": len(vidpid), "bytes": size}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--merged", required=True, type=pathlib.Path,
                   help="merged.json produced by merge.py")
    p.add_argument("--out",    required=True, type=pathlib.Path,
                   help="output SQLite path (e.g. site/site.db)")
    args = p.parse_args()
    build(args.merged, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
