// "Anything" mode — the universal search. Fans out to vendor + product
// + board lookups (b-tree for exact hex, FTS5 for names) and renders
// the union as a categorized overlay.

import { query } from '../db.js';
import { cleanHex, asVid4, asVidPid8 } from '../util/hex.js';
import { ftsQuery } from '../util/fts.js';
import { scoreName, scoreTokenCoverage, bumpOrPush } from '../util/score.js';
import { hideUniOverlay, renderCombined } from '../render/overlay.js';

const vidKey = (r) => r.vid;
const prodKey = (r) => `${r.vid}${r.pid}|${r.product}`;
const boardKey = (r) => r.rowid;

export async function universalSearch(raw) {
  const q = (raw || '').trim();
  if (!q) {
    hideUniOverlay();
    return;
  }

  const hex = cleanHex(q);
  const nameLc = q.toLowerCase();
  const fts = ftsQuery(q);
  const vendors = [];
  const products = [];
  const boards = [];

  // 1. Hex-based lookups -------------------------------------------------
  if (hex) {
    const vidExact = asVid4(q);
    const vidPidExact = asVidPid8(q);

    if (vidPidExact) {
      const rows = await query(
        'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
          'WHERE vidpid = ? ORDER BY is_primary DESC, product',
        [vidPidExact],
      );
      for (const r of rows) bumpOrPush(products, prodKey, r, 1000, 'exact VID:PID');
      const v = await query(
        'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
        [vidPidExact.slice(0, 4)],
      );
      for (const r of v) bumpOrPush(vendors, vidKey, r, 800, 'vendor of VID:PID');
    } else if (vidExact) {
      const rows = await query(
        'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
        [vidExact],
      );
      for (const r of rows) bumpOrPush(vendors, vidKey, r, 1000, 'exact VID');

      const vp = await query(
        'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
          'WHERE vid = ? ORDER BY is_primary DESC, product LIMIT 50',
        [vidExact],
      );
      for (const r of vp) bumpOrPush(products, prodKey, r, 600, 'same VID');

      // 4-hex could also be a PID — try a PID-only lookup.
      const pidHits = await query(
        'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
          'WHERE pid = ? ORDER BY is_primary DESC, product LIMIT 50',
        [vidExact],
      );
      for (const r of pidHits) {
        if (r.vid !== vidExact)
          bumpOrPush(products, prodKey, r, 300, 'PID match');
      }
    } else {
      // Short prefix or 5-7 char VID:PID prefix → FTS5 prefix matching.
      if (hex.length < 4) {
        const pref = await query(
          'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
            'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
            'WHERE vid_vendor_fts MATCH ? LIMIT 50',
          [`vid:${hex}*`],
        );
        for (const r of pref) bumpOrPush(vendors, vidKey, r, 400, 'VID prefix');
      } else if (hex.length >= 5 && hex.length <= 7) {
        const pref = await query(
          'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
            'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
            'WHERE vidpid_fts MATCH ? ORDER BY vp.is_primary DESC, vp.product LIMIT 50',
          [`vidpid:${hex}*`],
        );
        for (const r of pref)
          bumpOrPush(products, prodKey, r, 500, 'VID:PID prefix');

        const v = await query(
          'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
          [hex.slice(0, 4)],
        );
        for (const r of v) bumpOrPush(vendors, vidKey, r, 600, 'vendor of VID');
      }
    }
  }

  // 2. Name-based lookups via FTS5 ---------------------------------------
  if (fts && q.length >= 2) {
    const vByName = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 60',
      [`vendor:${fts}`],
    );
    for (const r of vByName) {
      const sc = Math.max(
        scoreName(r.vendor, nameLc),
        scoreTokenCoverage(r.vendor, nameLc),
      );
      bumpOrPush(vendors, vidKey, r, sc, 'name');
    }

    const pByName = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? LIMIT 80',
      [`product:${fts}`],
    );
    for (const r of pByName) {
      const sc = Math.max(
        scoreName(r.product, nameLc),
        scoreTokenCoverage(r.product, nameLc),
      );
      bumpOrPush(products, prodKey, r, sc, 'name');
    }

    const bByName = await query(
      'SELECT b.rowid AS rowid, b.board_id, b.layer, b.sublayer, b.name, ' +
        '       b.vendor, b.mcu, b.architecture, b.bit_width, ' +
        '       b.frequency_mhz, b.flash_kb, b.ram_kb, ' +
        '       b.upload_speed, b.core, b.variant, b.homepage, ' +
        '       b.frameworks, b.connectivity, b.vidpids, b.upstream_blob ' +
        'FROM boards b JOIN boards_fts f ON f.rowid = b.rowid ' +
        'WHERE boards_fts MATCH ? ORDER BY b.name COLLATE NOCASE LIMIT 20',
      [fts],
    );
    // For multi-token searches a board is "relevant" when all tokens
    // landed across the board's indexed columns (name, frameworks,
    // connectivity, architecture, …). scoreTokenCoverage looks across a
    // synthetic haystack that mirrors what FTS5 actually saw, so a
    // search like `wifi arduino uno` rates a board whose
    // name=Arduino UNO WiFi, frameworks=arduino, connectivity=wifi
    // at 620 — high enough to promote it into the Best Hits strip.
    for (const r of bByName) {
      const haystack = [
        r.name,
        r.board_id,
        r.mcu,
        r.architecture,
        r.frameworks,
        r.connectivity,
        r.vendor,
        r.sublayer,
      ]
        .filter(Boolean)
        .join(' ');
      const sc = Math.max(
        scoreName(r.name, nameLc),
        scoreName(r.board_id, nameLc),
        scoreTokenCoverage(haystack, nameLc),
      );
      bumpOrPush(boards, boardKey, r, sc, 'name');
    }
  }

  vendors.sort(
    (a, b) => b.score - a.score || a.row.vendor.localeCompare(b.row.vendor),
  );
  products.sort(
    (a, b) =>
      b.score - a.score ||
      (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
      a.row.product.localeCompare(b.row.product),
  );
  boards.sort(
    (a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name),
  );

  renderCombined(q, { vendors, products, boards });
}
