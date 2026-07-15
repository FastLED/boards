"""Build the versioned semantic USB transport profile artifact.

The artifact is deliberately independent of the legacy usb-ids JSON and
protobuf files: those files keep their wire shape while this adds roles and
board relationships for fbuild's resolver.
"""
from __future__ import annotations

import json
import hashlib
from typing import Any, Iterable

SCHEMA_VERSION = 1
ROLES = {"compile", "runtime", "bootloader", "probe"}
PURPOSES = ROLES
DEVICE_ROLES = {"runtime_cdc", "usb_uart_bridge", "bootloader_msc", "bootloader_hid", "bootloader_dfu", "bootloader_uf2", "debug_probe", "recovery_transport"}
RESETS = {None, "touch-1200", "hardware", "software", "manual"}
HANDOFFS = {None, "reconnect", "reset", "bootloader", "none"}


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


def normalize_match(value: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        vid = normalize_vidpid(f"{value.get('vid', '')}:0").split(":")[0]
        pid = value.get("pid")
        mask = value.get("pid_mask")
        if pid in (None, "", "*"):
            return f"{vid}:*", {"vid": vid, "pid": None, "pid_mask": mask}
        key = normalize_vidpid(f"{vid}:{pid}")
        return key, {"vid": vid, "pid": key.split(":")[1], "pid_mask": mask}
    if isinstance(value, str) and value.endswith(":*"):
        vid = normalize_vidpid(value[:-2] + ":0").split(":")[0]
        return f"{vid}:*", {"vid": vid, "pid": None, "pid_mask": None}
    key = normalize_vidpid(value)
    vid, pid = key.split(":")
    return key, {"vid": vid, "pid": pid, "pid_mask": None}


def _pairs(values: Any) -> Iterable[str]:
    if not values:
        return ()
    if isinstance(values, (str, tuple)):
        values = [values]
    return (normalize_vidpid(v) for v in values)


def _profile_record(board: dict[str, Any], key: str, purpose: str, source: Any) -> dict[str, Any]:
    if purpose not in PURPOSES:
        raise ValueError(f"invalid USB profile purpose {purpose!r}")
    role = board.get("role") or {"runtime": "runtime_cdc", "compile": "runtime_cdc", "bootloader": "bootloader_uf2", "probe": "debug_probe"}[purpose]
    if role not in DEVICE_ROLES:
        raise ValueError(f"invalid USB profile role {role!r}")
    reset = board.get("reset", "unknown")
    handoff = board.get("handoff", "unknown")
    if reset not in RESETS | {"unknown"} or handoff not in HANDOFFS | {"unknown"}:
        raise ValueError("invalid USB reset or handoff")
    if role != "runtime_cdc" and (reset == "unknown" or handoff == "unknown"):
        raise ValueError("curated deploy role requires reset and handoff")
    if not isinstance(source, dict):
        source = {"source_url": str(source), "source_revision": None, "source_class": "upstream"}
    return {
        "match": board.get("match") or {"vid": key.split(":")[0], "pid": key.split(":")[1] if ":" in key and key.split(":")[1] != "*" else None, "pid_mask": None},
        "purpose": purpose,
        "role": role,
        "transport": str(board.get("transport", "usb")),
        "reset": reset,
        "handoff": handoff,
        "platform": board.get("platform") or board.get("core"),
        "family": board.get("family") or board.get("mcu"),
        "generation": board.get("generation"),
        "interface": board.get("interface"),
        "provenance": source,
        "priority": int(board.get("priority", 0)),
        "allow_ambiguous": bool(board.get("allow_ambiguous", source.get("source_class") == "upstream" if isinstance(source, dict) else False)),
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
        source = {"source_url": board.get("upstream_blob"), "source_revision": board.get("source_revision"), "source_class": board.get("layer", "upstream")}
        purposes = board.get("identity_purposes") or {}
        for vp in _pairs(board.get("vidpids")):
            key_purposes = purposes.get(vp, ["runtime", "compile"])
            for purpose in key_purposes:
                add(board_id, vp, purpose, board, source)
        profile = board_profiles.setdefault(board_id, {"identities": {r: [] for r in PURPOSES}, "aliases": []})
        aliases = board.get("aliases") or []
        if isinstance(aliases, str):
            aliases = aliases.split(",")
        profile["aliases"] = sorted({str(x) for x in aliases if str(x).strip()})

    # Curated special-role records are accepted from the `other` layer.  They
    # are additive, so collisions/alternates remain visible in identities.
    records = (other or {}).get("usb_profiles", []) if isinstance(other, dict) else []
    for rec in records:
        board_id = str(rec.get("board_id", "")).strip() or None
        source = rec.get("provenance") or {"source_url": rec.get("source_url"), "source_revision": rec.get("source_revision"), "source_class": "other"}
        purpose = rec.get("purpose", "runtime")
        for raw in (rec.get("vidpids") or [rec.get("vidpid")]):
            key, match = normalize_match(raw)
            rec = dict(rec); rec["match"] = match
            vp = key
            if board_id:
                add(board_id, vp, purpose, rec, source)
            else:
                # Generic bridge/probe identities remain addressable even
                # without a board profile.
                item = _profile_record(rec, vp, purpose, source)
                identities.setdefault(vp, []).append(item)

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
        if normalize_match(key)[0] != key or not isinstance(entries, list):
            raise ValueError(f"invalid identity key {key!r}")
        for entry in entries:
            if entry.get("purpose") not in PURPOSES or entry.get("role") not in DEVICE_ROLES or not isinstance(entry.get("provenance"), dict):
                raise ValueError("identity requires a valid role and provenance")
            if entry.get("priority") is None:
                raise ValueError("identity requires priority")
        priorities = [(e.get("priority"), e.get("purpose"), e.get("role")) for e in entries]
        if len(priorities) != len(set(priorities)) and not any(e.get("allow_ambiguous") for e in entries):
            raise ValueError(f"ambiguous identity records for {key}")
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


def artifact_sha256(artifact: dict[str, Any]) -> str:
    raw = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()
