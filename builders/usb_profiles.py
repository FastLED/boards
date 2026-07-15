"""Build the versioned semantic USB transport profile artifact.

The artifact is deliberately independent of the legacy usb-ids JSON and
protobuf files: those files keep their wire shape while this adds roles and
board relationships for fbuild's resolver.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

SCHEMA_VERSION = 1
ROLES = {"compile", "runtime", "bootloader", "probe"}
PURPOSES = ROLES


def normalize_vidpid(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        value = f"{value[0]}:{value[1]}"
    if not isinstance(value, str) or ":" not in value:
        raise ValueError(f"invalid VID:PID {value!r}")
    vid, pid = (x.strip().lower().removeprefix("0x") for x in value.split(":", 1))
    if not (1 <= len(vid) <= 4 and 1 <= len(pid) <= 4):
        raise ValueError(f"invalid VID:PID {value!r}")
    try:
        vid_i, pid_i = int(vid, 16), int(pid, 16)
    except ValueError as exc:
        raise ValueError(f"invalid VID:PID {value!r}") from exc
    return f"{vid_i:04x}:{pid_i:04x}"


def _pairs(values: Any) -> Iterable[str]:
    if not values:
        return ()
    if isinstance(values, (str, tuple)):
        values = [values]
    return (normalize_vidpid(v) for v in values)


def _profile_record(board: dict[str, Any], key: str, role: str, source: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ValueError(f"invalid USB profile role {role!r}")
    return {
        "role": role,
        "transport": str(board.get("transport", "usb")),
        "reset": board.get("reset"),
        "handoff": board.get("handoff"),
        "platform": board.get("platform") or board.get("core"),
        "family": board.get("family") or board.get("mcu"),
        "generation": board.get("generation"),
        "interface": board.get("interface"),
        "provenance": source,
    }


def build_profiles(boards: list[dict[str, Any]], other: Any = None) -> dict[str, Any]:
    identities: dict[str, list[dict[str, Any]]] = {}
    board_profiles: dict[str, dict[str, Any]] = {}

    def add(board_id: str, vp: str, role: str, record: dict[str, Any], source: str) -> None:
        item = _profile_record(record, vp, role, source)
        identities.setdefault(vp, []).append(item)
        profile = board_profiles.setdefault(board_id, {"identities": {r: [] for r in PURPOSES}, "aliases": []})
        if vp not in profile["identities"][role]:
            profile["identities"][role].append(vp)

    for board in boards:
        board_id = str(board.get("board_id", "")).strip()
        if not board_id:
            continue
        source = str(board.get("upstream_blob") or board.get("source") or board.get("layer", "upstream"))
        for vp in _pairs(board.get("vidpids")):
            for role in (board.get("roles") or ["runtime", "compile"]):
                add(board_id, vp, role, board, source)
        profile = board_profiles.setdefault(board_id, {"identities": {r: [] for r in PURPOSES}, "aliases": []})
        aliases = board.get("aliases") or []
        profile["aliases"] = sorted({str(x) for x in aliases if str(x).strip()})

    # Curated special-role records are accepted from the `other` layer.  They
    # are additive, so collisions/alternates remain visible in identities.
    records = (other or {}).get("usb_profiles", []) if isinstance(other, dict) else []
    for rec in records:
        board_id = str(rec.get("board_id", "")).strip()
        if not board_id:
            continue
        source = str(rec.get("provenance") or rec.get("source") or "other")
        role = rec.get("role", "runtime")
        for vp in _pairs(rec.get("vidpids") or rec.get("vidpid")):
            add(board_id, vp, role, rec, source)

    for entries in identities.values():
        entries.sort(key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")))
    for profile in board_profiles.values():
        for role in PURPOSES:
            profile["identities"][role].sort()
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "artifact": "usb-transport-profiles",
            "compatibility": {"usb_ids": "usb-ids.json", "protobuf": "usb-vids.proto.zstd"},
        },
        "identities": dict(sorted(identities.items())),
        "boards": dict(sorted(board_profiles.items())),
    }


def validate_profiles(artifact: dict[str, Any]) -> None:
    if artifact.get("schema_version") != SCHEMA_VERSION or not isinstance(artifact.get("metadata"), dict):
        raise ValueError("invalid USB profile schema metadata")
    for key, entries in artifact.get("identities", {}).items():
        if normalize_vidpid(key) != key or not isinstance(entries, list):
            raise ValueError(f"invalid identity key {key!r}")
        for entry in entries:
            if entry.get("role") not in ROLES or not entry.get("provenance"):
                raise ValueError("identity requires a valid role and provenance")
    for board_id, profile in artifact.get("boards", {}).items():
        if not board_id or not isinstance(profile.get("identities"), dict):
            raise ValueError(f"invalid board profile {board_id!r}")
        for role, keys in profile["identities"].items():
            if role not in PURPOSES:
                raise ValueError(f"invalid board purpose {role!r}")
            for key in keys:
                if key not in artifact["identities"]:
                    raise ValueError(f"board references unknown identity {key}")


def write_profiles(boards: list[dict[str, Any]], other: Any, output) -> dict[str, Any]:
    artifact = build_profiles(boards, other)
    validate_profiles(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return artifact
