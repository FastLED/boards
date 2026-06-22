// "Vendors" mode — exact-VID b-tree + FTS5 name prefix.

import { query } from '../db.js';
import { cleanHex, asVid4 } from '../util/hex.js';
import { ftsQuery } from '../util/fts.js';
import { scoreName, bumpOrPush } from '../util/score.js';
import { hideUniOverlay, renderCombined } from '../render/overlay.js';

const vidKey = (r) => r.vid;

export async function vendorOnly(raw) {
  const q = (raw || '').trim();
  if (!q) {
    hideUniOverlay();
    return;
  }
  const nameLc = q.toLowerCase();
  const hex = cleanHex(q);
  const vidExact = asVid4(q);
  const vendors = [];

  if (vidExact) {
    const exact = await query(
      'SELECT vid, vendor, source FROM vid_vendor WHERE vid = ?',
      [vidExact],
    );
    for (const r of exact) bumpOrPush(vendors, vidKey, r, 1000, 'exact VID');
  } else if (hex && hex.length < 4) {
    const pref = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 50',
      [`vid:${hex}*`],
    );
    for (const r of pref) bumpOrPush(vendors, vidKey, r, 400, 'VID prefix');
  }

  const fts = ftsQuery(q);
  if (fts && q.length >= 2) {
    const byName = await query(
      'SELECT vv.vid, vv.vendor, vv.source FROM vid_vendor vv ' +
        'JOIN vid_vendor_fts f ON f.rowid = vv.rowid ' +
        'WHERE vid_vendor_fts MATCH ? LIMIT 60',
      [`vendor:${fts}`],
    );
    for (const r of byName)
      bumpOrPush(vendors, vidKey, r, scoreName(r.vendor, nameLc), 'name');
  }

  vendors.sort(
    (a, b) => b.score - a.score || a.row.vendor.localeCompare(b.row.vendor),
  );
  renderCombined(q, { vendors });
}
