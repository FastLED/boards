"""Locks down search behavior for the 61 terms that returned zero in
the original random-sample run (tests/test_search_corpus_results.py).

Each term is classified as:
  - expected_hit = True  → after adding boards.aliases + boards.keywords
    in extract_boards.py + build_sqlite.py, the term MUST resolve to
    at least one board via the same FTS5 path the live portal uses.
  - expected_hit = False → URLs and template placeholders. The portal
    intentionally does not index these because they aren't search
    terms users type.

Run against a locally rebuilt DB while iterating:

    python tools/rebuild_boards_local.py
    BOARDS_DB=%TEMP%\\fastled-boards-local.db python -m unittest tests.test_search_zero_terms -v

When BOARDS_DB is unset the test falls back to the live published
boards.db — useful as a post-deploy smoke check, but it will fail
until extractor + schema changes are deployed.

Query path mirrors the live portal's site-src/src/util/fts.js:
lowercase → strip non-alnum/underscore → split on whitespace →
append `*` to each token → join with space (FTS5 default AND).
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


# (term, expected_hit, reason)
# True  → must resolve to ≥1 board via boards_fts after data fixes land
# False → intentionally not indexed; portal exposes a 0-result answer
ZERO_TERMS: list[tuple[str, bool, str]] = [
    # STM32duino menu.pnum.<KEY> variants — now reachable via boards.aliases
    ("GENERIC_G041G8UX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_L031E6YX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_F412ZEJX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_G061C6TX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_F215VETX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_F101ZCTX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_L431RBYX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_L083CZUX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_F205RGEX",                                    True,  "STM32duino pnum alias"),
    ("GENERIC_L412K8UX",                                    True,  "STM32duino pnum alias"),
    ("NOD_U575ZI",                                          True,  "STM32duino Nucleo node alias"),
    # STM32duino "Generic <X>" human-readable variant labels
    ("Generic F031G6Ux",                                    True,  "STM32duino menu label"),
    ("Generic F429ZETx",                                    True,  "STM32duino menu label"),
    ("Generic H723VGTx",                                    True,  "STM32duino menu label"),
    ("Generic F101C6Tx",                                    True,  "STM32duino menu label"),
    ("Generic F756ZGTx",                                    True,  "STM32duino menu label"),
    ("Generic F378VCTx",                                    True,  "STM32duino menu label"),
    ("Generic F205RFTx",                                    True,  "STM32duino menu label"),
    ("Generic F746ZEYx",                                    True,  "STM32duino menu label"),
    ("Generic F103CBTx",                                    True,  "STM32duino menu label"),
    ("Nucleo U385RG-Q",                                     True,  "STM32duino Nucleo menu label"),
    ("Aurora One",                                          True,  "STM32duino menu label"),
    # PlatformIO Zephyr / OpenOCD aliases
    ("stm32l476g_disco",                                    True,  "Zephyr variant alias"),
    ("st_nucleo_f4",                                        True,  "OpenOCD board alias"),
    # ESP8266 build.board macro
    ("ESP8266_WEMOS_D1MINI",                                True,  "ESP8266 build.board macro"),
    # MCU family / product line — caught by keyword soup
    ("STM32WB0x",                                           True,  "STM32duino build.series in keywords"),
    ("STM32F205xx",                                         True,  "product_line in keywords"),
    ("STM32F0xx/F051K4T",                                   True,  "MCU family label in keywords"),
    ("STM32G0xx/G031F(4-6-8)P_G031Y8Y_G041F(6-8)P_G041Y8Y", True,  "MCU family label in keywords"),
    # Compile flags — keyword soup makes the macro substrings findable
    ("-DARDUINO_FEATHER_M4",                                True,  "compile flag in keywords"),
    ("-DSTM32L4 -DSTM32L452xx",                             True,  "compile flag in keywords"),
    ("-DSTM32H7 -DSTM32H7xx -DSTM32H745xx",                 True,  "compile flag in keywords"),
    ("-DSTM32F4 -DSTM32F446xx",                             True,  "compile flag in keywords"),
    ("-DSTM32F407xx -DARDUINO_STM32GenericF407VET6 -DSTM32F4", True, "compile flag in keywords"),
    ("-DESP8266 -DARDUINO_ARCH_ESP8266 -DARDUINO_ESP8266_SONOFF_S20", True, "compile flag in keywords"),
    ("-DESP8266 -DARDUINO_ARCH_ESP8266 -DARDUINO_ESP8266_XINABOX_CW01", True, "compile flag in keywords"),
    ("-DSTC15W4KXXS4 -DSTC15W4K16S4 -DNAKED_ARCH_MCS51 -DNAKED_MCS51_STC15W4KXXS4", True, "compile flag in keywords"),
    ("-DUSBD_PID=0x102d",                                   True,  "usbpid in keywords"),
    ("-DUSBD_PID=0x4253",                                   True,  "usbpid in keywords"),
    ("-DRP2350_PSRAM_CS=35",                                True,  "psramcs build flag in keywords"),
    ("-DZIGBEE_MODE_ED",                                    True,  "ZigbeeMode build flag in keywords"),
    # Config / debug filenames
    ("STM32F439x.svd",                                      True,  "debug.svd_path in keywords"),
    ("esp32c61-ftdi.cfg",                                   True,  "JTAG openocdscript in keywords"),
    ("esp32s2-kaluga-1.cfg",                                True,  "JTAG openocdscript in keywords"),
    # Arduino menu sub-labels
    ("India",                                               True,  "WiFi country menu entry in keywords"),
    ("GPIO 39",                                             True,  "psramcs pin menu in keywords"),
    ("GPIO 10",                                             True,  "psramcs pin menu in keywords"),
    ("Default with spiffs",                                 True,  "PartitionScheme label in keywords"),
    ("default_ffat_8MB",                                    True,  "partition scheme name in keywords"),
    ("32KB cache + 32KB IRAM (balanced)",                   True,  "mmu menu label in keywords"),
    ("32MB (Sketch: 13MB, FS: 19MB)",                       True,  "flash partition label in keywords"),
    ("128MB (Sketch: 27MB, FS: 101MB)",                     True,  "flash partition label in keywords"),
    ("NoAssert-NDEBUG",                                     True,  "build level label in keywords"),
    ("TLS_MEM+HTTP_SERVER",                                 True,  "build level label in keywords"),
    # Numeric-looking literal that slipped past the numeric filter
    # (CPU frequency literal "80000000L" — the trailing L disqualifies
    # it from int/float parsing, so it lands in keywords too)
    ("80000000L",                                           True,  "f_cpu literal in keywords"),
    # ────────────────────────────────────────────────────────────────
    # SHOULD NOT HIT — by design
    # ────────────────────────────────────────────────────────────────
    ("https://www.stcmicro.com/STC/STC89C52RC.html",        False, "URL — keyword filter skips http(s) URLs"),
    ("https://github.com/RAKWireless/RAK811",               False, "URL — keyword filter skips http(s) URLs"),
    ("https://www.microchip.com/wwwproducts/en/AVR64DD20",  False, "URL — keyword filter skips http(s) URLs"),
    ("http://www.atmel.com/devices/ATTINY45.aspx",          False, "URL — keyword filter skips http(s) URLs"),
    ("{build.usb_flags} -DUSBD_USE_HID_COMPOSITE",          False, "template placeholder — keyword filter skips strings containing { or }"),
    ("{runtime.platform.path}/debugger/R7FA4M1AB.cfg",      False, "template placeholder — keyword filter skips strings containing { or }"),
]


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _resolve_db_path() -> str:
    """Honor BOARDS_DB env override (local-rebuild loop). Fall back to
    downloading the live published DB into a temp-cached path."""
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
        return CACHE_PATH
    req = urllib.request.Request(
        LIVE_URL,
        headers={"Accept-Encoding": "identity",
                 "User-Agent": "search-zero-terms-test/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as resp:
        with open(CACHE_PATH, "wb") as fh:
            fh.write(resp.read())
    return CACHE_PATH


_STOP_WORDS = frozenset({
    "info", "warn", "error", "verbose",
    "default", "disable", "disabled", "enable", "enabled",
    "none", "on", "off", "all", "custom",
    "minimal", "small", "fast",
    "boot", "mode", "port", "os", "sdk", "ld", "fp",
})


def _fts_query(s: str) -> str | None:
    """Mirror the live portal's ftsQuery() from site-src/src/util/fts.js
    — same -D strip, same stop-word filter, same prefix-AND output."""
    s = re.sub(r"-D(?=[A-Z_])", "", s or "")
    tokens = re.sub(r"[^a-z0-9_\s]", " ", s.lower()).split()
    tokens = [t for t in tokens if t and t not in _STOP_WORDS]
    if not tokens:
        return None
    return " ".join(t + "*" for t in tokens)


class SearchZeroTermsTests(unittest.TestCase):
    """For each of the 61 terms that returned zero in the random-sample
    recon run, assert the post-fix behavior matches its classification.
    expected_hit=True terms MUST return ≥1 board; expected_hit=False
    terms MUST return 0."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_path = _resolve_db_path()
        cls.conn = sqlite3.connect(cls.db_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_expected_hit_terms_resolve(self) -> None:
        misses = []
        for term, expected_hit, reason in ZERO_TERMS:
            if not expected_hit:
                continue
            q = _fts_query(term)
            self.assertIsNotNone(q, f"empty fts query for {term!r}")
            try:
                rows = self.conn.execute(
                    "SELECT b.board_id, b.name FROM boards b "
                    "JOIN boards_fts f ON f.rowid = b.rowid "
                    "WHERE boards_fts MATCH ? LIMIT 1",
                    (q,),
                ).fetchall()
            except sqlite3.OperationalError as e:
                misses.append((term, reason, f"FTS5 error: {e}"))
                continue
            if not rows:
                misses.append((term, reason, "0 rows"))
        if misses:
            self.fail(
                f"\n{len(misses)} expected-hit terms returned zero:\n"
                + "\n".join(f"  {t!r:>60} ({r}) → {x}" for t, r, x in misses)
            )

    def test_expected_zero_terms_stay_zero(self) -> None:
        unexpected_hits = []
        for term, expected_hit, reason in ZERO_TERMS:
            if expected_hit:
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
                unexpected_hits.append((term, reason, rows[0]))
        if unexpected_hits:
            self.fail(
                f"\n{len(unexpected_hits)} expected-zero terms unexpectedly hit:\n"
                + "\n".join(f"  {t!r:>60} ({r}) → {h}" for t, r, h in unexpected_hits)
            )

    def test_classification_covers_all_61_zeros(self) -> None:
        self.assertEqual(
            len(ZERO_TERMS), 61,
            f"expected 61 zero-terms classified, got {len(ZERO_TERMS)}",
        )


if __name__ == "__main__":
    unittest.main()
