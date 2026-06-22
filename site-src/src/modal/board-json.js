// "View JSON" modal — fetches the per-board upstream JSON from the
// static bundle (boards/<layer>/<sublayer>/boards/<id>.json) and
// pretty-prints it. The JSON is intentionally NOT in the DB — keeps
// the DB small and dense for searches; clicking View JSON pays for the
// network fetch only when actually wanted.

const $ = (id) => document.getElementById(id);

let _lastUrl = null;

export async function openBoardJson(url, title) {
  const modal = $('boardJsonModal');
  $('boardJsonTitle').textContent = title || url;
  $('boardJsonCopy').style.display = 'none';
  $('boardJsonBody').textContent = 'loading…';
  modal.classList.add('open');
  _lastUrl = url;
  try {
    const resp = await fetch(url, { cache: 'force-cache' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    const text = await resp.text();
    if (_lastUrl !== url) return; // a newer modal opened while we waited
    let pretty = text;
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* leave as raw text */
    }
    $('boardJsonBody').textContent = pretty;
    $('boardJsonCopy').style.display = '';
    $('boardJsonCopy').onclick = async () => {
      try {
        await navigator.clipboard.writeText(pretty);
        $('boardJsonCopy').textContent = '✓ copied';
        setTimeout(() => {
          $('boardJsonCopy').textContent = '⧉ copy';
        }, 1500);
      } catch {
        /* clipboard refused — no-op */
      }
    };
  } catch (e) {
    $('boardJsonBody').textContent = `failed to load ${url}\n\n${e.message}`;
  }
}

export function closeBoardJson() {
  $('boardJsonModal').classList.remove('open');
}

export function isBoardJsonOpen() {
  return $('boardJsonModal').classList.contains('open');
}
