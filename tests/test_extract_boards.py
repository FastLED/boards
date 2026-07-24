"""PlatformIO extractor: compile-identity derivation from board manifests.

Regression coverage for the hwids-only manifests (atmelsam et al.):
PlatformIO's platform builders fall back to `build.hwids[0]` for
USB_VID/USB_PID when a manifest has no explicit `build.vid`/`build.pid`,
so the extractor must publish that pair as the primary compile identity.
Before this fix every hwids-only board shipped
`primary_compile_identity: null`, which broke consumers that source
USB_VID/USB_PID from the registry (FastLED/fbuild#1061 → SAMD CI breakage).
"""
import json
import pathlib

from builders.extract_boards import _extract_platformio
from builders.usb_profiles import build_profiles, validate_profiles


def _write_board(root: pathlib.Path, plat: str, board_id: str, payload: dict) -> None:
    boards_dir = root / plat / "boards"
    boards_dir.mkdir(parents=True, exist_ok=True)
    (boards_dir / f"{board_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_hwids_only_manifest_gains_compile_identity(tmp_path):
    _write_board(tmp_path, "atmelsam", "feather_like", {
        "name": "Feather-like M0",
        "build": {
            "mcu": "samd21g18a",
            "hwids": [["0x239A", "0x800B"], ["0x239A", "0x000B"]],
        },
    })
    records = _extract_platformio(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["primary_compile_identity"] == "239a:800b"
    assert record["identity_purposes"]["239a:800b"] == ["runtime", "compile"]
    # Secondary hwids stay runtime-only.
    assert record["identity_purposes"]["239a:000b"] == ["runtime"]

    # The site pipeline stamps each record with the data-branch commit
    # before profile assembly; emulate that so the validator accepts it.
    record["source_revision"] = "a" * 40
    artifact = build_profiles(records)
    validate_profiles(artifact)
    assert artifact["boards"]["feather_like"]["primary_compile_identity"] == "239a:800b"


def test_explicit_vid_pid_still_wins_over_hwids(tmp_path):
    _write_board(tmp_path, "raspberrypi", "pico_like", {
        "name": "Pico-like",
        "build": {
            "mcu": "rp2040",
            "vid": "0x2E8A",
            "pid": "0x000A",
            "hwids": [["0x2E8A", "0x0003"]],
        },
    })
    records = _extract_platformio(tmp_path)
    assert records[0]["primary_compile_identity"] == "2e8a:000a"


def test_manifest_without_any_usb_identity_stays_null(tmp_path):
    _write_board(tmp_path, "atmelavr", "bare_mcu", {
        "name": "Bare MCU",
        "build": {"mcu": "atmega328p"},
    })
    records = _extract_platformio(tmp_path)
    assert records[0]["primary_compile_identity"] is None
    assert records[0]["vidpids"] == []
