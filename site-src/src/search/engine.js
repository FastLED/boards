// Pure search engine. Same logic the portal renders, with all I/O
// injected as a `query(sql, bind)` callable.

import { cleanHex, asVid4, asVidPid8 } from '../util/hex.js';
import { ftsQuery } from '../util/fts.js';
import { scoreName, scoreTokenCoverage, bumpOrPush } from '../util/score.js';

const SEARCH_CACHE_MAX = 64;
const LINKED_BOARD_LIMIT = 60;
const PRODUCT_LIMIT = 80;
const EXACT_VID_PRODUCT_LIMIT = 25;
const _searchCache = new Map();

function _cacheKey(mode, text) {
  const norm = (text || '').trim().toLowerCase();
  if (!norm) return null;
  return mode + '|' + norm;
}

function _cacheGet(mode, text) {
  const key = _cacheKey(mode, text);
  if (key == null || !_searchCache.has(key)) return undefined;
  const v = _searchCache.get(key);
  _searchCache.delete(key);
  _searchCache.set(key, v);
  return v;
}

function _cachePut(mode, text, value) {
  const key = _cacheKey(mode, text);
  if (key == null) return;
  if (_searchCache.has(key)) _searchCache.delete(key);
  _searchCache.set(key, value);
  while (_searchCache.size > SEARCH_CACHE_MAX) {
    const oldest = _searchCache.keys().next().value;
    _searchCache.delete(oldest);
  }
}

const vidKey = (r) => r.vid;
const prodKey = (r) => `${r.vid}${r.pid}|${r.product}`;
const boardKey = (r) => r.rowid;

const BOARD_COLUMNS =
  'b.rowid AS rowid, b.board_id, b.layer, b.sublayer, b.name, ' +
  'b.vendor, b.mcu, b.architecture, b.bit_width, ' +
  'b.frequency_mhz, b.flash_kb, b.ram_kb, ' +
  'b.upload_speed, b.core, b.variant, b.homepage, ' +
  'b.frameworks, b.connectivity, b.vidpids, b.upstream_blob';

function reason(label, field, value, strength = 'related') {
  return { label, field, value, strength, exact: strength === 'exact' };
}

