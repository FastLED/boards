"""Auto-generated similar-names self-find corpus.

Each entry is (board_id, name, similar_peer_ids) where the peers'
names share ≥ 50% of their tokens with `name`. This is the
contention zone where ranking quality matters — multiple boards
plausibly match a query, but the queried board's exact display name
must still come back at position 0 (or tie via a duplicate
board_id under another upstream).

Regenerate with:
    python tools/gen_similar_names_corpus.py --threshold 0.5 --n 200 --seed 0

Sample: 200.

METRIC
  top_1_pct: of the 200 cases, fraction where rank-1 result
             has the SAME display name (case-insensitive) as the
             query. Captures both exact self-find and PlatformIO/
             Arduino duplicates (same physical board).
  mrr:       mean reciprocal rank — average of 1/rank where rank is
             the 1-based position of the first same-name hit. 0 if
             not in top 20.

The test asserts a floor on top_1_pct so a future change that
degrades ranking fails CI. Tune the floor when weights change.
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


# (board_id, name, similar_peer_board_ids)
SIMILAR_NAME_CASES: list[tuple[str, str, list[str]]] = [
    ('1284p8m', 'Microduino Core+ (ATmega1284P@8M,3.3V)', ['168pa8m', '328p8m', '644pa8m']),
    ('Bee_Motion_S3', 'Bee Motion S3', ['Bee_Motion', 'Bee_Motion_Mini', 'Bee_S3', 'bee_motion', 'bee_motion_s3', 'bee_s3']),
    ('GenC0', 'Generic STM32C0 series', ['GenF0', 'GenF1', 'GenF2', 'GenF3', 'GenF4', 'GenF7', 'GenG0', 'GenG4', 'GenH5', 'GenH7', 'GenL0', 'GenL1', 'GenL4', 'GenL5', 'GenU0', 'GenU3', 'GenU5', 'GenWB', 'GenWB0', 'GenWBA', 'GenWL', 'GenWL3']),
    ('GenF7', 'Generic STM32F7 series', ['GenC0', 'GenF0', 'GenF1', 'GenF2', 'GenF3', 'GenF4', 'GenG0', 'GenG4', 'GenH5', 'GenH7', 'GenL0', 'GenL1', 'GenL4', 'GenL5', 'GenU0', 'GenU3', 'GenU5', 'GenWB', 'GenWB0', 'GenWBA', 'GenWL', 'GenWL3']),
    ('GenG0', 'Generic STM32G0 series', ['GenC0', 'GenF0', 'GenF1', 'GenF2', 'GenF3', 'GenF4', 'GenF7', 'GenG4', 'GenH5', 'GenH7', 'GenL0', 'GenL1', 'GenL4', 'GenL5', 'GenU0', 'GenU3', 'GenU5', 'GenWB', 'GenWB0', 'GenWBA', 'GenWL', 'GenWL3']),
    ('GenL0', 'Generic STM32L0 series', ['GenC0', 'GenF0', 'GenF1', 'GenF2', 'GenF3', 'GenF4', 'GenF7', 'GenG0', 'GenG4', 'GenH5', 'GenH7', 'GenL1', 'GenL4', 'GenL5', 'GenU0', 'GenU3', 'GenU5', 'GenWB', 'GenWB0', 'GenWBA', 'GenWL', 'GenWL3']),
    ('GenU5', 'Generic STM32U5 series', ['GenC0', 'GenF0', 'GenF1', 'GenF2', 'GenF3', 'GenF4', 'GenF7', 'GenG0', 'GenG4', 'GenH5', 'GenH7', 'GenL0', 'GenL1', 'GenL4', 'GenL5', 'GenU0', 'GenU3', 'GenWB', 'GenWB0', 'GenWBA', 'GenWL', 'GenWL3']),
    ('GenWL', 'Generic STM32WL series', ['GenC0', 'GenF0', 'GenF1', 'GenF2', 'GenF3', 'GenF4', 'GenF7', 'GenG0', 'GenG4', 'GenH5', 'GenH7', 'GenL0', 'GenL1', 'GenL4', 'GenL5', 'GenU0', 'GenU3', 'GenU5', 'GenWB', 'GenWB0', 'GenWBA', 'GenWL3']),
    ('LilyPadUSB', 'LilyPad Arduino USB', ['lilypad', 'lilypadatmega168', 'lilypadatmega328']),
    ('Pcbcupid_GLYPH_C3', 'Pcbcupid GLYPH C3', ['Pcbcupid_GLYPH_C6', 'Pcbcupid_GLYPH_H2', 'Pcbcupid_GLYPH_S3', 'pcbcupid_glyph_2040', 'pcbcupid_glyph_c5']),
    ('S_ODI_Ultra', 'S.ODI Ultra v1', ['s_odi_ultra']),
    ('adafruit_feather_esp32_v2', 'Adafruit Feather ESP32 V2', ['adafruit_feather_esp32c6', 'adafruit_feather_esp32s2', 'adafruit_feather_esp32s2_tft', 'adafruit_feather_esp32s3_tft', 'featheresp32']),
    ('adafruit_feather_esp32c6', 'Adafruit Feather ESP32-C6', ['adafruit_feather_esp32_v2', 'adafruit_feather_esp32s2', 'adafruit_feather_esp32s2_tft', 'adafruit_feather_esp32s3_tft', 'featheresp32']),
    ('adafruit_feather_esp32s2', 'Adafruit Feather ESP32-S2', ['adafruit_feather_esp32_v2', 'adafruit_feather_esp32c6', 'adafruit_feather_esp32s2_reversetft', 'adafruit_feather_esp32s2_tft', 'adafruit_feather_esp32s3_tft', 'adafruit_metro_esp32s2', 'adafruit_qtpy_esp32s2', 'featheresp32', 'featheresp32-s2']),
    ('adafruit_feather_esp32s3_tft', 'Adafruit Feather ESP32-S3 TFT', ['adafruit_feather_esp32_v2', 'adafruit_feather_esp32c6', 'adafruit_feather_esp32s2', 'adafruit_feather_esp32s2_reversetft', 'adafruit_feather_esp32s2_tft', 'adafruit_feather_esp32s3', 'adafruit_feather_esp32s3_nopsram', 'adafruit_feather_esp32s3_reversetft', 'adafruit_matrixportal_esp32s3', 'adafruit_metro_esp32s3', 'featheresp32']),
    ('adafruit_feather_m4_can', 'Adafruit Feather M4 CAN', ['adafruit_feather_can', 'adafruit_feather_m4']),
    ('adafruit_feather_rp2350_hstx', 'Adafruit Feather RP2350 HSTX', ['adafruit_feather_rp2350_adalogger']),
    ('adafruit_feather_thinkink', 'Adafruit Feather RP2040 ThinkINK', ['adafruit_feather', 'adafruit_feather_adalogger', 'adafruit_feather_can', 'adafruit_feather_dvi', 'adafruit_feather_prop_maker', 'adafruit_feather_rfm', 'adafruit_feather_scorpio', 'adafruit_feather_usb_host']),
    ('adafruit_itsybitsy_m0', 'Adafruit ItsyBitsy M0', ['adafruit_crickit_m0', 'adafruit_feather_m0', 'adafruit_gemma_m0', 'adafruit_hallowing', 'adafruit_itsybitsy', 'adafruit_itsybitsy_esp32', 'adafruit_itsybitsy_m4', 'adafruit_trinket_m0']),
    ('adafruit_itsybitsy_nrf52840', 'ItsyBitsy nRF52840 Express', ['adafruit_metro_nrf52840', 'itsybitsy52840']),
    ('adafruit_macropad2040', 'Adafruit MacroPad RP2040', ['adafruit_feather', 'adafruit_itsybitsy', 'adafruit_metro']),
    ('adafruit_metro', 'Adafruit Metro RP2040', ['adafruit_feather', 'adafruit_itsybitsy', 'adafruit_macropad2040', 'adafruit_metro_m4', 'adafruit_metro_rp2350', 'metro']),
    ('adafruit_metro_m4', 'Adafruit Metro M4', ['adafruit_hallowing_m4', 'adafruit_itsybitsy_m4', 'adafruit_metro', 'adafruit_metro_m4_airliftlite', 'adafruit_metro_rp2350', 'adafruit_pyportal_m4', 'adafruit_trellis_m4', 'metro']),
    ('adafruit_metro_nrf52840', 'Metro nRF52840 Express', ['adafruit_itsybitsy_nrf52840', 'metro52840']),
    ('adafruit_pygamer_m4', 'Adafruit PyGamer M4 Express', ['adafruit_feather_m4', 'adafruit_pybadge_m4', 'adafruit_pygamer_advance_m4']),
    ('adafruit_qtpy_esp32c3', 'Adafruit QT Py ESP32-C3', ['adafruit_qt_py_m0', 'adafruit_qtpy', 'adafruit_qtpy_esp32', 'adafruit_qtpy_esp32_pico', 'adafruit_qtpy_esp32s2', 'adafruit_qtpy_esp32s3_nopsram']),
    ('adafruit_qtpy_esp32s2', 'Adafruit QT Py ESP32-S2', ['adafruit_feather_esp32s2', 'adafruit_metro_esp32s2', 'adafruit_qt_py_m0', 'adafruit_qtpy', 'adafruit_qtpy_esp32', 'adafruit_qtpy_esp32_pico', 'adafruit_qtpy_esp32c3', 'adafruit_qtpy_esp32s3_nopsram']),
    ('adafruit_qualia_s3_rgb666', 'Adafruit Qualia ESP32-S3 RGB666', ['adafruit_matrixportal_esp32s3', 'adafruit_metro_esp32s3']),
    ('adafruit_trinket_m0', 'Adafruit Trinket M0', ['adafruit_crickit_m0', 'adafruit_feather_m0', 'adafruit_gemma_m0', 'adafruit_hallowing', 'adafruit_itsybitsy_m0']),
    ('adafruit_trinkeyrp2040qt', 'Adafruit Trinkey RP2040 QT', ['adafruit_qtpy']),
    ('arduino_nano_connect', 'Arduino Nano RP2040 Connect', ['nano', 'nanorp2040connect']),
    ('artix7_35t', 'Artix-7 35T Arty FPGA Evaluation Kit', ['coreplexip-e31-arty', 'coreplexip-e51-arty', 'parashu', 'pinaka']),
    ('atmegang', 'Arduino NG or older', ['atmegangatmega168', 'atmegangatmega8']),
    ('atmegangatmega8', 'Arduino NG or older ATmega8', ['atmegang', 'atmegangatmega168']),
    ('b96b_aerocore2', '96Boards Neonkey', ['b96b_neonkey']),
    ('b96b_neonkey', '96Boards Neonkey', ['b96b_aerocore2']),
    ('bee_data_logger', 'Smart Bee Data Logger', ['Bee_Data_Logger']),
    ('btatmega168', 'Arduino BT ATmega168', ['bt', 'btatmega328', 'lilypadatmega168', 'miniatmega168', 'nanoatmega168']),
    ('challenger_2040_uwb', 'iLabs Challenger 2040 UWB', ['challenger_2040_lora', 'challenger_2040_lte', 'challenger_2040_nfc', 'challenger_2040_sdrtc', 'challenger_2040_subghz', 'challenger_2040_wifi', 'challenger_2040_wifi6_ble', 'challenger_2040_wifi_ble', 'challenger_nb_2040_wifi']),
    ('challenger_2040_wifi', 'iLabs Challenger 2040 WiFi', ['challenger_2040_lora', 'challenger_2040_lte', 'challenger_2040_nfc', 'challenger_2040_sdrtc', 'challenger_2040_subghz', 'challenger_2040_uwb', 'challenger_2040_wifi6_ble', 'challenger_2040_wifi_ble', 'challenger_2350_wifi6_ble5', 'challenger_nb_2040_wifi']),
    ('challenger_2040_wifi_ble', 'iLabs Challenger 2040 WiFi/BLE', ['challenger_2040_lora', 'challenger_2040_lte', 'challenger_2040_nfc', 'challenger_2040_subghz', 'challenger_2040_uwb', 'challenger_2040_wifi', 'challenger_2040_wifi6_ble', 'challenger_2350_wifi6_ble5', 'challenger_nb_2040_wifi', 'connectivity_2040_lte_wifi_ble']),
    ('challenger_2350_nbiot', 'iLabs Challenger 2350 NB-IoT', ['challenger_2350_bconnect']),
    ('challenger_2350_wifi6_ble5', 'iLabs Challenger 2350 WiFi/BLE', ['challenger_2040_wifi', 'challenger_2040_wifi_ble', 'challenger_2350_bconnect']),
    ('challenger_nb_2040_wifi', 'iLabs Challenger NB 2040 WiFi', ['challenger_2040_lora', 'challenger_2040_lte', 'challenger_2040_nfc', 'challenger_2040_subghz', 'challenger_2040_uwb', 'challenger_2040_wifi', 'challenger_2040_wifi_ble']),
    ('chipkit_pro_mx4', 'Digilent chipKIT Pro MX4', ['chipkit_pro_mx7']),
    ('cloud_jam_l4', 'RushUp Cloud-JAM L4', ['cloud_jam']),
    ('cluenrf52840', 'Adafruit CLUE', ['adafruit_clue_nrf52840']),
    ('coreplexip-e31-arty', 'Freedom E310 Arty (Artix-7) FPGA Dev Kit', ['artix7_35t', 'coreplexip-e51-arty', 'e310-arty']),
    ('curiosity_nano_db', 'Curiosity Nano AVR128DB48', ['curiosity_nano_4809', 'curiosity_nano_da']),
    ('cytron_maker_nano_rp2040', 'Cytron Maker Nano RP2040', ['cytron_maker_pi_rp2040', 'cytron_maker_uno_rp2040']),
    ('cytron_maker_pi_rp2040', 'Cytron Maker Pi RP2040', ['cytron_maker_nano_rp2040', 'cytron_maker_uno_rp2040']),
    ('cytron_maker_uno_rp2040', 'Cytron Maker Uno RP2040', ['cytron_maker_nano_rp2040', 'cytron_maker_pi_rp2040']),
    ('d1_mini', 'LOLIN(WEMOS) D1 R2 & mini', ['d1', 'd1_mini32', 'd1_mini_clone', 'd1_mini_lite', 'd1_mini_pro', 'wemos_d1_mini32']),
    ('deneyapkartv2', 'Deneyap Kart v2', ['deneyapkart', 'deneyapkart1A', 'deneyapkart1Av2', 'deneyapkartg', 'deneyapminiv2']),
    ('department_of_alchemy_minimain_esp32s2', 'Department of Alchemy MiniMain ESP32-S2', ['minimain_esp32s2']),
    ('dfrobot_firebeetle2_esp32c5', 'DFRobot Firebeetle 2 ESP32-C5', ['dfrobot_firebeetle2_esp32c6', 'dfrobot_firebeetle2_esp32e', 'dfrobot_firebeetle2_esp32p4', 'dfrobot_firebeetle2_esp32s3']),
    ('dfrobot_firebeetle2_esp32c6', 'DFRobot FireBeetle 2 ESP32-C6', ['dfrobot_beetle_esp32c6', 'dfrobot_firebeetle2_esp32c5', 'dfrobot_firebeetle2_esp32e', 'dfrobot_firebeetle2_esp32p4', 'dfrobot_firebeetle2_esp32s3']),
    ('dfrobot_firebeetle2_esp32e', 'FireBeetle 2 ESP32-E', ['dfrobot_firebeetle2_esp32c5', 'dfrobot_firebeetle2_esp32c6', 'dfrobot_firebeetle2_esp32p4', 'dfrobot_firebeetle2_esp32s3', 'firebeetle32']),
    ('diecimilaatmega328', 'Arduino Duemilanove or Diecimila ATmega328', ['diecimila', 'diecimilaatmega168']),
    ('electrosmith_daisy', 'Electrosmith Daisy', ['electrosmith_daisy_patch_sm', 'electrosmith_daisy_petal_sm']),
    ('electrosmith_daisy_patch_sm', 'Electrosmith Daisy Patch SM', ['electrosmith_daisy', 'electrosmith_daisy_petal_sm']),
    ('esp07s', 'Espressif Generic ESP8266 ESP-07S', ['esp01', 'esp01_1m', 'esp07', 'esp12e']),
    ('esp32-c3-m1i-kit', 'Ai-Thinker ESP-C3-M1-I-Kit', ['esp32c3m1IKit']),
    ('esp32-c6-devkitc-1', 'Espressif ESP32-C6-DevKitC-1', ['esp32-c6-devkitm-1']),
    ('esp32-pro', 'OLIMEX ESP32-PRO', ['esp32-evb', 'esp32-gateway', 'esp32-poe']),
    ('esp32c2', 'ESP32C2 Dev Module', ['esp32', 'esp32c3', 'esp32c5', 'esp32c6', 'esp32c61', 'esp32h2', 'esp32p4', 'esp32s2', 'esp32s3']),
    ('esp32c5', 'ESP32C5 Dev Module', ['esp32', 'esp32c2', 'esp32c3', 'esp32c6', 'esp32c61', 'esp32h2', 'esp32p4', 'esp32s2', 'esp32s3']),
    ('esp32c6', 'ESP32C6 Dev Module', ['cezerio_dev_esp32c6', 'esp32', 'esp32c2', 'esp32c3', 'esp32c5', 'esp32c61', 'esp32h2', 'esp32p4', 'esp32s2', 'esp32s3']),
    ('esp32s3', 'ESP32S3 Dev Module', ['esp32', 'esp32c2', 'esp32c3', 'esp32c5', 'esp32c6', 'esp32c61', 'esp32h2', 'esp32p4', 'esp32s2']),
    ('esp32s3box', 'ESP32-S3-Box', ['esp32s3_powerfeather', 'redpill_esp32s3']),
    ('espresso_lite_v1', 'ESPresso Lite 1.0', ['espresso_lite_v2']),
    ('feather32u4', 'Adafruit Feather 32u4', ['adafruit_feather', 'adafruit_feather_f405', 'adafruit_feather_m0', 'feather328p', 'feather52832', 'featheresp32']),
    ('feather52832', 'Adafruit Feather nRF52832', ['adafruit_feather', 'adafruit_feather_f405', 'adafruit_feather_m0', 'adafruit_feather_nrf52832', 'feather328p', 'feather32u4', 'featheresp32']),
    ('feather_nrf52840_sense_tft', 'Adafruit Feather nRF52840 Sense TFT', ['adafruit_feather_nrf52840', 'adafruit_feather_nrf52840_sense', 'feather52840', 'feather52840sense']),
    ('franzininho_wifi_esp32s2', 'Franzininho WiFi', ['esp32-s2-franzininho', 'franzininho_wifi_msc_esp32s2']),
    ('franzininho_wifi_msc_esp32s2', 'Franzininho WiFi MSC', ['esp32-s2-franzininho', 'franzininho_wifi_esp32s2']),
    ('frdm_kl25z', 'Freescale Kinetis FRDM-KL25Z', ['frdm_k22f', 'frdm_k64f', 'frdm_k66f', 'frdm_k82f', 'frdm_kl43z', 'frdm_kl46z', 'frdm_kw24d', 'frdm_kw41z']),
    ('frdm_kl46z', 'Freescale Kinetis FRDM-KL46Z', ['frdm_k22f', 'frdm_k64f', 'frdm_k66f', 'frdm_k82f', 'frdm_kl25z', 'frdm_kl43z', 'frdm_kw24d', 'frdm_kw41z']),
    ('frdm_kw24d', 'Freescale Kinetis FRDM-KW24D512', ['frdm_k22f', 'frdm_k64f', 'frdm_k66f', 'frdm_k82f', 'frdm_kl25z', 'frdm_kl43z', 'frdm_kl46z', 'frdm_kw41z']),
    ('freenove_esp32_wrover', 'Freenove ESP32-Wrover', ['esp32wrover']),
    ('genericSTM32F103V8', 'STM32F103V8 (20k RAM. 64k Flash)', ['genericSTM32F103C8', 'genericSTM32F103T8']),
    ('genericSTM32F103VD', 'STM32F103VD (64k RAM. 384k Flash)', ['genericSTM32F103RD', 'genericSTM32F103ZD']),
    ('genericSTM32F103VE', 'STM32F103VE (64k RAM. 512k Flash)', ['genericSTM32F103RE', 'genericSTM32F103ZE']),
    ('genericSTM32F401RB', 'STM32F401RB (64k RAM. 128k Flash)', ['genericSTM32F401CB']),
    ('genericSTM32F401RC', 'STM32F401RC (64k RAM. 256k Flash)', ['genericSTM32F401CC']),
    ('genericSTM32F412CE', 'STM32F412CE (256k RAM. 512k Flash)', ['genericSTM32F412RE']),
    ('genericSTM32F413RG', 'STM32F413RG (320k RAM. 1024k Flash)', ['genericSTM32F413CG']),
    ('genericSTM32F446RE', 'STM32F446RE (128k RAM. 512k Flash)', ['genericSTM32F411CE', 'genericSTM32F411RE', 'genericSTM32F417VE']),
    ('giga_r1_m7', 'Arduino Giga R1 (M7 core)', ['giga', 'giga_r1_m4']),
    ('heltec_wireless_paper', 'Heltec Wireless Paper', ['heltec_wireless_bridge', 'heltec_wireless_stick', 'heltec_wireless_tracker']),
    ('heltec_wireless_shell_V3', 'Heltec Wireless Shell (V3)', ['heltec_wireless_mini_shell', 'heltec_wireless_stick_V3', 'heltec_wireless_stick_lite', 'heltec_wireless_stick_lite_V3']),
    ('heltec_wireless_tracker_v2', 'Heltec Wireless Tracker(V2)', ['heltec_wireless_tracker']),
    ('inex_openkb', 'INEX OpenKB', ['OpenKB']),
    ('kb32', 'KB32-FT', ['kb32-ft']),
    ('kits-edu', 'KITS ESP32 EDU', ['uPesy_edu_esp32']),
    ('laird_bl653_dvk', 'BL653 Development Kit', ['laird_bl652_dvk', 'laird_bl654_dvk']),
    ('leonardo', 'Arduino Leonardo', ['leonardoeth']),
    ('lolin_s2_mini', 'LOLIN S2 Mini', ['lolin_c3_mini', 'lolin_s2_pico', 'lolin_s3_mini']),
    ('lolin_s3_mini_pro', 'LOLIN S3 Mini Pro', ['d1_mini_pro', 'lolin_s3', 'lolin_s3_mini', 'lolin_s3_pro']),
    ('lolin_s3_pro', 'LOLIN S3 Pro', ['d32_pro', 'lolin_s3', 'lolin_s3_mini', 'lolin_s3_mini_pro']),
    ('lora_e5_mini', 'SeeedStudio LoRa-E5 mini', ['lora_e5_dev_board']),
    ('lpmsp430fr5969', 'TI LaunchPad MSP-EXP430FR5969LP', ['lpmsp430f5529', 'lpmsp430fr2311', 'lpmsp430fr2355', 'lpmsp430fr2433', 'lpmsp430fr2476', 'lpmsp430fr4133', 'lpmsp430fr5994', 'lpmsp430fr6989', 'lpmsp430g2553']),
    ('lpmsp430fr5994', 'TI LaunchPad MSP-EXP430FR5994LP', ['lpmsp430f5529', 'lpmsp430fr2311', 'lpmsp430fr2355', 'lpmsp430fr2433', 'lpmsp430fr2476', 'lpmsp430fr4133', 'lpmsp430fr5969', 'lpmsp430fr6989', 'lpmsp430g2553']),
    ('lpmsp430g2452', 'TI LaunchPad MSP-EXP430G2 w/ MSP430G2452', ['lpmsp430g2231']),
    ('lptm4c1294ncpdt', 'TI LaunchPad (Tiva C) w/ tm4c129 (120MHz)', ['lptm4c123gh6pm']),
    ('m5stack-core-esp32', 'M5Stack Core ESP32', ['m5stack-core-esp32-16M', 'm5stack-coreink', 'm5stack-grey', 'microduino-core-esp32']),
    ('megaatmega1280', 'Arduino Mega or Mega 2560 ATmega1280', ['mega', 'megaatmega2560']),
    ('metro', 'Adafruit Metro', ['adafruit_metro', 'adafruit_metro_esp32s2', 'adafruit_metro_esp32s3', 'adafruit_metro_m0', 'adafruit_metro_m4', 'adafruit_metro_rp2350', 'metro52840']),
    ('mgbot-iotik32b', 'MGBOT IOTIK 32B', ['mgbot-iotik32a']),
    ('mini', 'Arduino Mini', ['miniatmega168', 'miniatmega328', 'pro', 'uno_mini', 'unomini', 'yunmini']),
    ('miniatmega168', 'Arduino Mini ATmega168', ['btatmega168', 'lilypadatmega168', 'mini', 'miniatmega328', 'nanoatmega168', 'uno_mini', 'unomini']),
    ('minimain_esp32s2', 'Department of Alchemy MiniMain ESP32-S2', ['department_of_alchemy_minimain_esp32s2']),
    ('moteino8mhz', 'LowPowerLab Moteino (8Mhz)', ['moteino']),
    ('mts_mdot_f405rg', 'MultiTech mDot', ['mts_mdot_f411re']),
    ('mzeropro', 'Arduino M0 Pro (Programming/Debug Port)', ['mzero_pro_bl', 'mzero_pro_bl_dbg', 'mzeroproUSB', 'zero']),
    ('nano33ble', 'Arduino Nano 33 BLE', ['nano', 'nano_33_iot']),
    ('nano_33_iot', 'Arduino NANO 33 IoT', ['nano', 'nano33ble']),
    ('nano_nora', 'Arduino Nano ESP32', ['arduino_nano_esp32', 'nano', 'nano_every', 'nano_matter', 'nano_r4', 'nanoatmega168', 'nanoatmega328', 'nanor4', 'nona4809']),
    ('nano_r4', 'Arduino Nano R4', ['arduino_nano_esp32', 'nano', 'nano_every', 'nano_matter', 'nano_nora', 'nanoatmega168', 'nanoatmega328', 'nanor4', 'nona4809']),
    ('nanoatmega328new', 'Arduino Nano ATmega328 (New Bootloader)', ['nanoatmega328']),
    ('nanor4', 'Arduino Nano R4', ['arduino_nano_esp32', 'nano', 'nano_every', 'nano_matter', 'nano_nora', 'nano_r4', 'nanoatmega168', 'nanoatmega328', 'nona4809']),
    ('nicla_sense', 'Arduino Nicla Sense ME', ['nicla_sense_me']),
    ('nona4809', 'Arduino Nano Every', ['arduino_nano_esp32', 'nano', 'nano_every', 'nano_matter', 'nano_nora', 'nano_r4', 'nanoatmega168', 'nanoatmega328', 'nanor4']),
    ('nrf52840_mdk', 'Makerdiary nRF52840-MDK', ['nrf52832_mdk']),
    ('nucleo_f030r8', 'ST Nucleo F030R8', ['nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_f072rb', 'ST Nucleo F072RB', ['disco_f072rb', 'nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_f302r8', 'ST Nucleo F302R8', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_f334r8', 'ST Nucleo F334R8', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_f410rb', 'ST Nucleo F410RB', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_f446ze', 'ST Nucleo F446ZE', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_g0b1re', 'ST Nucleo G0B1RE', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_h563zi', 'ST Nucleo H563ZI', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_h745zi_q', 'ST Nucleo H745ZI-Q', ['nucleo_l552ze_q', 'nucleo_u575zi_q']),
    ('nucleo_l053r8', 'ST Nucleo L053R8', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_l073rz', 'ST Nucleo L073RZ', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_l152re', 'ST Nucleo L152RE', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_l476rg', 'ST Nucleo L476RG', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi', 'nucleo_wl55jc']),
    ('nucleo_wl55jc', 'ST Nucleo WL55JC', ['nucleo_f030r8', 'nucleo_f031k6', 'nucleo_f042k6', 'nucleo_f070rb', 'nucleo_f072rb', 'nucleo_f091rc', 'nucleo_f103rb', 'nucleo_f207zg', 'nucleo_f302r8', 'nucleo_f303k8', 'nucleo_f303re', 'nucleo_f303ze', 'nucleo_f334r8', 'nucleo_f401re', 'nucleo_f410rb', 'nucleo_f411re', 'nucleo_f412zg', 'nucleo_f413zh', 'nucleo_f429zi', 'nucleo_f439zi', 'nucleo_f446re', 'nucleo_f446ze', 'nucleo_f722ze', 'nucleo_f746zg', 'nucleo_f756zg', 'nucleo_f767zi', 'nucleo_g031k8', 'nucleo_g0b1re', 'nucleo_h563zi', 'nucleo_h723zg', 'nucleo_h743zi', 'nucleo_h753zi', 'nucleo_l010rb', 'nucleo_l011k4', 'nucleo_l031k6', 'nucleo_l053r8', 'nucleo_l073rz', 'nucleo_l152re', 'nucleo_l412kb', 'nucleo_l432kc', 'nucleo_l452re', 'nucleo_l476rg', 'nucleo_l486rg', 'nucleo_l496zg', 'nucleo_l4r5zi']),
    ('opta_digital', 'Arduino OPTA DIGITAL', ['opta_analog']),
    ('pca10100', 'Nordic nRF52833 DK', ['nrf52833_dk', 'nrf52840_dk', 'nrf52_dk', 'pca10056']),
    ('pcbcupid_glyph_2040', 'PCBCupid Glyph 2040', ['Pcbcupid_GLYPH_C3', 'Pcbcupid_GLYPH_C6', 'Pcbcupid_GLYPH_H2', 'Pcbcupid_GLYPH_S3', 'pcbcupid_glyph_c5', 'pcbcupid_glyph_mini_2040']),
    ('pico', 'Raspberry Pi Pico', ['raspberrypi_zero', 'rpipico', 'rpipico2', 'rpipico2w', 'rpipicow']),
    ('pinaka', 'Pinaka on Artix-7 35T Arty FPGA Evaluation Kit', ['artix7_35t', 'parashu']),
    ('pybstick26_std', 'PYBStick Standard 26', ['pybstick26_lite', 'pybstick26_pro']),
    ('raspberrypi_1b', 'Raspberry Pi 1 Model B', ['raspberrypi_2b', 'raspberrypi_3b']),
    ('redscorp_rp2040_eins', 'redscorp RP2040-Eins', ['redscorp_rp2040_promini']),
    ('rymcu-esp32-c3-devkitm-1', 'RYMCU ESP32-C3-DevKitM-1', ['esp32-c3-devkitm-1']),
    ('rymcu-esp32-s3-devkitc-1', 'RYMCU ESP32-S3-DevKitC-1-N8R2 (8 MB QD, 2 MB PSRAM)', ['esp32-s3-devkitc-1']),
    ('sainSmartDue', 'SainSmart Due (Programming Port)', ['due', 'sainSmartDueUSB']),
    ('sainSmartDueUSB', 'SainSmart Due (USB Native Port)', ['dueUSB', 'sainSmartDue']),
    ('seeed_xiao', 'Seeeduino XIAO', ['seeeduino']),
    ('seeed_xiao_esp32c6', 'Seeed Studio XIAO ESP32C6', ['XIAO_ESP32C6', 'seeed_xiao_esp32c3', 'seeed_xiao_esp32s3', 'xiao_mg24']),
    ('seeed_xiao_esp32s3', 'Seeed Studio XIAO ESP32S3', ['XIAO_ESP32S3', 'seeed_xiao_esp32c3', 'seeed_xiao_esp32c6', 'xiao_mg24']),
    ('seeed_xiao_rp2350', 'Seeed XIAO RP2350', ['seeed_xiao_rp2040']),
    ('seeeduino_lorawan', 'Seeeduino LoRaWAN', ['seeeduino']),
    ('soldered_nula_ethernet_w55rp20', 'Soldered Electronics NULA Ethernet W55RP20', ['soldered_nula_rp2350']),
    ('solderparty_rp2350_stamp_xl', 'Solder Party RP2350 Stamp XL', ['solderparty_rp2040_stamp', 'solderparty_rp2350_stamp']),
    ('sparkfunBlynk', 'SparkFun Blynk Board', ['blynk']),
    ('sparkfun_fiov3', 'SparkFun Fio V3 3.3V/8MHz', ['sparkfun_megapro8MHz', 'sparkfun_promicro8']),
    ('sparkfun_promicrorp2350', 'SparkFun ProMicro RP2350', ['sparkfun_promicrorp2040']),
    ('sparkfun_redboard_turbo', 'SparkFun RedBoard Turbo', ['sparkfun_redboard']),
    ('sparklemotionmini', 'Adafruit Sparkle Motion Mini (ESP32)', ['sparklemotion', 'sparklemotionstick']),
    ('teensy41', 'Teensy 4.1', ['teensy40']),
    ('thing', 'SparkFun ESP8266 Thing', ['esp32thing', 'thingdev']),
    ('thingdev', 'SparkFun ESP8266 Thing Dev', ['thing']),
    ('trinket3', 'Adafruit Trinket 3V/8MHz', ['itsybitsy32u4_3V']),
    ('trinket5', 'Adafruit Trinket 5V/16MHz', ['itsybitsy32u4_5V', 'protrinket5', 'protrinket5ftdi']),
    ('ttgo-t-watch', 'TTGO T-Watch', ['ttgo-t-beam', 'twatch']),
    ('ttgo-t7-v13-mini32', 'TTGO T7 V1.3 Mini32', ['ttgo-t7-v14-mini32']),
    ('uPesy_wroom', 'uPesy ESP32 Wroom DevKit', ['uPesy_wrover', 'upesy_wroom', 'upesy_wrover']),
    ('ublox_c030_r410m', 'u-blox C030-R410M IoT', ['ublox_c030_n211', 'ublox_c030_u201']),
    ('ublox_evk_odin_w2', 'u-blox EVK-ODIN-W2', ['mtb_ublox_odin_w2']),
    ('um_feathers2', 'UM FeatherS2', ['um_feathers2neo']),
    ('um_feathers2neo', 'UM FeatherS2 Neo', ['um_feathers2', 'um_feathers3neo']),
    ('uno', 'Arduino UNO', ['minima', 'uno2018', 'uno_mini', 'uno_r4_minima', 'uno_r4_wifi', 'uno_wifi_rev2', 'unomini', 'unor4wifi', 'unowifi']),
    ('uno_pic32', 'Digilent chipKIT UNO32', ['chipkit_cmod', 'chipkit_dp32', 'chipkit_mx3', 'chipkit_uc32', 'chipkit_wf32', 'chipkit_wifire', 'mega_pic32']),
    ('unomini', 'Arduino UNO Mini', ['mini', 'miniatmega168', 'miniatmega328', 'uno', 'uno_mini', 'unowifi']),
    ('unor4wifi', 'Arduino UNO R4 WiFi', ['minima', 'uno', 'uno2018', 'uno_r4_minima', 'uno_r4_wifi', 'uno_wifi_rev2', 'unowifi']),
    ('unowifi', 'Arduino UNO WiFi', ['uno', 'uno2018', 'uno_mini', 'uno_r4_wifi', 'uno_wifi_rev2', 'unomini', 'unor4wifi']),
    ('upesy_esp32c3_basic', 'uPesy ESP32C3 Basic', ['upesy_esp32c3_mini', 'upesy_esp32s3_basic']),
    ('upesy_wrover', 'uPesy ESP32 Wrover DevKit', ['uPesy_wroom', 'uPesy_wrover', 'upesy_wroom']),
    ('vake_v1', 'VAkE v1.0', ['thunder_pack']),
    ('vccgnd_f103zet6', 'VCCGND F103ZET6 Mini', ['vccgnd_f407zg_mini']),
    ('vccgnd_f407zg_mini', 'VCCGND F407ZGT6 Mini', ['vccgnd_f103zet6']),
    ('vintlabs-devkit-v1', 'VintLabs ESP32 Devkit', ['fm-devkit']),
    ('waveshare_esp32_c6_zero', 'Waveshare ESP32-C6-Zero', ['waveshare_esp32_c3_zero', 'waveshare_esp32_s3_zero']),
    ('waveshare_esp32_s3_touch_amoled_241', 'Waveshare ESP32-S3-Touch-AMOLED-2.41', ['waveshare_esp32_s3_touch_amoled_143', 'waveshare_esp32_s3_touch_amoled_164', 'waveshare_esp32_s3_touch_amoled_18', 'waveshare_esp32_s3_touch_amoled_191', 'waveshare_esp32_s3_touch_amoled_206', 'waveshare_esp32_s3_touch_lcd_21', 'waveshare_esp32_s3_touch_lcd_28']),
    ('waveshare_esp32_s3_touch_lcd_21', 'Waveshare ESP32-S3-Touch-LCD-2.1', ['waveshare_esp32_s3_lcd_146', 'waveshare_esp32_s3_lcd_147', 'waveshare_esp32_s3_lcd_169', 'waveshare_esp32_s3_lcd_185', 'waveshare_esp32_s3_touch_amoled_143', 'waveshare_esp32_s3_touch_amoled_164', 'waveshare_esp32_s3_touch_amoled_18', 'waveshare_esp32_s3_touch_amoled_191', 'waveshare_esp32_s3_touch_amoled_206', 'waveshare_esp32_s3_touch_amoled_241', 'waveshare_esp32_s3_touch_lcd_146', 'waveshare_esp32_s3_touch_lcd_169', 'waveshare_esp32_s3_touch_lcd_185', 'waveshare_esp32_s3_touch_lcd_185_box', 'waveshare_esp32_s3_touch_lcd_28', 'waveshare_esp32_s3_touch_lcd_4', 'waveshare_esp32_s3_touch_lcd_43', 'waveshare_esp32_s3_touch_lcd_43B', 'waveshare_esp32_s3_touch_lcd_5', 'waveshare_esp32_s3_touch_lcd_5B', 'waveshare_esp32_s3_touch_lcd_7']),
    ('waveshare_rp2040_lcd_0_96', 'Waveshare RP2040 LCD 0.96', ['waveshare_rp2350_lcd_0_96']),
    ('waveshare_rp2040_lora', 'Waveshare RP2040 LoRa', ['waveshare_rp2040_matrix', 'waveshare_rp2040_one', 'waveshare_rp2040_pizero', 'waveshare_rp2040_plus', 'waveshare_rp2040_zero']),
    ('waveshare_rp2040_zero', 'Waveshare RP2040 Zero', ['waveshare_rp2040_lora', 'waveshare_rp2040_matrix', 'waveshare_rp2040_one', 'waveshare_rp2040_pizero', 'waveshare_rp2040_plus', 'waveshare_rp2350_zero']),
    ('we_oceanus1_ev', 'WE Oceanus-I EV', ['we_oceanus1']),
    ('wemos_d1_mini32', 'WEMOS D1 MINI ESP32', ['d1_mini', 'd1_mini32', 'd1_mini_clone', 'd1_mini_lite', 'd1_mini_pro']),
    ('wemos_d1_uno32', 'WEMOS D1 R32', ['d1_uno32']),
    ('wemosbat', 'WeMos WiFi and Bluetooth Battery', ['WeMosBat']),
    ('wio_3g', 'Seeed Wio 3G', ['wiolink']),
    ('wiolink', 'Seeed Wio Link', ['wio_3g', 'wio_link']),
    ('wiznet_5100s_evb_pico2', 'WIZnet W5100S-EVB-Pico2', ['wiznet_5100s_evb_pico', 'wiznet_5500_evb_pico2', 'wiznet_6300_evb_pico2']),
    ('xiao_mg24', 'Seeed Studio XIAO MG24 (Sense)', ['seeed_xiao_esp32c3', 'seeed_xiao_esp32c6', 'seeed_xiao_esp32s3']),
    ('zero', 'Arduino Zero (Programming/Debug Port)', ['arduino_zero_edbg', 'due', 'mzeropro']),
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
            capture_output=True, text=True, timeout=600, check=True,
        )
    finally:
        os.unlink(batch_path)
    return json.loads(proc.stdout)


def _compute_metrics(cases, results):
    """top_1 % + MRR over (case, result) pairs. A hit is a returned
    board whose name matches the queried name (case-insensitive)."""
    top1_hits = 0
    rr_sum = 0.0
    misses = []
    for (bid, name, peers), r in zip(cases, results):
        boards = r["data"]["boards"]
        want_lc = name.lower()
        rank = None
        for i, b in enumerate(boards):
            if b["row"]["name"].lower() == want_lc:
                rank = i + 1
                break
        if rank == 1:
            top1_hits += 1
        if rank is not None:
            rr_sum += 1.0 / rank
        else:
            misses.append((name, bid, [b["row"]["board_id"]
                                       for b in boards[:3]]))
    n = len(cases)
    return {
        "top_1_pct": 100 * top1_hits / n,
        "mrr": rr_sum / n,
        "misses": misses,
    }


@unittest.skipIf(BUN is None, "bun runtime not installed")
class SimilarNamesTop1Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        items = [{"text": name, "mode": "board"}
                 for _, name, _ in SIMILAR_NAME_CASES]
        results = _run_batch(items)
        assert len(results) == len(SIMILAR_NAME_CASES)
        cls.metrics = _compute_metrics(SIMILAR_NAME_CASES, results)
        print(f"\n[similar-names] cases={len(SIMILAR_NAME_CASES)} "
              f"top_1={cls.metrics['top_1_pct']:.1f}% "
              f"mrr={cls.metrics['mrr']:.3f}",
              file=sys.stderr)

    def test_corpus_size(self) -> None:
        self.assertEqual(len(SIMILAR_NAME_CASES), 200)

    def test_top_1_floor(self) -> None:
        # Floor set at 80% — the current default-BM25 baseline. Move
        # this floor up after a tuning PR proves the new weights are
        # stable.
        FLOOR = 80.0
        self.assertGreaterEqual(
            self.metrics["top_1_pct"], FLOOR,
            f"top-1 hit rate {self.metrics['top_1_pct']:.1f}% < {FLOOR}% floor.\n"
            + (f"First {min(len(self.metrics['misses']), 10)} misses:\n"
               + "\n".join(f"  {n!r} (want {b}) → top: {g}"
                            for n, b, g in self.metrics["misses"][:10])
               if self.metrics["misses"] else "")
        )


if __name__ == "__main__":
    unittest.main()
