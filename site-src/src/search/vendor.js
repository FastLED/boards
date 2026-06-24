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

export async function vendorOnly(raw) {
  const q = (raw || '').trim();
  if (!q) {
    showSearchIntro();
    return;
  }
  showUniOverlaySpinner();
  const data = await searchVendor(q, query);
  renderCombined(q, data);
}
