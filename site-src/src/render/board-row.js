import { escapeHtml } from '../util/escape.js';
import { fmtKb } from './fmt.js';

function csvChips(csv, kind) {
  if (!csv) return '';
  return csv
    .split(',')
    .map(
      (s) =>
        `<span class="board-chip board-chip-${kind}">${escapeHtml(s.trim())}</span>`,
    )
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

/**
 * Render one board row with all structured fields inline (chips for
 * frameworks + connectivity; mcu / freq / flash / ram / vidpids; View
 * JSON + homepage + source buttons).
 */
export function renderBoardRow(b) {
  const vendor = b.vendor ? `<span>${escapeHtml(b.vendor)}</span> · ` : '';
  const name = displayBoardName(b);

  const meta = [];
  if (b.mcu) meta.push(escapeHtml(b.mcu));
  if (b.architecture) meta.push(escapeHtml(b.architecture));
  if (b.bit_width) meta.push(`${b.bit_width}-bit`);
  if (b.frequency_mhz) meta.push(`${b.frequency_mhz} MHz`);
  if (b.flash_kb) meta.push(`${fmtKb(b.flash_kb)} flash`);
  if (b.ram_kb) meta.push(`${fmtKb(b.ram_kb)} RAM`);
  if (b.vidpids) meta.push(escapeHtml(b.vidpids));
  const metaStr = meta.length
    ? `<div class="board-meta">${meta.join(' · ')}</div>`
    : '';

  const chips = csvChips(b.frameworks, 'fw') + csvChips(b.connectivity, 'conn');
  const chipsRow = chips ? `<div class="board-chip-row">${chips}</div>` : '';

  const layerChip = `<span class="board-chip">${escapeHtml(b.layer)}/${escapeHtml(b.sublayer)}</span>`;

  const jsonUrl =
    `boards/${encodeURIComponent(b.layer)}/` +
    b.sublayer.split('/').map(encodeURIComponent).join('/') +
    `/boards/${encodeURIComponent(b.board_id)}.json`;
  const title = `${b.layer}/${b.sublayer}/boards/${b.board_id}.json`;

  const viewBtn =
    `<button class="btn" data-json-url="${escapeHtml(jsonUrl)}" ` +
    `data-title="${escapeHtml(title)}">View JSON</button>`;

  const srcBtn = b.upstream_blob
    ? `<a class="btn secondary" href="${escapeHtml(b.upstream_blob)}" target="_blank" rel="noopener">↗ source</a>`
    : '';
  const homepageBtn = b.homepage
    ? `<a class="btn secondary" href="${escapeHtml(b.homepage)}" target="_blank" rel="noopener">↗ homepage</a>`
    : '';

  return (
    `<div class="board-row">` +
    `<div class="board-main">${layerChip}${vendor}` +
    `<span class="board-name">${escapeHtml(name)}</span> ` +
    `<span class="board-meta">(${escapeHtml(b.board_id)})</span>` +
    `${metaStr}${chipsRow}</div>` +
    `<div class="board-spacer"></div>${viewBtn}${homepageBtn}${srcBtn}</div>`
  );
}
