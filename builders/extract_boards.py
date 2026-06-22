#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.10"
# ///
"""Extract per-board metadata records from the `platformio` and `arduino`
data-branch worktrees so the public portal can list, search, and link to
each individual board definition.

Distinct from extract_{platformio,arduino}.py — those pull (vid, pid,
product, source) triples for the VID:PID lookup. This script pulls the
*board* itself: name, vendor, mcu, frequency, all VID:PIDs, plus the
relative path of the source JSON so site.py can copy it into the
published bundle and the UI can deep-link to it via GitHub Pages.

Output shape (structured fields only — the raw upstream JSON is NOT
copied into the bundle; users follow `upstream_blob` to view it):

    {
      "layer": "boards",
      "boards": [
        {
          "layer":            "platformio",  # or "arduino"
          "sublayer":         "espressif32", # platform or core slug
          "board_id":         "esp32dev",
          "name":             "Espressif ESP32 Dev Module",
          "vendor":           "Espressif",
          "mcu":              "esp32",
          "frequency_mhz":    240,
          "flash_kb":         4096,
          "ram_kb":           320,
          "upload_speed":     460800,
          "upload_protocol":  null,
          "core":             "esp32",
          "variant":          "esp32",
          "homepage":         "https://en.wikipedia.org/wiki/ESP32",
          "frameworks":       "arduino,espidf",
          "connectivity":     "bluetooth,can,ethernet,wifi",
          "debug_tool":       "esp-wroom-32.cfg",
          "vidpids":          [["303a", "0002"]],
          "upstream_repo":    "https://github.com/platformio/platform-espressif32",
          "upstream_blob":    "https://github.com/platformio/platform-espressif32/tree/HEAD/boards/esp32dev.json"
        }
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any


# Hard-coded core slug -> upstream repo URL for arduino cores. The boards
# in these cores are parsed out of one shared boards.txt per core, so we
# can only link to the core repo, not a per-board file.
ARDUINO_UPSTREAM = {
    "arduino-arduinocore-avr":         "https://github.com/arduino/ArduinoCore-avr",
    "arduino-arduinocore-samd":        "https://github.com/arduino/ArduinoCore-samd",
    "arduino-arduinocore-megaavr":     "https://github.com/arduino/ArduinoCore-megaavr",
    "arduino-arduinocore-mbed":        "https://github.com/arduino/ArduinoCore-mbed",
    "arduino-arduinocore-renesas":     "https://github.com/arduino/ArduinoCore-renesas",
    "espressif-arduino-esp32":         "https://github.com/espressif/arduino-esp32",
    "esp8266-arduino":                 "https://github.com/esp8266/Arduino",
    "adafruit-adafruit_nrf52_arduino": "https://github.com/adafruit/Adafruit_nRF52_Arduino",
    "stm32duino-arduino_core_stm32":   "https://github.com/stm32duino/Arduino_Core_STM32",
    "siliconlabs-arduino":             "https://github.com/SiliconLabs/arduino",
    "earlephilhower-arduino-pico":     "https://github.com/earlephilhower/arduino-pico",
}


def _norm_hex(s: Any, width: int) -> str | None:
    if isinstance(s, int):
        return f"{s:0{width}x}"
    if not isinstance(s, str):
        return None
    s = s.strip().lower().removeprefix("0x")
    if not s:
        return None
    try:
        int(s, 16)
    except ValueError:
        return None
    if len(s) > width:
        return None
    return s.zfill(width)


def _f_cpu_mhz(s: Any) -> int | None:
    """Parse build.f_cpu (e.g. '240000000L', '16000000') into MHz."""
    if isinstance(s, (int, float)):
        hz = int(s)
    elif isinstance(s, str):
        t = s.strip().upper().rstrip("L").rstrip("UL")
        try:
            hz = int(t)
        except ValueError:
            return None
    else:
        return None
    if hz <= 0:
        return None
    return hz // 1_000_000 or None


def _int_or_none(v: Any) -> int | None:
    if isinstance(v, (int, float)):
        return int(v) if v else None
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _bytes_to_kb(v: Any) -> int | None:
    """Bytes → KB (e.g. 4194304 → 4096). Returns None for falsy/invalid."""
    n = _int_or_none(v)
    return None if n is None or n <= 0 else max(1, n // 1024)


def _csv_or_none(v: Any) -> str | None:
    """Normalize a list of strings to a sorted CSV; returns None when empty."""
    if not isinstance(v, list):
        return None
    items = sorted({s.strip().lower() for s in v
                    if isinstance(s, str) and s.strip()})
    return ",".join(items) if items else None


def _str_or_none(v: Any) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


# MCU prefix → (architecture, bit_width). Hand-maintained from the
# canonical MCU family databases; covers every chip family present in
# the platformio + arduino data branches at the time of writing.
#
# `architecture` is intentionally written with `-` so the default FTS5
# tokenizer splits "cortex-m7" into the searchable tokens "cortex" + "m7";
# the same goes for "cortex-m0plus", "cortex-m33", etc. Users can search
# either the full name or just the family token.
_MCU_PREFIX_TABLE: list[tuple[str, str, int]] = [
    # (prefix, architecture, bit_width)
    # NXP i.MX RT (Teensy 4.x)
    ("imxrt",       "cortex-m7",     32),
    # STM32 by series (high to low first so the more specific prefix wins)
    ("stm32h",      "cortex-m7",     32),
    ("stm32f7",     "cortex-m7",     32),
    ("stm32f4",     "cortex-m4",     32),
    ("stm32l4",     "cortex-m4",     32),
    ("stm32f3",     "cortex-m4",     32),
    ("stm32g4",     "cortex-m4",     32),
    ("stm32f1",     "cortex-m3",     32),
    ("stm32f2",     "cortex-m3",     32),
    ("stm32l1",     "cortex-m3",     32),
    ("stm32g0",     "cortex-m0plus", 32),
    ("stm32f0",     "cortex-m0",     32),
    ("stm32l0",     "cortex-m0plus", 32),
    ("stm32u5",     "cortex-m33",    32),
    ("stm32",       "cortex-m",      32),  # any other STM32
    # Atmel SAM / Microchip
    ("samd21",      "cortex-m0plus", 32),
    ("samd51",      "cortex-m4",     32),
    ("samd",        "cortex-m",      32),
    ("samc",        "cortex-m0plus", 32),
    ("same",        "cortex-m4",     32),
    ("sam3",        "cortex-m3",     32),
    # Nordic
    ("nrf52840",    "cortex-m4",     32),
    ("nrf52833",    "cortex-m4",     32),
    ("nrf52832",    "cortex-m4",     32),
    ("nrf52",       "cortex-m4",     32),
    ("nrf53",       "cortex-m33",    32),
    ("nrf51",       "cortex-m0",     32),
    ("nrf",         "cortex-m",      32),
    # Raspberry Pi
    ("rp2040",      "cortex-m0plus", 32),
    ("rp2350",      "cortex-m33",    32),
    # NXP Kinetis (Teensy 3.x)
    ("mk20dx",      "cortex-m4",     32),
    ("mk64",        "cortex-m4",     32),
    ("mk66",        "cortex-m4",     32),
    ("mkl26",       "cortex-m0plus", 32),
    ("mkl",         "cortex-m0plus", 32),
    ("mk",          "cortex-m4",     32),
    # TI
    ("cc32",        "cortex-m4",     32),
    ("cc26",        "cortex-m4",     32),
    ("cc13",        "cortex-m4",     32),
    ("tm4c",        "cortex-m4",     32),
    ("msp432",      "cortex-m4",     32),
    ("msp430",      "msp430",        16),
    # Silicon Labs
    ("efr32mg2",    "cortex-m33",    32),
    ("efr32",       "cortex-m4",     32),
    ("efm32",       "cortex-m",      32),
    # Espressif — Xtensa LX6/LX7 vs RISC-V
    # NB: order matters; check the RISC-V parts (c/h suffix) before the
    # generic esp32 fallback.
    ("esp32-c", "riscv",   32),
    ("esp32c",  "riscv",   32),
    ("esp32-h", "riscv",   32),
    ("esp32h",  "riscv",   32),
    ("esp32-s", "xtensa",  32),
    ("esp32s",  "xtensa",  32),
    ("esp32",   "xtensa",  32),
    ("esp8266", "xtensa",  32),
    # Renesas (Arduino UNO R4, Portenta C33)
    ("ra4",         "cortex-m33",    32),
    ("ra6",         "cortex-m33",    32),
    # SiFive / RISC-V
    ("fe310",       "riscv",         32),
    ("fe3",         "riscv",         32),
    # Atmel AVR / Microchip 8-bit
    ("atmega",      "avr",            8),
    ("atxmega",     "avr",            8),
    ("attiny",      "avr",            8),
    ("at90",        "avr",            8),
    # 8051 family (Nuvoton etc.)
    ("n76",         "8051",           8),
]


def _derive_arch_bits(mcu: str | None) -> tuple[str | None, int | None]:
    """Return (architecture, bit_width) inferred from the MCU string.
    Both fall back to None when the chip family isn't recognised."""
    if not mcu:
        return None, None
    m = mcu.lower().strip()
    for prefix, arch, bits in _MCU_PREFIX_TABLE:
        if m.startswith(prefix):
            return arch, bits
    return None, None


