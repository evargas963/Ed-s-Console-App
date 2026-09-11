// @ts-check
// Regression locks (audit 2026-07-04 / fix 3a0d338), behavioral halves:
//   Lock 2 — a ticker switch must reset the expiry scope: the prior ticker's
//     expiry (still sitting in #expiry-select) must not ride into the new
//     ticker's data requests, and the stale select must be cleared.
//   Lock 3 — the money-path ordering cursor is advanced only by gen-bearing
//     Tier C bundles: a fresher gen-less quote/shell payload must not block an
//     older-but-valid decision bundle as ts_regression.
const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => { window.__ED_E2E__ = true; });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  // RC-466 flake close: the tests below dereference #expiry-select inside evaluate().
  // The element is STATIC in index.html, so after a real app load it exists at
  // domcontentloaded — but if '/' raced the server's startup-exception window and served
  // an error page, the deref died as `Cannot set properties of null` mid-test (CI,
  // 2026-08-24, run 32716032624). Wait for ATTACHED, not the default visible: the empty
  // select is hidden until expiries populate (never, in CI offline mode), so a
  // visibility wait times out for every test in this file — measured on run 32716925350,
  // 3 failed / e2e 7.4m. Attached is exactly what the derefs need.
  await page.waitForSelector('#expiry-select', { state: 'attached' });
});

test('ticker switch resets expiry scope and clears the stale select', async ({ page }) => {
  const committed = await page.evaluate(() => {
    const sel = document.getElementById('expiry-select');
    sel.innerHTML = '<option value="2099-01-02" selected>2099-01-02</option>';
    sel.value = '2099-01-02';
    document.getElementById('ticker-input').value = 'QQQ';
    // setActiveTicker + the expiry reset run synchronously inside fetchState
    // before its first await; capture immediately after the call starts.
    const p = window.__edTestHooks.fetchState(false);
    if (p && typeof p.catch === 'function') p.catch(() => {});
    return {
      activeTicker: window.__edTestHooks.getActiveTicker(),
      activeExpiry: window.__edTestHooks.getActiveExpiry(),
      selectValue: sel.value,
    };
  });
  expect(committed.activeTicker).toBe('QQQ');
  // REGRESSION LOCK: carried expiry must be dropped (server default resolves it).
  expect(committed.activeExpiry).toBeNull();
  expect(committed.selectValue).not.toBe('2099-01-02');
});

test('a ticker switch triggered outside the header field syncs the visible header chip immediately', async ({ page }) => {
  // MEASURED 2026-09-11: a watchlist-row click (or a radar click, or the cross-tab storage
  // sync) calls setActiveTicker() directly -- it never goes through the header input's own
  // commitTicker() handler, which is the ONLY other place that wrote #cv2-hd-ticker besides
  // paintHeader()'s periodic full-render catch-up. Before the fix, the visible header chip
  // kept showing the PRIOR ticker for however long it took the next paintHeader() to run
  // (observed several seconds against a live dev instance, longer under a degraded/retrying
  // backend) while activeTicker, #ticker-input, and every panel that reads them had already
  // moved to the new ticker -- the operator-visible ticker identity disagreed with what was
  // actually being rendered. setActiveTicker must now mirror the header chip itself,
  // synchronously, with no dependency on a later render cycle.
  const r = await page.evaluate(() => {
    const hd = document.getElementById('cv2-hd-ticker');
    hd.value = 'SPY'; // known starting chip value, independent of whatever loaded last
    window.setActiveTicker('QQQ', null); // the watchlist/radar-click entry point, called directly
    return { hdImmediatelyAfter: hd.value, activeTicker: window.__edTestHooks.getActiveTicker() };
  });
  expect(r.activeTicker).toBe('QQQ');
  // REGRESSION LOCK: pre-fix this stayed 'SPY' until an unrelated paintHeader() call caught up.
  expect(r.hdImmediatelyAfter).toBe('QQQ');
});

test('an in-progress header edit is not clobbered by a switch triggered elsewhere', async ({ page }) => {
  // The synchronous mirror above must still respect the same "operator is actively typing"
  // guard paintHeader already used -- a concurrent switch must not eat a draft symbol.
  const r = await page.evaluate(() => {
    const hd = document.getElementById('cv2-hd-ticker');
    hd.focus();
    hd.value = 'DRAFT';
    window.setActiveTicker('TSLA', null);
    const whileFocused = hd.value;
    return { whileFocused, activeTicker: window.__edTestHooks.getActiveTicker() };
  });
  expect(r.activeTicker).toBe('TSLA');
  expect(r.whileFocused).toBe('DRAFT');
});

test('a cross-tab ticker change does not clobber an in-progress header draft', async ({ page }) => {
  // MEASURED 2026-09-11: the storage-event handler wrote #cv2-hd-ticker unconditionally, with
  // no "operator is actively editing" guard -- unlike every other writer of that field. A
  // parallel-tab ticker change landing while the operator was mid-draft silently overwrote
  // what they were typing and committed the OTHER tab's ticker as if they had typed it.
  const r = await page.evaluate(() => {
    const hd = document.getElementById('cv2-hd-ticker');
    hd.focus();
    hd.value = 'DRAFT2';
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'ed_ticker', newValue: 'MSFT', oldValue: 'SPY', storageArea: window.localStorage,
    }));
    return { whileFocused: hd.value };
  });
  expect(r.whileFocused).toBe('DRAFT2');
});

