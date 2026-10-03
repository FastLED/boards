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

export async function boardOnly(raw, { shouldRender = () => true } = {}) {
  const q = (raw || '').trim();
  if (!q) {
    if (shouldRender()) showSearchIntro();
    return;
  }
  if (q.length < 2) {
    if (shouldRender()) showUniOverlay('Enter at least 2 characters.', 'empty');
    return;
  }
  if (!ftsQuery(q)) {
    if (shouldRender()) showUniOverlay('nothing to search.', 'empty');
    return;
  }
  if (shouldRender()) showUniOverlaySpinner();
  const data = await searchBoard(q, query);
  if (shouldRender()) renderCombined(q, data, 'board');
}