function normalized(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function compact(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function includesLoose(haystack, needle) {
  const h = String(haystack || '').toLowerCase();
  const n = String(needle || '').trim().toLowerCase();
  if (!h || !n) return false;
  return h.includes(n) || normalized(h).includes(normalized(n)) || compact(h).includes(compact(n));
}

function csvHas(csv, needle) {
  return String(csv || '')
    .split(',')
    .some((part) => includesLoose(part, needle));
}

function inferBoardReason(row, rawText, fallback = 'name') {
  const q = String(rawText || '').trim();
  const qLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidpids = String(row.vidpids || '').toLowerCase();
  const vidpidCompact = compact(vidpids);

  if (hex?.length === 8 && vidpidCompact.includes(hex)) {
    return reason('matches VID:PID', 'vidpids', `${hex.slice(0, 4)}:${hex.slice(4)}`, 'exact');
  }
  if (hex?.length === 4 && vidpids.includes(hex)) {
    return reason('matches VID', 'vidpids', hex, 'exact');
  }
  if (row.board_id && row.board_id.toLowerCase() === qLc) {
    return reason('exact board id', 'board_id', row.board_id, 'exact');
  }
  if (includesLoose(row.board_id, q)) return reason('board id', 'board_id', q);
  if (includesLoose(row.architecture, q)) return reason('architecture', 'architecture', q);
  if (includesLoose(row.mcu, q)) return reason('MCU', 'mcu', q);
  if (csvHas(row.frameworks, q)) return reason('framework', 'frameworks', q);
  if (csvHas(row.connectivity, q)) return reason('feature', 'connectivity', q);
  if (includesLoose(row.vendor, q)) return reason('vendor', 'name', q);
  if (includesLoose(row.sublayer, q) || includesLoose(row.layer, q)) {
    return reason('platform', 'layer', q);
  }
  if (includesLoose(row.name, q)) return reason('name', 'name', q);
  return reason(fallback, 'name', q);
}

function scoreBoard(row, nameLc) {
  const haystack = [
    row.name,
    row.board_id,
    row.mcu,
    row.architecture,
    row.frameworks,
    row.connectivity,
    row.vendor,
    row.sublayer,
  ].filter(Boolean).join(' ');
  return Math.max(
    scoreName(row.name || '', nameLc),
    scoreName(row.board_id || '', nameLc),
    scoreTokenCoverage(haystack, nameLc),
  );
}

function setMeta(meta, key, total, loaded) {
  if (total == null) return;
  const prev = meta[key] || {};
  meta[key] = {
    total: Math.max(Number(prev.total || 0), Number(total || 0), loaded || 0),
    loaded: Math.max(Number(prev.loaded || 0), loaded || 0),
  };
}

function tokenCount(text) {
  return String(text || '').trim().split(/\s+/).filter(Boolean).length;
}

function vidPrefixUpperBound(prefix) {
  return `${prefix}g`;
}

function parseMixedExactVidQuery(text) {
  const tokens = String(text || '').trim().split(/\s+/).filter(Boolean);
  if (tokens.length < 2) return null;

  let vid = null;
  const qualifierTokens = [];
  for (const token of tokens) {
    const tokenVid = asVid4(token);
    if (!vid && tokenVid) {
      vid = tokenVid;
    } else {
      qualifierTokens.push(token);
    }
  }

  const qualifier = qualifierTokens.join(' ').trim();
  if (!vid || !qualifier || !ftsQuery(qualifier)) return null;
  return { vid, qualifier };
}

async function countRows(query, sql, args) {
  const rows = await query(sql, args);
  return Number(rows?.[0]?.n || 0);
}

async function fetchProductsForVid(query, vid, limit = PRODUCT_LIMIT) {
  const total = await countRows(
    query,
    'SELECT COUNT(*) AS n FROM vidpid WHERE vid = ?',
    [vid],
  );
  const rows = await query(
    'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
      `WHERE vid = ? ORDER BY is_primary DESC, product LIMIT ${limit}`,
    [vid],
  );
  return { rows, total };
}

async function fetchVendorsForVidPrefix(query, prefix, limit = 50) {
  return query(
    'SELECT vid, vendor, source FROM vid_vendor ' +
      `WHERE vid >= ? AND vid < ? ORDER BY vid LIMIT ${limit}`,
    [prefix, vidPrefixUpperBound(prefix)],
  );
}

async function fetchProductsForVidMatchingText(query, vid, text, limit = PRODUCT_LIMIT) {
  const fts = ftsQuery(text);
  if (!fts) return { rows: [], total: 0 };
  const match = `product:${fts}`;
  const total = await countRows(
    query,
    'SELECT COUNT(*) AS n FROM vidpid vp ' +
      'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
      'WHERE vp.vid = ? AND vidpid_fts MATCH ?',
    [vid, match],
  );
  const rows = await query(
    'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
      'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
      'WHERE vp.vid = ? AND vidpid_fts MATCH ? ' +
      `ORDER BY vp.is_primary DESC, vp.product LIMIT ${limit}`,
    [vid, match],
  );
  return { rows, total };
}

function uniquePairsFromRows(rows) {
  const seen = new Set();
  const pairs = [];
  for (const r of rows) {
    const key = r.vid + r.pid;
    if (!seen.has(key)) {
      seen.add(key);
      pairs.push([r.vid, r.pid]);
    }
  }
  return pairs;
}

function scopeToIdentity(ftsExpr) {
  const tokens = (ftsExpr || '').split(' ').filter(Boolean);
  if (!tokens.length) return null;
  return tokens.map((t) => `{name aliases board_id vendor}:${t}`).join(' ');
}

const BM25_WEIGHTS = '1, 2, 1, 1, 1, 1, 1, 1, 1, 0.2';

async function fts5BoardSearch(query, fts, rawText) {
  const word = (rawText || '').trim().toLowerCase();
  if (/^[a-z]+$/.test(word)) {
    try {
      const cached = await query(
        'SELECT results_json FROM vendor_prefix_results WHERE prefix = ?',
        [word],
      );
      if (cached.length > 0 && cached[0].results_json) {
        return JSON.parse(cached[0].results_json);
      }
    } catch {
      // Older DBs may not have the prefix cache.
    }
  }

  const SQL = `SELECT ${BOARD_COLUMNS} ` +
    'FROM boards b JOIN boards_fts f ON f.rowid = b.rowid ' +
    'WHERE boards_fts MATCH ? ' +
    `ORDER BY bm25(boards_fts, ${BM25_WEIGHTS}) LIMIT 20`;
  const scoped = scopeToIdentity(fts);
  if (scoped) {
    const rows = await query(SQL, [scoped]);
    if (rows.length > 0) return rows;
  }
  return query(SQL, [fts]);
}

async function fetchLinkedBoards(query, vidpidPairs, limit = LINKED_BOARD_LIMIT) {
  if (!vidpidPairs.length) return { rows: [], total: 0, pairCount: 0 };
  const capped = vidpidPairs.slice(0, 80);
  const placeholders = capped.map(() => '(?,?)').join(',');
  const args = capped.flat();
  const total = await countRows(
    query,
    'SELECT COUNT(*) AS n FROM (' +
      'SELECT DISTINCT b.rowid FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      `WHERE (bv.vid, bv.pid) IN (${placeholders})` +
    ')',
    args,
  );
  const rows = await query(
    `SELECT DISTINCT ${BOARD_COLUMNS} ` +
      'FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      `WHERE (bv.vid, bv.pid) IN (${placeholders}) ` +
      `LIMIT ${limit}`,
    args,
  );
  return { rows, total, pairCount: capped.length };
}

async function fetchBoardsForVid(query, vid, limit = LINKED_BOARD_LIMIT) {
  const total = await countRows(
    query,
    'SELECT COUNT(*) AS n FROM (' +
      'SELECT DISTINCT b.rowid FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      'WHERE bv.vid = ?' +
    ')',
    [vid],
  );
  const rows = await query(
    `SELECT DISTINCT ${BOARD_COLUMNS} ` +
      'FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      'WHERE bv.vid = ? ' +
      `LIMIT ${limit}`,
    [vid],
  );
  return { rows, total, pairCount: 1 };
}

async function fetchBoardsForVidMatchingText(query, vid, text, limit = LINKED_BOARD_LIMIT) {
  const fts = ftsQuery(text);
  if (!fts) return { rows: [], total: 0, pairCount: 1 };
  const match = scopeToIdentity(fts) || fts;
  const total = await countRows(
    query,
    'SELECT COUNT(*) AS n FROM (' +
      'SELECT DISTINCT b.rowid FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      'JOIN boards_fts f ON f.rowid = b.rowid ' +
      'WHERE bv.vid = ? AND boards_fts MATCH ?' +
    ')',
    [vid, match],
  );
  const rows = await query(
    `SELECT DISTINCT ${BOARD_COLUMNS} ` +
      'FROM boards b ' +
      'JOIN board_vidpids bv ON bv.board_rowid = b.rowid ' +
      'JOIN boards_fts f ON f.rowid = b.rowid ' +
      'WHERE bv.vid = ? AND boards_fts MATCH ? ' +
      `ORDER BY bm25(boards_fts, ${BM25_WEIGHTS}) LIMIT ${limit}`,
    [vid, match],
  );
  return { rows, total, pairCount: 1 };
}

function enrichFromLinkedRows(boards, linked, score, why, reasonObj, meta) {
  setMeta(meta, 'boards', linked.total, linked.rows.length);
  for (const r of linked.rows) {
    bumpOrPush(boards, boardKey, r, score, why, { reason: reasonObj });
  }
}

async function enrichWithLinkedBoards(query, boards, vidpidPairs, score, why, reasonObj, meta) {
  const linked = await fetchLinkedBoards(query, vidpidPairs);
  enrichFromLinkedRows(boards, linked, score, why, reasonObj, meta);
  return linked;
}

function linkedBoardSummary(linked) {
  if (!linked?.total) return null;
  const lean = (row) => ({
    board_id: row.board_id,
    name: row.name,
    layer: row.layer,
    sublayer: row.sublayer,
  });
  return {
    total: linked.total,
    // First 3 power the inline "Board samples:" hint inside the preview.
    sample: linked.rows.slice(0, 3).map(lean),
    // All fetched rows feed the expandable click-to-search board list. Capped
    // upstream by fetchBoardsForVid's limit — when total > all.length, the
    // expansion shows that gap as "showing first N of TOTAL".
    all: linked.rows.map(lean),
  };
}

function productSummary(products) {
  return {
    total: products.total,
    loaded: products.rows.length,
    sample: products.rows.slice(0, 5).map((row) => ({
      vid: row.vid,
      pid: row.pid,
      product: row.product,
      source: row.source,
      is_primary: row.is_primary,
    })),
  };
}

function makeVidPreview(vid, vendorRow, products, linked) {
  if (!vendorRow && !products.total && !linked.total) return null;
  return {
    kind: 'vid',
    vid,
    vendor: vendorRow?.vendor || null,
    source: vendorRow?.source || null,
    score: 1000,
    reason: reason('exact VID', 'vid', vid, 'exact'),
    knownProducts: productSummary(products),
    knownBoards: linkedBoardSummary(linked) || { total: 0, sample: [] },
  };
}

function attachLinkedSummaryToHits(hits, linked) {
  const summary = linkedBoardSummary(linked);
  if (!summary) return;
  for (const hit of hits) hit.linkedBoards = summary;
}

function pushBoardSearchRows(boards, rows, q, scoreFloor = 0) {
  const nameLc = q.toLowerCase();
  for (const r of rows) {
    const sc = Math.max(scoreBoard(r, nameLc), scoreFloor);
    bumpOrPush(boards, boardKey, r, sc, 'name', {
      reason: inferBoardReason(r, q),
    });
  }
}

function sortResultCategories(vendors, products, boards) {
  vendors.sort((a, b) => b.score - a.score || a.row.vendor.localeCompare(b.row.vendor));
  products.sort((a, b) =>
    b.score - a.score ||
    (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
    a.row.product.localeCompare(b.row.product));
  boards.sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));
}

export async function searchUniversal(text, query) {
  const q = (text || '').trim();
  if (!q) return { vendors: [], products: [], boards: [] };
  const cached = _cacheGet('universal', q);
  if (cached !== undefined) return cached;

  const hex = cleanHex(q);
  const nameLc = q.toLowerCase();
  const fts = ftsQuery(q);
  const vendors = [];
  const products = [];
  const boards = [];
  const previews = [];
  const meta = {};

  const mixedExactVid = hex ? null : parseMixedExactVidQuery(q);
  if (mixedExactVid) {
    const { vid, qualifier } = mixedExactVid;
    const vendorRows = await query(
      'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
      [vid],
    );
    for (const r of vendorRows) {
      bumpOrPush(vendors, vidKey, r, 1000, 'exact VID', {
        reason: reason('exact VID', 'vid', r.vid, 'exact'),
      });
    }

    const allProducts = await fetchProductsForVid(query, vid);
    const allLinked = await fetchBoardsForVid(query, vid, 5);
    const preview = makeVidPreview(vid, vendorRows[0], allProducts, allLinked);
    if (preview) previews.push(preview);

    const matchedProducts = await fetchProductsForVidMatchingText(query, vid, qualifier);
    setMeta(meta, 'products', matchedProducts.total, matchedProducts.rows.length);
    for (const r of matchedProducts.rows) {
      const sc = Math.max(scoreName(r.product, qualifier.toLowerCase()), 720);
      bumpOrPush(products, prodKey, r, sc, 'same VID + product text', {
        reason: reason('same VID + product', 'vidpid', `${r.vid}:${r.pid}`, 'exact'),
      });
    }

    const matchedBoards = await fetchBoardsForVidMatchingText(query, vid, qualifier);
    enrichFromLinkedRows(
      boards,
      matchedBoards,
      820,
      'linked via VID + text',
      reason('linked via VID + text', 'vidpids', vid, 'exact'),
      meta,
    );

    if (vendorRows.length || allProducts.total || allLinked.total) {
      sortResultCategories(vendors, products, boards);
      const result = { previews, vendors, products, boards, meta };
      _cachePut('universal', q, result);
      return result;
    }
  }

  if (hex) {
    const vidExact = asVid4(q);
    const vidPidExact = asVidPid8(q);

    if (vidPidExact) {
      const pair = [vidPidExact.slice(0, 4), vidPidExact.slice(4)];
      const rows = await query(
        'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
          'WHERE vidpid = ? ORDER BY is_primary DESC, product',
        [vidPidExact],
      );
      setMeta(meta, 'products', rows.length, rows.length);
      const productHits = [];
      for (const r of rows) {
        productHits.push(bumpOrPush(products, prodKey, r, 1000, 'exact VID:PID', {
          reason: reason('exact VID:PID', 'vidpid', `${r.vid}:${r.pid}`, 'exact'),
        }));
      }
      const v = await query(
        'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
        [pair[0]],
      );
      for (const r of v) {
        bumpOrPush(vendors, vidKey, r, 800, 'vendor of VID:PID', {
          reason: reason('vendor for VID', 'vid', r.vid, 'exact'),
        });
      }
      const linked = await enrichWithLinkedBoards(
        query,
        boards,
        [pair],
        850,
        'linked to VID:PID',
        reason('linked to VID:PID', 'vidpids', `${pair[0]}:${pair[1]}`, 'exact'),
        meta,
      );
      attachLinkedSummaryToHits(productHits, linked);
      // Emit a VID preview so isBestHitCoveredByPreview can suppress the
      // vendor + same-VID product rows from the Best Hits strip; the exact
      // VID:PID product and the linked boards survive the filter (their
      // reasons key off vidpid / `linked to VID:PID`, not `same VID`).
      const allProducts = await fetchProductsForVid(query, pair[0], 5);
      const allLinked = await fetchBoardsForVid(query, pair[0], 5);
      const preview = makeVidPreview(pair[0], v[0], allProducts, allLinked);
      if (preview) previews.push(preview);
    } else if (vidExact) {
      const rows = await query(
        'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
        [vidExact],
      );
      for (const r of rows) {
        bumpOrPush(vendors, vidKey, r, 1000, 'exact VID', {
          reason: reason('exact VID', 'vid', r.vid, 'exact'),
        });
      }

      if (tokenCount(q) === 1 && rows.length) {
        // Eager-fetch full product + linked-board lists so the preview
        // expansion lists every board for this VID AND Best Hits has real
        // content to show beneath the preview card. Still no FTS — this
        // path stays 5 indexed lookups (vendor + 2 product + 2 board).
        const vidProducts = await fetchProductsForVid(query, vidExact);
        const linked = await fetchBoardsForVid(query, vidExact, 500);

        setMeta(meta, 'products', vidProducts.total, vidProducts.rows.length);
        for (const r of vidProducts.rows) {
          bumpOrPush(products, prodKey, r, 600, 'same VID', {
            reason: reason('same VID', 'vidpid', r.vid, 'exact'),
          });
        }
        enrichFromLinkedRows(
          boards,
          linked,
          760,
          'linked via VID',
          reason('linked via VID', 'vidpids', vidExact, 'exact'),
          meta,
        );

        const preview = makeVidPreview(vidExact, rows[0], vidProducts, linked);
        if (preview) previews.push(preview);
        const result = { previews, vendors: [], products, boards, meta };
        _cachePut('universal', q, result);
        return result;
      }

      const vidProducts = await fetchProductsForVid(query, vidExact);
      const vp = vidProducts.rows;
      setMeta(meta, 'products', vidProducts.total, vp.length);
      for (const r of vp) {
        bumpOrPush(products, prodKey, r, 600, 'same VID', {
          reason: reason('same VID', 'vidpid', r.vid, 'exact'),
        });
      }

      const linked = await fetchBoardsForVid(query, vidExact);
      enrichFromLinkedRows(
        boards,
        linked,
        760,
        'linked via VID',
        reason('linked via VID', 'vidpids', vidExact, 'exact'),
        meta,
      );
      const preview = makeVidPreview(vidExact, rows[0], vidProducts, linked);
      if (preview) previews.push(preview);

      const pidHits = await query(
        'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
          `WHERE pid = ? ORDER BY is_primary DESC, product LIMIT ${PRODUCT_LIMIT}`,
        [vidExact],
      );
      for (const r of pidHits) {
        if (r.vid !== vidExact) {
          bumpOrPush(products, prodKey, r, 300, 'PID match', {
            reason: reason('PID match', 'vidpid', r.pid),
          });
        }
      }
    } else {
      if (hex.length < 4) {
        const pref = await fetchVendorsForVidPrefix(query, hex);
        for (const r of pref) {
          bumpOrPush(vendors, vidKey, r, 400, 'VID prefix', {
            reason: reason('VID prefix', 'vid', hex),
          });
        }
        if (tokenCount(q) === 1) {
          const result = { previews, vendors, products, boards, meta };
          _cachePut('universal', q, result);
          return result;
        }
      } else if (hex.length >= 5 && hex.length <= 7) {
        const pref = await query(
          'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
            'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
            `WHERE vidpid_fts MATCH ? ORDER BY vp.is_primary DESC, vp.product LIMIT ${PRODUCT_LIMIT}`,
          [`vidpid:${hex}*`],
        );
        for (const r of pref) {
          bumpOrPush(products, prodKey, r, 500, 'VID:PID prefix', {
            reason: reason('VID:PID prefix', 'vidpid', hex),
          });
        }

        const v = await query(
          'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
          [hex.slice(0, 4)],
        );
        for (const r of v) {
          bumpOrPush(vendors, vidKey, r, 600, 'vendor of VID', {
            reason: reason('vendor for VID', 'vid', r.vid, 'exact'),
          });
        }

        await enrichWithLinkedBoards(
          query,
          boards,
          uniquePairsFromRows(pref),
          650,
          'linked via VID:PID prefix',
          reason('linked via VID:PID prefix', 'vidpids', hex),
          meta,
        );
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
      const sc = Math.max(scoreName(r.vendor, nameLc), scoreTokenCoverage(r.vendor, nameLc));
      bumpOrPush(vendors, vidKey, r, sc, 'name', {
        reason: reason('vendor name', 'name', q),
      });
    }

    const pByName = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? LIMIT 80',
      [`product:${fts}`],
    );
    for (const r of pByName) {
      const sc = Math.max(scoreName(r.product, nameLc), scoreTokenCoverage(r.product, nameLc));
      bumpOrPush(products, prodKey, r, sc, 'name', {
        reason: reason('product name', 'name', q),
      });
    }

    const topProducts = [...products].sort((a, b) => b.score - a.score).slice(0, 20);
    await enrichWithLinkedBoards(
      query,
      boards,
      uniquePairsFromRows(topProducts.map((h) => h.row)),
      630,
      'linked via product name',
      reason('linked via product name', 'vidpids', q),
      meta,
    );

    const bByName = await fts5BoardSearch(query, fts, q);
    pushBoardSearchRows(boards, bByName, q);
  }

  sortResultCategories(vendors, products, boards);

  const result = { previews, vendors, products, boards, meta };
  _cachePut('universal', q, result);
  return result;
}

export async function searchVendor(text, query) {
  const q = (text || '').trim();
  if (!q) return { vendors: [], products: [], boards: [] };
  const cached = _cacheGet('vendor', q);
  if (cached !== undefined) return cached;
  const nameLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidExact = asVid4(q);
  const vendors = [];
  const previews = [];

  if (vidExact) {
    const exact = await query(
      'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
      [vidExact],
    );
    for (const r of exact) {
      bumpOrPush(vendors, vidKey, r, 1000, 'exact VID', {
        reason: reason('exact VID', 'vid', r.vid, 'exact'),
      });
    }
    const vidProducts = await fetchProductsForVid(query, vidExact, 5);
    const linked = await fetchBoardsForVid(query, vidExact, 5);
    const preview = makeVidPreview(vidExact, exact[0], vidProducts, linked);
    if (preview) previews.push(preview);
  } else if (hex && hex.length < 4) {
    const pref = await fetchVendorsForVidPrefix(query, hex);
    for (const r of pref) {
      bumpOrPush(vendors, vidKey, r, 400, 'VID prefix', {
        reason: reason('VID prefix', 'vid', hex),
      });
    }
  }

  const fts = ftsQuery(q);
  if (fts && q.length >= 2) {
    const byName = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 60',
      [`vendor:${fts}`],
    );
    for (const r of byName) {
      bumpOrPush(vendors, vidKey, r, scoreName(r.vendor, nameLc), 'name', {
        reason: reason('vendor name', 'name', q),
      });
    }
  }
  vendors.sort((a, b) => b.score - a.score || a.row.vendor.localeCompare(b.row.vendor));
  const result = { previews, vendors, products: [], boards: [] };
  _cachePut('vendor', q, result);
  return result;
}

