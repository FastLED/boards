// "View JSON" modal. Fetches the per-board JSON from the static bundle
// and pretty-prints it only when the user asks for it.

const $ = (id) => document.getElementById(id);
const COPY_JSON_TEXT = 'copy JSON';
const COPY_URL_TEXT = 'copy URL';
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

let _lastUrl = null;
let _previousFocus = null;

export function resolveBoardJsonUrl(url, baseHref = location.href) {
  return new URL(url, baseHref).href;
}

function focusableIn(modal) {
  return [...modal.querySelectorAll(FOCUSABLE)].filter((el) => {
    return el.offsetParent !== null || el === document.activeElement;
  });
}

function trapModalFocus(e) {
  if (e.key !== 'Tab') return;
  const modal = $('boardJsonModal');
  const items = focusableIn(modal);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];

  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

function focusModalTitle() {
  const titleLink = $('boardJsonTitle');
  if (titleLink) titleLink.focus({ preventScroll: true });
}

async function copyText(value, button, resetText) {
  button.classList.remove('copy-error');
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error('Clipboard API unavailable');
    }
    await navigator.clipboard.writeText(value);
    button.textContent = 'copied';
  } catch {
    button.textContent = 'copy failed';
    button.classList.add('copy-error');
  } finally {
    setTimeout(() => {
      button.textContent = resetText;
      button.classList.remove('copy-error');
    }, 1500);
  }
}

export async function openBoardJson(url, title) {
  const modal = $('boardJsonModal');
  const absoluteUrl = resolveBoardJsonUrl(url);
  const titleLink = $('boardJsonTitle');
  const copyJson = $('boardJsonCopy');
  const copyUrl = $('boardJsonCopyUrl');
  const body = $('boardJsonBody');

  if (!isBoardJsonOpen()) _previousFocus = document.activeElement;

  titleLink.textContent = title || url;
  titleLink.href = absoluteUrl;
  titleLink.title = absoluteUrl;
  copyJson.textContent = COPY_JSON_TEXT;
  copyJson.classList.remove('copy-error');
  copyJson.style.display = 'none';
  copyUrl.textContent = COPY_URL_TEXT;
  copyUrl.classList.remove('copy-error');
  copyUrl.onclick = () => copyText(absoluteUrl, copyUrl, COPY_URL_TEXT);
  body.textContent = 'loading...';
  body.setAttribute('aria-busy', 'true');
  modal.classList.add('open');
  document.body.classList.add('modal-open');
  modal.addEventListener('keydown', trapModalFocus);
  requestAnimationFrame(focusModalTitle);

  _lastUrl = absoluteUrl;
  try {
    const resp = await fetch(absoluteUrl, { cache: 'force-cache' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    const text = await resp.text();
    if (_lastUrl !== absoluteUrl) return;
    let pretty = text;
    try {
      pretty = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      // Leave non-JSON responses as raw text.
    }
    body.textContent = pretty;
    body.removeAttribute('aria-busy');
    copyJson.style.display = '';
    copyJson.onclick = () => copyText(pretty, copyJson, COPY_JSON_TEXT);
  } catch (e) {
    body.textContent = `failed to load ${absoluteUrl}\n\n${e.message}`;
    body.removeAttribute('aria-busy');
  }
}

export function closeBoardJson(options = {}) {
  const restoreFocus = options.restoreFocus !== false;
  const modal = $('boardJsonModal');
  modal.classList.remove('open');
  modal.removeEventListener('keydown', trapModalFocus);
  document.body.classList.remove('modal-open');
  _lastUrl = null;
  if (restoreFocus && _previousFocus?.focus) {
    _previousFocus.focus({ preventScroll: true });
  }
  _previousFocus = null;
}

export function isBoardJsonOpen() {
  return $('boardJsonModal').classList.contains('open');
}
