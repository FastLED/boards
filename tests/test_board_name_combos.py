"""Auto-generated: 100 randomly-sampled 2-token name
combinations. Mined from per-board display names via jq + tokenizer.

For each combo, the expected-board list is the set of all boards
whose name contains BOTH tokens (case-insensitive substring). The
contract: searching the combo via `board` mode MUST return at least
one expected board in the top 20.

HISTORICAL CONTEXT: this test was originally failing 4 of 100 combos
(Tiny BLE, Nordic nRF52, WiFi Bluetooth, USB OTG) because engine.js
had been degraded from `ORDER BY rank` (FTS5 BM25) to `ORDER BY name`,
allegedly for perf. The alphabetical slice was dropping the most
relevant boards out of the LIMIT-20 window. Restoring BM25 in
site-src/src/search/engine.js fixed every failure. Perf cost was
real but livable then; same expected now. If a future refactor
removes ORDER BY rank, this test exists to catch the regression.

Regenerate with:
    python tools/gen_board_name_combos_corpus.py --n 100 --seed 0

Generation stats:
    boards scanned:        1904
    unique 2-token combos: 2766
    sample size:           100
    seed:                  0

Honors BOARDS_DB env override for local iteration; otherwise hits
the live published URL.
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


# (combo_text, expected_board_ids)
COMBOS: list[tuple[str, list[str]]] = [
    ('1A v2', ['deneyapkart1Av2']),
    ('ARM Enabled', ['max32600mbed']),
    ('Adafruit KB2040', ['adafruit_kb2040']),
    ('Adafruit PyGamer', ['adafruit_pygamer_advance_m4', 'adafruit_pygamer_m4']),
    ('Adafruit RP2350', ['adafruit_feather_rp2350_adalogger', 'adafruit_feather_rp2350_hstx', 'adafruit_fruitjam', 'adafruit_metro_rp2350']),
    ('Azure Development', ['mxchip_az3166']),
    ('B96B F446VE', ['b96b_f446ve']),
    ('Bee Logger', ['Bee_Data_Logger', 'bee_data_logger']),
    ('BlackPill V2', ['blackpill_f401cc', 'blackpill_f411ce']),
    ('Bus Proteus', ['iotbusproteus']),
    ('Challenger BLE', ['challenger_2040_wifi6_ble', 'challenger_2040_wifi_ble', 'challenger_2350_wifi6_ble5']),
    ('Challenger RTC', ['challenger_2040_sdrtc']),
    ('Challenger SubGHz', ['challenger_2040_subghz']),
    ('Circuit Express', ['adafruit_circuitplayground_m0']),
    ('Cloud IoT', ['tb_sense_12']),
    ('Core ESP32', ['AirM2M_CORE_ESP32C3', 'CoreESP32', 'airm2m_core_esp32c3', 'esp32p4_core_board', 'm5stack-core-esp32', 'm5stack-core-esp32-16M', 'microduino-core-esp32', 'weactstudio_esp32c3coreboard']),
    ('Crabik ESP32', ['crabik_slot_esp32_s3']),
    ('DFRobot ESP32', ['dfrobot_beetle_esp32c3', 'dfrobot_beetle_esp32c6', 'dfrobot_firebeetle2_esp32c5', 'dfrobot_firebeetle2_esp32c6', 'dfrobot_firebeetle2_esp32p4', 'dfrobot_firebeetle2_esp32s3', 'dfrobot_lorawan_esp32s3', 'dfrobot_romeo_esp32s3']),
    ('Digilent DP32', ['chipkit_dp32']),
    ('Driver II', ['trueverit-iot-driver-mk2', 'trueverit-iot-driver-mk3']),
    ('ESP WROVER', ['esp-wrover-kit', 'esp32wrover', 'esp32wroverkit', 'freenove_esp32_wrover', 'uPesy_wrover', 'upesy_wrover']),
    ('ESP32 16M', ['4d_systems_esp32s3_gen4_r8n16', 'm5stack-core-esp32-16M']),
    ('ESP32 C3', ['AirM2M_CORE_ESP32C3', 'Geekble_ESP32C3', 'VALTRACK_V4_MFW_ESP32_C3', 'VALTRACK_V4_VTS_ESP32_C3', 'XIAO_ESP32C3', 'adafruit_qtpy_esp32c3', 'airm2m_core_esp32c3', 'dfrobot_beetle_esp32c3', 'esp32-c3-devkitc-02', 'esp32-c3-devkitm-1', 'esp32c3', 'makergo_c3_supermini', 'nologo_esp32c3_super_mini', 'pandabyte_xc3m', 'rymcu-esp32-c3-devkitm-1', 'seeed_xiao_esp32c3', 'sparkfun_pro_micro_esp32c3', 'ttgo-t-oi-plus', 'upesy_esp32c3_basic', 'upesy_esp32c3_mini', 'waveshare_esp32_c3_zero', 'weact_studio_esp32c3', 'weactstudio_esp32c3coreboard']),
    ('ESP32 EDU', ['kits-edu', 'uPesy_edu_esp32']),
    ('ESP32 Kaluga', ['esp32-s2-kaluga-1']),
    ('Ezurio 20dBm', ['lyra24p20']),
    ('FRDM K22F', ['frdm_k22f']),
    ('FYSETC V1', ['fysetc_f6_13']),
    ('Feather Bluefruit', ['adafruit_feather_nrf52832', 'adafruit_feather_nrf52840_sense']),
    ('Flip Click', ['flipnclickmz']),
    ('FoBE Mesh', ['fobe_quill_esp32s3_mesh']),
    ('Giga R1', ['giga', 'giga_r1_m4', 'giga_r1_m7']),
    ('Hallowing M0', ['adafruit_hallowing']),
    ('IoT Node', ['disco_l4s5i_iot01a', 'sparkfun_iotnode_lorawanrp2350', 'turta_iot_node']),
    ('ItsyBitsy 8MHz', ['itsybitsy32u4_3V']),
    ('Jam RP2350', ['adafruit_fruitjam']),
    ('LIVE ESP32MiniKit', ['mhetesp32minikit']),
    ('LaunchPad EXP430G2', ['lpmsp430g2231', 'lpmsp430g2452', 'lpmsp430g2553']),
    ('LaunchPad lm4f120', ['lplm4f120h5qr']),
    ('LaunchPad tm4c123', ['lptm4c123gh6pm']),
    ('MGBOT IOTIK', ['mgbot-iotik32a', 'mgbot-iotik32b']),
    ('MSP EXP430F5529LP', ['lpmsp430f5529']),
    ('MSP EXP430G2553LP', ['lpmsp430g2553']),
    ('MTS Dragonfly', ['mts_dragonfly_f411re']),
    ('Matrix M4', ['adafruit_matrix_portal_m4']),
    ('Maxim Development', ['max32600mbed']),
    ('Metro M0', ['adafruit_metro_m0']),
    ('Midatronics boards', ['Midatronics']),
    ('MikroElektronika Flip', ['flipnclickmz']),
    ('Multi Upgrade', ['prusa_mm_control']),
    ('NIBObee robot', ['nibobee', 'nibobee_1284']),
    ('NXP LPCXpresso54114', ['lpc54114']),
    ('NXP mbed', ['lpc1768']),
    ('Namino Bianco', ['namino_bianco']),
    ('Nucleo H723ZG', ['nucleo_h723zg']),
    ('Nucleo L496ZG', ['nucleo_l496zg', 'nucleo_l496zg_p']),
    ('Pi RP2040', ['adafruit_feather_scorpio', 'cytron_maker_pi_rp2040', 'geeekpi_rp2040_plus', 'olimex_rp2040pico30', 'waveshare_rp2040_pizero']),
    ('Pi Zero', ['raspberrypi_zero', 'waveshare_rp2040_pizero', 'waveshare_rp2350_pizero']),
    ('Prusa Upgrade', ['prusa_mm_control']),
    ('Qualia ESP32', ['adafruit_qualia_s3_rgb666']),
    ('RYMCU DevKitM', ['rymcu-esp32-c3-devkitm-1']),
    ('S2 S2', ['IAP12C5A62S2', 'IAP15F2K61S2', 'IRC15F2K63S2', 'STC12C5A08S2', 'STC12C5A16S2', 'STC12C5A32S2', 'STC12C5A40S2', 'STC12C5A48S2', 'STC12C5A52S2', 'STC12C5A56S2', 'STC12C5A60S2', 'STC15F2K08S2', 'STC15F2K16S2', 'STC15F2K24S2', 'STC15F2K32S2', 'STC15F2K40S2', 'STC15F2K48S2', 'STC15F2K52S2', 'STC15F2K56S2', 'STC15F2K60S2', 'STC8A4K16S2A12', 'STC8A4K32S2A12', 'STC8A4K60S2A12', 'STC8A4K64S2A12', 'STC8C2K16S2', 'STC8C2K32S2', 'STC8C2K60S2', 'STC8C2K64S2', 'STC8F1K08S2', 'STC8F1K08S2A10', 'STC8F1K17S2', 'STC8F2K08S2', 'STC8F2K16S2', 'STC8F2K32S2', 'STC8F2K60S2', 'STC8F2K64S2', 'STC8G2K16S2', 'STC8G2K32S2', 'STC8G2K60S2', 'STC8G2K64S2', 'STC8H1K08S2', 'STC8H1K08S2A10', 'STC8H1K16S2', 'STC8H1K16S2A10', 'STC8H1K32S2', 'STC8H1K32S2A10', 'STC8H1K64S2A10', 'STC8H3K32S2', 'STC8H3K48S2', 'STC8H3K60S2', 'STC8H3K64S2', 'adafruit_feather_esp32s2', 'adafruit_feather_esp32s2_reversetft', 'adafruit_feather_esp32s2_tft', 'adafruit_metro_esp32s2', 'adafruit_qtpy_esp32s2', 'atmegazero_esp32s2', 'department_of_alchemy_minimain_esp32s2', 'esp32-s2-kaluga-1', 'esp32-s2-saola-1', 'esp32s2', 'esp32s2usb', 'featheresp32-s2', 'lolin_s2_mini', 'lolin_s2_pico', 'm5stack_stickc_plus2', 'mb208', 'micros2', 'minimain_esp32s2', 'nodemcu-32s2', 'nucleo_8s207k8', 'nucleo_8s208rb', 'pimoroni_pico_plus_2', 'pimoroni_pico_plus_2w', 'sensebox_mcu_esp32s2', 'sonoff_s20', 'sparkfun_esp32s2_thing_plus', 'um_feathers2', 'um_feathers2_neo', 'um_feathers2neo', 'um_tinys2']),
    ('S3 WROOM', ['freenove_esp32_s3_wroom', 'fri3d_2024_esp32s3']),
    ('SEGGER IP', ['segger_ip_switch']),
    ('SODAQ Autonomo', ['sodaq_autonomo']),
    ('ST STM8S103F3', ['stm8sblue']),
    ('STK3800 Wonder', ['efm32wg_stk3800']),
    ('STM32 E407', ['olimex_e407']),
    ('STM32 Flash', ['genericSTM32F103C4', 'genericSTM32F103C6', 'genericSTM32F103C8', 'genericSTM32F103CB', 'genericSTM32F103R4', 'genericSTM32F103R6', 'genericSTM32F103R8', 'genericSTM32F103RB', 'genericSTM32F103RC', 'genericSTM32F103RD', 'genericSTM32F103RE', 'genericSTM32F103RF', 'genericSTM32F103RG', 'genericSTM32F103T4', 'genericSTM32F103T6', 'genericSTM32F103T8', 'genericSTM32F103TB', 'genericSTM32F103V8', 'genericSTM32F103VB', 'genericSTM32F103VC', 'genericSTM32F103VD', 'genericSTM32F103VE', 'genericSTM32F103VF', 'genericSTM32F103VG', 'genericSTM32F103ZC', 'genericSTM32F103ZD', 'genericSTM32F103ZE', 'genericSTM32F103ZF', 'genericSTM32F103ZG', 'genericSTM32F303CB', 'genericSTM32F373RC', 'genericSTM32F401CB', 'genericSTM32F401CC', 'genericSTM32F401CD', 'genericSTM32F401CE', 'genericSTM32F401RB', 'genericSTM32F401RC', 'genericSTM32F401RD', 'genericSTM32F401RE', 'genericSTM32F405RG', 'genericSTM32F407IGT6', 'genericSTM32F407VET6', 'genericSTM32F407VGT6', 'genericSTM32F410C8', 'genericSTM32F410CB', 'genericSTM32F410R8', 'genericSTM32F410RB', 'genericSTM32F411CC', 'genericSTM32F411CE', 'genericSTM32F411RC', 'genericSTM32F411RE', 'genericSTM32F412CE', 'genericSTM32F412CG', 'genericSTM32F412RE', 'genericSTM32F412RG', 'genericSTM32F413CG', 'genericSTM32F413CH', 'genericSTM32F413RG', 'genericSTM32F413RH', 'genericSTM32F415RG', 'genericSTM32F417VE', 'genericSTM32F417VG', 'genericSTM32F423CH', 'genericSTM32F423RH', 'genericSTM32F446RC', 'genericSTM32F446RE', 'genericSTM32G431CB', 'genericSTM32H750VB', 'microduino32_flash', 'rymcu_f407ve']),
    ('STM32U0 series', ['GenU0']),
    ('STorM32 v1', ['storm32_v1_31_rc']),
    ('Seeed ESP', ['edgebox-esp-100', 'seeed_xiao_esp32c3', 'seeed_xiao_esp32c6', 'seeed_xiao_esp32s3']),
    ('Sigma AGAFIA', ['agafia_sg0']),
    ('Sleepy Pi', ['sleepypi']),
    ('Solder XL', ['solderparty_rp2350_stamp_xl']),
    ('SparkFun Makey', ['sparkfun_makeymakey']),
    ('Studio ESP32S3', ['seeed_xiao_esp32s3']),
    ('T3 STM32', ['lilygo_t3_stm32_v1']),
    ('TI EXP430FR4133LP', ['lpmsp430fr4133']),
    ('TTGO C3', ['ttgo-t-oi-plus']),
    ('TTGO ESP32', ['ttgo-t-oi-plus']),
    ('TTGO RISC', ['ttgo-t-oi-plus']),
    ('Taida Century', ['stct_nrf52_minidev']),
    ('Tech V1', ['btt_ebb42_v1_1', 'usbono_pic32']),
    ('Tiny BLE', ['seeedTinyBLE']),
    ('Turta Node', ['turta_iot_node']),
    ('Unexpected Maker', ['tinypico', 'um_feathers2_neo', 'um_rmp']),
    ('VCC GND', ['vccgnd_f103zet6', 'vccgnd_f407zg_mini', 'vccgnd_yd_rp2040']),
    ('Valetron V4VTS', ['valtrack_v4_vts_esp32_c3']),
    ('WIZnet W5100S', ['wiznet_5100s_evb_pico', 'wiznet_5100s_evb_pico2']),
    ('Waveshare ESP32S3', ['waveshare_esp32_s3_lcd_146', 'waveshare_esp32_s3_lcd_147', 'waveshare_esp32_s3_lcd_169', 'waveshare_esp32_s3_lcd_185', 'waveshare_esp32_s3_relay_6ch', 'waveshare_esp32_s3_touch_amoled_143', 'waveshare_esp32_s3_touch_amoled_164', 'waveshare_esp32_s3_touch_amoled_18', 'waveshare_esp32_s3_touch_amoled_191', 'waveshare_esp32_s3_touch_amoled_206', 'waveshare_esp32_s3_touch_amoled_241', 'waveshare_esp32_s3_touch_lcd_146', 'waveshare_esp32_s3_touch_lcd_169', 'waveshare_esp32_s3_touch_lcd_185', 'waveshare_esp32_s3_touch_lcd_185_box', 'waveshare_esp32_s3_touch_lcd_21', 'waveshare_esp32_s3_touch_lcd_28', 'waveshare_esp32_s3_touch_lcd_4', 'waveshare_esp32_s3_touch_lcd_43', 'waveshare_esp32_s3_touch_lcd_43B', 'waveshare_esp32_s3_touch_lcd_5', 'waveshare_esp32_s3_touch_lcd_5B', 'waveshare_esp32_s3_touch_lcd_7', 'waveshare_esp32_s3_zero', 'waveshare_esp32s3_touch_lcd_128', 'ws_esp32_s3_matrix']),
    ('Waveshare One', ['waveshare_rp2040_one']),
    ('WiFi Rev2', ['uno2018', 'uno_wifi_rev2']),
    ('WiFire rev', ['chipkit_wifire_revc', 'uno2018', 'uno_wifi_rev2']),
    ('Wicked V3', ['wildfirev3']),
    ('WizFi360 EVB', ['wiznet_wizfi360_evb_pico']),
    ('YeaCreate NSCREEN', ['nscreen-32']),
    ('gen4 Range', ['gen4iod']),
    ('of ESP32', ['department_of_alchemy_minimain_esp32s2', 'minimain_esp32s2']),
    ('systems NIBObee', ['nibobee', 'nibobee_1284']),
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
class BoardNameCombosTests(unittest.TestCase):
    """100 random 2-token name combinations must each surface at
    least one of the boards whose name contains both tokens."""

    def test_corpus_size(self) -> None:
        self.assertEqual(len(COMBOS), 100)

    def test_every_combo_finds_an_expected_board(self) -> None:
        items = [{"text": combo, "mode": "board"} for combo, _ in COMBOS]
        results = _run_batch(items)
        self.assertEqual(len(results), len(COMBOS))

        misses = []
        for (combo, expected), r in zip(COMBOS, results):
            got_ids = {b["row"]["board_id"] for b in r["data"]["boards"]}
            expected_set = set(expected)
            if not (got_ids & expected_set):
                misses.append((combo, sorted(expected)[:5], list(got_ids)[:5]))
        if misses:
            self.fail(
                f"\n{len(misses)}/{len(COMBOS)} combos returned no expected board:\n"
                + "\n".join(f"  {c!r} | want one of {e} | got {g}"
                             for c, e, g in misses)
            )


if __name__ == "__main__":
    unittest.main()
