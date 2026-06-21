# FastLED/boards — `other` branch

Layer-4 of the merge pipeline. Carries the **override** file
(`overrides.json`) plus ad-hoc flat-record JSON files for sources that
don't fit the platformio / arduino / vendors source classes (udev rules,
esptool VID tables, manually-curated chip-vendor lookups, web-scrape
outputs).

## File reference

| File | Role | Read by |
|---|---|---|
| `overrides.json` | Layer-4 **overrides**: VID-vendor + VIDPID-product replacements that UNCONDITIONALLY win over earlier layers (no warnings/error logged). | `builders/extract_other.py` |
| `teensy_pids.json` | Curated flat-record table of every PJRC Teensy USB mode (17 modes) + 2 bootloader PIDs + the NXP IMXRT 1062 serial-download recovery PID. | `builders/extract_other.py` (flat-record path) |

## `overrides.json`

Read by `builders/extract_other.py` on `main`. Entries listed under
`vid_overrides` / `vidpid_overrides` UNCONDITIONALLY replace whatever
earlier layers said about that VID / VIDPID — without generating a
`warnings/` log entry.

### Current overrides

| Key | Replacement | Why |
| --- | --- | --- |
| `16c0` -> `PJRC (Teensy)` | re-attribute VOTI's sub-allocated VID | The registered owner of 0x16C0 is Van Ooijen Technische Informatica (VOTI); PJRC uses it for the Teensy family. In an embedded-board context the recognizable brand is PJRC/Teensy. |

## `teensy_pids.json`

A flat-record JSON list (the shape `extract_other.py` accepts for ad-hoc
records). Each entry carries `vid`, optional `pid`, optional `vendor`,
optional `product`, and a `_source` field documenting which primary
source each value was lifted from.

The headline insight encoded here is that **the PID is determined by
USB mode, not chip variant** — Teensy 4.0 / 3.5 / 3.2 all enumerate as
`0x16C0:0x0483` when configured for Serial, all as `0x16C0:0x0482` for
HID-only, etc. To distinguish chip variants you must read the USB
Product String (bcdDevice / iProduct).

Primary sources:
- `PaulStoffregen/cores/teensy4/usb_desc.h` (USB-mode PIDs)
- `PaulStoffregen/teensy_loader_cli/teensy_loader_cli.c` (bootloader PIDs)
- `adafruit/tinyuf2/ports/mimxrt10xx/Makefile` (NXP IMXRT 1062 SDP PID, cross-confirmed by phoenix-rtos and pyMBoot)
- `https://www.pjrc.com/teensy/00-teensy.rules` (the wildcard udev rule that confirms the `1fc9:013*` and `16c0:04*` ranges)

## Direct edits

This branch is bot-pushed for the orphan-commit invariant, AND
human-editable for the curated files (`overrides.json`,
`teensy_pids.json`, future ad-hoc records). The override list and curated
records are not sync output — they're curation.
