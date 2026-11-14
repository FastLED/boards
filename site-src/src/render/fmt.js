// Small formatting helpers shared by the row renderers.

import { escapeHtml } from '../util/escape.js';

function cls(base, extra) {
  return [base, extra].filter(Boolean).map((part) => part.trim()).join(' ');
}

export function fmtVid(v, extraClass = '') {
  return `<span class="${cls('k', extraClass)}">0x${escapeHtml(v)}</span>`;
}

export function fmtPair(v, p, extraClass = '') {
  return `<span class="${cls('k', extraClass)}">0x${escapeHtml(v)}:0x${escapeHtml(p)}</span>`;
}

export function fmtSrc(s) {
  return s ? `<span class="src">${escapeHtml(s)}</span>` : '';
}

/** Format a board memory size (KB → "4 MB" / "320 KB"). */
export function fmtKb(v) {
  if (!v) return null;
  if (v >= 1024) return `${(v / 1024).toFixed(v % 1024 === 0 ? 0 : 1)} MB`;
  return `${v} KB`;
}
