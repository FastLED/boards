#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Site orchestrator: chain the per-layer extractors -> merge -> sqlite ->
Vite build -> bundle.

Runs (in order):
  1. extract_vendors.py    on  <data-root>/vendors/    -> normalized/vendors.json
  2. extract_arduino.py    on  <data-root>/arduino/    -> normalized/arduino.json
  3. extract_platformio.py on  <data-root>/platformio/ -> normalized/platformio.json
  4. extract_other.py      on  <data-root>/other/      -> normalized/other.json
  5. merge.py              -> merged.json + warnings/{vendor,product}-conflicts.log
  6. extract_boards.py     on  <data-root>            -> normalized/boards.json
  7. build_sqlite.py       -> <site-src>/public/boards.db
  7b. build_usb_ids.py   -> <site-src>/public/usb-ids.json
  8. stages per-board JSONs at <site-src>/public/boards/<layer>/…
  9. writes <site-src>/public/_meta.json + warnings/ + errors/
 10. `npm ci && npm run build` inside site-src/  →  site-src/dist/
 11. copies site-src/dist/* into <out>/

site-src/ is the front-end Vite project (npm + sqlite-wasm-http + the
memex patch). builders/ stay Python — they produce the data that Vite's
`public/` directory then serves verbatim.

Each Python step is also runnable standalone — this script just stitches
them together with consistent paths.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import shutil
import subprocess
import sys


HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SITE_SRC = REPO_ROOT / "site-src"


def _run_script(script: pathlib.Path, *args: str) -> None:
    cmd = ["uv", "run", "--no-project", "--script", str(script), *args]
    print(f"site: run {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _copy_board_jsons(boards: list[dict], data_root: pathlib.Path,
                       public_dir: pathlib.Path) -> int:
    """Stage each upstream board JSON into <public>/boards/<layer>/<src_relpath>.

    Tolerates both `<branch-root>/data/<sublayer>/boards/<id>.json` (data
    branches put files under `data/`) and `<branch-root>/<sublayer>/boards/
    <id>.json` (older flat layout)."""
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
        dst = public_dir / "boards" / layer / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied += 1
    print(f"site: staged {copied} board JSONs into {public_dir/'boards'} "
          f"({missing} missing)", file=sys.stderr)
    return copied


def _which(name: str) -> str | None:
    """Locate an executable, tolerating Windows extensions."""
    p = shutil.which(name)
    if p:
        return p
    if os.name == "nt":
        for ext in (".cmd", ".bat", ".exe"):
            p = shutil.which(name + ext)
            if p:
                return p
    return None


def _run_vite_build(site_src: pathlib.Path, skip_npm_ci: bool = False) -> None:
    npm = _which("npm")
    if not npm:
        raise RuntimeError("npm not found on PATH — install Node.js to build the site")

    if not skip_npm_ci:
        print(f"site: npm ci in {site_src}", file=sys.stderr)
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"],
                       cwd=site_src, check=True)

    print(f"site: npm run build in {site_src}", file=sys.stderr)
    subprocess.run([npm, "run", "build"], cwd=site_src, check=True)


def _copy_tree(src: pathlib.Path, dst: pathlib.Path) -> int:
    """Mirror src into dst (creating dst). Returns file count."""
    count = 0
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        out = dst / rel
        if path.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
            count += 1
    return count


def _clean_public(public_dir: pathlib.Path) -> None:
    """Wipe the generated subset of site-src/public/ — keep checked-in
    files (none currently) intact. We're explicit about what we touch
    so a stale board file from a previous run can't sneak through."""
    for name in ("boards.db", "site.db", "usb-ids.json", "_meta.json"):
        f = public_dir / name
        if f.exists():
            f.unlink()
    for sub in ("boards", "warnings", "errors"):
        d = public_dir / sub
        if d.exists():
            shutil.rmtree(d)


def orchestrate(
    data_root: pathlib.Path,
    out_dir: pathlib.Path,
    workdir: pathlib.Path,
    skip_build: bool = False,
    skip_npm_ci: bool = False,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    normalized = workdir / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)

    public_dir = SITE_SRC / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    _clean_public(public_dir)

    errors_dir   = public_dir / "errors"
    warnings_dir = public_dir / "warnings"
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

    # 5: merge
    _run_script(
        HERE / "merge.py",
        "--normalized-dir", str(normalized),
        "--out",            str(merged_path),
        "--warnings-dir",   str(warnings_dir),
        "--errors-dir",     str(errors_dir),
    )

    # 6: per-board metadata
    boards_path = normalized / "boards.json"
    _run_script(
        HERE / "extract_boards.py",
        "--in",  str(data_root),
        "--out", str(boards_path),
    )
    boards_data = json.loads(boards_path.read_text(encoding="utf-8"))

    # 6b: stage the per-board JSONs as Vite static assets
    boards_copied = _copy_board_jsons(boards_data.get("boards") or [],
                                       data_root, public_dir)

    # 7: sqlite → public/boards.db
    _run_script(
        HERE / "build_sqlite.py",
        "--merged", str(merged_path),
        "--boards", str(boards_path),
        "--out",    str(public_dir / "boards.db"),
    )

    # 7b: compact USB VID:PID direct-download JSON from the finished DB.
    _run_script(
        HERE / "build_usb_ids.py",
        "--db",  str(public_dir / "boards.db"),
        "--out", str(public_dir / "usb-ids.json"),
    )

    # 8: _meta.json (also written into public/ for Vite to serve)
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    stats = merged.get("stats", {})
    meta = {
        "schema_version": 5,
        "generated_at":   _now_iso(),
        "trigger":        os.environ.get("GITHUB_EVENT_NAME", "manual"),
        "totals": {
            "vendors":             stats.get("total_vids", 0),
            "vidpid_keys":         stats.get("total_vidpid_keys", 0),
            "vidpid_rows":         stats.get("total_vidpid_rows", 0),
            "vidpid_alternates":   stats.get("vidpid_alternates", 0),
            "boards":              len(boards_data.get("boards") or []),
            "board_jsons_copied":  boards_copied,
        },
        "warnings":         stats.get("warnings", {}),
        "severity_counts":  stats.get("severity_counts", {}),
        "per_layer_counts": stats.get("per_layer", {}),
        "errors_folder":    "errors/",
        "warnings_folder":  "warnings/",
        "database":         "boards.db",
        "usb_ids_download": "usb-ids.json",
        "loader":           "vite",
        "boards_root":      "boards/",
    }
    (public_dir / "_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 9: Vite build
    if not skip_build:
        _run_vite_build(SITE_SRC, skip_npm_ci=skip_npm_ci)

        # 10: mirror site-src/dist → out_dir
        dist = SITE_SRC / "dist"
        if not dist.is_dir():
            raise RuntimeError(f"Vite build did not produce {dist}")
        # Clear out_dir to keep it clean (preserves the parent)
        for entry in out_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        n = _copy_tree(dist, out_dir)
        print(f"site: copied {n} files from {dist} → {out_dir}", file=sys.stderr)

    print(f"site: bundle complete at {out_dir} -> {meta['totals']}", file=sys.stderr)
    return meta


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", required=True, type=pathlib.Path,
                   help="dir containing subdirs vendors/, arduino/, platformio/, other/")
    p.add_argument("--out",       required=True, type=pathlib.Path,
                   help="output bundle dir (will receive Vite's dist/* contents)")
    p.add_argument("--workdir",   default=pathlib.Path("/tmp/site-work"), type=pathlib.Path,
                   help="scratch dir for normalized/ + merged.json")
    p.add_argument("--skip-build", action="store_true",
                   help="skip Vite build (test mode)")
    p.add_argument("--skip-npm-ci", action="store_true",
                   help="skip 'npm ci' before build (use cached node_modules)")
    args = p.parse_args()
    orchestrate(args.data_root, args.out, args.workdir,
                skip_build=args.skip_build,
                skip_npm_ci=args.skip_npm_ci)
    return 0


if __name__ == "__main__":
    sys.exit(main())
