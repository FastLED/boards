// Portal entry point. Wires:
//   - styles (Vite injects them into the bundle)
//   - DB init via sqlite-wasm-http (Accept-Encoding: identity baked in)
//   - search-mode dispatch on input/dropdown change
//   - inline results UX (Esc dismiss + focus/click reopen)
//   - View JSON modal close handlers

import './style/base.css';
import './style/search.css';
import './style/board-row.css';
import './style/modal.css';
import './style/help.css';

import { openDb, query } from './db.js';
import { escapeHtml } from './util/escape.js';
import { universalSearch } from './search/universal.js';
import { vendorOnly } from './search/vendor.js';
import { productOnly } from './search/product.js';
import { boardOnly } from './search/board.js';
import { hideUniOverlay, showQueuedSearch, showSearchIntro } from './render/overlay.js';
import { closeBoardJson, isBoardJsonOpen } from './modal/board-json.js';
import { closeBoardDefines, isBoardDefinesOpen } from './modal/board-defines.js';

const $ = (id) => document.getElementById(id);

let dbReady = false;
/** @type {{ q: string, mode: string } | null} */
let pendingQuery = null;

function modeFn(mode) {
  switch (mode) {
    case 'board':
      return boardOnly;
    case 'vendor':
      return vendorOnly;
    case 'product':
      return productOnly;
    case 'anything':
    default:
      return universalSearch;
  }
}

function runCurrentSearch() {
  const q = $('uniIn').value;
  const mode = $('modeIn').value;
  if (!dbReady) {
    pendingQuery = { q, mode };
    if (q.trim()) showQueuedSearch(q.trim());
    else showSearchIntro();
    return;
  }
  modeFn(mode)(q).catch((err) => console.error(err));
}

function replayPending() {
  if (pendingQuery && pendingQuery.q) {
    modeFn(pendingQuery.mode)(pendingQuery.q).catch((err) => console.error(err));
  }
  pendingQuery = null;
}

function debounced(fn, ms = 120) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

async function init() {
  try {
    // Two parallel fetches: meta (cheap, gives counts without COUNT(*))
    // and the DB worker (downloads sqlite3.wasm + opens via Range).
    const metaPromise = fetch('_meta.json', { cache: 'no-cache' })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);

    const url = new URL('boards.db', location.href).href;
    const dbPromise = openDb(url, { maxPageSize: 1024, cacheSize: 8192 });

    // Wire UI before the DB resolves so typing-while-loading is replayed.
    wireUp();

    const [meta] = await Promise.all([metaPromise, dbPromise]);
    dbReady = true;

    const t = (meta && meta.totals) || {};
    const countOrFallback = async (sql, fallback) => {
      try {
        return Number((await query(sql))[0].n || 0);
      } catch {
        return Number(fallback || 0);
      }
    };
    const [cv, cp, bc] = await Promise.all([
      countOrFallback('SELECT COUNT(*) AS n FROM vid_vendor', t.vendors),
      countOrFallback('SELECT COUNT(*) AS n FROM vidpid', t.vidpid_rows || t.vidpid_keys),
      countOrFallback('SELECT COUNT(*) AS n FROM boards', t.boards),
    ]);

    $('dbStatus').textContent = 'database loaded (HTTP range-fetched)';
    $('dbCounts').textContent =
      `${cv.toLocaleString()} USB vendors / ` +
      `${cp.toLocaleString()} USB products / ` +
      `${bc.toLocaleString()} boards`;

    replayPending();
  } catch (e) {
    $('dbStatus').innerHTML = `<span class="err">failed: ${escapeHtml(e.message)}</span>`;
    console.error(e);
  }
}

function wireUp() {
  const debouncedRun = debounced(runCurrentSearch);
  $('uniIn').addEventListener('input', debouncedRun);
  $('modeIn').addEventListener('change', runCurrentSearch);

  // View JSON modal close handlers
  $('boardJsonClose').addEventListener('click', () => closeBoardJson());
  $('boardJsonModal').addEventListener('click', (e) => {
    if (e.target.id === 'boardJsonModal') closeBoardJson();
  });

  showSearchIntro();

  // Results UX: Esc dismiss; focus / click reopen
  $('uniIn').addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('uniOut').hasAttribute('hidden')) {
      hideUniOverlay();
      e.stopPropagation();
    }
  });
  const reshowIfRelevant = () => {
    const v = $('uniIn').value.trim();
    if (v && $('uniOut').hasAttribute('hidden')) {
      modeFn($('modeIn').value)(v).catch((err) => console.error(err));
    } else if (!v && $('uniOut').hasAttribute('hidden')) {
      showSearchIntro();
    }
  };
  $('uniIn').addEventListener('focus', reshowIfRelevant);
  $('uniIn').addEventListener('click', reshowIfRelevant);

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (isBoardDefinesOpen()) {
      closeBoardDefines();
      e.preventDefault();
      return;
    }
    if (isBoardJsonOpen()) {
      closeBoardJson();
      e.preventDefault();
      return;
    }
    if (!$('uniOut').hasAttribute('hidden')) {
      hideUniOverlay();
      e.preventDefault();
    }
  });

  $('uniIn').focus();
}

init();
