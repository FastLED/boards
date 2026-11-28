import { fmtVid, fmtPair, fmtSrc } from './fmt.js';
import { renderBoardRow } from './board-row.js';
import {
  fieldClass,
  hitClasses,
  highlightText,
  reasonBadge,
} from './match.js';

/**
 * Render a single Best-Hits row. Board hits reuse the full board row so
 * they keep View JSON / View Defines / homepage actions.
 */
const KIND_LABEL = {
  vendor: 'USB VID',
  product: 'USB VID:PID',
  board: 'board',
};

export function renderBestRow(h, query = '') {
  if (h.kind === 'board') return renderBoardRow(h, query);

  const label = KIND_LABEL[h.kind] || h.kind;
  const tag = `<span class="tag ${h.kind}">${label}</span>`;
  const reason = h.reason;

  if (h.kind === 'vendor') {
    return (
      `<div class="${hitClasses(h, 'hit')}">${tag}` +
      `${fmtVid(h.row.vid, fieldClass(h, 'vid'))} &mdash; ` +
      `<span class="v">${highlightText(h.row.vendor, query, [reason?.value])}</span>` +
      `${reasonBadge(h)}${fmtSrc(h.row.source)}</div>`
    );
  }

  const alt =
    h.row.is_primary === 0
      ? ' <span class="src" style="color:#c44">(alternate)</span>'
      : '';
  return (
    `<div class="${hitClasses(h, 'hit')}">${tag}` +
    `${fmtPair(h.row.vid, h.row.pid, fieldClass(h, 'vidpid'))} &mdash; ` +
    `<span class="v">${highlightText(h.row.product, query, [reason?.value])}</span>` +
    `${alt}${reasonBadge(h)}${fmtSrc(h.row.source)}</div>`
  );
}
