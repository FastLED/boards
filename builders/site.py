#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Site orchestrator: chain the per-layer extractors -> merge -> sqlite -> bundle.

Runs (in order):
  1. extract_vendors.py    on  <data-root>/vendors/    -> normalized/vendors.json
  2. extract_arduino.py    on  <data-root>/arduino/    -> normalized/arduino.json
  3. extract_platformio.py on  <data-root>/platformio/ -> normalized/platformio.json
  4. extract_other.py      on  <data-root>/other/      -> normalized/other.json
  5. merge.py              -> merged.json + errors/{vendor,product}-conflicts.log
  6. extract_boards.py     on  <data-root>            -> normalized/boards.json
  7. copies each platformio/arduino board JSON into <out>/boards/<layer>/<...>.json
  8. build_sqlite.py       -> <out>/site.db (includes the `boards` table)
  9. copies templates/index.html      -> <out>/index.html
 10. downloads pinned sql-wasm.js/.wasm assets from the GitHub release
 11. writes <out>/_meta.json + <out>/errors/  (the errors folder ships with
     the site so humans can inspect what was logged)

Each extractor / merger / builder is also runnable standalone — this script
just stitches them together with consistent paths.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import urllib.request


SQLJS_VERSION = "1.10.3"
SQLJS_BASE = ("https://github.com/sql-js/sql.js/releases/download/"
              f"v{SQLJS_VERSION}/sqljs-wasm.zip")
HERE = pathlib.Path(__file__).resolve().parent


def _run_script(script: pathlib.Path, *args: str) -> None:
    cmd = ["uv", "run", "--no-project", "--script", str(script), *args]
    print(f"site: run {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ssl_ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _copy_board_jsons(boards: list[dict], data_root: pathlib.Path,
                       out_dir: pathlib.Path) -> int:
    """Stage each upstream board JSON into <out>/boards/<layer>/<src_relpath>.

    The data branches put their per-board JSONs at either
    `<branch-root>/data/<sublayer>/boards/<id>.json` or directly at
    `<branch-root>/<sublayer>/boards/<id>.json` (depending on the sync).
    Tolerate both."""
    copied = 0
    missing = 0
    for b in boards:
        layer = b["layer"]
        relpath = b["src_relpath"]
        src_data = data_root / layer / "data" / relpath
        src_flat = data_root / layer / relpath
        src = src_data if src_data.is_file() else (src_flat if src_flat.is_file() else None)
        if src is None:
            missing += 1
            continue
        dst = out_dir / "boards" / layer / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied += 1
    print(f"site: staged {copied} board JSONs into {out_dir/'boards'} "
          f"({missing} missing)", file=sys.stderr)
    return copied


