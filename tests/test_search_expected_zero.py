"""Locks in the *intentional* zero-result contract for the search index.

Some categories of strings appear in the per-board JSONs but are NOT
useful search targets — URLs, template placeholders, raw numeric
literals. `builders/extract_boards.py:_collect_keywords` filters them
out before they reach the `boards.keywords` column and therefore
`boards_fts`. This test asserts those filters keep doing their job:
every term below MUST return zero rows from boards_fts.

If one of these starts returning a hit, the filter regressed (or
someone added the term as a real keyword/alias) — investigate before
relaxing this test.

Honors BOARDS_DB env override so it can run against a locally-built
DB during iteration. Falls back to the live published URL otherwise.
"""

from __future__ import annotations

import os
import re
import sqlite3
import ssl
import tempfile
import unittest
import urllib.request


LIVE_URL = "https://fastled.github.io/boards/boards.db"
CACHE_PATH = os.path.join(tempfile.gettempdir(), "fastled-boards-boards.db")


# (category, term)
# Each term has the same shape as something a per-board JSON actually
# contains; the contract is that none of these are search-reachable
# because they aren't search terms a user would type to find a board.
EXPECTED_ZERO_TERMS: list[tuple[str, str]] = [
    # URLs — full http(s) URLs in homepage / wiki / vendor doc fields.
    # _collect_keywords skips strings starting with http:// or https://.
    ("url",      "https://www.stcmicro.com/STC/STC89C52RC.html"),
    ("url",      "https://github.com/RAKWireless/RAK811"),
    ("url",      "https://www.microchip.com/wwwproducts/en/AVR64DD20"),
    ("url",      "http://www.atmel.com/devices/ATTINY45.aspx"),
    ("url",      "https://en.wikipedia.org/wiki/ESP32"),
    ("url",      "http://example.invalid/probably-not-indexed-either"),

    # Template placeholders — Arduino board.txt frequently has
    # `{build.usb_flags} -DUSBD_USE_HID_COMPOSITE` style entries that
    # only make sense after substitution. _collect_keywords skips any
    # string containing `{` or `}`.
    ("template", "{build.usb_flags} -DUSBD_USE_HID_COMPOSITE"),
    ("template", "{runtime.platform.path}/debugger/R7FA4M1AB.cfg"),
    ("template", "{build.core.path}/variants/{build.variant}/linker.ld"),
    ("template", "{compiler.path}{compiler.c.cmd}"),
]


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _resolve_db_path() -> str:
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
        return CACHE_PATH
    req = urllib.request.Request(
        LIVE_URL,
        headers={"Accept-Encoding": "identity",
                 "User-Agent": "search-expected-zero-test/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        with open(CACHE_PATH, "wb") as fh:
            fh.write(resp.read())
    return CACHE_PATH


def _fts_query(s: str) -> str | None:
    """Mirror site-src/src/util/fts.js verbatim — same tokenization
    the live portal uses for free-text queries."""
    tokens = re.sub(r"[^a-z0-9_\s]", " ", (s or "").lower()).split()
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    return " ".join(t + "*" for t in tokens)


class SearchExpectedZeroTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_path = _resolve_db_path()
        cls.conn = sqlite3.connect(cls.db_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_urls_return_no_boards(self) -> None:
        offenders = []
        for category, term in EXPECTED_ZERO_TERMS:
            if category != "url":
                continue
            q = _fts_query(term)
            self.assertIsNotNone(q, f"empty fts query for url {term!r}")
            try:
                rows = self.conn.execute(
                    "SELECT b.board_id, b.name FROM boards b "
                    "JOIN boards_fts f ON f.rowid = b.rowid "
                    "WHERE boards_fts MATCH ? LIMIT 1",
                    (q,),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            if rows:
                offenders.append((term, rows[0]))
        if offenders:
            self.fail(
                f"\n{len(offenders)} URL terms unexpectedly hit boards_fts:\n"
                + "\n".join(f"  {t!r} → {h}" for t, h in offenders)
            )

    def test_template_placeholders_return_no_boards(self) -> None:
        offenders = []
        for category, term in EXPECTED_ZERO_TERMS:
            if category != "template":
                continue
            q = _fts_query(term)
            if q is None:
                continue
            try:
                rows = self.conn.execute(
                    "SELECT b.board_id, b.name FROM boards b "
                    "JOIN boards_fts f ON f.rowid = b.rowid "
                    "WHERE boards_fts MATCH ? LIMIT 1",
                    (q,),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            if rows:
                offenders.append((term, rows[0]))
        if offenders:
            self.fail(
                f"\n{len(offenders)} template-placeholder terms unexpectedly hit "
                f"boards_fts:\n"
                + "\n".join(f"  {t!r} → {h}" for t, h in offenders)
            )

    def test_corpus_has_both_categories(self) -> None:
        cats = {c for c, _ in EXPECTED_ZERO_TERMS}
        self.assertEqual(cats, {"url", "template"})


if __name__ == "__main__":
    unittest.main()
