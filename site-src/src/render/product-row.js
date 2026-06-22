import { escapeHtml } from '../util/escape.js';
import { fmtPair, fmtSrc } from './fmt.js';

export function renderProductRow(r) {
  const alt =
    r.is_primary === 0
      ? ' <span class="src" style="color:#c44">(alternate)</span>'
      : '';
  return (
    `<div class="hit">${fmtPair(r.vid, r.pid)} &mdash; ` +
    `<span class="v">${escapeHtml(r.product)}</span>${alt}${fmtSrc(r.source)}</div>`
  );
}
