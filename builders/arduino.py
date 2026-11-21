#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Fetch and parse upstream Arduino-core ``boards.txt`` files into per-board JSON.

Usage:
    uv run --no-project --script builders/arduino.py --out <dir>

Each configured core is fetched once. The ``boards.txt`` content is parsed
into a nested dict per board id, then written as
``<out>/<core-slug>/boards/<board_id>.json`` along with a sibling
``_source.json`` describing the upstream commit/branch.

Designed to be tolerant of per-core failures (HTTP 404, parse glitches): the
script exits 0 if at least one core succeeded.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# (owner, repo, fallback_branch). ``default_branch`` is queried at runtime via
# the GitHub API; the fallback is used when the API call fails for any reason.
CORES: list[tuple[str, str, str]] = [
    ("arduino", "ArduinoCore-avr", "master"),
    ("arduino", "ArduinoCore-samd", "master"),
    ("arduino", "ArduinoCore-megaavr", "master"),
    ("arduino", "ArduinoCore-mbed", "main"),
    ("arduino", "ArduinoCore-renesas", "main"),
    ("espressif", "arduino-esp32", "master"),
    ("esp8266", "Arduino", "master"),
    ("adafruit", "Adafruit_nRF52_Arduino", "master"),
    ("stm32duino", "Arduino_Core_STM32", "main"),
    ("SiliconLabs", "arduino", "main"),
    ("earlephilhower", "arduino-pico", "master"),
]

HTTP_TIMEOUT = 30  # seconds
USER_AGENT = "fastled-boards-arduino-builder/1.0 (+https://github.com/FastLED/boards)"

# Matches a single ``boards.txt`` data line:
#     <board_id>.<dotted.key>=<value>
# We deliberately split only on the *first* dot (board id vs everything else)
# and only on the *first* ``=`` (value can contain ``=``).
_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\.([^=\s][^=]*?)\s*=\s*(.*?)\s*$")


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #


def _gh_headers() -> dict[str, str]:
    """Return headers for api.github.com calls (auth via GH_TOKEN / GITHUB_TOKEN if set)."""
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _raw_headers() -> dict[str, str]:
    """Headers for raw.githubusercontent.com fetches (no auth — raw is public for public repos)."""
    return {"User-Agent": USER_AGENT}


