#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Merge normalized records from extract_{vendors,arduino,platformio,other}.py
into authoritative {vid_vendor, vidpid} tables with severity-tiered conflict
handling.

## Merge order (strict priority)

  vendors -> arduino -> platformio -> other

`other` layer overrides (`vid_overrides` / `vidpid_overrides` in
`overrides.json`) UNCONDITIONALLY replace whatever earlier layers said —
this is how Teensy gets to read as "PJRC (Teensy)" instead of the
registered VOTI owner. Override entries never generate log entries.

## Conflict handling for PRODUCT names (vidpid table)

For each VID:PID, when two sources disagree the merger compares names by
string similarity and routes the conflict to one of three tiers:

  - sim >= 0.85  : minor diff (case/parens/sub-suffix). Silent winner;
                   logged to warnings/minor.log. Loser dropped.
  - 0.50 <= sim < 0.85 : sub-variant of same family (Pico vs Pico W).
                   Silent winner; logged to warnings/family.log. Loser
                   dropped.
  - sim < 0.50   : genuinely different products. Both kept in the table
                   (multi-row vidpid). The HIGHER-SCORING name is marked
                   primary; the lower-scoring becomes an alternate
                   (is_primary=0). Logged to warnings/distinct.log.

## "Professional name" scorer

Tiebreaks at sim<0.5 use score_name() which prefers names carrying a
canonical chip / part designator over pure marketing names. Examples:

  "Nordic nRF52840 DK"  -> (1, 0, 18)  -- nRF52840 is a chip token
  "Particle Photon"     -> (0, 0, 15)  -- no chip token
  -> "Nordic nRF52840 DK" wins; "Particle Photon" becomes alternate.

Tuple comparison: (chip_tokens, spec_paren_bonus, length). Bigger wins.
Length is the final tiebreak so deterministic ordering holds.

## Output shape

    {
      "generated_at": "ISO-8601 UTC",
      "vid_vendor":   {"303a": {"vendor": "...", "source": "..."}},
      "vidpid":       [{"vidpid":"303a4002", "vid":"303a", "pid":"4002",
                        "product":"...", "source":"...",
                        "is_primary": true|false, "score": [n, ...]}],
      "stats":        {...}
    }

The vidpid value is now a LIST (was a dict in v1) — multiple entries
per VIDPID can appear when genuinely-different products collide.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import pathlib
import re
import sys
from typing import Any

LAYER_ORDER = ["vendors", "arduino", "platformio", "other"]

SIM_MINOR    = 0.85
SIM_FAMILY   = 0.50

_CHIP_TOKEN_RE = re.compile(r"\b(?:[A-Za-z]+\d+\w*|\d+[A-Za-z]+\w*)\b")
_SPEC_UNITS = ("MB", "KB", "MHZ", "RAM", "FLASH", "PSRAM", "GHZ")


