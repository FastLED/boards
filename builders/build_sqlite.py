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
      board_id, layer, sublayer, name, vendor, mcu,
      frequency_mhz, flash_kb, ram_kb,
      upload_speed, upload_protocol, core, variant,
      homepage, frameworks (CSV), connectivity (CSV), debug_tool,
      vidpids (pretty CSV), upstream_blob
      -- NO raw JSON column. Users follow upstream_blob to view originals.
    boards_fts: FTS5(board_id, name, vendor, mcu, sublayer,
                     frameworks, connectivity)

Output is `<out>/boards.db` — the browser uses sql.js-httpvfs to read it via
HTTP Range requests, so only the pages a query actually touches travel
the wire. The DB can grow to many MB without affecting page-load latency.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys


SCHEMA_SQL = """
-- page_size must be set BEFORE any table exists. 1024 is sqlite-wasm-http's
-- recommended size — smaller pages = finer-grained HTTP range fetches and
-- better HTTP/2 multiplexing (typical query reads 5-10 pages in parallel
-- instead of 5-10 sequential larger ones).
PRAGMA page_size    = 1024;
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

-- Per-board structured metadata. Common useful fields are projected into
-- their own columns so the search path doesn't have to skip past anything
-- — the table stays dense and every page touched returns multiple rows
-- of useful data. The raw upstream JSON is NOT stored here; users follow
-- the `upstream_blob` URL to view the original on GitHub.
CREATE TABLE boards (
  board_id        TEXT NOT NULL,
  layer           TEXT NOT NULL,
  sublayer        TEXT NOT NULL,
  name            TEXT NOT NULL,
  vendor          TEXT,
  mcu             TEXT,
  architecture    TEXT,        -- e.g. "cortex-m7", "xtensa", "riscv", "avr"
  bit_width       INTEGER,     -- 8 / 16 / 32
  frequency_mhz   INTEGER,
  flash_kb        INTEGER,
  ram_kb          INTEGER,
  upload_speed    INTEGER,
  upload_protocol TEXT,
  core            TEXT,
  variant         TEXT,
  homepage        TEXT,
  frameworks      TEXT,        -- CSV: "arduino,espidf"
  connectivity    TEXT,        -- CSV: "bluetooth,can,ethernet,wifi"
  debug_tool      TEXT,
  aliases         TEXT,        -- CSV of alternate IDs the board responds to:
                               -- STM32duino menu.pnum part numbers, Zephyr
                               -- variants, OpenOCD board names, ESP8266
                               -- build.board macros. Surfaces in search so
                               -- typing `GENERIC_F412ZEJX`, `stm32l476g_disco`,
                               -- or `ESP8266_WEMOS_D1MINI` finds the right board.
  keywords        TEXT,        -- space-joined soup of every search-shaped
                               -- string value found in the per-board JSON
                               -- (filtered: no URLs, templates, or pure
                               -- numbers). Catches the long tail of
                               -- compile-flag fragments etc.
  vidpids         TEXT,
  upstream_blob   TEXT
);
CREATE INDEX idx_boards_board_id ON boards (board_id COLLATE NOCASE);
CREATE INDEX idx_boards_layer    ON boards (layer, sublayer);

-- FTS5 mirror so name / vendor / mcu / architecture / connectivity /
-- frameworks searches stay cheap under byte-range loading (LIKE '%foo%'
-- would scan every page). Architecture is stored with `-` separators
-- ("cortex-m7") so the default unicode61 tokenizer splits it into
-- ["cortex", "m7"], letting users search either token. `aliases` and
-- `keywords` widen reach so STM32duino pnum variants, Zephyr aliases,
-- ESP8266 build macros, compile-flag fragments, and the like land hits.
CREATE VIRTUAL TABLE boards_fts USING fts5(
  board_id, name, vendor, mcu, architecture, sublayer,
  frameworks, connectivity, aliases, keywords,
  content='boards', content_rowid='rowid'
);

-- Many-to-many junction between boards and VID:PIDs. Each row maps one
-- board to one VID:PID it can present on the bus. `origin` records
-- whether the link came from the board's upstream JSON ('upstream') or
-- was filled in by a curated rule in other/overrides.json
-- ('curated:<rule-id>'). The PRIMARY KEY makes upstream-wins polyfill
-- behaviour automatic — Path 1 inserts upstream rows first, Path 2
-- does INSERT OR IGNORE so curated rules can't overwrite them.
--
-- The `vidpid` table stays independent: it carries every known VID:PID
-- name (including USB devices unrelated to embedded boards). Queries
-- that just identify a USB device hit `vidpid` alone; queries that ask
-- "which board uses this VID:PID" LEFT JOIN through this junction.
CREATE TABLE board_vidpids (
  board_rowid INTEGER NOT NULL,
  vid         TEXT    NOT NULL,
  pid         TEXT    NOT NULL,
  origin      TEXT    NOT NULL,
  PRIMARY KEY (board_rowid, vid, pid)
);
CREATE INDEX idx_board_vidpids_vidpid ON board_vidpids (vid, pid);
"""


