"""Auto-generated keyword-disambiguation test cases.

For each row, the long form `<long_name>` MUST return `<expected>` at
position 0 in `board` mode. The `<collisions>` list is the OTHER
boards whose name tokens are a superset of (long_name minus keyword)
— proof that the short form alone wouldn't pick the right variant.

Locks in that adding `ble` / `tiny` / `wifi` / `bluetooth` to a
search actually selects the keyword-variant board, not just any
collision-set neighbour with the same base name.

Regenerate with:
    python tools/gen_keyword_disambig_corpus.py

Cases: 11.

Honors BOARDS_DB env override for local iteration; falls back to the
live published URL otherwise.
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


# (long_name, expected_top_board_ids, keyword_that_disambiguates,
#  collision_set_of_other_board_ids)
# expected_top_board_ids is a list because the same display name can
# back multiple board_ids (PlatformIO + Arduino variants of the same
# physical board) — any of them counts as a correct top hit.
DISAMBIG_CASES: list[tuple[str, list[str], str, list[str]]] = [
    ('Arduino Nano 33 BLE', ['nano33ble'], 'ble', ['nano_33_iot']),
    ('Arduino UNO WiFi', ['unowifi'], 'wifi', ['minima', 'uno', 'uno2018', 'uno_mini', 'uno_r4_minima', 'uno_r4_wifi', 'uno_wifi_rev2', 'unomini', 'unor4wifi']),
    ('Arduino Uno R4 WiFi', ['uno_r4_wifi', 'unor4wifi'], 'wifi', ['minima', 'uno_r4_minima']),
    ('Heltec WiFi Kit 32', ['heltec_wifi_kit_32'], 'wifi', ['heltec_wifi_kit_32_V3', 'heltec_wifi_kit_32_v2']),
    ('Heltec WiFi LoRa 32', ['heltec_wifi_lora_32'], 'wifi', ['heltec_wifi_lora_32_V2', 'heltec_wifi_lora_32_V3', 'heltec_wifi_lora_32_V4']),
    ('WeMos WiFi&Bluetooth Battery', ['WeMosBat'], 'bluetooth', ['wemosbat']),
    ('WeMos WiFi&Bluetooth Battery', ['WeMosBat'], 'wifi', ['wemosbat']),
    ('WiFi Kit 8', ['wifi_kit_8'], 'wifi', ['heltec_wifi_kit_8']),
    ('iLabs Challenger 2040 WiFi', ['challenger_2040_wifi'], 'wifi', ['challenger_2040_lora', 'challenger_2040_lte', 'challenger_2040_nfc', 'challenger_2040_sdrtc', 'challenger_2040_subghz', 'challenger_2040_uwb', 'challenger_2040_wifi6_ble', 'challenger_2040_wifi_ble', 'challenger_nb_2040_wifi']),
    ('iLabs Challenger 2040 WiFi/BLE', ['challenger_2040_wifi_ble'], 'ble', ['challenger_2040_wifi', 'challenger_nb_2040_wifi']),
    ('iLabs Challenger 2040 WiFi/BLE', ['challenger_2040_wifi_ble'], 'wifi', ['challenger_2040_wifi6_ble']),
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
        batch_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, str(QUERY_MJS), "--db", _db_arg(), "--batch", batch_path],
            capture_output=True, text=True, timeout=300, check=True,
        )
    finally:
        os.unlink(batch_path)
    return json.loads(proc.stdout)


@unittest.skipIf(BUN is None, "bun runtime not installed")
class KeywordDisambigTests(unittest.TestCase):
    """The long-form (with keyword) MUST return the keyword-variant
    board at position 0. Otherwise the keyword didn't actually
    disambiguate from collision-set neighbours."""

    def test_corpus_size(self) -> None:
        self.assertEqual(len(DISAMBIG_CASES), 11)

    def test_long_form_returns_keyword_variant_at_top(self) -> None:
        items = [{"text": long_name, "mode": "board"}
                 for long_name, *_ in DISAMBIG_CASES]
        results = _run_batch(items)
        self.assertEqual(len(results), len(DISAMBIG_CASES))

        misses = []
        for (long_name, expected_ids, kw, collisions), r in zip(DISAMBIG_CASES, results):
            boards = r["data"]["boards"]
            if not boards:
                misses.append((long_name, expected_ids, kw, "no rows", collisions[:3]))
                continue
            top_bid = boards[0]["row"]["board_id"]
            if top_bid not in expected_ids:
                misses.append((long_name, expected_ids, kw,
                               f"top was {top_bid!r}", collisions[:3]))
        if misses:
            self.fail(
                f"\n{len(misses)}/{len(DISAMBIG_CASES)} keyword-variant searches "
                f"did NOT top-result the variant board:\n"
                + "\n".join(
                    f"  {n!r} (kw={k!r}) | want top={e!r} | got: {g} "
                    f"| collides w/ {c}"
                    for n, e, k, g, c in misses
                )
            )


if __name__ == "__main__":
    unittest.main()
