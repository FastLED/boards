// SQLite-over-HTTP wrapper. Opens the published `boards.db` via
// sqlite-wasm-http with Accept-Encoding: identity — see
// .extern-repos/memex/IMPLEMENT.md for why that header is the load-bearing
// piece of the whole pipeline.

import { createSQLiteThread, createHttpBackend } from 'sqlite-wasm-http';

let _db = null;
let _backend = null;
let _close = null;

/**
 * Open the published SQLite database.
 *
 * @param {string} url        absolute or relative URL of boards.db
 * @param {object} [options]
 * @param {number} [options.maxPageSize=1024]   must match the DB's PRAGMA page_size
 * @param {number} [options.cacheSize=8192]     KB of LRU page cache in the worker
 * @param {number} [options.timeout=30000]      HTTP request timeout (ms)
 */
export async function openDb(url, options = {}) {
  _backend = createHttpBackend({
    maxPageSize: options.maxPageSize ?? 1024,
    timeout: options.timeout ?? 30000,
    cacheSize: options.cacheSize ?? 8192,
    backendType: 'sync',
    // The critical line. Without it GH Pages returns the full gzipped
    // file with HTTP 200 even when Range was asked for; the library then
    // misreads pages and SQLite reports "database disk image is malformed".
    headers: { 'Accept-Encoding': 'identity' },
  });
  _db = await createSQLiteThread({ http: _backend });
  await _db('open', {
    filename: 'file:' + encodeURI(url),
    vfs: 'http',
  });
  _close = async () => {
    await _db('close', {});
    _db.close();
    await _backend.close();
  };
}

/**
 * Run a SQL query and return rows as plain objects.
 *
 *   const r = await query('SELECT a, b FROM t WHERE c = ?', [42]);
 *   // r === [{ a: 1, b: 2 }, ...]
 *
 * @param {string} sql
 * @param {any[]|object} [bind]
 * @returns {Promise<object[]>}
 */
export async function query(sql, bind) {
  if (!_db) throw new Error('db: openDb() not called yet');
  const columns = [];
  const rows = [];
  const hasBind =
    bind && (Array.isArray(bind) ? bind.length : Object.keys(bind).length);
  try {
    await _db('exec', {
      sql,
      bind: hasBind ? bind : undefined,
      callback: (msg) => {
        if (msg.row) {
          rows.push(msg.row);
          if (!columns.length && msg.columnNames) columns.push(...msg.columnNames);
        } else if (msg.columnNames && !columns.length) {
          columns.push(...msg.columnNames);
        }
      },
    });
  } catch (err) {
    // The promiser rejects with a {type:'error', result:{}} response
    // object that doesn't expose the underlying SQL error message. Log
    // the SQL + bind so the failing query is visible in the page console.
    console.error('db.query failed', { sql, bind, err });
    throw err;
  }
  return rows.map((r) => {
    const o = {};
    for (let i = 0; i < columns.length; i++) o[columns[i]] = r[i];
    return o;
  });
}

/** Close the worker + backend. Mostly for tests / clean shutdown. */
export async function closeDb() {
  if (_close) await _close();
  _db = null;
  _backend = null;
  _close = null;
}