def _board_rows(boards: list[dict]) -> list[tuple]:
    """Returns rows for the structured `boards` table."""
    rows = []
    for b in boards:
        vidpids = ", ".join(f"{v}:{p}" for v, p in (b.get("vidpids") or []))
        rows.append((
            b["board_id"], b["layer"], b["sublayer"], b["name"],
            b.get("vendor"), b.get("mcu"),
            b.get("architecture"), b.get("bit_width"),
            b.get("frequency_mhz"),
            b.get("flash_kb"), b.get("ram_kb"),
            b.get("upload_speed"), b.get("upload_protocol"),
            b.get("core"), b.get("variant"),
            b.get("homepage"), b.get("frameworks"),
            b.get("connectivity"), b.get("debug_tool"),
            b.get("aliases"), b.get("keywords"),
            vidpids or None, b.get("upstream_blob"),
        ))
    return rows


def _board_matches_rule(board: dict, match: dict[str, str]) -> bool:
    """Decide whether a board satisfies a single curated rule's
    `match_boards` predicate. Supported keys (mix-and-match):

      board_id_glob: "teensy*"   — fnmatch against board_id (case-insensitive)
      mcu_glob:      "imxrt*"    — fnmatch against mcu (case-insensitive)
      vendor:        "PJRC"      — exact vendor (case-insensitive)
      vendor_glob:   "PJRC*"     — fnmatch against vendor (case-insensitive)
      sublayer:      "teensy"    — exact sublayer (case-insensitive)
      sublayer_glob: "teensy*"   — fnmatch against sublayer
      layer:         "platformio"|"arduino"

    Multiple keys are ANDed. A board with a missing field (e.g. no MCU
    set) never satisfies a glob predicate on that field.
    """
    import fnmatch
    for key, pattern in match.items():
        if not isinstance(pattern, str):
            return False
        pat_lc = pattern.lower()
        if key == "board_id_glob":
            v = (board.get("board_id") or "").lower()
            if not fnmatch.fnmatchcase(v, pat_lc):
                return False
        elif key == "mcu_glob":
            v = (board.get("mcu") or "").lower()
            if not v or not fnmatch.fnmatchcase(v, pat_lc):
                return False
        elif key == "vendor":
            v = (board.get("vendor") or "").lower()
            if v != pat_lc:
                return False
        elif key == "vendor_glob":
            v = (board.get("vendor") or "").lower()
            if not v or not fnmatch.fnmatchcase(v, pat_lc):
                return False
        elif key == "sublayer":
            if (board.get("sublayer") or "").lower() != pat_lc:
                return False
        elif key == "sublayer_glob":
            v = (board.get("sublayer") or "").lower()
            if not fnmatch.fnmatchcase(v, pat_lc):
                return False
        elif key == "layer":
            if (board.get("layer") or "") != pattern:
                return False
        else:
            # Unknown predicate keys make the rule a no-op for safety.
            return False
    return True


def _upstream_junction_rows(boards: list[dict]) -> list[tuple[int, str, str, str]]:
    """Path 1: yield (board_rowid, vid, pid, 'upstream') for each
    board's own upstream vidpids array. board_rowid matches the insert
    order of the boards table (1..N)."""
    rows: list[tuple[int, str, str, str]] = []
    for i, b in enumerate(boards, start=1):
        for vp in (b.get("vidpids") or []):
            if isinstance(vp, (list, tuple)) and len(vp) >= 2:
                vid, pid = vp[0], vp[1]
                if isinstance(vid, str) and isinstance(pid, str):
                    rows.append((i, vid, pid, "upstream"))
    return rows


