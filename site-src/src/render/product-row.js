import { escapeHtml } from '../util/escape.js';
import { fmtPair, fmtSrc } from './fmt.js';
import {
  fieldClass,
  hitClasses,
  highlightText,
  reasonBadge,
  unwrapHit,
} from './match.js';

function renderLinkedBoardSummary(hit) {
  const linked = hit?.linkedBoards;
  if (!linked?.total) return '';
  const label = linked.total === 1 ? '1 linked board' : `${linked.total} linked boards`;
  const sample = linked.sample?.length
    ? `: ${linked.sample.map((b) => escapeHtml(b.board_id)).join(', ')}`
    : '';
  return `<span class="linked-summary">${label}${sample}</span>`;
}

export function renderProductRow(hit, query = '') {
  const r = unwrapHit(hit);
  const reason = hit?.reason;
  const alt =
    r.is_primary === 0
      ? ' <span class="src" style="color:#c44">(alternate)</span>'
      : '';
  return (
    `<div class="${hitClasses(hit, 'hit')}">${fmtPair(r.vid, r.pid, fieldClass(hit, 'vidpid'))} &mdash; ` +
    `<span class="v">${highlightText(r.product, query, [reason?.value])}</span>` +
    `${alt}${reasonBadge(hit)}${renderLinkedBoardSummary(hit)}${fmtSrc(r.source)}</div>`
  );
}
