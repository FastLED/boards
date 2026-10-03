"""Adversarial search-quality regression test.

Mined from three parallel sub-agents probing different attack angles:
  - field:    leak/collision through JSON fields (extra_flags, variant,
              alias columns, menu.pnum subtree, ampersand/punctuation
              names)
  - query:    user-typed pathologies (FTS5 reserved chars, stop-word-
              only queries, compile-error pastes, boolean-op intent)
  - collision: inter-board name collisions, substring families, numeric-
              suffix siblings, cross-vendor name reuse

Each case has:
  query: the user's typed string
  expected_top: board_id at position 0, or None for "zero hits expected"
  acceptable_tops: alternative board_ids that count as a #1 hit
                   (for genuinely ambiguous cases — e.g. PlatformIO +
                   Arduino duplicates of the same board)
  must_appear: board_ids that must appear somewhere in top 20

Reports top-1 hit rate and zero-hit accuracy. The floor is set
generously since this is exploratory — adversarial cases that fail
are evidence of where ranking still needs work.
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


# Combined output from 3 adversarial sub-agents (see commit message).
# Format: dict with query + expected behaviour.
ADVERSARIAL_CASES: list[dict] = [
    # ─── FIELD-CONTENT ATTACK SURFACE (agent A) ────────────────────────
    {"src":"field", "query":"WiFi Bluetooth Battery", "expected_top":"WeMosBat", "acceptable_tops":["WeMosBat","wemosbat"], "must_appear":[], "why":"ampersand drop + connectivity-column noise"},
    {"src":"field", "query":"ARDUINO_Pocket32", "expected_top":"pocket_32", "acceptable_tops":["pocket_32"], "must_appear":[], "why":"build.extra_flags macro leak across boards"},
    {"src":"field", "query":"Teensy++ 2.0", "expected_top":"teensy2pp", "acceptable_tops":["teensy2pp"], "must_appear":[], "why":"++ stripped, query collapses to 'teensy' + numerics"},
    {"src":"field", "query":"DISCO_F407VG", "expected_top":"disco_f407vg", "acceptable_tops":["disco_f407vg","Disco"], "must_appear":[], "why":"STM32duino umbrella vs PlatformIO leaf"},
    {"src":"field", "query":"STM32F4DISCOVERY", "expected_top":"disco_f407vg", "acceptable_tops":["disco_f407vg","Disco"], "must_appear":[], "why":"alias collision with siblings"},
    {"src":"field", "query":"NUCLEO_H743ZI", "expected_top":"nucleo_h743zi", "acceptable_tops":["nucleo_h743zi","Nucleo_144"], "must_appear":[], "why":"umbrella vs leaf"},
    {"src":"field", "query":"ARDUINO_NRF52840_FEATHER", "expected_top":"adafruit_feather_nrf52840", "acceptable_tops":["adafruit_feather_nrf52840"], "must_appear":[], "why":"extra_flag macro leaks into Metro nRF52840's keyword soup"},
    {"src":"field", "query":"ARDUINO_HELTEC_WIFI_KIT_32", "expected_top":"heltec_wifi_kit_32", "acceptable_tops":["heltec_wifi_kit_32","heltec_wifi_kit_32_v2"], "must_appear":[], "why":"v1 and v2 share the same macro"},
    {"src":"field", "query":"ARDUINO_AVR_NANO", "expected_top":"nanoatmega328", "acceptable_tops":["nanoatmega328","nanoatmega328new","nano"], "must_appear":[], "why":"shared between old/new bootloader Nano variants"},
    {"src":"field", "query":"d1_mini", "expected_top":"d1_mini", "acceptable_tops":["d1_mini"], "must_appear":[], "why":"build.variant=d1_mini shared across pro/lite"},
    {"src":"field", "query":"nRF52DK", "expected_top":"nrf52_dk", "acceptable_tops":["nrf52_dk","nrf52840_dk"], "must_appear":[], "why":"build.variant collision between 832 and 840 boards"},
    {"src":"field", "query":"RED-V", "expected_top":"sparkfun_redboard_v", "acceptable_tops":["sparkfun_redboard_v"], "must_appear":[], "why":"hyphen drop + single-letter v ambiguity"},
    {"src":"field", "query":"ARDUINO_NANO33BLE", "expected_top":"nano33ble", "acceptable_tops":["nano33ble"], "must_appear":[], "why":"underscore-preserving macro paste"},
    {"src":"field", "query":"ESP8266_WEMOS_D1MINI", "expected_top":"d1_mini", "acceptable_tops":["d1_mini"], "must_appear":[], "why":"shared macro substring with d1_mini_pro"},

    # ─── QUERY-CONSTRUCTION PATHOLOGIES (agent B) ──────────────────────
    {"src":"query", "query":"esp32-dev", "expected_top":"esp32dev", "acceptable_tops":["esp32dev"], "must_appear":[], "why":"hyphen splits — esp32-devkitlipo may win"},
    {"src":"query", "query":"esp32 OR teensy", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"FTS5 is AND-only; OR token forces every match to literally contain 'or'"},
    {"src":"query", "query":"feather NOT m0", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"NOT is a literal token requirement"},
    {"src":"query", "query":"info default verbose", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"all-stopwords query — ftsQuery returns null"},
    {"src":"query", "query":"off on all none", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"stopwords-only"},
    {"src":"query", "query":"   ", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"whitespace only"},
    {"src":"query", "query":"!!@#$%^&*()", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"punctuation only — stripped to nothing"},
    {"src":"query", "query":"\"esp32\"", "expected_top":"esp32dev", "acceptable_tops":["esp32dev"], "must_appear":[], "why":"quoted phrase — quotes stripped, becomes esp32* prefix"},
    {"src":"query", "query":"esp32*", "expected_top":"esp32dev", "acceptable_tops":["esp32dev"], "must_appear":[], "why":"user-supplied wildcard silently dropped"},
    {"src":"query", "query":"at tiny 85", "expected_top":"attiny85", "acceptable_tops":["attiny85"], "must_appear":[], "why":"spaced spelling — no bridge between 'at' 'tiny'"},
    {"src":"query", "query":"ATtiny 85", "expected_top":"attiny85", "acceptable_tops":["attiny85"], "must_appear":[], "why":"case OK after lowercasing but space-split"},
    {"src":"query", "query":"iPhone", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"off-corpus — zero hits is correct"},
    {"src":"query", "query":"error: 'ARDUINO_NANO33BLE' not declared in this scope", "expected_top":"nano33ble", "acceptable_tops":["nano33ble"], "must_appear":[], "why":"compile-error paste — 'declared' is rare token, will force AND across non-existent words"},
    {"src":"query", "query":"303a:1001", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"VID:PID in board mode — colon split tokens; board mode shouldn't find anything"},
    {"src":"query", "query":"C++", "expected_top":None, "acceptable_tops":[], "must_appear":[], "why":"single 'c' after strip — likely null/0"},
    {"src":"query", "query":"uno", "expected_top":"uno", "acceptable_tops":["uno"], "must_appear":[], "why":"3-char common; ranking under variant/alias noise"},
    {"src":"query", "query":"ESP32-S3-DevKitC-1", "expected_top":"esp32-s3-devkitc-1", "acceptable_tops":["esp32-s3-devkitc-1"], "must_appear":[], "why":"hyphens split into multiple AND tokens incl bare '1'"},

    # ─── COLLISION FAMILIES (agent C) ─────────────────────────────────
    {"src":"collision", "query":"Adafruit Feather M0", "expected_top":"adafruit_feather_m0", "acceptable_tops":["adafruit_feather_m0"], "must_appear":[], "why":"M0 Express superset competition"},
    {"src":"collision", "query":"Adafruit Metro M4", "expected_top":"adafruit_metro_m4", "acceptable_tops":["adafruit_metro_m4"], "must_appear":[], "why":"AirLift Lite superset"},
    {"src":"collision", "query":"Adafruit Feather ESP32-S2", "expected_top":"adafruit_feather_esp32s2", "acceptable_tops":["adafruit_feather_esp32s2","featheresp32-s2"], "must_appear":[], "why":"multiple TFT/reverseTFT variants"},
    {"src":"collision", "query":"Adafruit Feather ESP32-S3", "expected_top":"adafruit_feather_esp32s3", "acceptable_tops":["adafruit_feather_esp32s3"], "must_appear":[], "why":"4 ESP32-S3 Feather variants"},
    {"src":"collision", "query":"ATtiny85", "expected_top":"attiny85", "acceptable_tops":["attiny85"], "must_appear":[], "why":"numeric siblings 84/45/88/841"},
    {"src":"collision", "query":"ATtiny84", "expected_top":"attiny84", "acceptable_tops":["attiny84"], "must_appear":[], "why":"attiny841 numeric extension"},
    {"src":"collision", "query":"ATmega328", "expected_top":"ATmega328", "acceptable_tops":["ATmega328","ATmega328P","ATmega328PB","nanoatmega328"], "must_appear":[], "why":"P/PB variants + Nano derivatives"},
    {"src":"collision", "query":"Arduino Nano", "expected_top":"nano", "acceptable_tops":["nano","nanoatmega328"], "must_appear":[], "why":"classic AVR Nano vs 33 IoT/BLE/RP2040 heirs"},
    {"src":"collision", "query":"Arduino Uno", "expected_top":"uno", "acceptable_tops":["uno"], "must_appear":[], "why":"Mini/WiFi variants"},
    {"src":"collision", "query":"Raspberry Pi Pico", "expected_top":"rpipico", "acceptable_tops":["rpipico","pico"], "must_appear":[], "why":"triple-defined across mbed/earlephilhower/platformio"},
    {"src":"collision", "query":"Raspberry Pi Pico W", "expected_top":"rpipicow", "acceptable_tops":["rpipicow","picow"], "must_appear":[], "why":"Pico 2W numeric superset"},
    {"src":"collision", "query":"Teensy 4", "expected_top":"teensy40", "acceptable_tops":["teensy40","teensy41"], "must_appear":[], "why":"4.0 vs 4.1 disambiguation by trailing digit"},
    {"src":"collision", "query":"Teensy 2", "expected_top":"teensy2", "acceptable_tops":["teensy2"], "must_appear":[], "why":"Teensy++ 2.0 competition"},
    {"src":"collision", "query":"Nucleo F411RE", "expected_top":"nucleo_f411re", "acceptable_tops":["nucleo_f411re"], "must_appear":[], "why":"F4xx siblings"},
    {"src":"collision", "query":"ESP32 DevKit", "expected_top":"esp32doit-devkit-v1", "acceptable_tops":["esp32doit-devkit-v1"], "must_appear":[], "why":"S2/S3/C3 DevKits all share tokens"},
    {"src":"collision", "query":"D1 Mini", "expected_top":"d1_mini", "acceptable_tops":["d1_mini"], "must_appear":[], "why":"Lite/Pro supersets"},
    {"src":"collision", "query":"NodeMCU", "expected_top":"nodemcuv2", "acceptable_tops":["nodemcuv2","nodemcu","nodemcu-32s"], "must_appear":[], "why":"ESP8266 NodeMCU vs ESP32 NodeMCU-32S"},
    {"src":"collision", "query":"XIAO ESP32S3", "expected_top":"seeed_xiao_esp32s3", "acceptable_tops":["seeed_xiao_esp32s3","XIAO_ESP32S3"], "must_appear":[], "why":"vendor name placement"},
    {"src":"collision", "query":"Adafruit ItsyBitsy M4", "expected_top":"adafruit_itsybitsy_m4", "acceptable_tops":["adafruit_itsybitsy_m4"], "must_appear":[], "why":"M0/M4 numeric suffix"},
    {"src":"collision", "query":"Adafruit Trinket M0", "expected_top":"adafruit_trinket_m0", "acceptable_tops":["adafruit_trinket_m0"], "must_appear":[], "why":"5 *Trinkey M0 boards competing"},
]


def _db_arg() -> str:
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    return LIVE_URL


def _run_batch(items: list[dict]) -> list[dict]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(items, fh)
        path = fh.name
    try:
        proc = subprocess.run(
            [BUN, str(QUERY_MJS), "--db", _db_arg(), "--batch", path],
            capture_output=True, text=True, timeout=600, check=True,
        )
    finally:
        os.unlink(path)
    return json.loads(proc.stdout)


@unittest.skipIf(BUN is None, "bun runtime not installed")
class AdversarialSearchTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        items = [{"text": c["query"], "mode": "board"} for c in ADVERSARIAL_CASES]
        cls.results = _run_batch(items)
        cls.metrics = cls._compute(ADVERSARIAL_CASES, cls.results)
        cls._print_report(ADVERSARIAL_CASES, cls.results, cls.metrics)

    @staticmethod
    def _compute(cases, results):
        top1 = 0
        zero_ok = 0
        zero_attempts = 0
        positive_attempts = 0
        misses_pos = []
        misses_zero = []
        by_src = {}
        for c, r in zip(cases, results):
            src = c["src"]
            b = by_src.setdefault(src, {"top1":0, "n":0, "zero_ok":0, "zero_n":0})
            boards = r["data"]["boards"]
            if c["expected_top"] is None:
                # expect EMPTY result
                b["zero_n"] += 1
                zero_attempts += 1
                if not boards:
                    b["zero_ok"] += 1
                    zero_ok += 1
                else:
                    misses_zero.append((c["query"], [x["row"]["board_id"] for x in boards[:3]]))
            else:
                b["n"] += 1
                positive_attempts += 1
                ok_set = set(c["acceptable_tops"]) | {c["expected_top"]}
                if boards and boards[0]["row"]["board_id"] in ok_set:
                    b["top1"] += 1
                    top1 += 1
                else:
                    misses_pos.append((c["query"], c["expected_top"],
                                       [x["row"]["board_id"] for x in boards[:3]]))
        return {
            "top1": top1, "positive_attempts": positive_attempts,
            "zero_ok": zero_ok, "zero_attempts": zero_attempts,
            "by_src": by_src, "misses_pos": misses_pos, "misses_zero": misses_zero,
        }

    @staticmethod
    def _print_report(cases, results, m):
        print(file=sys.stderr)
        print("┌─ adversarial search report ─────────────────────────────", file=sys.stderr)
        print(f"│ total cases: {len(cases)}", file=sys.stderr)
        print(f"│ positive (expect a board): {m['positive_attempts']}", file=sys.stderr)
        print(f"│   top-1 hits:  {m['top1']}/{m['positive_attempts']} "
              f"({100*m['top1']/max(m['positive_attempts'],1):.1f}%)", file=sys.stderr)
        print(f"│ zero-hit (expect empty):   {m['zero_attempts']}", file=sys.stderr)
        print(f"│   stayed empty: {m['zero_ok']}/{m['zero_attempts']} "
              f"({100*m['zero_ok']/max(m['zero_attempts'],1):.1f}%)", file=sys.stderr)
        print("│ per-source breakdown:", file=sys.stderr)
        for src, b in sorted(m["by_src"].items()):
            print(f"│   {src:>10}: top-1 {b['top1']}/{b['n']} "
                  f"zero-ok {b['zero_ok']}/{b['zero_n']}", file=sys.stderr)
        print(file=sys.stderr)
        if m["misses_pos"]:
            print("┌─ POSITIVE MISSES (wanted a specific board) ─────────────", file=sys.stderr)
            for q, want, got in m["misses_pos"]:
                print(f"│   {q!r}", file=sys.stderr)
                print(f"│      want top: {want!r}", file=sys.stderr)
                print(f"│      got top:  {got}", file=sys.stderr)
            print(file=sys.stderr)
        if m["misses_zero"]:
            print("┌─ ZERO-HIT MISSES (wanted empty, got results) ───────────", file=sys.stderr)
            for q, got in m["misses_zero"]:
                print(f"│   {q!r} → top: {got}", file=sys.stderr)
            print(file=sys.stderr)

    def test_corpus_size(self) -> None:
        self.assertEqual(len(ADVERSARIAL_CASES), 51)

    def test_top_1_floor(self) -> None:
        m = self.metrics
        # Floor is the BASELINE observed in the report — moves up as we fix
        # ranking issues, never down. Adversarial test, by definition the
        # floor is below 100% — that's where the ranking work hides.
        FLOOR = 50.0
        rate = 100 * m["top1"] / max(m["positive_attempts"], 1)
        self.assertGreaterEqual(
            rate, FLOOR,
            f"adversarial top-1 = {rate:.1f}% < {FLOOR}% floor",
        )

    def test_zero_hit_accuracy(self) -> None:
        m = self.metrics
        FLOOR = 50.0
        rate = 100 * m["zero_ok"] / max(m["zero_attempts"], 1)
        self.assertGreaterEqual(
            rate, FLOOR,
            f"adversarial zero-hit accuracy = {rate:.1f}% < {FLOOR}% floor",
        )


if __name__ == "__main__":
    unittest.main()