test('a delayed liquidity-snapshot response for the PRIOR ticker is dropped, not rendered', async ({ page }) => {
  // MEASURED 2026-09-11: pollLiquiditySnapshot() read #ticker-input directly and carried no
  // generation/ticker guard, unlike every other fetch path in this file -- a response for the
  // ticker requested when the poll STARTED rendered unconditionally, even after the operator
  // had already switched to a different ticker while it was in flight.
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    let resolveDelayed;
    window.fetch = (url, opts) => String(url).includes('/api/liquidity-snapshot')
      ? new Promise((res) => { resolveDelayed = res; })
      : realFetch(url, opts);
    window._lastLiquidityMapPayload = null;
    window.setActiveTicker('SPY', null);
    const p = window.pollLiquiditySnapshot();
    await new Promise((r2) => setTimeout(r2, 20));
    window.setActiveTicker('QQQ', null); // switch BEFORE the SPY response arrives
    resolveDelayed({ ok: true, json: async () => ({ ticker: 'SPY', snapshot_type: 'live', zones: [] }) });
    await p;
    window.fetch = realFetch;
    return {
      activeTicker: window.__edTestHooks.getActiveTicker(),
      lastPayloadTicker: window._lastLiquidityMapPayload ? window._lastLiquidityMapPayload.ticker : null,
    };
  });
  expect(r.activeTicker).toBe('QQQ');
  // REGRESSION LOCK: pre-fix this rendered, and lastPayloadTicker would read 'SPY'.
  expect(r.lastPayloadTicker).toBeNull();
});

test('liquidity snapshot: valid render -> failure marks UNAVAILABLE, not stale-as-current -> recovery renders fresh data', async ({ page }) => {
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    window.setActiveTicker('IWM', null);

    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({ ticker: 'IWM', snapshot_type: 'live', zones: [{ zone_type: 'value_area', zone_low: 1, zone_high: 2 }] }) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterValid = {
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      payload: window._lastLiquidityMapPayload?.ticker,
    };

    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? Promise.reject(new TypeError('network error'))
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterFailure = { badge: document.getElementById('lm-snapshot-badge')?.textContent };

    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({ ticker: 'IWM', snapshot_type: 'live', zones: [{ zone_type: 'value_area', zone_low: 3, zone_high: 4 }] }) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterRecovery = {
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      payload: window._lastLiquidityMapPayload?.ticker,
    };

    window.fetch = realFetch;
    return { afterValid, afterFailure, afterRecovery };
  });
  expect(r.afterValid.badge).toBe('LIVE');
  expect(r.afterValid.payload).toBe('IWM');
  // REGRESSION LOCK: pre-fix the badge stayed 'LIVE' here -- stale data presented as current.
  expect(r.afterFailure.badge).toBe('UNAVAILABLE');
  expect(r.afterRecovery.badge).toBe('LIVE');
  expect(r.afterRecovery.payload).toBe('IWM');
});

test('transport diag lastFullRenderSource leaves init after a full render and persists across syncs', async ({ page }) => {
  // Lane-2 lock: pre-fix, render wrote only window._lastFullRenderSource while
  // _edTransportSync rebuilt __edTransport from the module-level variable, so the
  // field reverted to 'init' on the next sync (SSE tick / poll skip) and stayed
  // there forever. Post-fix it must reflect the last accepted full render source
  // and persist across later syncs.
  await page.evaluate(() => {
    const p = window.__edTestHooks.fetchState(false); // default SPY — warmed at server boot
    if (p && typeof p.catch === 'function') p.catch(() => {});
  });
  await page.waitForFunction(() => {
    const t = window.__edTransport || {};
    return !!t.lastFullRenderSource && t.lastFullRenderSource !== 'init';
  }, undefined, { timeout: 110000 });
  // Let SSE/poll syncs run — pre-fix these reverted the field to 'init'.
  await page.waitForTimeout(4000);
  const src = await page.evaluate(() => (window.__edTransport || {}).lastFullRenderSource);
  expect(src).not.toBe('init');
  expect(['rest_manual', 'rest_poll', 'sse', 'sse_fanout_rest']).toContain(src);
});

test('ordering cursor advanced only by gen-bearing Tier C bundles', async ({ page }) => {
  const r = await page.evaluate(() => {
    window._edMplMonotonicGateReset();
    const now = Date.now() / 1000;
    // gen-less quote-tier payload with the freshest wall-clock timestamp
    const genless = window.acceptMoneyPathPayload(
      { _tier: 'B_light', ticker: 'SPY', _server_build_ts: now }, 'lock_b_light');
    // older-but-valid cached decision bundle (the QQQ-wedge shape)
    const oldBundle = window.acceptMoneyPathPayload(
      { ticker: 'SPY', decision_generation_id: 3, _server_build_ts: now - 600, mhap_rows: [] }, 'lock_c_old');
    // real gen regression must still be rejected
    const regressGen = window.acceptMoneyPathPayload(
      { ticker: 'SPY', decision_generation_id: 2, _server_build_ts: now, mhap_rows: [] }, 'lock_c_regress');
    // newer gen accepts even when its build ts is older (documented contract)
    const newerGen = window.acceptMoneyPathPayload(
      { ticker: 'SPY', decision_generation_id: 4, _server_build_ts: now - 300, mhap_rows: [] }, 'lock_c_new');
    return { genless, oldBundle, regressGen, newerGen };
  });
  expect(r.genless).toBe(true);
  // REGRESSION LOCK: under the pre-fix cursor, this returned false (ts_regression).
  expect(r.oldBundle).toBe(true);
  expect(r.regressGen).toBe(false);
  expect(r.newerGen).toBe(true);
});
