// HTTP-Range adapter (browser only). Wraps the existing
// sqlite-wasm-http worker so the portal can do byte-range fetches
// against a remote boards.db. Requires the host to send
// `Accept-Encoding: identity` + advertise `Accept-Ranges: bytes`.
//
// Exposes the same { query, close } shape as memory.js so callers
// pick freely between the two.

import { createSQLiteThread, createHttpBackend } from 'sqlite-wasm-http';

export async function openHttpRangeDb(url, options = {}) {
  const backend = createHttpBackend({
    maxPageSize: options.maxPageSize ?? 1024,
    timeout:     options.timeout     ?? 30000,
    cacheSize:   options.cacheSize   ?? 8192,
    backendType: 'sync',
    // The critical line. Without it GH Pages returns the full gzipped
    // file with HTTP 200 even when Range was asked for; the library
    // then misreads pages and SQLite reports "database disk image is
    // malformed".
    headers: { 'Accept-Encoding': 'identity' },
  });
  const sqlite = await createSQLiteThread({ http: backend });
  await sqlite('open', { filename: 'file:' + encodeURI(url), vfs: 'http' });

  return {
    backend: 'http-range',
    async query(sql, bind) {
      const columns = [];
      const rows = [];
      const hasBind =
        bind && (Array.isArray(bind) ? bind.length : Object.keys(bind).length);
      try {
        await sqlite('exec', {
          sql,
          bind: hasBind ? bind : undefined,
          callback: (msg) => {
            if (msg.row) {
              rows.push(msg.row);
              if (!columns.length && msg.columnNames)
                columns.push(...msg.columnNames);
            } else if (msg.columnNames && !columns.length) {
              columns.push(...msg.columnNames);
            }
          },
        });
      } catch (err) {
        console.error('db.query failed', { sql, bind, err });
        throw err;
      }
      return rows.map((r) => {
        const o = {};
        for (let i = 0; i < columns.length; i++) o[columns[i]] = r[i];
        return o;
      });
    },
    async close() {
      await sqlite('close', {});
      sqlite.close();
      await backend.close();
    },
  };
}
