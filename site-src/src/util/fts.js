/**
 * Build an FTS5 prefix-AND query from a free-text input. Strips
 * punctuation, tokenizes on whitespace, appends `*` to each token.
 * Returns null when nothing meaningful is left to search.
 *
 *   ftsQuery("ESP32 Dev")     → "esp32* dev*"
 *   ftsQuery("303a:1001")     → "303a* 1001*"
 *   ftsQuery("!!  ")          → null
 *
 * @param {string} s
 * @returns {string|null}
 */
export function ftsQuery(s) {
  const tokens = (s || '')
    .toLowerCase()
    .replace(/[^a-z0-9_\s]/g, ' ')
    .split(/\s+/)
    .filter((t) => t.length > 0);
  if (!tokens.length) return null;
  return tokens.map((t) => `${t}*`).join(' ');
}
