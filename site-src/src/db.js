// Legacy singleton wrapper. Existing callers (main.js + the search/*
// UI wrappers) import { openDb, query } from this file. Internally we
// now delegate to the modular db/index.js so the same logic powers
// both the browser and the Bun-backed Node test CLI.
//
// New code should prefer importing from './db/index.js' directly and
// holding its own db instance instead of mutating module state.

import { openDb as _openDb } from './db/index.js';

let _db = null;

/**
 * Open the published SQLite database.
 *
 * @param {string} url        absolute or relative URL of boards.db
 * @param {object} [options]
 * @param {number} [options.maxPageSize=1024]
 * @param {number} [options.cacheSize=8192]
 * @param {number} [options.timeout=30000]
 */
export async function openDb(url, options = {}) {
  _db = await _openDb({ source: url, options });
}

/**
 * Run a SQL query and return rows as plain objects.
 *
 * @param {string} sql
 * @param {any[]|object} [bind]
 * @returns {Promise<object[]>}
 */
export async function query(sql, bind) {
  if (!_db) throw new Error('db: openDb() not called yet');
  return _db.query(sql, bind);
}

/** Close the active backend. Mostly for tests / clean shutdown. */
export async function closeDb() {
  if (_db) {
    await _db.close();
    _db = null;
  }
}
