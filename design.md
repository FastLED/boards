# FastLED/boards — Design

The architectural decisions behind the layout described in `README.md`.
Read this before changing the branch topology, the workflow set, or the
safety machinery.

## Problem statement

fbuild needs to answer two questions, fast and reliably, for any
embedded board a user plugs in:

1. **VID:PID → "what is this device?"** (vendor name + likely board)
2. **Board name → VID:PID(s) it will enumerate as** (so we can connect on
   the first shot without scanning every port)

The upstream sources for this data are fragmented and uneven:

- **PlatformIO** has rich per-board JSON for ~1500 boards (mirrored from
  Arduino cores by hand by their maintainer) but only ~22% of entries
  carry `build.hwids`.
- **Arduino cores** carry the original `boards.txt` files PIO mirrors;
  authoritative but per-vendor format drift.
- **Vendor PID allocation registries** (Raspberry Pi `usb-pid`, Espressif
  `usb-pids`) are the gold standard but only exist for 2 vendors.
- **Public usb.ids databases** (linux-usb.org, Fedora hwdata, Rust
  `usb-ids` crate) don't yet carry many newer VIDs (notably 0x303A
  Espressif and 0x2E8A Raspberry Pi).
- **Everything else** lives in udev rules, esptool source, datasheets,
  scraped registration pages (`usb-ids.gowdy.us`).

The fbuild repo's `online-data` orphan branch was the v1 aggregator. It
worked, but the curation pipeline outgrew "a few scripts in one
workflow" — hence this dedicated registry repo.

## Architecture overview

```
                       ┌─────────────────────────────────────────┐
                       │  FastLED/boards (private)              │
                       └─────────────────────────────────────────┘
                                       │
       ┌──────────┬───────────────┬────┴────────┬──────────────────────────┐
       ▼          ▼               ▼             ▼                          ▼
   ┌────────┐ ┌──────────┐ ┌────────────┐ ┌─────────┐ ┌────────────────────────┐
   │  main  │ │platformio│ │  arduino   │ │ vendors │ │ other                  │
   │workflows│ │(orphan)  │ │(orphan)   │ │(orphan) │ │ (orphan)               │
   │+ tools │ │boards/   │ │boards/    │ │PID      │ │ udev/esptool/scrape    │
   │+ tests │ │+platform │ │as JSON    │ │registries│ │                        │
   └────────┘ └──────────┘ └────────────┘ └─────────┘ └────────────────────────┘
                   │            │              │                 │
                   └────────────┴──────┬───────┴─────────────────┘
                                       │ push to any → triggers build-site
                                       │ + nightly cron at 04:30 UTC
                                       │ + workflow_dispatch (human override)
                                       ▼
                                ┌───────────────┐
                                │ build-site    │ concurrency: build-site,
                                │   workflow    │ cancel-in-progress: false
                                └───────┬───────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │   site (orphan)     │  history-pruned to ~10 commits
                              │   • aggregate.db    │
                              │   • aggregate.json  │
                              │   • index.html + js │
                              │   • _meta.json      │
                              └──────────┬──────────┘
                                         │ (Pages / Cloudflare / Vercel)
                                         ▼
                                 public boards portal
                                         │
                          fbuild ◀───────┴───────▶ humans / curl / sql.js
```

## Decision: tools + workflows on `main`, data on orphan branches

Hard rule: every workflow file and every sync tool lives on `main`. Data
branches are orphan and carry **only** output data + `_meta.json`. No
`.github/`, no `.py`, no `LICENSE` (license attribution lives in
`_meta.json`).

### Why

1. **`schedule:` and `workflow_dispatch:` triggers must live on the
   default branch** — GitHub Actions enforces this. So at least the
   scheduled and manually-dispatched workflows have to be on `main`. Once
   most workflows have to be on `main`, putting any of them elsewhere
   creates a confusing split.
2. **One source of truth for tooling.** Fix a bug in `sync_platformio.py`
   once, on `main`, via PR review. With per-branch tooling you fix 4-5
   copies separately and they drift.
3. **Code review happens on `main`.** PRs to `main` get reviewed. Data
   branches are bot-pushed and skip review (data, not code). This is the
   right shape.
4. **Onboarding is obvious.** Clone `main`, read `.github/workflows/`,
   read `tools/`, you understand the whole system. Nobody needs to
   discover that the code lives on an orphan branch.
5. **Tests run on `main` like a normal repo.** No special CI shape for
   the data-generation logic.
6. **Vendored dependencies are pinned once** in `tools/vendored/` and
   `tools/requirements.txt`. All workflows use the same pinned versions.

