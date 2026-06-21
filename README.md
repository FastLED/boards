# FastLED/boards — `arduino` branch

Parsed JSON form of boards.txt from upstream Arduino cores (AVR, SAMD, Espressif, Adafruit nRF52, STM32duino, Silicon Labs).

## Status

**Initialized, no data yet.** First push by `sync-arduino.yml` will replace
this README and `_meta.json` with the real synced data + provenance.

## How this branch is regenerated

This is an **orphan branch**. It carries no shared history with `main`.
Every nightly / manually-dispatched run of `.github/workflows/sync-arduino.yml`
on `main` produces a fresh complete snapshot of the data, then publishes
to this branch via `tools/git_publish.py` (force-with-lease, history pruned
to ~200 commits).

## Direct edits

Direct human pushes to this branch are blocked by repo branch-protection
rules. To change the data, edit the sync tool on `main` (`tools/sync_arduino.py`)
and re-run the workflow.

## See also

- [`main` branch README](https://github.com/FastLED/boards/tree/main) — repo overview
- [`main` branch design.md](https://github.com/FastLED/boards/blob/main/design.md) — full architecture