export async function searchProduct(text, query) {
  const q = (text || '').trim();
  if (!q) return { vendors: [], products: [], boards: [] };
  const cached = _cacheGet('product', q);
  if (cached !== undefined) return cached;
  const nameLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidExact = hex ? asVid4(q) : null;
  const vidPidExact = asVidPid8(q);
  const previews = [];
  const vendors = [];
  const products = [];
  const boards = [];
  const meta = {};

  const mixedExactVid = hex ? null : parseMixedExactVidQuery(q);
  if (mixedExactVid) {
    const { vid, qualifier } = mixedExactVid;
    const vendorRows = await query(
      'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
      [vid],
    );
    const allProducts = await fetchProductsForVid(query, vid, 5);
    const allLinked = await fetchBoardsForVid(query, vid, 5);
    const preview = makeVidPreview(vid, vendorRows[0], allProducts, allLinked);
    if (preview) previews.push(preview);

    const matchedProducts = await fetchProductsForVidMatchingText(query, vid, qualifier);
    setMeta(meta, 'products', matchedProducts.total, matchedProducts.rows.length);
    for (const r of matchedProducts.rows) {
      const sc = Math.max(scoreName(r.product, qualifier.toLowerCase()), 720);
      bumpOrPush(products, prodKey, r, sc, 'same VID + product text', {
        reason: reason('same VID + product', 'vidpid', `${r.vid}:${r.pid}`, 'exact'),
      });
    }

    const matchedBoards = await fetchBoardsForVidMatchingText(query, vid, qualifier);
    enrichFromLinkedRows(
      boards,
      matchedBoards,
      820,
      'linked via VID + text',
      reason('linked via VID + text', 'vidpids', vid, 'exact'),
      meta,
    );

    if (preview || products.length || boards.length) {
      products.sort((a, b) =>
        b.score - a.score ||
        (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
        a.row.product.localeCompare(b.row.product));
      boards.sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));
      const result = { previews, vendors, products, boards, meta };
      _cachePut('product', q, result);
      return result;
    }
  }

  if (vidPidExact) {
    const pair = [vidPidExact.slice(0, 4), vidPidExact.slice(4)];
    const exact = await query(
      'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
        'WHERE vidpid = ? ORDER BY is_primary DESC, product',
      [vidPidExact],
    );
    setMeta(meta, 'products', exact.length, exact.length);
    const productHits = [];
    for (const r of exact) {
      productHits.push(bumpOrPush(products, prodKey, r, 1000, 'exact VID:PID', {
        reason: reason('exact VID:PID', 'vidpid', `${r.vid}:${r.pid}`, 'exact'),
      }));
    }
    const linked = await enrichWithLinkedBoards(
      query,
      boards,
      [pair],
      850,
      'linked to VID:PID',
      reason('linked to VID:PID', 'vidpids', `${pair[0]}:${pair[1]}`, 'exact'),
      meta,
    );
    attachLinkedSummaryToHits(productHits, linked);
  } else if (vidExact && tokenCount(q) === 1) {
    const vendorRows = await query(
      'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
      [vidExact],
    );
    const vidProducts = await fetchProductsForVid(query, vidExact, EXACT_VID_PRODUCT_LIMIT);
    const linked = await fetchBoardsForVid(query, vidExact, 5);
    const preview = makeVidPreview(vidExact, vendorRows[0], vidProducts, linked);
    if (preview) {
      previews.push(preview);
      setMeta(meta, 'products', vidProducts.total, vidProducts.rows.length);
      for (const r of vidProducts.rows) {
        bumpOrPush(products, prodKey, r, 600, 'same VID', {
          reason: reason('same VID', 'vidpid', r.vid, 'exact'),
        });
      }
      const result = { previews, vendors, products, boards, meta };
      _cachePut('product', q, result);
      return result;
    }
  } else if (hex && hex.length < 4 && tokenCount(q) === 1) {
    const pref = await fetchVendorsForVidPrefix(query, hex);
    for (const r of pref) {
      bumpOrPush(vendors, vidKey, r, 400, 'VID prefix', {
        reason: reason('VID prefix', 'vid', hex),
      });
    }
    const result = { previews, vendors, products, boards, meta };
    _cachePut('product', q, result);
    return result;
  } else if (hex && hex.length >= 1 && hex.length <= 7) {
    const pref = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        `WHERE vidpid_fts MATCH ? ORDER BY vp.is_primary DESC, vp.product LIMIT ${PRODUCT_LIMIT}`,
      [`vidpid:${hex}*`],
    );
    for (const r of pref) {
      bumpOrPush(products, prodKey, r, 500, 'VID:PID prefix', {
        reason: reason('VID:PID prefix', 'vidpid', hex),
      });
    }
    await enrichWithLinkedBoards(
      query,
      boards,
      uniquePairsFromRows(pref),
      650,
      'linked via VID:PID prefix',
      reason('linked via VID:PID prefix', 'vidpids', hex),
      meta,
    );
  }

  const fts = ftsQuery(q);
  if (fts && q.length >= 2) {
    const byName = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? LIMIT 80',
      [`product:${fts}`],
    );
    for (const r of byName) {
      bumpOrPush(products, prodKey, r, scoreName(r.product, nameLc), 'name', {
        reason: reason('product name', 'name', q),
      });
    }
    const topProducts = [...products].sort((a, b) => b.score - a.score).slice(0, 20);
    await enrichWithLinkedBoards(
      query,
      boards,
      uniquePairsFromRows(topProducts.map((h) => h.row)),
      630,
      'linked via product name',
      reason('linked via product name', 'vidpids', q),
      meta,
    );
  }

  products.sort((a, b) =>
    b.score - a.score ||
    (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
    a.row.product.localeCompare(b.row.product));
  boards.sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));
  const result = { previews, vendors, products, boards, meta };
  _cachePut('product', q, result);
  return result;
}

export async function searchBoard(text, query) {
  const q = (text || '').trim();
  if (!q || q.length < 2) return { vendors: [], products: [], boards: [] };
  const cached = _cacheGet('board', q);
  if (cached !== undefined) return cached;
  const fts = ftsQuery(q);
  if (!fts) return { vendors: [], products: [], boards: [] };

  const rows = await fts5BoardSearch(query, fts, q);
  const boards = [];
  pushBoardSearchRows(boards, rows, q);
  boards.sort((a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name));
  const result = { vendors: [], products: [], boards };
  _cachePut('board', q, result);
  return result;
}
