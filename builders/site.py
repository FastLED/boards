#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Aggregate every per-board JSON file from the four data branches into a
small static-site bundle.

Usage:
    uv run --no-project --script builders/site.py \
        --data-root <DIR> --out <DIR> [--source-shas FILE]

``--data-root`` must contain (zero or more of) subdirectories named
``platformio/``, ``arduino/``, ``vendors/``, ``other/`` -- each one a
fully-checked-out worktree of the matching orphan data branch. Branches
whose worktree directory is missing are silently skipped so the script
remains useful during bootstrap when only 1-2 branches have been
populated.

Outputs three files to ``--out``:

* ``aggregate.json``   - one big dict keyed by
                          ``<branch>/<relative-path-without-extension>``,
                          values are the parsed JSON contents of each
                          per-board / per-platform file. Pretty-printed,
                          ``sort_keys=True`` for stable diffs.
* ``_meta.json``       - schema-versioned metadata: generation timestamp,
                          per-branch counts + branch_meta + source SHA,
                          totals.
* ``index.html``       - minimal vanilla-JS substring search UI (no
                          external deps, no framework).

The ``_meta.json`` and ``_source.json`` files found inside each branch
are folded into the site bundle's own ``_meta.json`` rather than the
aggregate dataset.

Exits 0 even if zero branches are present (valid bootstrap state).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

BRANCHES: tuple[str, ...] = ("platformio", "arduino", "vendors", "other")
META_FILENAMES: frozenset[str] = frozenset({"_meta.json", "_source.json"})
SCHEMA_VERSION: int = 1
INDEX_TOP_RESULTS: int = 50


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _aggregate_branch(branch: str, root: Path) -> tuple[dict[str, object], dict | None]:
    """Walk one branch worktree.

    Returns (aggregate_subset, branch_meta) where:
      * aggregate_subset is keyed by ``<branch>/<relpath-without-.json>``;
      * branch_meta is the parsed ``_meta.json`` at the root of the
        worktree (or ``None`` if no such file exists / it failed to parse).
    """
    subset: dict[str, object] = {}
    branch_meta: dict | None = None

    for path in sorted(root.rglob("*.json")):
        if not path.is_file():
            continue
        name = path.name
        if name in META_FILENAMES:
            # Capture the top-level _meta.json for branch_meta; ignore
            # any nested _meta.json / _source.json files entirely.
            if name == "_meta.json" and path.parent == root:
                try:
                    branch_meta = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    _log(f"site: WARN failed to parse {path}: {exc!r}")
            continue

        rel = path.relative_to(root)
        # Strip the .json suffix for the key; keep POSIX-style separators.
        rel_no_ext = rel.with_suffix("")
        key = f"{branch}/{rel_no_ext.as_posix()}"

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log(f"site: WARN failed to parse {path}: {exc!r}; skipping")
            continue

        if key in subset:
            # Should not happen given filesystem unique-path guarantees,
            # but log loudly if it does.
            _log(f"site: WARN duplicate key {key!r} (path={path})")
        subset[key] = value

    return subset, branch_meta


# --------------------------------------------------------------------------- #
# index.html
# --------------------------------------------------------------------------- #


