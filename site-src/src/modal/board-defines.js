import { resolveBoardJsonUrl } from './board-json.js';

const cache = new Map();
const PRIMARY_FLAG_RE = /(^|_)extra_flags$/;
let activeToken = 0;
let hideTimer = null;
let popover = null;
let activeAnchor = null;
let pinned = false;

function valueToText(value) {
  if (value == null) return '';
  if (typeof value === 'string') return value.trim();
  if (Array.isArray(value)) {
    return value.map(valueToText).filter(Boolean).join('\n');
  }
  if (typeof value === 'object') return JSON.stringify(value, null, 2).trim();
  return String(value).trim();
}

function isFlagKey(key) {
  return PRIMARY_FLAG_RE.test(key) || key === 'defines';
}

function flagSort(a, b) {
  const aPrimary = PRIMARY_FLAG_RE.test(a.key);
  const bPrimary = PRIMARY_FLAG_RE.test(b.key);
  if (aPrimary !== bPrimary) return aPrimary ? -1 : 1;
  return a.path.localeCompare(b.path);
}

export function collectBoardFlags(payload) {
  const out = [];

  function visit(value, path) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, path.concat(String(index))));
      return;
    }
    for (const [key, child] of Object.entries(value)) {
      const childPath = path.concat(key);
      if (isFlagKey(key)) {
        const text = valueToText(child);
        if (text) out.push({ key, path: childPath.join('.'), value: text });
      }
      visit(child, childPath);
    }
  }

  visit(payload, []);
  return out.sort(flagSort);
}

export function formatBoardFlags(flags) {
  if (!flags.length) return 'No extra_flags or defines found in this board JSON.';
  return flags.map((entry) => `${entry.path}\n${entry.value}`).join('\n\n');
}

async function fetchBoardFlags(url) {
  const absoluteUrl = resolveBoardJsonUrl(url);
  if (!cache.has(absoluteUrl)) {
    cache.set(
      absoluteUrl,
      fetch(absoluteUrl, { cache: 'force-cache' })
        .then((resp) => {
          if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
          return resp.json();
        })
        .then((json) => collectBoardFlags(json)),
    );
  }
  return cache.get(absoluteUrl);
}

function ensurePopover() {
  if (popover) return popover;
  popover = document.createElement('div');
  popover.id = 'boardDefinesPopover';
  popover.className = 'board-defines-popover';
  popover.hidden = true;
  popover.setAttribute('role', 'dialog');
  popover.setAttribute('aria-label', 'Board defines');
  popover.innerHTML =
    '<div class="board-defines-head">' +
      '<div class="board-defines-title"></div>' +
      '<button class="board-defines-close" type="button" aria-label="close defines">x</button>' +
    '</div>' +
    '<pre class="board-defines-body" tabindex="0"></pre>';
  popover.addEventListener('pointerenter', () => clearTimeout(hideTimer));
  popover.addEventListener('pointerleave', () => {
    if (!pinned) scheduleClose();
  });
  popover.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeBoardDefines();
    }
  });
  popover.querySelector('.board-defines-close').addEventListener('click', () => {
    closeBoardDefines();
  });
  document.body.appendChild(popover);
  return popover;
}

function setPopoverContent(title, text, isEmpty = false) {
  const el = ensurePopover();
  el.querySelector('.board-defines-title').textContent = title;
  el.querySelector('.board-defines-body').textContent = text;
  el.classList.toggle('empty', isEmpty);
}

function positionPopover(anchor) {
  const el = ensurePopover();
  const margin = 10;
  const gap = 8;
  el.hidden = false;

  const anchorRect = anchor.getBoundingClientRect();
  const popRect = el.getBoundingClientRect();
  const maxLeft = Math.max(margin, window.innerWidth - popRect.width - margin);
  const left = Math.min(Math.max(margin, anchorRect.left), maxLeft);

  let top = anchorRect.bottom + gap;
  if (top + popRect.height > window.innerHeight - margin) {
    top = Math.max(margin, anchorRect.top - popRect.height - gap);
  }

  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

async function showDefinesPopover(anchor, options = {}) {
  clearTimeout(hideTimer);
  const el = ensurePopover();
  const token = ++activeToken;
  const url = anchor.getAttribute('data-defines-url');
  const title = anchor.getAttribute('data-title') || 'defines';

  activeAnchor = anchor;
  pinned = options.pin === true;
  anchor.setAttribute('aria-expanded', 'true');
  setPopoverContent(title, 'loading defines...');
  positionPopover(anchor);

  try {
    const flags = await fetchBoardFlags(url);
    if (token !== activeToken) return;
    setPopoverContent(title, formatBoardFlags(flags), flags.length === 0);
    positionPopover(anchor);
    if (pinned) el.querySelector('.board-defines-body').focus({ preventScroll: true });
  } catch (err) {
    if (token !== activeToken) return;
    setPopoverContent(title, `failed to load defines\n\n${err.message}`, true);
    positionPopover(anchor);
  }
}

function scheduleClose() {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    const el = ensurePopover();
    if (pinned) return;
    if (el.contains(document.activeElement) || activeAnchor === document.activeElement) return;
    closeBoardDefines({ restoreFocus: false });
  }, 140);
}

export function closeBoardDefines(options = {}) {
  clearTimeout(hideTimer);
  activeToken += 1;
  if (activeAnchor) activeAnchor.setAttribute('aria-expanded', 'false');
  const shouldFocus = options.restoreFocus !== false;
  const focusTarget = activeAnchor;
  activeAnchor = null;
  pinned = false;
  if (popover) popover.hidden = true;
  if (shouldFocus && focusTarget?.focus) focusTarget.focus({ preventScroll: true });
}

export function isBoardDefinesOpen() {
  return !!popover && !popover.hidden;
}

export function wireBoardDefineButtons(root) {
  root.querySelectorAll('button[data-defines-url]').forEach((btn) => {
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', 'false');
    btn.addEventListener('pointerenter', () => showDefinesPopover(btn));
    btn.addEventListener('focus', () => showDefinesPopover(btn));
    btn.addEventListener('click', () => showDefinesPopover(btn, { pin: true }));
    btn.addEventListener('pointerleave', scheduleClose);
    btn.addEventListener('blur', scheduleClose);
  });
}
