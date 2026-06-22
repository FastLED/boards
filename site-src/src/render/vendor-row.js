import { escapeHtml } from '../util/escape.js';
import { fmtVid, fmtSrc } from './fmt.js';

export function renderVendorRow(r) {
  return (
    `<div class="hit">${fmtVid(r.vid)} &mdash; ` +
    `<span class="v">${escapeHtml(r.vendor)}</span>${fmtSrc(r.source)}</div>`
  );
}
