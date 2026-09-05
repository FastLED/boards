#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Dump every per-board JSON file from every PlatformIO ``platform-*`` repo.

Usage:
    uv run --no-project --script builders/platformio.py --out <dir>

For each PlatformIO ``platform-*`` repo:
  * Walks ``boards/`` and downloads each ``*.json`` board definition.
  * Downloads the top-level ``platform.json`` if present.
  * Writes to ``<out>/<plat>/boards/<file>.json`` (where ``<plat>`` is the
    repo name with the ``platform-`` prefix stripped) and
    ``<out>/<plat>/platform.json``.

Network calls to ``api.github.com`` use the ``GH_TOKEN`` / ``GITHUB_TOKEN``
env var when set to lift the unauthenticated 60-req/hr rate limit to
5000-req/hr. ``raw.githubusercontent.com`` does not require auth.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import requests

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
ORG = "platformio"
API_SLEEP = 0.3  # polite delay between api.github.com calls
HTTP_TIMEOUT = 30


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FastLED-boards-platformio-sync/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_get(session: requests.Session, url: str, params: dict | None = None) -> requests.Response:
    """GET against api.github.com with auth and a polite sleep afterward."""
    resp = session.get(url, params=params, headers=_auth_headers(), timeout=HTTP_TIMEOUT)
    time.sleep(API_SLEEP)
    return resp


def discover_platform_repos(session: requests.Session) -> list[str]:
    """Return sorted list of ``platform-*`` repo names under platformio org."""
    names: list[str] = []
    page = 1
    while True:
        url = f"{GITHUB_API}/orgs/{ORG}/repos"
        params = {"per_page": 100, "type": "public", "page": page}
        resp = _api_get(session, url, params=params)
        if resp.status_code != 200:
            _log(
                f"pio: failed to list repos page={page} status={resp.status_code} body={resp.text[:200]}"
            )
            break
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        for repo in batch:
            name = repo.get("name", "")
            if name.startswith("platform-"):
                names.append(name)
        if len(batch) < 100:
            break
        page += 1
    return sorted(set(names))


def _fetch_raw(session: requests.Session, url: str) -> bytes | None:
    """Fetch a raw.githubusercontent.com URL, returning bytes or None on failure."""
    try:
        resp = session.get(
            url,
            headers={"User-Agent": "FastLED-boards-platformio-sync/1.0"},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        _log(f"pio: GET {url} raised {exc!r}")
        return None
    if resp.status_code != 200:
        _log(f"pio: GET {url} -> {resp.status_code}")
        return None
    return resp.content


def _sync_one_platform(session: requests.Session, repo_name: str, out_root: Path) -> int:
    """Sync a single ``platform-<plat>`` repo. Returns count of board files written."""
    plat = repo_name[len("platform-"):]
    plat_out = out_root / plat
    boards_out = plat_out / "boards"

    # 1. Get default_branch
    repo_url = f"{GITHUB_API}/repos/{ORG}/{repo_name}"
    repo_resp = _api_get(session, repo_url)
    if repo_resp.status_code != 200:
        _log(
            f"pio[{plat}]: failed to fetch repo metadata status={repo_resp.status_code}"
        )
        return 0
    default_branch = repo_resp.json().get("default_branch", "develop")

    # 2. List boards/ contents
    contents_url = f"{GITHUB_API}/repos/{ORG}/{repo_name}/contents/boards"
    contents_resp = _api_get(session, contents_url, params={"ref": default_branch})
    if contents_resp.status_code != 200:
        # Some platform repos don't ship a boards/ directory.
        _log(
            f"pio[{plat}]: no boards/ directory (status={contents_resp.status_code})"
        )
        json_names: list[str] = []
    else:
        entries = contents_resp.json()
        if not isinstance(entries, list):
            _log(f"pio[{plat}]: boards/ listing not a list, skipping")
            entries = []
        json_names = [
            e["name"]
            for e in entries
            if isinstance(e, dict)
            and e.get("type") == "file"
            and isinstance(e.get("name"), str)
            and e["name"].endswith(".json")
        ]

    boards_out.mkdir(parents=True, exist_ok=True)

    # 3. Parallel raw fetches for board JSONs (per-platform)
    written = 0
    if json_names:
        def _worker(name: str) -> tuple[str, bytes | None]:
            url = f"{RAW_BASE}/{ORG}/{repo_name}/{default_branch}/boards/{name}"
            return name, _fetch_raw(session, url)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_worker, name) for name in json_names]
            for fut in as_completed(futures):
                name, data = fut.result()
                if data is None:
                    continue
                (boards_out / name).write_bytes(data)
                written += 1

    # 4. platform.json from repo root (best-effort)
    pj_url = f"{RAW_BASE}/{ORG}/{repo_name}/{default_branch}/platform.json"
    pj_data = _fetch_raw(session, pj_url)
    if pj_data is not None:
        plat_out.mkdir(parents=True, exist_ok=True)
        (plat_out / "platform.json").write_bytes(pj_data)

    _log(f"pio[{plat}]: {written} boards written to {boards_out}")
    return written


def sync_all(out_root: Path, only: Iterable[str] | None = None) -> tuple[int, int, int]:
    """Sync every platform-* repo. Returns (platforms_ok, platforms_failed, total_files)."""
    session = requests.Session()
    repos = discover_platform_repos(session)
    if only:
        filt = set(only)
        repos = [r for r in repos if r in filt or r[len("platform-"):] in filt]
    _log(f"pio: discovered {len(repos)} platform-* repos")

    ok = failed = total = 0
    for repo in repos:
        try:
            n = _sync_one_platform(session, repo, out_root)
        except Exception as exc:  # pragma: no cover - network surprises
            _log(f"pio[{repo}]: unexpected error {exc!r}")
            failed += 1
            continue
        # Treat "fetched metadata but zero boards" as a soft-ok; only count
        # full metadata failures as failed (handled inside _sync_one_platform
        # by returning 0 + warning logs). We approximate by checking the out
        # dir was created.
        if (out_root / repo[len("platform-"):]).exists():
            ok += 1
            total += n
        else:
            failed += 1
    return ok, failed, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="Output root directory")
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help="Restrict to specific platform name(s); can be repeated. "
             "Accepts either 'platform-espressif32' or 'espressif32'.",
    )
    args = parser.parse_args()

    out_root: Path = args.out
    out_root.mkdir(parents=True, exist_ok=True)

    ok, failed, total = sync_all(out_root, only=args.only)
    _log(
        f"pio: SUMMARY platforms_ok={ok} platforms_failed={failed} total_board_files={total}"
    )
    if ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
