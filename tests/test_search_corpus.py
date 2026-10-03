"""Auto-generated search-term corpus.

Sampled from per-board JSON manifests + curated rules under
site-src/public/boards/ and .extern-repos/boards-other/. Sampling is
reproducible:

    python tools/gen_search_corpus.py --n 100 --seed 0

Generation stats at last regen:
    JSON files scanned: 2090
    unique strings (len > 4, non-numeric): 13017
    sample size:        100
    seed:               0

Do not edit the SEARCH_TERMS list by hand — regenerate via the tool
above so the sample stays linked to a deterministic seed.
"""

import unittest


SEARCH_TERMS = [
    'Generic STC8F1K17',
    'stm32l476g_disco',
    'MH_ET_LIVE_ESP32DEVKIT',
    '-DARDUINO_FEATHER_M4',
    'GENERIC_G041G8UX',
    'STM32G0xx/G031F(4-6-8)P_G031Y8Y_G041F(6-8)P_G041Y8Y',
    'STM32F0xx/F051K4T',
    'India',
    '{build.usb_flags} -DUSBD_USE_HID_COMPOSITE',
    'GPIO 39',
    'ST Nucleo F413ZH',
    'Generic IAP15F106',
    'atmega165a',
    'ESP8266_WEMOS_D1MINI',
    'STM32F439x.svd',
    '32KB cache + 32KB IRAM (balanced)',
    'GENERIC_L031E6YX',
    '32MB (Sketch: 13MB, FS: 19MB)',
    'stm32h750ibk6',
    '-DSTM32L4 -DSTM32L452xx',
    'heltec_wifi_lora_32',
    'GENERIC_F412ZEJX',
    'STM32WB0x',
    'moteino_m0',
    'cytron_maker_uno_rp2040',
    '80000000L',
    'Generic F031G6Ux',
    '-DUSBD_PID=0x102d',
    'sparkfun_thingplusrp2350',
    '-DRP2350_PSRAM_CS=35',
    'https://www.stcmicro.com/STC/STC89C52RC.html',
    'Generic F429ZETx',
    'SODAQ Tatu',
    'ViraLink Gate32-0.1',
    '-DUSBD_PID=0x4253',
    'Generic H723VGTx',
    'NOD_U575ZI',
    'Generic F101C6Tx',
    'esp32c61-ftdi.cfg',
    'https://github.com/RAKWireless/RAK811',
    'Default with spiffs',
    'The Things Uno',
    'ST Nucleo F756ZG',
    'NoAssert-NDEBUG',
    'STM32L072KZ',
    'GENERIC_G061C6TX',
    '-DESP8266 -DARDUINO_ARCH_ESP8266 -DARDUINO_ESP8266_SONOFF_S20',
    'TLS_MEM+HTTP_SERVER',
    '"Revelop eS"',
    '-DSTM32H7 -DSTM32H7xx -DSTM32H745xx',
    'pimoroni_servo2040',
    'HORNBILL_ESP32_MINIMA',
    'nanor4',
    '{runtime.platform.path}/debugger/R7FA4M1AB.cfg',
    'https://www.microchip.com/wwwproducts/en/AVR64DD20',
    'http://www.atmel.com/devices/ATTINY45.aspx',
    '"Amken"',
    'esp32s2-kaluga-1.cfg',
    'STM32F205xx',
    'Generic F756ZGTx',
    'GENERIC_F215VETX',
    'st_nucleo_f4',
    'Generic F378VCTx',
    'ml51ob9ae',
    '-DESP8266 -DARDUINO_ARCH_ESP8266 -DARDUINO_ESP8266_XINABOX_CW01',
    'BluesWireless',
    'Waveshare ESP32-S3-Touch-AMOLED-2.41',
    'Element14 chipKIT Pi',
    'GENERIC_F101ZCTX',
    '32MX795F512H',
    'SparkFun IoT Node LoRaWAN',
    'Nucleo U385RG-Q',
    '-DSTM32F4 -DSTM32F446xx',
    '-DSTC15W4KXXS4 -DSTC15W4K16S4 -DNAKED_ARCH_MCS51 -DNAKED_MCS51_STC15W4KXXS4',
    'Generic F205RFTx',
    'STM32F7508-DK',
    'STM32F103RG',
    '-DZIGBEE_MODE_ED',
    'GPIO 10',
    'Teensy (Serial mode)',
    'GENERIC_L431RBYX',
    'msp430fr2476',
    '128MB (Sketch: 27MB, FS: 101MB)',
    'TI LaunchPad MSP-EXP430F5529LP',
    'Generic F746ZEYx',
    'Smart Bee',
    'DatanoiseTV PicoADK',
    'default_ffat_8MB',
    'TI FraunchPad MSP-EXP430FR5739LP',
    'attiny1614',
    'GENERIC_L083CZUX',
    'Nucleo F303RE',
    '-DSTM32F407xx -DARDUINO_STM32GenericF407VET6 -DSTM32F4',
    'canipulator_v1',
    'Generic STC8C2K64S4',
    'Generic F103CBTx',
    'adafruit_feather_esp32s2_tft',
    'GENERIC_F205RGEX',
    'GENERIC_L412K8UX',
    'Aurora One',
]


class SearchCorpusTests(unittest.TestCase):
    def test_corpus_size(self) -> None:
        self.assertEqual(len(SEARCH_TERMS), 100)

    def test_corpus_unique(self) -> None:
        self.assertEqual(len(set(SEARCH_TERMS)), len(SEARCH_TERMS))


if __name__ == "__main__":
    unittest.main()
