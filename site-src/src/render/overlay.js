// The search results panel rendered inline below the search controls.

import { escapeHtml } from '../util/escape.js';
import { renderBestRow } from './best-row.js';
import { renderVendorRow } from './vendor-row.js';
import { renderProductRow } from './product-row.js';
import { renderBoardRow } from './board-row.js';
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

/**
 * Show a small spinner inside the results panel while the search awaits.
 * Placed where the results will eventually land so the user's gaze
 * stays in one spot — renderCombined() (or showUniOverlay('no
 * matches…')) overwrites the spinner the moment the query resolves.
 */
export function showUniOverlaySpinner() {
  showUniOverlay(
    '<div class="spinner-row" role="status" aria-live="polite">' +
      '<span class="spinner" aria-hidden="true"></span>' +
      '<span>Searching…</span>' +
    '</div>',
    'loading',
  );
}

function renderNoResults(query) {
  return (
    '<div class="search-empty" role="status" aria-live="polite">' +
    `<h3>No matches for "${escapeHtml(query)}"</h3>` +
    '<p>Try a USB vendor ID, a VID:PID pair, a board name, or a hardware term.</p>' +
    '<div class="example-row" aria-label="Example searches">' +
    '<code>303a</code><code>303a:1001</code><code>espressif</code><code>wifi</code><code>cortex-m7</code>' +
    '</div>' +
    '</div>'
  );
}

/**
 * Render any combination of categories into the results panel. Single-mode
 * searches leave the other arrays empty. Best Hits is a score-ranked
 * union threshold-filtered to ≥ 600.
 *
 * @param {string} query
 * @param {{vendors?: Array, products?: Array, boards?: Array}} cats
 */
export function renderCombined(query, { vendors = [], products = [], boards = [] }) {
  if (!vendors.length && !products.length && !boards.length) {
    showUniOverlay(renderNoResults(query), 'empty');
    return;
  }

  const best = [
    ...boards.map((h) => ({ kind: 'board', ...h })),
    ...vendors.map((h) => ({ kind: 'vendor', ...h })),
    ...products.map((h) => ({ kind: 'product', ...h })),
  ]
    .filter((h) => h.score >= 600)
    .sort((a, b) => b.score - a.score)
    .slice(0, 6);

  let html = '';
  if (best.length) {
    html += '<div class="cat best"><div class="cat-head">Best hits</div>';
    for (const h of best) html += renderBestRow(h);
    html += '</div>';
  }
  if (boards.length) {
    const capped = boards.slice(0, 15);
    const more = boards.length - capped.length;
    html += `<div class="cat"><div class="cat-head">Boards (${boards.length})</div>`;
    for (const h of capped) html += renderBoardRow(h.row);
    if (more > 0)
      html += `<div class="stat">…${more} more — refine the query for narrower results.</div>`;
    html += '</div>';
  }
  if (vendors.length) {
    const capped = vendors.slice(0, 15);
    const more = vendors.length - capped.length;
    html += `<div class="cat"><div class="cat-head">USB Vendors / VID (${vendors.length})</div>`;
    for (const h of capped) html += renderVendorRow(h.row);
    if (more > 0)
      html += `<div class="stat">…${more} more — refine the query.</div>`;
    html += '</div>';
  }
  if (products.length) {
    const capped = products.slice(0, 25);
    const more = products.length - capped.length;
    html += `<div class="cat"><div class="cat-head">USB Products / VID:PID (${products.length})</div>`;
    for (const h of capped) html += renderProductRow(h.row);
    if (more > 0)
      html += `<div class="stat">…${more} more — refine the query.</div>`;
    html += '</div>';
  }
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
