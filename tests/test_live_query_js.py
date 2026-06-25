"""End-to-end test that drives the actual JS search engine via Bun.

The previous Python tests (test_search_corpus_results.py,
test_search_zero_terms.py) ported the portal's ftsQuery() + SQL
queries into Python so we could test against the live boards.db
without a JS runtime. That works, but the Python implementation can
drift away from the JS source — silent divergence is exactly the kind
of bug a test should catch.

This test runs the SAME `site-src/src/search/engine.js` the portal
uses, against the SAME boards.db, via the `tools/query.mjs` Bun CLI.
Output is parsed from JSON and asserted. No SQL string lives in
Python anymore.

Requirements:
  - `bun` on PATH (https://bun.sh)
  - BOARDS_DB env var to point at a local DB (recommended for iteration),
    otherwise the CLI fetches the live published boards.db on each run.

Run:
    BOARDS_DB=%TEMP%\\fastled-boards-local.db python -m unittest tests.test_live_query_js -v
or:
    python -m unittest tests.test_live_query_js -v   # falls back to live URL
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


REPO = pathlib.Path(__file__).resolve().parents[1]
BUN = shutil.which("bun")
QUERY_MJS = REPO / "tools" / "query.mjs"
LIVE_URL = "https://fastled.github.io/boards/boards.db"


RAW_VID_COUNTS_SCRIPT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo, dbSource, vid] = process.argv.slice(2);
const { openDb } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/db/index.js')).href
);

const db = await openDb({ source: dbSource });
try {
  const products = await db.query(
    'SELECT COUNT(*) AS n FROM vidpid WHERE vid = ?',
    [vid],
  );
  const boards = await db.query(
    'SELECT COUNT(*) AS n FROM (' +
      'SELECT DISTINCT b.rowid FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      'WHERE bv.vid = ?' +
    ')',
    [vid],
  );
  process.stdout.write(JSON.stringify({
    products: products[0].n,
    boards: boards[0].n,
  }));
} finally {
  await db.close();
}
"""


QUERY_SHAPE_SCRIPT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo, dbSource, text, mode = 'anything'] = process.argv.slice(2);
const { openDb } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/db/index.js')).href
);
const { searchUniversal, searchVendor, searchProduct, searchBoard } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/search/engine.js')).href
);

const MODES = {
  anything: searchUniversal,
  vendor: searchVendor,
  product: searchProduct,
  board: searchBoard,
};

const db = await openDb({ source: dbSource });
const calls = [];
const query = async (sql, args = []) => {
  calls.push({ sql, args });
  return db.query(sql, args);
};

try {
  const data = await MODES[mode](text, query);
  process.stdout.write(JSON.stringify({
    data,
    calls,
    counts: {
      previews: data.previews?.length ?? 0,
      vendors: data.vendors?.length ?? 0,
      products: data.products?.length ?? 0,
      boards: data.boards?.length ?? 0,
    },
  }));
} finally {
  await db.close();
}
"""


def _db_arg() -> str:
    """Honor BOARDS_DB env override; fall back to the live URL."""
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    local_db = REPO / "site-src" / "dist" / "boards.db"
    if local_db.exists():
        return str(local_db)
    return LIVE_URL


def _run_batch(db: str, items: list[dict], timeout: int = 120) -> list[dict]:
    """Invoke the Bun CLI in batch mode against `db` with the given
    items and return the parsed JSON list. Raises CalledProcessError
    on non-zero exit so test failures surface the CLI stderr."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(items, fh)
        batch_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, str(QUERY_MJS), "--db", db, "--batch", batch_path],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AssertionError(
            f"bun query.mjs exit {e.returncode}\nstderr:\n{e.stderr}\n"
            f"stdout:\n{e.stdout[:1000]}"
        ) from e
    finally:
        os.unlink(batch_path)
    return json.loads(proc.stdout)


def _raw_vid_counts(db: str, vid: str, timeout: int = 120) -> dict:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjs", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(RAW_VID_COUNTS_SCRIPT.strip() + "\n")
        script_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, script_path, str(REPO), db, vid],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AssertionError(
            f"bun raw VID count exit {e.returncode}\nstderr:\n{e.stderr}\n"
            f"stdout:\n{e.stdout[:1000]}"
        ) from e
    finally:
        os.unlink(script_path)
    return json.loads(proc.stdout)


