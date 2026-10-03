// Hex-input helpers. The portal accepts VIDs and VID:PIDs in any of the
// common spellings (`0x303a`, `303A`, `303a:1001`, `303A 1001`, …) and
// the user is autocompleting from the LEFT, so short inputs are treated
// as left-justified prefixes — typing `1` matches VIDs starting with
// `1`, NOT VID `0001`.

const SEP_RE = /[:\s\-_]+/g;

/**
 * Strip `0x`, separators, and lowercase. Returns `null` when the
 * cleaned input isn't pure hex (or is empty).
 *
 *   cleanHex("0x303A:1001") → "303a1001"
 *   cleanHex("1")           → "1"
 *   cleanHex("xyz")         → null
 *
 * @param {string} s
 * @returns {string|null}
 */
export function cleanHex(s) {
  const t = (s || '').trim().toLowerCase().replace(/^0x/, '').replace(SEP_RE, '');
  if (!t || !/^[0-9a-f]+$/.test(t)) return null;
  return t;
}

/**
 * Return the input if it's exactly a 4-hex VID, else null.
 * Used for exact b-tree lookups against `vid_vendor.vid`.
 *
 * @param {string} s
 * @returns {string|null}
 */
export function asVid4(s) {
  const t = cleanHex(s);
  return t && t.length === 4 ? t : null;
}

/**
 * Return the input if it's exactly an 8-hex VID:PID, else null.
 * Used for exact b-tree lookups against `vidpid.vidpid`.
 *
 * @param {string} s
 * @returns {string|null}
 */
export function asVidPid8(s) {
  const t = cleanHex(s);
  return t && t.length === 8 ? t : null;
}
