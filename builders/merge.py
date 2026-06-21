#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Merge the normalized records from extract_{vendors,arduino,platformio,other}.py
into a single authoritative `{vid_vendor, vidpid}` table set.

Merge order (strict priority): **vendors -> arduino -> platformio -> other**.
Within a layer, first-seen-wins. Across layers, first-layer-wins, with one
exception: entries listed under `vid_overrides` / `vidpid_overrides` in the
`other` layer UNCONDITIONALLY replace whatever earlier layers assigned —
this is how Teensy gets to read as "PJRC (Teensy)" instead of inheriting
"Van Ooijen Technische Informatica" (the registered owner of VID 0x16C0)
from a generic upstream.

Conflicts (two layers disagree on the vendor or product name) are NOT a
build-stopper: they get appended to `<errors-dir>/<kind>.log` for human
review, and the higher-priority entry stays in the table.

Vendor-name HINT records (those carrying `"hint": true`) are treated as
weak: they fill a VID's vendor only if no non-hint source has supplied
one. Conflicts among hints don't generate error log entries.

Output: `<out>` JSON file with shape
    {
      "generated_at":  "ISO-8601 UTC",
      "vid_vendor":    {"303a": {"vendor": "...", "source": "..."}},
      "vidpid":        {"303a4002": {"vid": "303a", "pid": "4002",
                                     "product": "...", "source": "..."}}
    }

Plus per-kind conflict logs under `--errors-dir`:
  - vendor-conflicts.log
  - product-conflicts.log
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
from typing import Any

LAYER_ORDER = ["vendors", "arduino", "platformio", "other"]