INDEX_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FastLED boards registry</title>
<style>
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  margin: 0; padding: 1rem 1.25rem; line-height: 1.4;
}
header { margin-bottom: 1rem; }
header h1 { margin: 0 0 0.25rem 0; font-size: 1.2rem; }
header .meta { color: #666; font-size: 0.85rem; }
#q {
  width: 100%; padding: 0.6rem 0.75rem; font-size: 1rem;
  border: 1px solid #888; border-radius: 4px;
}
#status { font-size: 0.85rem; color: #666; margin: 0.5rem 0; min-height: 1.2em; }
#results { list-style: none; padding: 0; margin: 0; }
#results li { margin: 0.25rem 0; }
details { border: 1px solid #ccc; border-radius: 4px; padding: 0.4rem 0.6rem; }
details > summary { cursor: pointer; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9rem; word-break: break-all; }
details[open] > summary { margin-bottom: 0.4rem; }
pre {
  margin: 0; padding: 0.5rem 0.6rem; background: #f4f4f4; color: #111;
  border-radius: 3px; overflow-x: auto; font-size: 0.8rem;
}
@media (prefers-color-scheme: dark) {
  pre { background: #1e1e1e; color: #eee; }
  details { border-color: #444; }
}
.note { color: #888; font-style: italic; }
</style>
</head>
<body>
<header>
  <h1>FastLED boards registry</h1>
  <div class="meta">Generated <code>__GENERATED_AT__</code> &middot; branches: <code>__BRANCHES__</code> &middot; <code>__KEY_COUNT__</code> entries.</div>
</header>
<input id="q" type="search" placeholder="Substring search (case-insensitive)... e.g. esp32, uno, 0x303A" autocomplete="off" autofocus>
<div id="status" class="note">Type to search. Data loads on first keystroke.</div>
<ul id="results"></ul>
<script>
"use strict";
const TOP_N = __TOP_N__;
let DATA = null;
let KEYS = null;
let loading = null;
const q = document.getElementById("q");
const status = document.getElementById("status");
const results = document.getElementById("results");

async function ensureData() {
  if (DATA) return DATA;
  if (loading) return loading;
  status.textContent = "Loading aggregate.json...";
  loading = fetch("aggregate.json")
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(j => { DATA = j; KEYS = Object.keys(j); status.textContent = `Loaded ${KEYS.length} entries.`; return j; })
    .catch(e => { status.textContent = "Failed to load aggregate.json: " + e.message; throw e; });
  return loading;
}

function escapeText(s) {
  const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
}

function render(matches) {
  results.replaceChildren();
  if (matches.length === 0) {
    status.textContent = `No matches for "${q.value}".`;
    return;
  }
  status.textContent = `${matches.length} shown of up to ${TOP_N} matches.`;
  const frag = document.createDocumentFragment();
  for (const key of matches) {
    const li = document.createElement("li");
    const d = document.createElement("details");
    const sm = document.createElement("summary");
    sm.textContent = key;
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(DATA[key], null, 2);
    d.appendChild(sm); d.appendChild(pre); li.appendChild(d);
    frag.appendChild(li);
  }
  results.appendChild(frag);
}

let timer = null;
async function onInput() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const term = q.value.trim().toLowerCase();
    if (!term) { results.replaceChildren(); status.textContent = "Type to search."; return; }
    try { await ensureData(); } catch { return; }
    const hits = [];
    for (const k of KEYS) {
      if (k.toLowerCase().includes(term)) {
        hits.push(k);
        if (hits.length >= TOP_N) break;
      }
    }
    render(hits);
  }, 80);
}
q.addEventListener("input", onInput);
</script>
</body>
</html>
"""


def build_index_html(generated_at: str, branches_present: list[str], key_count: int) -> str:
    return (
        INDEX_HTML_TEMPLATE.replace("__GENERATED_AT__", generated_at)
        .replace("__BRANCHES__", ", ".join(branches_present) if branches_present else "(none)")
        .replace("__KEY_COUNT__", str(key_count))
        .replace("__TOP_N__", str(INDEX_TOP_RESULTS))
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def _load_source_shas(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log(f"site: WARN failed to parse --source-shas {path}: {exc!r}")
        return {}
    if not isinstance(raw, dict):
        _log(f"site: WARN --source-shas {path} is not a JSON object; ignoring")
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", required=True, type=Path,
                        help="Directory containing per-branch worktree subdirs")
    parser.add_argument("--out", required=True, type=Path,
                        help="Output directory for site bundle")
    parser.add_argument("--source-shas", type=Path, default=None,
                        help="Optional JSON file mapping branch name -> upstream commit SHA")
    args = parser.parse_args()

    t0 = time.monotonic()
    data_root: Path = args.data_root
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    source_shas = _load_source_shas(args.source_shas)

    aggregate: dict[str, object] = {}
    branch_summaries: dict[str, dict] = {}
    branches_present: list[str] = []

    for branch in BRANCHES:
        bdir = data_root / branch
        if not bdir.is_dir():
            _log(f"site: {branch} -> SKIP (no worktree at {bdir})")
            continue
        subset, branch_meta = _aggregate_branch(branch, bdir)
        aggregate.update(subset)
        branches_present.append(branch)
        branch_summaries[branch] = {
            "files_indexed": len(subset),
            "branch_meta": branch_meta,
            "source_sha": source_shas.get(branch),
        }
        _log(f"site: {branch} -> {len(subset)} keys")

    # Write aggregate.json (pretty-printed, sorted).
    aggregate_path = out / "aggregate.json"
    aggregate_bytes = json.dumps(aggregate, indent=2, sort_keys=True).encode("utf-8")
    aggregate_path.write_bytes(aggregate_bytes)
    _log(f"site: aggregate.json size={len(aggregate_bytes)} bytes keys={len(aggregate)}")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trigger = os.environ.get("GITHUB_EVENT_NAME") or "manual"

    meta = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "trigger": trigger,
        "branches": branch_summaries,
        "totals": {
            "branches_present": len(branches_present),
            "aggregate_keys": len(aggregate),
            "aggregate_size_bytes": len(aggregate_bytes),
        },
    }
    (out / "_meta.json").write_bytes(
        json.dumps(meta, indent=2, sort_keys=True).encode("utf-8")
    )

    # Write index.html.
    (out / "index.html").write_text(
        build_index_html(generated_at, branches_present, len(aggregate)),
        encoding="utf-8",
    )

    elapsed = time.monotonic() - t0
    _log(
        f"site: SUMMARY branches_present={len(branches_present)} "
        f"aggregate_keys={len(aggregate)} elapsed={elapsed:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