def _download_sqljs(out_dir: pathlib.Path) -> None:
    """Fetch sql-wasm.js + sql-wasm.wasm from the pinned sql.js release."""
    import io, zipfile
    req = urllib.request.Request(SQLJS_BASE, headers={
        "User-Agent": "fbuild-bot/1.0 (+https://github.com/FastLED/boards)"
    })
    print(f"site: downloading {SQLJS_BASE}", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as r:
        blob = r.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        js_entry = wasm_entry = None
        for n in zf.namelist():
            if n.endswith("/sql-wasm.js") or n == "sql-wasm.js":
                js_entry = n
            elif n.endswith("/sql-wasm.wasm") or n == "sql-wasm.wasm":
                wasm_entry = n
        if not js_entry or not wasm_entry:
            raise RuntimeError(
                f"sqljs archive missing sql-wasm.{{js,wasm}}: entries={zf.namelist()[:6]}"
            )
        (out_dir / "sql-wasm.js").write_bytes(zf.read(js_entry))
        (out_dir / "sql-wasm.wasm").write_bytes(zf.read(wasm_entry))
    print(f"site: staged sql-wasm.js ({(out_dir/'sql-wasm.js').stat().st_size:,} B) + "
          f"sql-wasm.wasm ({(out_dir/'sql-wasm.wasm').stat().st_size:,} B)",
          file=sys.stderr)


def orchestrate(
    data_root: pathlib.Path,
    out_dir: pathlib.Path,
    workdir: pathlib.Path,
    skip_sqljs: bool = False,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    normalized = workdir / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    errors_dir   = out_dir / "errors"      # hard failures (parse fails, etc.)
    warnings_dir = out_dir / "warnings"    # conflict logs from merger
    errors_dir.mkdir(parents=True, exist_ok=True)
    warnings_dir.mkdir(parents=True, exist_ok=True)
    merged_path = workdir / "merged.json"

    # 1-4: extractors
    for layer in ("vendors", "arduino", "platformio", "other"):
        layer_in = data_root / layer
        _run_script(
            HERE / f"extract_{layer}.py",
            "--in",  str(layer_in),
            "--out", str(normalized / f"{layer}.json"),
        )

    # 5: merge (writes severity-bucketed conflict logs to warnings/, NOT errors/)
    _run_script(
        HERE / "merge.py",
        "--normalized-dir", str(normalized),
        "--out",            str(merged_path),
        "--warnings-dir",   str(warnings_dir),
        "--errors-dir",     str(errors_dir),
    )

    # 6: per-board metadata extraction
    boards_path = normalized / "boards.json"
    _run_script(
        HERE / "extract_boards.py",
        "--in",  str(data_root),
        "--out", str(boards_path),
    )

    # 7: copy each board JSON into the published bundle so the portal's
    # "View JSON" button is a static fetch.
    boards_data = json.loads(boards_path.read_text(encoding="utf-8"))
    boards_copied = _copy_board_jsons(boards_data.get("boards") or [],
                                       data_root, out_dir)

    # 8: sqlite (now includes the `boards` table)
    _run_script(
        HERE / "build_sqlite.py",
        "--merged", str(merged_path),
        "--boards", str(boards_path),
        "--out",    str(out_dir / "site.db"),
    )

    # 9: copy demo HTML
    shutil.copyfile(HERE / "templates" / "index.html", out_dir / "index.html")

    # 10: sql.js
    if not skip_sqljs:
        _download_sqljs(out_dir)

    # 11: _meta.json
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    stats = merged.get("stats", {})
    meta = {
        "schema_version": 3,
        "generated_at":   _now_iso(),
        "trigger":        os.environ.get("GITHUB_EVENT_NAME", "manual"),
        "totals": {
            "vendors":               stats.get("total_vids", 0),
            "vidpid_keys":           stats.get("total_vidpid_keys", 0),
            "vidpid_rows":           stats.get("total_vidpid_rows", 0),
            "vidpid_alternates":     stats.get("vidpid_alternates", 0),
            "boards":                len(boards_data.get("boards") or []),
            "board_jsons_copied":    boards_copied,
        },
        "warnings":         stats.get("warnings", {}),
        "severity_counts":  stats.get("severity_counts", {}),
        "per_layer_counts": stats.get("per_layer", {}),
        "errors_folder":    "errors/",
        "warnings_folder":  "warnings/",
        "database":         "site.db",
        "demo":             "index.html",
        "boards_root":      "boards/",
    }
    (out_dir / "_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"site: bundle complete at {out_dir} -> {meta['totals']}", file=sys.stderr)
    return meta


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", required=True, type=pathlib.Path,
                   help="dir containing subdirs vendors/, arduino/, platformio/, other/")
    p.add_argument("--out",       required=True, type=pathlib.Path,
                   help="output site bundle dir (will receive site.db, index.html, etc.)")
    p.add_argument("--workdir",   default=pathlib.Path("/tmp/site-work"), type=pathlib.Path,
                   help="scratch dir for normalized/ + merged.json")
    p.add_argument("--skip-sqljs", action="store_true",
                   help="(test mode) don't download sql.js — useful for offline tests")
    args = p.parse_args()
    orchestrate(args.data_root, args.out, args.workdir, skip_sqljs=args.skip_sqljs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
