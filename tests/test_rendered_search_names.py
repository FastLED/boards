"""Rendered search-name regressions.

These tests drive the same JS search engine and row renderer the portal
uses, against boards.db. Set BOARDS_DB to a freshly generated local DB,
for example:

    python tools/rebuild_boards_local.py --out %TEMP%\\fastled-boards-local.db
    set BOARDS_DB=%TEMP%\\fastled-boards-local.db
    python -m unittest tests.test_rendered_search_names -v
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO = pathlib.Path(__file__).resolve().parents[1]
BUN = shutil.which("bun")
LIVE_URL = "https://fastled.github.io/boards/boards.db"


def _db_arg() -> str:
    override = os.environ.get("BOARDS_DB")
    if override and os.path.exists(override):
        return override
    return LIVE_URL


RENDER_303A_SCRIPT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo, dbSource] = process.argv.slice(2);
const { openDb } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/db/index.js')).href
);
const { searchUniversal } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/search/engine.js')).href
);
const { renderBoardRow } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/render/board-row.js')).href
);

function htmlText(html) {
  return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function hasVendorPrefixedName(row) {
  const vendor = (row.vendor || '').trim();
  const name = (row.name || '').trim();
  if (!vendor || !name) return false;
  if (name.slice(0, vendor.length).toLocaleLowerCase()
      !== vendor.toLocaleLowerCase()) {
    return false;
  }
  return /^[\s:|/._\-\u00b7\u2022\u2013\u2014]+/u.test(
    name.slice(vendor.length),
  );
}

function repeatsRenderedVendor(row, renderedText) {
  const vendor = escapeRegex((row.vendor || '').trim());
  const repeated = new RegExp(
    `${vendor}\\s*[\\u00b7:\\-\\u2013\\u2014|/]\\s*${vendor}`,
    'iu',
  );
  return repeated.test(renderedText);
}

const db = await openDb({ source: dbSource });
try {
  const data = await searchUniversal('303a', db.query.bind(db));
  const rows = data.boards.map((h) => h.row);
  const prefixedRows = rows.filter(hasVendorPrefixedName);
  const rendered = prefixedRows.map((row) => ({
    board_id: row.board_id,
    vendor: row.vendor,
    name: row.name,
    text: htmlText(renderBoardRow(row)),
  }));
  const duplicates = rendered.filter((row) => repeatsRenderedVendor(row, row.text));
  process.stdout.write(JSON.stringify({
    boardCount: rows.length,
    prefixedCount: prefixedRows.length,
    sample: rendered.slice(0, 3),
    duplicates: duplicates.slice(0, 5),
  }));
} finally {
  await db.close();
}
"""


RENDER_303A_PREVIEW_SCRIPT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo, dbSource] = process.argv.slice(2);
const { openDb } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/db/index.js')).href
);
const { searchUniversal } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/search/engine.js')).href
);
const { renderPreviewRow } = await import(
  pathToFileURL(path.join(repo, 'site-src/src/render/preview-row.js')).href
);

function htmlText(html) {
  return html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}

const db = await openDb({ source: dbSource });
try {
  const data = await searchUniversal('303a', db.query.bind(db));
  const preview = data.previews.find((p) => p.kind === 'vid' && p.vid === '303a');
  process.stdout.write(JSON.stringify({
    preview,
    text: preview ? htmlText(renderPreviewRow(preview, '303a')) : '',
  }));
} finally {
  await db.close();
}
"""


def _render_303a_board_rows(db: str) -> dict:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjs", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(textwrap.dedent(RENDER_303A_SCRIPT).strip() + "\n")
        script_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, script_path, str(REPO), db],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AssertionError(
            f"bun render check exit {e.returncode}\nstderr:\n{e.stderr}\n"
            f"stdout:\n{e.stdout[:1000]}"
        ) from e
    finally:
        os.unlink(script_path)
    return json.loads(proc.stdout)


def _render_303a_preview(db: str) -> dict:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjs", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(textwrap.dedent(RENDER_303A_PREVIEW_SCRIPT).strip() + "\n")
        script_path = fh.name
    try:
        proc = subprocess.run(
            [BUN, script_path, str(REPO), db],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise AssertionError(
            f"bun preview render check exit {e.returncode}\nstderr:\n{e.stderr}\n"
            f"stdout:\n{e.stdout[:1000]}"
        ) from e
    finally:
        os.unlink(script_path)
    return json.loads(proc.stdout)


@unittest.skipIf(BUN is None, "bun runtime not installed")
class RenderedSearchNameTests(unittest.TestCase):
    def test_303a_board_rows_do_not_repeat_vendor_prefix(self) -> None:
        payload = _render_303a_board_rows(_db_arg())
        self.assertGreater(
            payload["boardCount"],
            0,
            f"303a should return board rows: {payload!r}",
        )
        self.assertGreater(
            payload["prefixedCount"],
            0,
            "303a fixture should include DB rows whose name starts with vendor; "
            f"sample={payload.get('sample')!r}",
        )
        self.assertFalse(
            payload["duplicates"],
            "rendered 303a board rows should not repeat vendor as "
            "`Vendor · Vendor ...`:\n"
            + json.dumps(payload["duplicates"], indent=2),
        )


    def test_303a_vid_preview_renders_known_board_summary(self) -> None:
        payload = _render_303a_preview(_db_arg())
        preview = payload["preview"]
        self.assertIsNotNone(preview, f"303a preview missing: {payload!r}")
        text = payload["text"]
        self.assertIn("0x303a", text)
        self.assertIn("Espressif Systems", text)
        self.assertIn("exact VID", text)
        self.assertIn("known boards", text)
        self.assertIn(str(preview["knownBoards"]["total"]), text)


if __name__ == "__main__":
    unittest.main()
