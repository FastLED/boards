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

        repo, blob = _platformio_upstream(root / plat, board_id)
        out.append({
            "layer":            "platformio",
            "sublayer":         plat,
            "board_id":         board_id,
            "name":             (b.get("name") or board_id).strip(),
            "vendor":           _str_or_none(b.get("vendor")),
            "mcu":              _str_or_none(build.get("mcu")),
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
            "vidpids":          vidpids,
            "upstream_repo":    repo,
            "upstream_blob":    blob,
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
        out.append({
            "layer":            "arduino",
            "sublayer":         core,
            "board_id":         board_id,
            "name":             name,
            "vendor":           None,
            "mcu":              _str_or_none(build.get("mcu")),
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
            "vidpids":          _arduino_vidpids(b),
            "upstream_repo":    upstream,
            "upstream_blob":    upstream,
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
