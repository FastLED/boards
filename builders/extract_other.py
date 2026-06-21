#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Extract uniform VID/PID records from the `other` data-branch worktree.

Layer-4 — the **override** layer. Lower priority than vendors/arduino/
platformio in the strict-vendor-name-conflict sense, but special: entries
listed under `vid_overrides` in `overrides.json` UNCONDITIONALLY replace
whatever vendor name an earlier layer assigned. This is the only layer
where overrides are silent (no errors/ log entry generated).

The headline use case is Teensy (VID 0x16C0). 0x16C0 is allocated to
Van Ooijen Technische Informatica (VOTI), who sub-licenses to PJRC for
the Teensy family. Generic linux-usb.org / hwdata text dumps still call
0x16C0 "Van Ooijen Technische Informatica" but for an embedded-board
context we want it to read as "PJRC (Teensy)". An explicit override here
encodes that decision once.

Input shape: `<root>/overrides.json` carrying:
    {
      "vid_overrides": {"16c0": "PJRC (Teensy)", ...},
      "vidpid_overrides": {"16c0:0483": "Teensy LC", ...}   (optional)
    }

Plus any additional `<root>/*.json` files in the same flat-record shape
extract_vendors accepts (forwards them so curators can add ad-hoc
udev/esptool extracts here without writing new extractors).
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
    if not s:
        return None
    try:
        int(s, 16)
    except ValueError:
        return None
    if len(s) > width:
        return None
    return s.zfill(width)


def extract(root: pathlib.Path) -> dict[str, Any]:
    vendors: list[dict] = []
    products: list[dict] = []
    vid_overrides: dict[str, str] = {}
    vidpid_overrides: dict[str, str] = {}

    if not root.is_dir():
        print(f"other: input dir {root} missing; emitting empty record set",
              file=sys.stderr)
        return {"layer": "other", "vendors": vendors, "products": products,
                "vid_overrides": vid_overrides, "vidpid_overrides": vidpid_overrides}

    ovr_path = root / "overrides.json"
    if ovr_path.is_file():
        try:
            ovr = json.loads(ovr_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"other[skip overrides.json]: {e}", file=sys.stderr)
        else:
            for vid_raw, vendor in (ovr.get("vid_overrides") or {}).items():
                vid = _norm_hex(vid_raw, 4)
                if vid and isinstance(vendor, str) and vendor.strip():
                    vid_overrides[vid] = vendor.strip()
            for key, product in (ovr.get("vidpid_overrides") or {}).items():
                # key shape: "vid:pid" or "vidpid"
                if isinstance(key, str) and isinstance(product, str):
                    cleaned = key.lower().replace(":", "")
                    if len(cleaned) == 8:
                        vid = _norm_hex(cleaned[:4], 4)
                        pid = _norm_hex(cleaned[4:], 4)
                        if vid and pid:
                            vidpid_overrides[f"{vid}{pid}"] = product.strip()
            print(f"other: {len(vid_overrides)} vid overrides, "
                  f"{len(vidpid_overrides)} vidpid overrides",
                  file=sys.stderr)

    # Any additional flat-record JSON files in this branch are forwarded as
    # ordinary vendor/product records (same shape as extract_vendors accepts).
    for p in sorted(root.rglob("*.json")):
        if p.name in ("overrides.json", "_meta.json", "_source.json"):
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"other[skip]: {p}: {e}", file=sys.stderr)
            continue
        src = f"other:{p.relative_to(root).as_posix()}"
        # Accept the same three shapes the vendors extractor accepts.
        if isinstance(payload, list):
            for rec in payload:
                if not isinstance(rec, dict):
                    continue
                vid = _norm_hex(rec.get("vid", ""), 4)
                if not vid:
                    continue
                if isinstance(rec.get("vendor"), str):
                    vendors.append({"vid": vid, "vendor": rec["vendor"].strip(),
                                    "source": src})
                pid = _norm_hex(rec.get("pid", ""), 4)
                if pid and isinstance(rec.get("product"), str):
                    products.append({"vid": vid, "pid": pid,
                                     "product": rec["product"].strip(),
                                     "source": src})
        # Other shapes are tolerated but ignored for now.

    print(f"other: {len(vendors)} flat-record vendors, {len(products)} flat-record products",
          file=sys.stderr)
    return {"layer": "other", "vendors": vendors, "products": products,
            "vid_overrides": vid_overrides, "vidpid_overrides": vidpid_overrides}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in",  dest="in_dir",  required=True, type=pathlib.Path)
    p.add_argument("--out", dest="out",     required=True, type=pathlib.Path)
    args = p.parse_args()
    records = extract(args.in_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"other: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
