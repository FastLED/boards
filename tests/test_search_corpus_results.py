"""Recon test: run every SEARCH_TERMS entry through the live boards.db
FTS5 indices (boards_fts, vidpid_fts, vid_vendor_fts) and dump
`{term: result}` to a JSON artifact for inspection.

Co-located with `test_search_corpus.py` (which holds the auto-generated
corpus) but kept separate so the generator can overwrite the corpus
file without trampling this analysis code.

This is *exploratory*, not a hard assertion suite — it makes one
soft check (every term produced a result entry) and writes the rest
to a JSON file we read back to think about coverage. Output path is
printed to stdout at the end of the run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import ssl
import sys
import tempfile
import unittest
import urllib.request

# Import SEARCH_TERMS from the auto-generated sibling. Both files live
# under tests/, so importing as a sibling needs the package to resolve;
# unittest auto-discovery puts tests/ on sys.path via the implicit
# __init__-less namespace package, so a direct module import works.
try:
    from tests.test_search_corpus import SEARCH_TERMS  # type: ignore
except ImportError:
    # Fallback when running this file directly without `python -m unittest`.
    sys.path.insert(0, os.path.dirname(__file__))
    from test_search_corpus import SEARCH_TERMS  # type: ignore


LIVE_URL = "https://fastled.github.io/boards/boards.db"
CACHE_PATH = os.path.join(tempfile.gettempdir(), "fastled-boards-boards.db")
RESULTS_PATH = os.path.join(
    tempfile.gettempdir(), "fastled-boards-search-corpus-results.json"
)


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _download_db() -> str:
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
        return CACHE_PATH
    req = urllib.request.Request(
        LIVE_URL,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "search-corpus-test/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        with open(CACHE_PATH, "wb") as fh:
            fh.write(resp.read())
    return CACHE_PATH


def _phrase(term: str) -> str:
    """FTS5 phrase-quote: wrap in `"…"` so punctuation / spaces are
    treated as literal phrase content, not query syntax. Internal `"`
    is escaped by doubling per FTS5 spec."""
    return '"' + term.replace('"', '""') + '"'


def _fts_search(conn: sqlite3.Connection, sql: str, phrase: str) -> list:
    """Run an FTS5 query and tolerate operational errors (e.g. the
    tokenizer reduces the phrase to nothing → "no tokens" error).
    Surface the error string in the result so the JSON dump captures
    what happened instead of silently dropping the row."""
    try:
        return [list(r) for r in conn.execute(sql, (phrase,)).fetchall()]
    except sqlite3.OperationalError as e:
        return [{"_error": str(e)}]


class SearchCorpusResultsTests(unittest.TestCase):
    """Walk SEARCH_TERMS, query the three FTS5 indices for each one,
    dump everything to a JSON for human analysis."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_path = _download_db()
        cls.conn = sqlite3.connect(cls.db_path)
        cls.results: dict[str, dict] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.conn.close()
        finally:
            with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
                json.dump(cls.results, fh, indent=2, ensure_ascii=False)
            print(f"\nWrote {len(cls.results)} term-results → {RESULTS_PATH}",
                  file=sys.stderr)

    def test_search_each_term(self) -> None:
        BOARD_SQL = (
            "SELECT b.board_id, b.name, b.vendor, b.mcu, b.layer, b.sublayer "
            "FROM boards b JOIN boards_fts f ON f.rowid = b.rowid "
            "WHERE boards_fts MATCH ? LIMIT 5"
        )
        VIDPID_SQL = (
            "SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary "
            "FROM vidpid vp JOIN vidpid_fts f ON f.rowid = vp.rowid "
            "WHERE vidpid_fts MATCH ? LIMIT 5"
        )
        VENDOR_SQL = (
            "SELECT vv.vid, vv.vendor, vv.source "
            "FROM vid_vendor vv JOIN vid_vendor_fts f ON f.rowid = vv.rowid "
            "WHERE vid_vendor_fts MATCH ? LIMIT 5"
        )

        for term in SEARCH_TERMS:
            phrase = _phrase(term)
            boards   = _fts_search(self.conn, BOARD_SQL,  phrase)
            products = _fts_search(self.conn, VIDPID_SQL, phrase)
            vendors  = _fts_search(self.conn, VENDOR_SQL, phrase)

            # An entry counts as "errored" if any of the three FTS calls
            # returned a sentinel {"_error": ...}.
            errored = any(
                rows and isinstance(rows[0], dict) and "_error" in rows[0]
                for rows in (boards, products, vendors)
            )

            self.__class__.results[term] = {
                "fts_phrase": phrase,
                "boards":     boards,
                "products":   products,
                "vendors":    vendors,
                "counts": {
                    "boards":   0 if errored else len(boards),
                    "products": 0 if errored and isinstance(products[0], dict) else len(products),
                    "vendors":  0 if errored and isinstance(vendors[0], dict) else len(vendors),
                },
                "errored": errored,
            }

        self.assertEqual(len(self.__class__.results), len(SEARCH_TERMS))


if __name__ == "__main__":
    unittest.main()
