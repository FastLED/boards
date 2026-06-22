#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Build a compact USB VID:PID download JSON from the finished SQLite DB.

Output shape:

    {
      "303a": {
        "Vendor name": "Espressif Systems",
        "PIDs": [{"1001": "USB JTAG/serial debug unit"}, ...]
      },
      ...
    }

The file is intentionally minimized because it is a direct-download helper.
It is generated after boards.db is constructed, so it reflects the final
ingested vid_vendor + vidpid tables.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys


def dump_usb_ids(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}

    rows = conn.execute(
        """
        SELECT p.vid, COALESCE(v.vendor, ''), p.pid, p.product
        FROM vidpid p
        LEFT JOIN vid_vendor v ON v.vid = p.vid
        ORDER BY p.vid, p.pid, p.is_primary DESC, p.product COLLATE NOCASE
        """
    )
    for vid, vendor_name, pid, product in rows:
        bucket = out.setdefault(
            vid,
            {
                "Vendor name": vendor_name,
                "PIDs": [],
            },
        )
        pids = bucket["PIDs"]
        if isinstance(pids, list):
            pids.append({pid: product})

    return out


def build(db_path: pathlib.Path, out_path: pathlib.Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        download = dump_usb_ids(conn)
    finally:
        conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(download, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    size = out_path.stat().st_size
    pid_rows = sum(len(v["PIDs"]) for v in download.values())
    print(
        f"build_usb_ids: wrote {out_path} "
        f"({size:,} bytes, {len(download)} VIDs, {pid_rows} PID rows)",
        file=sys.stderr,
    )
    return {"vids": len(download), "pid_rows": pid_rows, "bytes": size}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True, type=pathlib.Path,
                   help="boards.db produced by build_sqlite.py")
    p.add_argument("--out", required=True, type=pathlib.Path,
                   help="compact output JSON path")
    args = p.parse_args()
    build(args.db, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
