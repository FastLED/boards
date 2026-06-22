// "Products" mode UI wrapper. See engine.js for the actual lookup
// (exact VID:PID b-tree + FTS5 prefix + FTS5 name search). This file
// just runs the pure search against the singleton query() and renders.

import { query } from '../db.js';
import { hideUniOverlay, renderCombined } from '../render/overlay.js';
import { searchProduct } from './engine.js';

export async function productOnly(raw) {
  const q = (raw || '').trim();
  if (!q) {
    hideUniOverlay();
    return;
  }
  const data = await searchProduct(q, query);
  renderCombined(q, data);
}