### Workflow execution shape

Every sync workflow follows the same pattern:

```yaml
# .github/workflows/sync-platformio.yml
on:
  workflow_dispatch: {}   # manual for v1; add `schedule:` later

permissions:
  contents: write

concurrency:
  group: sync-platformio
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4   # main, where the tools live
      - uses: astral-sh/setup-uv@v3
      - name: Worktree the platformio branch
        run: |
          if git ls-remote --heads origin platformio | grep -q .; then
            git fetch origin platformio:platformio
            git worktree add .data platformio
          else
            git worktree add --detach .data
            (cd .data && git checkout --orphan platformio && git rm -rf .)
          fi
      - name: Sync
        run: uv run tools/sync_platformio.py --out .data/
      - name: Sanity gates + publish
        run: |
          uv run tools/sanity_gates.py --branch platformio --worktree .data/
          uv run tools/git_publish.py --worktree .data/ --branch platformio \
            --message "chore(platformio): sync from upstream"
```

Same shape for `sync-arduino.yml`, `sync-vendors.yml`, `sync-other.yml`.
`build-site.yml` worktree's all 4 data branches plus the site branch and
runs `build_site.py`.

## Decision: 4 data branches, by source class

`platformio`, `arduino`, `vendors`, `other`. Not "one branch per
vendor" (would be ~30 branches), not "one branch for everything" (loses
the per-source debuggability).

### Why these four

1. **`platformio`** — single coherent upstream (the platformio org's 37
   `platform-*` repos), uniform JSON schema, one parser.
2. **`arduino`** — N upstreams (Arduino AVR / SAMD / Espressif Arduino /
   Adafruit nRF52 / STM32duino / Silicon Labs Arduino) but all sharing
   the `boards.txt` format. One parser, N source URLs.
3. **`vendors`** — vendor-published PID allocation registries
   (`raspberrypi/usb-pid`, `espressif/usb-pids`) + our curated
   `vendor_names_inlined` overlay. Authoritative but small.
4. **`other`** — the eclectic catch-all: udev rules, esptool tables,
   gowdy.us scrapes, anything that doesn't fit. Lives separately so the
   noise from this branch doesh't muddy the cleaner three.

Adding a 5th class (e.g. `zephyr` for the Zephyr `board.yml` corpus) is
a single follow-up: new sync workflow, new branch, add the branch name
to `build-site.yml`'s `push:` trigger list, add an ingest path in
`build_site.py`. No central rewrite.

## Decision: single `build-site.yml` with three triggers

```yaml
on:
  # Fast path — rebuild within minutes of any data-branch push.
  push:
    branches: [platformio, arduino, vendors, other]
  # 24-hour backstop — catches missed push triggers, token expiries,
  # GH outages, anti-recursion quirks. No-ops when nothing changed.
  schedule:
    - cron: "30 4 * * *"   # 04:30 UTC, off-peak
  # Human override — "rebuild now regardless".
  workflow_dispatch: {}

concurrency:
  group: build-site
  cancel-in-progress: false
```

### Why all three

| Trigger | Role | Worst-case site staleness if this is the ONLY trigger |
|---|---|---|
| `push:` on data branches | Optimistic fast path | Unbounded if trigger silently fails |
| `schedule:` nightly | Backstop / heartbeat | Up to 24 h after a data push |
| `workflow_dispatch:` | Emergency human override | n/a |

Combined: **minutes typically; 24 h ceiling guaranteed.** Belt and
suspenders.

Git's built-in "no commit on empty diff" handles the "did anything
change?" question for free — the nightly run is a pure no-op when
inputs are unchanged. No conditional logic needed.

## Decision: centralise the safety machinery

A bad push to a data branch doesn't just lose data — it propagates to
the site builder, which propagates to fbuild consumers downstream. One
centralised place to enforce sanity beats N workflows each reinventing
it.

### Layers, from outermost to innermost

| Layer | Lives in | Defends against |
|---|---|---|
| **Branch protection** (Settings → Branches) | Repo admin | Direct human pushes / typo'd `git push --force` from a checkout |
| **Push-gate sanity checks** | `tools/sanity_gates.py` | Workflow bug producing a truncated / empty dataset |
| **Schema validators** | `tools/schemas/*.json` + `tools/validate.py` | Workflow drift producing malformed JSON |
| **Diff-size circuit breaker** | inside `sanity_gates.py` | A bug that wipes 90 % of rows silently |
| **`last-good-*` ref tags** | `tools/git_publish.py` | Rollback target — one ref points to the last sane state per branch |
| **Atomic publish** (commit then check then push) | `tools/git_publish.py` | Race conditions, partial-write failures |
| **History prune policy** | `tools/git_publish.py` (HISTORY_LIMIT constant) | Repo growing without bound |
| **Bot identity + commit format** | `tools/git_publish.py` | Drift in commit-message conventions; easy to filter bot vs human in git log |
| **Notifications** | `tools/notify.py` (Slack / auto-create issue) | One config for "where does failure go?" |
| **Dry-run toggle** | env `DRY_RUN=1` honoured by every sync tool | Verify a workflow without touching the real branch |

