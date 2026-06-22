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
 * Push `row` onto `arr` keyed by `keyFn(row)`, bumping the score (and
 * `why` reason) of an existing entry if this score is higher.
 *
 * @template T
 * @param {Array<{row: T, score: number, why: string}>} arr
 * @param {(row: T) => string} keyFn
 * @param {T} row
 * @param {number} score
 * @param {string} why
 */
export function bumpOrPush(arr, keyFn, row, score, why) {
  const key = keyFn(row);
  const existing = arr.find((h) => keyFn(h.row) === key);
  if (existing) {
    if (score > existing.score) {
      existing.score = score;
      existing.why = why;
    }
  } else {
    arr.push({ row, score, why });
  }
}
