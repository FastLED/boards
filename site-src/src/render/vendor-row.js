import { fmtVid, fmtSrc } from './fmt.js';
import {
  fieldClass,
  hitClasses,
  highlightText,
  reasonBadge,
  unwrapHit,
} from './match.js';

export function renderVendorRow(hit, query = '') {
  const r = unwrapHit(hit);
  const reason = hit?.reason;
  return (
    `<div class="${hitClasses(hit, 'hit')}">${fmtVid(r.vid, fieldClass(hit, 'vid'))} &mdash; ` +
    `<span class="v">${highlightText(r.vendor, query, [reason?.value])}</span>` +
    `${reasonBadge(hit)}${fmtSrc(r.source)}</div>`
  );
}
