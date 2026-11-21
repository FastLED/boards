// "Vendors" mode UI wrapper. See engine.js for the actual lookup
// (exact-VID b-tree + FTS5 name match) — this file just runs the
// pure search against the singleton query() and renders the result.

import { query } from '../db.js';
import {
  renderCombined,
  showSearchIntro,
  showUniOverlaySpinner,
} from '../render/overlay.js';
import { searchVendor } from './engine.js';

export async function vendorOnly(raw, { shouldRender = () => true } = {}) {
  const q = (raw || '').trim();
  if (!q) {
    if (shouldRender()) showSearchIntro();
    return;
  }
  if (shouldRender()) showUniOverlaySpinner();
  const data = await searchVendor(q, query);
  if (shouldRender()) renderCombined(q, data, 'vendor');
}
