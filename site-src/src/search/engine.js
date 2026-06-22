// Pure search engine. Same logic the portal renders, with all I/O
// (SQL query execution) injected as a `query(sql, bind)` callable.
//
// Single source of truth: the UI wrappers in universal.js / vendor.js /
// product.js / board.js call the corresponding `searchX(text, query)`
// here, then hand the result to renderCombined(). The Node test CLI
// calls the same `searchX(text, query)` with a bun:sqlite-backed query
// and prints the result as JSON. No drift possible — same SQL, same
// ftsQuery, same scoring, same shape.
//
// The four exports each return:
//   { vendors: Array<{row, score, why}>,
//     products: Array<{row, score, why}>,
//     boards:   Array<{row, score, why}> }
// where empty arrays denote "no results in this category" and the
// rendering layer decides what to show the user.

import { cleanHex, asVid4, asVidPid8 } from '../util/hex.js';
import { ftsQuery } from '../util/fts.js';
import { scoreName, scoreTokenCoverage, bumpOrPush } from '../util/score.js';

const vidKey   = (r) => r.vid;
const prodKey  = (r) => `${r.vid}${r.pid}|${r.product}`;
const boardKey = (r) => r.rowid;

const BOARD_COLUMNS =
  'b.rowid AS rowid, b.board_id, b.layer, b.sublayer, b.name, ' +
  'b.vendor, b.mcu, b.architecture, b.bit_width, ' +
  'b.frequency_mhz, b.flash_kb, b.ram_kb, ' +
  'b.upload_speed, b.core, b.variant, b.homepage, ' +
  'b.frameworks, b.connectivity, b.vidpids, b.upstream_blob';

async function enrichWithLinkedBoards(query, boards, vidpidPairs, score, why) {
  if (!vidpidPairs.length) return;
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
  for (const r of rows) bumpOrPush(boards, boardKey, r, score, why);
}

/**
 * "Anything" mode — fans out across vendor + product + board lookups
 * and returns the merged, sorted union.
 *
 * @param {string} text user-typed free-text query
 * @param {(sql:string, bind?:Array|Object)=>Promise<Object[]>} query
 */
export async function searchUniversal(text, query) {
  const q = (text || '').trim();
  if (!q) return { vendors: [], products: [], boards: [] };

  const hex = cleanHex(q);
  const nameLc = q.toLowerCase();
  const fts = ftsQuery(q);
  const vendors = [];
  const products = [];
  const boards = [];

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
      await enrichWithLinkedBoards(query, boards,
        [[vidPidExact.slice(0, 4), vidPidExact.slice(4)]], 800, 'linked to VID:PID');
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

      const seen = new Set();
      const pairs = [];
      for (const r of vp) {
        const k = r.vid + r.pid;
        if (!seen.has(k)) { seen.add(k); pairs.push([r.vid, r.pid]); }
      }
      await enrichWithLinkedBoards(query, boards, pairs, 700, 'linked via VID');

      const pidHits = await query(
        'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
          'WHERE pid = ? ORDER BY is_primary DESC, product LIMIT 50',
        [vidExact],
      );
      for (const r of pidHits) {
        if (r.vid !== vidExact) bumpOrPush(products, prodKey, r, 300, 'PID match');
      }
    } else {
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
        for (const r of pref) bumpOrPush(products, prodKey, r, 500, 'VID:PID prefix');

        const v = await query(
          'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
          [hex.slice(0, 4)],
        );
        for (const r of v) bumpOrPush(vendors, vidKey, r, 600, 'vendor of VID');

        const seen = new Set();
        const pairs = [];
        for (const r of pref) {
          const k = r.vid + r.pid;
          if (!seen.has(k)) { seen.add(k); pairs.push([r.vid, r.pid]); }
        }
        await enrichWithLinkedBoards(query, boards, pairs, 650, 'linked via VID:PID prefix');
      }
    }
  }

  if (fts && q.length >= 2) {
    const vByName = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 60',
      [`vendor:${fts}`],
    );
    for (const r of vByName) {
      const sc = Math.max(scoreName(r.vendor, nameLc),
                          scoreTokenCoverage(r.vendor, nameLc));
      bumpOrPush(vendors, vidKey, r, sc, 'name');
    }

    const pByName = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? LIMIT 80',
      [`product:${fts}`],
    );
    for (const r of pByName) {
      const sc = Math.max(scoreName(r.product, nameLc),
                          scoreTokenCoverage(r.product, nameLc));
      bumpOrPush(products, prodKey, r, sc, 'name');
    }

    const topProducts = [...products].sort((a, b) => b.score - a.score).slice(0, 20);
    const seen = new Set();
    const pairs = [];
    for (const p of topProducts) {
      const k = p.row.vid + p.row.pid;
      if (!seen.has(k)) { seen.add(k); pairs.push([p.row.vid, p.row.pid]); }
    }
    await enrichWithLinkedBoards(query, boards, pairs, 630, 'linked via product name');

    const bByName = await query(
      `SELECT ${BOARD_COLUMNS} ` +
        'FROM boards b JOIN boards_fts f ON f.rowid = b.rowid ' +
        // ORDER BY rank uses FTS5's built-in BM25 so name matches
        // float to the top. With ORDER BY b.name we'd just take
        // alphabetically-first 20 hits, dropping highly-relevant
        // boards like "Seeed Tiny BLE" out of a Tiny BLE search.
        //
        // HISTORICAL: BM25 ordering had been used here previously,
        // then degraded to ORDER BY name (allegedly for perf — the
        // hit was livable). Restoring it because the perf cost is
        // dwarfed by the search-quality recovery; see
        // tests/test_board_name_combos.py for the regression that
        // exposed the degradation.
        'WHERE boards_fts MATCH ? ORDER BY rank LIMIT 20',
      [fts],
    );
    for (const r of bByName) {
      const haystack = [r.name, r.board_id, r.mcu, r.architecture,
                        r.frameworks, r.connectivity, r.vendor, r.sublayer]
        .filter(Boolean).join(' ');
      const sc = Math.max(
        scoreName(r.name, nameLc),
        scoreName(r.board_id, nameLc),
        scoreTokenCoverage(haystack, nameLc),
      );
      bumpOrPush(boards, boardKey, r, sc, 'name');
    }
  }

  vendors.sort((a, b) => b.score - a.score || a.row.vendor.localeCompare(b.row.vendor));
  products.sort((a, b) =>
    b.score - a.score ||
    (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
    a.row.product.localeCompare(b.row.product));
  boards.sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));

  return { vendors, products, boards };
}

