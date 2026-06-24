// "Anything" mode UI wrapper. Pure search logic lives in engine.js;
// this file just runs the engine against the singleton query() and
// hands the result to renderCombined().

import { query } from '../db.js';
import {
  renderCombined,
  showSearchIntro,
  showUniOverlaySpinner,
} from '../render/overlay.js';
import { searchUniversal } from './engine.js';

export async function universalSearch(raw) {
  const q = (raw || '').trim();
  if (!q) {
    showSearchIntro();
    return;
  }
  showUniOverlaySpinner();
  const data = await searchUniversal(q, query);
  renderCombined(q, data);
}
