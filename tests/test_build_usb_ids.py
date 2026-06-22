from __future__ import annotations

import json
import sqlite3

from builders.build_usb_ids import dump_usb_ids


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
