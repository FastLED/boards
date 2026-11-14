export function normalizeSearchIntent(intent = {}) {
  return {
    q: String(intent.q || '').trim(),
    mode: String(intent.mode || 'anything'),
  };
}

export function sameSearchIntent(a, b) {
  if (!a || !b) return false;
  return a.q === b.q && a.mode === b.mode;
}

export function createLatestOnlySearchScheduler({
  run,
  debounceMs = 120,
  setTimer = globalThis.setTimeout.bind(globalThis),
  clearTimer = globalThis.clearTimeout.bind(globalThis),
  onQueued = () => {},
  onError = (err) => console.error(err),
} = {}) {
  if (typeof run !== 'function') {
    throw new TypeError('search scheduler requires a run(intent, shouldRender) function');
  }

  let latest = null;
  let active = null;
  let queued = null;
  let timer = null;

  function clearScheduled() {
    if (timer == null) return;
    clearTimer(timer);
    timer = null;
  }

  function shouldRender(intent) {
    return sameSearchIntent(intent, latest);
  }

  async function start(intent) {
    active = intent;
    queued = null;
    try {
      await run(intent, () => shouldRender(intent));
    } catch (err) {
      if (shouldRender(intent)) onError(err);
    } finally {
      active = null;
      const next = queued;
      queued = null;
      if (next && !sameSearchIntent(next, intent)) {
        request(next);
      }
    }
  }

  function schedule(intent, delayMs) {
    timer = setTimer(() => {
      timer = null;
      start(intent);
    }, delayMs);
  }

  function request(intent, { immediate = false } = {}) {
    const next = normalizeSearchIntent(intent);
    if ((active || timer) && sameSearchIntent(next, latest)) return;

    latest = next;
    clearScheduled();

    if (active) {
      queued = sameSearchIntent(next, active) ? null : next;
      onQueued(next);
      return;
    }

    schedule(next, immediate ? 0 : debounceMs);
  }

  return {
    request,
    getState() {
      return {
        latest,
        active,
        queued,
        scheduled: timer != null,
      };
    },
  };
}
