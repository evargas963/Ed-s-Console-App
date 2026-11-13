// @ts-check
/**
 * TICKER / EXPIRY / MEASURE controls — the value IS the control (real dropdowns, not metadata chips).
 * Proves: one selected-symbol state (dropdown <-> watchlist <-> header <-> panels); the expiry list
 * comes from the page's socket (never hard-coded); All Expirations shows every canonical column; a single
 * expiry filters the heatmap to that column; an old expiry invalid for a new ticker fails safe to All;
 * terrain Key Levels stay disclosed as all-exp when a single expiry is filtered. Offline.
 */
const { test, expect } = require('@playwright/test');
const { expiriesAnswer, pushExpiries } = require('./fixtures/expiries');
const { expiriesFrame, served, chainAt } = require('./fixtures/price_socket');
const { routeWatchlist, beat } = require('./fixtures/watchlist');
const { watchRequests, holdClock } = require('./fixtures/settled');

// The two tickers with panels are SPY and AMZN, each the server's own answers on its real chain of
// 2026-11-12 (held to the server by tests/test_e2e_panels_two_day_v1.py); any other ticker a
// test types has no panel sent. The expiry list is SPY's real one (34 expiries).
const SETS = { SPY: require('./fixtures/panels_spy_two_day.json'), AMZN: require('./fixtures/panels_amzn_two_day.json') };
const EXPS = SETS.SPY.surface.expirations.map((e) => e.expiry);
const DTE = Object.fromEntries(SETS.SPY.surface.expirations.map((e) => [e.expiry, e.dte]));
const PICK = EXPS[1];                       // SPY's second expiry
// the served window: every column, or the selected expiry's alone (server.py _surface_view)
function surfaceFor(set, expiry) {
  if (!expiry) return set.surface;
  return expiry === set.surface_second_expiry.expirations[0].expiry ? set.surface_second_expiry : undefined;
}

async function intercept(page) {
  const of = (key, part) => (SETS[key] ? part(SETS[key]) : undefined);
  return pushExpiries(page, EXPS, DTE,
    { tape: (key) => of(key, (s) => s.tape), bars: (key) => of(key, (s) => s.bars['1']),
      terrain: (key) => of(key, (s) => s.terrain), strikes: (key) => of(key, (s) => s.strikes),
      surface: (key, params) => of(key, (s) => surfaceFor(s, params.expiry)),
      chain: (key, params) => of(key, (s) => chainAt(s.chain)(key, params)) });
}

