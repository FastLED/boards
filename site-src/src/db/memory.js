// Memory adapter — opens a SQLite DB from a path, URL (full
// download), or in-memory buffer.
//
// Backend pick:
//   - Bun       → bun:sqlite (native, zero deps)
//   - Browser   → not yet wired (will throw with TODO message). Adding
//     sql.js as a bundled fallback is straightforward but adds ~300 KB
//     of WASM and Vite serve config; deferred until the fallback path
//     actually triggers in the wild.
//
// Same { query, close } shape as http-range.js.

const IS_BUN = typeof globalThis.Bun !== 'undefined';
const IS_BROWSER =
  typeof window !== 'undefined' && typeof document !== 'undefined';

function _isUrl(s) {
  return typeof s === 'string' && /^https?:\/\//i.test(s);
}

async function _readToBuffer(source) {
  // URL: full download (no Range — that's what http-range.js is for).
  if (_isUrl(source)) {
    const resp = await fetch(source, {
      headers: { 'Accept-Encoding': 'identity' },
    });
    if (!resp.ok) {
      throw new Error(`openMemoryDb: fetch ${source}: ${resp.status} ${resp.statusText}`);
    }
    return new Uint8Array(await resp.arrayBuffer());
  }
  if (source instanceof Uint8Array) return source;
  if (source instanceof ArrayBuffer) return new Uint8Array(source);
  // Path: caller-provided file path — only meaningful outside the
  // browser; let the host-specific code (Bun) handle that directly.
  return null;
}

export async function openMemoryDb(source, options = {}) {
  if (IS_BUN) {
    // String-concat to hide `bun:sqlite` and `node:*` imports from
    // Vite/Rollup's static analyzer. The browser bundle never
    // executes this branch, but Rollup still tries to *resolve* the
    // import specifier at build time unless we obscure it.
    const { Database } = await import(/* @vite-ignore */ 'bun' + ':sqlite');
    const fs       = await import(/* @vite-ignore */ 'node' + ':fs');
    const os       = await import(/* @vite-ignore */ 'node' + ':os');
    const pathlib  = await import(/* @vite-ignore */ 'node' + ':path');

    let filePath = null;
    let tmpToClean = null;

    if (_isUrl(source) || source instanceof Uint8Array || source instanceof ArrayBuffer) {
      const buf = await _readToBuffer(source);
      const tmp = pathlib.join(os.tmpdir(),
        `fastled-boards-mem-${process.pid}-${Date.now()}.db`);
      fs.writeFileSync(tmp, buf);
      filePath = tmp;
      tmpToClean = tmp;
    } else if (typeof source === 'string') {
      filePath = source;
    } else {
      throw new Error('openMemoryDb: source must be url, path, or Uint8Array');
    }

    const db = new Database(filePath, { readonly: true });
    return {
      backend: 'bun:sqlite',
      async query(sql, bind) {
        const stmt = db.prepare(sql);
        try {
          if (bind == null) return stmt.all();
          if (Array.isArray(bind)) return stmt.all(...bind);
          return stmt.all(bind);
        } catch (err) {
          console.error('db.query failed', { sql, bind, err: err.message });
          throw err;
        }
      },
      async close() {
        db.close();
        if (tmpToClean) {
          try { fs.unlinkSync(tmpToClean); } catch { /* best-effort */ }
        }
      },
    };
  }

  if (IS_BROWSER) {
    throw new Error(
      'openMemoryDb: browser memory fallback not implemented. ' +
      'Add sql.js as a dep and wire it here. The Range-fetch adapter ' +
      '(http-range.js) is the browser primary; this fallback only ' +
      'fires when the host omits Accept-Ranges: bytes.',
    );
  }

  // Plain Node (not Bun, not browser). Could add better-sqlite3 here
  // later; for now Bun is the supported runtime for headless tests.
  throw new Error(
    'openMemoryDb: this runtime is not supported. Use Bun for ' +
    'headless tests or run in a browser with http-range.js.',
  );
}