### Sanity gates per branch

`tools/sanity_gates.py` carries one tunable table:

```python
THRESHOLDS = {
    "platformio": {"min_boards": 1400, "max_diff_pct": 0.10},
    "arduino":    {"min_boards":  500, "max_diff_pct": 0.15},
    "vendors":    {"min_pids":    400, "max_diff_pct": 0.20},
    "other":      {"min_rows":    100, "max_diff_pct": 0.30},
}
```

If the new build's row count is below threshold OR the diff vs
`last-good-<branch>` exceeds `max_diff_pct`, the gate refuses the
publish, opens a GitHub issue, and exits non-zero. The previous good
state remains on the branch.

### `last-good-*` tags

After every successful publish, `git_publish.py` advances
`last-good-<branch>` to the new HEAD. Rollback is a single command:

```bash
git push origin last-good-platformio:platformio --force
```

The site builder also pins which source SHAs it built from in
`site/_meta.json`, so "site looks weird since yesterday" → diff
`_meta.json` between commits → spot the source that changed → bisect
just that one branch.

### Branch protection rules (apply via repo Settings → Branches)

| Branch | Allowed pushers | Other rules |
|---|---|---|
| `main` | humans via PR only | require 1 approving review, status checks pass, linear history |
| `platformio`, `arduino`, `vendors`, `other` | the matching `sync-*` workflow only (via deploy key or bot PAT) | allow force-push (history prune); block direct PRs |
| `site` | `build-site.yml` only | allow force-push; history-prune-friendly |

The deploy-key / PAT scope matters: scope the key so it can only push to
its assigned branch. A fully-compromised `sync-platformio.yml` can only
corrupt the `platformio` branch, not site or other data branches.

### Staging + promote (deferred to v2)

A stronger pattern: each `sync-*.yml` writes to `staging-<branch>`, a
matching `promote-*.yml` runs sanity gates, and only on success
fast-forwards `<branch>` to `staging-<branch>`. Doubles the orphan-branch
count (4 → 8) and adds 4 promote workflows. Worth doing if v1's inline
gates ever miss a bad commit; deferred until then.

## Decision: vendored / pinned tool versions

We do not want a PyPI outage or an Arduino-CLI release-page hiccup
breaking the curation pipeline.

| Tool | Pin strategy |
|---|---|
| `platformio` | `uv tool install platformio==X.Y.Z` with GitHub Actions cache layer. Lockfile in `tools/uv.lock` pins the exact wheel set. Migrate to vendored wheels if PyPI bites. |
| `arduino-cli` | Mirror the exact pinned version's release binaries (Go static binary, per-OS) as assets on a GitHub Release on `FastLED/boards` itself. Install step does `gh release download v1.0 -p '*-{os}.tar.gz'` + SHA-256 verify. Self-hosted, version-pinned. |
| `zstd`, `tar` | Runner-provided on GitHub-hosted Ubuntu; no pin needed. |
| `python` | Pinned via `uv` (`requires-python` in script headers). |

`tools/vendored/` carries the `arduino-cli` binaries when they're
checked in, plus checksums; `tools/requirements.txt` and `tools/uv.lock`
carry the Python pins.

## Decision: public Pages from a private repo

Site branch publishes via one of:

1. **GitHub Pages from a private repo** — requires GitHub Pro/Team plan.
   If FastLED org is already on Team, zero friction.
2. **Cloudflare Pages / Vercel deploy** — builds from the `site` branch
   of the private repo (their integrations handle the auth). Free for
   public sites with reasonable bandwidth limits.
3. **Mirror to a public sibling repo** — `FastLED/boards-site` is
   public, mirrors only the `site` branch's contents. Curation engine
   stays private; published artifact is explicitly public.

Decision: start with (1) if the org plan supports it. Fall back to (3)
if billing / policy makes (1) awkward. (2) is the fallback after that.

## fbuild integration

This repo's data lands in fbuild via two channels:

### 1. Compile-time embedded archive (offline)

