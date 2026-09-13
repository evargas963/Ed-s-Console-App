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

test('a delayed /api/terrain response for the PRIOR ticker cannot overwrite the Terrain card after a switch (state-authority review)', async ({ page }) => {
  // Independent-review finding (2026-09-12, state-authority review), REPRODUCED: unlike
  // fetchState (requestGeneration) and pollLiquiditySnapshot (test above, its own
  // ticker-check fix), edLoadTerrain() carried no requestGeneration guard at all -- a
  // response for the ticker requested when edLoadTerrain() STARTED rendered
  // unconditionally, even after the operator had already switched ticker while it was
  // in flight (the 5s Terrain-tab poll timer, or a fast radar-row double-click).
  // Reproduced exactly: PLTR's /api/terrain request in flight, switch to AMD BEFORE it
  // resolves, then deliver PLTR's late response -- it must not overwrite tv-sym/
  // tv-contracts (already showing/reflecting AMD) with PLTR's data.
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    let resolveDelayed;
    window.fetch = (url, opts) => String(url).includes('/api/terrain?ticker=PLTR')
      ? new Promise((res) => { resolveDelayed = res; })
      : realFetch(url, opts);
    window.setActiveTicker('PLTR', null);
    const p = window.edLoadTerrain();
    await new Promise((r2) => setTimeout(r2, 20));
    window.setActiveTicker('AMD', null);   // switch BEFORE PLTR's response arrives
    const tvSymBeforeLateResponse = (document.getElementById('tv-sym') || {}).textContent;
    resolveDelayed({
      ok: true,
      json: async () => ({
        ticker: 'PLTR', spot: 20, gamma_flip: 19, confidence: 'TRUSTED',
        contracts_used: 500, strikes_used: 20, computed_ts_utc: Date.now() / 1000,
      }),
    });
    await p;
    window.fetch = realFetch;
    return {
      activeTicker: window.__edTestHooks.getActiveTicker(),
      tvSymBeforeLateResponse,
      tvSymAfterLateResponse: (document.getElementById('tv-sym') || {}).textContent,
    };
  });
  expect(r.activeTicker).toBe('AMD');
  // REGRESSION LOCK: pre-fix, the late PLTR response repainted tv-sym to 'PLTR' here.
  expect(r.tvSymAfterLateResponse).toBe(r.tvSymBeforeLateResponse);
  expect(r.tvSymAfterLateResponse).not.toBe('PLTR');
});

test('liquidity snapshot: valid render (actual zone numbers) -> failure invalidates payload/zones/summary, not just the badge -> recovery renders REPLACEMENT values', async ({ page }) => {
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    window.setActiveTicker('IWM', null);
    const zoneRangeTexts = () => Array.from(document.querySelectorAll('#lm-zones .lm-zone-price')).map((e) => e.textContent);

    // 1) valid response renders the ACTUAL zone numbers, not merely a ticker/badge match --
    // and a REAL, recognized summary (value_state/vwap_relation/auction_interpretation are the
    // fields buildLiquidityMapSummaryHtml actually reads; an unrecognized fixture like {x:1}
    // renders as an empty string regardless of whether invalidation happened, which would make
    // the "cleared by failure" assertion below pass even with no invalidation at all).
    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({
          ticker: 'IWM', snapshot_type: 'live',
          summary: { value_state: 'shifted_higher', vwap_relation: 'above_value', auction_interpretation: 'bullish_acceptance' },
          zones: [{ zone_type: 'value_area', zone_low: 1, zone_high: 2 }] }) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterValid = {
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      payload: window._lastLiquidityMapPayload?.ticker,
      zoneRanges: zoneRangeTexts(),
      summaryHtml: document.getElementById('lm-summary-section')?.innerHTML,
    };

    // 2) failure must invalidate the STORED payload and the rendered zones/summary, not only
    // the badge text -- patchLiquidityMapSummaryFromLivePlane() is an INDEPENDENT consumer
    // (the periodic mark-to-market spot refresh calls it on its own) that reads
    // window._lastLiquidityMapPayload directly; if the fix only touched the badge, this
    // downstream call would still repaint the summary from the stale payload's content.
    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? Promise.reject(new TypeError('network error'))
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const summaryEl = document.getElementById('lm-summary-section');
    const summaryClearedByFailure = summaryEl ? summaryEl.innerHTML : null;
    window.patchLiquidityMapSummaryFromLivePlane(); // the independent downstream consumer, called directly
    const afterFailure = {
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      payload: window._lastLiquidityMapPayload,
      zoneRanges: zoneRangeTexts(),
      summaryClearedByFailure,
      // REGRESSION TARGET: if the payload were still the stale IWM one, this call would
      // repaint it with x:1's summary HTML -- it must stay whatever the failure left it as.
      summaryAfterDownstreamConsumerCall: summaryEl ? summaryEl.innerHTML : null,
    };

    // 3) recovery must show REPLACEMENT values -- a different zone range, not the same numbers
    // re-rendered, which would pass a same-ticker-only check without proving fresh data landed.
    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({ ticker: 'IWM', snapshot_type: 'live', zones: [{ zone_type: 'value_area', zone_low: 30, zone_high: 40 }] }) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterRecovery = {
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      payload: window._lastLiquidityMapPayload?.ticker,
      zoneRanges: zoneRangeTexts(),
    };

    window.fetch = realFetch;
    return { afterValid, afterFailure, afterRecovery };
  });
  expect(r.afterValid.badge).toBe('LIVE');
  expect(r.afterValid.payload).toBe('IWM');
  expect(r.afterValid.zoneRanges).toEqual(['1.00 – 2.00']);
  // Precondition: the summary fixture must actually render REAL, recognizable content --
  // otherwise the "cleared by failure" assertions below would pass even with no invalidation.
  expect(r.afterValid.summaryHtml).toContain('bullish acceptance');

  // REGRESSION LOCK: pre-fix the badge stayed 'LIVE', the payload/zones were left as IWM's
  // valid data, and the independent downstream consumer kept painting from it.
  expect(r.afterFailure.badge).toBe('UNAVAILABLE');
  expect(r.afterFailure.payload).toBeNull();
  expect(r.afterFailure.zoneRanges).toEqual([]);
  expect(r.afterFailure.summaryClearedByFailure).toBe('');
  // REGRESSION TARGET: with the payload still stale, this call would have repainted the OLD
  // summary HTML; with it invalidated, the independent consumer has nothing to repaint from.
  expect(r.afterFailure.summaryAfterDownstreamConsumerCall).toBe('');

  expect(r.afterRecovery.badge).toBe('LIVE');
  expect(r.afterRecovery.payload).toBe('IWM');
  // REGRESSION LOCK: a same-ticker-only check would pass even if stale zone numbers survived.
  expect(r.afterRecovery.zoneRanges).toEqual(['30.00 – 40.00']);
  expect(r.afterRecovery.zoneRanges).not.toEqual(r.afterValid.zoneRanges);
});

