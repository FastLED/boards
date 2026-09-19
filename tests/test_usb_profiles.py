import pytest

from builders.usb_profiles import build_profiles, normalize_vidpid, validate_profiles


def test_normalization_and_collision_preserve_provenance():
    artifact = build_profiles([
        {"board_id": "pico", "layer": "platformio", "aliases": "Pico2040, pico-alias", "vidpids": [["0x2E8A", "000A"]], "identity_purposes": {"2e8a:000a": ["runtime"]}, "source_revision": "a"*40, "upstream_blob": "pio.json"},
        {"board_id": "other-pico", "layer": "arduino", "vidpids": [["2e8a", "a"]], "source_revision": "b"*40, "upstream_blob": "arduino.json"},
    ])
    assert normalize_vidpid("2E8A:000A") == "2e8a:000a"
    assert len(artifact["identities"]["2e8a:000a"]) == 3
    assert {x["provenance"]["source_url"] for x in artifact["identities"]["2e8a:000a"]} == {"pio.json", "arduino.json"}
    validate_profiles(artifact)


def test_curated_roles_aliases_and_determinism():
    boards = [{"board_id": "x", "aliases": ["z", "a"], "vidpids": ["303a:1001"], "primary_compile_identity": "303a:1001"}]
    other = {"usb_profiles": [{"board_id": "x", "aliases": ["x-with-headers", "a"], "vidpid": "303a:0002", "role": "bootloader_uf2", "purpose": "bootloader", "reset": "touch-1200", "handoff": "bootloader", "provenance": {"source_url": "curated#1", "source_revision": "c"*40, "source_class": "other"}}]}
    a = build_profiles(boards, other)
    b = build_profiles(list(reversed(boards)), other)
    assert a == b
    assert a["boards"]["x"]["aliases"] == ["a", "x-with-headers", "z"]
    assert a["boards"]["x"]["identities"]["bootloader"] == ["303a:0002"]
    assert a["boards"]["x"]["primary_compile_identity"] == "303a:1001"


def test_primary_compile_identity_must_reference_compile_role():
    artifact = build_profiles([{
        "board_id": "x",
        "vidpids": ["303a:1001"],
        "identity_purposes": {"303a:1001": ["runtime"]},
        "primary_compile_identity": "303a:1001",
        "source_revision": "f" * 40,
    }])
    with pytest.raises(ValueError, match="primary compile identity"):
        validate_profiles(artifact)


def test_platformio_primary_compile_identity_wins_independent_of_input_order():
    boards = [
        {"board_id": "x", "layer": "arduino", "aliases": ["arduino-x"], "vidpids": ["feed:0001"], "primary_compile_identity": "feed:0001", "source_revision": "a" * 40},
        {"board_id": "x", "layer": "platformio", "aliases": ["pio-x"], "vidpids": ["feed:0002"], "primary_compile_identity": "feed:0002", "source_revision": "b" * 40},
    ]
    forward = build_profiles(boards)
    reverse = build_profiles(list(reversed(boards)))
    assert forward == reverse
    assert forward["boards"]["x"]["primary_compile_identity"] == "feed:0002"
    assert forward["boards"]["x"]["aliases"] == ["arduino-x", "pio-x"]


def test_generic_bridge_identity_without_board():
    artifact = build_profiles([], {"usb_profiles": [{"vidpid": "1d50:6018", "role": "usb_uart_bridge", "purpose": "runtime", "reset": "touch-1200", "handoff": "reconnect", "provenance": {"source_url": "curated", "source_revision": "d"*40, "source_class": "other"}}]})
    assert "1d50:6018" in artifact["identities"]
    assert not artifact["boards"]


def test_invalid_role_rejected():
    with pytest.raises(ValueError, match="invalid USB profile role"):
        build_profiles([], {"usb_profiles": [{"board_id": "x", "vidpid": "1:2", "role": "bogus", "purpose": "runtime"}]})


def test_validation_rejects_unknown_identity():
    with pytest.raises(ValueError):
        validate_profiles({"schema_version": 1, "metadata": {}, "identities": {}, "boards": {"x": {"identities": {"runtime": ["1:2"]}}}})


def test_validation_rejects_tampered_transport_and_match():
    artifact = build_profiles([{"board_id": "x", "vidpids": ["1:2"], "source_revision": "e"*40}])
    entry = artifact["identities"]["0001:0002"][0]
    entry["transport"] = "bogus"
    with pytest.raises(ValueError):
        validate_profiles(artifact)
