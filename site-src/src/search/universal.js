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

// Columns selected for every board fetch — kept as one constant so the
// junction lookup and the FTS5 lookup return identically-shaped rows.
const BOARD_COLUMNS =
  'b.rowid AS rowid, b.board_id, b.layer, b.sublayer, b.name, ' +
  'b.vendor, b.mcu, b.architecture, b.bit_width, ' +
  'b.frequency_mhz, b.flash_kb, b.ram_kb, ' +
  'b.upload_speed, b.core, b.variant, b.homepage, ' +
  'b.frameworks, b.connectivity, b.vidpids, b.upstream_blob';

/**
 * Given a list of `[vid, pid]` pairs, fetch every board that the
 * `board_vidpids` junction links them to. One round-trip via the
 * `idx_board_vidpids_vidpid` index — no full scans.
 *
 * Push the results into the `boards` array at the given score so they
 * surface in Best Hits next to the vidpid rows they identify.
 */
async function enrichWithLinkedBoards(boards, vidpidPairs, score, why) {
  if (!vidpidPairs.length) return;
  // SQLite supports row-value IN syntax: `WHERE (vid, pid) IN ((?,?),(?,?),...)`.
  // Cap the in-list to keep the planner happy and to bound the work the
  // junction does on broad VID-only queries.
  const capped = vidpidPairs.slice(0, 40);
  const placeholders = capped.map(() => '(?,?)').join(',');
  const args = capped.flat();
  const rows = await query(
    `SELECT DISTINCT ${BOARD_COLUMNS} ` +
      'FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      `WHERE (bv.vid, bv.pid) IN (${placeholders}) ` +
      'LIMIT 30',
    args,
  );
  for (const r of rows) {
    bumpOrPush(boards, boardKey, r, score, why);
  }
}

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

      // Master-record lookup: which boards does this VID:PID actually
      // identify? With the board_vidpids junction in place, a query like
      // "16c0:0483" jumps straight from "Teensy (Serial mode)" to the 10
      // Teensy boards via a single indexed JOIN, and they surface in
      // Best Hits with a View JSON button each.
      await enrichWithLinkedBoards(
        boards,
        [[vidPidExact.slice(0, 4), vidPidExact.slice(4)]],
        800,
        'linked to VID:PID',
      );
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

      // Boards linked to ANY VID:PID with this VID. Important because
      // boards_fts doesn't index the vidpids column — searching by VID
      // would otherwise miss the boards. We feed the (vid, pid) pairs
      // we just pulled from the vidpid table into the junction lookup.
      const seen = new Set();
      const pairsForJunction = [];
      for (const r of vp) {
        const k = r.vid + r.pid;
        if (!seen.has(k)) {
          seen.add(k);
          pairsForJunction.push([r.vid, r.pid]);
        }
      }
      await enrichWithLinkedBoards(
        boards,
        pairsForJunction,
        700,
        'linked via VID',
      );

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

        // Junction enrichment for prefix VID:PID — gathers any boards
        // linked to one of the prefix-matched VID:PIDs.
        const seen = new Set();
        const pairsForJunction = [];
        for (const r of pref) {
          const k = r.vid + r.pid;
          if (!seen.has(k)) {
            seen.add(k);
            pairsForJunction.push([r.vid, r.pid]);
          }
        }
        await enrichWithLinkedBoards(
          boards,
          pairsForJunction,
          650,
          'linked via VID:PID prefix',
        );
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

    // For each VID:PID that came back from the product name search, see
    // whether the junction links it to one or more boards. This is the
    // "esp returns vid/pid fragments" → "esp returns master records with
    // View JSON" upgrade: when the user types `esp`, the product hit
    // `Espressif ESP-WROVER-KIT (0403:6010)` now drags the matching
    // board(s) along too. Capped to the top-scoring 20 product rows so a
    // broad name search doesn't fan out beyond what the user can read.
    const topProducts = [...products]
      .sort((a, b) => b.score - a.score)
      .slice(0, 20);
    const seenPairs = new Set();
    const pairsForJunction = [];
    for (const p of topProducts) {
      const k = p.row.vid + p.row.pid;
      if (!seenPairs.has(k)) {
        seenPairs.add(k);
        pairsForJunction.push([p.row.vid, p.row.pid]);
      }
    }
    await enrichWithLinkedBoards(
      boards,
      pairsForJunction,
      630,
      'linked via product name',
    );

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
