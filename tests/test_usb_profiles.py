import json

import pytest

from builders.usb_profiles import build_profiles, normalize_vidpid, validate_profiles


def test_normalization_and_collision_preserve_provenance():
    artifact = build_profiles([
        {"board_id": "pico", "aliases": "Pico2040, pico-alias", "vidpids": [["0x2E8A", "000A"]], "identity_purposes": {"2e8a:000a": ["runtime"]}, "upstream_blob": "pio.json"},
        {"board_id": "other-pico", "vidpids": [["2e8a", "a"]], "upstream_blob": "arduino.json"},
    ])
    assert normalize_vidpid("2E8A:000A") == "2e8a:000a"
    assert len(artifact["identities"]["2e8a:000a"]) == 3
    assert {x["provenance"]["source_url"] for x in artifact["identities"]["2e8a:000a"]} == {"pio.json", "arduino.json"}
    validate_profiles(artifact)


def test_curated_roles_aliases_and_determinism():
    boards = [{"board_id": "x", "aliases": ["z", "a"], "vidpids": ["303a:1001"]}]
    other = {"usb_profiles": [{"board_id": "x", "vidpid": "303a:0002", "role": "bootloader_uf2", "purpose": "bootloader", "reset": "touch-1200", "handoff": "bootloader", "provenance": {"source_url": "curated#1", "source_revision": "r1", "source_class": "other"}}]}
    a = build_profiles(boards, other)
    b = build_profiles(list(reversed(boards)), other)
    assert a == b
    assert a["boards"]["x"]["aliases"] == ["a", "z"]
    assert a["boards"]["x"]["identities"]["bootloader"] == ["303a:0002"]


def test_generic_bridge_identity_without_board():
    artifact = build_profiles([], {"usb_profiles": [{"vidpid": "1d50:6018", "role": "usb_uart_bridge", "purpose": "runtime", "reset": "touch-1200", "handoff": "reconnect", "provenance": {"source_url": "curated", "source_revision": "r1", "source_class": "other"}}]})
    assert "1d50:6018" in artifact["identities"]
    assert not artifact["boards"]


def test_invalid_role_rejected():
    with pytest.raises(ValueError, match="invalid USB profile role"):
        build_profiles([], {"usb_profiles": [{"board_id": "x", "vidpid": "1:2", "role": "bogus", "purpose": "runtime"}]})


def test_validation_rejects_unknown_identity():
    with pytest.raises(ValueError):
        validate_profiles({"schema_version": 1, "metadata": {}, "identities": {}, "boards": {"x": {"identities": {"runtime": ["1:2"]}}}})
