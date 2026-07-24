#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "zstandard==0.23.0",
# ]
# ///
"""Build compact USB VID:PID download artifacts from the finished SQLite DB.

JSON output shape:

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

The protobuf sidecar is written as `usb-vids.proto.zstd`. Its wire schema is:

    message UsbVidDatabase {
      repeated Vendor vendors = 1;
    }
    message Vendor {
      uint32 vid = 1;
      string name = 2;
      repeated Product products = 3;
    }
    message Product {
      uint32 pid = 1;
      string name = 2;
    }
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


def _varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _key(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _u32(field: int, value: int) -> bytes:
    return _key(field, 0) + _varint(value)


def _string(field: int, value: str) -> bytes:
    raw = value.encode("utf-8")
    return _key(field, 2) + _varint(len(raw)) + raw


def _message(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _hex_u16(s: str) -> int:
    return int(s, 16)


def encode_usb_vids_proto(download: dict[str, dict[str, object]]) -> bytes:
    """Encode `dump_usb_ids()` output as the protobuf schema above."""
    database = bytearray()
    for vid_hex, vendor_entry in sorted(download.items()):
        vendor = bytearray()
        vendor += _u32(1, _hex_u16(vid_hex))
        vendor += _string(2, str(vendor_entry.get("Vendor name", "")))
        pids = vendor_entry.get("PIDs", [])
        if isinstance(pids, list):
            for pid_entry in pids:
                if not isinstance(pid_entry, dict):
                    continue
                for pid_hex, product_name in sorted(pid_entry.items()):
                    product = bytearray()
                    product += _u32(1, _hex_u16(str(pid_hex)))
                    product += _string(2, str(product_name))
                    vendor += _message(3, bytes(product))
        database += _message(1, bytes(vendor))
    return bytes(database)


def write_proto_zstd(download: dict[str, dict[str, object]], out_path: pathlib.Path) -> int:
    import zstandard

    raw = encode_usb_vids_proto(download)
    compressed = zstandard.ZstdCompressor(level=19).compress(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(compressed)
    return len(compressed)


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
    proto_path = out_path.with_name("usb-vids.proto.zstd")
    proto_size = write_proto_zstd(download, proto_path)
    print(
        f"build_usb_ids: wrote {out_path} "
        f"({size:,} bytes, {len(download)} VIDs, {pid_rows} PID rows)",
        file=sys.stderr,
    )
    print(
        f"build_usb_ids: wrote {proto_path} "
        f"({proto_size:,} bytes compressed protobuf)",
        file=sys.stderr,
    )
    return {
        "vids": len(download),
        "pid_rows": pid_rows,
        "bytes": size,
        "proto_zstd_bytes": proto_size,
    }


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
