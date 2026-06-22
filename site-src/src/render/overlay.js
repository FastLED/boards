// The result overlay anchored below the search input.

import { escapeHtml } from '../util/escape.js';
import { renderBestRow } from './best-row.js';
import { renderVendorRow } from './vendor-row.js';
import { renderProductRow } from './product-row.js';
import { renderBoardRow } from './board-row.js';
import { openBoardJson } from '../modal/board-json.js';

const $ = (id) => document.getElementById(id);

export function showUniOverlay(html, kind) {
  const out = $('uniOut');
  out.className = 'uni-overlay' + (kind ? ' ' + kind : '');
  out.innerHTML = html;
  out.removeAttribute('hidden');
}

export function hideUniOverlay() {
  const out = $('uniOut');
  out.setAttribute('hidden', '');
  out.innerHTML = '';
}

/**
 * Render any combination of categories into the overlay. Single-mode
 * searches leave the other arrays empty. Best Hits is a score-ranked
 * union threshold-filtered to ≥ 600.
 *
 * @param {string} query
 * @param {{vendors?: Array, products?: Array, boards?: Array}} cats
 */
export function renderCombined(query, { vendors = [], products = [], boards = [] }) {
  if (!vendors.length && !products.length && !boards.length) {
    showUniOverlay(`no matches for "${escapeHtml(query)}"`, 'empty');
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
    html += `<div class="cat"><div class="cat-head">Vendors (${vendors.length})</div>`;
    for (const h of capped) html += renderVendorRow(h.row);
    if (more > 0)
      html += `<div class="stat">…${more} more — refine the query.</div>`;
    html += '</div>';
  }
  if (products.length) {
    const capped = products.slice(0, 25);
    const more = products.length - capped.length;
    html += `<div class="cat"><div class="cat-head">Products (${products.length})</div>`;
    for (const h of capped) html += renderProductRow(h.row);
    if (more > 0)
      html += `<div class="stat">…${more} more — refine the query.</div>`;
    html += '</div>';
  }
  showUniOverlay(html);

  // Wire up the View JSON buttons that landed in the overlay.
  $('uniOut')
    .querySelectorAll('button[data-json-url]')
    .forEach((btn) => {
      btn.addEventListener('click', () =>
        openBoardJson(btn.getAttribute('data-json-url'), btn.getAttribute('data-title')),
      );
    });
}
