// The search results panel rendered inline below the search controls.

import { escapeHtml } from '../util/escape.js';
import { renderBestRow } from './best-row.js';
import { renderVendorRow } from './vendor-row.js';
import { renderProductRow } from './product-row.js';
import { renderBoardRow } from './board-row.js';
import { renderPreviewRow } from './preview-row.js';
import { openBoardJson } from '../modal/board-json.js';
import { wireBoardDefineButtons } from '../modal/board-defines.js';

const $ = (id) => document.getElementById(id);
const RESULTS_CLASS = 'uni-results';

export function showUniOverlay(html, kind) {
  const out = $('uniOut');
  out.className = RESULTS_CLASS + (kind ? ' ' + kind : '');
  out.innerHTML = html;
  out.removeAttribute('hidden');
}

export function hideUniOverlay() {
  const out = $('uniOut');
  out.setAttribute('hidden', '');
  out.innerHTML = '';
}

export function showSearchIntro() {
  const template = $('searchIntroTemplate');
  if (!template) {
    hideUniOverlay();
    return;
  }
  showUniOverlay(template.innerHTML.trim(), 'intro');
}

export function showQueuedSearch(query) {
  const label = query ? `Queued "${escapeHtml(query)}"` : 'Preparing search';
  showUniOverlay(
    '<div class="spinner-row" role="status" aria-live="polite">' +
      '<span class="spinner" aria-hidden="true"></span>' +
      `<span>${label}; database is still loading.</span>` +
    '</div>',
    'loading queued',
  );
}

/**
 * Show a small spinner inside the results panel while the search awaits.
 * Placed where the results will eventually land so the user's gaze
 * stays in one spot.
 */
export function showUniOverlaySpinner() {
  showUniOverlay(
    '<div class="spinner-row" role="status" aria-live="polite">' +
      '<span class="spinner" aria-hidden="true"></span>' +
      '<span>Searching...</span>' +
    '</div>',
    'loading',
  );
}

function renderNoResults(query, mode) {
  const modeText = {
    board: 'No board definitions matched.',
    vendor: 'No USB vendor IDs matched.',
    product: 'No USB product IDs matched.',
    anything: 'No vendors, products, or boards matched.',
  }[mode] || 'No matches.';

  return (
    '<div class="search-empty" role="status" aria-live="polite">' +
    `<h3>No matches for "${escapeHtml(query)}"</h3>` +
    `<p>${modeText} Try a USB VID, VID:PID, board id, MCU, framework, or connectivity term.</p>` +
    '<div class="example-row" aria-label="Example searches">' +
    '<code>303a</code><code>303a:1001</code><code>espressif</code><code>wifi</code><code>cortex-m7</code>' +
    '</div>' +
    '</div>'
  );
}

function totalFor(meta, key, loaded) {
  const total = Number(meta?.[key]?.total || 0);
  return Math.max(total, loaded);
}

function renderCategory({ label, key, hits, limit, render, query, meta }) {
  if (!hits.length) return '';
  const total = totalFor(meta, key, hits.length);
  const loaded = hits.length;
  const capped = hits.slice(0, limit);
  const rest = hits.slice(limit);
  const detail =
    total > loaded
      ? ` <span class="cat-detail">showing first ${loaded.toLocaleString()} of ${total.toLocaleString()}</span>`
      : '';

  let html = `<div class="cat"><div class="cat-head">${label} (${total.toLocaleString()})${detail}</div>`;
  for (const h of capped) html += render(h, query);
  if (rest.length) {
    html +=
      `<details class="more-results"><summary>Show ${rest.length.toLocaleString()} more loaded results</summary>`;
    for (const h of rest) html += render(h, query);
    html += '</details>';
  }
  if (total > loaded) {
    html += '<div class="stat">More matches exist in the database; refine the query to narrow the result set.</div>';
  }
  html += '</div>';
  return html;
}

function bestSort(a, b) {
  const aExact = a.reason?.strength === 'exact' || a.reason?.exact;
  const bExact = b.reason?.strength === 'exact' || b.reason?.exact;
  if (aExact !== bExact) return aExact ? -1 : 1;
  const kindOrder = { vendor: 0, board: 1, product: 2 };
  return (
    b.score - a.score ||
    (kindOrder[a.kind] ?? 9) - (kindOrder[b.kind] ?? 9)
  );
}

/**
 * Render any combination of categories into the results panel. Single-mode
 * searches leave the other arrays empty. Best Hits is a score-ranked
 * union threshold-filtered to >= 600.
 *
 * @param {string} query
 * @param {{previews?: Array, vendors?: Array, products?: Array, boards?: Array, meta?: Object}} cats
 * @param {string} mode
 */
export function renderCombined(
  query,
  { previews = [], vendors = [], products = [], boards = [], meta = {} },
  mode = 'anything',
) {
  if (!previews.length && !vendors.length && !products.length && !boards.length) {
    showUniOverlay(renderNoResults(query, mode), 'empty');
    return;
  }

  const best = [
    ...vendors.map((h) => ({ kind: 'vendor', ...h })),
    ...boards.map((h) => ({ kind: 'board', ...h })),
    ...products.map((h) => ({ kind: 'product', ...h })),
  ]
    .filter((h) => h.score >= 600)
    .sort(bestSort)
    .slice(0, 6);

  let html = '';
  if (previews.length) {
    html += '<div class="cat previews"><div class="cat-head">Preview</div>';
    for (const preview of previews) html += renderPreviewRow(preview, query);
    html += '</div>';
  }

  if (best.length) {
    html += '<div class="cat best"><div class="cat-head">Best hits</div>';
    for (const h of best) html += renderBestRow(h, query);
    html += '</div>';
  }

  html += renderCategory({
    label: 'Boards',
    key: 'boards',
    hits: boards,
    limit: 15,
    render: renderBoardRow,
    query,
    meta,
  });
  html += renderCategory({
    label: 'USB Vendors / VID',
    key: 'vendors',
    hits: vendors,
    limit: 15,
    render: renderVendorRow,
    query,
    meta,
  });
  html += renderCategory({
    label: 'USB Products / VID:PID',
    key: 'products',
    hits: products,
    limit: 25,
    render: renderProductRow,
    query,
    meta,
  });

  showUniOverlay(html);

  // Wire up the View JSON buttons that landed in the results panel.
  $('uniOut')
    .querySelectorAll('button[data-json-url]')
    .forEach((btn) => {
      btn.addEventListener('click', () =>
        openBoardJson(btn.getAttribute('data-json-url'), btn.getAttribute('data-title')),
      );
    });
  wireBoardDefineButtons($('uniOut'));
}
