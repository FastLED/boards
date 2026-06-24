// "Boards" mode UI wrapper. See engine.js for the actual lookup
// (FTS5 against the boards table). This file handles the empty /
// too-short input UX feedback and renders the engine's result.

import { query } from '../db.js';
import {
  renderCombined,
  showSearchIntro,
  showUniOverlay,
  showUniOverlaySpinner,
} from '../render/overlay.js';
import { ftsQuery } from '../util/fts.js';
import { searchBoard } from './engine.js';

export async function boardOnly(raw) {
  const q = (raw || '').trim();
  if (!q) {
    showSearchIntro();
    return;
  }
  if (q.length < 2) {
    showUniOverlay('Enter at least 2 characters.', 'empty');
    return;
  }
  if (!ftsQuery(q)) {
    showUniOverlay('nothing to search.', 'empty');
    return;
  }
  showUniOverlaySpinner();
  const data = await searchBoard(q, query);
  renderCombined(q, data);
}
