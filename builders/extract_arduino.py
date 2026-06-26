#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Extract uniform VID/PID records from the `arduino` data-branch worktree.

Layer-2 (priority below `vendors`, above `platformio`).

Input shape: per-board JSON files at `<root>/<core-slug>/boards/<id>.json`
parsed by the upstream `boards.txt` sync. Each board carries vid/pid as
either:

  - paired indexed dicts at top-level:
      "vid": {"0": "0x2341", "1": "0x2341"}
      "pid": {"0": "0x0036", "1": "0x8036"}
  - and/or the build-time defaults:
      "build": {"vid": "0x2341", "pid": "0x8036"}
  - and a `name` and `build.usb_product` for the human label.

Output: the same `{layer, vendors, products}` normalized record shape
defined in extract_vendors.py.

Vendor-name resolution at this layer is best-effort: the arduino core a
board ships in is a strong hint at its vendor (arduino/* → Arduino,
adafruit/* → Adafruit, espressif/* → Espressif, etc.) but the boards.txt
file does not name the VID's vendor. We emit vendor records keyed by VID
using a per-core hint mapping; the `vendors` and `other` layers can
override or sharpen those names downstream.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

# Core-slug -> conservative vendor-name HINT. The merger applies these only
# when no higher-authority layer (vendors) has already claimed the VID.
CORE_VENDOR_HINTS = {
    "arduino-arduinocore-avr":      "Arduino",
    "arduino-arduinocore-samd":     "Arduino",
    "arduino-arduinocore-megaavr":  "Arduino",
    "arduino-arduinocore-mbed":     "Arduino",
    "arduino-arduinocore-renesas":  "Arduino",
    "espressif-arduino-esp32":      "Espressif Systems",
    "esp8266-arduino":              "Espressif Systems",
    "adafruit-adafruit_nrf52_arduino": "Adafruit",
    "stm32duino-arduino_core_stm32": "STMicroelectronics",
    "siliconlabs-arduino":          "Silicon Labs",
    "earlephilhower-arduino-pico":  "Raspberry Pi Foundation",
}


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


def _unquote(s: str | None) -> str | None:
    if not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.strip() or None


def _collect_vid_pid_pairs(board: dict) -> list[tuple[str, str]]:
    """Walk the indexed vid.N/pid.N pairs and build.vid/build.pid fallback.
    Returns a deduped list of (vid_lower, pid_lower) 4-hex strings."""
    pairs: list[tuple[str, str]] = []

    # Indexed top-level: vid.N + pid.N paired by index.
    vid_dict = board.get("vid") if isinstance(board.get("vid"), dict) else {}
    pid_dict = board.get("pid") if isinstance(board.get("pid"), dict) else {}
    common_keys = sorted(set(vid_dict) & set(pid_dict),
                          key=lambda k: int(k) if k.isdigit() else 1_000_000)
    for k in common_keys:
        vid = _norm_hex(vid_dict.get(k, ""), 4)
        pid = _norm_hex(pid_dict.get(k, ""), 4)
        if vid and pid:
            pairs.append((vid, pid))

    # build.vid + build.pid (singular, runtime default).
    bv = _norm_hex((board.get("build") or {}).get("vid", ""), 4)
    bp = _norm_hex((board.get("build") or {}).get("pid", ""), 4)
    if bv and bp:
        pairs.append((bv, bp))

    # Dedupe, preserve order.
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for p in pairs:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def extract(root: pathlib.Path) -> dict[str, Any]:
    vendors: list[dict] = []
    products: list[dict] = []
    seen_vendor_vids: set[str] = set()

    if not root.is_dir():
        print(f"arduino: input dir {root} missing; emitting empty record set",
              file=sys.stderr)
        return {"layer": "arduino", "vendors": vendors, "products": products}

    per_core_counts: dict[str, int] = {}

    # The arduino branch worktree puts everything under `data/`. Tolerate
    # both `--in <worktree-root>` and `--in <worktree-root>/data` so the
    # extractor works either way.
    if (root / "data").is_dir() and not list(root.glob("*/boards/*.json")):
        root = root / "data"

    for board_json in sorted(root.glob("*/boards/*.json")):
        core_slug = board_json.parts[-3]
        try:
            board = json.loads(board_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"arduino[skip]: {board_json}: {e}", file=sys.stderr)
            continue

        name = board.get("name") or _unquote((board.get("build") or {}).get("usb_product")) or board_json.stem
        pairs = _collect_vid_pid_pairs(board)
        if not pairs:
            continue

        per_core_counts[core_slug] = per_core_counts.get(core_slug, 0) + 1
        src = f"arduino:{core_slug}/{board_json.stem}"
        # Vendor hints belong to the core, not the first board we happened to
        # see — otherwise vid_vendor.source ends up pointing at a random board
        # JSON path (e.g. `arduino:espressif-arduino-esp32/Bee_Data_Logger`).
        vendor_src = f"arduino:{core_slug}"

        for vid, pid in pairs:
            products.append({
                "vid": vid, "pid": pid,
                "product": str(name).strip(),
                "source": src,
            })
            # One vendor-hint record per (core, vid). The hint is conservative —
            # the merger will only apply it when no higher-authority source has
            # already named the VID.
            hint = CORE_VENDOR_HINTS.get(core_slug)
            if hint and (vid not in seen_vendor_vids):
                vendors.append({"vid": vid, "vendor": hint, "source": vendor_src,
                                "hint": True})
                seen_vendor_vids.add(vid)

    for core, n in sorted(per_core_counts.items()):
        print(f"arduino[{core}]: {n} boards with vid+pid", file=sys.stderr)
    print(f"arduino: {len(vendors)} vendor hints, {len(products)} product records",
          file=sys.stderr)
    return {"layer": "arduino", "vendors": vendors, "products": products}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in",  dest="in_dir",  required=True, type=pathlib.Path)
    p.add_argument("--out", dest="out",     required=True, type=pathlib.Path)
    args = p.parse_args()
    records = extract(args.in_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"arduino: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