/** Vendors-only mode. */
export async function searchVendor(text, query) {
  const q = (text || '').trim();
  if (!q) return { vendors: [], products: [], boards: [] };
  const nameLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidExact = asVid4(q);
  const vendors = [];

  if (vidExact) {
    const exact = await query(
      'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?', [vidExact]);
    for (const r of exact) bumpOrPush(vendors, vidKey, r, 1000, 'exact VID');
  } else if (hex && hex.length < 4) {
    const pref = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 50',
      [`vid:${hex}*`]);
    for (const r of pref) bumpOrPush(vendors, vidKey, r, 400, 'VID prefix');
  }

  const fts = ftsQuery(q);
  if (fts && q.length >= 2) {
    const byName = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 60',
      [`vendor:${fts}`]);
    for (const r of byName)
      bumpOrPush(vendors, vidKey, r, scoreName(r.vendor, nameLc), 'name');
  }
  vendors.sort((a, b) => b.score - a.score || a.row.vendor.localeCompare(b.row.vendor));
  return { vendors, products: [], boards: [] };
}

/** Products-only mode. */
export async function searchProduct(text, query) {
  const q = (text || '').trim();
  if (!q) return { vendors: [], products: [], boards: [] };
  const nameLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidPidExact = asVidPid8(q);
  const products = [];

  if (vidPidExact) {
    const exact = await query(
      'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
        'WHERE vidpid = ? ORDER BY is_primary DESC, product',
      [vidPidExact]);
    for (const r of exact) bumpOrPush(products, prodKey, r, 1000, 'exact VID:PID');
  } else if (hex && hex.length >= 1 && hex.length <= 7) {
    const pref = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? ORDER BY vp.is_primary DESC, vp.product LIMIT 50',
      [`vidpid:${hex}*`]);
    for (const r of pref) bumpOrPush(products, prodKey, r, 500, 'VID:PID prefix');
  }

  const fts = ftsQuery(q);
  if (fts && q.length >= 2) {
    const byName = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? LIMIT 80',
      [`product:${fts}`]);
    for (const r of byName)
      bumpOrPush(products, prodKey, r, scoreName(r.product, nameLc), 'name');
  }
  products.sort((a, b) =>
    b.score - a.score ||
    (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
    a.row.product.localeCompare(b.row.product));
  return { vendors: [], products, boards: [] };
}

/** Boards-only mode. */
export async function searchBoard(text, query) {
  const q = (text || '').trim();
  if (!q || q.length < 2) return { vendors: [], products: [], boards: [] };
  const fts = ftsQuery(q);
  if (!fts) return { vendors: [], products: [], boards: [] };

  const rows = await query(
    `SELECT ${BOARD_COLUMNS} ` +
      'FROM boards b JOIN boards_fts f ON f.rowid = b.rowid ' +
      // ORDER BY rank — see HISTORICAL note in searchUniversal above.
      // BM25 keeps name-matched boards at the top instead of taking
      // an alphabetical slice that drops the relevant hits.
      'WHERE boards_fts MATCH ? ORDER BY rank LIMIT 20',
    [fts]);
  const nameLc = q.toLowerCase();
  const boards = rows.map((row) => ({
    row,
    score: Math.max(scoreName(row.name, nameLc), scoreName(row.board_id, nameLc)),
    why: 'name',
  }));
  boards.sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));
  return { vendors: [], products: [], boards };
}
