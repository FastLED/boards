#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Extract uniform VID/PID records from the `vendors` data-branch worktree.

Layer-1 (most authoritative). The vendors branch is the home of curated
VID -> vendor mappings + per-vendor PID allocation registries (Raspberry Pi
`usb-pid`, Espressif `usb-pids`, our `vendor_names_inlined` overlay).

Input shape (when populated): per-source JSON files under the worktree root
carrying either `{vid_lower_hex: vendor_name}` dicts OR per-vendor PID
tables `[{vid, pid, product}, ...]`. The extractor is intentionally
tolerant of both shapes so vendors branch contributors can pick whichever
fits their source.

Output: a normalized JSON record file (the input format every extractor
in this directory emits and `merge.py` reads):

    {
      "layer":    "vendors",
      "vendors":  [{"vid": "303a", "vendor": "Espressif Systems", "source": "..."}],
      "products": [{"vid": "303a", "pid": "1001", "product": "...", "source": "..."}]
    }

Currently the vendors branch is a placeholder; this extractor produces an
empty record set in that case (and exits 0).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


def _norm_hex(s: str | int, width: int) -> str | None:
    if isinstance(s, int):
        return f"{s:0{width}x}"
    if not isinstance(s, str):
        return None
    s = s.strip().lower().removeprefix("0x")
    if len(s) > width or not s:
        return None
    try:
        int(s, 16)
    except ValueError:
        return None
    return s.zfill(width)


def _walk_json_files(root: pathlib.Path):
    for p in root.rglob("*.json"):
        # Skip provenance / index files; only ingest payload.
        if p.name in ("_meta.json", "_source.json", "manifest.json"):
            continue
        try:
            yield p, json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"vendors[skip]: {p}: {e}", file=sys.stderr)


def extract(root: pathlib.Path) -> dict[str, Any]:
    vendors: list[dict] = []
    products: list[dict] = []
    if not root.is_dir():
        print(f"vendors: input dir {root} missing; emitting empty record set",
              file=sys.stderr)
        return {"layer": "vendors", "vendors": vendors, "products": products}

    for fpath, payload in _walk_json_files(root):
        src = f"vendors:{fpath.relative_to(root).as_posix()}"

        # Shape A: a flat {vid_hex: vendor_name} dict
        if isinstance(payload, dict) and all(
            isinstance(v, str) for v in payload.values()
        ):
            for vid_raw, vendor_name in payload.items():
                vid = _norm_hex(vid_raw, 4)
                if vid and vendor_name.strip():
                    vendors.append({"vid": vid, "vendor": vendor_name.strip(),
                                    "source": src})
            continue

        # Shape B: a list of records [{vid, pid?, vendor?, product?}, ...]
        if isinstance(payload, list):
            for rec in payload:
                if not isinstance(rec, dict):
                    continue
                vid = _norm_hex(rec.get("vid", ""), 4)
                if not vid:
                    continue
                if "vendor" in rec and isinstance(rec["vendor"], str):
                    vendors.append({"vid": vid, "vendor": rec["vendor"].strip(),
                                    "source": src})
                pid = _norm_hex(rec.get("pid", ""), 4)
                if pid and isinstance(rec.get("product"), str):
                    products.append({"vid": vid, "pid": pid,
                                     "product": rec["product"].strip(),
                                     "source": src})
            continue

        # Shape C: nested {vid: {vendor, products: {pid: name}}}
        if isinstance(payload, dict):
            for vid_raw, sub in payload.items():
                vid = _norm_hex(vid_raw, 4)
                if not vid or not isinstance(sub, dict):
                    continue
                if isinstance(sub.get("vendor"), str):
                    vendors.append({"vid": vid, "vendor": sub["vendor"].strip(),
                                    "source": src})
                prods = sub.get("products")
                if isinstance(prods, dict):
                    for pid_raw, pname in prods.items():
                        pid = _norm_hex(pid_raw, 4)
                        if pid and isinstance(pname, str):
                            products.append({"vid": vid, "pid": pid,
                                             "product": pname.strip(),
                                             "source": src})

    print(f"vendors: {len(vendors)} vendor records, {len(products)} product records",
          file=sys.stderr)
    return {"layer": "vendors", "vendors": vendors, "products": products}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in",  dest="in_dir",  required=True, type=pathlib.Path,
                   help="vendors data-branch worktree root")
    p.add_argument("--out", dest="out",     required=True, type=pathlib.Path,
                   help="normalized record file (JSON) to write")
    args = p.parse_args()
    records = extract(args.in_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"vendors: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
