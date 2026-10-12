// @ts-check
/**
 * TICKER / EXPIRY / MEASURE controls — the value IS the control (real dropdowns, not metadata chips).
 * Proves: one selected-symbol state (dropdown <-> watchlist <-> header <-> panels); the expiry list
 * comes from /api/expiries (never hard-coded); All Expirations shows every canonical column; a single
 * expiry filters the heatmap to that column; an old expiry invalid for a new ticker fails safe to All;
 * terrain Key Levels stay disclosed as all-exp when a single expiry is filtered. Offline.
 */
const { test, expect } = require('@playwright/test');
const { routeWatchlist } = require('./fixtures/watchlist');

const EXPS = ['2026-09-11', '2026-09-12', '2026-09-18'];
// the served window: every column, or the selected expiry's alone (server.py _surface_view)
function surfaceFor(tk, spot, expiry) {
  const gex = [-90000, 958600, -264500];
  const cols = EXPS.map(function (e, i) { return i; }).filter(function (i) { return !expiry || EXPS[i] === expiry; });
  return { ticker: tk, symbol: tk, available: true, spot: spot, source: 'terrain_live_cache',
    live: true, stale: false, age_sec: 5, chain_basis: 'full', complete: false,
    expirations: cols.map(function (i) { return { expiry: EXPS[i], dte: [2, 3, 9][i], front: i === 0 }; }),
    strikes: [spot - 2, spot, spot + 2],
    cells: [spot - 2, spot, spot + 2].map(function (k) {
      return { strike: k, gex: cols.map(function (i) { return gex[i]; }), spot: k === spot }; }),
    view: { centre: spot, scope: 'auto', coverage: null, max_abs: { gex: 958600 }, missing_expiry: null } };
}
const TERRAIN = { spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98, absolute_gamma_strike: 100,
  net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false, levels_age_sec: 10 };
const STRIKES = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 10, levels_stale: false,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] },
  views: { all: { centre: 100, note: null, max_abs: 958600 } } };
