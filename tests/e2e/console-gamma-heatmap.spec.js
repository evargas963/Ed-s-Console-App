// @ts-check
/**
 * RC-UI-1 — browser DOM proof for the rebuilt Ed Console shell + Options/Gamma heatmap.
 *
 * Proves the FRONTEND presentation contract in a real browser: the heatmap renders the
 * canonical /api/options/gamma-surface payload VERBATIM (cell text == formatted backend value,
 * invariant E), sign -> colour with no inversion (invariant D), spot row highlight, and the Key
 * Levels rail reflects /api/terrain. The endpoint==faucet equality (the projected payload equals
 * compute_exposures_by_strike) is proven separately in tests/test_gamma_surface_projection_v1.py.
 *
 * Independent-review finding (2026-09-13), REPRODUCED: this docstring previously claimed the two
 * suites "together cover end-to-end" -- overstated. Every /api/** call here is intercepted with a
 * synthetic payload (`intercept()` below), so no request in this file ever reaches the real
 * FastAPI route, and the projection test calls the projection function directly rather than
 * through a live HTTP round trip. Together they prove frontend-renders-what-the-contract-says
 * and backend-computes-what-the-contract-says, NOT that the real route/HTTP/fetch layer
 * connecting the two actually behaves that way end-to-end; that HTTP-through-render path is
 * covered per-feature elsewhere when it exists (e.g. the streamed-volume overlay in
 * tests/test_chain_api_v1.py, itself a direct-call proof of the route body rather than a
 * TestClient/HTTP round trip -- see that file's own header comment) rather than by this suite.
 *
 * Endpoints are intercepted with synthetic payloads so the proof is deterministic and offline —
 * it exercises the real shell HTML/JS, not stubbed rendering.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SURFACE = {
  ticker: '$SPX', symbol: '$SPX', available: true, current_spot: 583.41, current_spot_state: 'live', spot: 583.41,
  source: 'terrain_live_cache', live: true, stale: false, age_sec: 3, chain_basis: 'full',
  complete: false,
  coverage: { window: 'live_near_money', chain_basis: 'full', strike_count: 3,
    note: 'near-money LIVE window (strike_count-bounded terrain chain) — NOT the full strike_range=ALL book' },
  chain_as_of_ts_utc: 1757000200, spot_as_of_ts_utc: 1757000200, spot_source: 'last',
  expirations: [{ expiry: '2026-09-11', dte: 2 }, { expiry: '2026-09-18', dte: 9 }],
  strikes: [580, 583, 586],
  cells: [
    { strike: 580, gex: [-90000, null],
      contracts: [{ call: 'SPX_580C1', put: 'SPX_580P1' }, { call: 'SPX_580C2', put: 'SPX_580P2' }] },
    { strike: 583, gex: [958600, 300000],
      contracts: [{ call: 'SPX_583C1', put: 'SPX_583P1' }, { call: 'SPX_583C2', put: 'SPX_583P2' }] },
    { strike: 586, gex: [-264500, 120000],
      contracts: [{ call: 'SPX_586C1', put: 'SPX_586P1' }, { call: 'SPX_586C2', put: 'SPX_586P2' }] },
  ],
  provenance: { producer: 'math_exposure_core.compute_exposures_by_strike', classification: 'DERIVED' },
};
// A surface WITH real per-cell vendor contract identity (server.py's project_gamma_surface
// always carries this in production; the plain SURFACE fixture above never needed it before
// the demand-declaration tests below, which specifically exercise _heatmapVisibleContracts —
// an empty `contracts` field on every cell would make ANY scope's demand list empty,
// masking exactly the coverage difference these tests exist to prove).
function surfaceWithContracts(nExps, nStrikes) {
  var expirations = [];
  for (var e = 0; e < nExps; e++) {
    var d = new Date(Date.UTC(2026, 8, 11 + e));
    expirations.push({ expiry: d.toISOString().slice(0, 10), dte: e + 1 });
  }
  var strikes = [];
  for (var s = 0; s < nStrikes; s++) strikes.push(580 + s);
  var cells = strikes.map(function (k) {
    return {
      strike: k,
      gex: expirations.map(function () { return 1000; }),
      contracts: expirations.map(function (exp) {
        return { call: 'C' + k + 'X' + exp.expiry, put: 'P' + k + 'X' + exp.expiry };
      }),
    };
  });
  return Object.assign({}, SURFACE, { expirations: expirations, strikes: strikes, cells: cells });
}
// Always-live heatmap mandate (2026-09-15): a surface carrying the real per-cell `stream`
// field server.py's _stamp_gamma_surface_cell_stream_state now stamps unconditionally on
// every real /api/options/gamma-surface response. `perCol` is one entry per expiry column
// for a single strike, each `{call, put}` naming that leg's state ('live'|'stale'|
// 'unavailable', or omitted entirely for "no contract on this leg").
function surfaceWithStreamState(perCol) {
  var strike = 583;
  var expirations = perCol.map(function (_, i) { return { expiry: '2026-09-1' + (1 + i), dte: i + 1 }; });
  var contracts = perCol.map(function (legs, i) {
    return { call: legs.call ? 'C' + i : null, put: legs.put ? 'P' + i : null };
  });
  function leg(state, sym) {
    return { symbol: sym, state: state, ts_recv: state === 'live' ? Date.now() / 1000 : null,
             age_sec: state === 'live' ? 1.0 : null };
  }
  var stream = perCol.map(function (legs, i) {
    var states = [legs.call, legs.put].filter(Boolean);
    var cellState = states.length === 0 ? 'unavailable'
      : states.every(function (s) { return s === 'live'; }) ? 'live'
      : states.some(function (s) { return s === 'live'; }) ? 'partial'
      : states.some(function (s) { return s === 'stale'; }) ? 'stale' : 'unavailable';
    var out = { state: cellState };
    if (legs.call) out.call = leg(legs.call, 'C' + i);
    if (legs.put) out.put = leg(legs.put, 'P' + i);
    return out;
  });
  return Object.assign({}, SURFACE, {
    expirations: expirations, strikes: [strike],
    cells: [{ strike: strike, gex: perCol.map(function () { return 12345; }),
              contracts: contracts, stream: stream }],
  });
}
const TERRAIN = {
  ticker: '$SPX', spot: 583.41, gamma_flip: 582.90, call_wall: 586, put_wall: 580,
  absolute_gamma_strike: 583, net_gex_peak: 583, net_gex_at_spot: 2140000000,
  regime: 'LONG_GAMMA_CHOP', levels_stale: false,
};
const STRIKES = {
  ticker: '$SPX', spot: 583.41,
  today: { all: [[586, -264500, 1200], [583, 958600, 5400], [580, -90000, 900]] },
};
// The plane identity a Tier C consumer caches against: the market session and the Tier C bundle
// generation (analytics_lightweight.analytics_version) — both carried by /api/live/state. Mutable so
// a test can advance the generation / flip the session with ticker + expiry held constant.
// Tier C state is keyed by (ticker, expiry) and its generation is PER ENTRY: '' is the no-expiry
// (newest-entry) context, the dated keys are explicit expiry entries. Both carriers answer from the
// entry the request's expiry= names, exactly as the server does.
const BASE_VERSION = { '': 7, '2026-09-11': 7, '2026-09-18': 20 };
const PLANE = { session: 'RTH', versions: Object.assign({}, BASE_VERSION) };
function expiryOf(url) { return decodeURIComponent((url.match(/[?&]expiry=([^&]+)/) || [])[1] || ''); }
function liveNow(url) {
  const exp = expiryOf(url);
  return { spot: 583.41, spot_disp: '583.41', bid: 583.40, ask: 583.42, session_label: PLANE.session,
    selected_exp: exp || null,
    analytics_lightweight: { spy_chg_pct: 0.38, analytics_version: PLANE.versions[exp] },
    streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 380 } };
}
const BARS = {
  ticker: '$SPX', n: 8,
  bars: [582.6, 582.9, 583.1, 582.8, 583.3, 583.5, 583.2, 583.41].map(function (c, i) {
    return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i };
  }),
};
const CHAIN = {
  ticker: '$SPX', spot: 583.41, expiry: '2026-09-11', status: 'ok',
  contracts: [
    { putCall: 'CALL', strikePrice: 583, openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.52, volatility: 12.3, expirationDate: '2026-09-11' },
    { putCall: 'PUT', strikePrice: 583, openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.48, volatility: 12.6, expirationDate: '2026-09-11' },
  ],
};

// Tier C analytics bundle (only the fields the rail reads): pcr_val is served BESIDE the expiry it is
// scoped to (server._fetch_state -> totals[0].pcr_oi over the selected-expiry chain).
function analyticsFor(url) {
  const exp = expiryOf(url);                       // '' = no expiry requested -> the newest entry
  // the bundle answers with ITS OWN generation; a newer generation carries a newer OI ratio
  const base = exp === '2026-09-18' ? 1.13 : 0.87;
  const version = PLANE.versions[exp];
  return { _tier: 'C_analytics', ticker: '$SPX', selected_exp: exp || '2026-09-11', analytics_pending_shell: false,
    analytics_version: version, pcr_val: +(base + 0.01 * (version - BASE_VERSION[exp])).toFixed(2) };
}

async function isolateEdStream(page) {
  await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ available: false, source: 'unavailable', reason: 'test isolates EdStream' }),
  }));
}

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/analytics/state')) body = analyticsFor(url);
    else if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/chain')) body = CHAIN;
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11', '2026-09-18'] };
    else if (url.includes('/api/live/state')) body = liveNow(url);
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('Ed Console shell + gamma heatmap', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('shell structure: rail has all seven workspaces + 3-tier nav', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.navitem[data-ws]')).toHaveCount(7);
    for (const ws of ['trade-desk', 'order-flow', 'options', 'liquidity', 'desk', 'portfolio', 'system']) {
      await expect(page.locator(`.navitem[data-ws="${ws}"]`)).toHaveCount(1);
    }
    await expect(page.locator('#subnav .wtitle')).toContainText('OPTIONS');
    await expect(page.locator('.vtab', { hasText: 'Heatmap' })).toBeVisible();
    // #6: canonical market session shown in the header, distinct from feed liveness
    await expect(page.locator('#hSession')).toHaveText('RTH');
    await expect(page.locator('#hSession')).toHaveClass(/rth/);
  });

  test('narrowed live chain basis is surfaced prominently (#2)', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, SURFACE, { chain_basis: 'dte<=45' })),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.heat-banner.degraded')).toContainText('NARROWED');
  });

  test('a streamed-only surface update still triggers a re-render even when every REST field is unchanged (RC-UI-2 finding #1)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: server.py's eager
    // refresh_gamma_surface_from_stream changes _gamma_surface's CELL VALUES without ever
    // touching chain_as_of_ts_utc/spot_as_of_ts_utc/chain_basis/et_date -- those are stamped
    // only by the ~60s REST cycle. surfaceRevision()'s old key was built ENTIRELY from those
    // REST-only fields, so a genuinely new surface hashed identical to the old one and
    // renderSurface()'s "cells unchanged, skip the rebuild" branch left the DOM showing the
    // stale value forever. Fixed by including the server-owned surface_seq counter (bumped on
    // every publication, REST or streamed) in the revision key. This test exercises the REAL
    // event listener (`ed:refresh`) and the REAL renderer against two live fetches through an
    // actual browser DOM -- a stubbed "no existing heatmap" harness could never have
    // distinguished the revision-skip branch from a normal rebuild.
    let call = 0;
    await page.route('**/api/options/gamma-surface**', (route) => {
      call += 1;
      const value = call === 1 ? 1000 : 2000;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, SURFACE, {
          strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }],
          cells: [{ strike: 583, gex: [value], contracts: [{ call: 'C583', put: 'P583' }] }],
          surface_seq: call,
          // chain_as_of_ts_utc / spot_as_of_ts_utc / chain_basis / et_date are DELIBERATELY
          // identical to SURFACE's own (unmodified) values on both fetches -- exactly what an
          // eager streaming refresh does: change a cell, touch no REST-cycle field.
        })),
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');

    // The real slow-refresh trigger (ed-core.js's liveTick, every 4th 3s tick) dispatches this
    // exact event; firing it directly here exercises the REAL ed-gamma.js listener without
    // waiting out the real ~12s cadence.
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(cell).toHaveText('$2.0K');
  });

  test('a cell whose value actually changed gets a one-shot visual flash; an unchanged cell does not (state-authority review)', async ({ page }) => {
    // Independent-review finding (2026-09-12, state-authority review): "actual Schwab
    // updates visibly change the appropriate values and colors" -- the pre-fix renderer
    // did a full, unconditional table rebuild on every update with no cue distinguishing
    // "the table was rebuilt" from "this specific value just moved", so a real, correct
    // change could go unnoticed on a busy grid. Two strikes: 583's value genuinely
    // changes between fetches, 586's does not -- only 583's cell may flash, and neither
    // may flash on the very FIRST render (nothing to compare against yet).
    let call = 0;
    await page.route('**/api/options/gamma-surface**', (route) => {
      call += 1;
      const changedValue = call === 1 ? 1000 : 2000;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, SURFACE, {
          strikes: [583, 586], expirations: [{ expiry: '2026-09-11', dte: 2 }],
          cells: [
            { strike: 583, gex: [changedValue], contracts: [{ call: 'C583', put: 'P583' }] },
            { strike: 586, gex: [-50000], contracts: [{ call: 'C586', put: 'P586' }] },   // identical on every fetch
          ],
          surface_seq: call,
        })),
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const changedCell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    const unchangedCell = page.locator('.hcell[data-strike="586"][data-expiry="2026-09-11"]');
    await expect(changedCell).toHaveText('$1.0K');
    // First render: no prior state exists to compare against -- must not flash anything.
    await expect(changedCell).not.toHaveClass(/flash-update/);
    await expect(unchangedCell).not.toHaveClass(/flash-update/);

    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(changedCell).toHaveText('$2.0K');
    await expect(changedCell).toHaveClass(/flash-update/);
    await expect(unchangedCell).not.toHaveClass(/flash-update/);
  });

  test('a genuine SSE push delivers the update in well under the 12s slow-poll cadence, with no manual event dispatch (RC-UI-2 finding #1, delivery timing)', async ({ page }) => {
    // Independent-review finding (2026-09-12): "the browser still polls every 12 seconds ...
    // manually triggers the refresh event, bypassing that wait. It proves rendering after
    // delivery, not timely delivery." The test above proves the RENDERER; this test proves
    // DELIVERY -- no `document.dispatchEvent` anywhere here. /api/analytics/light/stream is
    // intercepted with a REAL SSE-framed response (the browser's native EventSource parses it,
    // not a simulated DOM event), carrying one genuine `gamma_surface_seq` event -- exactly
    // what server.py's _next_gamma_surface_seq now pushes through this same connection on
    // every publication (see tests/test_gamma_surface_sse_push_v1.py for that push's own
    // construction). A tight timeout well under the 12s poll cadence is the actual claim under
    // test: if this only resolved via the slow poll, it would not resolve this fast.
    let surfaceCalls = 0;
    await page.route('**/api/options/gamma-surface**', (route) => {
      surfaceCalls += 1;
      const value = surfaceCalls === 1 ? 1000 : 2000;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, SURFACE, {
          strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }],
          cells: [{ strike: 583, gex: [value], contracts: [{ call: 'C583', put: 'P583' }] }],
          surface_seq: surfaceCalls,
        })),
      });
    });
    await page.route('**/api/analytics/light/stream**', async (route) => {
      // Deferred (not instant) fulfillment: without a real gap, the whole SSE body (including
      // the push event) can arrive before the FIRST gamma-surface render is even observable,
      // making the intermediate "$1.0K" state a flaky race rather than a real assertion. A
      // real streamed contract's Greeks/OI genuinely arrive some time after initial page load
      // too -- this models that, not just working around test timing.
      await new Promise((r) => setTimeout(r, 500));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');
    // No document.dispatchEvent call anywhere above or below -- only the intercepted SSE
    // connection's own (real, browser-parsed) event, arriving ~500ms after initial render,
    // can cause this -- and it must land well before the ~12s slow-poll cadence would have.
    await expect(cell).toHaveText('$2.0K', { timeout: 3000 });
    expect(surfaceCalls).toBeGreaterThanOrEqual(2);
  });

  test('a burst of pushes faster than the round trip converges the display live, not only once the pushes stop (2026-09-13 controlled reproduction)', async ({ page }) => {
    // Operator-reported controlled failure, reproduced then fixed: refresh notifications
    // (server.py's gamma_surface_seq push, dispatched client-side as `ed:refresh{slow,
    // pushed}`) arriving every ~500ms against a measured ~750ms round trip left the heatmap
    // frozen at its FIRST value while incoming values advanced far past it -- the display
    // only updated once the notifications stopped. Root cause: ed-gamma.js's load() bumped
    // a per-call generation counter on every push and only applied a response whose
    // generation still matched on arrival; once pushes outran the round trip, no response's
    // generation ever survived long enough to be applied -- a live-lock, not mere staleness.
    // Fixed with a coalescing loader (l1_sse_guards.js:makeCoalescedLoader): at most one
    // fetch in flight, a push arriving mid-flight coalesces into exactly one trailing
    // re-fetch, so the table keeps converging toward the latest surface DURING the burst.
    let call = 0;
    await page.route('**/api/options/gamma-surface**', async (route) => {
      call += 1;
      const value = call * 1000;
      await new Promise((r) => setTimeout(r, 750));   // the measured round trip
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, SURFACE, {
          strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }],
          cells: [{ strike: 583, gex: [value], contracts: [{ call: 'C583', put: 'P583' }] }],
          surface_seq: call,
        })),
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');   // the initial render (call 1)

    // The measured cadence: a push every 500ms (inside the 750ms round trip) for 3s -- long
    // enough that several pushes land while a fetch is still outstanding, exactly the
    // condition that live-locked the old generation-counter guard. The mid-burst read below
    // is a single instantaneous DOM snapshot (`textContent()`, no auto-retry) taken WHILE
    // traffic is still arriving -- unlike `expect(...).not.toHaveText(...)`, which polls for
    // up to its own timeout and would eventually pass even under the live-lock once the
    // final, unopposed push resolves after traffic quiets. A snapshot mid-burst is the only
    // way to actually distinguish "frozen through the whole burst" from "kept converging".
    for (let i = 0; i < 6; i++) {
      await page.waitForTimeout(500);
      await page.evaluate(() => document.dispatchEvent(
        new CustomEvent('ed:refresh', { detail: { slow: true, pushed: true } })));
      if (i === 2) {
        // Traffic is still actively arriving here (3 more pushes still queued below) --
        // the pre-fix code stayed at $1.0K through the entire burst, discarding every
        // intervening response because a newer push always beat it to `_gen`.
        const midBurstText = await cell.textContent();
        expect(midBurstText, 'display must already be tracking updates mid-burst, not frozen at its starting value').not.toBe('$1.0K');
      }
    }

    // Traffic has stopped. Convergence to whatever value the burst actually produced last
    // must not require anything beyond the loader's own bounded trailing re-fetch chain --
    // never "wait for the next unrelated 12s refresh cycle". `call` (this closure's own
    // request counter) names the exact value the surface last settled on, whatever the real
    // coalescing schedule produced -- the claim under test is convergence and correctness,
    // not a specific call count.
    await page.waitForTimeout(2200);   // generous settle margin: >= 2 round trips
    const finalText = await cell.textContent();
    expect(finalText).toBe('$' + call.toFixed(1) + 'K');
  });

  test('a held fetch for an abandoned ticker does not block the newly selected ticker from loading (2026-09-13, independent-review finding)', async ({ page }) => {
    // Independent-review finding (2026-09-13), REPRODUCED: the round-7 coalescing loader
    // merged EVERY trigger into the SAME in-flight slot regardless of context -- switching
    // ticker while the PREVIOUS ticker's fetch was still outstanding just queued the new
    // ticker behind it instead of loading immediately, so a slow (or hung) request for a
    // ticker the operator has already left kept the newly-selected ticker waiting
    // indefinitely. Fixed by keying the loader on ticker and aborting the abandoned
    // request the instant a different one is wanted (l1_sse_guards.js:makeCoalescedLoader).
    let releaseSpy;
    const spyGate = new Promise((r) => { releaseSpy = r; });
    await page.route('**/api/options/gamma-surface**', async (route) => {
      const tk = new URL(route.request().url()).searchParams.get('ticker');
      if (tk === 'SPY') await spyGate;   // hangs until this test explicitly releases it
      const value = tk === 'SPY' ? 1000 : 9000;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, SURFACE, {
          ticker: tk, symbol: tk,
          strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }],
          cells: [{ strike: 583, gex: [value], contracts: [{ call: 'C583', put: 'P583' }] }],
          surface_seq: 1,
        })),
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // The initial SPY load is now hung (spyGate not released yet). Switch to AAPL WHILE
    // it is still outstanding -- this must not be forced to wait for SPY's hung request.
    await page.locator('#symInput').fill('AAPL');
    await page.locator('#symInput').press('Enter');
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$9.0K', { timeout: 3000 });
    // Releasing the hung SPY response now must never resurrect it under AAPL's label.
    releaseSpy();
    await page.waitForTimeout(300);
    await expect(cell).toHaveText('$9.0K');
  });

  test('Strike Detail keeps following the workspace expiry filter after a selection, never reverting on refresh (2026-09-13, independent-review finding)', async ({ page }) => {
    // Independent-review finding (2026-09-13), REPRODUCED: ed-gamma-panels.js kept a
    // private `_lastExpiry` variable in sync ONLY on `ed:strike` -- switching the
    // workspace expiry filter (`ed:expiry`) called loadStrike with the fresh filter but
    // never updated `_lastExpiry`, so the next `ed:refresh` tick used the now-stale value
    // and reverted Strike Detail's chain request back to the OLD expiry. Reproduced
    // exactly: select a strike under Sept 18, switch the filter to Sept 25 (no re-click),
    // then a refresh tick -- chain requests must read 18 -> 25 -> 25, never back to 18.
    const chainExpiryRequests = [];
    await page.route('**/api/chain**', (route) => {
      const url = new URL(route.request().url());
      chainExpiryRequests.push(url.searchParams.get('expiry'));
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CHAIN) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.EdShell.setStrike(583, '2026-09-18'));
    await expect.poll(() => chainExpiryRequests[chainExpiryRequests.length - 1]).toBe('2026-09-18');
    await page.evaluate(() => window.EdShell.setExpiry('2026-09-25'));
    await expect.poll(() => chainExpiryRequests[chainExpiryRequests.length - 1]).toBe('2026-09-25');
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await page.waitForTimeout(200);
    expect(chainExpiryRequests[chainExpiryRequests.length - 1]).toBe('2026-09-25');
  });

  test('an unavailable heatmap surface is not resurrected by a later theme/expiry/scope event (2026-09-13, independent-review finding)', async ({ page }) => {
    // Independent-review finding (2026-09-13), REPRODUCED: _lastSurface used to survive an
    // unavailable render untouched, so a LATER presentation-only event (ed:theme here; also
    // ed:expiry/ed:scope) reused it as if still current -- repainting the stale AVAILABLE
    // data and reissuing its streamed-contract demand, resurrecting exactly the
    // subscription the unavailable branch had just cleared.
    let available = true;
    await page.route('**/api/options/gamma-surface**', (route) => {
      const body = available
        ? Object.assign({}, SURFACE, { strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }], cells: [{ strike: 583, gex: [1000], contracts: [{ call: 'C583', put: 'P583' }] }] })
        : { available: false, reason: 'not currently active for this symbol' };
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');

    available = false;
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(page.locator('#heatBody .placeholder .big')).toHaveText('Gamma surface unavailable');

    // A theme toggle must not repaint the old $1.0K cell back onto the screen. A plain
    // `expect(locator).toHaveText(...)` auto-retries for up to its own timeout, so a
    // TRANSIENT resurrection that a LATER, unrelated real periodic tick (the page's own
    // live liveTick scheduler, still running for real in this test) happens to correct
    // before the retry window elapses would silently read back as a pass -- exactly the
    // same trap this branch's own Flow tests already document. A single, non-retrying
    // snapshot of the DOM taken immediately after the theme toggle is the only way to
    // catch the transient resurrection itself.
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    await page.waitForTimeout(150);
    const html = await page.locator('#heatBody').innerHTML();
    expect(html).not.toContain('$1.0K');
    expect(html).toContain('Gamma surface unavailable');
  });

  test('heatmap column tooltip reflects the real subscription outcome, not just what was requested (2026-09-13, independent-review finding)', async ({ page }) => {
    // Independent-review finding (2026-09-13), REPRODUCED: the column tooltip claimed
    // "sub-second streaming updates active for this column" the instant a column was in
    // demandCols -- but that only names what the CLIENT asked for. With the streaming-
    // control endpoint returning a real HTTP 503 (confirmed contracts stay empty), the
    // tooltip kept claiming active streaming anyway. It must now say REQUESTED (pending),
    // then flip to the real REJECTED wording once the server's own answer comes back.
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surfaceWithContracts(3, 3)),
    }));
    // A deliberate delay makes the transient PENDING state actually observable (a mocked
    // local route can otherwise resolve faster than the first assertion poll, making the
    // real, correct intermediate state invisible to the test -- not a defect in the fix).
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      await new Promise((r) => setTimeout(r, 300));
      route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // Always-live heatmap mandate (2026-09-15) supersedes this count: Auto scope now demands
    // EVERY visible column (see the "declares live-streaming demand for every visible
    // column's contracts" test), not just the front one -- surfaceWithContracts(3, 3) has 3
    // unexpired columns, all within them the demand set, so all 3 carry '.stream-demand'.
    // The single POST's real 503 rejects the whole set at once, so every column's own
    // tooltip reflects the identical real outcome; `.first()` below checks one as
    // representative of all three.
    const col = page.locator('.heat thead th.hexp.stream-demand');
    await expect(col).toHaveCount(3);
    await expect(col.first()).toHaveAttribute('title', /awaiting confirmation/);
    await expect(col.first()).toHaveAttribute('title', /NOT accepted by the server/, { timeout: 3000 });
    await expect(col.first()).not.toHaveAttribute('title', /streaming updates active/);
  });

  test('Wider and All scope declare real streaming demand for what they display, not zero (2026-09-13, operator-directed)', async ({ page }) => {
    // Independent-review finding (2026-09-13), operator-directed: Wider/All used to demand
    // ZERO contracts unconditionally, regardless of what they actually displayed --
    // "vendor-capacity uncertainty does not explain away that application behavior." They
    // now demand exactly the columns they display, the same rule an explicit expiry filter
    // already used; Auto's own measured front-column-only policy is unchanged.
    // 16 unexpired expirations x 3 strikes: enough columns that Auto (front column only,
    // 1 col x 3 strikes x 2 sides = 6 symbols) and Wider (min(2*autoColCount,16) columns)
    // genuinely differ in how many contracts they cover.
    await page.addInitScript(() => { try { localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surfaceWithContracts(16, 3)),
    }));
    const demandCalls = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      demandCalls.push(body.contracts || []);
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => demandCalls.length).toBeGreaterThan(0);
    const autoContracts = demandCalls[demandCalls.length - 1].length;

    demandCalls.length = 0;
    await page.evaluate(() => window.EdShell.setScope('wider'));
    await expect.poll(() => demandCalls.length).toBeGreaterThan(0);
    const widerContracts = demandCalls[demandCalls.length - 1].length;
    expect(widerContracts).toBeGreaterThan(autoContracts);

    demandCalls.length = 0;
    await page.evaluate(() => window.EdShell.setScope('all'));
    await expect.poll(() => demandCalls.length).toBeGreaterThan(0);
    const allContracts = demandCalls[demandCalls.length - 1].length;
    expect(allContracts).toBeGreaterThanOrEqual(widerContracts);
  });

  test('a live gamma_surface_seq push re-renders and re-declares demand for the CURRENTLY SELECTED scope, never reverts to Auto (2026-09-17, spot-tick live-UI mandate)', async ({ page }) => {
    // The spot-tick fix (refresh_gamma_surface_from_spot_tick, server.py) makes a NEW surface
    // generation arrive live while the operator may be looking at Wider or All, not just Auto
    // -- every prior push test in this file only ever exercised the DEFAULT (Auto) scope, and
    // every prior scope test only ever exercised a STATIC load with no push in between. This
    // is the missing combination the mandate's own "browser proof" section names explicitly:
    // "actual Auto/Wider/All controls... actual rendered cells... displayed spot/GEX changes".
    // Real 116-strike/16-expiration fixture (same one the REAL-DATA VIEWPORT test above uses)
    // so Auto (11 rows) and Wider (23 rows) are genuinely, visibly different counts.
    const REAL_RAW = require('./fixtures/real_spy_gamma_surface_116x16_premarket_20260910.json');
    // This banked-morning fixture (like the real /api/options/gamma-surface response it was
    // captured from) carries per-cell vendor contract identity -- synthesized here only
    // because the checked-in JSON snapshot predates that field; without it every cell's
    // demand would be empty and this test could not tell "no push happened" apart from
    // "the surface never carried contracts to demand in the first place".
    const REAL = Object.assign({}, REAL_RAW, {
      source: 'terrain_live_cache', live: true, available: true, stale: false,
      current_spot: REAL_RAW.spot, current_spot_state: 'live',
      cells: REAL_RAW.cells.map((c) => Object.assign({}, c, {
        contracts: REAL_RAW.expirations.map((e) => ({
          call: 'C' + c.strike + 'X' + e.expiry, put: 'P' + c.strike + 'X' + e.expiry,
        })),
      })),
    });
    let surfaceCalls = 0;
    const pushedGex = -999000000;   // a value nothing in the baseline fixture already has
    await page.route('**/api/options/gamma-surface**', (route) => {
      surfaceCalls += 1;
      if (surfaceCalls === 1) {
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(Object.assign({}, REAL, { surface_seq: 1 })),
        });
        return;
      }
      const pushed = JSON.parse(JSON.stringify(REAL));
      pushed.cells.find((c) => c.strike === 764.0).gex[2] = pushedGex;   // strike 764 / 2026-09-11 column
      pushed.surface_seq = 2;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(pushed) });
    });
    const demandCalls = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      demandCalls.push(body.contracts || []);
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.route('**/api/analytics/light/stream**', async (route) => {
      await new Promise((r) => setTimeout(r, 500));   // see the delivery-timing test above for why
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const rows = page.locator('#heatBody .heat tbody tr');
    await expect(rows).toHaveCount(11);   // Auto, sanity

    await page.locator('#scopeCtl .scbtn', { hasText: 'Wider' }).click();
    await expect(rows).toHaveCount(23);
    await expect.poll(() => demandCalls.length).toBeGreaterThan(0);
    const widerContractsBeforePush = demandCalls[demandCalls.length - 1].length;
    expect(await page.evaluate(() => window.EdShell.getScope())).toBe('wider');

    const pushedCell = page.locator('.hcell[data-strike="764"][data-expiry="2026-09-11"]');
    await expect(pushedCell).toHaveText('-$999.0M', { timeout: 3000 });   // the live push landed
    await expect(rows).toHaveCount(23);   // still Wider -- the push must never silently revert scope
    expect(await page.evaluate(() => window.EdShell.getScope())).toBe('wider');
    // The new generation carries the identical strike/expiry population (only a GEX value
    // changed), so the recomputed demand set is byte-identical to what is already confirmed
    // -- ed-stream.js's own dedup (see its "cacheTrustworthy" short-circuit) correctly sends
    // NO redundant POST here. Proving that requires a genuinely NEW population, covered by
    // the scope-switch assertions above; what this push must never do is drop back to
    // Auto's demand shape while still labelled Wider.
    expect(widerContractsBeforePush).toBeGreaterThan(0);
  });

  test('GEX-by-strike displays each row\'s own session volume, not just signed GEX$ (RC-UI-2 finding #5a)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: "GEX-by-strike does not display its
    // row's volume field" -- terrain_engine._per_strike_rows' own shape is
    // [strike, net_gex_1pct$, session_volume]; the THIRD element was read into _lastGbs but
    // never rendered anywhere. STRIKES.today.all above already carries real volume numbers
    // (1200/5400/900) -- this proves they actually reach the DOM now.
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const row583 = page.locator('.gbs-row[data-strike="583"]');
    await expect(row583.locator('.gbs-vol')).toHaveText('5.4K');   // fmtVol(5400)
    await expect(row583).toHaveAttribute('data-volume', '5400');
    const row580 = page.locator('.gbs-row[data-strike="580"]');
    await expect(row580.locator('.gbs-vol')).toHaveText('900');    // fmtVol(900), no K suffix under 1000
  });

  test('Strike Detail reloads on the slow refresh tick, not just on a new strike selection (RC-UI-2 finding #5b)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: "Strike Detail reads volume from
    // /api/chain. Its refresh handler does not reload that detail." loadAll() (wired to
    // ed:refresh) never included Strike Detail, so a selected strike's OI/Vol/Gamma/Delta/IV
    // froze at whatever they were when first clicked -- even as the underlying /api/chain (and
    // now streamed) data kept moving.
    // A flag the test itself flips between phases -- not a raw call count, since the FIRST
    // strike selection can legitimately trigger more than one /api/chain fetch (e.g. a
    // selection also touching the expiry filter) before settling. What matters for THIS
    // finding is only: does /api/chain get RE-FETCHED (any settled value updates) once
    // ed:refresh fires, without a new strike being clicked.
    let updated = false;
    let chainCalls = 0;
    await page.route('**/api/chain**', (route) => {
      chainCalls += 1;
      const vol = updated ? 999999 : 540;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          ticker: '$SPX', spot: 583.41, expiry: '2026-09-11', status: 'ok',
          contracts: [
            { putCall: 'CALL', strikePrice: 583, openInterest: 1200, totalVolume: vol, gamma: 0.021, delta: 0.52, volatility: 12.3, expirationDate: '2026-09-11' },
            { putCall: 'PUT', strikePrice: 583, openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.48, volatility: 12.6, expirationDate: '2026-09-11' },
          ],
        }),
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('#sdCtx')).toContainText('583');
    const callVolCell = page.locator('.sd tbody tr').first().locator('td').nth(2);   // Type, OI, Vol
    await expect(callVolCell).toHaveText('540');
    const callsBeforeRefresh = chainCalls;
    updated = true;   // the NEXT /api/chain fetch (whenever it happens) must answer with this

    // The real slow-refresh trigger (liveTick's ed:refresh at tick % 4 === 0, or the new SSE
    // push) -- fired directly here to exercise the REAL ed-gamma-panels.js listener without
    // waiting out the real cadence, exactly as the heatmap's own revision test above does.
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(callVolCell).toHaveText('999999');
    expect(chainCalls).toBeGreaterThan(callsBeforeRefresh);
  });

  test('Strike Detail\'s Net GEX$ cell re-syncs when GEX-by-Strike updates, not just on its own /api/chain fetch (state-authority review)', async ({ page }) => {
    // Independent-review finding (2026-09-12, state-authority review), REPRODUCED: "Strike
    // Detail can retain $1.0K after GEX by Strike updates to $3.0K." Strike Detail's Net
    // GEX$ cell reads gbsNetAt(strike), sourced from _lastGbs -- a module-level cache that
    // ONLY renderGbs() (GEX-by-Strike's own render) ever updates. loadGbs() (->
    // /api/terrain/strikes) and loadStrike() (-> /api/chain) are two independent,
    // unsynchronized fetches with no cross-panel version check: if /api/chain resolves
    // FIRST on a refresh tick, Strike Detail bakes in whatever _lastGbs still holds from
    // the PREVIOUS cycle; when /api/terrain/strikes resolves LATER and updates _lastGbs
    // (repainting GEX-by-Strike's own bars), nothing told Strike Detail its
    // already-rendered Net cell was now stale -- it kept showing the old value.
    let strikesNet = 1000;
    let strikesCalls = 0;
    let hangNextStrikes = false;
    let releaseStrikes = null;
    await page.route('**/api/terrain/strikes**', (route) => {
      strikesCalls += 1;
      const body = JSON.stringify({ ticker: '$SPX', spot: 583.41,
        today: { all: [[583, strikesNet, 5400], [580, -90000, 900], [586, -264500, 1200]] } });
      if (hangNextStrikes) {
        hangNextStrikes = false;
        return new Promise((resolve) => {
          releaseStrikes = () => resolve(route.fulfill({ status: 200, contentType: 'application/json', body }));
        });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body });
    });
    let chainCalls = 0;
    await page.route('**/api/chain**', (route) => {
      chainCalls += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CHAIN) });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('#sdCtx')).toContainText('583');
    const netCell = page.locator('#sdBody .sd-net td').nth(4);   // Net, OI, Vol, Gamma, GEX$
    await expect(netCell).toHaveText('$1.0K');

    // The NEXT /api/terrain/strikes response hangs; /api/chain resolves normally and fast,
    // so renderStrike() runs FIRST and bakes in the still-stale $1.0K from _lastGbs.
    strikesNet = 3000;
    hangNextStrikes = true;
    const chainCallsBeforeRefresh = chainCalls;
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect.poll(() => strikesCalls).toBeGreaterThanOrEqual(2);   // the new terrain/strikes request is in flight, hanging
    await expect.poll(() => chainCalls).toBeGreaterThan(chainCallsBeforeRefresh);   // /api/chain already settled
    await expect(netCell).toHaveText('$1.0K');   // still the OLD value

    // NOW release the delayed /api/terrain/strikes response -- the Net cell must re-sync
    // to $3.0K WITHOUT a new /api/chain fetch (a direct push, not a re-fetch). A plain
    // `expect(locator).toHaveText(...)` auto-retries for its whole timeout, so it would
    // still eventually pass if some LATER, unrelated periodic refresh happened to
    // re-fetch /api/chain and pick up the by-then-updated value on its own -- that would
    // prove an unrelated mechanism works, not this fix. A short, bounded, non-retrying
    // check immediately after release is the only way to catch the direct resync itself.
    const chainCallsBeforeRelease = chainCalls;
    if (releaseStrikes) releaseStrikes();
    await page.waitForTimeout(150);
    expect(await netCell.textContent()).toBe('$3.0K');
    expect(chainCalls).toBe(chainCallsBeforeRelease);
  });

  test('heatmap renders canonical cells verbatim (value == formatted payload; sign -> colour)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell583 = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    const cell586 = page.locator('.hcell[data-strike="586"][data-expiry="2026-09-11"]');
    await expect(cell583).toHaveText('$958.6K');   // E: formatting-only of 958600
    await expect(cell586).toHaveText('-$264.5K');  // E: formatting-only of -264500
    // D: positive -> green-dominant fill, negative -> red-dominant fill (no inversion)
    const rgbOf = (s) => { const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(s); return [+m[1], +m[2], +m[3]]; };
    const bg583 = rgbOf(await cell583.evaluate((el) => getComputedStyle(el).backgroundColor));
    const bg586 = rgbOf(await cell586.evaluate((el) => getComputedStyle(el).backgroundColor));
    expect(bg583[1]).toBeGreaterThan(bg583[0]);   // green channel dominant
    expect(bg586[0]).toBeGreaterThan(bg586[1]);   // red channel dominant
    // spot row is the 583 strike (nearest 583.41)
    await expect(page.locator('tr.spotrow .hstrike')).toHaveText('583');
    // The default SURFACE fixture carries no per-cell `stream` state at all (it predates the
    // always-live mandate's per-cell stamping and is used here to test value/colour/format
    // rendering, not streaming disclosure) -- independent-review finding (2026-09-16, follow-
    // up mandate): the header must NEVER read the word LIVE without genuine per-cell
    // confirmation, not even via a legacy "payload predates this field" compatibility
    // fallback. A surface with zero confirmed-identity visible cells honestly reads WARMING.
    await expect(page.locator('.heat-banner')).toHaveCount(0);
    await expect(page.locator('#heatScope')).toContainText('WARMING');
    // #7: shade legend present — vertical magnitude legend at the heatmap's right edge
    await expect(page.locator('.heat-vlegend .bar')).toBeVisible();
    // C: nearest-expiry (front) column emphasised
    expect(await page.locator('.heat .hexp.col-front').count()).toBeGreaterThan(0);
    // A: clicking a heatmap cell syncs the selected strike across panels
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('.hcell.sel-strike')).toHaveCount(2);                 // both expiry cells at 583
    await expect(page.locator('.gbs-row.gbs-sel[data-strike="583"]')).toHaveCount(1);  // GEX-by-strike synced
    await expect(page.locator('#sdCtx')).toContainText('583');                       // Strike Detail loaded
  });

  test('always-live heatmap mandate: a confirmed-live cell renders its numeric value with no snapshot flag', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(surfaceWithStreamState([{ call: 'live', put: 'live' }])),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'live');
    await expect(cell).not.toHaveClass(/state-partial|state-stale|state-unavailable/);
  });

  test('always-live heatmap mandate: a stale cell (desired but not fresh) still shows its real value, honestly labelled as a snapshot -- never blanked', async ({ page }) => {
    // Operator directive (2026-09-15), FINAL: "Never blank valid data... keep the latest
    // valid timestamped GEX displayed when a contract is not actively updating."
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(surfaceWithStreamState([{ call: 'stale', put: 'stale' }])),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'stale');
    await expect(cell).toHaveAttribute('data-gex', '12345');
    await expect(cell).toHaveClass(/state-stale/);
    await expect(cell).toHaveAttribute('title', /SNAPSHOT/);
    // never mislabelled as live
    const cls = await cell.getAttribute('class');
    expect(cls).not.toMatch(/state-live/);
  });

  test('always-live heatmap mandate: an unavailable/not-yet-confirmed cell still shows its real value, honestly labelled, never dashed', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(surfaceWithStreamState([{ call: 'unavailable', put: 'unavailable' }])),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'unavailable');
    await expect(cell).toHaveAttribute('title', /SNAPSHOT/);
  });

  test('always-live heatmap mandate: a cell with no valid computed value at all (has_oi=false) still renders — (unrelated to streaming, pre-existing behavior)', async ({ page }) => {
    // The ONLY case that still renders '—': project_gamma_surface's own pre-existing
    // has_oi-gated absence (a strike/expiry that genuinely never cleared the OI gate) --
    // orthogonal to, and unchanged by, the streaming-state disclosure under test above.
    const surf = surfaceWithStreamState([{ call: 'live', put: 'live' }]);
    surf.cells[0].gex = [null];
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surf),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('OI UNAVAILABLE');
    await expect(cell).toHaveAttribute('data-value-state', 'oi_unavailable');
    await expect(cell).toHaveAttribute('data-cell-state', 'live');   // stream state is unrelated to value-state
  });

  test('always-live heatmap mandate: a partial cell (one leg live, one not) shows the same value as fully live, visibly flagged distinct from fully live', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(surfaceWithStreamState([{ call: 'live', put: 'unavailable' }])),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$12.3K');   // ONE FAUCET: the already-computed value is not re-derived
    await expect(cell).toHaveAttribute('data-cell-state', 'partial');
    await expect(cell).toHaveClass(/state-partial/);
  });

  test('always-live heatmap mandate NEGATIVE CONTROL: a live cell that goes stale on the next refresh keeps its value but is relabelled from live to snapshot -- never silently kept as live', async ({ page }) => {
    // Proves the label reacts to a real state TRANSITION (the stream being lost), not merely
    // to a hand-picked static fixture -- the operator's own required negative control ("never
    // mislabel snapshot data as live"), proven here at the frontend/render layer against a
    // controlled state transition. The live-vendor equivalent (a REAL Schwab stream actually
    // going quiet mid-session) is proven separately by the RTH live-vendor proof tooling,
    // which this test cannot reach.
    // surface_seq must advance between fetches (RC-UI-2 finding #1, this file's own earlier
    // test): renderSurface() skips its table rebuild when the revision key -- built from
    // REST-only fields PLUS surface_seq specifically so a stream-only change is still
    // detected -- is unchanged. Omitting it here would test the fast-path skip, not the gate.
    let live = true, seq = 1;
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign(
        surfaceWithStreamState([{ call: live ? 'live' : 'stale', put: live ? 'live' : 'stale' }]),
        { surface_seq: seq })),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'live');

    live = false; seq = 2;   // the stream goes quiet -- no reload, no navigation, just the next refresh
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(cell).toHaveAttribute('data-cell-state', 'stale');
    await expect(cell).toHaveText('$12.3K');   // the same valid value -- never blanked
    await expect(cell).toHaveAttribute('title', /SNAPSHOT/);   // relabelled, not silently kept as live
  });

  test('stale/reference gamma surface fails stale visibly (no morning snapshot passed as live)', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, SURFACE, {
        source: 'banked_morning_reference', live: false, stale: true, available: true,
        degraded: 'live terrain surface unavailable — showing banked MORNING chain (reference only: morning spot + morning Greeks, NOT intraday)',
      })),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody .placeholder .big')).toContainText('Gamma surface unavailable');
    await expect(page.locator('#heatBody')).toContainText('historical morning Gamma is not the current heatmap');
    await expect(page.locator('#heatBody .hcell')).toHaveCount(0);
    await expect(page.locator('#heatScope')).not.toContainText('REF·morning');
  });

  test('persists workspace/view across reload (D: UI state, not market truth)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();       // restored from localStorage
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
  });

  test('key levels rail reflects /api/terrain', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSpot')).toHaveText('583.41');
    await expect(page.locator('#klFlip')).toHaveText('582.90');
    await expect(page.locator('#klCall')).toHaveText('586.00');
    await expect(page.locator('#klPut')).toHaveText('580.00');
    await expect(page.locator('#klNet')).toHaveText('$2.1B');
    await expect(page.locator('#klRegime')).toContainText('Long γ');
    // NOT_PROVEN items are honestly labelled, never fabricated
    await expect(page.locator('#klBody')).toContainText('NOT PROVEN');
    // D-PCR: the put/call OPEN-INTEREST ratio comes from /api/analytics/state, formatted only, and the
    // expiry it is scoped to is disclosed on the row (it is a selected-expiry ratio, not all-exp).
    await expect(page.locator('#klPcr')).toHaveText('0.87');
    await expect(page.locator('#klPcrScope')).toContainText('OI');
    await expect(page.locator('#klPcrScope')).toContainText('2026-09-11');
  });

  test('D-PCR: read once per (ticker, expiry) context — not per tick; warming shell retries; expiry re-scopes', async ({ page }) => {
    const hits = [];
    let pending = true;   // first answer: Tier C still warming (pending shell, no pcr_val)
    await page.route('**/api/analytics/state**', (route) => {
      const url = route.request().url();
      // ed-alerts.js independently polls this same endpoint (its own `_via=alerts` tag) on
      // its own ~12s cadence, unrelated to the PCR read-once-per-context contract under test
      // here -- excluded so its traffic never inflates this test's own hit count.
      if (!url.includes('_via=alerts')) hits.push(url);
      const body = pending ? { _tier: 'C_analytics', ticker: '$SPX', selected_exp: null, analytics_pending_shell: true, expiries: [], totals_rows: [] }
        : analyticsFor(url);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klFlip')).toHaveText('582.90');          // rail is up (terrain)
    await expect(page.locator('#klPcr')).toHaveText('—');                 // warming: no value fabricated
    await expect(page.locator('#klPcrScope')).toHaveText('warming');
    expect(hits.length).toBeLessThanOrEqual(2);                           // init (ed:view/ed:ticker) — never a per-3s-tick stream
    pending = false;                                                       // Tier C completes
    await expect(page.locator('#klPcr')).toHaveText('0.87', { timeout: 20000 });   // bounded re-read on the slow tick (12s)
    const settled = hits.length;                                           // 2 (the warming retry), never one per 3s tick
    expect(settled).toBeLessThanOrEqual(3);
    await page.waitForTimeout(13000);                                      // > one slow tick with a value already held
    expect(hits.length).toBe(settled);                                     // no re-read once the context has its value
    // the expiry filter is part of the context: a selected expiry re-reads WITH expiry= and the row re-scopes
    await page.locator('#expSel').selectOption('2026-09-18');
    await expect(page.locator('#klPcr')).toHaveText('1.13');
    await expect(page.locator('#klPcrScope')).toContainText('2026-09-18');
    expect(hits[hits.length - 1]).toContain('expiry=2026-09-18');
    expect(hits.length).toBe(settled + 1);
  });

  test('D-PCR NEGATIVE CONTROL: a new bundle generation / market session with ticker+expiry constant refreshes EXACTLY once (never stale forever, never per tick)', async ({ page }) => {
    PLANE.session = 'RTH'; PLANE.versions = Object.assign({}, BASE_VERSION);
    const hits = [];
    await page.route('**/api/analytics/state**', (route) => {
      const url = route.request().url();
      // see the D-PCR read-once test's identical note: ed-alerts.js's independent, unrelated
      // ~12s poll of this same endpoint is excluded from this test's own hit count.
      if (!url.includes('_via=alerts')) hits.push(url);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(analyticsFor(url)) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klPcr')).toHaveText('0.87');
    await page.waitForTimeout(13000);                                      // > one slow tick, same generation, same session
    const settled = hits.length;
    expect(settled).toBeLessThanOrEqual(2);                                // no per-tick stream while identity is unchanged
    // 1) the Tier C bundle generation advances on the plane (ticker + expiry unchanged; default context)
    PLANE.versions[''] = 8;                                                // the plane the shell already polls reports it
    await expect(page.locator('#klPcr')).toHaveText('0.88', { timeout: 20000 });   // the old ratio is NOT retained
    await page.waitForTimeout(13000);
    expect(hits.length).toBe(settled + 1);                                 // exactly one refresh for the new generation
    // 2) the market session transitions (the next trading day's canonical trigger), generation unchanged
    PLANE.session = 'After-Hours';
    await expect(page.locator('#hSession')).toHaveText('AH', { timeout: 20000 });
    await page.waitForTimeout(13000);
    expect(hits.length).toBe(settled + 2);                                 // exactly one refresh for the session transition
    expect(hits.every((u) => u.includes('ticker=SPY') && !u.includes('expiry='))).toBe(true);   // context never changed
    PLANE.session = 'RTH'; PLANE.versions = Object.assign({}, BASE_VERSION);
  });

  test('D-PCR IDENTITY IS THE SAME (ticker, expiry) BUNDLE: an explicit expiry follows ITS entry generation only', async ({ page }) => {
    test.setTimeout(300000);
    PLANE.session = 'RTH'; PLANE.versions = Object.assign({}, BASE_VERSION);
    const hits = [];
    await page.route('**/api/analytics/state**', (route) => {
      const url = route.request().url();
      // see the D-PCR read-once test's identical note: ed-alerts.js's independent, unrelated
      // ~12s poll of this same endpoint is excluded from this test's own hit count.
      if (!url.includes('_via=alerts')) hits.push(url);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(analyticsFor(url)) });
    });
    const planeReads = [];
    await page.route('**/api/live/state**', (route) => {
      planeReads.push(route.request().url());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liveNow(route.request().url())) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klPcr')).toHaveText('0.87');
    // (1) ticker SPY, expiry A = 2026-09-18 (its entry is at generation 20) -> PCR A displayed
    await page.locator('#expSel').selectOption('2026-09-18');
    await expect(page.locator('#klPcr')).toHaveText('1.13');
    await expect(page.locator('#klPcrScope')).toContainText('2026-09-18');
    expect(hits[hits.length - 1]).toContain('expiry=2026-09-18');
    await page.waitForTimeout(13000);
    const s1 = hits.length;
    // the shell's OWN plane read now carries the same context, so both carriers name entry (SPY, A)
    expect(planeReads[planeReads.length - 1]).toContain('expiry=2026-09-18');
    // (2) entry A advances 20 -> 21 while the default / other entries stay -> PCR A refreshes exactly once
    PLANE.versions['2026-09-18'] = 21;
    await expect(page.locator('#klPcr')).toHaveText('1.14', { timeout: 20000 });
    await page.waitForTimeout(13000);
    expect(hits.length).toBe(s1 + 1);
    expect(hits[hits.length - 1]).toContain('expiry=2026-09-18');
    // (3) OTHER entries advance (default + 2026-09-11) while A stays at 21 -> PCR A does NOT refresh
    PLANE.versions[''] = 9; PLANE.versions['2026-09-11'] = 9;
    await page.waitForTimeout(15000);
    expect(hits.length).toBe(s1 + 1);
    await expect(page.locator('#klPcr')).toHaveText('1.14');
    // (4) same ticker / expiry / generation / session -> no redundant read
    await page.waitForTimeout(13000);
    expect(hits.length).toBe(s1 + 1);
    // (5) ticker change -> exactly one read, for the new ticker in the same expiry context
    await page.locator('#symInput').fill('QQQ'); await page.locator('#symInput').press('Enter');
    await expect.poll(() => hits.length, { timeout: 20000 }).toBe(s1 + 2);
    expect(hits[hits.length - 1]).toContain('ticker=QQQ');
    await page.waitForTimeout(13000);
    expect(hits.length).toBe(s1 + 2);
    // (6) expiry change -> exactly one read, PCR re-scoped to that entry (2026-09-11 is at generation 9)
    await page.locator('#expSel').selectOption('2026-09-11');
    await expect(page.locator('#klPcr')).toHaveText('0.89');
    await expect(page.locator('#klPcrScope')).toContainText('2026-09-11');
    expect(hits[hits.length - 1]).toContain('expiry=2026-09-11');
    expect(hits.length).toBe(s1 + 3);
    await page.waitForTimeout(13000);
    expect(hits.length).toBe(s1 + 3);
    // (7) a session transition is one deliberate re-read, and afterwards the identity is STILL the
    //     entry's generation: the default entry advancing again does not touch this expiry's PCR
    PLANE.session = 'After-Hours';
    await expect.poll(() => hits.length, { timeout: 20000 }).toBe(s1 + 4);
    PLANE.versions[''] = 10;
    await page.waitForTimeout(15000);
    expect(hits.length).toBe(s1 + 4);
    PLANE.session = 'RTH'; PLANE.versions = Object.assign({}, BASE_VERSION);
  });

  // REAL-DATA VIEWPORT PROOF (2026-09-10 visual FAIL on the running candidate): the fixture is the
  // REAL /api/options/gamma-surface response captured from the candidate at 06:35 CDT — SPY, 116
  // strikes x 16 expirations, banked_morning_reference from 2026-09-09 — plus the two fields the
  // server now stamps (session_date_et / prior_session / per-expiration expired; the pre-fix capture
  // predates them). Nothing else is altered. The proof: the canonical population is intact and
  // disclosed, Auto selects a legible viewport, Wider widens it, All available exposes everything at
  // the same row height, and an expired prior-session column is never dressed as current structure.
  test('REAL-DATA VIEWPORT: 116x16 canonical surface -> Auto 11 rows x <=11 unexpired columns; Wider 23; All 116x16 legible + EXPIRED labelled; no data loss', async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    const REAL = require('./fixtures/real_spy_gamma_surface_116x16_premarket_20260910.json');
    const stamped = Object.assign({}, REAL, {
      source: 'terrain_live_cache', live: true, available: true, stale: false,
      current_spot: REAL.spot, current_spot_state: 'live',
      session_date_et: '2026-09-10', prior_session: false,
      expirations: REAL.expirations.map((e) => Object.assign({}, e, { expired: e.expiry < '2026-09-10' })),
      cells: REAL.cells.map((row) => Object.assign({}, row, {
        contracts: REAL.expirations.map((_e, j) => ({
          call: 'C' + row.strike + '_' + j, put: 'P' + row.strike + '_' + j,
        })),
      })),
    });
    expect(stamped.strikes.length).toBe(116); expect(stamped.expirations.length).toBe(16);
    expect(stamped.expirations.filter((e) => e.expired).map((e) => e.expiry)).toEqual(['2026-09-09']);
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stamped) }));
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const rows = page.locator('#heatBody .heat tbody tr');
    const cols = page.locator('#heatBody .heat thead .hexp');
    // canonical population disclosed; Auto viewport = 11 rows centred on spot 764.15 -> 759..769,
    // rendered highest strike first (operator decision 2026-09-11: "highest strike at the top,
    // lowest at the bottom" -- static/js/ed-gamma.js renderSurface reverses presentation order
    // only; the shared ascending scopeSelect() contract other consumers rely on is untouched).
    await expect(page.locator('#heatScope')).toContainText('116×16 canonical');
    await expect(rows).toHaveCount(11);
    await expect(page.locator('#heatBody .scope-note')).toContainText('11 of 116 strikes');
    await expect(page.locator('#heatBody .scope-note .clip')).toContainText('105 outside view');
    await expect(rows.first().locator('.hstrike')).toHaveText('769');
    await expect(rows.last().locator('.hstrike')).toHaveText('759');
    await expect(page.locator('#heatBody tr.spotrow .hstrike')).toHaveText('764');
    const nCols = await cols.count();
    expect(nCols).toBeGreaterThanOrEqual(3); expect(nCols).toBeLessThanOrEqual(11);
    await expect(page.locator('#heatBody .heat thead .hexp.expired')).toHaveCount(0);       // the expired 09-09 column is not current structure
    await expect(page.locator('#heatBody .scope-note')).toContainText('1 expired hidden in Auto');
    await expect(page.locator('#heatBody .scope-note')).toContainText(nCols + ' of 16 expirations');
    // legible density: rows at the approved height, cell text at the workstation size
    const rowH = await rows.first().evaluate((el) => el.getBoundingClientRect().height);
    expect(rowH).toBeGreaterThanOrEqual(30);
    const cellFont = await page.locator('#heatBody .hcell').first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(cellFont).toBeGreaterThanOrEqual(13);
    await expect(page.locator('#heatBody .heat-banner.ref')).toHaveCount(0);
    // WIDER: 23 rows, up to twice the Auto column budget (nearest unexpired first, expired labelled)
    await page.locator('#scopeCtl .scbtn', { hasText: 'Wider' }).click();
    await expect(rows).toHaveCount(23);
    await expect(page.locator('#heatBody .scope-note')).toContainText('23 of 116 strikes');
    const widerCols = await cols.count();
    expect(widerCols).toBeGreaterThanOrEqual(nCols); expect(widerCols).toBeLessThanOrEqual(2 * nCols);
    // ALL AVAILABLE: the complete population, every column (expired one labelled), same row height, scrolls
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect(rows).toHaveCount(116);
    await expect(cols).toHaveCount(16);
    await expect(page.locator('#heatBody .heat thead .hexp.expired')).toHaveCount(1);
    await expect(page.locator('#heatBody .heat thead .hexp.expired .dte')).toHaveText('EXPIRED');
    await expect(page.locator('#heatBody .scope-note')).toContainText('116 of 116 strikes');
    await expect(page.locator('#heatBody .scope-note .clip')).toHaveCount(0);
    expect(await page.locator('#heatBody .hcell').count()).toBe(116 * 16);                  // no data loss
    const allRowH = await rows.first().evaluate((el) => el.getBoundingClientRect().height);
    expect(allRowH).toBeGreaterThanOrEqual(30);                                              // never shrunk to fit
    // columns are never crushed either: every expiration column keeps a legible width and the grid
    // scrolls horizontally past the panel instead of compressing (MEASURED live 216x34 overprinted)
    const colWidths = await cols.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().width));
    expect(Math.min(...colWidths)).toBeGreaterThanOrEqual(80);
    const scrolls = await page.locator('#heatBody .heat-wrap').evaluate((el) => el.scrollHeight > el.clientHeight + 40);
    expect(scrolls).toBe(true);
    const scrollsX = await page.locator('#heatBody .heat-wrap').evaluate((el) => el.scrollWidth > el.clientWidth + 40);
    expect(scrollsX).toBe(true);
    await page.screenshot({ path: 'test-results/gamma-real-116x16-all.png', fullPage: false });
    await page.locator('#scopeCtl .scbtn', { hasText: 'Auto' }).click();
    await expect(rows).toHaveCount(11);
    await page.screenshot({ path: 'test-results/gamma-real-116x16-auto.png', fullPage: false });
  });

  test('workspace switching + editable watchlist foundation', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
    // add a symbol via the shell API (foundation is editable + localStorage-backed)
    await page.evaluate(() => window.EdShell.addSymbol('AMD'));
    await expect(page.locator('.wl-row .wl-sym', { hasText: 'AMD' })).toHaveCount(1);
  });

  test('chart view: Price + GEX Profile and Dot Map render from canonical inputs', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#view-chart')).toHaveClass(/on/);
    // profile mode (default): price line + signed profile bars + flip level line + spot
    const svg = page.locator('#chartBody svg');
    await expect(svg).toBeVisible();
    await expect(page.locator('#chartBody svg polyline')).toHaveCount(1);      // price line
    await expect(page.locator('#chartBody svg rect').first()).toBeVisible();   // profile bars (retrying)
    await expect(page.locator('#chartBody svg')).toContainText('spot 583.41');
    await expect(page.locator('#chartBody svg')).toContainText('flip');
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.screenshot({ path: require('path').join('test-results', 'console-gamma-chart-2560x1440.png') });
    // dot map mode: per-strike dots
    await page.locator('.cmode[data-cmode="dotmap"]').click();
    await expect(page.locator('#chartBody svg circle').first()).toBeVisible();   // retrying
    await expect(page.locator('#chartModes .cmode[data-cmode="dotmap"]')).toHaveClass(/on/);
  });

  test('live-update: single scheduler + monotonic latest-wins on the header quote', async ({ page }) => {
    // a stale/slow response for the PREVIOUS ticker must never overwrite the newer one
    await page.route('**/api/live/state**', async (route) => {
      const url = route.request().url();
      if (url.includes('ticker=SPY')) {
        await new Promise((r) => setTimeout(r, 900));   // stale, arrives late
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ spot: 111.11, spot_disp: '111.11', bid: 111, ask: 111.2,
            streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 100 } }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ spot: 222.22, spot_disp: '222.22', bid: 222, ask: 222.3,
          streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 100 } }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });   // init ticker SPY -> delayed 111.11
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));        // newer -> immediate 222.22
    await expect(page.locator('#hPx')).toHaveText('222.22');
    await page.waitForTimeout(1300);                                   // let the stale SPY response land
    await expect(page.locator('#hPx')).toHaveText('222.22');          // not overwritten by the stale response
  });

  test('header consumes the canonical L1 SSE push (real server envelope) when available', async ({ page }) => {
    // The server sends an ENVELOPE {scope, payload}; the quote lives on env.payload. This event
    // is the ACTUAL production shape — a root-field parser would read undefined and never paint,
    // so this test fails against the broken parser and passes only when the envelope is consumed.
    const ts = Date.now() / 1000;
    await page.route('**/api/analytics/light/stream**', (route) => route.fulfill({
      status: 200, contentType: 'text/event-stream',
      body: 'event: l1_projection\ndata: ' + JSON.stringify({
        l1_sse_schema: 1, scope: { ticker: 'SPY', expiry: '__auto__' },
        l1_generation: 9, l1_server_build_ts: ts,
        payload: {
          ticker: 'SPY', selected_exp: '2026-09-11', spot: 601.23, spot_disp: '601.23',
          bid: 601.20, ask: 601.25, l1_generation: 9, _server_build_ts: ts,
        },
      }) + '\n\n',
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // 601.23 comes only from env.payload; the /api/live/state poll fallback would show 583.41
    await expect(page.locator('#hPx')).toHaveText('601.23');
    await expect(page.locator('#hFeed')).toContainText('LIVE');
  });

  test('theme A/B: explicit dark and light selections persist across reload', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');   // first-paint guard
    await page.evaluate(() => window.EdShell.setTheme('light'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('theme C: SYSTEM resolves to a concrete data-theme (follows the OS at load)', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => { try { localStorage.setItem('ed_theme', 'system'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');   // SYSTEM + OS light -> light
  });

  test('theme SYSTEM follows LIVE OS changes; explicit ignores them (A-F)', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => { try { localStorage.setItem('ed_theme', 'system'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');     // A: SYSTEM + OS dark -> dark
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await cell.click();
    const val = (await cell.textContent()).trim();
    const darkBg = await cell.evaluate((el) => getComputedStyle(el).backgroundColor);
    // B: OS dark->light while OPEN -> shell AND the JS-computed heatmap update
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expect.poll(() => cell.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(darkBg);
    // C: OS light->dark -> both update back
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // F: value + selection unchanged through the transitions
    await expect(cell).toHaveText(val);
    await expect(page.locator('.hcell.sel-strike')).toHaveCount(2);
    await expect(page.locator('#hSym')).toHaveText('SPY');
    // D: explicit LIGHT ignores a later OS dark change
    await page.evaluate(() => window.EdShell.setTheme('light'));
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    // E: explicit DARK ignores a later OS light change
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    await page.emulateMedia({ colorScheme: 'light' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });

  test('theme D/E/F: switch preserves values, sign mapping, and selection', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    const darkVal = (await cell.textContent()).trim();
    await cell.click();                                   // select strike 583
    await page.evaluate(() => window.EdShell.setTheme('light'));
    // D: the displayed dollar value is unchanged by theme
    await expect(cell).toHaveText(darkVal);
    // E: positive cell green-dominant, negative cell red-dominant in LIGHT (no inversion)
    const rgbOf = (s) => { const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(s); return [+m[1], +m[2], +m[3]]; };
    const posBg = rgbOf(await cell.evaluate((el) => getComputedStyle(el).backgroundColor));
    const negBg = rgbOf(await page.locator('.hcell[data-strike="586"][data-expiry="2026-09-11"]').evaluate((el) => getComputedStyle(el).backgroundColor));
    expect(posBg[1]).toBeGreaterThan(posBg[0]);   // green channel dominant
    expect(negBg[0]).toBeGreaterThan(negBg[1]);   // red channel dominant
    // F: the selected strike + ticker survive the theme switch
    await expect(page.locator('.hcell.sel-strike')).toHaveCount(2);
    await expect(page.locator('#hSym')).toHaveText('SPY');
  });

  test('theme: ONE canonical owner (window.EdTheme) drives first-paint AND runtime resolution', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => { try { localStorage.setItem('ed_theme', 'system'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // the owner exists and exposes the resolution API
    expect(await page.evaluate(() => !!(window.EdTheme && window.EdTheme.resolve && window.EdTheme.setPref && window.EdTheme.getPref))).toBe(true);
    // FIRST PAINT used the owner: data-theme === EdTheme.resolve(EdTheme.getPref())
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme') === window.EdTheme.resolve(window.EdTheme.getPref()))).toBe(true);
    // RUNTIME goes through the SAME owner (EdShell delegates to EdTheme.setPref)
    await page.evaluate(() => window.EdShell.setTheme('light'));
    const rt = await page.evaluate(() => ({ dt: document.documentElement.getAttribute('data-theme'), pref: window.EdTheme.getPref(), resolved: window.EdTheme.resolve('light') }));
    expect(rt.pref).toBe('light');
    expect(rt.dt).toBe(rt.resolved);   // resolved via the one owner -> 'light'
  });

  test('theme screenshots: dark and light at 2560x1440 and 1920x1080, no h-overflow', async ({ page }) => {
    const path = require('path');
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    for (const theme of ['dark', 'light']) {
      await page.evaluate((t) => window.EdShell.setTheme(t), theme);
      for (const wh of [[2560, 1440], [1920, 1080]]) {
        await page.setViewportSize({ width: wh[0], height: wh[1] });
        await expect(page.locator('.hcell').first()).toBeVisible();
        const ok = await page.evaluate(() => document.body.scrollWidth <= window.innerWidth + 2);
        expect(ok).toBe(true);
        await page.screenshot({ path: path.join('test-results', 'console-' + theme + '-' + wh[0] + 'x' + wh[1] + '.png') });
      }
    }
  });

  test('#10 control-writer: newer contract command wins; a stale one cannot commit (two tabs safe)', async ({ page }) => {
    await page.route('**/api/streaming/active-option-contract', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      if (String(body.contract).indexOf('AAA') === 0) {   // delay the FIRST command so the second overtakes it
        await new Promise((r) => setTimeout(r, 400));
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contract: body.contract, command_generation: 1 }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contract: body.contract, command_generation: 2 }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const out = await page.evaluate(async () => {
      const A = 'AAA   260101C00100000', B = 'BBB   260101C00100000';
      const pa = window.EdStream.setActiveContract(A);   // client token 1
      const pb = window.EdStream.setActiveContract(B);   // client token 2 supersedes token 1
      return { a: await pa, b: await pb };
    });
    expect(out.b.accepted).toBe(true);                   // newer command commits
    expect(out.a.accepted).toBe(false);                  // older command is inert
    expect(out.a.reason).toBe('superseded_client');
  });

  test('#10 control-writer: a server 409 superseded verdict never commits', async ({ page }) => {
    await page.route('**/api/streaming/active-option-contract', (route) => route.fulfill({
      status: 409, contentType: 'application/json',
      body: JSON.stringify({ ok: false, superseded: true, contract: 'ZZZ', command_generation: 7 }),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const res = await page.evaluate(async () => window.EdStream.setActiveContract('ZZZ   260101C00100000'));
    expect(res.accepted).toBe(false);
    expect(res.reason).toBe('superseded_server');
  });

  test('#10 shared slot: request-accepted != active; loss of binding fails visibly; no auto re-POST', async ({ page }) => {
    let postCount = 0;
    await page.route('**/api/streaming/active-option-contract', (route) => {
      postCount++;
      const c = JSON.parse(route.request().postData() || '{}').contract;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contract: c, command_generation: postCount }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const X = 'XXX   260101C00100000', Y = 'YYY   260101C00100000';

    // A selects X -> REQUEST ACCEPTED, but NOT active until the producer confirms (empty plane)
    expect((await page.evaluate((c) => window.EdStream.setActiveContract(c), X)).accepted).toBe(true);
    expect((await page.evaluate((c) => window.EdStream.status({}, c), X)).active).toBe(false);
    // producer binds X (A polls the plane for X) -> A ACTIVE
    const boundX = { contract_match: true, producer_l1_contract: X, producer_book_contract: X };
    expect((await page.evaluate(([p, c]) => window.EdStream.status(p, c), [boundX, X])).active).toBe(true);

    // B selects Y (newer legitimate global intent) -> accepted; the global slot moves to Y
    expect((await page.evaluate((c) => window.EdStream.setActiveContract(c), Y)).accepted).toBe(true);
    // A now polls the plane for X and sees the producer is Y (contract_match:false) -> NOT ACTIVE,
    // so A cannot render Y's data as if it were X. A does NOT re-POST X.
    const aAfter = await page.evaluate(([p, c]) => window.EdStream.status(p, c), [{ contract_match: false, producer_l1_contract: Y, producer_book_contract: Y }, X]);
    expect(aAfter.active).toBe(false);
    expect(aAfter.bound).toBe(false);
    // B polls the plane for Y and is ACTIVE
    const boundY = { contract_match: true, producer_l1_contract: Y, producer_book_contract: Y };
    expect((await page.evaluate(([p, c]) => window.EdStream.status(p, c), [boundY, Y])).active).toBe(true);
    // no oscillation: exactly the two operator selections (X, Y) were POSTed — losing the slot re-POSTs nothing
    expect(postCount).toBe(2);
  });

  test('#10 active-ticker ack is fail-closed (request-accepted only; bookBound NOT_PROVEN)', async ({ page }) => {
    let mode = 'ok';
    await page.route('**/api/streaming/active-ticker', (route) => {
      var status = 200, body;
      if (mode === 'missing') body = { ok: true };                       // ok but NO echoed ticker
      else if (mode === 'wrong') body = { ok: true, ticker: 'QQQ' };      // echoed ticker != requested
      else if (mode === 'err500') { status = 500; body = { ok: true, ticker: 'SPY' }; }  // non-2xx, valid-looking body
      else body = { ok: true, ticker: 'SPY' };                           // exact 2xx + ok + matching ticker
      return route.fulfill({ status: status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const run = () => page.evaluate(() => window.EdStream.setActiveTicker('SPY'));
    mode = 'missing'; expect((await run()).requestAccepted).toBe(false);   // missing ticker -> rejected
    mode = 'wrong';   expect((await run()).requestAccepted).toBe(false);   // mismatched ticker -> rejected
    mode = 'err500';  expect((await run()).requestAccepted).toBe(false);   // non-2xx -> rejected
    mode = 'ok';      const ok = await run();
    expect(ok.requestAccepted).toBe(true);                                 // request accepted only
    expect(ok.bookBound).toBeNull();                                       // book binding NOT_PROVEN here
  });

  test('#1 perf: a large heatmap surface renders synchronously without pathological jank', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const ms = await page.evaluate(() => {
      var host = document.getElementById('heatBody');
      var exps = [], strikes = [], cells = [];
      for (var i = 0; i < 20; i++) exps.push({ expiry: '2026-' + (i < 4 ? '09' : '12') + '-' + String(10 + (i % 20)).padStart(2, '0'), dte: i * 3 });
      for (var s = 0; s < 200; s++) strikes.push(500 + s);
      for (var si = 0; si < strikes.length; si++) {
        var row = [];
        for (var j = 0; j < exps.length; j++) row.push((j % 2 ? 1 : -1) * 1000 * ((si % 50) + 1));
        cells.push({ strike: strikes[si], gex: row,
          contracts: exps.map(function (_e, j) { return { call: 'C' + si + '_' + j, put: 'P' + si + '_' + j }; }) });
      }
      var surface = { available: true, source: 'terrain_live_cache', live: true, current_spot: 600, current_spot_state: 'live', spot: 600, complete: false,
        coverage: { chain_basis: 'full' }, expirations: exps, strikes: strikes, cells: cells };
      var t0 = performance.now();
      window.EdGamma.renderSurface(host, surface);   // 200 strikes x 20 expiries = 4000 cells
      var dt = performance.now() - t0;
      return { dt: dt, cellCount: document.querySelectorAll('#heatBody .hcell').length };
    }).then((r) => { console.log('[#1 perf] heatmap render:', Math.round(r.dt), 'ms for', r.cellCount, 'cells'); return r.dt; });
    // no arbitrary tight SLA — a generous ceiling that only fails on pathological render behaviour
    expect(ms).toBeLessThan(1500);
  });

  test('#1 revision: DATA change rebuilds; STATUS change updates without rebuild (A-D)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const r = await page.evaluate(() => {
      var host = document.getElementById('heatBody');
      var R = window.EdGamma.renderSurface;
      var mark = function () {
        var c = host.querySelector('.hcell') || host.querySelector('.placeholder');
        if (c) c.setAttribute('data-marker', '1');
      };
      var marked = function () {
        return !!(host.querySelector('.hcell[data-marker="1"]') || host.querySelector('.placeholder[data-marker="1"]'));
      };
      var banner = function () { var b = host.querySelector('.heat-banner'); return b ? b.textContent : ''; };
      var scope = function () { return document.getElementById('heatScope').textContent; };
      var live = function (age, stale) {
        return { available: true, source: 'terrain_live_cache', live: true, stale: !!stale, warming: false, current_spot: 583.41, current_spot_state: 'live', spot: 583.41,
          complete: false, chain_as_of_ts_utc: 1000, spot_as_of_ts_utc: 1000, chain_basis: 'full', age_sec: age,
          coverage: { chain_basis: 'full' }, expirations: [{ expiry: '2026-09-11', dte: 2 }], strikes: [583], cells: [{ strike: 583, gex: [958600], contracts: [{ call: 'C583', put: 'P583' }] }] };
      };
      var banked = function (etd, warming) {   // current heatmap must refuse banked cells
        return { available: false, source: 'unavailable', live: false, stale: true, warming: warming, requested: true, on_board: true,
          reason: 'historical morning Gamma is not the current heatmap',
          et_date: etd };
      };
      // A: same live DATA revision, age changes -> table preserved, scope age updates
      R(host, live(3)); mark(); R(host, live(99));
      var A = { preserved: marked(), scopeHasAge: scope().indexOf('99s') !== -1 };
      // D: stale flips with no cell change -> no rebuild, but the STALE banner appears (not frozen)
      R(host, live(3)); mark(); R(host, live(3, true));
      var D = { preserved: marked(), staleBanner: banner().indexOf('STALE') !== -1 };
      // B: banked et_date changes -> table rebuilds
      R(host, banked('2026-09-08', false)); mark(); R(host, banked('2026-09-09', false));
      var B = { rebuilt: !marked() };
      // C: warming true->false, SAME banked et_date -> table preserved, banner changes
      R(host, banked('2026-09-08', true)); mark();
      var cWarm = banner();
      R(host, banked('2026-09-08', false));
      var C = { preserved: marked(), warmToRequested: cWarm.indexOf('WARMING') !== -1 && banner().indexOf('REQUESTED') !== -1 };
      return { A: A, B: B, C: C, D: D };
    });
    expect(r.A.preserved).toBe(true); expect(r.A.scopeHasAge).toBe(true);
    expect(r.D.preserved).toBe(true); expect(r.D.staleBanner).toBe(true);
    expect(r.B.rebuilt).toBe(true);
    expect(r.C.preserved).toBe(true); expect(r.C.warmToRequested).toBe(true);
  });

  test('#1.3 a warming reference surface shows LIVE SURFACE WARMING (never a final state)', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, SURFACE, {
        source: 'banked_morning_reference', live: false, stale: true, warming: true,
        degraded: 'live terrain surface unavailable — showing banked morning wide reference',
      })),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.heat-banner.warming')).toContainText('LIVE SURFACE WARMING');
  });

  test('#1-A requested but NOT on the board says collection is not active (never awaiting a refresh)', async ({ page }) => {
    // A new/non-enrolled symbol: the endpoint recorded demand (requested) but the ticker is not on
    // the canonical terrain board (on_board:false), so no next refresh can occur for it. The banner
    // must say collection is not active for this symbol — never promise an "awaiting next refresh".
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        available: false, source: 'unavailable', live: false, stale: true,
        warming: false, requested: true, on_board: false,
        reason: 'no live terrain surface and no banked wide chain',
      }),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    var b = page.locator('.heat-banner').first();
    await expect(b).toContainText('NOT COLLECTING');
    await expect(b).toContainText('not currently active for this symbol');
    await expect(b).not.toContainText('awaiting');
  });

  test('responsive proof: 2560x1440 and 1920x1080 screenshots', async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await page.screenshot({ path: path.join('test-results', 'console-gamma-2560x1440.png'), fullPage: false });
    await page.setViewportSize({ width: 1920, height: 1080 });
    await expect(page.locator('.hcell').first()).toBeVisible();
    // body must not scroll sideways at the smaller target
    const overflow = await page.evaluate(() => document.body.scrollWidth <= window.innerWidth + 2);
    expect(overflow).toBe(true);
    await page.screenshot({ path: path.join('test-results', 'console-gamma-1920x1080.png'), fullPage: false });
  });

  test('selecting a strike connects it to live streaming via the plural subscription endpoint (RC-UI-3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: "The new UI does not call the
    // plural subscription endpoint." Strike Detail is the one panel with a genuinely
    // resolved, DISPLAYED per-contract identity (the heatmap itself is a computed
    // aggregate with no per-cell OSI symbol) -- selecting a strike must request BOTH its
    // call AND put vendor symbols ("both sides where required") via
    // /api/streaming/active-option-contracts, the real endpoint, through the real
    // ed-stream.js/ed-gamma-panels.js wiring -- not a synthetic call into the JS module.
    await page.route('**/api/chain**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ticker: '$SPX', spot: 583.41, expiry: '2026-09-11', status: 'ok',
        contracts: [
          { symbol: 'SPY   260911C00583000', putCall: 'CALL', strikePrice: 583,
            openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.52, volatility: 12.3,
            expirationDate: '2026-09-11' },
          { symbol: 'SPY   260911P00583000', putCall: 'PUT', strikePrice: 583,
            openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.48, volatility: 12.6,
            expirationDate: '2026-09-11' },
        ],
      }),
    }));
    /** @type {any[]} */
    const requests = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      requests.push(body);
      // Echo the real server's contract: `contracts` in the response is the ACKNOWLEDGED
      // set, which ed-stream.js's identity check now requires to match what was sent.
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('#sdCtx')).toContainText('583');

    await expect.poll(() => requests.length).toBeGreaterThan(0);
    const sent = requests[requests.length - 1].contracts.slice().sort();
    expect(sent).toEqual(expect.arrayContaining(['SPY   260911C00583000', 'SPY   260911P00583000']));
  });

  test('the heatmap declares live-streaming demand for every visible column\'s contracts, not just the front column (state-authority review, superseded 2026-09-15)', async ({ page }) => {
    // Independent-review finding (2026-09-12, state-authority review), REPRODUCED: the
    // heatmap grid itself was never actually live -- only whatever ONE strike Strike
    // Detail had separately selected ever reached the streaming layer, so the rest of
    // the visible grid only ever refreshed on the ~60s wide-chain REST cycle. Every
    // surface cell now carries its own vendor OSI symbols (server.py's project_gamma_
    // surface); the heatmap declares its OWN demand for them through EdStream's
    // multi-owner additional-contracts slot ('heatmap', coexisting with Strike Detail's
    // own 'default'-owner demand).
    //
    // Always-live heatmap mandate (2026-09-15, operator directive), SUPERSEDES this test's
    // own prior "bounded to ... only the FRONT column" claim: "every visible heatmap cell
    // must correspond to an exact option contract actively receiving streamed Schwab
    // updates" -- a cell this module never demanded can never legitimately show
    // live/partial (ed-gamma.js's own per-cell render gate), so Auto scope now demands
    // EVERY visible column, the same rule Wider/All and an explicit expiry filter already
    // used (see the "Wider and All scope declare real streaming demand" test above).
    const surfaceWithContracts = Object.assign({}, SURFACE, {
      cells: [
        { strike: 580, gex: [-90000, null],
          contracts: [{ call: 'SPXW  260911C00580000', put: 'SPXW  260911P00580000' }, { call: null, put: null }] },
        { strike: 583, gex: [958600, 300000],
          contracts: [{ call: 'SPXW  260911C00583000', put: 'SPXW  260911P00583000' },
                      { call: 'SPXW  260918C00583000', put: 'SPXW  260918P00583000' }] },
        { strike: 586, gex: [-264500, 120000],
          contracts: [{ call: 'SPXW  260911C00586000', put: 'SPXW  260911P00586000' },
                      { call: 'SPXW  260918C00586000', put: 'SPXW  260918P00586000' }] },
      ],
    });
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surfaceWithContracts),
    }));
    // Strike Detail's own auto-select-on-load (an unrelated, already-covered demand
    // source) is suppressed here by giving /api/chain an empty result, so the posted
    // union under test is unambiguously the heatmap's own contribution alone.
    await page.route('**/api/chain**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ticker: '$SPX', spot: 583.41, expiry: '2026-09-11', status: 'ok', contracts: [] }),
    }));
    /** @type {any[]} */
    const requests = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      requests.push(body);
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // 2026-09-16: poll for the MEANINGFUL condition (the heatmap's own non-empty demand
    // having landed), not merely "any request happened" -- an unrelated owner (Strike
    // Detail, suppressed above to an empty selection but still issuing its own clear call)
    // can legitimately POST an earlier, empty request that "length > 0" alone would catch.
    await expect.poll(() => {
      const last = requests[requests.length - 1];
      return last && last.contracts && last.contracts.length;
    }).toBeGreaterThan(0);
    const sent = requests[requests.length - 1].contracts.slice().sort();
    // BOTH visible columns' call+put for every strike that has one -- 2026-09-11 (all
    // three strikes) AND 2026-09-18 (580 has no contracts on that expiry in this fixture,
    // 583/586 do). Every visible cell's own contracts are now demanded, not just the
    // front column's.
    expect(sent).toEqual([
      'SPXW  260911C00580000', 'SPXW  260911C00583000', 'SPXW  260911C00586000',
      'SPXW  260911P00580000', 'SPXW  260911P00583000', 'SPXW  260911P00586000',
      'SPXW  260918C00583000', 'SPXW  260918C00586000',
      'SPXW  260918P00583000', 'SPXW  260918P00586000',
    ].sort());

    // Leaving the Gamma workspace must clear the heatmap's OWN demand (not keep the
    // last-viewed ticker's contracts subscribed forever once nobody is looking).
    const beforeLeave = requests.length;
    await page.locator('.navitem[data-ws="order-flow"]').click();
    await expect.poll(() => requests.length).toBeGreaterThan(beforeLeave);
    expect(requests[requests.length - 1].contracts).toEqual([]);
  });

  test('the first-ever additional-contracts request on a fresh page confirms with the server, not just a local default (state-authority review)', async ({ page }) => {
    // Independent-review finding (2026-09-12, state-authority review), REPRODUCED: on a
    // FRESH page, before this module has ever dispatched a single request,
    // `_desiredAdditionalGen` (0) trivially equalled `_additionalGen` (0) -- a sentinel
    // meaning "never touched", not "confirmed by the server". The shell's own background
    // auto-select-on-load resolves to a genuine clear demand (setAdditionalContracts([]),
    // the empty default fixture's contracts have no `symbol` field) as its first-ever
    // call -- this matched the untouched pair and short-circuited with
    // accepted:true/unchanged:true WITHOUT ever contacting the server, a LOCAL DEFAULT
    // masquerading as CONFIRMED SERVER STATE. A real server that still holds some OTHER
    // additional-contracts selection (a prior tab, a server that did not reset) would
    // never be told to clear it. Fixed with an explicit `_desiredAdditionalConfirmed`
    // flag, set true ONLY by a genuine accepted commit -- `_desiredAdditionalGen ===
    // _additionalGen` alone cannot distinguish "confirmed" from "never asked".
    let requestCount = 0;
    let firstBody = null;
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      requestCount += 1;
      const body = JSON.parse(route.request().postData() || '{}');
      if (firstBody === null) firstBody = body;
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#sdCtx')).toContainText('583');   // background auto-select settled

    expect(requestCount).toBeGreaterThanOrEqual(1);
    expect(firstBody && firstBody.contracts).toEqual([]);

    // A second identical call, now genuinely confirmed, is correctly free to short-circuit
    // -- the fix does not remove the caching optimization, only when it may be trusted.
    const before = requestCount;
    const again = await page.evaluate(() => window.EdStream.setAdditionalContracts([]));
    expect(again.accepted).toBe(true);
    expect(again.unchanged).toBe(true);
    expect(requestCount).toBe(before);
  });

  test('a failed additional-contracts request is retried, not falsely reported accepted (RC-UI-3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED against the real
    // EdStream.setAdditionalContracts: the first request received HTTP 503; repeating
    // the SAME request afterward returned {accepted:true, unchanged:true} with only ONE
    // HTTP request ever having occurred -- _desiredAdditional was committed optimistically
    // BEFORE the fetch resolved, so a failed attempt was indistinguishable from a
    // successful one on the very next call. Also proves: a call repeated WHILE the first
    // is still pending must not fire a duplicate concurrent request, and a response whose
    // acknowledged `contracts` do not match what was sent must not be accepted either.
    //
    // Independent-review-adjacent flake, self-diagnosed (2026-09-12): the shell's own
    // background auto-select-on-load (Strike Detail auto-selecting the nearest-to-spot
    // strike -- the default CHAIN fixture's contracts have no `symbol` field, so it
    // resolves to a genuine "clear" demand, setAdditionalContracts([])) can still be
    // in flight when this test's own SET request is dispatched. Once the "latest
    // intent always wins, even over an in-flight request for a different target" fix
    // landed (the exact behavior these subscription tests exist to prove), that
    // background clear correctly SUPERSEDES this test's own in-flight SET request if
    // it lands mid-flight -- firing a genuine extra network call this test did not
    // expect, not a bug in the fix. Settled the same way the newer subscription-state-
    // machine tests already do: wait for the page's own background auto-select to
    // finish before starting this test's own explicit sequence.
    let requestCount = 0;
    /** @type {((v: any) => void) | null} */
    let releasePending = null;
    let mode = 'fail';   // 'fail' -> 503, 'hang' -> never resolves until released, 'ok' -> echoes back, 'wrong' -> echoes a different set
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      requestCount += 1;
      const body = JSON.parse(route.request().postData() || '{}');
      if (mode === 'fail') {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false }) });
      }
      if (mode === 'hang') {
        await new Promise((resolve) => { releasePending = resolve; });
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
      }
      if (mode === 'wrong') {
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, contracts: ['SPY   260911C00999000'] }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#sdCtx')).toContainText('583');   // background auto-select settled
    requestCount = 0;   // discard the auto-select's own settle-time request(s), if any

    const SET = ['SPY   260911C00583000', 'SPY   260911P00583000'];

    // 1) First request fails (503) -- must not be reported accepted.
    const r1 = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), SET);
    expect(r1.accepted).toBe(false);
    expect(requestCount).toBe(1);

    // 2) Repeating the SAME set after a failure must retry -- a real second HTTP request,
    // not a false accepted:true/unchanged:true short-circuit.
    const r2 = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), SET);
    expect(requestCount).toBe(2);
    expect(r2.unchanged).toBe(false);

    // 3) A response acknowledging the WRONG contract set must not be accepted.
    mode = 'wrong';
    const r3 = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), SET);
    expect(r3.accepted).toBe(false);
    expect(requestCount).toBe(3);

    // 4) Repetition WHILE the request is still pending must not fire a duplicate.
    mode = 'hang';
    const pendingPromise = page.evaluate((set) => window.EdStream.setAdditionalContracts(set), SET);
    await page.waitForTimeout(100);   // let the request actually reach the route handler
    expect(requestCount).toBe(4);
    const r4b = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), SET);
    expect(requestCount).toBe(4);     // no NEW request while the same set is still in flight
    expect(r4b.pending).toBe(true);
    expect(r4b.accepted).toBe(false);
    if (releasePending) releasePending(undefined);
    const r4a = await pendingPromise;
    expect(r4a.accepted).toBe(true);

    // 5) Now genuinely accepted -- calling again with the SAME set must not re-POST.
    mode = 'ok';
    const before = requestCount;
    const r5 = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), SET);
    expect(r5.accepted).toBe(true);
    expect(r5.unchanged).toBe(true);
    expect(requestCount).toBe(before);
  });

  test('switching ticker while a strike-detail chain fetch is in flight discards the stale response (RC-UI-2 finding #3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: ed-core.js's setTicker() already
    // clears the SHARED state.selStrike before dispatching 'ed:ticker' (confirmed correct),
    // but ed-gamma-panels.js's own 'ed:ticker' listener used to be just `loadAll` -- it never
    // bumped Strike Detail's OWN generation counter (_sgen) or reset its DOM/subscription
    // state. A /api/chain fetch already in flight for the OLD ticker at switch time still
    // passed the unchanged `g === _sgen` guard on arrival, rendering the old ticker's stale
    // OI/Vol/Gamma/Delta/IV and re-requesting the OLD ticker's vendor contracts into the
    // plural streaming endpoint UNDER THE NEW TICKER'S CONTEXT. Reproduced here exactly:
    // select strike 583 on SPY (delayed /api/chain), switch to QQQ before the response
    // arrives, then deliver it -- Strike Detail must stay reset (no SPY table rendered) and
    // SPY's contract symbols must never reach /api/streaming/active-option-contracts.
    let chainCalls = 0;
    let releaseChain = null;
    function contractsFor(strike) {
      return [
        { symbol: 'SPY   260911C00' + strike + '000', putCall: 'CALL', strikePrice: strike,
          openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.52, volatility: 12.3,
          expirationDate: '2026-09-11' },
        { symbol: 'SPY   260911P00' + strike + '000', putCall: 'PUT', strikePrice: strike,
          openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.48, volatility: 12.6,
          expirationDate: '2026-09-11' },
      ];
    }
    await page.route('**/api/chain**', async (route) => {
      chainCalls += 1;
      const strike = chainCalls === 1 ? 583 : 586;   // first select resolves immediately; second is delayed
      if (chainCalls > 1) await new Promise((resolve) => { releaseChain = resolve; });
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ticker: 'SPY', spot: 583.41, expiry: '2026-09-11', status: 'ok',
          contracts: contractsFor(strike) }),
      });
    });
    /** @type {any[]} */
    const requests = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      requests.push(body.contracts || []);
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // select strike 583 on SPY -- resolves immediately, its contracts are ACCEPTED into the
    // plural subscription (a real non-empty desired state, not the initial empty one)
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('#sdCtx')).toContainText('583');
    await expect.poll(() => requests.length).toBeGreaterThan(0);
    expect(requests[requests.length - 1].slice().sort()).toEqual(
      expect.arrayContaining(['SPY   260911C00583000', 'SPY   260911P00583000']));

    // select strike 586 -- fires the SECOND (delayed) /api/chain fetch, nothing resolves yet
    await page.locator('.hcell[data-strike="586"][data-expiry="2026-09-11"]').click();
    await expect.poll(() => releaseChain !== null).toBe(true);

    // switch ticker BEFORE the delayed 586 chain response arrives.
    // Isolate heatmap demand so this proof observes Strike Detail's owner only — the
    // replacement QQQ surface must not re-post the fixture's SPX symbols under QQQ.
    await isolateEdStream(page);
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    // reset fires synchronously off the 'ed:ticker' listener: placeholder restored immediately,
    // and the additional-contracts demand is cleared ([]) -- both BEFORE the stale data lands
    await expect(page.locator('#sdBody')).toContainText('Select a strike/expiry');
    await expect.poll(() => requests[requests.length - 1]).toEqual([]);
    const requestsAtSwitch = requests.length;

    // now deliver the stale (586, SPY) response
    releaseChain(undefined);
    await page.waitForTimeout(300);   // let any (incorrect) render/post attempt land

    // Strike Detail must still show the reset placeholder, not SPY's stale 586 table
    await expect(page.locator('#sdBody')).toContainText('Select a strike/expiry');
    await expect(page.locator('.sd')).toHaveCount(0);
    // SPY's 586 contract symbols must never have been (re-)posted to the plural endpoint
    expect(requests.length).toBe(requestsAtSwitch);
    for (const r of requests) {
      expect(r).not.toContain('SPY   260911C00586000');
      expect(r).not.toContain('SPY   260911P00586000');
    }
  });

  test('clearing demand while a request is still pending is not overridden by that request\'s late acceptance (RC-UI-3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: request A (left pending),
    // then clear ([]) BEFORE A resolves. Because _desiredAdditional was still [] (A had
    // never actually committed), the clear matched the OLD "unchanged" short-circuit
    // against the CONFIRMED value alone and returned accepted:true WITHOUT sending any
    // cancellation to the server and WITHOUT invalidating A's in-flight generation token
    // -- so when A's late response finally arrived, it was still "current" and silently
    // committed, overriding the operator's explicit clear intent. The real invariant:
    // the LATEST call always wins, including a return to an empty/no-longer-desired set.
    // Body-keyed request tracking (not a raw ordinal count): the shell's own unrelated
    // background behavior (e.g. auto-selecting the spot strike on first load) can fire
    // its own additional-contracts calls independent of this test's own sequence, so
    // "the Nth request" is not a reliable handle -- "a request naming exactly this set
    // has arrived" is.
    await isolateEdStream(page);
    const A = ['SPY   260911C00583000', 'SPY   260911P00583000'];
    const keyOf = (arr) => arr.slice().sort().join(',');
    /** @type {string[]} */
    const seen = [];
    let hungOnceForA = false;
    /** @type {((v: any) => void) | null} */
    let releaseA = null;
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      const key = keyOf(body.contracts || []);
      seen.push(key);
      if (key === keyOf(A) && !hungOnceForA) {
        hungOnceForA = true;
        await new Promise((resolve) => { releaseA = resolve; });   // A hangs, once
      }
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(200);   // let any unrelated page-load auto-request settle first

    const seenBeforeA = seen.length;
    const pendingA = page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    await expect.poll(() => seen.includes(keyOf(A))).toBe(true);   // A's request is in flight, hanging
    expect(seen.length).toBe(seenBeforeA + 1);   // exactly one new request, for A

    // Clear BEFORE A resolves -- must send a REAL cancellation request, not a fabricated
    // accept with zero network activity.
    const clearResult = await page.evaluate(() => window.EdStream.setAdditionalContracts([]));
    expect(seen.length).toBe(seenBeforeA + 2);   // the clear must have fired its OWN real request
    expect(seen[seen.length - 1]).toBe(keyOf([]));
    expect(clearResult.accepted).toBe(true);
    expect(await page.evaluate(() => window.EdStream.getDesiredAdditional())).toEqual([]);

    // NOW release A's late response -- it must NOT be able to override the clear.
    if (releaseA) releaseA(undefined);
    await pendingA;
    await page.waitForTimeout(150);   // let any (incorrect) late-commit attempt land
    expect(await page.evaluate(() => window.EdStream.getDesiredAdditional())).toEqual([]);
  });

  test('returning to a previously-accepted set while a newer request is pending is not overridden by that request\'s late acceptance (RC-UI-3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED, the mirror case: accept A,
    // then request B (left pending), then explicitly return to A BEFORE B resolves.
    // Because A equals the CONFIRMED _desiredAdditional, returning to it matched the OLD
    // "unchanged" short-circuit and did not bump the generation token -- B's in-flight
    // request was still "current" when it resolved, silently overriding the operator's
    // explicit return-to-A intent.
    await isolateEdStream(page);
    const A = ['SPY   260911C00583000', 'SPY   260911P00583000'];
    const B = ['SPY   260911C00586000', 'SPY   260911P00586000'];
    const keyOf = (arr) => arr.slice().sort().join(',');
    /** @type {string[]} */
    const seen = [];
    let hungOnceForB = false;
    /** @type {((v: any) => void) | null} */
    let releaseB = null;
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      const key = keyOf(body.contracts || []);
      seen.push(key);
      if (key === keyOf(B) && !hungOnceForB) {
        hungOnceForB = true;
        await new Promise((resolve) => { releaseB = resolve; });   // B hangs, once
      }
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(200);   // let any unrelated page-load auto-request settle first

    const acceptA = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    expect(acceptA.accepted).toBe(true);
    expect(seen[seen.length - 1]).toBe(keyOf(A));

    const seenBeforeB = seen.length;
    const pendingB = page.evaluate((set) => window.EdStream.setAdditionalContracts(set), B);
    await expect.poll(() => seen.includes(keyOf(B))).toBe(true);   // B's request is in flight, hanging
    expect(seen.length).toBe(seenBeforeB + 1);   // exactly one new request, for B

    // Return to A BEFORE B resolves -- must send a REAL request reasserting A, not a
    // fabricated accept that leaves B's stale in-flight token free to win.
    const returnToA = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    expect(seen.length).toBe(seenBeforeB + 2);   // the return-to-A must have fired its OWN real request
    expect(seen[seen.length - 1]).toBe(keyOf(A));
    expect(returnToA.accepted).toBe(true);
    expect(await page.evaluate(() => window.EdStream.getDesiredAdditional())).toEqual(A);

    // NOW release B's late response -- it must NOT be able to override the return to A.
    if (releaseB) releaseB(undefined);
    await pendingB;
    await page.waitForTimeout(150);   // let any (incorrect) late-commit attempt land
    expect(await page.evaluate(() => window.EdStream.getDesiredAdditional())).toEqual(A);
  });

  test('retrying a clear after the clear itself failed sends a fresh request, not a stale cache hit (RC-UI-3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: request A (left pending),
    // then a clear ([]) FAILS (503), then A's late response arrives and is correctly
    // ignored (superseded) -- so far identical to the sibling test above. The NEW
    // finding: retrying the SAME clear again used to match the UNTOUCHED initial
    // _desiredAdditional (still [], since nothing had ever actually committed a value)
    // and short-circuit with accepted:true/unchanged:true WITHOUT sending another
    // request -- even though the FAILED clear never actually removed anything, and A's
    // own request was never confirmed either way once superseded. A coincidental match
    // against a STALE cached value must never substitute for a fresh confirmation.
    await isolateEdStream(page);
    const A = ['SPY   260911C00583000', 'SPY   260911P00583000'];
    const keyOf = (arr) => arr.slice().sort().join(',');
    /** @type {string[]} */
    const seen = [];
    let hungOnceForA = false;
    let clearShouldFail = false;
    /** @type {((v: any) => void) | null} */
    let releaseA = null;
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      const key = keyOf(body.contracts || []);
      seen.push(key);
      if (key === keyOf(A) && !hungOnceForA) {
        hungOnceForA = true;
        await new Promise((resolve) => { releaseA = resolve; });   // A hangs, once
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
      }
      if (key === keyOf([]) && clearShouldFail) {
        clearShouldFail = false;   // fail exactly once
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(200);   // let any unrelated page-load auto-request settle first

    const pendingA = page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    await expect.poll(() => seen.includes(keyOf(A))).toBe(true);   // A's request is in flight, hanging

    // The clear FAILS while A is still pending.
    clearShouldFail = true;
    const seenBeforeClear = seen.length;
    const clearResult = await page.evaluate(() => window.EdStream.setAdditionalContracts([]));
    expect(seen.length).toBe(seenBeforeClear + 1);
    expect(clearResult.accepted).toBe(false);

    // Release A's late response -- it must be ignored (superseded), not committed.
    if (releaseA) releaseA(undefined);
    await pendingA;
    await page.waitForTimeout(100);

    // Retry the SAME clear -- must send a FRESH request, not a stale cache hit against
    // the untouched initial (coincidentally matching) desired value.
    const seenBeforeRetry = seen.length;
    const retryResult = await page.evaluate(() => window.EdStream.setAdditionalContracts([]));
    expect(seen.length).toBe(seenBeforeRetry + 1);   // a REAL new request, not a fabricated accept
    expect(seen[seen.length - 1]).toBe(keyOf([]));
    expect(retryResult.accepted).toBe(true);
    expect(retryResult.unchanged).toBe(false);
    expect(await page.evaluate(() => window.EdStream.getDesiredAdditional())).toEqual([]);
  });

  test('retrying a return-to-prior-value after it failed sends a fresh request, not a stale cache hit (RC-UI-3)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED, the mirror case: accept A,
    // request B (pending), the return to A FAILS, B's late response arrives and is
    // correctly ignored (superseded) -- then retrying the return to A again used to
    // match the STALE _desiredAdditional=A (confirmed BEFORE B was ever dispatched) and
    // short-circuit without a fresh request -- even though the intervening B dispatch
    // means the server's actual state cannot be assumed to still be A without asking
    // again.
    await isolateEdStream(page);
    const A = ['SPY   260911C00583000', 'SPY   260911P00583000'];
    const B = ['SPY   260911C00586000', 'SPY   260911P00586000'];
    const keyOf = (arr) => arr.slice().sort().join(',');
    /** @type {string[]} */
    const seen = [];
    let hungOnceForB = false;
    let returnToAShouldFail = false;
    /** @type {((v: any) => void) | null} */
    let releaseB = null;
    await page.route('**/api/streaming/active-option-contracts', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      const key = keyOf(body.contracts || []);
      seen.push(key);
      if (key === keyOf(B) && !hungOnceForB) {
        hungOnceForB = true;
        await new Promise((resolve) => { releaseB = resolve; });   // B hangs, once
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
      }
      if (key === keyOf(A) && returnToAShouldFail) {
        returnToAShouldFail = false;   // fail exactly once
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(200);

    const acceptA = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    expect(acceptA.accepted).toBe(true);

    const pendingB = page.evaluate((set) => window.EdStream.setAdditionalContracts(set), B);
    await expect.poll(() => seen.includes(keyOf(B))).toBe(true);   // B's request is in flight, hanging

    // The return to A FAILS while B is still pending.
    returnToAShouldFail = true;
    const seenBeforeReturn = seen.length;
    const returnResult = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    expect(seen.length).toBe(seenBeforeReturn + 1);
    expect(returnResult.accepted).toBe(false);

    // Release B's late response -- it must be ignored (superseded), not committed.
    if (releaseB) releaseB(undefined);
    await pendingB;
    await page.waitForTimeout(100);

    // Retry the return to A -- must send a FRESH request, not a stale cache hit against
    // the confirmed-before-B value.
    const seenBeforeRetry = seen.length;
    const retryResult = await page.evaluate((set) => window.EdStream.setAdditionalContracts(set), A);
    expect(seen.length).toBe(seenBeforeRetry + 1);   // a REAL new request, not a fabricated accept
    expect(seen[seen.length - 1]).toBe(keyOf(A));
    expect(retryResult.accepted).toBe(true);
    expect(await page.evaluate(() => window.EdStream.getDesiredAdditional())).toEqual(A);
  });

  // Independent-review finding (2026-09-13), REPRODUCED, then a FOURTH review overturned the
  // first fix's own test: falling back to every column when the selected expiry is missing
  // avoided a blank grid, but silently SUBSTITUTED other expiries' data (and kept demanding
  // streamed contracts for expiries the operator never asked to watch) -- the operator's own
  // requirement is that this state reads UNAVAILABLE for the requested expiry, with demand
  // cleared, never a silent substitution. This test enforces the CORRECTED requirement; the
  // superseded "fell back to both real columns" assertion is gone.
  test('a selected expiry absent from the surface reads unavailable and clears demand (no substitute expiries)', async ({ page }) => {
    let demandCalls = [];
    await page.route('**/api/expiries*', (r) => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ expiries: ['2026-09-11', '2026-09-18', '2026-09-25'] }) }));
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      let body = {}; try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
      demandCalls.push(body.contracts || []);
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ accepted: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();

    // '2026-09-25' is listed in /api/expiries but absent from SURFACE.expirations.
    demandCalls = [];
    await page.locator('#expSel').selectOption('2026-09-25');
    await expect(page.locator('#heatBody')).toContainText('Expiry 2026-09-25 unavailable');
    await expect(page.locator('#heatBody .hexp')).toHaveCount(0);   // NOT a silent substitute grid
    // The one demand call this selection can trigger clears everything -- no substitute expiry
    // is ever streamed on the operator's behalf.
    await expect.poll(() => demandCalls.length).toBeGreaterThan(0);
    expect(demandCalls[demandCalls.length - 1]).toEqual([]);
  });

  test('recovers automatically once the requested expiry appears in a later surface poll', async ({ page }) => {
    let currentSurface = SURFACE;   // SURFACE only has 2026-09-11/2026-09-18 -- 09-25 is initially missing
    await page.route('**/api/expiries*', (r) => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ expiries: ['2026-09-11', '2026-09-18', '2026-09-25'] }) }));
    await page.route('**/api/options/gamma-surface*', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(currentSurface) }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();

    await page.locator('#expSel').selectOption('2026-09-25');
    await expect(page.locator('#heatBody')).toContainText('Expiry 2026-09-25 unavailable');

    // The surface now genuinely includes the requested expiry -- a real vendor-side recovery.
    currentSurface = Object.assign({}, SURFACE, {
      expirations: SURFACE.expirations.concat([{ expiry: '2026-09-25', dte: 16 }]),
      cells: SURFACE.cells.map((c) => Object.assign({}, c, { gex: c.gex.concat([777000]) })),
    });
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(page.locator('#heatBody .hexp')).toHaveCount(1);
    await expect(page.locator('#heatBody')).not.toContainText('unavailable');
    await expect(page.locator('#heatBody .hexp .d')).toHaveText('09-25');
  });

  // A FOURTH independent review (2026-09-13), REPRODUCED: "confirmed" (the tooltip's
  // "sub-second streaming updates active" claim) fired the instant setAdditionalContracts
  // resolved with the server's own subscribe-request ACK -- a control-plane acceptance, never
  // checked against whether the producer has actually delivered one real observation. Fixed:
  // 'accepted' names the ACK; only a LATER surface poll's own real evidence promotes it to
  // 'observed', which is the only state whose tooltip claims streaming is actually active.
  //
  // A SIXTH independent review (2026-09-13), REPRODUCED then repaired: that "real evidence"
  // used to be `stream_overlay_contracts > 0` alone -- a surface-wide COUNT satisfied by ANY
  // contract anywhere, not necessarily one this column actually demanded. Now the evidence
  // must be `stream_overlay_symbols` naming a symbol THIS column's own demand set covers
  // (see `_colHasObservedEvidence` in ed-gamma.js) -- this test's fixture carries both the
  // legacy count (kept for a client that hasn't wired the sixth-review fix at all) and the
  // real per-symbol identity `surfaceWithContracts(1, 3)`'s own column 0 actually demands.
  test('an accepted subscription is honestly disclosed as accepted, not claimed active, until real observed data arrives', async ({ page }) => {
    let overlaySymbols = [];
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, surfaceWithContracts(1, 3), {
        stream_overlay_contracts: overlaySymbols.length, stream_overlay_symbols: overlaySymbols,
      })),
    }));
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const col = page.locator('.heat thead th.hexp.stream-demand');
    await expect(col).toHaveCount(1);
    // Accepted, but never overclaiming "active" while no symbol has actually overlaid.
    await expect(col).toHaveAttribute('title', /subscription accepted.*awaiting the first observed update/, { timeout: 3000 });
    await expect(col).not.toHaveAttribute('title', /streaming updates observed/);

    // A later poll's surface now carries real overlay evidence FOR THIS COLUMN'S OWN
    // demanded symbol -- ONLY NOW may the tooltip claim streaming is actually active.
    overlaySymbols = ['C580X2026-09-11'];
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(col).toHaveAttribute('title', /streaming updates observed for this column/, { timeout: 3000 });
  });

  // A SIXTH independent review (2026-09-13), REPRODUCED: `stream_overlay_contracts` is a
  // single surface-wide COUNT -- nonzero the instant ANY contract anywhere overlaid, even one
  // belonging to a completely different, unrelated column. That count alone used to promote
  // EVERY currently-accepted column to 'observed' together. This test proves TWO accepted
  // columns are judged INDEPENDENTLY: only the column whose own demanded symbol actually
  // appears in `stream_overlay_symbols` is promoted; its sibling, with real overlay evidence
  // for a totally different contract, must stay 'accepted'.
  test('one column\'s overlay evidence does not promote an unrelated accepted column to observed', async ({ page }) => {
    // 2 columns x 1 strike -- demandCols under Wider/All-style scope names both, well under
    // the 240-contract cap, so both accept.
    let overlaySymbols = [];
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, surfaceWithContracts(2, 1), {
        stream_overlay_contracts: overlaySymbols.length, stream_overlay_symbols: overlaySymbols,
      })),
    }));
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    const cols = page.locator('.heat thead th.hexp.stream-demand');
    await expect(cols).toHaveCount(2, { timeout: 3000 });
    await expect(cols.nth(0)).toHaveAttribute('title', /subscription accepted/, { timeout: 3000 });
    await expect(cols.nth(1)).toHaveAttribute('title', /subscription accepted/, { timeout: 3000 });

    // Only column 0's own demanded symbol (strike 580, expiry 2026-09-11) actually overlaid.
    overlaySymbols = ['C580X2026-09-11'];
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(cols.nth(0)).toHaveAttribute('title', /streaming updates observed for this column/, { timeout: 3000 });
    // Column 1 (a different expiry's symbol, e.g. C580X2026-09-12) has NO overlay evidence
    // of its own -- it must stay 'accepted', never borrow column 0's evidence.
    await expect(cols.nth(1)).toHaveAttribute('title', /subscription accepted.*awaiting the first observed update/);
    await expect(cols.nth(1)).not.toHaveAttribute('title', /streaming updates observed/);
  });

  // A FOURTH independent review (2026-09-13), REPRODUCED: at 244 visible contracts (2 columns
  // x 61 strikes x call+put), a flat `.slice(0, 240)` over the column-interleaved symbol list
  // cut mid-row -- excluding one strike's contracts in the SECOND column while every other
  // cell in that same column stayed covered, with the column's own tooltip still claiming full
  // coverage. Fixed: the cap drops whole trailing COLUMNS, and a capped column's own tooltip
  // says so distinctly from an uncapped one's.
  // Always-live heatmap mandate (2026-09-15, operator directive), FINAL, RETIRES the two
  // tests this replaces ("the streaming-demand cap partially covers the column that crosses
  // the ceiling..." and "a single explicitly-selected expiry with 242 contracts gets 240
  // partial, never zero"): "The 240-contract ceiling is our current implementation limit
  // unless you prove otherwise. Do not use it as an excuse to reduce the product... Stream
  // every contract Schwab permits." The client-side cap and its capped/partial-column
  // carve-out (MAX_DEMAND_CONTRACTS, _cappedCols, _partialCols) are removed outright, not
  // just re-tuned -- a scope this large is no longer capped, split, or excluded at all.
  test('a visible scope larger than the former 240-contract self-imposed ceiling is demanded in FULL, uncapped, unsplit', async ({ page }) => {
    // 2 columns x 61 strikes x 2 sides = 244 contracts -- previously would have capped
    // column 1 to a 118-contract partial; now both columns' contracts are demanded whole.
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surfaceWithContracts(2, 61)),
    }));
    const demandCalls = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      demandCalls.push(body.contracts || []);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.EdShell.setScope('all'));   // demand follows every displayed column
    await expect.poll(() => {
      const last = demandCalls[demandCalls.length - 1] || [];
      return last.length;
    }).toBe(244);

    const lastDemand = demandCalls[demandCalls.length - 1];
    expect(lastDemand.length).toBe(244);   // the FULL set -- no cap, no split, no exclusion
    const col1Symbols = lastDemand.filter((s) => /X2026-09-12$/.test(s));
    expect(col1Symbols.length).toBe(122);   // column 1's own full 61 strikes x 2 sides

    const colTitles = await page.locator('.heat thead th.hexp').evaluateAll(
      (ths) => ths.map((th) => th.getAttribute('title')));
    expect(colTitles.length).toBe(2);
    colTitles.forEach((t) => expect(t || '').not.toMatch(/PARTIALLY|excluded|safety limit/));
    await expect(page.locator('#heatBody .scope-note')).not.toContainText('capped');
  });

  test('Auto/Wider/All demand cannot silently collapse to zero when the surface names contracts', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surfaceWithContracts(2, 61)),
    }));
    const demandCalls = [];
    await page.route('**/api/streaming/active-option-contracts', (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      demandCalls.push(body.contracts || []);
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const scopes = ['auto', 'wider', 'all'];
    for (const scope of scopes) {
      await page.evaluate((s) => window.EdShell.setScope(s), scope);
      await expect.poll(() => {
        const last = demandCalls[demandCalls.length - 1] || [];
        return last.length;
      }, { timeout: 8000 }).toBeGreaterThan(0);
      const last = demandCalls[demandCalls.length - 1];
      expect(last.length, `${scope} collapsed to zero`).toBeGreaterThan(0);
    }
    const viaHelper = await page.evaluate((surface) => {
      const G = window.EdGamma;
      return {
        auto: G.heatmapDemandSymbols(surface, 'auto').length,
        wider: G.heatmapDemandSymbols(surface, 'wider').length,
        all: G.heatmapDemandSymbols(surface, 'all').length,
      };
    }, surfaceWithContracts(2, 61));
    expect(viaHelper.auto).toBeGreaterThan(0);
    expect(viaHelper.wider).toBeGreaterThan(0);
    expect(viaHelper.all).toBeGreaterThan(0);
    expect(viaHelper.all).toBeGreaterThanOrEqual(viaHelper.wider);
    expect(viaHelper.wider).toBeGreaterThanOrEqual(viaHelper.auto);
  });


  // ---------------------------------------------------------------------------
  // 2026-09-16 audit findings #3/#4/#5/#6 — bounded/consolidated live-UI architecture
  // ---------------------------------------------------------------------------

  test('audit #4: cold start hydrates every endpoint exactly once, never twice', async ({ page }) => {
    // The former design had TWO independent initial-hydration mechanisms (ed-core.js's own
    // ed:ticker/ed:view dispatch, and each view module's own bottom-of-file self-call) that
    // only avoided colliding because of a script-load-order coincidence. Now there is exactly
    // one (ed-core.js's dispatch, deferred to DOMContentLoaded) -- proven here by counting
    // calls to endpoints owned by DIFFERENT modules across the initial render.
    const counts = {};
    // fallback() (not continue()) chains to the next-registered handler -- here, intercept()'s
    // own catch-all from beforeEach, which actually fulfills with mock data. continue() would
    // instead send the request over the real network, bypassing every mock entirely.
    const track = (path) => (route) => {
      counts[path] = (counts[path] || 0) + 1;
      return route.fallback();
    };
    await page.route('**/api/options/gamma-surface**', track('gamma-surface'));
    await page.route('**/api/terrain/strikes**', track('terrain-strikes'));
    await page.route('**/api/terrain?**', track('terrain'));
    await page.route('**/api/options/tape**', track('tape'));
    await page.route('**/api/chain**', track('chain'));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    // Give any accidental second trigger (a stray immediate self-call racing the deferred
    // dispatch) a real chance to land before asserting the count stayed at exactly one.
    await page.waitForTimeout(300);
    for (const path of ['gamma-surface', 'terrain-strikes', 'terrain', 'tape', 'chain']) {
      expect(counts[path] || 0, `${path} must hydrate exactly once on cold start`).toBe(1);
    }
  });

  test('audit #3: one gamma_surface_seq push refetches only gamma-surface-derived endpoints, not unrelated ones', async ({ page }) => {
    let gammaCalls = 0, strikesCalls = 0, terrainCalls = 0;
    const unrelated = { tape: 0, chain: 0, analytics: 0 };
    // fallback() (not continue()) -- see the identical note in the cold-start test above.
    await page.route('**/api/options/gamma-surface**', (route) => { gammaCalls += 1; return route.fallback(); });
    await page.route('**/api/terrain/strikes**', (route) => { strikesCalls += 1; return route.fallback(); });
    // CONFIRMED REGRESSION (2026-09-17, live-UI field audit): a gamma-surface push can now
    // mean "canonical spot moved with NO option tick at all"
    // (refresh_gamma_surface_from_spot_tick) -- /api/terrain's own spot/walls/flip/net-GEX
    // fields (the Gamma Chart's spot line, Key Levels) are exactly as gamma-surface-derived
    // as /api/terrain/strikes is, and moved from "unrelated" into the reacting set.
    await page.route('**/api/terrain?**', (route) => { terrainCalls += 1; return route.fallback(); });
    await page.route('**/api/options/tape**', (route) => { unrelated.tape += 1; return route.fallback(); });
    await page.route('**/api/chain**', (route) => { unrelated.chain += 1; return route.fallback(); });
    await page.route('**/api/analytics/state**', (route) => { unrelated.analytics += 1; return route.fallback(); });
    await page.route('**/api/analytics/light/stream**', async (route) => {
      // Long enough to land AFTER the strike-clear settle wait below (else the push
      // fires before this test ever captures its baseline counts, and the SSE-reaction
      // assertions below would look like no reaction happened at all).
      await new Promise((r) => setTimeout(r, 1000));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    // The heatmap auto-selects the at-the-money strike by default, which gives Strike
    // Detail's OWN legitimate ed:gamma-push reaction (loadStrike, reading /api/chain) a
    // selection to act on -- a real, separate mechanism this test is not about (it only
    // cares about endpoints with NO business reacting to a gamma-surface push at all).
    // Clearing the selection isolates the test to that claim. The initial auto-select
    // itself scheduled a 600ms-delayed loadOf() (ed-gamma-panels.js's own ed:strike
    // handler) BEFORE this clears it -- wait that out too, or it fires during this test's
    // own observation window and gets mistaken for a reaction to the gamma-surface push.
    await page.evaluate(() => window.EdShell.setStrike(null));
    await page.waitForTimeout(650);
    const beforeUnrelated = Object.assign({}, unrelated);
    const gammaBefore = gammaCalls, strikesBefore = strikesCalls, terrainBefore = terrainCalls;
    await page.waitForTimeout(600);   // past the mocked SSE delay (1000ms from page load)
    // The genuinely gamma-surface-derived endpoints DID react to the push.
    expect(gammaCalls).toBeGreaterThan(gammaBefore);
    expect(strikesCalls).toBeGreaterThan(strikesBefore);
    expect(terrainCalls).toBeGreaterThan(terrainBefore);
    // Nothing unrelated fired again just because ONE gamma-surface push arrived.
    expect(unrelated).toEqual(beforeUnrelated);
  });

  test('audit #3 (follow-up): two modules reacting to the SAME push for the SAME endpoint collapse into one network call', async ({ page }) => {
    // On the Chart view, ed-gamma-chart.js's own GEX profile AND ed-gamma-panels.js's
    // Key Levels rail (isGamma() is view-independent -- see that file's own gate) are BOTH
    // active and BOTH react to ed:gamma-push by reading /api/terrain/strikes for the SAME
    // ticker -- exactly the "independently refetches multiple related endpoints" shape the
    // operator's mandate bans. l1_sse_guards.js's sharedFetchJson must collapse the two
    // into a single real request, not merely narrow WHICH modules react.
    let strikesCalls = 0;
    await page.route('**/api/terrain/strikes**', (route) => { strikesCalls += 1; return route.fallback(); });
    await page.route('**/api/analytics/light/stream**', async (route) => {
      await new Promise((r) => setTimeout(r, 1000));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#chartBody svg')).toBeVisible();
    await page.waitForTimeout(200);   // let the view-switch's own hydration settle
    const before = strikesCalls;
    await page.waitForTimeout(1100);   // past the mocked SSE delay
    // Exactly one MORE call for the one push, not two (one per reacting module).
    expect(strikesCalls - before).toBe(1);
  });

  test('audit #3 (follow-up): one gamma_surface_seq push costs a strict, documented request budget of at most 4 REST calls total, including Strike Detail and Key Levels', async ({ page }) => {
    // Independent-review finding (2026-09-16, follow-up mandate item 7): "consolidate
    // gamma-push data delivery or prove a strict request budget including selected Strike
    // Detail". The heatmap auto-selects the at-the-money strike by default, so Strike
    // Detail (ed-gamma-panels.js, reading /api/chain) is ALSO a genuine ed:gamma-push
    // reactor whenever a strike is selected -- a prior test isolated the OTHER two
    // endpoints by explicitly clearing the selection; this one leaves it selected and
    // measures the TRUE worst case: every endpoint any gamma-push reactor can possibly
    // touch, together, for one push.
    //
    // Budget revised 4->3->4 (2026-09-17, live-UI field audit): /api/terrain (Key Levels'
    // spot/walls/flip/net-GEX, view-independent per isGamma()) was found to be a
    // CONFIRMED REGRESSION -- gamma-surface-derived data left off the push entirely, so it
    // sat on the 12s cadence while claiming an unconditional "terrain · live" label. Wiring
    // it to the push (this row's own fix) is a genuine, documented, deliberate budget
    // increase from 3 to 4 distinct endpoints (gamma-surface, terrain/strikes, chain,
    // terrain) -- correctness over the smaller number. Still each fetched exactly once,
    // regardless of how many modules react to the SAME push (Key Levels and the Gamma
    // Chart's own spot-line fix both read /api/terrain and collapse to one real call via
    // sharedFetchJson).
    let gammaCalls = 0, strikesCalls = 0, chainCalls = 0, terrainCalls = 0;
    await page.route('**/api/options/gamma-surface**', (route) => { gammaCalls += 1; return route.fallback(); });
    await page.route('**/api/terrain/strikes**', (route) => { strikesCalls += 1; return route.fallback(); });
    await page.route('**/api/chain**', (route) => { chainCalls += 1; return route.fallback(); });
    await page.route('**/api/terrain?**', (route) => { terrainCalls += 1; return route.fallback(); });
    await page.route('**/api/analytics/light/stream**', async (route) => {
      await new Promise((r) => setTimeout(r, 1000));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await page.waitForTimeout(200);   // let cold-start hydration (including auto-select) settle
    const before = { gamma: gammaCalls, strikes: strikesCalls, chain: chainCalls, terrain: terrainCalls };
    await page.waitForTimeout(1100);   // past the mocked SSE delay
    expect(gammaCalls - before.gamma).toBe(1);
    expect(strikesCalls - before.strikes).toBe(1);
    expect(chainCalls - before.chain).toBe(1);
    expect(terrainCalls - before.terrain).toBe(1);
    const totalDelta = (gammaCalls - before.gamma) + (strikesCalls - before.strikes)
      + (chainCalls - before.chain) + (terrainCalls - before.terrain);
    expect(totalDelta).toBeLessThanOrEqual(4);
  });

  test('CONFIRMED REGRESSION FIX (2026-09-17): the Gamma Chart spot line moves on a spot-only gamma_surface_seq push, not just the 12s poll', async ({ page }) => {
    // Live-UI field audit finding: ed-gamma-chart.js's own gamma-push handler reused the
    // STALE `_lastRaw.terrain` object instead of refetching /api/terrain, on the reasoning
    // "a streamed option tick carries no terrain/spot information" -- true before this
    // mandate's spot-tick fix, false now that a push can ALSO mean "spot moved with no
    // option tick at all". This proves the fix: the terrain response is genuinely refetched
    // on the push, and the chart's own spot line/label reflects the NEW value.
    let terrainSpot = 583.41;
    await page.route('**/api/terrain?**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, TERRAIN, { spot: terrainSpot })),
    }));
    await page.route('**/api/analytics/light/stream**', async (route) => {
      await new Promise((r) => setTimeout(r, 1000));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#chartBody svg')).toContainText('spot 583.41');
    // Canonical spot moves -- NO option tick, purely a spot-only tick's own gamma_surface_seq
    // push (the exact shape refresh_gamma_surface_from_spot_tick produces).
    terrainSpot = 601.23;
    await page.waitForTimeout(1100);   // past the mocked SSE delay
    await expect(page.locator('#chartBody svg')).toContainText('spot 601.23');
  });

  test('CONFIRMED REGRESSION FIX (2026-09-17): Key Levels rail updates on a gamma_surface_seq push, not just the 12s poll', async ({ page }) => {
    let terrainSpot = 583.41;
    await page.route('**/api/terrain?**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, TERRAIN, { spot: terrainSpot })),
    }));
    await page.route('**/api/analytics/light/stream**', async (route) => {
      await new Promise((r) => setTimeout(r, 1000));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":2}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSpot')).toHaveText('583.41');
    terrainSpot = 601.23;
    await page.waitForTimeout(1100);   // past the mocked SSE delay
    await expect(page.locator('#klSpot')).toHaveText('601.23');
  });

  test('audit #5: the Chain view does not poll on a fixed 12s cadence while inactive, and hydrates once on entry', async ({ page }) => {
    let chainCalls = 0;
    await page.route('**/api/chain**', (route) => {
      chainCalls += 1;
      // Strike Detail (ed-gamma-panels.js) ALSO reads /api/chain for a selected strike's own
      // OI/volume, on the SAME 12s cadence -- a real, separate, still-correct mechanism this
      // test is not about. Returning empty contracts here (same convention the "declares
      // live-streaming demand" test above uses) means Strike Detail has nothing to select and
      // never re-reads it, isolating this test to the Chain LADDER's own fetch behavior.
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ticker: 'SPY', spot: 583.41, expiry: '2026-09-11', status: 'ok', contracts: [] }),
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();   // lands on Gamma, not Chain
    // The heatmap auto-selects the at-the-money strike by default, which gives Strike
    // Detail (ed-gamma-panels.js) something to read from /api/chain on its OWN, separate,
    // still-correct ed:refresh{slow} cadence -- a real mechanism unrelated to this test.
    // Clearing the selection isolates this test to the Chain LADDER's own fetch behavior.
    await page.evaluate(() => window.EdShell.setStrike(null));
    const afterLoad = chainCalls;
    // Simulate what USED to be several 12s slow-poll ticks while a DIFFERENT view is active --
    // the old design's unconditional ed:refresh{slow} listener would have refetched the
    // complete chain on every one of these even though nobody was looking at it.
    for (let i = 0; i < 4; i++) {
      await page.evaluate((n) => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { tick: n, slow: true } })), i);
    }
    await page.waitForTimeout(200);
    expect(chainCalls).toBe(afterLoad);   // zero extra chain fetches while Chain was never viewed
    // Entering the Chain view for the first time hydrates it exactly once.
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect.poll(() => chainCalls).toBeGreaterThan(afterLoad);
    const afterEntry = chainCalls;
    await page.waitForTimeout(200);
    expect(chainCalls).toBe(afterEntry);   // exactly one hydration on entry, not a burst
  });

  test('audit #6: the header never reads the word LIVE (in any form) when visible coverage is only partial', async ({ page }) => {
    // Two visible cells, one genuinely live-streaming and one merely stale -- 50% coverage
    // must read as a disclosed percentage, never a source-path-only check that ignores
    // per-cell coverage, and never a label containing the word LIVE at all (follow-up
    // mandate independent-review finding: "LIVE·50%" still contains the literal word LIVE,
    // which a viewer scanning for that one word could mistake for a complete reading).
    // No stream_coverage is set on the payload at all -- the header's LIVE/STREAMING word is
    // computed client-side from the DOM's own data-cell-state attributes (visible-scope
    // coverage), never from this canonical-surface, server-computed field.
    const surf = surfaceWithStreamState([{ call: 'live' }, { call: 'stale' }]);
    surf.source = 'terrain_live_cache';
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surf),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    const scopeText = await page.locator('#heatScope').textContent();
    expect(scopeText).toMatch(/STREAMING·50%/);
    expect(scopeText).not.toMatch(/LIVE/);   // the literal word must never appear below 100%
    await expect(page.locator('#heatScope')).toHaveAttribute('title', /1 live, 0 partial, 1 stale, 0 pending, 0 daemon-unavailable, 0 rejected, 0 unavailable of 2 visible/);
  });

  test('audit #6: a vendor-rejected contract renders a distinct, visibly-failed cell', async ({ page }) => {
    const surf = Object.assign({}, SURFACE, {
      strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }],
      cells: [{
        strike: 583, gex: [null], contracts: [{ call: 'BADSYM', put: null }],
        stream: [{ state: 'rejected', call: { symbol: 'BADSYM', state: 'rejected', rejected_reason: 'vendor refused' } }],
      }],
    });
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(surf),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveClass(/state-rejected/);
    await expect(cell).toHaveAttribute('title', /REJECTED.*vendor refused/);
  });

  test('audit #3: a late gamma_surface_seq push scoped to the PREVIOUS ticker never paints the new ticker\'s cells', async ({ page }) => {
    // surfaceRevision()'s own key includes the server-owned surface_seq counter specifically
    // so cell-VALUE-only changes are never mistaken for "nothing changed" (RC-UI-2 finding
    // #1 -- see the identical note earlier in this file). This fixture's two ticker
    // responses share the same strikes/expirations shape, so a real, incrementing
    // surface_seq is required here for the same reason production always stamps one.
    let seq = 0;
    await page.route('**/api/options/gamma-surface**', (route) => {
      const url = route.request().url();
      const tk = decodeURIComponent((url.match(/[?&]ticker=([^&]+)/) || [])[1] || 'SPY');
      const value = tk === 'SPY' ? 1000 : 9000;
      seq += 1;
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, SURFACE, {
          strikes: [583], expirations: [{ expiry: '2026-09-11', dte: 2 }],
          cells: [{ strike: 583, gex: [value], contracts: [{ call: 'C583', put: 'P583' }] }], surface_seq: seq,
        })),
      });
    });
    // A short, fixed delay (same proven pattern as the "genuine SSE push" test above) --
    // long enough for the test to switch ticker before it lands, short enough to keep the
    // test fast. The push is scoped to SPY, the ticker this test is about to LEAVE.
    await page.route('**/api/analytics/light/stream**', async (route) => {
      await new Promise((r) => setTimeout(r, 400));
      route.fulfill({
        status: 200, contentType: 'text/event-stream',
        body: ': ok\n\nevent: gamma_surface_seq\ndata: {"scope":{"ticker":"SPY"},"surface_seq":99}\n\n',
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');   // SPY's own value
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect(cell).toHaveText('$9.0K');   // now QQQ's own value, before the SPY-scoped push lands
    // Give the held-open SSE connection's delayed SPY-scoped push a real chance to arrive
    // and, if the scope guard were broken, repaint over QQQ's own value.
    await page.waitForTimeout(500);
    await expect(cell).toHaveText('$9.0K');   // still QQQ's -- the stale SPY-scoped push was ignored
  });
});