# Whole-string stop words for the keyword soup. Match is case-insensitive
# against the FULL string value — so the standalone menu sub-label
# "Disabled" gets filtered out, but a rich descriptive string like
# "Disable interrupts" or "Default with spiffs" stays in the index
# because it doesn't match any entry verbatim.
#
# Curated from the dict-key recon (tools/gen_search_keys_corpus.py):
# 24 keys appeared as standalone string values across hundreds of
# boards' menu structures with no realistic search intent — log levels
# (info/warn/error), generic UI states (default/none/disabled/enable),
# size labels (small/fast/minimal/custom), and schema-shaped
# abbreviations (boot/mode/port/os/sdk/ld/fp).
#
# NOT included — these hit broadly too but are real search terms users
# would type, and they're already covered by structured columns
# (architecture / connectivity / frameworks):
#   arduino, mbed, freertos, zephyr, riscv, arm, xtensa,
#   wifi, bluetooth, serial, wire, psram, zigbee, cdc, dfu, flash
_STOP_WORDS: frozenset[str] = frozenset({
    # Log levels
    "info", "warn", "error", "verbose",
    # Generic UI states
    "default", "disable", "disabled", "enable", "enabled",
    "none", "on", "off", "all", "custom",
    # Size / speed labels
    "minimal", "small", "fast",
    # Pure schema labels that bled in as menu values
    "boot", "mode", "port", "os", "sdk", "ld", "fp",
})