const BARS = { bars: [{ t: 1757000000, o: 99, h: 101, l: 98, c: 100, v: 1000 }] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const tk = (url.match(/[?&]ticker=([^&]+)/) || [])[1] || 'SPY';
    const dec = decodeURIComponent(tk);
    const spot = dec === 'QQQ' ? 480 : 100;
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = surfaceFor(dec, spot, new URL(url).searchParams.get('expiry'));
    else if (url.includes('/api/terrain/strikes')) body = Object.assign({}, STRIKES, { spot: spot });
    else if (url.includes('/api/terrain')) body = Object.assign({}, TERRAIN, { spot: spot });
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/expiries')) body = { expiries: EXPS };
    else if (url.includes('/api/chain')) body = { ticker: dec, spot: spot, expiry: EXPS[0], status: 'ok',
      scope: { kind: 'complete_single_expiry' }, contracts: [] };    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('ticker / expiry / measure controls', () => {
  let watchlist;                  // the list the daemon keeps, as its stand-in holds it
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    watchlist = await routeWatchlist(page, ['SPY', 'QQQ', 'IWM']);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('controls are real dropdowns (value is the control, no SYM/EXPIRY/MEASURE chips)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#symInput')).toBeVisible();   // #9: a typed instrument control, not a watchlist-bound select
    await expect(page.locator('#expSel')).toBeVisible();
    await expect(page.locator('#measureSel')).toBeVisible();
    // the old SYM/EXPIRY/MEASURE metadata chips are gone (the value itself is the control)
    await expect(page.locator('.viewbar .ctrls .sel')).toHaveCount(0);
    await expect(page.locator('#measureSel')).toHaveValue('gex');
  });

  test('expiry options come from /api/expiries; All Expirations is the default', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const opts = page.locator('#expSel option');
    await expect(opts).toHaveCount(1 + EXPS.length);           // All + each canonical expiry
    await expect(opts.first()).toHaveText('All Expirations');
    await expect(page.locator('#expSel')).toHaveValue('');     // defaults to All
  });

  test('a new chain pushed for the ticker on screen replaces the expiry list (2026-10-08: yesterday\'s list stayed)', async ({ page }) => {
    // The console held yesterday's chain when the page opened; today's chain lands, the console
    // pushes `chain` on /api/changes, and /api/expiries serves today's list.
    const YESTERDAY = { expiries: ['2026-10-07', '2026-10-08'],
      labels: { '2026-10-07': '10/07/2026 · 0DTE', '2026-10-08': '10/08/2026 · 1DTE' } };
    const TODAY = { expiries: ['2026-10-08', '2026-10-09'],
      labels: { '2026-10-08': '10/08/2026 · 0DTE', '2026-10-09': '10/09/2026 · 1DTE' } };
    let served = YESTERDAY, listed;
    const first = new Promise((resolve) => { listed = resolve; });
    await page.route('**/api/expiries**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(served) });
      listed();
    });
    let pushes = 0;
    await page.route('**/api/changes**', async (route) => {
      pushes += 1;
      await first;                                          // the page holds yesterday's list
      served = TODAY;                                        // today's chain reached the console
      route.fulfill({ status: 200, contentType: 'text/event-stream',
        body: pushes === 1 ? 'event: chain\ndata: SPY\n\n' : 'event: session\ndata: RTH\n\n' });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#expSel option')).toHaveText(['All Expirations', '10/08/2026 · 0DTE', '10/09/2026 · 1DTE']);
  });

  test('selecting one expiry filters the heatmap to that column; All restores every column', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
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
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#symInput')).toHaveValue('SPY');
    await typeSymbol(page, 'QQQ');
    await expect(page.locator('#hSym')).toHaveText('QQQ');                        // header
    await expect(page.locator('.wl-row.sel .wl-sym')).toHaveText('QQQ');          // watchlist selection (QQQ is a member)
    await expect(page.locator('#mvTicker')).toHaveText('QQQ');                    // panel header
    // the heatmap refetched for QQQ (spot 480 -> a 480 strike row exists)
    await expect(page.locator('#view-heatmap .hstrike', { hasText: '480' }).first()).toBeVisible();
  });

  // #9 (live operator finding 2026-09-10): the analytical ticker control was built FROM the watchlist,
  // so only SPY/QQQ/IWM/NVDA/TSLA were selectable and analysing a symbol mutated the watchlist. The
  // two responsibilities are separate: WATCHLIST = persistent symbols the operator monitors (explicit
  // add/remove); ACTIVE INSTRUMENT = any supported Schwab symbol analysed now (typed -> Enter).
  test('#9 ACTIVE INSTRUMENT is not watchlist membership: any typed symbol switches the workspace; the watchlist never changes', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.wl-row')).toHaveCount(3);                         // the daemon's list, served
    const wlBefore = watchlist.slice();
    const rowsBefore = await page.locator('.wl-row').count();
    for (const sym of ['AAPL', 'META', 'AMZN', 'AVGO', 'PLTR']) {
      await typeSymbol(page, sym);
      await expect(page.locator('#hSym')).toHaveText(sym);                        // header
      await expect(page.locator('#mvTicker')).toHaveText(sym);                    // Gamma panel
      await expect(page.locator('#symInput')).toHaveValue(sym);                   // the control reflects the ONE state
      expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe(sym);
      await expect(page.locator('.wl-row.sel')).toHaveCount(0);                   // not a member -> no row selected, none added
      await expect(page.locator('.wl-row')).toHaveCount(rowsBefore);
    }
    expect(watchlist).toEqual(wlBefore);                                          // the kept watchlist untouched
    // the header search analyses too — it never adds to the watchlist
    await page.locator('#symSearch').fill('nflx'); await page.locator('#symSearch').press('Enter');
    await expect(page.locator('#hSym')).toHaveText('NFLX');
    expect(watchlist).toEqual(wlBefore);
    // a malformed entry is refused (nothing is fabricated, no allowlist decides): the control reverts
    await typeSymbol(page, 'not a symbol!!');
    await expect(page.locator('#hSym')).toHaveText('NFLX');
    await expect(page.locator('#symInput')).toHaveValue('NFLX');
    // adding to the watchlist remains an EXPLICIT separate action (the rail's "+ Add symbol")
    page.once('dialog', (d) => d.accept('PLTR'));
    await page.locator('#wlAdd').click();
    await expect(page.locator('.wl-row')).toHaveCount(rowsBefore + 1);
    await expect(page.locator('.wl-row.sel .wl-sym')).toHaveText('PLTR');
    expect(watchlist).toEqual(['SPY', 'QQQ', 'IWM', 'PLTR']);                     // added through the console
  });

  // Step 4 (operator 2026-10-07): a ticker Schwab does not quote (named in errors.invalidSymbols) is
  // shown as invalid with Schwab's answer and not added; a removal is the daemon's, its list the answer.
  test('an invalid ticker is shown as invalid and not added; a removal leaves the served list', async ({ page }) => {
    await routeWatchlist(page, ['SPY', 'QQQ', 'IWM'], ['ZQZQZ']);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.wl-row')).toHaveCount(3);
    await page.evaluate(() => window.EdShell.addSymbol('ZQZQZ'));
    await expect(page.locator('#wlMsg')).toHaveText(
      'ZQZQZ is not added: Schwab does not quote it ({"errors":{"invalidSymbols":["ZQZQZ"]}})');
    await expect(page.locator('.wl-row')).toHaveCount(3);
    await page.locator('[data-rm="QQQ"]').click();
    await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'IWM']);
  });

  test('#9 ONE ticker state: watchlist click, typed entry, Gamma / Chain / Flow and the expiry filter resolve to the same instrument, no prior-symbol request afterwards', async ({ page }) => {
    const reqs = [];
    page.on('request', (r) => { const u = r.url(); if (u.includes('/api/')) reqs.push(u); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
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
