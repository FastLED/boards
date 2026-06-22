# FastLED/boards

Slim, machine-readable registry of embedded board definitions + USB VID:PID
mappings, aggregated from PlatformIO, Arduino cores, vendor allocation
registries, and curated overlays. Source of truth for fbuild's USB resolver
and the public boards portal.

Currently **private**; may go public once the curation pipeline + public
portal are stable.

## 🔎 Live portal — **<https://fastled.github.io/boards/>**

Public query UI (works even though this repo is private — the `site`
branch is published via GitHub Pages from a Team-plan account). Searchable
by VID, VID:PID, vendor-name fragment, or product-name fragment. Backed
by `boards.db` (SQLite over HTTP, served alongside `index.html`).

| Endpoint | URL |
|---|---|
| Demo query UI                       | <https://fastled.github.io/boards/> |
| Raw SQLite database                 | <https://fastled.github.io/boards/boards.db> |
| Compact USB VID:PID download JSON   | <https://fastled.github.io/boards/usb-ids.json> |
| Build provenance + counts (`_meta`) | <https://fastled.github.io/boards/_meta.json> |
| Severity-bucketed warnings folder   | <https://fastled.github.io/boards/warnings/> |

Quick examples to try in the portal:
- VID box: `303a` → Espressif Systems
- VID box: `16c0` → PJRC (Teensy)  *(re-attribution via `other` branch override)*
- VID:PID box: `303a:1001` → primary board + 36 alternates (genuine PID collision)
- VID:PID box: `16c0:0483` → Teensy 4.0
- Product-name fragment: `teensy` → all Teensy entries

## What's in here

The repo has a strict split: code on `main`, data on orphan branches.

### `main` — control center

Holds **all** workflows, tools, vendored dependencies, tests, and
documentation. No data files. Every sync job and every site rebuild reads
its code from `main` regardless of which data branch it's writing.

```
.github/workflows/
  sync-platformio.yml        # → writes platformio branch
  sync-arduino.yml           # → writes arduino branch
  sync-vendors.yml           # → writes vendors branch
  sync-other.yml             # → writes other branch
  build-site.yml             # → writes site branch (triggers: push + nightly + dispatch)

tools/
  sync_platformio.py         # walks platformio/platform-*/boards/*.json
  sync_arduino.py            # parses upstream Arduino-core boards.txt files
  sync_vendors.py            # pulls Espressif/RaspberryPi allocation registries
  sync_other.py              # scrapes udev rules, esptool tables, gowdy.us
  build_site.py              # aggregates all 4 data branches → sqlite + html + json
  sanity_gates.py            # row-count / schema / diff-size guards
  git_publish.py             # centralised commit + history-prune + push + last-good-* tag
  vendored/                  # pinned arduino-cli binaries; platformio wheels via uv lockfile

tests/                       # standard pytest suite, runs on every PR to main
README.md                    # this file
design.md                    # full architectural design — read this before changing anything
```

### Data branches (orphan, bot-pushed only)

| Branch | What it carries | Refresh trigger |
|---|---|---|
| `platformio` | Slim mirror of `boards/*.json` + `platform.json` from the 37 PlatformIO `platform-*` repos (Apache-2.0). | `workflow_dispatch` (manual for v1; nightly cron later) |
| `arduino` | Parsed JSON form of `boards.txt` from upstream Arduino cores (Arduino AVR, SAMD, Espressif Arduino, Adafruit nRF52, STM32duino, Silicon Labs, …). | `workflow_dispatch` |
| `vendors` | Authoritative PID allocation registries: `raspberrypi/usb-pid`, `espressif/usb-pids`, our curated `vendor_names_inlined` overlay. | `workflow_dispatch` |
| `other` | Heterogeneous: udev rules, esptool VID tables, gowdy.us scrapes, anything that doesn't fit a clean upstream category. | `workflow_dispatch` |

Each carries a top-level `_meta.json` recording every source URL, upstream
commit SHA, sync timestamp, and license — provenance is part of the data.

### `site` — public-facing aggregate (history-pruned)

Built by `build-site.yml` whenever any data branch is pushed (and as a
24-hour heartbeat). Carries the merged SQLite database, the static-site
front-end (sql.js portal, fuzzy search, canned queries), and a flat
`aggregate.json` for direct consumers. History is pruned to the last ~10
commits since the database blobs are large.

This branch is published as the public portal even though the repo itself
is private. See `design.md` for the publishing mechanism.

### `staging-*` — optional safety-net branches (deferred)

Pattern reserved for when a sync workflow needs to land changes for human
inspection before promoting to the real data branch. Not used in v1; see
`design.md` § "Staging + promote".

## How to use the data

### From `fbuild`

fbuild's `online-data` workflow consumes this repo's `site` branch as its
upstream USB-vendor + board catalogue. Per-board metadata can also be
embedded directly into a user's sketch as a `platformio.lock`-style file
since the JSON is ~1–4 KB per board (reproducible, offline-buildable).

### From the public site

Browse the published portal at <https://fastled.github.io/boards/>. It
exposes:

- VID → vendor name lookup
- VID:PID → product / board name reverse lookup (primary + all alternates)
- Vendor-name fragment → matching VIDs (fuzzy)
- Product-name fragment → matching VID:PIDs (fuzzy)

The portal loads `boards.db` once via `fetch()`, then runs every query
client-side in sql.js (WASM). Zero server, fully cacheable.

### From curl / scripts

Once branches exist, raw JSON is available via:

```
https://raw.githubusercontent.com/FastLED/boards/<branch>/<path>
```

(While the repo is private, raw URLs require an authenticated token. The
public portal is the recommended path for unauthenticated consumers.)

## Filing issues

Curation issues, missing boards, wrong VID:PID mappings → file under
[FastLED/fbuild](https://github.com/FastLED/fbuild) issues for now; the
repo will get its own tracker once it goes public.

## License

The repo itself is unlicensed (private). Upstream data is mirrored under
its original licenses — see each data branch's `_meta.json` for
per-source license attribution. Aggregate output published to `site` is
intended to land under MIT once the repo is public.