def _query_shape(db: str, text: str, mode: str = "anything", timeout: int = 120) -> dict:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjs", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(QUERY_SHAPE_SCRIPT.strip() + "\n")
        script_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, script_path, str(REPO), db, text, mode],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AssertionError(
            f"bun query-shape exit {e.returncode}\nstderr:\n{e.stderr}\n"
            f"stdout:\n{e.stdout[:1000]}"
        ) from e
    finally:
        os.unlink(script_path)
    return json.loads(proc.stdout)


@unittest.skipIf(BUN is None, "bun runtime not installed; skipping JS-engine tests")
class LiveQueryJsTests(unittest.TestCase):
    """Run the JS search engine against the live or local boards.db
    and assert the same headline contracts the Python tests cover.
    Replaces nothing — runs alongside them as a parity check that the
    JS engine produces the expected answers."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = _db_arg()
        # Sanity-warm one query so the rest of the test methods don't
        # all eat the URL download cost on cold cache.
        _run_batch(cls.db, [{"text": "teensy40", "mode": "board", "limit": 1}])

    def test_teensy40_resolves_via_board_mode(self) -> None:
        results = _run_batch(self.db, [{"text": "teensy40", "mode": "board"}])
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["mode"], "board")
        boards = r["data"]["boards"]
        self.assertTrue(boards, f"teensy40 should hit at least one board: {r}")
        top = boards[0]["row"]
        self.assertEqual(top["board_id"], "teensy40")
        self.assertIn("teensy", top["name"].lower())

    def test_vidpid_16c0_0483_returns_full_set(self) -> None:
        """Exact VID:PID query hits all 10 Teensy variants via the
        board_vidpids junction enrichment in searchUniversal()."""
        results = _run_batch(self.db, [{"text": "16c0:0483", "mode": "anything"}])
        r = results[0]
        self.assertGreaterEqual(
            len(r["data"]["products"]), 1,
            f"16c0:0483 should return ≥1 vidpid row: {r['counts']}")
        self.assertGreaterEqual(
            len(r["data"]["boards"]), 9,
            f"16c0:0483 should JOIN to ≥9 Teensy boards via the junction: "
            f"{r['counts']}")
        # Every joined board must be a Teensy.
        non_teensy = [
            b["row"]["board_id"] for b in r["data"]["boards"]
            if "teensy" not in b["row"]["name"].lower()
        ]
        self.assertFalse(non_teensy,
                         f"non-Teensy boards in 16c0:0483 result: {non_teensy}")

    def test_303a_returns_vid_preview_document(self) -> None:
        results = _run_batch(self.db, [{"text": "303a", "mode": "anything"}])
        r = results[0]
        previews = r["data"].get("previews", [])
        preview = next(
            (p for p in previews if p.get("kind") == "vid" and p.get("vid") == "303a"),
            None,
        )
        self.assertIsNotNone(preview, f"303a should return a VID preview: {r}")
        self.assertEqual(preview["vendor"], "Espressif Systems")
        self.assertEqual(preview["reason"]["label"], "exact VID")
        self.assertEqual(preview["reason"]["field"], "vid")
        self.assertEqual(preview["reason"]["value"], "303a")
        self.assertEqual(preview["reason"]["strength"], "exact")

        raw_counts = _raw_vid_counts(self.db, "303a")
        self.assertEqual(len(r["data"]["vendors"]), 1)
        self.assertEqual(r["data"]["vendors"][0]["row"]["vid"], "303a")
        self.assertEqual(r["data"]["products"], [])
        self.assertEqual(r["data"]["boards"], [])
        self.assertEqual(preview["knownBoards"]["total"], raw_counts["boards"])
        self.assertEqual(preview["knownProducts"]["total"], raw_counts["products"])
        self.assertGreater(preview["knownBoards"]["total"], 0)
        self.assertTrue(preview["knownBoards"]["sample"])

    def test_exact_vid_fast_path_avoids_unscoped_fts(self) -> None:
        payload = _query_shape(self.db, "303a")
        self.assertEqual(
            payload["counts"],
            {"previews": 1, "vendors": 1, "products": 0, "boards": 0},
            payload,
        )
        sql_text = "\n".join(call["sql"] for call in payload["calls"]).lower()
        self.assertNotIn(" match ", sql_text)
        self.assertNotIn("_fts", sql_text)
        self.assertNotIn("bm25", sql_text)
        self.assertLessEqual(
            len(payload["calls"]),
            5,
            "exact VID should only fetch vendor plus preview product/board summaries:\n"
            + json.dumps(payload["calls"], indent=2),
        )

    def test_product_mode_303a_uses_compact_vid_preview(self) -> None:
        results = _run_batch(self.db, [{"text": "303a", "mode": "product"}])
        r = results[0]
        previews = r["data"].get("previews", [])
        preview = next(
            (p for p in previews if p.get("kind") == "vid" and p.get("vid") == "303a"),
            None,
        )
        self.assertIsNotNone(
            preview,
            "USB Products mode should answer a bare exact VID with a compact "
            f"VID preview instead of a long VID:PID dump: {r}",
        )
        self.assertEqual(preview["vendor"], "Espressif Systems")

        raw_counts = _raw_vid_counts(self.db, "303a")
        self.assertEqual(preview["knownProducts"]["total"], raw_counts["products"])
        self.assertEqual(preview["knownBoards"]["total"], raw_counts["boards"])
        self.assertTrue(preview["knownProducts"]["sample"])
        self.assertEqual(r["data"].get("products"), [])
        self.assertEqual(r["data"].get("boards"), [])

    def test_product_mode_exact_vid_avoids_unscoped_fts(self) -> None:
        payload = _query_shape(self.db, "303a", mode="product")
        self.assertEqual(
            payload["counts"],
            {"previews": 1, "vendors": 0, "products": 0, "boards": 0},
            payload,
        )
        sql_text = "\n".join(call["sql"] for call in payload["calls"]).lower()
        self.assertNotIn(" match ", sql_text)
        self.assertNotIn("_fts", sql_text)
        self.assertNotIn("bm25", sql_text)
        self.assertLessEqual(
            len(payload["calls"]),
            5,
            "product-mode exact VID should only fetch preview summaries:\n"
            + json.dumps(payload["calls"], indent=2),
        )

    def test_product_mode_hex_vid_prefixes_use_vendor_prefix_only(self) -> None:
        for text in ("3", "30", "303"):
            with self.subTest(text=text):
                payload = _query_shape(self.db, text, mode="product")
                self.assertEqual(payload["counts"]["previews"], 0, payload)
                self.assertGreaterEqual(payload["counts"]["vendors"], 1, payload)
                self.assertEqual(payload["counts"]["products"], 0, payload)
                self.assertEqual(payload["counts"]["boards"], 0, payload)

                sql_text = "\n".join(call["sql"] for call in payload["calls"]).lower()
                self.assertNotIn(" match ", sql_text)
                self.assertNotIn("_fts", sql_text)
                self.assertNotIn("bm25", sql_text)
                self.assertLessEqual(
                    len(payload["calls"]),
                    1,
                    f"Product-mode VID prefix {text!r} should be one indexed "
                    "vendor range query:\n"
                    + json.dumps(payload["calls"], indent=2),
                )
                for hit in payload["data"]["vendors"]:
                    self.assertTrue(hit["row"]["vid"].startswith(text), hit)

    def test_hex_vid_prefixes_use_btree_vendor_prefix_only(self) -> None:
        for text in ("3", "30", "303"):
            with self.subTest(text=text):
                payload = _query_shape(self.db, text)
                self.assertEqual(payload["counts"]["previews"], 0, payload)
                self.assertGreaterEqual(payload["counts"]["vendors"], 1, payload)
                self.assertEqual(payload["counts"]["products"], 0, payload)
                self.assertEqual(payload["counts"]["boards"], 0, payload)

                sql_text = "\n".join(call["sql"] for call in payload["calls"]).lower()
                self.assertNotIn(" match ", sql_text)
                self.assertNotIn("_fts", sql_text)
                self.assertNotIn("bm25", sql_text)
                self.assertLessEqual(
                    len(payload["calls"]),
                    1,
                    f"VID prefix {text!r} should be one indexed range query:\n"
                    + json.dumps(payload["calls"], indent=2),
                )
                for hit in payload["data"]["vendors"]:
                    self.assertTrue(hit["row"]["vid"].startswith(text), hit)

    def test_mixed_vid_and_vendor_text_refines_linked_boards(self) -> None:
        results = _run_batch(self.db, [{"text": "303a Adafruit", "mode": "anything"}])
        r = results[0]
        previews = r["data"].get("previews", [])
        preview = next(
            (p for p in previews if p.get("kind") == "vid" and p.get("vid") == "303a"),
            None,
        )
        self.assertIsNotNone(preview, f"mixed VID query should keep VID context: {r}")

        boards = r["data"]["boards"]
        self.assertGreaterEqual(
            len(boards),
            2,
            f"303a Adafruit should return Adafruit boards linked through VID 303a: {r}",
        )
        board_ids = {b["row"]["board_id"] for b in boards}
        self.assertIn("adafruit_qtpy_esp32c3", board_ids)
        self.assertIn("adafruit_feather_esp32_v2", board_ids)

        off_topic = [
            b["row"]["board_id"]
            for b in boards
            if b.get("why") != "linked via VID + text"
            or "adafruit" not in (
                (b["row"].get("vendor") or "")
                + " "
                + (b["row"].get("name") or "")
                + " "
                + (b["row"].get("board_id") or "")
            ).lower()
        ]
        self.assertFalse(
            off_topic,
            f"mixed VID+text query should only return boards matching both terms: {off_topic}",
        )

    def test_alias_fix_terms_resolve_via_engine_js(self) -> None:
        """The four marquee aliases from the keyword/aliases work
        (PR #4) must hit boards mode via the real JS engine — proving
        the fix isn't just visible to Python's port of ftsQuery."""
        terms = [
            ("GENERIC_F412ZEJX",     "GenF4"),
            ("stm32l476g_disco",     "disco_l476vg"),
            ("ESP8266_WEMOS_D1MINI", "d1_mini"),
            ("Aurora One",           "GenG0"),
        ]
        items = [{"text": t, "mode": "board"} for t, _ in terms]
        results = _run_batch(self.db, items)
        self.assertEqual(len(results), len(terms))
        misses = []
        for (term, want_id), r in zip(terms, results):
            boards = r["data"]["boards"]
            if not boards:
                misses.append((term, "no rows"))
                continue
            ids = [b["row"]["board_id"] for b in boards]
            if want_id not in ids:
                misses.append((term, f"want {want_id!r} not in {ids[:5]}"))
        self.assertFalse(
            misses,
            "JS engine missed at least one alias-fixed term:\n"
            + "\n".join(f"  {t!r}: {why}" for t, why in misses),
        )

    def test_expected_zero_url_terms_return_empty_via_engine_js(self) -> None:
        """URLs intentionally skipped by _collect_keywords must return
        zero boards via the real JS engine too — locks in the contract
        across runtimes."""
        urls = [
            "https://www.stcmicro.com/STC/STC89C52RC.html",
            "https://github.com/RAKWireless/RAK811",
            "http://www.atmel.com/devices/ATTINY45.aspx",
        ]
        items = [{"text": u, "mode": "board"} for u in urls]
        results = _run_batch(self.db, items)
        offenders = []
        for u, r in zip(urls, results):
            if r["data"]["boards"]:
                offenders.append((u, r["data"]["boards"][0]["row"]["board_id"]))
        self.assertFalse(
            offenders,
            f"URLs unexpectedly hit boards via JS engine: {offenders}",
        )

    def test_cli_reports_a_backend(self) -> None:
        """Sanity: each result should report which adapter served it
        (bun:sqlite for local/URL via memory.js, http-range for the
        browser path — never exercised here)."""
        results = _run_batch(self.db, [{"text": "esp32dev", "mode": "board"}])
        self.assertEqual(results[0]["backend"], "bun:sqlite")


if __name__ == "__main__":
    unittest.main()
