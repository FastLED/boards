// "Products" mode — exact VID:PID b-tree (returns primary + all
// alternates) + FTS5 prefix for short hex + FTS5 name search.

import { query } from '../db.js';
import { cleanHex, asVidPid8 } from '../util/hex.js';
import { ftsQuery } from '../util/fts.js';
import { scoreName, bumpOrPush } from '../util/score.js';
import { hideUniOverlay, renderCombined } from '../render/overlay.js';

const prodKey = (r) => `${r.vid}${r.pid}|${r.product}`;

export async function productOnly(raw) {
  const q = (raw || '').trim();
  if (!q) {
    hideUniOverlay();
    return;
  }
  const nameLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidPidExact = asVidPid8(q);
  const products = [];

  if (vidPidExact) {
    const exact = await query(
      'SELECT vid, pid, product, source, is_primary FROM vidpid ' +
        'WHERE vidpid = ? ORDER BY is_primary DESC, product',
      [vidPidExact],
    );
    for (const r of exact) bumpOrPush(products, prodKey, r, 1000, 'exact VID:PID');
  } else if (hex && hex.length >= 1 && hex.length <= 7) {
    const pref = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? ORDER BY vp.is_primary DESC, vp.product LIMIT 50',
      [`vidpid:${hex}*`],
    );
    for (const r of pref) bumpOrPush(products, prodKey, r, 500, 'VID:PID prefix');
  }

  const fts = ftsQuery(q);
  if (fts && q.length >= 2) {
    const byName = await query(
      'SELECT vp.vid, vp.pid, vp.product, vp.source, vp.is_primary FROM vidpid vp ' +
        'JOIN vidpid_fts f ON f.rowid = vp.rowid ' +
        'WHERE vidpid_fts MATCH ? LIMIT 80',
      [`product:${fts}`],
    );
    for (const r of byName)
      bumpOrPush(products, prodKey, r, scoreName(r.product, nameLc), 'name');
  }

  products.sort(
    (a, b) =>
      b.score - a.score ||
      (b.row.is_primary || 0) - (a.row.is_primary || 0) ||
      a.row.product.localeCompare(b.row.product),
  );
  renderCombined(q, { products });
}
