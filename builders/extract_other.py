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
      "vidpid_overrides": {"16c0:0483": "Teensy LC", ...},   (optional)
      "vidpid_board_links": [                                  (optional)
        {
          "id": "teensy-usb-modes",
          "vidpids": ["16c0:0483", "16c0:0482", ...],
          "match_boards": { "board_id_glob": "teensy*" },
          "note": "PJRC USB-mode PIDs apply to every Teensy variant."
        },
        ...
      ]
    }

The `vidpid_board_links` rules are polyfill-only. `build_sqlite.py`
expands them at build time into `board_vidpids(board_rowid, vid, pid)`
junction rows, and applies INSERT OR IGNORE so any board that already
has the upstream hwid wins. This lets curators fill in linkage for
boards whose upstream JSONs don't carry hwids (Teensy is the
canonical case) without overriding correct upstream data.

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


def _normalize_link_rule(rec: dict, fallback_id: int) -> dict | None:
    """Validate + normalize one vidpid_board_links rule.

    Returns None when the rule is malformed (so the build keeps going
    instead of aborting on a typo in curated data). Normalizes vidpid
    strings to lowercase 8-hex keys and `match_boards` to a stable
    sub-dict shape.
    """
    if not isinstance(rec, dict):
        return None
    vidpids_raw = rec.get("vidpids") or []
    if not isinstance(vidpids_raw, list):
        return None
    vidpids: list[str] = []
    for s in vidpids_raw:
        if not isinstance(s, str):
            continue
        cleaned = s.lower().replace(":", "").replace(" ", "")
        if len(cleaned) != 8:
            continue
        vid = _norm_hex(cleaned[:4], 4)
        pid = _norm_hex(cleaned[4:], 4)
        if vid and pid:
            vidpids.append(f"{vid}{pid}")
    if not vidpids:
        return None
    match = rec.get("match_boards") or {}
    if not isinstance(match, dict):
        return None
    keep: dict[str, str] = {}
    for k, v in match.items():
        if isinstance(v, str) and v.strip():
            keep[k] = v.strip()
    if not keep:
        return None
    rule_id = rec.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        rule_id = f"rule-{fallback_id}"
    return {
        "id":            rule_id.strip(),
        "vidpids":       vidpids,
        "match_boards":  keep,
        "note":          (rec.get("note") or "").strip() or None,
    }


def extract(root: pathlib.Path) -> dict[str, Any]:
    vendors: list[dict] = []
    products: list[dict] = []
    vid_overrides: dict[str, str] = {}
    vidpid_overrides: dict[str, str] = {}
    vidpid_board_links: list[dict] = []
    usb_profiles: list[dict] = []

    if not root.is_dir():
        print(f"other: input dir {root} missing; emitting empty record set",
              file=sys.stderr)
        return {"layer": "other", "vendors": vendors, "products": products,
                "vid_overrides": vid_overrides, "vidpid_overrides": vidpid_overrides,
                "vidpid_board_links": vidpid_board_links,
                "usb_profiles": usb_profiles}

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
            for i, rec in enumerate(ovr.get("vidpid_board_links") or []):
                rule = _normalize_link_rule(rec, i)
                if rule:
                    vidpid_board_links.append(rule)
                else:
                    print(f"other[skip vidpid_board_link rule #{i}]: malformed",
                          file=sys.stderr)
            for rec in ovr.get("usb_profiles") or []:
                if isinstance(rec, dict):
                    usb_profiles.append(rec)
            print(f"other: {len(vid_overrides)} vid overrides, "
                  f"{len(vidpid_overrides)} vidpid overrides, "
                  f"{len(vidpid_board_links)} board-link rules",
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
            "vid_overrides": vid_overrides, "vidpid_overrides": vidpid_overrides,
            "vidpid_board_links": vidpid_board_links,
            "usb_profiles": usb_profiles}


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