def _load(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        print(f"merge: skip missing layer file {path}", file=sys.stderr)
        return {"layer": path.stem, "vendors": [], "products": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge(layer_files: list[pathlib.Path], errors_dir: pathlib.Path) -> dict[str, Any]:
    errors_dir.mkdir(parents=True, exist_ok=True)
    vendor_log = errors_dir / "vendor-conflicts.log"
    product_log = errors_dir / "product-conflicts.log"
    # Truncate at start so this run's log is self-contained.
    vendor_log.write_text("", encoding="utf-8")
    product_log.write_text("", encoding="utf-8")

    vid_vendor: dict[str, dict[str, str]] = {}
    vidpid:    dict[str, dict[str, str]] = {}
    other_data: dict[str, Any] | None = None
    layer_counts = {l: {"vendors": 0, "products": 0, "hint_vendors": 0} for l in LAYER_ORDER}

    # 1. Walk layers in strict order, first-wins, log conflicts.
    by_layer = {}
    for f in layer_files:
        data = _load(f)
        layer = data.get("layer") or f.stem
        by_layer[layer] = data

    for layer in LAYER_ORDER:
        data = by_layer.get(layer)
        if not data:
            continue
        if layer == "other":
            other_data = data

        # Vendor pass: non-hint first, then hints (so authoritative entries
        # claim the slot before weak hints try).
        all_vendor_recs = data.get("vendors") or []
        non_hint = [r for r in all_vendor_recs if not r.get("hint")]
        hints    = [r for r in all_vendor_recs if r.get("hint")]

        for rec in non_hint:
            vid = rec.get("vid")
            name = rec.get("vendor")
            if not vid or not isinstance(name, str):
                continue
            layer_counts[layer]["vendors"] += 1
            existing = vid_vendor.get(vid)
            if existing is None:
                vid_vendor[vid] = {"vendor": name, "source": rec.get("source", layer),
                                   "layer": layer}
                continue
            # Already set; first-wins. Log only if names actually differ.
            if existing["vendor"] != name:
                with vendor_log.open("a", encoding="utf-8") as f:
                    f.write(f"conflict vid=0x{vid}: kept={existing['vendor']!r} "
                            f"(from {existing['source']}/{existing['layer']}) "
                            f"vs new={name!r} (from {rec.get('source')}/{layer})\n")

        for rec in hints:
            vid = rec.get("vid")
            name = rec.get("vendor")
            if not vid or not isinstance(name, str):
                continue
            layer_counts[layer]["hint_vendors"] += 1
            if vid in vid_vendor:
                continue  # hints never overwrite a real entry; no error logged
            vid_vendor[vid] = {"vendor": name, "source": rec.get("source", layer),
                               "layer": layer, "hint": True}

        # Product pass: first-wins; log differences.
        for rec in (data.get("products") or []):
            vid = rec.get("vid")
            pid = rec.get("pid")
            product = rec.get("product")
            if not vid or not pid or not isinstance(product, str):
                continue
            key = f"{vid}{pid}"
            layer_counts[layer]["products"] += 1
            existing = vidpid.get(key)
            if existing is None:
                vidpid[key] = {"vid": vid, "pid": pid, "product": product,
                               "source": rec.get("source", layer), "layer": layer}
                continue
            if existing["product"] != product:
                with product_log.open("a", encoding="utf-8") as f:
                    f.write(f"conflict vidpid=0x{vid}:0x{pid}: "
                            f"kept={existing['product']!r} "
                            f"(from {existing['source']}/{existing['layer']}) "
                            f"vs new={product!r} (from {rec.get('source')}/{layer})\n")

    # 2. Apply `other` layer overrides — these UNCONDITIONALLY replace.
    if other_data:
        for vid, vendor in (other_data.get("vid_overrides") or {}).items():
            prior = vid_vendor.get(vid, {}).get("vendor")
            vid_vendor[vid] = {"vendor": vendor, "source": "other:overrides.json",
                               "layer": "other", "override": True,
                               "replaced": prior}
        for vidpid_key, product in (other_data.get("vidpid_overrides") or {}).items():
            prior = vidpid.get(vidpid_key, {}).get("product")
            vid = vidpid_key[:4]; pid = vidpid_key[4:]
            vidpid[vidpid_key] = {"vid": vid, "pid": pid, "product": product,
                                  "source": "other:overrides.json",
                                  "layer": "other", "override": True,
                                  "replaced": prior}

    # 3. Sort keys for deterministic output.
    vid_vendor = dict(sorted(vid_vendor.items()))
    vidpid     = dict(sorted(vidpid.items()))

    # Summary to stderr.
    for layer, counts in layer_counts.items():
        if any(counts.values()):
            print(f"merge[{layer}]: vendors={counts['vendors']} "
                  f"hints={counts['hint_vendors']} products={counts['products']}",
                  file=sys.stderr)
    vendor_conflicts = sum(1 for _ in vendor_log.read_text(encoding='utf-8').splitlines())
    product_conflicts = sum(1 for _ in product_log.read_text(encoding='utf-8').splitlines())
    print(f"merge: {len(vid_vendor)} vendors, {len(vidpid)} products in final tables",
          file=sys.stderr)
    print(f"merge: {vendor_conflicts} vendor-name conflicts, "
          f"{product_conflicts} product-name conflicts logged to {errors_dir}",
          file=sys.stderr)

    return {
        "generated_at": _now_iso(),
        "vid_vendor": vid_vendor,
        "vidpid": vidpid,
        "stats": {
            "total_vids": len(vid_vendor),
            "total_vidpids": len(vidpid),
            "vendor_conflicts_logged": vendor_conflicts,
            "product_conflicts_logged": product_conflicts,
            "per_layer": layer_counts,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--normalized-dir", required=True, type=pathlib.Path,
                   help="directory containing vendors.json/arduino.json/"
                        "platformio.json/other.json from each extractor")
    p.add_argument("--out",            required=True, type=pathlib.Path)
    p.add_argument("--errors-dir",     required=True, type=pathlib.Path)
    args = p.parse_args()

    layer_files = [args.normalized_dir / f"{l}.json" for l in LAYER_ORDER]
    result = merge(layer_files, args.errors_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"merge: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
