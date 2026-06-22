// "Boards" mode — FTS5 against (board_id, name, vendor, mcu, sublayer,
// frameworks, connectivity); name-ordered for cheap LIMIT 20.

import { query } from '../db.js';
import { ftsQuery } from '../util/fts.js';
import { scoreName } from '../util/score.js';
import {
  hideUniOverlay,
  renderCombined,
  showUniOverlay,
} from '../render/overlay.js';

export async function boardOnly(raw) {
  const q = (raw || '').trim();
  if (!q) {
    hideUniOverlay();
    return;
  }
  if (q.length < 2) {
    showUniOverlay('Enter at least 2 characters.', 'empty');
    return;
  }
  const fts = ftsQuery(q);
  if (!fts) {
    showUniOverlay('nothing to search.', 'empty');
    return;
  }

  const rows = await query(
    'SELECT b.rowid AS rowid, b.board_id, b.layer, b.sublayer, b.name, ' +
      '       b.vendor, b.mcu, b.architecture, b.bit_width, ' +
      '       b.frequency_mhz, b.flash_kb, b.ram_kb, ' +
      '       b.upload_speed, b.core, b.variant, b.homepage, ' +
      '       b.frameworks, b.connectivity, b.vidpids, b.upstream_blob ' +
      'FROM boards b JOIN boards_fts f ON f.rowid = b.rowid ' +
      'WHERE boards_fts MATCH ? ORDER BY b.name COLLATE NOCASE LIMIT 20',
    [fts],
  );
  const nameLc = q.toLowerCase();
  const boards = rows.map((row) => ({
    row,
    score: Math.max(scoreName(row.name, nameLc), scoreName(row.board_id, nameLc)),
    why: 'name',
  }));
  boards.sort(
    (a, b) => b.score - a.score || a.row.name.localeCompare(b.row.name),
  );
  renderCombined(q, { boards });
}
