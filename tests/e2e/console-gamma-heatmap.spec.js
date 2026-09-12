// @ts-check
/**
 * RC-UI-1 — browser DOM proof for the rebuilt Ed Console shell + Options/Gamma heatmap.
 *
 * Proves the FRONTEND presentation contract in a real browser: the heatmap renders the
 * canonical /api/options/gamma-surface payload VERBATIM (cell text == formatted backend value,
 * invariant E), sign -> colour with no inversion (invariant D), spot row highlight, and the Key
 * Levels rail reflects /api/terrain. The endpoint==faucet equality is proven separately in
 * tests/test_gamma_surface_projection_v1.py; together they cover end-to-end.
 *
 * Endpoints are intercepted with synthetic payloads so the proof is deterministic and offline —
 * it exercises the real shell HTML/JS, not stubbed rendering.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SURFACE = {
  ticker: '$SPX', symbol: '$SPX', available: true, spot: 583.41,
  source: 'terrain_live_cache', live: true, stale: false, age_sec: 3, chain_basis: 'full',
  complete: false,
  coverage: { window: 'live_near_money', chain_basis: 'full', strike_count: 3,
    note: 'near-money LIVE window (strike_count-bounded terrain chain) — NOT the full strike_range=ALL book' },
  chain_as_of_ts_utc: 1757000200, spot_as_of_ts_utc: 1757000200, spot_source: 'last',
  expirations: [{ expiry: '2026-09-11', dte: 2 }, { expiry: '2026-09-18', dte: 9 }],
  strikes: [580, 583, 586],
  cells: [
    { strike: 580, gex: [-90000, null] },
    { strike: 583, gex: [958600, 300000] },
    { strike: 586, gex: [-264500, 120000] },
  ],
  provenance: { producer: 'math_exposure_core.compute_exposures_by_strike', classification: 'DERIVED' },
};
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
          cells: [{ strike: 583, gex: [value] }],
          surface_seq: call,
          // chain_as_of_ts_utc / spot_as_of_ts_utc / chain_basis / et_date are DELIBERATELY
          // identical to SURFACE's own (unmodified) values on both fetches -- exactly what an
          // eager streaming refresh does: change a cell, touch no REST-cycle field.
        })),
      });
    });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');

    // The real slow-refresh trigger (ed-core.js's liveTick, every 4th 3s tick) dispatches this
    // exact event; firing it directly here exercises the REAL ed-gamma.js listener without
    // waiting out the real ~12s cadence.
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(cell).toHaveText('$2.0K');
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
          cells: [{ strike: 583, gex: [value] }],
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const cell = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    await expect(cell).toHaveText('$1.0K');
    // No document.dispatchEvent call anywhere above or below -- only the intercepted SSE
    // connection's own (real, browser-parsed) event, arriving ~500ms after initial render,
    // can cause this -- and it must land well before the ~12s slow-poll cadence would have.
    await expect(cell).toHaveText('$2.0K', { timeout: 3000 });
    expect(surfaceCalls).toBeGreaterThanOrEqual(2);
  });

  test('GEX-by-strike displays each row\'s own session volume, not just signed GEX$ (RC-UI-2 finding #5a)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: "GEX-by-strike does not display its
    // row's volume field" -- terrain_engine._per_strike_rows' own shape is
    // [strike, net_gex_1pct$, session_volume]; the THIRD element was read into _lastGbs but
    // never rendered anywhere. STRIKES.today.all above already carries real volume numbers
    // (1200/5400/900) -- this proves they actually reach the DOM now.
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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

  test('heatmap renders canonical cells verbatim (value == formatted payload; sign -> colour)', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    // a LIVE surface shows no stale/reference banner and is tagged a live WINDOW (not "complete")
    await expect(page.locator('.heat-banner')).toHaveCount(0);
    await expect(page.locator('#heatScope')).toContainText('LIVE·window');
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

  test('stale/reference gamma surface fails stale visibly (no morning snapshot passed as live)', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, SURFACE, {
        source: 'banked_morning_reference', live: false, stale: true,
        degraded: 'live terrain surface unavailable — showing banked MORNING chain (reference only: morning spot + morning Greeks, NOT intraday)',
      })),
    }));
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const banner = page.locator('.heat-banner.ref');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('MORNING REFERENCE');
    await expect(banner).toContainText('intraday');
    await expect(page.locator('#heatScope')).toContainText('REF');
    // B: the reference surface visually recedes, not just a banner
    await expect(page.locator('.heat-wrap.recede')).toBeVisible();
  });

  test('persists workspace/view across reload (D: UI state, not market truth)', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();       // restored from localStorage
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
  });

  test('key levels rail reflects /api/terrain', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
      const url = route.request().url(); hits.push(url);
      const body = pending ? { _tier: 'C_analytics', ticker: '$SPX', selected_exp: null, analytics_pending_shell: true, expiries: [], totals_rows: [] }
        : analyticsFor(url);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
      hits.push(route.request().url());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(analyticsFor(route.request().url())) });
    });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
      hits.push(route.request().url());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(analyticsFor(route.request().url())) });
    });
    const planeReads = [];
    await page.route('**/api/live/state**', (route) => {
      planeReads.push(route.request().url());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liveNow(route.request().url())) });
    });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    const REAL = require('./fixtures/real_spy_gamma_surface_116x16_premarket_20260910.json');
    const stamped = Object.assign({}, REAL, {
      session_date_et: '2026-09-10', prior_session: true,
      expirations: REAL.expirations.map((e) => Object.assign({}, e, { expired: e.expiry < '2026-09-10' })),
    });
    expect(stamped.strikes.length).toBe(116); expect(stamped.expirations.length).toBe(16);
    expect(stamped.expirations.filter((e) => e.expired).map((e) => e.expiry)).toEqual(['2026-09-09']);
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stamped) }));
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    // prior-session reference is unmistakable and concise (details in the tooltip, not a paragraph)
    const banner = page.locator('#heatBody .heat-banner.ref');
    await expect(banner).toContainText('PRIOR SESSION REFERENCE');
    await expect(banner).toContainText('2026-09-09');
    expect((await banner.getAttribute('title') || '').length).toBeGreaterThan(20);
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
    // add a symbol via the shell API (foundation is editable + localStorage-backed)
    await page.evaluate(() => window.EdShell.addSymbol('AMD'));
    await expect(page.locator('.wl-row .wl-sym', { hasText: 'AMD' })).toHaveCount(1);
  });

  test('chart view: Price + GEX Profile and Dot Map render from canonical inputs', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });   // init ticker SPY -> delayed 111.11
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    // 601.23 comes only from env.payload; the /api/live/state poll fallback would show 583.41
    await expect(page.locator('#hPx')).toHaveText('601.23');
    await expect(page.locator('#hFeed')).toContainText('LIVE');
  });

  test('theme A/B: explicit dark and light selections persist across reload', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');   // SYSTEM + OS light -> light
  });

  test('theme SYSTEM follows LIVE OS changes; explicit ignores them (A-F)', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => { try { localStorage.setItem('ed_theme', 'system'); } catch (e) {} });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const run = () => page.evaluate(() => window.EdStream.setActiveTicker('SPY'));
    mode = 'missing'; expect((await run()).requestAccepted).toBe(false);   // missing ticker -> rejected
    mode = 'wrong';   expect((await run()).requestAccepted).toBe(false);   // mismatched ticker -> rejected
    mode = 'err500';  expect((await run()).requestAccepted).toBe(false);   // non-2xx -> rejected
    mode = 'ok';      const ok = await run();
    expect(ok.requestAccepted).toBe(true);                                 // request accepted only
    expect(ok.bookBound).toBeNull();                                       // book binding NOT_PROVEN here
  });

  test('#1 perf: a large heatmap surface renders synchronously without pathological jank', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const ms = await page.evaluate(() => {
      var host = document.getElementById('heatBody');
      var exps = [], strikes = [], cells = [];
      for (var i = 0; i < 20; i++) exps.push({ expiry: '2026-' + (i < 4 ? '09' : '12') + '-' + String(10 + (i % 20)).padStart(2, '0'), dte: i * 3 });
      for (var s = 0; s < 200; s++) strikes.push(500 + s);
      for (var si = 0; si < strikes.length; si++) {
        var row = [];
        for (var j = 0; j < exps.length; j++) row.push((j % 2 ? 1 : -1) * 1000 * ((si % 50) + 1));
        cells.push({ strike: strikes[si], gex: row });
      }
      var surface = { available: true, source: 'terrain_live_cache', live: true, spot: 600, complete: false,
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const r = await page.evaluate(() => {
      var host = document.getElementById('heatBody');
      var R = window.EdGamma.renderSurface;
      var mark = function () { var c = host.querySelector('.hcell'); if (c) c.setAttribute('data-marker', '1'); };
      var marked = function () { return !!host.querySelector('.hcell[data-marker="1"]'); };
      var banner = function () { var b = host.querySelector('.heat-banner'); return b ? b.textContent : ''; };
      var scope = function () { return document.getElementById('heatScope').textContent; };
      var live = function (age, stale) {
        return { available: true, source: 'terrain_live_cache', live: true, stale: !!stale, warming: false, spot: 583.41,
          complete: false, chain_as_of_ts_utc: 1000, spot_as_of_ts_utc: 1000, chain_basis: 'full', age_sec: age,
          coverage: { chain_basis: 'full' }, expirations: [{ expiry: '2026-09-11', dte: 2 }], strikes: [583], cells: [{ strike: 583, gex: [958600] }] };
      };
      var banked = function (etd, warming) {   // an ON-BOARD symbol (on_board:true) -> a refresh is coming
        return { available: true, source: 'banked_morning_reference', live: false, stale: true, warming: warming, requested: true, on_board: true,
          chain_as_of_ts_utc: null, spot_as_of_ts_utc: null, chain_basis: 'banked_morning', et_date: etd, age_sec: null,
          coverage: { window: 'banked_morning_wide' }, degraded: 'banked morning wide reference (not intraday)',
          expirations: [{ expiry: '2026-09-11', dte: 2 }], strikes: [583], cells: [{ strike: 583, gex: [100000] }] };
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    var b = page.locator('.heat-banner').first();
    await expect(b).toContainText('NOT COLLECTING');
    await expect(b).toContainText('not currently active for this symbol');
    await expect(b).not.toContainText('awaiting');
  });

  test('responsive proof: 2560x1440 and 1920x1080 screenshots', async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('#sdCtx')).toContainText('583');

    await expect.poll(() => requests.length).toBeGreaterThan(0);
    const sent = requests[requests.length - 1].contracts.slice().sort();
    expect(sent).toEqual(['SPY   260911C00583000', 'SPY   260911P00583000']);
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });

    // select strike 583 on SPY -- resolves immediately, its contracts are ACCEPTED into the
    // plural subscription (a real non-empty desired state, not the initial empty one)
    await page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]').click();
    await expect(page.locator('#sdCtx')).toContainText('583');
    await expect.poll(() => requests.length).toBeGreaterThan(0);
    expect(requests[requests.length - 1].slice().sort()).toEqual(
      ['SPY   260911C00583000', 'SPY   260911P00583000'].sort());

    // select strike 586 -- fires the SECOND (delayed) /api/chain fetch, nothing resolves yet
    await page.locator('.hcell[data-strike="586"][data-expiry="2026-09-11"]').click();
    await expect.poll(() => releaseChain !== null).toBe(true);

    // switch ticker BEFORE the delayed 586 chain response arrives
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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
});
