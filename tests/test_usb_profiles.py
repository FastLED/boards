import json

import pytest

from builders.usb_profiles import build_profiles, normalize_vidpid, validate_profiles


def test_normalization_and_collision_preserve_provenance():
    artifact = build_profiles([
        {"board_id": "pico", "aliases": ["Pico2040"], "vidpids": [["0x2E8A", "000A"]], "upstream_blob": "pio.json"},
        {"board_id": "other-pico", "vidpids": [["2e8a", "a"]], "upstream_blob": "arduino.json"},
    ])
    assert normalize_vidpid("2E8A:000A") == "2e8a:000a"
    assert len(artifact["identities"]["2e8a:000a"]) == 4
    assert {x["provenance"] for x in artifact["identities"]["2e8a:000a"]} == {"pio.json", "arduino.json"}
    validate_profiles(artifact)


def test_curated_roles_aliases_and_determinism():
    boards = [{"board_id": "x", "aliases": ["z", "a"], "vidpids": ["303a:1001"]}]
    other = {"usb_profiles": [{"board_id": "x", "vidpid": "303a:0002", "role": "bootloader", "provenance": "curated#1"}]}
    a = build_profiles(boards, other)
    b = build_profiles(list(reversed(boards)), other)
    assert a == b
    assert a["boards"]["x"]["aliases"] == ["a", "z"]
    assert a["boards"]["x"]["identities"]["bootloader"] == ["303a:0002"]


def test_invalid_role_rejected():
    with pytest.raises(ValueError, match="invalid USB profile role"):
        build_profiles([], {"usb_profiles": [{"board_id": "x", "vidpid": "1:2", "role": "bogus"}]})


def test_validation_rejects_unknown_identity():
    with pytest.raises(ValueError):
        validate_profiles({"schema_version": 1, "metadata": {}, "identities": {}, "boards": {"x": {"identities": {"runtime": ["1:2"]}}}})
