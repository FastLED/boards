// Vite configuration for the FastLED/boards portal.
//
// `public/` holds files the builders/site.py orchestrator stages (boards.db,
// _meta.json, boards/, warnings/, errors/) plus the sqlite-wasm-http
// worker + WASM that the patch script copies in from node_modules.
// Vite serves these unchanged at the bundle root.
//
// Output goes to ./dist; builders/site.py copies dist/* into the
// published `_site/` directory after the build.

import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  publicDir: 'public',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    target: 'es2020',
    rollupOptions: {
      output: {
        // Stable, human-readable filenames so the deployed bundle is
        // diffable across builds. No content-hash on the entry — _meta.json
        // is the build-id mechanism.
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  // sqlite-wasm-http spawns a Web Worker via new Worker(new URL(…, import.meta.url));
  // Vite recognises that pattern and bundles the worker automatically.
  worker: { format: 'es' },
});
