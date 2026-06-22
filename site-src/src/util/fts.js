// Token-level stop list. Must stay in lockstep with
// builders/extract_boards.py:_STOP_WORDS — same words filtered on
// both the QUERY side (here) and the INDEX side (extractor) so the
// search doesn't include tokens that can't possibly match.
const STOP_WORDS = new Set([
  // Log levels
  'info', 'warn', 'error', 'verbose',
  // Generic UI states
  'default', 'disable', 'disabled', 'enable', 'enabled',
  'none', 'on', 'off', 'all', 'custom',
  // Size / speed labels
  'minimal', 'small', 'fast',
  // Pure schema labels that bled in as menu values
  'boot', 'mode', 'port', 'os', 'sdk', 'ld', 'fp',
]);

/**
 * Build an FTS5 prefix-AND query from a free-text input. Strips
 * punctuation, tokenizes on whitespace, drops stop tokens, appends
 * `*` to each surviving token. Returns null when nothing meaningful
 * is left to search.
 *
 *   ftsQuery("ESP32 Dev")          → "esp32* dev*"
 *   ftsQuery("303a:1001")          → "303a* 1001*"
 *   ftsQuery("Default with spiffs") → "with* spiffs*"   (default stripped)
 *   ftsQuery("!!  ")               → null
 *
 * @param {string} s
 * @returns {string|null}
 */
export function ftsQuery(s) {
  const tokens = (s || '')
    .toLowerCase()
    .replace(/[^a-z0-9_\s]/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length > 0 && !STOP_WORDS.has(t));
  if (!tokens.length) return null;
  return tokens.map((t) => `${t}*`).join(' ');
}
