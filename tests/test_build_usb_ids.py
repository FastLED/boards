from __future__ import annotations

import json
import sqlite3

from builders.build_usb_ids import dump_usb_ids, encode_usb_vids_proto


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        b = data[offset]
        offset += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, offset
        shift += 7


def _read_fields(data: bytes) -> list[tuple[int, int, bytes | int]]:
    fields: list[tuple[int, int, bytes | int]] = []
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        field = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
            fields.append((field, wire_type, value))
        elif wire_type == 2:
            size, offset = _read_varint(data, offset)
            payload = data[offset:offset + size]
            offset += size
            fields.append((field, wire_type, payload))
        else:
            raise AssertionError(f"unexpected wire type {wire_type}")
    return fields


def test_dump_usb_ids_is_compact_download_shape() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE vid_vendor (
          vid TEXT PRIMARY KEY,
          vendor TEXT NOT NULL,
          source TEXT NOT NULL
        );
        CREATE TABLE vidpid (
          vidpid TEXT NOT NULL,
          vid TEXT NOT NULL,
          pid TEXT NOT NULL,
          product TEXT NOT NULL,
          source TEXT NOT NULL,
          is_primary INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.executemany(
        "INSERT INTO vid_vendor (vid, vendor, source) VALUES (?, ?, ?)",
        [
            ("303a", "Espressif Systems", "test"),
            ("16c0", "PJRC", "test"),
        ],
    )
    conn.executemany(
        "INSERT INTO vidpid (vidpid, vid, pid, product, source, is_primary) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("303a1001", "303a", "1001", "USB JTAG/serial debug unit", "test", 1),
            ("303a0002", "303a", "0002", "ESP32-S2", "test", 1),
            ("16c00483", "16c0", "0483", "Teensy USB Serial", "test", 1),
        ],
    )

    result = dump_usb_ids(conn)
    conn.close()

    assert result == {
        "16c0": {
            "Vendor name": "PJRC",
            "PIDs": [{"0483": "Teensy USB Serial"}],
        },
        "303a": {
            "Vendor name": "Espressif Systems",
            "PIDs": [
                {"0002": "ESP32-S2"},
                {"1001": "USB JTAG/serial debug unit"},
            ],
        },
    }
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    assert "\n" not in encoded
    assert ": " not in encoded


def test_encode_usb_vids_proto_wire_shape() -> None:
    data = {
        "16c0": {
            "Vendor name": "PJRC",
            "PIDs": [{"0483": "Teensy USB Serial"}],
        },
        "303a": {
            "Vendor name": "Espressif Systems",
            "PIDs": [
                {"0002": "ESP32-S2"},
                {"1001": "USB JTAG/serial debug unit"},
            ],
        },
    }

    encoded = encode_usb_vids_proto(data)
    vendors = [payload for field, wire_type, payload in _read_fields(encoded)
               if field == 1 and wire_type == 2]

    decoded: list[tuple[int, str, list[tuple[int, str]]]] = []
    for vendor_payload in vendors:
        assert isinstance(vendor_payload, bytes)
        vendor_fields = _read_fields(vendor_payload)
        vid = next(value for field, _, value in vendor_fields if field == 1)
        name_raw = next(value for field, _, value in vendor_fields if field == 2)
        assert isinstance(vid, int)
        assert isinstance(name_raw, bytes)
        products = []
        for field, wire_type, product_payload in vendor_fields:
            if field != 3:
                continue
            assert wire_type == 2
            assert isinstance(product_payload, bytes)
            product_fields = _read_fields(product_payload)
            pid = next(value for product_field, _, value in product_fields
                       if product_field == 1)
            product_raw = next(value for product_field, _, value in product_fields
                               if product_field == 2)
            assert isinstance(pid, int)
            assert isinstance(product_raw, bytes)
            products.append((pid, product_raw.decode("utf-8")))
        decoded.append((vid, name_raw.decode("utf-8"), products))

    assert decoded == [
        (0x16C0, "PJRC", [(0x0483, "Teensy USB Serial")]),
        (
            0x303A,
            "Espressif Systems",
            [
                (0x0002, "ESP32-S2"),
                (0x1001, "USB JTAG/serial debug unit"),
            ],
        ),
    ]
