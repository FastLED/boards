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

    boards:
      board_id     TEXT          -- e.g. "esp32dev"
      layer        TEXT          -- "platformio" | "arduino"
      sublayer     TEXT          -- platform name or core slug
      name         TEXT          -- "Espressif ESP32 Dev Module"
      vendor       TEXT          -- nullable
      mcu          TEXT          -- nullable
      frequency_mhz INTEGER      -- nullable
      vidpids      TEXT          -- "303a:0002, 1234:5678" pretty CSV
      json_url     TEXT          -- relative URL into the site bundle
      upstream_blob TEXT         -- upstream link (may be repo-root for arduino)

Output is `<out>/site.db` (read by sql.js in the browser via HTTP range
requests; the file is intentionally small enough to download in full —
~200KB at the time of writing, ~600KB-1MB once `boards` is populated).
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

-- vidpid is multi-row per key: one row marked is_primary=1 is the
-- merger's preferred name; additional rows (is_primary=0) carry
-- alternate names for genuinely-different products that share the same
-- VID:PID (e.g. several RP2040 boards all using Raspberry Pi's default
-- Pico PIDs because their vendors never registered their own).
CREATE TABLE vidpid (
  vidpid     TEXT NOT NULL,        -- "303a4002" concatenated 8-hex
  vid        TEXT NOT NULL,
  pid        TEXT NOT NULL,
  product    TEXT NOT NULL,
  source     TEXT NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_vidpid_vidpid  ON vidpid (vidpid);
CREATE INDEX idx_vidpid_vid     ON vidpid (vid);
CREATE INDEX idx_vidpid_product ON vidpid (product COLLATE NOCASE);
CREATE INDEX idx_vidpid_primary ON vidpid (vidpid, is_primary DESC);

-- FTS5 mirrors: external-content tables that follow the base tables.
-- Both the key columns (vid/vidpid/pid) and the human-name columns are
-- indexed so the demo HTML can fuzzy-match either side.
CREATE VIRTUAL TABLE vid_vendor_fts
  USING fts5(vid, vendor, content='vid_vendor', content_rowid='rowid');

CREATE VIRTUAL TABLE vidpid_fts
  USING fts5(vidpid, vid, pid, product, content='vidpid', content_rowid='rowid');

-- Per-board metadata: one row per upstream board JSON. Each row carries a
-- relative json_url that points at the copy site.py stages into the
-- published bundle (e.g. "boards/platformio/espressif32/boards/esp32dev.json"),
-- so the portal "View JSON" button is just a static fetch.
CREATE TABLE boards (
  board_id      TEXT NOT NULL,
  layer         TEXT NOT NULL,
  sublayer      TEXT NOT NULL,
  name          TEXT NOT NULL,
  vendor        TEXT,
  mcu           TEXT,
  frequency_mhz INTEGER,
  vidpids       TEXT,
  json_url      TEXT NOT NULL,
  upstream_blob TEXT
);
CREATE INDEX idx_boards_name     ON boards (name COLLATE NOCASE);
CREATE INDEX idx_boards_board_id ON boards (board_id COLLATE NOCASE);
CREATE INDEX idx_boards_layer    ON boards (layer, sublayer);
"""


def _board_rows(boards: list[dict]) -> list[tuple]:
    rows = []
    for b in boards:
        vidpids = ", ".join(f"{v}:{p}" for v, p in (b.get("vidpids") or []))
        json_url = f"boards/{b['layer']}/{b['src_relpath']}"
        rows.append((
            b["board_id"], b["layer"], b["sublayer"], b["name"],
            b.get("vendor"), b.get("mcu"), b.get("frequency_mhz"),
            vidpids or None, json_url, b.get("upstream_blob"),
        ))
    return rows


def build(merged_path: pathlib.Path, out_path: pathlib.Path,
          boards_path: pathlib.Path | None = None) -> dict[str, int]:
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    vid_vendor = merged.get("vid_vendor") or {}
    # vidpid is now a LIST of row dicts (v2 schema). Tolerate the old v1
    # dict shape (`{key: rec}`) for callers that still emit the older
    # format — convert to a list with everything marked as primary.
    vidpid_raw = merged.get("vidpid") or []
    if isinstance(vidpid_raw, dict):
        vidpid = [{**rec, "is_primary": True} for rec in vidpid_raw.values()]
    else:
        vidpid = vidpid_raw

    boards: list[dict] = []
    if boards_path and boards_path.is_file():
        boards = (json.loads(boards_path.read_text(encoding="utf-8"))
                  .get("boards") or [])

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
            "INSERT INTO vidpid (vidpid, vid, pid, product, source, is_primary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(rec["vidpid"], rec["vid"], rec["pid"], rec["product"],
              rec.get("source", ""), 1 if rec.get("is_primary") else 0)
             for rec in vidpid],
        )
        if boards:
            conn.executemany(
                "INSERT INTO boards (board_id, layer, sublayer, name, vendor, "
                "mcu, frequency_mhz, vidpids, json_url, upstream_blob) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _board_rows(boards),
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
          f"{len(vid_vendor)} vendors, {len(vidpid)} products, {len(boards)} boards)",
          file=sys.stderr)
    return {"vendors": len(vid_vendor), "products": len(vidpid),
            "boards": len(boards), "bytes": size}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--merged", required=True, type=pathlib.Path,
                   help="merged.json produced by merge.py")
    p.add_argument("--boards", type=pathlib.Path, default=None,
                   help="boards.json produced by extract_boards.py (optional)")
    p.add_argument("--out",    required=True, type=pathlib.Path,
                   help="output SQLite path (e.g. site/site.db)")
    args = p.parse_args()
    build(args.merged, args.out, args.boards)
    return 0


if __name__ == "__main__":
    sys.exit(main())