test('a SUCCESSFUL ticker switch invalidates the prior ticker liquidity snapshot immediately', async ({ page }) => {
  // MEASURED 2026-09-11 (independent review of the merged fix): _lastLiquidityMapPayload was
  // invalidated on a FAILED poll but never on a successful ticker CHANGE -- the prior ticker's
  // accepted snapshot stayed in place, with no ticker check of its own, until the NEW ticker's
  // poll happened to complete. setActiveTicker (the one commit point for every switch trigger)
  // now invalidates it directly, the same way every other ticker-scoped piece of state is reset.
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    window.setActiveTicker('SPY', null);
    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({ ticker: 'SPY', snapshot_type: 'live', summary: { auction_interpretation: 'bullish_acceptance' }, zones: [{ zone_type: 'value_area', zone_low: 1, zone_high: 2 }] }) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const beforeSwitch = {
      payload: window._lastLiquidityMapPayload?.ticker,
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      auctionPathVisible: document.getElementById('lm-auction-path')?.style.display,
    };
    // switch to QQQ -- do NOT let its own poll resolve; check state IMMEDIATELY.
    window.fetch = () => new Promise(() => {}); // never resolves
    window.setActiveTicker('QQQ', null);
    const afterSwitchBeforeAnyResponse = {
      payload: window._lastLiquidityMapPayload,
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      zoneRanges: Array.from(document.querySelectorAll('#lm-zones .lm-zone-price')).map((e) => e.textContent),
      auctionPathHtml: document.getElementById('lm-auction-path')?.innerHTML,
      // the independent downstream consumer must have nothing stale left to repaint either
      summaryAfterDownstreamConsumerCall: (window.patchLiquidityMapSummaryFromLivePlane(),
        document.getElementById('lm-summary-section')?.innerHTML),
    };
    window.fetch = realFetch;
    return { beforeSwitch, afterSwitchBeforeAnyResponse };
  });
  expect(r.beforeSwitch.payload).toBe('SPY');
  expect(r.beforeSwitch.badge).toBe('LIVE');
  expect(r.beforeSwitch.auctionPathVisible).toBe('block');
  // REGRESSION LOCK: pre-fix, all of these stayed SPY's valid data until QQQ's own poll
  // completed -- which in this test never happens, proving the invalidation is immediate and
  // does not depend on the new ticker's request finishing.
  expect(r.afterSwitchBeforeAnyResponse.payload).toBeNull();
  expect(r.afterSwitchBeforeAnyResponse.badge).toBe('UNAVAILABLE');
  expect(r.afterSwitchBeforeAnyResponse.zoneRanges).toEqual([]);
  expect(r.afterSwitchBeforeAnyResponse.auctionPathHtml).toBe('');
  expect(r.afterSwitchBeforeAnyResponse.summaryAfterDownstreamConsumerCall).toBe('');
});

