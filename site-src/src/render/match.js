import { escapeHtml } from '../util/escape.js';

const CLASS_TOKEN_RE = /[^a-z0-9_-]+/gi;

export function unwrapHit(hitOrRow) {
  return hitOrRow && hitOrRow.row ? hitOrRow.row : hitOrRow;
}

export function getReason(hitOrRow) {
  if (!hitOrRow) return null;
  if (hitOrRow.reason) return hitOrRow.reason;
  if (hitOrRow.why) return { label: hitOrRow.why };
  return null;
}

export function hitClasses(hitOrRow, base) {
  const reason = getReason(hitOrRow);
  const classes = [base, 'search-hit'];
  if (reason?.strength === 'exact' || reason?.exact) classes.push('exact-hit');
  if (reason?.field) {
    classes.push(`field-${String(reason.field).replace(CLASS_TOKEN_RE, '-')}`);
  }
  return classes.join(' ');
}

export function reasonBadge(hitOrRow) {
  const reason = getReason(hitOrRow);
  if (!reason?.label) return '';
  const exact = reason.strength === 'exact' || reason.exact ? ' exact' : '';
  const value = reason.value ? ` <span>${escapeHtml(String(reason.value))}</span>` : '';
  return `<span class="match-reason${exact}">${escapeHtml(reason.label)}${value}</span>`;
}

export function fieldClass(hitOrRow, field) {
  const reason = getReason(hitOrRow);
  return reason?.field === field ? ' field-hit' : '';
}

function uniqueNeedles(query, values = []) {
  const needles = [];
  for (const raw of [query, ...values]) {
    const text = String(raw || '').trim();
    if (!text) continue;
    for (const part of text.split(/[\s:._/-]+/)) {
      if (part.length >= 2 && !needles.includes(part.toLowerCase())) {
        needles.push(part.toLowerCase());
      }
    }
  }
  return needles.sort((a, b) => b.length - a.length);
}

export function highlightText(value, query, values = []) {
  const text = String(value || '');
  const needles = uniqueNeedles(query, values);
  if (!needles.length) return escapeHtml(text);

  const spans = [];
  const lower = text.toLowerCase();
  let index = 0;
  while (index < text.length) {
    let match = null;
    for (const needle of needles) {
      if (lower.startsWith(needle, index)) {
        match = needle;
        break;
      }
    }
    if (!match) {
      spans.push(escapeHtml(text[index]));
      index += 1;
      continue;
    }
    spans.push(`<mark>${escapeHtml(text.slice(index, index + match.length))}</mark>`);
    index += match.length;
  }
  return spans.join('');
}
