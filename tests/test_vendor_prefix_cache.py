"""Lock in the vendor-prefix fast-path cache that turns broad
single-token queries like `arduino` from ~1s of HTTP-paged FTS5 work
into a single PK lookup.

Asserts:
  - the cache table exists and is populated
  - the marquee single-word queries `arduino`, `adafruit`, `sparkfun`,
    `espressif`, `microchip`, `heltec`, `waveshare`, `seeed`, `pimoroni`,
    `raspberry` all hit the cache (single B-tree lookup, JSON-blob
    return)
  - every 1-char, 2-char, and 3-char prefix of every major vendor is
    in the cache (the typing-completion use case)
  - the cache's top hit for each marquee query is a board ACTUALLY
    associated with that vendor (sanity — guards against the cache
    drifting away from real data on future schema changes)
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import unittest
import urllib.request


REPO = pathlib.Path(__file__).resolve().parents[1]
BUN = shutil.which("bun")
LIVE_URL = "https://fastled.github.io/boards/boards.db"
CACHE_PATH = os.path.join(tempfile.gettempdir(), "fastled-boards-boards.db")


def _ssl_ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _resolve_db_path() -> str:
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
        return CACHE_PATH
    req = urllib.request.Request(
        LIVE_URL,
        headers={"Accept-Encoding": "identity",
                 "User-Agent": "vendor-prefix-cache-test/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        with open(CACHE_PATH, "wb") as fh:
            fh.write(resp.read())
    return CACHE_PATH


# (vendor_name, marquee_full_word) — words a user might type expecting
# this vendor's boards. We check both the full word AND the single
# letter prefix to make sure the cache covers the typing-completion
# path end-to-end.
MARQUEE_VENDORS = [
    ("arduino",   "arduino"),
    ("adafruit",  "adafruit"),
    ("sparkfun",  "sparkfun"),
    ("espressif", "espressif"),
    ("microchip", "microchip"),
    ("heltec",    "heltec"),
    ("waveshare", "waveshare"),
    ("seeed",     "seeed"),
    ("pimoroni",  "pimoroni"),
    ("raspberry", "raspberry"),
]


class VendorPrefixCacheTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(_resolve_db_path())

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_table_exists_and_populated(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM vendor_prefix_results"
        ).fetchone()[0]
        self.assertGreater(
            n, 50,
            f"vendor_prefix_results has only {n} rows — expected >50 "
            "(34 major vendors × multi-length prefixes)",
        )

    def test_marquee_full_words_in_cache(self):
        misses = []
        for vendor, word in MARQUEE_VENDORS:
            row = self.conn.execute(
                "SELECT results_json FROM vendor_prefix_results WHERE prefix=?",
                (word,),
            ).fetchone()
            if not row:
                misses.append(word)
        self.assertFalse(
            misses,
            f"{len(misses)} marquee vendor full-word queries not in cache: {misses}",
        )

    def test_short_prefixes_in_cache(self):
        misses = []
        for vendor, _word in MARQUEE_VENDORS:
            for n in (1, 2, 3):
                pre = vendor[:n].lower()
                row = self.conn.execute(
                    "SELECT 1 FROM vendor_prefix_results WHERE prefix=?",
                    (pre,),
                ).fetchone()
                if not row:
                    misses.append(pre)
        misses = sorted(set(misses))
        self.assertFalse(
            misses,
            f"{len(misses)} short prefixes missing from cache: {misses}",
        )

    def test_marquee_full_word_top_hit_is_that_vendor(self):
        misses = []
        for vendor, word in MARQUEE_VENDORS:
            row = self.conn.execute(
                "SELECT results_json FROM vendor_prefix_results WHERE prefix=?",
                (word,),
            ).fetchone()
            if not row:
                continue
            results = json.loads(row[0])
            if not results:
                misses.append((word, "empty results_json"))
                continue
            top = results[0]
            top_vendor_lc = (top.get("vendor") or "").lower()
            top_name_lc   = (top.get("name") or "").lower()
            top_board_id  = (top.get("board_id") or "").lower()
            # Pass if the vendor token appears anywhere in vendor / name /
            # board_id of the top result. Tolerant of vendor canonicals
            # like "Arduino LLC" or "Adafruit Industries".
            if not (vendor in top_vendor_lc
                    or vendor in top_name_lc
                    or vendor in top_board_id):
                misses.append((word, top.get("board_id"), top.get("name"),
                               top.get("vendor")))
        self.assertFalse(
            misses,
            f"{len(misses)} marquee top-hits don't reference their vendor:\n"
            + "\n".join(f"  {m}" for m in misses),
        )


if __name__ == "__main__":
    unittest.main()
