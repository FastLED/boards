"""Recon test: take the 50 dict-KEY sample from
tests/test_search_keys_corpus.py, run each through the JS search
engine (via the Bun CLI), and dump every {query: response} to a JSON
file for analysis.

Hypothesis: dict keys are mostly JSON schema labels ('build', 'menu',
'size', 'frameworks', ...) and should produce zero or noise hits.
The exception is the STM32duino `menu.pnum.*` substructure where the
keys ARE board variant aliases (`GENERIC_F412ZEJX`, `NUCLEO_L4R5ZI`,
`MAPLEMINI_F103CB`) — those should hit thanks to the aliases column.

Soft assertion: every term produces a JSON entry. The actual content
gets analyzed offline from the dumped file.

Run:
    BOARDS_DB=%TEMP%\\fastled-boards-local.db python -m unittest tests.test_search_keys_results -v
or (post-deploy):
    python -m unittest tests.test_search_keys_results -v
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    from tests.test_search_keys_corpus import SEARCH_KEYS  # type: ignore
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from test_search_keys_corpus import SEARCH_KEYS  # type: ignore


REPO = pathlib.Path(__file__).resolve().parents[1]
BUN = shutil.which("bun")
QUERY_MJS = REPO / "tools" / "query.mjs"
LIVE_URL = "https://fastled.github.io/boards/boards.db"
RESULTS_PATH = os.path.join(
    tempfile.gettempdir(), "fastled-boards-search-keys-results.json"
)


def _db_arg() -> str:
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    return LIVE_URL


@unittest.skipIf(BUN is None, "bun runtime not installed")
class SearchKeysResultsTests(unittest.TestCase):

    def test_run_keys_against_js_engine(self) -> None:
        db = _db_arg()
        items = [{"text": k, "mode": "anything", "limit": 3} for k in SEARCH_KEYS]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(items, fh)
            batch_path = fh.name
        try:
            proc = subprocess.run(
                [BUN, str(QUERY_MJS), "--db", db, "--batch", batch_path],
                capture_output=True, text=True, timeout=180, check=True,
            )
        finally:
            os.unlink(batch_path)

        results = json.loads(proc.stdout)
        self.assertEqual(
            len(results), len(SEARCH_KEYS),
            f"expected {len(SEARCH_KEYS)} result entries, got {len(results)}",
        )

        # Materialise a {key: result} mapping and write it for analysis.
        mapped: dict[str, dict] = {}
        for key, res in zip(SEARCH_KEYS, results):
            mapped[key] = res
        with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
            json.dump(mapped, fh, indent=2, ensure_ascii=False)
        print(f"\nWrote {len(mapped)} key-results → {RESULTS_PATH}",
              file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
