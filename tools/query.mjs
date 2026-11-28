#!/usr/bin/env bun
// Bun-backed query CLI. Same search code the portal renders, run
// against a local boards.db (or fresh download from a URL) and
// printed as JSON. Lets Python tests assert against the *actual* JS
// engine instead of a Python port that can drift.
//
// Usage (single query):
//   bun tools/query.mjs --db <url|path> --text "esp32dev"
//                       [--mode anything|vendor|product|board]
//                       [--limit N]
//
// Usage (batch, one open per process):
//   bun tools/query.mjs --db <url|path> --batch <jsonfile>
//                       [--mode anything|vendor|product|board]
//
// where <jsonfile> is `[{"text": "..."}, {"text": "...", "mode": "vendor"}, ...]`
// Batch output is a JSON array of the same per-query objects.
//
// Output (--json, default for piping):
//   { "query": "esp32dev",
//     "mode":  "anything",
//     "data":  { "vendors": [...], "products": [...], "boards": [...] },
//     "counts": { "vendors": N, "products": N, "boards": N } }
//
// Each `data.X` entry is the same {row, score, why} shape the portal
// renders, so the Python test can compare hit/miss + counts without
// duplicating any of the search logic.

import { openDb } from '../site-src/src/db/index.js';
import {
  searchUniversal, searchVendor, searchProduct, searchBoard,
} from '../site-src/src/search/engine.js';

function parseArgs(argv) {
  const out = {
    db: null, text: null, batch: null,
    mode: 'anything', limit: null, pretty: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--db')    out.db = argv[++i];
    else if (a === '--text')   out.text = argv[++i];
    else if (a === '--batch')  out.batch = argv[++i];
    else if (a === '--mode')   out.mode = argv[++i];
    else if (a === '--limit')  out.limit = parseInt(argv[++i], 10);
    else if (a === '--pretty') out.pretty = true;
    else if (a === '--help' || a === '-h') {
      console.error(
`Usage: bun tools/query.mjs --db <url|path> --text "query"
                            [--mode anything|vendor|product|board]
                            [--limit N] [--pretty]
       bun tools/query.mjs --db <url|path> --batch <jsonfile>`);
      process.exit(0);
    }
  }
  return out;
}

const MODES = {
  anything: searchUniversal,
  vendor:   searchVendor,
  product:  searchProduct,
  board:    searchBoard,
};

function applyLimit(data, n) {
  if (n == null) return data;
  for (const k of ['vendors', 'products', 'boards']) {
    if (Array.isArray(data[k])) data[k] = data[k].slice(0, n);
  }
  return data;
}

function shape(text, mode, backend, data) {
  return {
    query: text,
    mode,
    backend,
    data,
    counts: {
      vendors:  data.vendors?.length  ?? 0,
      products: data.products?.length ?? 0,
      boards:   data.boards?.length   ?? 0,
    },
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.db) {
    console.error('error: --db is required');
    process.exit(2);
  }
  if (!args.batch && args.text == null) {
    console.error('error: provide either --text "..." or --batch <jsonfile>');
    process.exit(2);
  }

  const db = await openDb({ source: args.db });
  try {
    if (args.batch) {
      const fs = await import('node:fs');
      const items = JSON.parse(fs.readFileSync(args.batch, 'utf8'));
      const results = [];
      for (const item of items) {
        const mode = item.mode || args.mode;
        const fn = MODES[mode];
        if (!fn) {
          results.push({ query: item.text, mode, error: `unknown mode '${mode}'` });
          continue;
        }
        let data;
        try {
          data = await fn(item.text, db.query.bind(db));
        } catch (err) {
          results.push({ query: item.text, mode, error: err.message });
          continue;
        }
        results.push(shape(item.text, mode, db.backend,
                           applyLimit(data, item.limit ?? args.limit)));
      }
      process.stdout.write(
        JSON.stringify(results, null, args.pretty ? 2 : 0) + '\n');
    } else {
      const fn = MODES[args.mode];
      if (!fn) {
        console.error(`error: unknown --mode '${args.mode}' (anything|vendor|product|board)`);
        process.exit(2);
      }
      const data = applyLimit(await fn(args.text, db.query.bind(db)), args.limit);
      process.stdout.write(
        JSON.stringify(shape(args.text, args.mode, db.backend, data),
                       null, args.pretty ? 2 : 0) + '\n');
    }
  } finally {
    await db.close();
  }
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
