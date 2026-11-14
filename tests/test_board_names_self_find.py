"""Auto-generated: 100 randomly-sampled (board_id, name)
pairs from the per-board JSON corpus. The contract this test locks
in — typing a board's display name into the portal's search MUST
return that board. 100/100 self-find or the build fails.

Regenerate with:
    python tools/gen_board_names_corpus.py --n 100 --seed 0

Mined via jq from site-src/public/boards/. Generation stats:
    total unique boards with names: 1904
    sample size:                    100
    seed:                           0

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


# (board_id, expected_display_name)
BOARD_NAMES: list[tuple[str, str]] = [
    ('1284p8m', 'Microduino Core+ (ATmega1284P@8M,3.3V)'),
    ('ATmega164A', 'ATmega164A'),
    ('ATtiny1604', 'ATtiny1604'),
    ('AVR32DA28', 'AVR32DA28'),
    ('AVR32DA32', 'AVR32DA32'),
    ('Blues', 'Blues boards'),
    ('GenF0', 'Generic STM32F0 series'),
    ('GenWL3', 'Generic STM32WL3 series'),
    ('IAP15F206A', 'Generic IAP15F206A'),
    ('IAP15F413AD', 'Generic IAP15F413AD'),
    ('IAP15W4K63S4', 'Generic IAP15W4K63S4'),
    ('IRC15W107', 'Generic IRC15W107'),
    ('STC12C5A16S2', 'Generic STC12C5A16S2'),
    ('STC12C5A32S2', 'Generic STC12C5A32S2'),
    ('STC12C5A60S2', 'Generic STC12C5A60S2'),
    ('STC15F103', 'Generic STC15F103'),
    ('STC8F2K32S2', 'Generic STC8F2K32S2'),
    ('STC8H1K12', 'Generic STC8H1K12'),
    ('STC8H4K60LCD', 'Generic STC8H4K60LCD'),
    ('STC8H8K48U', 'Generic STC8H8K48U'),
    ('adafruit_feather_dvi', 'Adafruit Feather RP2040 DVI'),
    ('adafruit_feather_m0', 'Adafruit Feather M0'),
    ('adafruit_floppsy', 'Adafruit Floppsy'),
    ('adafruit_matrixportal_esp32s3', 'Adafruit MatrixPortal ESP32-S3'),
    ('adafruit_metro_esp32s3', 'Adafruit Metro ESP32-S3'),
    ('amken_revelop_es', 'Amken Revelop eS'),
    ('attiny84', 'Generic ATtiny84'),
    ('b96b_argonkey', '96Boards Argonkey (STEVAL-MKI187V1)'),
    ('black_f407ve', 'Black STM32F407VE'),
    ('blackpill_f411ce', 'WeAct Studio BlackPill V2.0 (STM32F411CE)'),
    ('bluey', 'Bluey nRF52832 IoT'),
    ('btatmega168', 'Arduino BT ATmega168'),
    ('canipulator_v1', 'CANipulator V1 (ESP32-C6)'),
    ('connectivity_2040_lte_wifi_ble', 'iLabs Connectivity 2040 LTE/WiFi/BLE'),
    ('crabik_slot_esp32_s3', 'Crabik Slot ESP32-S3'),
    ('diecimila', 'Arduino Duemilanove or Diecimila'),
    ('disco_g071rb', 'ST STM32G071B Discovery'),
    ('dsmini', 'DataStation Mini'),
    ('esp-wrover-kit', 'Espressif ESP-WROVER-KIT'),
    ('esp32c3', 'ESP32C3 Dev Module'),
    ('esp32s2usb', 'ESP32S2 Native USB'),
    ('esp32wroverkit', 'ESP32 Wrover Kit (all versions)'),
    ('frdm_kw41z', 'Freescale Kinetis FRDM-KW41Z'),
    ('fysetc_f6_13', 'FYSETC F6 V1.3'),
    ('genericSTM32F103RG', 'STM32F103RG (96k RAM. 1024k Flash)'),
    ('genericSTM32F103ZF', 'STM32F103ZF (96k RAM. 768k Flash)'),
    ('genericSTM32F411RE', 'STM32F411RE (128k RAM. 512k Flash)'),
    ('genericSTM32F446RC', 'STM32F446RC (128k RAM. 256k Flash)'),
    ('heltec_wifi_kit_32', 'Heltec WiFi Kit 32'),
    ('helvepic32_smd_mx270', 'HelvePic32 SMD MX270'),
    ('iotbusproteus', 'oddWires IoT-Bus Proteus'),
    ('kb32-ft', 'MakerAsia KB32-FT'),
    ('leafony_ap03', 'Leafony Systems AP03'),
    ('lilygo_t_display_s3', 'LilyGo T-Display-S3'),
    ('lolin_s3_mini', 'LOLIN S3 Mini'),
    ('m5stack-atoms3', 'M5Stack AtomS3'),
    ('m5stick-c', 'M5Stick-C'),
    ('maxwsnenv', 'Maxim Wireless Sensor Node Demonstrator'),
    ('mb208', 'sduino MB (STM8S208MBT6B)'),
    ('mgbot-iotik32a', 'MGBOT IOTIK 32A'),
    ('mimxrt1064_evk', 'NXP i.MX RT1064 Evaluation Kit'),
    ('mts_mdot_f411re', 'MultiTech mDot F411'),
    ('nrf52840_dk', 'Nordic nRF52840-DK'),
    ('nucleo_f767zi', 'ST Nucleo F767ZI'),
    ('olimex_pico2bb48', 'Olimex Pico2BB48'),
    ('olimex_rp2040pico30', 'Olimex RP2040-Pico30'),
    ('opta_m4', 'Arduino Opta (M4 core)'),
    ('phoenix_v1', 'Phoenix 1.0'),
    ('pintronix_pinmax', 'Pintronix PinMax'),
    ('piranha_esp32', 'Fishino Piranha ESP-32'),
    ('robotControl', 'Arduino Robot Control'),
    ('rpipico2', 'Raspberry Pi Pico 2'),
    ('sleepypi', 'SpellFoundry Sleepy Pi 2'),
    ('sodaq_autonomo', 'SODAQ Autonomo'),
    ('sparkfun_esp32micromod', 'SparkFun ESP32 MicroMod'),
    ('sparkfun_lora_gateway_1-channel', 'SparkFun LoRa Gateway 1-Channel'),
    ('sparkfun_makeymakey', 'SparkFun Makey Makey'),
    ('sparkfun_megapro8MHz', 'SparkFun Mega Pro 3.3V/8MHz'),
    ('sparkfun_redboard_turbo', 'SparkFun RedBoard Turbo'),
    ('swervolf_nexys', 'RVfpga: Digilent Nexys A7'),
    ('teensy31', 'Teensy 3.1 / 3.2'),
    ('teensy41', 'Teensy 4.1'),
    ('ttgo-lora32-v1', 'TTGO LoRa32-OLED V1'),
    ('tuinozero96', 'Tuino 096'),
    ('ublox_c030_u201', 'u-blox C030-U201 IoT Starter Kit'),
    ('unphone7', 'unPhone 7'),
    ('upesy_esp32c3_mini', 'uPesy ESP32C3 Mini'),
    ('usbono_pic32', 'PONTECH UAV100'),
    ('vccgnd_yd_rp2040', 'VCC-GND YD RP2040'),
    ('waveshare_esp32_s3_touch_lcd_5B', 'Waveshare ESP32-S3-Touch-LCD-5B'),
    ('waveshare_esp32s3_touch_lcd_128', 'Waveshare ESP32S3 Touch LCD 128'),
    ('waveshare_rp2350_zero', 'Waveshare RP2350 Zero'),
    ('weact_studio_esp32c3', 'WeAct Studio ESP32C3'),
    ('wifiduino32c3', 'WiFiduinoV2'),
    ('wildfirev3', 'Wicked Device WildFire V3'),
    ('wiznet_5100s_evb_pico', 'WIZnet W5100S-EVB-Pico'),
    ('wiznet_6300_evb_pico2', 'WIZnet W6300-EVB-Pico2'),
    ('wizwiki_w7500eco', 'WIZwiki-W7500ECO'),
    ('wraith32_v1', 'Wraith V1 ESC'),
    ('ws_esp32_s3_matrix', 'Waveshare ESP32-S3-Matrix'),
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
class BoardNamesSelfFindTests(unittest.TestCase):
    """100 random boards must each be findable by their display name
    via the portal's `board` mode (FTS5 boards_fts MATCH, LIMIT 20)."""

    def test_corpus_size(self) -> None:
        self.assertEqual(len(BOARD_NAMES), 100)

    def test_every_board_name_self_finds(self) -> None:
        items = [{"text": name, "mode": "board"} for _, name in BOARD_NAMES]
        results = _run_batch(items)
        self.assertEqual(len(results), len(BOARD_NAMES))

        misses = []
        for (want_bid, name), r in zip(BOARD_NAMES, results):
            ids = [b["row"]["board_id"] for b in r["data"]["boards"]]
            if want_bid not in ids:
                misses.append((name, want_bid, ids[:5]))
        if misses:
            self.fail(
                f"\n{len(misses)}/{len(BOARD_NAMES)} board names failed to self-find:\n"
                + "\n".join(f"  {n!r} → want {w!r}, got top: {g}"
                             for n, w, g in misses)
            )


if __name__ == "__main__":
    unittest.main()
