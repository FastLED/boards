"""Smoke tests run directly against the published site.db.

Downloads https://fastled.github.io/boards/site.db once per test process
into a temp-cached path, then asserts properties of the data the portal
relies on. Intentionally minimal — these lock in the user-facing
guarantees (DB size budget, junction linkage) without touching the
front-end build.

Run:
    python -m unittest tests.test_live_db -v
or
    pytest tests/

Stdlib only — no pytest / requests dependency.
"""

from __future__ import annotations

import os
import sqlite3
import ssl
import tempfile
import unittest
import urllib.request


SITE_DB_URL = "https://fastled.github.io/boards/site.db"
SIZE_BUDGET_BYTES = 50 * 1024 * 1024  # 50 MB hard ceiling

# The headline polyfill case: PJRC reuses 16c0:0483 across every Teensy
# variant (Arduino-IDE selects the active mode-PID at compile time, not
# the chip), so the curated rule in other/overrides.json should link this
# single VID:PID to every board whose board_id matches `teensy*`.
TEENSY_SERIAL_VID = "16c0"
TEENSY_SERIAL_PID = "0483"


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _download_db() -> str:
    """Fetch site.db with Accept-Encoding: identity so we get the
    uncompressed bytes (not a gzipped CDN response). Caches into the
    OS temp dir; subsequent tests in the same process reuse it."""
    cached = os.path.join(tempfile.gettempdir(), "fastled-boards-site.db")
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
    """Smoke tests against the published live site.db."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_path = _download_db()

    def test_db_size_under_50mb(self) -> None:
        size = os.path.getsize(self.db_path)
        self.assertGreater(size, 100_000, "site.db is suspiciously small")
        self.assertLess(
            size, SIZE_BUDGET_BYTES,
            f"site.db is {size:,} bytes — over the {SIZE_BUDGET_BYTES:,} byte budget",
        )

    def test_teensy_serial_pid_resolves_to_full_board_records(self) -> None:
        """16c0:0483 (Teensy USB-Serial mode) should resolve through
        board_vidpids to every Teensy variant, and each junction row
        must JOIN back to a complete boards row carrying the rich
        metadata the portal renders (name, mcu, layer, board_id)."""
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT b.board_id, b.name, b.mcu, b.layer, b.sublayer, bv.origin
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
        # UI relies on — board_id, name, layer/sublayer. None should be
        # NULL or empty.
        for board_id, name, mcu, layer, sublayer, origin in rows:
            self.assertTrue(board_id, f"empty board_id on row {(board_id, name)!r}")
            self.assertTrue(name, f"empty name on row {(board_id, name)!r}")
            self.assertTrue(layer, f"empty layer on row {(board_id, name)!r}")
            self.assertTrue(sublayer, f"empty sublayer on row {(board_id, name)!r}")
            self.assertIn(origin, ("upstream", "curated:teensy-usb-modes"),
                          f"unexpected origin {origin!r} on row {(board_id, name)!r}")

        # And every returned board must actually be a Teensy.
        names = [name.lower() for (_, name, *_) in rows]
        non_teensy = [n for n in names if "teensy" not in n]
        self.assertFalse(
            non_teensy,
            f"non-Teensy rows linked to Teensy Serial PID 16c0:0483: {non_teensy!r}",
        )

        # The polyfill semantic must hold: teensy40 has the hwid
        # upstream in its PlatformIO JSON, so its origin should be
        # 'upstream', not the curated rule.
        teensy40 = [origin for (board_id, _, _, _, _, origin) in rows
                    if board_id == "teensy40"]
        self.assertEqual(
            teensy40, ["upstream"],
            "teensy40 should keep its upstream-supplied linkage for 16c0:0483",
        )


if __name__ == "__main__":
    unittest.main()
