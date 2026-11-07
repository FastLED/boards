/**
 * Score how well a haystack matches a (lowercased) needle. Used to
 * rank universal-search results so exact / starts-with hits surface
 * to the Best Hits strip ahead of contains-only matches.
 *
 * @param {string} haystack
 * @param {string} needle  pre-lowercased
 * @returns {number}
 */
export function scoreName(haystack, needle) {
  const lc = haystack.toLowerCase();
  if (lc === needle) return 950;
  if (lc.startsWith(needle)) return 700;
  if (
    lc.includes(' ' + needle) ||
    lc.includes('-' + needle) ||
    lc.includes('_' + needle) ||
    lc.includes('/' + needle)
  )
    return 400;
  return 100;
}

/**
 * Score multi-token coverage: how many of the needle's whitespace
 * tokens appear in the haystack (case-insensitive, as substrings).
 *
 * Returns 0 when the needle has only one token (use `scoreName`
 * instead). Otherwise:
 *   - All tokens present → 620 (above the Best Hits threshold).
 *   - Most tokens present → proportional (≥ 300 when ≥ 50% covered).
 *   - Few / none → 0 (caller falls back to `scoreName`).
 *
 * The rationale: a row that an FTS5 prefix-AND query already returned
 * is by definition relevant — every searched token matched some
 * indexed column. Surface those in Best Hits so the user doesn't have
 * to scroll past 30 vendors to see them.
 *
 * @param {string} haystack
 * @param {string} needle  pre-lowercased
 * @returns {number}
 */
export function scoreTokenCoverage(haystack, needle) {
  const tokens = needle.split(/\s+/).filter((t) => t.length);
  if (tokens.length < 2) return 0;
  const lc = haystack.toLowerCase();
  let present = 0;
  for (const t of tokens) if (lc.includes(t)) present++;
  if (present === tokens.length) return 620;
  const ratio = present / tokens.length;
  if (ratio >= 0.5) return Math.round(300 * ratio);
  return 0;
}

/**
 * Push `row` onto `arr` keyed by `keyFn(row)`, bumping the score (and
 * `why` reason) of an existing entry if this score is higher.
 *
 * @template T
 * @param {Array<{row: T, score: number, why: string}>} arr
 * @param {(row: T) => string} keyFn
 * @param {T} row
 * @param {number} score
 * @param {string} why
 * @param {Object=} extra
 * @returns {{row: T, score: number, why: string}}
 */
export function bumpOrPush(arr, keyFn, row, score, why, extra = {}) {
  const key = keyFn(row);
  const existing = arr.find((h) => keyFn(h.row) === key);
  if (existing) {
    if (score > existing.score) {
      existing.score = score;
      existing.why = why;
      Object.assign(existing, extra);
    } else {
      if (!existing.reason && extra.reason) existing.reason = extra.reason;
      if (extra.linkedBoards) existing.linkedBoards = extra.linkedBoards;
      if (extra.total != null) existing.total = extra.total;
    }
    return existing;
  } else {
    const hit = { row, score, why, ...extra };
    arr.push(hit);
    return hit;
  }
}
