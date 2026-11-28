"""Smoke tests run directly against the published boards.db.

Downloads https://fastled.github.io/boards/boards.db once per test
process into a temp-cached path, then asserts properties of the data
the portal relies on. Intentionally minimal — these lock in the
user-facing guarantees (DB size budget, junction linkage, URL
traceability) without touching the front-end build.

Run:
    python -m unittest tests.test_live_db -v
or
    pytest tests/

Stdlib only — no pytest / requests dependency.
"""

from __future__ import annotations

import os
import re
import sqlite3
import ssl
import tempfile
import unittest
import urllib.request


SITE_DB_URL = "https://fastled.github.io/boards/boards.db"
SIZE_BUDGET_BYTES = 8 * 1024 * 1024  # 8 MB hard ceiling
# Bumped from 5 MB → 8 MB when the vendor_prefix_results JSON-blob
# cache landed (PR #20). The cache adds ~1.5 MB of denormalized
# top-20 results for ~220 vendor prefixes so single-word vendor
# searches like `arduino` collapse from >1s of HTTP-paged FTS5 work
# to a single PK lookup. Speed is the explicit trade for size.

# The headline polyfill case: PJRC reuses 16c0:0483 across every Teensy
# variant (Arduino-IDE selects the active mode-PID at compile time, not
# the chip), so the curated rule in other/overrides.json should link this
# single VID:PID to every board whose board_id matches `teensy*`.
TEENSY_SERIAL_VID = "16c0"
TEENSY_SERIAL_PID = "0483"

# Used to verify the `homepage` column actually carries a URL, not just
# any non-empty string.
_HTTP_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _download_db() -> str:
    """Fetch boards.db with Accept-Encoding: identity so we get the
    uncompressed bytes (not a gzipped CDN response). Caches into the
    OS temp dir; subsequent tests in the same process reuse it."""
    cached = os.path.join(tempfile.gettempdir(), "fastled-boards-boards.db")
    if os.path.exists(cached) and os.path.getsize(cached) > 0:
        return cached
    req = urllib.request.Request(
        SITE_DB_URL,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "fastled-boards-tests/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        with open(cached, "wb") as fh:
            fh.write(resp.read())
    return cached


class LiveDbTests(unittest.TestCase):
    """Smoke tests against the published live boards.db."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_path = _download_db()

    def test_db_size_under_budget(self) -> None:
        size = os.path.getsize(self.db_path)
        self.assertGreater(size, 100_000, "boards.db is suspiciously small")
        self.assertLess(
            size, SIZE_BUDGET_BYTES,
            f"boards.db is {size:,} bytes — over the {SIZE_BUDGET_BYTES:,} byte budget",
        )

    def test_teensy_serial_pid_traces_back_to_board_urls(self) -> None:
        """16c0:0483 (Teensy USB-Serial mode) should resolve through
        board_vidpids to every Teensy variant, and each row must carry
        a URL that takes the user back to that board — both the
        product `homepage` (e.g. https://www.pjrc.com/store/teensy40.html)
        and the `upstream_blob` (the GitHub source the entry was
        merged from). These URLs are what the portal renders next to
        each board, so a regression in either field breaks the
        "VID:PID → board page" trace path."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT b.board_id, b.name, b.mcu, b.layer, b.sublayer,
                       b.homepage, b.upstream_blob, bv.origin
                FROM board_vidpids bv
                JOIN boards b ON b.rowid = bv.board_rowid
                WHERE bv.vid = ? AND bv.pid = ?
                ORDER BY b.board_id
                """,
                (TEENSY_SERIAL_VID, TEENSY_SERIAL_PID),
            ).fetchall()
        finally:
            conn.close()

        # Headline assertion: the curated rule must polyfill linkage to
        # every Teensy variant the boards table has. At least 9 are
        # expected (the 10-board Teensy lineup the curated rule covers,
        # minus 1 if any variant gets dropped upstream).
        self.assertGreaterEqual(
            len(rows), 9,
            f"expected ≥9 Teensy boards linked to 16c0:0483, got {len(rows)}: {rows!r}",
        )

        # Every joined row must carry the structured-board fields the
        # UI relies on — board_id, name, layer/sublayer, AND a URL the
        # user can click to trace the VID:PID back to its board page.
        for board_id, name, mcu, layer, sublayer, homepage, upstream_blob, origin in rows:
            self.assertTrue(board_id, f"empty board_id on row {(board_id, name)!r}")
            self.assertTrue(name, f"empty name on row {(board_id, name)!r}")
            self.assertTrue(layer, f"empty layer on row {(board_id, name)!r}")
            self.assertTrue(sublayer, f"empty sublayer on row {(board_id, name)!r}")
            self.assertIn(origin, ("upstream", "curated:teensy-usb-modes"),
                          f"unexpected origin {origin!r} on row {(board_id, name)!r}")

            # URL traceability — primary path is `homepage`, fallback is
            # `upstream_blob` (the GitHub JSON source). At least one of
            # the two MUST be a http(s) URL for every Teensy row.
            url_candidates = [u for u in (homepage, upstream_blob) if u]
            self.assertTrue(
                url_candidates,
                f"no URL field on Teensy row {board_id!r} — homepage and upstream_blob both empty",
            )
            self.assertTrue(
                any(_HTTP_URL_RE.match(u) for u in url_candidates),
                f"Teensy row {board_id!r} has no http(s) URL — homepage={homepage!r}, "
                f"upstream_blob={upstream_blob!r}",
            )

        # And every returned board must actually be a Teensy.
        names = [name.lower() for (_, name, *_) in rows]
        non_teensy = [n for n in names if "teensy" not in n]
        self.assertFalse(
            non_teensy,
            f"non-Teensy rows linked to Teensy Serial PID 16c0:0483: {non_teensy!r}",
        )

        # Spot-check: teensy40 should keep upstream origin (PJRC supplies
        # 16c0:0483 in its PlatformIO JSON, so the curated rule must not
        # overwrite it), and its homepage should point at pjrc.com.
        by_id = {row[0]: row for row in rows}
        self.assertIn("teensy40", by_id, "teensy40 missing from Teensy lookup")
        t40 = by_id["teensy40"]
        self.assertEqual(t40[7], "upstream",
                         "teensy40 should keep its upstream-supplied linkage for 16c0:0483")
        t40_homepage = t40[5] or ""
        self.assertIn(
            "pjrc.com", t40_homepage.lower(),
            f"teensy40 homepage doesn't trace back to PJRC: {t40_homepage!r}",
        )


if __name__ == "__main__":
    unittest.main()
