#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Extract uniform VID/PID records from the `platformio` data-branch worktree.

Layer-3 (priority below `vendors` and `arduino`, above `other`).

Input shape: per-board JSON files at `<root>/<plat>/boards/<id>.json`,
the raw PlatformIO format. VID:PID lives in `build.hwids` as a list of
`[VID, PID]` pairs. Coverage is ~23% of boards as of the 2026 snapshot
(see audit in this repo's PR conversation): Espressif, Adafruit, Arduino,
RP2040 family carry hwids; bare-chip generics and STM32 do not.

Output: the same `{layer, vendors, products}` normalized record shape
defined in extract_vendors.py.

Vendor names come from the per-board JSON's `vendor` field (often present
on PlatformIO boards) — kept as a hint, not authoritative.
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
    seen_vendor: set[tuple[str, str]] = set()  # (vid, vendor) — dedup hints

    if not root.is_dir():
        print(f"platformio: input dir {root} missing; emitting empty record set",
              file=sys.stderr)
        return {"layer": "platformio", "vendors": vendors, "products": products}

    per_plat_counts: dict[str, int] = {}

    # The platformio branch worktree puts everything under `data/`. Tolerate
    # both `--in <worktree-root>` and `--in <worktree-root>/data`.
    if (root / "data").is_dir() and not list(root.glob("*/boards/*.json")):
        root = root / "data"

    for board_json in sorted(root.glob("*/boards/*.json")):
        plat = board_json.parts[-3]
        try:
            board = json.loads(board_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"platformio[skip]: {board_json}: {e}", file=sys.stderr)
            continue

        hwids = (board.get("build") or {}).get("hwids") or []
        if not isinstance(hwids, list) or not hwids:
            continue

        name = board.get("name") or board_json.stem
        vendor_hint = board.get("vendor") if isinstance(board.get("vendor"), str) else None
        src = f"platformio:{plat}/{board_json.stem}"

        per_plat_counts[plat] = per_plat_counts.get(plat, 0) + 1

        for entry in hwids:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            vid = _norm_hex(entry[0], 4)
            pid = _norm_hex(entry[1], 4)
            if not vid or not pid:
                continue
            products.append({
                "vid": vid, "pid": pid,
                "product": str(name).strip(),
                "source": src,
            })
            if vendor_hint and (vid, vendor_hint) not in seen_vendor:
                vendors.append({"vid": vid, "vendor": vendor_hint.strip(),
                                "source": src, "hint": True})
                seen_vendor.add((vid, vendor_hint))

    for plat, n in sorted(per_plat_counts.items(), key=lambda kv: -kv[1])[:10]:
        print(f"platformio[{plat}]: {n} boards with hwids", file=sys.stderr)
    print(f"platformio: {len(vendors)} vendor hints, {len(products)} product records",
          file=sys.stderr)
    return {"layer": "platformio", "vendors": vendors, "products": products}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in",  dest="in_dir",  required=True, type=pathlib.Path)
    p.add_argument("--out", dest="out",     required=True, type=pathlib.Path)
    args = p.parse_args()
    records = extract(args.in_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"platformio: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
