import { escapeHtml } from '../util/escape.js';
import { fmtVid, fmtPair, fmtSrc } from './fmt.js';

/**
 * Render a single Best-Hits row. Hits can be vendors, products, or boards;
 * each gets a coloured kind-tag.
 */
export function renderBestRow(h) {
  const tag = `<span class="tag ${h.kind}">${h.kind}</span>`;
  const why = h.why ? `<span class="why">${escapeHtml(h.why)}</span>` : '';

  if (h.kind === 'vendor') {
    return (
      `<div class="hit">${tag}${fmtVid(h.row.vid)} &mdash; ` +
      `<span class="v">${escapeHtml(h.row.vendor)}</span>${why}${fmtSrc(h.row.source)}</div>`
    );
  }
  if (h.kind === 'board') {
    const meta = h.row.mcu
      ? ` <span class="board-meta">${escapeHtml(h.row.mcu)}` +
        (h.row.frequency_mhz ? ` · ${h.row.frequency_mhz} MHz` : '') +
        `</span>`
      : '';
    return (
      `<div class="hit">${tag}<span class="k">${escapeHtml(h.row.layer)}/${escapeHtml(h.row.sublayer)}</span> &mdash; ` +
      `<span class="v">${escapeHtml(h.row.name)}</span>` +
      ` <span class="board-meta">(${escapeHtml(h.row.board_id)})</span>${meta}${why}</div>`
    );
  }
  // product
  const alt =
    h.row.is_primary === 0
      ? ' <span class="src" style="color:#c44">(alternate)</span>'
      : '';
  return (
    `<div class="hit">${tag}${fmtPair(h.row.vid, h.row.pid)} &mdash; ` +
    `<span class="v">${escapeHtml(h.row.product)}</span>${alt}${why}${fmtSrc(h.row.source)}</div>`
  );
}