def _is_numeric(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    try:
        int(s); return True
    except ValueError:
        pass
    try:
        int(s, 0); return True
    except (ValueError, TypeError):
        pass
    try:
        float(s); return True
    except ValueError:
        pass
    return False


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _filter_stop_tokens(s: str) -> str:
    """Tokenize `s` using the same alphanumeric+underscore rule
    FTS5's unicode61 tokenizer uses, drop tokens whose lowercase form
    is in _STOP_WORDS, and rejoin with spaces.

    Token-level filter applied at INDEX time. Must stay in lockstep
    with the JS ftsQuery() filter at QUERY time (site-src/src/util/
    fts.js) so the same words are stripped on both sides — otherwise
    queries would contain tokens that can't possibly match the
    filtered index.
    """
    tokens = _TOKEN_RE.findall(s)
    kept = [t for t in tokens if t.lower() not in _STOP_WORDS]
    return " ".join(kept)


def _collect_keywords(obj: Any, sink: set[str], max_len: int = 200) -> None:
    """Recursively walk the per-board JSON and gather every string value
    that looks like it could be a search term users would type. Used to
    populate the boards.keywords column (and via that, boards_fts) so
    free-text search hits the long tail — STM32duino menu.pnum.* part
    numbers, ESP8266 build.board macros, Zephyr variant aliases, etc.

    Skipped, in order:
      - empty / whitespace
      - longer than max_len chars (giant license blobs etc.)
      - URLs (http:// or https://)
      - template placeholders (contain `{` or `}`)
      - purely numeric literals (parseable as int / 0x-int / float)
      - whole-string stop-word matches
    Then the surviving string is tokenized and stop tokens are
    stripped at token level too, so a multi-word string like
    "Default with spiffs" becomes "with spiffs" before it's added.
    Dict KEYS are intentionally NOT collected — they're schema labels
    (menu, build, hwids, …) and would only add noise.
    """
    if isinstance(obj, str):
        s = obj.strip()
        if not s or len(s) > max_len:
            return
        sl = s.lower()
        if sl.startswith(("http://", "https://")):
            return
        if "{" in s or "}" in s:
            return
        if _is_numeric(s):
            return
        if sl in _STOP_WORDS:
            return
        filtered = _filter_stop_tokens(s)
        if not filtered.strip():
            return
        sink.add(filtered)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_keywords(v, sink, max_len)
    elif isinstance(obj, list):
        for v in obj:
            _collect_keywords(v, sink, max_len)


def _extract_aliases(b: dict) -> list[str]:
    """Structured aliases — alternate identifiers a user might type that
    point back to this board. Distinct from `keywords` in that these
    are pulled from known schema locations rather than free-walking, and
    can be surfaced in the UI as "this board also goes by:".

    Sources covered (no-op when the field is absent):
      - Arduino board.txt `menu.pnum.<KEY>` substructure (STM32duino's
        variant part-numbers): collect the KEY itself, the empty-key
        label inside it, and any `build.board` macro it defines.
      - PlatformIO `build.zephyr.variant` (Zephyr board alias).
      - PlatformIO `debug.openocd_board` (OpenOCD target name).
      - `build.board` macro at the top level (ESP8266 boards encode the
        Arduino build define here, e.g. `ESP8266_WEMOS_D1MINI`).
    """
    aliases: set[str] = set()
    menu = b.get("menu") if isinstance(b.get("menu"), dict) else {}
    pnum = menu.get("pnum") if isinstance(menu.get("pnum"), dict) else {}
    for key, val in pnum.items():
        if isinstance(key, str) and key.strip():
            aliases.add(key.strip())
        if isinstance(val, dict):
            label = val.get("")
            if isinstance(label, str) and label.strip():
                aliases.add(label.strip())
            sub_build = val.get("build") if isinstance(val.get("build"), dict) else {}
            sub_board = sub_build.get("board")
            if isinstance(sub_board, str) and sub_board.strip():
                aliases.add(sub_board.strip())
    build = b.get("build") if isinstance(b.get("build"), dict) else {}
    zephyr = build.get("zephyr") if isinstance(build.get("zephyr"), dict) else {}
    zv = zephyr.get("variant") if isinstance(zephyr, dict) else None
    if isinstance(zv, str) and zv.strip():
        aliases.add(zv.strip())
    debug = b.get("debug") if isinstance(b.get("debug"), dict) else {}
    ob = debug.get("openocd_board") if isinstance(debug, dict) else None
    if isinstance(ob, str) and ob.strip():
        aliases.add(ob.strip())
    top_build_board = build.get("board")
    if isinstance(top_build_board, str) and top_build_board.strip():
        aliases.add(top_build_board.strip())
    return sorted(aliases)


def _unquote(s: Any) -> str | None:
    if not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.strip() or None


def _norm_root(root: pathlib.Path) -> pathlib.Path:
    """Tolerate both `<branch-root>` and `<branch-root>/data` as input."""
    if (root / "data").is_dir() and not list(root.glob("*/boards/*.json")):
        return root / "data"
    return root


def _platformio_upstream(plat_dir: pathlib.Path, board_id: str) -> tuple[str | None, str | None]:
    """Read <plat>/platform.json -> (repo_url, per-board blob_url)."""
    pj = plat_dir / "platform.json"
    if not pj.is_file():
        return None, None
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    repo = (data.get("repository") or {}).get("url")
    if not isinstance(repo, str):
        return None, None
    # Normalize ".git" suffix off so we can build /tree/HEAD paths.
    repo = repo.rstrip("/")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    blob = f"{repo}/tree/HEAD/boards/{board_id}.json"
    return repo, blob


def _extract_platformio(root: pathlib.Path) -> list[dict]:
    out: list[dict] = []
    if not root.is_dir():
        print("boards: platformio root missing; skipping", file=sys.stderr)
        return out
    root = _norm_root(root)
    for board_json in sorted(root.glob("*/boards/*.json")):
        plat = board_json.parts[-3]
        board_id = board_json.stem
        try:
            b = json.loads(board_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"boards[platformio:skip]: {board_json}: {e}", file=sys.stderr)
            continue

        build = b.get("build") or {}
        upload = b.get("upload") or {}
        debug = b.get("debug") or {}

        vidpids: list[list[str]] = []
        for entry in (build.get("hwids") or []):
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                vid = _norm_hex(entry[0], 4)
                pid = _norm_hex(entry[1], 4)
                if vid and pid:
                    vidpids.append([vid, pid])

        mcu_str = _str_or_none(build.get("mcu"))
        arch, bits = _derive_arch_bits(mcu_str)
        repo, blob = _platformio_upstream(root / plat, board_id)
        kw_sink: set[str] = set()
        _collect_keywords(b, kw_sink)
        aliases = _extract_aliases(b)
        out.append({
            "layer":            "platformio",
            "sublayer":         plat,
            "board_id":         board_id,
            "name":             (b.get("name") or board_id).strip(),
            "vendor":           _str_or_none(b.get("vendor")),
            "mcu":              mcu_str,
            "architecture":     arch,
            "bit_width":        bits,
            "frequency_mhz":    _f_cpu_mhz(build.get("f_cpu")),
            "flash_kb":         _bytes_to_kb(upload.get("maximum_size")),
            "ram_kb":           _bytes_to_kb(upload.get("maximum_ram_size")),
            "upload_speed":     _int_or_none(upload.get("speed")),
            "upload_protocol":  _str_or_none(upload.get("protocol")),
            "core":             _str_or_none(build.get("core")),
            "variant":          _str_or_none(build.get("variant")),
            "homepage":         _str_or_none(b.get("url")),
            "frameworks":       _csv_or_none(b.get("frameworks")),
            "connectivity":     _csv_or_none(b.get("connectivity")),
            "debug_tool":       _str_or_none(debug.get("openocd_board")
                                              or debug.get("default_tool")),
            "aliases":          ",".join(aliases) if aliases else None,
            "keywords":         " ".join(sorted(kw_sink)) if kw_sink else None,
            "vidpids":          vidpids,
            "upstream_repo":    repo,
            "upstream_blob":    blob,
            # Source path under the layer's data dir — site.py uses this to
            # stage a copy of the JSON into the published bundle at
            # boards/<layer>/<src_relpath>, served as a static asset for the
            # portal's "View JSON" button.
            "src_relpath":      f"{plat}/boards/{board_id}.json",
        })
    return out


def _arduino_vidpids(b: dict) -> list[list[str]]:
    pairs: list[list[str]] = []
    vd = b.get("vid") if isinstance(b.get("vid"), dict) else {}
    pd = b.get("pid") if isinstance(b.get("pid"), dict) else {}
    common = sorted(set(vd) & set(pd),
                    key=lambda k: int(k) if k.isdigit() else 1_000_000)
    for k in common:
        vid = _norm_hex(vd.get(k, ""), 4)
        pid = _norm_hex(pd.get(k, ""), 4)
        if vid and pid:
            pairs.append([vid, pid])
    bv = _norm_hex((b.get("build") or {}).get("vid", ""), 4)
    bp = _norm_hex((b.get("build") or {}).get("pid", ""), 4)
    if bv and bp and [bv, bp] not in pairs:
        pairs.append([bv, bp])
    return pairs


def _extract_arduino(root: pathlib.Path) -> list[dict]:
    out: list[dict] = []
    if not root.is_dir():
        print("boards: arduino root missing; skipping", file=sys.stderr)
        return out
    root = _norm_root(root)
    for board_json in sorted(root.glob("*/boards/*.json")):
        core = board_json.parts[-3]
        board_id = board_json.stem
        try:
            b = json.loads(board_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"boards[arduino:skip]: {board_json}: {e}", file=sys.stderr)
            continue

        build = b.get("build") or {}
        upload = b.get("upload") or {}
        name = (b.get("name") or _unquote(build.get("usb_product")) or board_id).strip()
        upstream = ARDUINO_UPSTREAM.get(core)
        # Arduino boards run under the Arduino framework by definition;
        # mark frameworks accordingly so the UI can show it as a chip.
        frameworks_csv = "arduino"
        mcu_str = _str_or_none(build.get("mcu"))
        arch, bits = _derive_arch_bits(mcu_str)
        kw_sink: set[str] = set()
        _collect_keywords(b, kw_sink)
        aliases = _extract_aliases(b)
        out.append({
            "layer":            "arduino",
            "sublayer":         core,
            "board_id":         board_id,
            "name":             name,
            "vendor":           None,
            "mcu":              mcu_str,
            "architecture":     arch,
            "bit_width":        bits,
            "frequency_mhz":    _f_cpu_mhz(build.get("f_cpu")),
            "flash_kb":         _bytes_to_kb(upload.get("maximum_size")),
            # `maximum_data_size` is what Arduino calls available RAM.
            "ram_kb":           _bytes_to_kb(upload.get("maximum_data_size")),
            "upload_speed":     _int_or_none(upload.get("speed")),
            "upload_protocol":  _str_or_none(upload.get("protocol")),
            "core":             _str_or_none(build.get("core")),
            "variant":          _str_or_none(build.get("variant")),
            "homepage":         None,
            "frameworks":       frameworks_csv,
            "connectivity":     None,
            "debug_tool":       None,
            "aliases":          ",".join(aliases) if aliases else None,
            "keywords":         " ".join(sorted(kw_sink)) if kw_sink else None,
            "vidpids":          _arduino_vidpids(b),
            "upstream_repo":    upstream,
            "upstream_blob":    upstream,
            "src_relpath":      f"{core}/boards/{board_id}.json",
        })
    return out


def extract(data_root: pathlib.Path) -> dict[str, Any]:
    pio = _extract_platformio(data_root / "platformio")
    ard = _extract_arduino(data_root / "arduino")
    boards = pio + ard
    print(f"boards: platformio={len(pio)} arduino={len(ard)} total={len(boards)}",
          file=sys.stderr)
    return {"layer": "boards", "boards": boards}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in",  dest="in_dir",  required=True, type=pathlib.Path,
                   help="data root containing platformio/ and arduino/ branch worktrees")
    p.add_argument("--out", dest="out", required=True, type=pathlib.Path)
    args = p.parse_args()
    records = extract(args.in_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"boards: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