test('watchlist % change renders for a non-sentinel symbol from real bars data, not an unconditional dash', async ({ page }) => {
  // MEASURED 2026-09-11 (independent review): WL names every enrolled watchlist symbol
  // (SPY/QQQ/IWM/NVDA/TSLA), but the % change dict paint() reads from is hardcoded to the
  // three sentinel market-context fields (spy_chg_pct/qqq_chg_pct/iwm_chg_pct) -- NVDA and
  // TSLA showed "--" unconditionally regardless of what the backend actually had, because
  // /api/bars1m data for them (already fetched for the sparkline) was never used to derive one.
  // loadSparks() is a closure-private function (not exposed on window), so this exercises it
  // through the real page-load path it actually runs on, via network interception.
  await page.route('**/api/bars1m?ticker=NVDA', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ bars: [{ c: 100 }, { c: 101 }, { c: 105 }] }),
  }));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    const row = document.querySelector('.cv-wlrow[data-sym="NVDA"]');
    const out = row ? row.querySelector('[data-chg]') : null;
    return out && out.textContent !== '—';
  }, undefined, { timeout: 20000 });
  const r = await page.evaluate(() => {
    const row = document.querySelector('.cv-wlrow[data-sym="NVDA"]');
    const out = row ? row.querySelector('[data-chg]') : null;
    return { text: out ? out.textContent : null, cls: out ? out.className : null };
  });
  // REGRESSION LOCK: pre-fix this was unconditionally "--" / "cv-chg cv-mu" for NVDA/TSLA.
  expect(r.text).toBe('+5.00%');
  expect(r.cls).toContain('cv-up');
});

test('an empty or malformed 200 response is treated as UNAVAILABLE, not a confident LIVE label', async ({ page }) => {
  // MEASURED 2026-09-11: `{}` has a falsy .ticker, so `data.ticker && mismatch` short-circuited
  // to false and the empty object was accepted and rendered with snapshot_type defaulting to
  // 'live'. A well-formed EMPTY result (the real ticker, genuinely zero zones) must still be
  // accepted -- this is the "preserve legitimate empty states" half of the same fix.
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    window.setActiveTicker('SPY', null);
    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({}) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterEmptyObject = { badge: document.getElementById('lm-snapshot-badge')?.textContent };

    window.fetch = async (url) => String(url).includes('liquidity-snapshot')
      ? { ok: true, json: async () => ({ ticker: 'SPY', snapshot_type: 'live', zones: [] }) }
      : realFetch(url);
    await window.pollLiquiditySnapshot();
    const afterLegitimateEmpty = {
      badge: document.getElementById('lm-snapshot-badge')?.textContent,
      payload: window._lastLiquidityMapPayload?.ticker,
    };
    window.fetch = realFetch;
    return { afterEmptyObject, afterLegitimateEmpty };
  });
  // REGRESSION LOCK: pre-fix this was 'LIVE' with no ticker and no real content.
  expect(r.afterEmptyObject.badge).toBe('UNAVAILABLE');
  expect(r.afterLegitimateEmpty.badge).toBe('LIVE');
  expect(r.afterLegitimateEmpty.payload).toBe('SPY');
});

test('an older response cannot overwrite a newer one within the same unchanged ticker/generation', async ({ page }) => {
  // MEASURED 2026-09-11: two overlapping requests for the SAME (ticker, generation) are not
  // distinguished by ticker/gen equality alone -- whichever response ARRIVES last wins, even
  // when it was DISPATCHED first and is chronologically stale by the time it resolves.
  const r = await page.evaluate(async () => {
    const realFetch = window.fetch.bind(window);
    window.setActiveTicker('TSLA', null);
    const zoneRangeTexts = () => Array.from(document.querySelectorAll('#lm-zones .lm-zone-price')).map((e) => e.textContent);

    let resolveOld;
    let dispatchCount = 0;
    window.fetch = (url) => {
      if (!String(url).includes('liquidity-snapshot')) return realFetch(url);
      dispatchCount += 1;
      if (dispatchCount === 1) {
        return new Promise((res) => { resolveOld = res; }); // held open -- the OLDER dispatch
      }
      // the NEWER dispatch resolves immediately, first
      return Promise.resolve({ ok: true, json: async () => ({ ticker: 'TSLA', snapshot_type: 'live', zones: [{ zone_type: 'value_area', zone_low: 9, zone_high: 10 }] }) });
    };
    const pOld = window.pollLiquiditySnapshot();       // dispatch 1 -- held
    await new Promise((r2) => setTimeout(r2, 10));
    const pNew = window.pollLiquiditySnapshot();        // dispatch 2 -- resolves first, renders
    await pNew;
    const afterNewer = { zoneRanges: zoneRangeTexts() };
    // now let the OLDER, held-open request resolve -- LAST to arrive, but chronologically stale
    resolveOld({ ok: true, json: async () => ({ ticker: 'TSLA', snapshot_type: 'live', zones: [{ zone_type: 'value_area', zone_low: 1, zone_high: 2 }] }) });
    await pOld;
    const afterOlderArrivesLate = { zoneRanges: zoneRangeTexts() };

    window.fetch = realFetch;
    return { afterNewer, afterOlderArrivesLate };
  });
  expect(r.afterNewer.zoneRanges).toEqual(['9.00 – 10.00']);
  // REGRESSION LOCK: pre-fix the older, later-arriving response overwrote the newer one here.
  expect(r.afterOlderArrivesLate.zoneRanges).toEqual(['9.00 – 10.00']);
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
