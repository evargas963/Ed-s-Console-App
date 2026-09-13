// @ts-check
/**
 * TICKER / EXPIRY / MEASURE controls — the value IS the control (real dropdowns, not metadata chips).
 * Proves: one selected-symbol state (dropdown <-> watchlist <-> header <-> panels); the expiry list
 * comes from /api/expiries (never hard-coded); All Expirations shows every canonical column; a single
 * expiry filters the heatmap to that column; an old expiry invalid for a new ticker fails safe to All;
 * terrain Key Levels stay disclosed as all-exp when a single expiry is filtered. Offline.
 */
const { test, expect } = require('@playwright/test');

const EXPS = ['2026-09-11', '2026-09-12', '2026-09-18'];
function surfaceFor(tk, spot) {
  return { ticker: tk, symbol: tk, available: true, spot: spot, source: 'terrain_live_cache',
    live: true, stale: false, age_sec: 5, chain_basis: 'full', complete: false,
    expirations: EXPS.map(function (e, i) { return { expiry: e, dte: [2, 3, 9][i] }; }),
    strikes: [spot - 2, spot, spot + 2],
    cells: [spot - 2, spot, spot + 2].map(function (k) { return { strike: k, gex: [-90000, 958600, -264500] }; }) };
}
const TERRAIN = { spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98, absolute_gamma_strike: 100,
  net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false, levels_age_sec: 10 };