def _curated_junction_rows(boards: list[dict],
                            rules: list[dict]
                            ) -> list[tuple[int, str, str, str]]:
    """Path 2: expand each curated rule into (board_rowid, vid, pid,
    'curated:<rule-id>') candidates. Order doesn't matter; the
    INSERT OR IGNORE in build() makes upstream rows win on conflict."""
    rows: list[tuple[int, str, str, str]] = []
    for rule in rules:
        match = rule.get("match_boards") or {}
        rule_id = rule.get("id") or "unknown"
        origin = f"curated:{rule_id}"
        matched_rowids = [
            i for i, b in enumerate(boards, start=1)
            if _board_matches_rule(b, match)
        ]
        if not matched_rowids:
            print(f"build_sqlite: rule {rule_id!r} matched 0 boards",
                  file=sys.stderr)
            continue
        for vidpid_key in rule.get("vidpids") or []:
            vid, pid = vidpid_key[:4], vidpid_key[4:]
            for rowid in matched_rowids:
                rows.append((rowid, vid, pid, origin))
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

    # Curated polyfill rules: links between (vid, pid) and one or more
    # boards for boards whose upstream JSON doesn't carry hwids. Already
    # validated by extract_other.py.
    link_rules = merged.get("vidpid_board_links") or []

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
                "mcu, architecture, bit_width, frequency_mhz, flash_kb, "
                "ram_kb, upload_speed, upload_protocol, core, variant, "
                "homepage, frameworks, connectivity, debug_tool, "
                "aliases, keywords, vidpids, upstream_blob) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _board_rows(boards),
            )

            # board_vidpids junction. Path 1 (upstream) runs first so its
            # rows always exist before Path 2 attempts to fill polyfill
            # entries; the PRIMARY KEY + OR IGNORE makes upstream win on
            # conflict so curated rules can never silently overwrite real
            # upstream data.
            upstream_rows = _upstream_junction_rows(boards)
            if upstream_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO board_vidpids "
                    "(board_rowid, vid, pid, origin) VALUES (?, ?, ?, ?)",
                    upstream_rows,
                )
            curated_candidates = _curated_junction_rows(boards, link_rules)
            curated_inserted_pre = conn.execute(
                "SELECT COUNT(*) FROM board_vidpids WHERE origin <> 'upstream'"
            ).fetchone()[0]
            if curated_candidates:
                conn.executemany(
                    "INSERT OR IGNORE INTO board_vidpids "
                    "(board_rowid, vid, pid, origin) VALUES (?, ?, ?, ?)",
                    curated_candidates,
                )
            curated_inserted_post = conn.execute(
                "SELECT COUNT(*) FROM board_vidpids WHERE origin <> 'upstream'"
            ).fetchone()[0]
            print(
                f"build_sqlite: board_vidpids: "
                f"{len(upstream_rows)} upstream + "
                f"{curated_inserted_post - curated_inserted_pre} curated "
                f"({len(curated_candidates) - (curated_inserted_post - curated_inserted_pre)} "
                f"polyfill-skipped because upstream already supplied them)",
                file=sys.stderr,
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
        conn.execute(
            "INSERT INTO boards_fts (rowid, board_id, name, vendor, mcu, "
            "                        architecture, sublayer, frameworks, "
            "                        connectivity, aliases, keywords) "
            "SELECT rowid, board_id, name, COALESCE(vendor,''), "
            "       COALESCE(mcu,''), COALESCE(architecture,''), sublayer, "
            "       COALESCE(frameworks,''), COALESCE(connectivity,''), "
            "       COALESCE(aliases,''), COALESCE(keywords,'') "
            "FROM boards"
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
                   help="output SQLite path (e.g. site/boards.db)")
    args = p.parse_args()
    build(args.merged, args.out, args.boards)
    return 0


if __name__ == "__main__":
    sys.exit(main())
