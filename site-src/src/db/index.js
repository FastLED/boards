// Runtime-agnostic DB factory. Picks an adapter based on (a) the
// source (URL vs. path/buffer) and (b) the host (browser vs. Bun/Node).
//
//   const db = await openDb({ source: 'boards.db' });        // browser
//   const db = await openDb({ source: '/tmp/x.db' });        // Bun/Node
//   const db = await openDb({ source: 'https://…/x.db' });    // either
//   await db.query(sql, bind);  // -> Promise<Object[]>
//   await db.close();
//
// Policy:
//   - Bun/Node (any source)             → memory.js (bun:sqlite native)
//   - Browser + URL + Accept-Ranges:bytes → http-range.js (sqlite-wasm-http)
//   - Browser + URL + no Range           → memory.js (full download + warn)
//   - Browser + path/buffer              → memory.js
//
// `force` lets callers pin a backend ('memory' | 'http-range') and skip
// the auto-pick — handy for unit-testing the fallback path explicitly.

const IS_BROWSER = typeof window !== 'undefined' && typeof document !== 'undefined';

function _isUrl(source) {
  return typeof source === 'string' && /^https?:\/\//i.test(source);
}

async function _rangeOk(url) {
  try {
    const r = await fetch(url, { method: 'HEAD' });
    if (!r.ok) return false;
    const ar = (r.headers.get('accept-ranges') || '').toLowerCase();
    return ar === 'bytes';
  } catch {
    return false;
  }
}

export async function openDb({ source, force = null, options = {} } = {}) {
  if (source == null) throw new Error('openDb: source is required');

  // Non-browser hosts (Bun / Node): memory adapter always. URLs get
  // a full download with a console.warn since we don't do range there.
  if (!IS_BROWSER) {
    if (force === 'http-range') {
      throw new Error('openDb: http-range adapter is browser-only');
    }
    const { openMemoryDb } = await import('./memory.js');
    return openMemoryDb(source, options);
  }

  // Browser path.
  if (force === 'memory' || !_isUrl(source)) {
    const { openMemoryDb } = await import('./memory.js');
    return openMemoryDb(source, options);
  }
  if (force === 'http-range' || await _rangeOk(source)) {
    const { openHttpRangeDb } = await import('./http-range.js');
    return openHttpRangeDb(source, options);
  }
  console.warn(
    `[db] ${source} does not advertise Accept-Ranges: bytes; falling back to ` +
    `full-download + in-memory open. For a smaller initial payload, ` +
    `configure the host to send Accept-Ranges: bytes.`,
  );
  const { openMemoryDb } = await import('./memory.js');
  return openMemoryDb(source, options);
}
