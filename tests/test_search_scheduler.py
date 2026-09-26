from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO = pathlib.Path(__file__).resolve().parents[1]
BUN = shutil.which("bun")


SCHEDULER_TEST_SCRIPT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo] = process.argv.slice(2);
const {
  createLatestOnlySearchScheduler,
} = await import(
  pathToFileURL(path.join(repo, 'site-src/src/search/scheduler.js')).href
);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function delay(ms = 0) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

async function waitFor(predicate, message) {
  for (let i = 0; i < 50; i++) {
    if (predicate()) return;
    await delay(0);
  }
  throw new Error(message);
}

async function testIdleRequestsCoalesceToLastSearch() {
  const started = [];
  const rendered = [];
  const scheduler = createLatestOnlySearchScheduler({
    debounceMs: 5,
    run: async (intent, shouldRender) => {
      started.push(intent);
      rendered.push(shouldRender());
    },
  });

  scheduler.request({ q: '3', mode: 'anything' });
  scheduler.request({ q: '30', mode: 'anything' });
  scheduler.request({ q: '303', mode: 'anything' });
  scheduler.request({ q: '303a', mode: 'anything' });

  await waitFor(() => started.length === 1, 'expected one coalesced search to start');
  assert(started[0].q === '303a', `expected last query to start, got ${started[0].q}`);
  assert(rendered.length === 1 && rendered[0] === true, 'latest coalesced search should render');
}

async function testActiveSearchKeepsOnlyLatestQueuedSearch() {
  const started = [];
  const decisions = [];
  const releases = [];
  const scheduler = createLatestOnlySearchScheduler({
    debounceMs: 0,
    run: async (intent, shouldRender) => {
      started.push(intent);
      const gate = deferred();
      releases.push(gate.resolve);
      await gate.promise;
      decisions.push({ q: intent.q, shouldRender: shouldRender() });
    },
  });

  scheduler.request({ q: '3', mode: 'anything' }, { immediate: true });
  await waitFor(() => started.length === 1, 'first search did not start');

  scheduler.request({ q: '30', mode: 'anything' });
  scheduler.request({ q: '303', mode: 'anything' });
  scheduler.request({ q: '303a', mode: 'anything' });

  assert(started.length === 1, 'queued searches must not start while active search runs');
  assert(
    scheduler.getState().queued.q === '303a',
    `expected latest queued query 303a, got ${scheduler.getState().queued?.q}`,
  );

  releases[0]();
  await waitFor(() => decisions.length === 1, 'active search did not finish');
  assert(decisions[0].q === '3' && decisions[0].shouldRender === false,
    'superseded active search must not render');

  await waitFor(() => started.length === 2, 'queued latest search did not start');
  assert(started[1].q === '303a', `expected only latest queued search, got ${started[1].q}`);

  releases[1]();
  await waitFor(() => decisions.length === 2, 'queued search did not finish');
  assert(decisions[1].q === '303a' && decisions[1].shouldRender === true,
    'latest queued search should render');
}

async function testReturningToActiveIntentAllowsActiveSearchToRender() {
  const started = [];
  const decisions = [];
  const releases = [];
  const scheduler = createLatestOnlySearchScheduler({
    debounceMs: 0,
    run: async (intent, shouldRender) => {
      started.push(intent);
      const gate = deferred();
      releases.push(gate.resolve);
      await gate.promise;
      decisions.push({ q: intent.q, shouldRender: shouldRender() });
    },
  });

  scheduler.request({ q: '303', mode: 'anything' }, { immediate: true });
  await waitFor(() => started.length === 1, 'first search did not start');

  scheduler.request({ q: '303a', mode: 'anything' });
  scheduler.request({ q: '303', mode: 'anything' });

  assert(scheduler.getState().queued === null, 'returning to active intent should clear queued search');
  releases[0]();
  await waitFor(() => decisions.length === 1, 'active search did not finish');
  assert(decisions[0].q === '303' && decisions[0].shouldRender === true,
    'active search matching latest intent should render');
  assert(started.length === 1, 'no follow-up search should start when active intent is latest');
}

await testIdleRequestsCoalesceToLastSearch();
await testActiveSearchKeepsOnlyLatestQueuedSearch();
await testReturningToActiveIntentAllowsActiveSearchToRender();
"""


@unittest.skipIf(BUN is None, "bun runtime not installed")
class SearchSchedulerTests(unittest.TestCase):
    def test_latest_only_scheduler_contract(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mjs", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(textwrap.dedent(SCHEDULER_TEST_SCRIPT).strip() + "\n")
            script_path = fh.name
        try:
            proc = subprocess.run(
                [BUN, script_path, str(REPO)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise AssertionError(
                f"bun scheduler test exit {e.returncode}\nstderr:\n{e.stderr}\n"
                f"stdout:\n{e.stdout[:1000]}"
            ) from e
        finally:
            pathlib.Path(script_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