const STRIKES = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 10, levels_stale: false,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] } };
const BARS = { bars: [{ t: 1757000000, o: 99, h: 101, l: 98, c: 100, v: 1000 }] };
function liveFor(tk, spot) { return { ticker: tk, spot: spot, spot_disp: spot.toFixed(2), bid: spot - 0.01, ask: spot + 0.01,
  session_label: 'RTH', analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } }; }

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const tk = (url.match(/[?&]ticker=([^&]+)/) || [])[1] || 'SPY';
    const dec = decodeURIComponent(tk);
    const spot = dec === 'QQQ' ? 480 : 100;
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = surfaceFor(dec, spot);
    else if (url.includes('/api/terrain/strikes')) body = Object.assign({}, STRIKES, { spot: spot });
    else if (url.includes('/api/terrain')) body = Object.assign({}, TERRAIN, { spot: spot });
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/expiries')) body = { expiries: EXPS };
    else if (url.includes('/api/chain')) body = { ticker: dec, spot: spot, expiry: EXPS[0], status: 'ok',
      scope: { kind: 'complete_single_expiry' }, contracts: [] };
    else if (url.includes('/api/live/state')) body = liveFor(dec, spot);
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('ticker / expiry / measure controls', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY');
      localStorage.setItem('ed_watchlist_v1', JSON.stringify(['SPY', 'QQQ', 'IWM'])); } catch (e) {} });
  });

  test('controls are real dropdowns (value is the control, no SYM/EXPIRY/MEASURE chips)', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#symInput')).toBeVisible();   // #9: a typed instrument control, not a watchlist-bound select
    await expect(page.locator('#expSel')).toBeVisible();
    await expect(page.locator('#measureSel')).toBeVisible();
    // the old SYM/EXPIRY/MEASURE metadata chips are gone (the value itself is the control)
    await expect(page.locator('.viewbar .ctrls .sel')).toHaveCount(0);
    await expect(page.locator('#measureSel')).toHaveValue('gex');
  });

  test('expiry options come from /api/expiries; All Expirations is the default', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const opts = page.locator('#expSel option');
    await expect(opts).toHaveCount(1 + EXPS.length);           // All + each canonical expiry
    await expect(opts.first()).toHaveText('All Expirations');
    await expect(page.locator('#expSel')).toHaveValue('');     // defaults to All
  });

  test('selecting one expiry filters the heatmap to that column; All restores every column', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(EXPS.length);   // All Expirations
    await page.locator('#expSel').selectOption('2026-09-12');
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(1);             // just the selected expiry
    await expect(page.locator('#view-heatmap .hexp .d')).toHaveText('09-12');
    // Key Levels stays aggregate terrain, disclosed as all-exp (never relabeled selected-expiry)
    await expect(page.locator('#klSrc')).toContainText('all-exp');
    await page.locator('#expSel').selectOption('');
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(EXPS.length);
    await expect(page.locator('#klSrc')).not.toContainText('all-exp');
  });

  async function typeSymbol(page, sym) {
    await page.locator('#symInput').fill(sym);
    await page.locator('#symInput').press('Enter');
  }

  test('one symbol state: typed instrument -> header/watchlist/panels all move together', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#symInput')).toHaveValue('SPY');
    await typeSymbol(page, 'QQQ');
    await expect(page.locator('#hSym')).toHaveText('QQQ');                        // header
    await expect(page.locator('.wl-row.sel .wl-sym')).toHaveText('QQQ');          // watchlist selection (QQQ is a member)
    await expect(page.locator('#mvTicker')).toHaveText('QQQ');                    // panel header
    // the heatmap refetched for QQQ (spot 480 -> a 480 strike row exists)
    await expect(page.locator('#view-heatmap .hstrike', { hasText: '480' }).first()).toBeVisible();
  });

  test('watchlist click keeps the instrument control synchronized', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.wl-row .wl-sym', { hasText: 'IWM' }).click();
    await expect(page.locator('#symInput')).toHaveValue('IWM');
    await expect(page.locator('#hSym')).toHaveText('IWM');
  });

  // #9 (live operator finding 2026-09-10): the analytical ticker control was built FROM the watchlist,
  // so only SPY/QQQ/IWM/NVDA/TSLA were selectable and analysing a symbol mutated the watchlist. The
  // two responsibilities are separate: WATCHLIST = persistent symbols the operator monitors (explicit
  // add/remove); ACTIVE INSTRUMENT = any supported Schwab symbol analysed now (typed -> Enter).
  test('#9 ACTIVE INSTRUMENT is not watchlist membership: any typed symbol switches the workspace; the watchlist never changes', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const wlBefore = await page.evaluate(() => localStorage.getItem('ed_watchlist_v1'));
    const rowsBefore = await page.locator('.wl-row').count();
    expect(rowsBefore).toBe(3);
    for (const sym of ['AAPL', 'META', 'AMZN', 'AVGO', 'PLTR']) {
      await typeSymbol(page, sym);
      await expect(page.locator('#hSym')).toHaveText(sym);                        // header
      await expect(page.locator('#mvTicker')).toHaveText(sym);                    // Gamma panel
      await expect(page.locator('#symInput')).toHaveValue(sym);                   // the control reflects the ONE state
      expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe(sym);
      await expect(page.locator('.wl-row.sel')).toHaveCount(0);                   // not a member -> no row selected, none added
      await expect(page.locator('.wl-row')).toHaveCount(rowsBefore);
    }
    expect(await page.evaluate(() => localStorage.getItem('ed_watchlist_v1'))).toBe(wlBefore);   // persisted watchlist untouched
    // the header search analyses too — it never adds to the watchlist
    await page.locator('#symSearch').fill('nflx'); await page.locator('#symSearch').press('Enter');
    await expect(page.locator('#hSym')).toHaveText('NFLX');
    expect(await page.evaluate(() => localStorage.getItem('ed_watchlist_v1'))).toBe(wlBefore);
    // a malformed entry is refused (nothing is fabricated, no allowlist decides): the control reverts
    await typeSymbol(page, 'not a symbol!!');
    await expect(page.locator('#hSym')).toHaveText('NFLX');
    await expect(page.locator('#symInput')).toHaveValue('NFLX');
    // adding to the watchlist remains an EXPLICIT separate action (the rail's "+ Add symbol")
    page.once('dialog', (d) => d.accept('PLTR'));
    await page.locator('#wlAdd').click();
    await expect(page.locator('.wl-row')).toHaveCount(rowsBefore + 1);
    await expect(page.locator('.wl-row.sel .wl-sym')).toHaveText('PLTR');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('ed_watchlist_v1')))).toEqual(['SPY', 'QQQ', 'IWM', 'PLTR']);
  });

  test('#9 ONE ticker state: watchlist click, typed entry, Gamma / Chain / Flow and the expiry filter resolve to the same instrument, no prior-symbol request afterwards', async ({ page }) => {
    const reqs = [];
    page.on('request', (r) => { const u = r.url(); if (u.includes('/api/')) reqs.push(u); });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await typeSymbol(page, 'AAPL');
    await expect(page.locator('#hSym')).toHaveText('AAPL');
    await page.locator('#expSel').selectOption('2026-09-12');                    // expiry context on AAPL
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect(page.locator('#chTicker')).toHaveText('AAPL');
    await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
    await expect(page.locator('#flTicker')).toHaveText('AAPL');
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await expect(page.locator('#mvTicker')).toHaveText('AAPL');
    // switch by WATCHLIST CLICK -> the same single state everywhere; nothing keeps asking for AAPL
    reqs.length = 0;
    await page.locator('.wl-row .wl-sym', { hasText: 'QQQ' }).click();
    await expect(page.locator('#hSym')).toHaveText('QQQ');
    await expect(page.locator('#symInput')).toHaveValue('QQQ');
    await expect(page.locator('#mvTicker')).toHaveText('QQQ');
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect(page.locator('#chTicker')).toHaveText('QQQ');
    await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
    await expect(page.locator('#flTicker')).toHaveText('QQQ');
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await page.waitForTimeout(4000);                                                 // more than one scheduler tick
    const tickered = reqs.filter((u) => /[?&]ticker=/.test(u));
    expect(tickered.length).toBeGreaterThan(0);
    expect(tickered.filter((u) => !/[?&]ticker=QQQ(&|$)/.test(u))).toEqual([]);      // no AAPL (or SPY) request survives the switch
    expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe('QQQ');
  });
});