test.describe('ticker / expiry / measure controls', () => {
  let watchlist;                  // the list the daemon keeps, as its stand-in holds it
  let sock;                       // the page's socket, stood in for
  test.beforeEach(async ({ page }) => {
    sock = await intercept(page);
    watchlist = await routeWatchlist(page, ['SPY', 'AMZN', 'IWM']);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); });
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

  test('expiry options come from the page\'s socket; All Expirations is the default', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const opts = page.locator('#expSel option');
    await expect(opts).toHaveCount(1 + EXPS.length);           // All + each canonical expiry
    await expect(opts.first()).toHaveText('All Expirations');
    await expect(page.locator('#expSel')).toHaveValue('');     // defaults to All
  });

  test('a new chain pushed for the ticker on screen replaces the expiry list (2026-10-08: yesterday\'s list stayed)', async ({ page }) => {
    // The program held yesterday's chain when the page subscribed; today's chain lands, and the
    // program pushes today's list on the page's socket, with no request from the page.
    const YESTERDAY = expiriesAnswer(['2026-10-07', '2026-10-08'], { '2026-10-07': 0, '2026-10-08': 1 });
    const TODAY = expiriesAnswer(['2026-10-08', '2026-10-09'], { '2026-10-08': 0, '2026-10-09': 1 });
    const asked = [];
    page.on('request', (r) => { if (r.url().includes('/api/expiries')) asked.push(r.url()); });
    let program;
    await page.routeWebSocket(/\/ws$/, (ws) => {
      program = ws;
      beat(page, ws);   // the program's beat, the watchlist the rail draws
      ws.onMessage((m) => {
        const req = JSON.parse(String(m));
        if (req.op !== 'subscribe') return;
        ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
        ws.send(expiriesFrame(req.ticker, YESTERDAY));
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#expSel option')).toHaveText(['All Expirations', '10/07/2026 · 0DTE', '10/08/2026 · 1DTE']);
    program.send(expiriesFrame('SPY', TODAY));                // today's chain reached the program
    await expect(page.locator('#expSel option')).toHaveText(['All Expirations', '10/08/2026 · 0DTE', '10/09/2026 · 1DTE']);
    expect(asked).toEqual([]);
  });

  test('selecting one expiry filters the heatmap to that column; All restores every column', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(EXPS.length);   // All Expirations
    await page.locator('#expSel').selectOption(PICK);
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(1);             // just the selected expiry
    await expect(page.locator('#view-heatmap .hexp .d')).toHaveText(PICK.slice(5));
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
    await typeSymbol(page, 'AMZN');
    await expect(page.locator('#hSym')).toHaveText('AMZN');                        // header
    await expect(page.locator('.wl-row.sel .wl-sym')).toHaveText('AMZN');          // watchlist selection (AMZN is a member)
    await expect(page.locator('#mvTicker')).toHaveText('AMZN');                    // panel header
    // the heatmap is AMZN's now (its price is 269.43: a 270 strike row exists; SPY's rows are near 757)
    await expect(page.locator('#view-heatmap .hstrike', { hasText: '270' }).first()).toBeVisible();
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
    for (const sym of ['AAPL', 'META', 'NVDA', 'AVGO', 'PLTR']) {
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
    expect(watchlist).toEqual(['SPY', 'AMZN', 'IWM', 'PLTR']);                     // added through the console
  });

  // Step 4 (operator 2026-10-07): a ticker Schwab does not quote (named in errors.invalidSymbols) is
  // shown as invalid with Schwab's answer and not added; a removal is the daemon's, its list the answer.
  test('an invalid ticker is shown as invalid and not added; a removal leaves the served list', async ({ page }) => {
    await routeWatchlist(page, ['SPY', 'AMZN', 'IWM'], ['ZQZQZ']);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.wl-row')).toHaveCount(3);
    await page.evaluate(() => window.EdShell.addSymbol('ZQZQZ'));
    await expect(page.locator('#wlMsg')).toHaveText(
      'ZQZQZ is not added: Schwab does not quote it ({"errors":{"invalidSymbols":["ZQZQZ"]}})');
    await expect(page.locator('.wl-row')).toHaveCount(3);
    await page.locator('[data-rm="AMZN"]').click();
    await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'IWM']);
  });

  // The message line is the answer to the operator's own add: the price watchdog finding the push
  // silent a moment later marks the list (the header says why) and does not write over it.
  test('the answer to an add stands when the price watchdog then finds the push silent', async ({ page }) => {
    await routeWatchlist(page, ['SPY', 'AMZN', 'IWM'], ['ZQZQZ']);
    await holdClock(page);   // the page's timers run when the test moves its time
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.wl-row')).toHaveCount(3);
    await expect(page.locator('#watchlist')).not.toHaveClass(/wl-degraded/);
    await page.evaluate(() => window.EdShell.addSymbol('ZQZQZ'));
    const said = 'ZQZQZ is not added: Schwab does not quote it ({"errors":{"invalidSymbols":["ZQZQZ"]}})';
    await expect(page.locator('#wlMsg')).toHaveText(said);
    await page.clock.runFor(1500);   // the watchdog's next look: no price row has come
    await expect(page.locator('#watchlist')).toHaveClass(/wl-degraded/);
    await expect(page.locator('#wlMsg')).toHaveText(said);
  });

  test('#9 ONE ticker state: watchlist click, typed entry, Gamma / Chain / Flow and the expiry filter resolve to the same instrument, no prior-symbol subscribe afterwards', async ({ page }) => {
    const requests = watchRequests(page);
    await holdClock(page);   // the page's timers run when the test moves its time
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await typeSymbol(page, 'AAPL');
    await expect(page.locator('#hSym')).toHaveText('AAPL');
    await page.locator('#expSel').selectOption(PICK);                            // expiry context on AAPL
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect(page.locator('#chTicker')).toHaveText('AAPL');
    await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
    await expect(page.locator('#flTicker')).toHaveText('AAPL');
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await expect(page.locator('#mvTicker')).toHaveText('AAPL');
    // what opening the tab asks: the tape panel, for AAPL
    await expect.poll(() => { const s = sock.subscribes[sock.subscribes.length - 1]; return s.ticker + ' ' + ('tape' in s.panels); })
      .toBe('AAPL true');
    // switch by WATCHLIST CLICK -> the same single state everywhere; nothing keeps asking for AAPL
    const before = sock.subscribes.length;
    await page.locator('.wl-row .wl-sym', { hasText: 'AMZN' }).click();
    await expect(page.locator('#hSym')).toHaveText('AMZN');
    await expect(page.locator('#symInput')).toHaveValue('AMZN');
    await expect(page.locator('#mvTicker')).toHaveText('AMZN');
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect(page.locator('#chTicker')).toHaveText('AMZN');
    await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
    await expect(page.locator('#flTicker')).toHaveText('AMZN');
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await requests.settled();                                                        // the switch's own reads are done
    await page.clock.runFor(4000);                                                   // every page timer due in 4 s has run
    await requests.settled();                                                        // and every read those made
    const tickered = sock.subscribes.slice(before).map((s) => s.ticker);
    expect(tickered.length).toBeGreaterThan(0);
    expect(tickered.filter((t) => t !== 'AMZN')).toEqual([]);                         // no AAPL (or SPY) subscribe survives the switch
    expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe('AMZN');
  });

  // An expiry belongs to its ticker: right after a switch, before the new ticker's list is known,
  // the page asked for the NEW ticker's chain and surface at the OLD ticker's expiry.
  test('a ticker switch reads no old expiry; the new list re-applies a still-valid one, else All', async ({ page }) => {
    const LIST = expiriesAnswer(EXPS, DTE);
    const IWM_LIST = expiriesAnswer([EXPS[2]], { [EXPS[2]]: DTE[EXPS[2]] });
    const read = [];   // [ticker, expiry] of every read that names both
    page.on('request', (r) => {
      const q = new URL(r.url()).searchParams;
      if (q.get('ticker') && q.get('expiry')) read.push([q.get('ticker'), q.get('expiry')]);
    });
    const requests = watchRequests(page);
    let releaseAmzn;
    const amznHeld = new Promise((resolve) => { releaseAmzn = resolve; });
    await page.routeWebSocket(/\/ws$/, (ws) => {
      beat(page, ws);   // the program's beat, the watchlist the rail draws (AMZN and IWM clicked below)
      ws.onMessage(async (m) => {
        const req = JSON.parse(String(m));
        if (req.op !== 'subscribe') return;
        // a panel asked at an expiry is a read that names both, as a route's was
        Object.values(req.panels).forEach((p) => { if (req.ticker && p.expiry) read.push([req.ticker, p.expiry]); });
        ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
        if (req.ticker === 'AMZN') await amznHeld;   // AMZN's list is held until the test releases it
        ws.send(expiriesFrame(req.ticker, req.ticker === 'IWM' ? IWM_LIST : LIST));
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#expSel option[value="' + PICK + '"]')).toHaveCount(1);
    await page.locator('#expSel').selectOption(PICK);
    await expect.poll(() => read.some(([t, e]) => t === 'SPY' && e === PICK)).toBe(true);
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();            // the Chain tab reads at the expiry too
    await page.locator('.wl-row .wl-sym', { hasText: 'AMZN' }).click();
    await expect(page.locator('#chTicker')).toHaveText('AMZN');
    await requests.settled();                                                       // every read the switch made
    expect(read.filter(([t]) => t === 'AMZN')).toEqual([]);                         // none at SPY's expiry, or any
    await expect(page.locator('#expSel')).toHaveValue('');
    releaseAmzn();                                                                   // AMZN's list lists PICK: kept
    await expect(page.locator('#expSel')).toHaveValue(PICK);
    await expect.poll(() => read.some(([t, e]) => t === 'AMZN' && e === PICK)).toBe(true);
    await page.locator('.wl-row .wl-sym', { hasText: 'IWM' }).click();             // IWM's list does not: All
    await expect(page.locator('#chTicker')).toHaveText('IWM');
    await expect(page.locator('#expSel option[value="' + EXPS[2] + '"]')).toHaveCount(1);
    await expect(page.locator('#expSel')).toHaveValue('');
    await requests.settled();
    expect(read.filter(([t, e]) => t === 'IWM' && e === PICK)).toEqual([]);
  });
});
