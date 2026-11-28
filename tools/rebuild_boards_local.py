"""Locally rebuild boards.db from per-board JSONs already staged at
site-src/public/boards/.

Used as the fast inner loop for search-corpus iteration: the full
site builder needs all five data-branch worktrees + the merge step,
but we only need the boards table + boards_fts to validate search
behavior. This script:

  1. Runs builders/extract_boards.py against site-src/public/boards/
     to produce a boards.json with the new aliases + keywords fields.
  2. Pulls the live boards.db as a base (so vid_vendor + vidpid +
     board_vidpids tables stay intact for any downstream check).
  3. DROPs the boards + boards_fts tables in the local copy.
  4. RE-CREATEs them with the new schema (lifted verbatim from
     build_sqlite.py) and re-populates from boards.json.
  5. VACUUMs and writes to --out (default tmp/local-boards.db).

The output file is then what tests with BOARDS_DB=<path> point at.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCE_BOARDS = REPO / "site-src" / "public" / "boards"
LIVE_DB_URL = "https://fastled.github.io/boards/boards.db"


def _download_live(into: pathlib.Path) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        LIVE_DB_URL,
        headers={"Accept-Encoding": "identity",
                 "User-Agent": "rebuild-boards-local/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        into.write_bytes(resp.read())


def _run_extract(boards_root: pathlib.Path, out: pathlib.Path) -> None:
    cmd = [
        sys.executable, str(REPO / "builders" / "extract_boards.py"),
        "--in", str(boards_root), "--out", str(out),
    ]
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def _boards_schema() -> str:
    """Lift the boards + boards_fts schema out of build_sqlite.py so we
    don't drift. Reads the file and pulls out the CREATE statements
    between the boards table and the board_vidpids comment block."""
    src = (REPO / "builders" / "build_sqlite.py").read_text(encoding="utf-8")
    start = src.index("CREATE TABLE boards (")
    end = src.index("-- Many-to-many junction")
    boards_schema = src[start:end]
    # Also need vendor_prefix_results (the precomputed fast-path table).
    pre_start = src.index("CREATE TABLE vendor_prefix_results (")
    pre_end = src.index('"""', pre_start)
    prefix_schema = src[pre_start:pre_end]
    return boards_schema + "\n" + prefix_schema


def rebuild(out_path: pathlib.Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rebuild-boards-"))
    try:
        boards_json = tmp / "boards.json"
        _run_extract(SOURCE_BOARDS, boards_json)
        records = json.loads(boards_json.read_text(encoding="utf-8"))
        boards = records.get("boards") or []
        print(f"extracted {len(boards)} boards (with aliases + keywords)",
              file=sys.stderr)

        # Pull a live copy and rebuild boards-only in it.
        local_db = tmp / "boards.db"
        print("downloading live boards.db as base…", file=sys.stderr)
        _download_live(local_db)
        print(f"  base size: {local_db.stat().st_size:,} bytes", file=sys.stderr)

        conn = sqlite3.connect(local_db)
        try:
            conn.execute("DROP TABLE IF EXISTS boards_fts")
            conn.execute("DROP TABLE IF EXISTS boards")
            conn.execute("DROP TABLE IF EXISTS vendor_prefix_results")
            conn.executescript(_boards_schema())

            rows = []
            for b in boards:
                vidpids = ", ".join(f"{v}:{p}" for v, p in (b.get("vidpids") or []))
                rows.append((
                    b["board_id"], b["layer"], b["sublayer"], b["name"],
                    b.get("name_search") or b["name"],
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
            conn.executemany(
                "INSERT INTO boards (board_id, layer, sublayer, name, name_search, "
                "vendor, mcu, architecture, bit_width, frequency_mhz, flash_kb, "
                "ram_kb, upload_speed, upload_protocol, core, variant, "
                "homepage, frameworks, connectivity, debug_tool, "
                "aliases, keywords, vidpids, upstream_blob) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute(
                "INSERT INTO boards_fts (rowid, board_id, name, vendor, mcu, "
                "                        architecture, sublayer, frameworks, "
                "                        connectivity, aliases, keywords) "
                "SELECT rowid, board_id, COALESCE(name_search, name), "
                "       COALESCE(vendor,''), "
                "       COALESCE(mcu,''), COALESCE(architecture,''), sublayer, "
                "       COALESCE(frameworks,''), COALESCE(connectivity,''), "
                "       COALESCE(aliases,''), COALESCE(keywords,'') "
                "FROM boards"
            )
            # Mirror the prefix-cache build so local tests see the same
            # fast-path table the live DB carries. Import lazily to dodge
            # circular-import issues with the parent build_sqlite module.
            sys.path.insert(0, str(REPO))
            from builders.build_sqlite import _build_vendor_prefix_results
            _build_vendor_prefix_results(conn)
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()

        shutil.copyfile(local_db, out_path)
        size = out_path.stat().st_size
        print(f"wrote {out_path} ({size:,} bytes)", file=sys.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    default_out = pathlib.Path(tempfile.gettempdir()) / "fastled-boards-local.db"
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=default_out)
    args = ap.parse_args()
    rebuild(args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
