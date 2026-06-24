// "View JSON" modal — fetches the per-board upstream JSON from the
// static bundle (boards/<layer>/<sublayer>/boards/<id>.json) and
// pretty-prints it. The JSON is intentionally NOT in the DB — keeps
// the DB small and dense for searches; clicking View JSON pays for the
// network fetch only when actually wanted.

const $ = (id) => document.getElementById(id);
const COPY_JSON_TEXT = 'copy JSON';
const COPY_URL_TEXT = 'copy URL';

let _lastUrl = null;

export function resolveBoardJsonUrl(url, baseHref = location.href) {
  return new URL(url, baseHref).href;
}

async function copyText(value, button, resetText) {
  try {
    await navigator.clipboard.writeText(value);
    button.textContent = 'copied';
    setTimeout(() => {
      button.textContent = resetText;
    }, 1500);
  } catch {
    /* clipboard refused — no-op */
  }
}

export async function openBoardJson(url, title) {
  const modal = $('boardJsonModal');
  const absoluteUrl = resolveBoardJsonUrl(url);
  const titleLink = $('boardJsonTitle');
  const copyJson = $('boardJsonCopy');
  const copyUrl = $('boardJsonCopyUrl');

  titleLink.textContent = title || url;
  titleLink.href = absoluteUrl;
  titleLink.title = absoluteUrl;
  copyJson.textContent = COPY_JSON_TEXT;
  copyJson.style.display = 'none';
  copyUrl.textContent = COPY_URL_TEXT;
  copyUrl.onclick = () => copyText(absoluteUrl, copyUrl, COPY_URL_TEXT);
  $('boardJsonBody').textContent = 'loading…';
  modal.classList.add('open');
  _lastUrl = absoluteUrl;
  try {
    const resp = await fetch(absoluteUrl, { cache: 'force-cache' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    const text = await resp.text();
    if (_lastUrl !== absoluteUrl) return; // a newer modal opened while we waited
    let pretty = text;
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* leave as raw text */
    }
    $('boardJsonBody').textContent = pretty;
    copyJson.style.display = '';
    copyJson.onclick = () => copyText(pretty, copyJson, COPY_JSON_TEXT);
  } catch (e) {
    $('boardJsonBody').textContent = `failed to load ${absoluteUrl}\n\n${e.message}`;
  }
}

export function closeBoardJson() {
  $('boardJsonModal').classList.remove('open');
}

export function isBoardJsonOpen() {
  return $('boardJsonModal').classList.contains('open');
}
