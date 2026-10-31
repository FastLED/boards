import { escapeHtml } from '../util/escape.js';
import { fmtKb } from './fmt.js';
import {
  fieldClass,
  getReason,
  hitClasses,
  highlightText,
  reasonBadge,
  unwrapHit,
} from './match.js';

function csvChips(csv, kind, hit, field) {
  if (!csv) return '';
  const reason = getReason(hit);
  const reasonValue = String(reason?.value || '').toLowerCase();
  return csv
    .split(',')
    .map((s) => {
      const text = s.trim();
      const matched =
        reason?.field === field &&
        reasonValue &&
        text.toLowerCase().includes(reasonValue);
      const cls = `board-chip board-chip-${kind}${matched ? ' field-hit' : ''}`;
      return `<span class="${cls}">${escapeHtml(text)}</span>`;
    })
    .join('');
}

const VENDOR_PREFIX_SEPARATORS = /^[\s:|/._\-\u00b7\u2022\u2013\u2014]+/u;

export function displayBoardName(b) {
  const name = (b.name || '').trim();
  const vendor = (b.vendor || '').trim();
  if (!name || !vendor) return name;

  const candidate = name.slice(0, vendor.length);
  if (candidate.toLocaleLowerCase() !== vendor.toLocaleLowerCase()) return name;

  const suffix = name.slice(vendor.length);
  if (!suffix || !VENDOR_PREFIX_SEPARATORS.test(suffix)) return name;

  const stripped = suffix.replace(VENDOR_PREFIX_SEPARATORS, '').trim();
  return stripped || name;
}

function matchedMeta(hit, field, value) {
  if (!value) return null;
  const extraClass = fieldClass(hit, field).trim();
  const text = escapeHtml(value);
  return extraClass ? `<span class="${extraClass}">${text}</span>` : text;
}

/**
 * Render one board row with all structured fields inline (chips for
 * frameworks + connectivity; mcu / freq / flash / ram / vidpids; View
 * JSON + defines + homepage + source buttons).
 */
export function renderBoardRow(hit, query = '') {
  const b = unwrapHit(hit);
  const reason = getReason(hit);
  const vendor = b.vendor ? `<span>${escapeHtml(b.vendor)}</span> &middot; ` : '';
  const name = displayBoardName(b);

  const meta = [];
  const mcu = matchedMeta(hit, 'mcu', b.mcu);
  const architecture = matchedMeta(hit, 'architecture', b.architecture);
  const vidpids = matchedMeta(hit, 'vidpids', b.vidpids);
  if (mcu) meta.push(mcu);
  if (architecture) meta.push(architecture);
  if (b.bit_width) meta.push(`${b.bit_width}-bit`);
  if (b.frequency_mhz) meta.push(`${b.frequency_mhz} MHz`);
  if (b.flash_kb) meta.push(`${fmtKb(b.flash_kb)} flash`);
  if (b.ram_kb) meta.push(`${fmtKb(b.ram_kb)} RAM`);
  if (vidpids) meta.push(vidpids);
  const metaStr = meta.length
    ? `<div class="board-meta">${meta.join(' &middot; ')}</div>`
    : '';

  const chips =
    csvChips(b.frameworks, 'fw', hit, 'frameworks') +
    csvChips(b.connectivity, 'conn', hit, 'connectivity');
  const chipsRow = chips ? `<div class="board-chip-row">${chips}</div>` : '';

  const layerChip =
    `<span class="board-chip${fieldClass(hit, 'layer')}">` +
    `${escapeHtml(b.layer)}/${escapeHtml(b.sublayer)}</span>`;

  const jsonUrl =
    `boards/${encodeURIComponent(b.layer)}/` +
    b.sublayer.split('/').map(encodeURIComponent).join('/') +
    `/boards/${encodeURIComponent(b.board_id)}.json`;
  const title = `${b.layer}/${b.sublayer}/boards/${b.board_id}.json`;

  const viewBtn =
    `<button class="btn" data-json-url="${escapeHtml(jsonUrl)}" ` +
    `data-title="${escapeHtml(title)}">View JSON</button>`;
  const definesBtn =
    `<button class="btn secondary" data-defines-url="${escapeHtml(jsonUrl)}" ` +
    `data-title="${escapeHtml(title)}">View Defines</button>`;

  const srcBtn = b.upstream_blob
    ? `<a class="btn secondary" href="${escapeHtml(b.upstream_blob)}" target="_blank" rel="noopener">source</a>`
    : '';
  const homepageBtn = b.homepage
    ? `<a class="btn secondary" href="${escapeHtml(b.homepage)}" target="_blank" rel="noopener">homepage</a>`
    : '';
  const actions = `<div class="board-actions">${viewBtn}${definesBtn}${homepageBtn}${srcBtn}</div>`;

  return (
    `<div class="${hitClasses(hit, 'board-row')}">` +
    `<div class="board-main">${layerChip}${vendor}` +
    `<span class="board-name${fieldClass(hit, 'name')}">${highlightText(name, query, [reason?.value])}</span> ` +
    `<span class="board-meta${fieldClass(hit, 'board_id')}">(${escapeHtml(b.board_id)})</span>` +
    `${reasonBadge(hit)}` +
    `${metaStr}${chipsRow}</div>` +
    `${actions}</div>`
  );
}