def score_name(name: str) -> tuple[int, int, int]:
    """Higher tuple = more 'professional' name. Tuple comparison:
    (chip_tokens, spec_paren_bonus, length)."""
    chip = len(_CHIP_TOKEN_RE.findall(name))
    bonus = 0
    if "(" in name:
        up = name.upper()
        if any(u in up for u in _SPEC_UNITS):
            bonus = 1
    return (chip, bonus, len(name))


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _load(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        print(f"merge: skip missing layer file {path}", file=sys.stderr)
        return {"layer": path.stem, "vendors": [], "products": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge(layer_files: list[pathlib.Path], warnings_dir: pathlib.Path,
          errors_dir: pathlib.Path) -> dict[str, Any]:
    warnings_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)
    minor_log    = warnings_dir / "minor.log"
    family_log   = warnings_dir / "family.log"
    distinct_log = warnings_dir / "distinct.log"
    vendor_log   = warnings_dir / "vendor.log"
    for f in (minor_log, family_log, distinct_log, vendor_log):
        f.write_text("", encoding="utf-8")

    vid_vendor: dict[str, dict[str, str]] = {}
    vidpid_rows: dict[str, list[dict]] = {}
    other_data: dict[str, Any] | None = None
    layer_counts = {l: {"vendors": 0, "products": 0, "hint_vendors": 0}
                    for l in LAYER_ORDER}
    severity_counts = {"minor": 0, "family": 0,
                       "distinct_kept_both": 0, "distinct_alt_dropped": 0}

    by_layer = {}
    for f in layer_files:
        data = _load(f)
        layer = data.get("layer") or f.stem
        by_layer[layer] = data

    def ingest_product(rec: dict, layer: str) -> None:
        vid = rec.get("vid"); pid = rec.get("pid")
        product = rec.get("product")
        if not vid or not pid or not isinstance(product, str):
            return
        product = product.strip()
        if not product:
            return
        key = f"{vid}{pid}"
        new_score = score_name(product)
        src = rec.get("source", layer)

        existing = vidpid_rows.get(key, [])
        if not existing:
            vidpid_rows[key] = [{
                "vidpid": key, "vid": vid, "pid": pid,
                "product": product, "source": src, "layer": layer,
                "is_primary": True, "score": list(new_score),
            }]
            return

        primary = next((e for e in existing if e.get("is_primary")), existing[0])
        if primary["product"] == product:
            return  # exact duplicate

        sim = _similarity(primary["product"], product)
        if sim >= SIM_MINOR:
            severity_counts["minor"] += 1
            with minor_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"minor vidpid=0x{vid}:0x{pid} sim={sim:.2f} "
                    f"kept={primary['product']!r} (from {primary['source']}/{primary['layer']}) "
                    f"dropped={product!r} (from {src}/{layer})\n"
                )
            return

        if sim >= SIM_FAMILY:
            severity_counts["family"] += 1
            with family_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"family vidpid=0x{vid}:0x{pid} sim={sim:.2f} "
                    f"kept={primary['product']!r} (from {primary['source']}/{primary['layer']}) "
                    f"dropped={product!r} (from {src}/{layer})\n"
                )
            return

        # sim < SIM_FAMILY → genuinely different products. Score-based.
        prim_score = tuple(primary.get("score") or score_name(primary["product"]))
        if new_score > prim_score:
            primary["is_primary"] = False
            new_entry = {
                "vidpid": key, "vid": vid, "pid": pid,
                "product": product, "source": src, "layer": layer,
                "is_primary": True, "score": list(new_score),
            }
            existing.insert(0, new_entry)
            severity_counts["distinct_kept_both"] += 1
            with distinct_log.open("a", encoding="utf-8") as f:
                f.write(
                    f"distinct vidpid=0x{vid}:0x{pid} sim={sim:.2f} "
                    f"PROMOTED new={product!r} (score={new_score}, from {src}/{layer}) "
                    f"PREVIOUS-PRIMARY-DEMOTED-TO-ALT={primary['product']!r} (score={prim_score})\n"
                )
            return

        # Else: keep existing primary; add new as alternate (or score-tied alt).
        existing.append({
            "vidpid": key, "vid": vid, "pid": pid,
            "product": product, "source": src, "layer": layer,
            "is_primary": False, "score": list(new_score),
        })
        if new_score == prim_score:
            severity_counts["distinct_kept_both"] += 1
        else:
            severity_counts["distinct_alt_dropped"] += 1
        with distinct_log.open("a", encoding="utf-8") as f:
            f.write(
                f"distinct vidpid=0x{vid}:0x{pid} sim={sim:.2f} "
                f"primary-kept={primary['product']!r} (score={prim_score}, "
                f"from {primary['source']}/{primary['layer']}) "
                f"alternate={product!r} (score={new_score}, from {src}/{layer})\n"
            )

    for layer in LAYER_ORDER:
        data = by_layer.get(layer)
        if not data:
            continue
        if layer == "other":
            other_data = data

        all_v = data.get("vendors") or []
        non_hint = [r for r in all_v if not r.get("hint")]
        hints    = [r for r in all_v if r.get("hint")]

        for rec in non_hint:
            vid = rec.get("vid"); name = rec.get("vendor")
            if not vid or not isinstance(name, str):
                continue
            layer_counts[layer]["vendors"] += 1
            ex = vid_vendor.get(vid)
            if ex is None:
                vid_vendor[vid] = {"vendor": name, "source": rec.get("source", layer),
                                   "layer": layer}
                continue
            if ex["vendor"] != name:
                with vendor_log.open("a", encoding="utf-8") as f:
                    f.write(
                        f"vendor vid=0x{vid} kept={ex['vendor']!r} "
                        f"(from {ex['source']}/{ex['layer']}) "
                        f"dropped={name!r} (from {rec.get('source')}/{layer})\n"
                    )

        for rec in hints:
            vid = rec.get("vid"); name = rec.get("vendor")
            if not vid or not isinstance(name, str):
                continue
            layer_counts[layer]["hint_vendors"] += 1
            if vid in vid_vendor:
                continue
            vid_vendor[vid] = {"vendor": name, "source": rec.get("source", layer),
                               "layer": layer, "hint": True}

        for rec in (data.get("products") or []):
            layer_counts[layer]["products"] += 1
            ingest_product(rec, layer)

    if other_data:
        for vid, vendor in (other_data.get("vid_overrides") or {}).items():
            prior = vid_vendor.get(vid, {}).get("vendor")
            vid_vendor[vid] = {"vendor": vendor, "source": "other:overrides.json",
                               "layer": "other", "override": True,
                               "replaced": prior}
        for vidpid_key, product in (other_data.get("vidpid_overrides") or {}).items():
            vid = vidpid_key[:4]; pid = vidpid_key[4:]
            vidpid_rows[vidpid_key] = [{
                "vidpid": vidpid_key, "vid": vid, "pid": pid,
                "product": product, "source": "other:overrides.json",
                "layer": "other", "is_primary": True, "override": True,
                "score": list(score_name(product)),
            }]

    vid_vendor = dict(sorted(vid_vendor.items()))
    flat_vidpid: list[dict] = []
    for key in sorted(vidpid_rows):
        rows = vidpid_rows[key]
        rows.sort(key=lambda e: (not e.get("is_primary"),
                                  -sum(e.get("score") or [0]),
                                  e.get("source", "")))
        flat_vidpid.extend(rows)

    def _wc(p: pathlib.Path) -> int:
        return sum(1 for _ in p.read_text(encoding='utf-8').splitlines())
    log_counts = {
        "minor.log":    _wc(minor_log),
        "family.log":   _wc(family_log),
        "distinct.log": _wc(distinct_log),
        "vendor.log":   _wc(vendor_log),
    }

    for layer, counts in layer_counts.items():
        if any(counts.values()):
            print(f"merge[{layer}]: vendors={counts['vendors']} "
                  f"hints={counts['hint_vendors']} products={counts['products']}",
                  file=sys.stderr)
    primary_count = sum(1 for e in flat_vidpid if e.get("is_primary"))
    alt_count = len(flat_vidpid) - primary_count
    print(f"merge: {len(vid_vendor)} vendors, {primary_count} primary vidpid + "
          f"{alt_count} alternates", file=sys.stderr)
    print(f"merge: warnings: minor={log_counts['minor.log']} "
          f"family={log_counts['family.log']} "
          f"distinct={log_counts['distinct.log']} "
          f"vendor={log_counts['vendor.log']}", file=sys.stderr)

    vidpid_board_links = (other_data or {}).get("vidpid_board_links") or []

    return {
        "generated_at":       _now_iso(),
        "vid_vendor":         vid_vendor,
        "vidpid":             flat_vidpid,
        # Polyfill linkage rules forwarded verbatim from the `other` layer
        # so build_sqlite.py can expand them into the `board_vidpids`
        # junction. Validated upstream in extract_other.py.
        "vidpid_board_links": vidpid_board_links,
        "stats": {
            "total_vids":              len(vid_vendor),
            "total_vidpid_keys":       len(vidpid_rows),
            "total_vidpid_rows":       len(flat_vidpid),
            "vidpid_alternates":       alt_count,
            "vidpid_board_link_rules": len(vidpid_board_links),
            "warnings":                log_counts,
            "severity_counts":         severity_counts,
            "per_layer":               layer_counts,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--normalized-dir", required=True, type=pathlib.Path)
    p.add_argument("--out",            required=True, type=pathlib.Path)
    p.add_argument("--warnings-dir",   type=pathlib.Path)
    p.add_argument("--errors-dir",     type=pathlib.Path)
    args = p.parse_args()

    if args.warnings_dir is None and args.errors_dir is None:
        p.error("--warnings-dir or --errors-dir required")
    warnings_dir = args.warnings_dir or (args.errors_dir.parent / "warnings")
    errors_dir   = args.errors_dir   or (args.warnings_dir.parent / "errors")

    layer_files = [args.normalized_dir / f"{l}.json" for l in LAYER_ORDER]
    result = merge(layer_files, warnings_dir, errors_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"merge: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
