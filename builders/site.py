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
                                                          (json_text inlined)
  7. build_sqlite.py       -> <out>/site.db (boards + boards_fts, json_blob
                              column carries each upstream board JSON)
  8. copies templates/index.html      -> <out>/index.html
  9. downloads sql.js-httpvfs (index.js + sqlite.worker.js + sql-wasm.wasm)
     so the portal can serve the DB via HTTP Range requests
 10. writes <out>/_meta.json + <out>/errors/  (the errors folder ships with
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


SQLJS_HTTPVFS_VERSION = "0.8.12"
SQLJS_HTTPVFS_BASE = ("https://cdn.jsdelivr.net/npm/"
                      f"sql.js-httpvfs@{SQLJS_HTTPVFS_VERSION}/dist")
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


_HTTPVFS_ASSETS = ("index.js", "sqlite.worker.js", "sql-wasm.wasm")

# Prepended to sqlite.worker.js. GH Pages' Fastly layer gzips
# application/octet-stream responses when the client advertises gzip — but
# returns the WHOLE gzipped file with HTTP 200 even when Range was asked
# for, defeating byte-range loading entirely (sql.js-httpvfs then fails
# with "database disk image is malformed"). Setting Accept-Encoding:
# identity opts out of compression so Range works (returns 206 Partial
# Content with the true uncompressed byte slice). Same workaround memex
# uses; observed on the wire from Chrome despite Accept-Encoding being a
# spec-forbidden header (Chrome allows it in worker contexts).
_HTTPVFS_WORKER_SHIM = (
    b"// patched by builders/site.py: opt out of GH Pages gzip so HTTP\n"
    b"// Range requests are honored. Without this, every range fetch\n"
    b"// returns the full gzipped file and sql.js-httpvfs misreads pages.\n"
    b"(function(){\n"
    b"  var _fetch=self.fetch;\n"
    b"  if(_fetch){self.fetch=function(input,init){\n"
    b"    init=init||{}; var h=new Headers(init.headers||{});\n"
    b"    h.set('Accept-Encoding','identity');\n"
    b"    var copy={}; for(var k in init){copy[k]=init[k];} copy.headers=h;\n"
    b"    return _fetch(input,copy);\n"
    b"  };}\n"
    b"  var _open=XMLHttpRequest.prototype.open;\n"
    b"  XMLHttpRequest.prototype.open=function(){\n"
    b"    var r=_open.apply(this,arguments);\n"
    b"    try{this.setRequestHeader('Accept-Encoding','identity');}catch(e){}\n"
    b"    return r;\n"
    b"  };\n"
    b"})();\n"
)


def _download_sqljs_httpvfs(out_dir: pathlib.Path) -> None:
    """Fetch sql.js-httpvfs (index.js + sqlite.worker.js + sql-wasm.wasm)
    from jsdelivr. Staged as <out>/sql-httpvfs.js + <out>/sqlite.worker.js
    + <out>/sql-wasm.wasm so the portal serves them same-origin.

    sqlite.worker.js is prepended with a small Accept-Encoding: identity
    shim — see _HTTPVFS_WORKER_SHIM for the why."""
    for asset in _HTTPVFS_ASSETS:
        url = f"{SQLJS_HTTPVFS_BASE}/{asset}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "fbuild-bot/1.0 (+https://github.com/FastLED/boards)"
        })
        print(f"site: downloading {url}", file=sys.stderr)
        with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as r:
            blob = r.read()
        # Rename index.js -> sql-httpvfs.js so its purpose is obvious in the
        # bundle; the other two keep their package names because the worker
        # internally references sql-wasm.wasm by that path.
        out_name = "sql-httpvfs.js" if asset == "index.js" else asset
        if asset == "sqlite.worker.js":
            blob = _HTTPVFS_WORKER_SHIM + blob
        (out_dir / out_name).write_bytes(blob)
        print(f"site: staged {out_name} ({len(blob):,} B)", file=sys.stderr)


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

    # 6: per-board metadata extraction (json_text inlined into each record)
    boards_path = normalized / "boards.json"
    _run_script(
        HERE / "extract_boards.py",
        "--in",  str(data_root),
        "--out", str(boards_path),
    )
    boards_data = json.loads(boards_path.read_text(encoding="utf-8"))

    # 7: sqlite (boards + boards_fts + json_blob)
    _run_script(
        HERE / "build_sqlite.py",
        "--merged", str(merged_path),
        "--boards", str(boards_path),
        "--out",    str(out_dir / "site.db"),
    )

    # 8: copy demo HTML
    shutil.copyfile(HERE / "templates" / "index.html", out_dir / "index.html")

    # 9: sql.js-httpvfs
    if not skip_sqljs:
        _download_sqljs_httpvfs(out_dir)

    # 10: _meta.json
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    stats = merged.get("stats", {})
    meta = {
        "schema_version": 4,
        "generated_at":   _now_iso(),
        "trigger":        os.environ.get("GITHUB_EVENT_NAME", "manual"),
        "totals": {
            "vendors":               stats.get("total_vids", 0),
            "vidpid_keys":           stats.get("total_vidpid_keys", 0),
            "vidpid_rows":           stats.get("total_vidpid_rows", 0),
            "vidpid_alternates":     stats.get("vidpid_alternates", 0),
            "boards":                len(boards_data.get("boards") or []),
        },
        "warnings":         stats.get("warnings", {}),
        "severity_counts":  stats.get("severity_counts", {}),
        "per_layer_counts": stats.get("per_layer", {}),
        "errors_folder":    "errors/",
        "warnings_folder":  "warnings/",
        "database":         "site.db",
        "demo":             "index.html",
        "loader":           "sql-httpvfs.js",
        "sqljs_httpvfs_version": SQLJS_HTTPVFS_VERSION,
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