def resolve_default_branch(owner: str, repo: str, fallback: str) -> str:
    """Look up the repo's ``default_branch`` via the GitHub API; fall back on failure."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            branch = r.json().get("default_branch")
            if isinstance(branch, str) and branch:
                return branch
        print(
            f"arduino[{owner}/{repo}]: GitHub API returned {r.status_code}, "
            f"falling back to '{fallback}'",
            file=sys.stderr,
        )
    except requests.RequestException as exc:
        print(
            f"arduino[{owner}/{repo}]: GitHub API error ({exc}), "
            f"falling back to '{fallback}'",
            file=sys.stderr,
        )
    return fallback


def fetch_boards_txt(owner: str, repo: str, branch: str) -> tuple[str, str]:
    """Fetch the raw ``boards.txt`` body. Returns (text, source_url)."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/boards.txt"
    r = requests.get(url, headers=_raw_headers(), timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    # Force UTF-8; upstream files are ASCII/UTF-8 in practice.
    r.encoding = r.encoding or "utf-8"
    return r.text, url


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def _set_nested(d: dict[str, Any], path: list[str], value: str) -> None:
    """Set ``d[path[0]][path[1]]...[path[-1]] = value``, creating dicts as needed.

    If an intermediate node already exists and isn't a dict (string collision),
    we promote it to a dict with a ``""`` key holding the old value so we don't
    silently drop data. This is rare in practice but happens in a few cores
    (e.g. ``upload=`` and ``upload.tool=`` for the same board).
    """
    cur: dict[str, Any] = d
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            promoted: dict[str, Any] = {}
            if nxt is not None:
                promoted[""] = nxt
            cur[key] = promoted
            nxt = promoted
        cur = nxt
    leaf = path[-1]
    existing = cur.get(leaf)
    if isinstance(existing, dict):
        # We're trying to assign a scalar at a node that's already a subtree.
        # Stash it under the empty string instead of clobbering the subtree.
        existing[""] = value
    else:
        cur[leaf] = value


def parse_boards_txt(text: str) -> tuple[dict[str, dict[str, Any]], int]:
    """Parse a ``boards.txt`` body into ``{board_id: nested_dict}``.

    Returns the per-board dict plus the count of data lines actually processed
    (i.e. non-blank, non-comment lines that matched ``<id>.<key>=<value>``).
    """
    boards: dict[str, dict[str, Any]] = {}
    matched_lines = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        board_id, dotted_key, value = m.group(1), m.group(2), m.group(3)
        # Skip dropdown menu definitions ("menu.<id>=<label>") — these are
        # not boards, they're option-group declarations at the top of the file.
        if board_id == "menu":
            continue
        path = [p for p in dotted_key.split(".") if p]
        if not path:
            continue
        matched_lines += 1
        bd = boards.setdefault(board_id, {})
        _set_nested(bd, path, value)
    return boards, matched_lines


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #


def core_slug(owner: str, repo: str) -> str:
    """Return the slug used as the per-core directory name under ``<out>/``.

    Convention: ``<owner-lowercased>-<repo-lowercased>``, with slashes stripped
    (defensive — neither field should contain ``/`` in practice).
    """
    return f"{owner.lower().replace('/', '')}-{repo.lower().replace('/', '')}"


def write_core(
    out_root: Path,
    owner: str,
    repo: str,
    branch: str,
    source_url: str,
    boards: dict[str, dict[str, Any]],
) -> int:
    """Write per-board JSON + ``_source.json`` for a single core. Returns count written."""
    slug = core_slug(owner, repo)
    core_dir = out_root / slug
    boards_dir = core_dir / "boards"
    boards_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for board_id, data in sorted(boards.items()):
        target = boards_dir / f"{board_id}.json"
        with target.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        written += 1

    source_meta = {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "boards_count": written,
    }
    with (core_dir / "_source.json").open("w", encoding="utf-8") as f:
        json.dump(source_meta, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    return written


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def process_core(out_root: Path, owner: str, repo: str, fallback_branch: str) -> int:
    """Process a single core; return number of boards written (0 on failure)."""
    slug = core_slug(owner, repo)
    branch = resolve_default_branch(owner, repo, fallback_branch)
    try:
        text, source_url = fetch_boards_txt(owner, repo, branch)
    except requests.RequestException as exc:
        print(f"arduino[{slug}]: fetch failed: {exc}", file=sys.stderr)
        return 0

    try:
        boards, matched = parse_boards_txt(text)
    except Exception as exc:  # noqa: BLE001 — never let one core blow up the run
        print(f"arduino[{slug}]: parse failed: {exc}", file=sys.stderr)
        return 0

    if not boards:
        print(
            f"arduino[{slug}]: parsed 0 boards "
            f"(from boards.txt, {matched} lines) — skipping write",
            file=sys.stderr,
        )
        return 0

    try:
        written = write_core(out_root, owner, repo, branch, source_url, boards)
    except OSError as exc:
        print(f"arduino[{slug}]: write failed: {exc}", file=sys.stderr)
        return 0

    print(
        f"arduino[{slug}]: parsed {written} boards "
        f"(from boards.txt, {matched} lines)",
        file=sys.stderr,
    )
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch upstream Arduino-core boards.txt into JSON.")
    ap.add_argument("--out", required=True, help="Output directory (will be created).")
    args = ap.parse_args()

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    cores_succeeded = 0
    total_boards = 0
    for owner, repo, fb in CORES:
        n = process_core(out_root, owner, repo, fb)
        if n > 0:
            cores_succeeded += 1
            total_boards += n

    print(
        f"arduino: done — {cores_succeeded}/{len(CORES)} cores succeeded, "
        f"{total_boards} boards written to {out_root}",
        file=sys.stderr,
    )

    if cores_succeeded == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