fbuild's `fbuild-core::usb::embedded` module already `include_bytes!`s
a compact `usb-vendors.tar.zst` (vendor-name-only map). The build
pipeline pulls the latest from this repo's `site` branch and bumps
`crates/fbuild-core/data/usb-vendors.tar.zst` on a manual cadence
(PR-reviewed). Stays offline, stays small (~22 KB compressed).

### 2. Runtime SQLite-over-HTTP query (online, optional)

The `site` branch hosts the full per-board SQLite database via the
public portal. fbuild can fetch it on demand for richer queries (per-
PID resolution, fuzzy board-name search). Falls through to the embedded
archive when offline.

### 3. Sketch-embedded `platformio.lock` (new)

At ~1–4 KB per board, the resolved board JSON is small enough to
commit directly into the user's sketch as a `platformio.lock` file
alongside `platformio.ini`. This makes the build:

- **Reproducible** — the resolved board metadata is pinned at commit
  time, surviving upstream changes.
- **Offline-buildable** — no network fetch needed; everything the
  build pipeline needs is already on disk.
- **Diff-reviewable** — if a board's metadata changes, the diff shows
  up in PR review.

fbuild emits the `.lock` file on the first successful build for a given
`board=` setting. The user can commit it (recommended) or `.gitignore`
it (acceptable for throwaway sketches).

## Migration plan from fbuild's `online-data` branch

The current fbuild `online-data` branch + `www` branch are the v0 of
this design (one repo, two orphan branches, one nightly workflow). The
migration is incremental:

1. **Phase 1 (this PR)** — stand up `FastLED/boards` skeleton: `main`
   with README + design + workflow stubs + empty `tools/` directory.
   No data branches yet.
2. **Phase 2** — port `sync_platformio.py` from a scratch implementation
   (re-using the `pio boards --json-output` knowledge but reading raw
   `boards/*.json` to capture `build.hwids`). First push to the
   `platformio` data branch.
3. **Phase 3** — port the existing `vendor_names_inlined.py` overlay
   into `tools/sync_vendors.py`. First push to `vendors` data branch.
4. **Phase 4** — implement `sync_arduino.py` (boards.txt parser) and
   `sync_other.py` (gowdy + udev + esptool scrapes).
5. **Phase 5** — stand up `build_site.py` + the `site` branch. Public
   portal goes live (private-Pages or sibling-public-repo).
6. **Phase 6** — point fbuild's embedded-archive bump workflow at
   `FastLED/boards#site` instead of `FastLED/fbuild#online-data`.
7. **Phase 7** — retire fbuild's `online-data` + `www` branches, keep
   them as read-only archives for historical reference.

Each phase is a PR-reviewable change, gated by tests on `main`.

## Anti-goals (intentionally out of scope)

- **Per-board issue tracker** — issues live on `FastLED/fbuild` for now.
  When this repo goes public, it gets its own.
- **PR-based board contributions** — data branches are bot-pushed; if a
  human needs to add a board manually, the right place is the upstream
  source (PlatformIO platform-*, Arduino core, vendor registry). We
  mirror, we don't curate-by-PR.
- **Real-time push notifications to fbuild clients** — the existing
  pull / cache model is fine; push would add infrastructure
  (websockets, durable subscriptions) that doesn't fit this repo's
  static-asset shape.
- **Per-vendor authentication / rate limiting on the public portal** —
  the portal serves static assets; rate limits are inherited from the
  CDN. If abuse becomes real, move behind Cloudflare's free tier with
  Workers gating.
- **Mutable history on data branches** — every data branch is
  force-pushable by design (history prune); consumers MUST be tolerant
  of `force-with-lease` rewrites. The `last-good-*` tags are the
  stable references.

## Open questions

- **GitHub Pages plan availability** — does FastLED org have Team or
  higher? Determines whether we publish via private-repo Pages or via
  Cloudflare Pages / a public mirror repo.
- **Notification target** — Slack channel name? Or auto-create issue on
  this repo + assign? Both are easy; preference TBD.
- **`fbuild platformio.lock` file format** — proposed JSON shape:
  the full resolved board JSON wrapped in `{ "board": ..., "_meta":
  { "source_sha": "...", "resolved_at": "..." } }`. To be specced in a
  separate `fbuild` issue.

## See also

- `README.md` — repo overview, branch layout, how to consume the data.
- `FastLED/fbuild#718` — original SQLite-over-HTTP design that this
  repo's `site` branch generalises.
- `FastLED/fbuild#722` — meta tracker for per-vendor VID:PID ingest;
  this repo's `vendors` + `other` branches are the implementation
  surface for that work.
