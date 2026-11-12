// @ts-check
/**
 * RC-UI-1 — browser DOM proof for the rebuilt Ed Console shell + Options/Gamma heatmap.
 *
 * Proves the FRONTEND presentation contract in a real browser: the heatmap renders the
 * canonical surface the program sends on the page's socket VERBATIM (cell text == formatted backend value,
 * invariant E), sign -> colour with no inversion (invariant D), spot row highlight, and the Key
 * Levels rail reflects the terrain panel on the page's socket. The endpoint==faucet equality (the projected payload equals
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
const { pushExpiries } = require('./fixtures/expiries');
const path = require('path');

// The served window (server.py _surface_view): the cells to draw, each with `spot` (the row at
// the price) and the `view` -- the centre, the coverage words and each measure's colour scale.
// The page draws these; it picks and counts nothing.
//
// The base panels are the server's own answers on AMZN's real chain of 2026-11-12 10:39 ET, 24
// expiries, levels LIVE, the prior day's close compared (held to the server by
// tests/test_e2e_panels_two_day_v1.py). A test's induced condition is that answer with the
// named part changed.
const REAL = require('./fixtures/panels_amzn_two_day.json');
const SURFACE = REAL.surface, TERRAIN = REAL.terrain, STRIKES = REAL.strikes, CHAIN = REAL.chain;
const K = SURFACE.spot_strike;                       // 270, the strike at the price
const EXPIRIES = SURFACE.expirations.map((e) => e.expiry);
const E1 = EXPIRIES[0], E2 = EXPIRIES[1];            // 2026-11-13 (the front one), 2026-11-16
const MISSING = REAL.surface_missing_expiry.view.missing_expiry;   // 2026-11-14: no AMZN expiry
const CELL_K = SURFACE.cells.find((c) => c.strike === K);
// a served cell cut to its first `n` columns
function cut(cell, n) {
  return Object.fromEntries(Object.entries(cell).map(([k, v]) => [k, Array.isArray(v) ? v.slice(0, n) : v]));
}
function view(over = {}) { return Object.assign({}, SURFACE.view, over); }
// the heatmap cell at the price in the front expiry (51,735,223.55), and the surface's most
// negative cell, 262.5 on 2026-11-20 (-3,907,027.65)
const CELL = '.hcell[data-strike="' + K + '"][data-expiry="' + E1 + '"]';
const CELL_NEG = '.hcell[data-strike="262.5"][data-expiry="' + EXPIRIES[3] + '"]';
// SPY's surface as captured 2026-09-10 pre-market, with the served window the route adds
function realSpySurface() {
  const REAL = require('./fixtures/real_spy_gamma_surface_116x16_premarket_20260910.json');
  return Object.assign({}, REAL, {
    source: 'terrain_live_cache', levels_state: 'LIVE',
    session_date_et: '2026-09-10', prior_session: false,
    expirations: REAL.expirations.map((e) => Object.assign({}, e, { expired: e.expiry < '2026-09-10', front: e.expiry === '2026-09-10' })),
    cells: REAL.cells.map((c) => Object.assign({}, c, { spot: c.strike === 764 })),
    view: view({ centre: 764, scope: 'all', max_abs: { gex: 1e9 } }),
  });
}
// A surface WITH real per-cell vendor contract identity (server.py's project_gamma_surface
// always carries this in production).
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
  return Object.assign({}, SURFACE, { expirations: expirations, strikes: strikes, cells: cells,
    view: view({ centre: strikes[0], max_abs: { gex: 1000 } }) });
}
// Always-live heatmap mandate (2026-09-15): a surface carrying the real per-cell `stream`
// field server.py's _stamp_gamma_surface_cell_stream_state now stamps unconditionally on
// every real surface panel. `perCol` is one entry per expiry column
// for a single strike, each `{call, put}` naming that leg's state ('live'|'stale'|
// 'unavailable', or omitted entirely for "no contract on this leg").
function surfaceWithStreamState(perCol) {
  var strike = K;
  var expirations = perCol.map(function (_, i) { return SURFACE.expirations[i]; });
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
    cells: [{ strike: strike, gex: perCol.map(function () { return 12345; }), spot: true,
              contracts: contracts, stream: stream }],
    view: view({ max_abs: { gex: 12345 } }),
  });
}
// price bars around the real price (the set holds no bars)
const BARS = {
  ticker: 'AMZN', n: 8,
  bars: [-0.8, -0.5, -0.3, -0.6, -0.1, 0.1, -0.2, 0].map(function (d, i) {
    const c = TERRAIN.spot + d;
    return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i };
  }),
};
// the call at the price in the front expiry's chain, as Schwab sent it
const CALL_K = CHAIN.contracts.find((c) => c.strikePrice === K && c.putCall === 'CALL');

// The capture daemon's price socket, stood in for (tests/e2e/fixtures/price_socket.js).
const { mockPriceSocket, priceRow, served, panelFrame, chainAt } = require('./fixtures/price_socket');
// The console's watchlist routes, stood in for (tests/e2e/fixtures/watchlist.js).
const { routeWatchlist } = require('./fixtures/watchlist');
// The page's requests, watched until its work runs out (tests/e2e/fixtures/settled.js).
const { watchRequests, holdClock } = require('./fixtures/settled');

// The panels the page's socket sends this test (a test sets its own before the page opens), and
// the program's side of that socket: `sock.changed(kind)` sends the kind's panels again, as the
// program does when they change; `sock.subscribes` is every subscribe the page sent.
let panels, sock;
// the page's socket with these panels and the pushed price `rows`
async function socketWith(page, rows) {
  sock = await mockPriceSocket(page, rows, [], undefined, panels);
}
async function intercept(page) {
  // the console's answer to the contract the page names for the Flow panel
  await page.route('**/api/flow-contract', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, contract: route.request().postDataJSON().contract }) }));
  await routeWatchlist(page, ['SPY']);
  panels = { terrain: TERRAIN, strikes: STRIKES, surface: SURFACE, chain: chainAt(CHAIN),
    bars: BARS, tape: { available: false } };
  sock = await pushExpiries(page, EXPIRIES, undefined, panels);
}

test.describe('Ed Console shell + gamma heatmap', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); });
  });

  test('shell structure: rail has all six workspaces + 3-tier nav', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.navitem[data-ws]')).toHaveCount(6);   // Desk / Research dropped (operator 2026-09-27)
    for (const ws of ['trade-desk', 'order-flow', 'options', 'liquidity', 'portfolio', 'system']) {
      await expect(page.locator(`.navitem[data-ws="${ws}"]`)).toHaveCount(1);
    }
    await expect(page.locator('#subnav .wtitle')).toContainText('OPTIONS');
    await expect(page.locator('.vtab', { hasText: 'Heatmap' })).toBeVisible();
    // #6: canonical market session shown in the header, distinct from feed liveness. The session
    // is Schwab's /markets answer, which only the daemon asks for: with no daemon here, the
    // console holds no answer and the header says so.
    await expect(page.locator('#hSession')).toHaveText('UNKNOWN');
    await expect(page.locator('#hSession')).toHaveClass(/unknown/);
  });

  // induced: the real surface cut to one cell, the strike at the price in the front expiry,
  // holding `value` (the program's surface of a ticker)
  function oneCell(value, seq, tk) {
    return Object.assign({}, SURFACE, tk ? { ticker: tk, symbol: tk } : {}, {
      strikes: [K], expirations: SURFACE.expirations.slice(0, 1),
      cells: [Object.assign(cut(CELL_K, 1), { gex: [value] })], surface_seq: seq });
  }

  test('new levels reach the heatmap on the page\'s socket, with no read and no event of the page', async ({ page }) => {
    // Delivery, not rendering: the program sends the surface again when the levels change
    // (server._levels_changed), and the page asks for nothing
    panels.surface = oneCell(1000, 1);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$1.0K');
    const asked = sock.subscribes.length;
    panels.surface = oneCell(2000, 2);
    sock.changed('surface');
    await expect(cell).toHaveText('$2.0K', { timeout: 3000 });
    expect(sock.subscribes.length).toBe(asked);
  });

  test('a burst of pushes faster than the round trip converges the display live, not only once the pushes stop (2026-09-13 controlled reproduction)', async ({ page }) => {
    // the program's surface sent six times, 40 ms apart: each frame is drawn as it lands, and
    // the last one stands. The mid-burst read below is a single instantaneous DOM snapshot
    // (`textContent()`, no auto-retry) taken while frames are still arriving: it tells "frozen
    // through the whole burst" from "kept converging".
    panels.surface = oneCell(1000, 1);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$1.0K');   // the initial render
    let call = 1;
    for (let i = 0; i < 6; i++) {
      call += 1;
      panels.surface = oneCell(call * 1000, call);
      sock.changed('surface');
      if (i === 2) {
        await expect(cell).not.toHaveText('$1.0K');
        const midBurstText = await cell.textContent();
        expect(midBurstText, 'display must already be tracking updates mid-burst, not frozen at its starting value').not.toBe('$1.0K');
      }
      await page.waitForTimeout(40);
    }
    await expect(cell).toHaveText('$' + call.toFixed(1) + 'K');
    const finalText = await cell.textContent();
    expect(finalText).toBe('$' + call.toFixed(1) + 'K');
  });

  test('a surface still on its way for an abandoned ticker does not block the newly selected one, and is never drawn under it', async ({ page }) => {
    // the program's side: SPY's surface not sent until the test says; AAPL's at once on its
    // subscribe. SPY's, sent after the switch, is a frame of a ticker the page has left.
    let sendSpy = null;
    await page.routeWebSocket(/\/ws$/, (ws) => {
      ws.onMessage((m) => {
        const req = JSON.parse(String(m));
        if (req.op !== 'subscribe') return;
        ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
        if (!req.panels || !req.panels.surface) return;
        if (req.ticker === 'SPY') sendSpy = () => ws.send(panelFrame('surface', 'SPY', oneCell(1000, 1, 'SPY')));
        else ws.send(panelFrame('surface', req.ticker, oneCell(9000, 1, req.ticker)));
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => sendSpy !== null).toBe(true);   // SPY's surface is asked, not yet sent
    await page.locator('#symInput').fill('AAPL');
    await page.locator('#symInput').press('Enter');
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$9.0K', { timeout: 3000 });
    sendSpy();                                                 // SPY's, late
    await page.waitForTimeout(200);
    await expect(cell).toHaveText('$9.0K');
  });

  test('Strike Detail keeps following the workspace expiry filter after a selection, never reverting on refresh (2026-09-13, independent-review finding)', async ({ page }) => {
    // select under Sept 18, filter to Sept 25, then a new chain: the panel asked 18 -> 25 -> 25.
    // (a selected expiry comes from the list the socket sends on each subscribe: the real one)
    const E3 = EXPIRIES[2];                                 // 2026-11-18
    const asked = () => sock.subscribes[sock.subscribes.length - 1].panels['chain:detail'];
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(([k, e]) => window.EdShell.setStrike(k, e), [K, E2]);
    await expect.poll(asked).toEqual({ expiry: E2 });
    await expect(page.locator('#sdCtx')).toContainText(E2.slice(5));
    await page.evaluate((e) => window.EdShell.setExpiry(e), E3);
    await expect.poll(asked).toEqual({ expiry: E3 });
    await expect(page.locator('#sdCtx')).toContainText(E3.slice(5));
    const subscribes = sock.subscribes.length;
    sock.changed('chain');                                  // the program's next chain
    await expect(page.locator('#sdCtx')).toContainText(E3.slice(5));
    expect(sock.subscribes.length).toBe(subscribes);
    expect(asked()).toEqual({ expiry: E3 });
  });

  test('an unavailable heatmap surface is not resurrected by a later theme/expiry/scope event (2026-09-13, independent-review finding)', async ({ page }) => {
    // Independent-review finding (2026-09-13), REPRODUCED: _lastSurface used to survive an
    // unavailable render untouched, so a LATER presentation-only event (ed:theme here; also
    // ed:expiry/ed:scope) reused it as if still current -- repainting the stale AVAILABLE data.
    const requests = watchRequests(page);
    panels.surface = oneCell(1000, 1);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$1.0K');

    panels.surface = { available: false, reason: 'not currently active for this symbol' };
    sock.changed('surface');
    await expect(page.locator('#heatBody .placeholder .big')).toHaveText('Gamma surface unavailable');

    // a theme toggle must not repaint the old cell: one non-retrying DOM snapshot
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    await requests.settled();   // the theme change's work, and any read it made, has run
    const html = await page.locator('#heatBody').innerHTML();
    expect(html).not.toContain('$1.0K');
    expect(html).toContain('Gamma surface unavailable');
  });

  // A panel the program could not produce says the program's words (live_ui `failed`). Induced
  // condition: the panel's producer raises. (The order-flow book's is in
  // console-order-flow-heatmap.spec.js.)
  const PANELS = [
    { name: 'the tape', host: '#ofBody', kind: 'tape' },
    { name: 'the flow panel', host: '#flowBody', kind: 'contract', sub: 'flow', contract: CALL_K.symbol },
  ];
  for (const p of PANELS) {
    test(`${p.name}: a panel the program could not produce says the program's words`, async ({ page }) => {
      const words = 'the program could not produce this panel: OSError: ' + p.kind + ' read failed';
      panels[p.kind] = { failed: words };
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#hPx')).not.toHaveText('CHOOSE A SYMBOL');
      if (p.sub) await page.evaluate((sub) => window.EdShell.setSubview(sub), p.sub);
      if (p.contract) await page.evaluate((c) => window.EdFlow.select(c), p.contract);
      await expect(page.locator(p.host)).toContainText(words);
    });
  }

  // A chain panel the program could not produce after a good one says the program's words and
  // leaves no as-of badge from the last chain. Induced condition: the chain producer raises
  // (live_ui `failed`) after a chain marked complete was drawn.
  const CHAINED = [
    { name: 'Strike Detail', host: '#sdBody', badge: '#sdSrc' },
    { name: 'the chain', host: '#chainBody', badge: '#chSrc', sub: 'chain' },
    { name: 'Structures', host: '#stBody', sub: 'structures' },
  ];
  for (const p of CHAINED) {
    test(`${p.name}: a chain the program could not produce after a good one says why and leaves no badge`, async ({ page }) => {
      const words = 'the program could not produce this panel: RuntimeError: chain lock timed out';
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      if (p.sub) await page.evaluate((sub) => window.EdShell.setSubview(sub), p.sub);
      else await page.evaluate(([k, e]) => window.EdShell.setStrike(k, e), [K, E1]);
      if (p.badge) await expect(page.locator(p.badge)).not.toBeEmpty();
      else await expect(page.locator(p.host)).not.toHaveText('-');
      panels.chain = { failed: words };
      sock.changed('chain');
      await expect(page.locator(p.host)).toContainText(words);
      if (p.badge) await expect(page.locator(p.badge)).toBeEmpty();
    });
  }

  test('GEX by strike: a panel the program could not produce after a good one says why and leaves no badge', async ({ page }) => {
    const words = 'the program could not produce this panel: RuntimeError: chain lock timed out';
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#gbsSrc')).not.toBeEmpty();
    panels.strikes = { failed: words };
    sock.changed('strikes');
    await expect(page.locator('#gbsBody')).toContainText(words);
    await expect(page.locator('#gbsSrc')).toBeEmpty();
    await expect(page.locator('#klFlip')).toHaveText('243.91');   // the other panels keep theirs
  });

  test('GEX by strike after a ticker switch: "-" until the new ticker\'s rows, the new ticker\'s window', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(STRIKES.today.all.length);
    panels.strikes = (key) => (key === 'QQQ' ? undefined : STRIKES);   // QQQ's not sent yet
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect(page.locator('#gbsBody')).toHaveText('-');
    await expect(page.locator('#gbsSrc')).toBeEmpty();
    const asked = sock.subscribes[sock.subscribes.length - 1];
    expect(asked.ticker).toBe('QQQ');
    expect(asked.panels['strikes:gbs']).toEqual({ scope: 'auto', centre: null, shift: 0 });
  });

  test('Key Levels: a panel the program could not produce after a stale one keeps none of its tooltip or colour', async ({ page }) => {
    // Induced condition: the first panel is marked stale with a reason (served status labels);
    // then the program's producer raises, and the socket sends its words (live_ui `failed`).
    const words = 'the program could not produce this panel: RuntimeError: chain lock timed out';
    panels.terrain = Object.assign({}, TERRAIN, { levels_state: 'STALE', levels_mark: 'STALE',
      levels_stale_reason: 'chain 12m old', levels_mark_reason: 'chain 12m old' });
    await socketWith(page, [priceRow('SPY', 601.23)]);                    // the pushed price
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSrc')).toHaveAttribute('title', 'chain 12m old');
    await expect(page.locator('#klSpot')).toHaveText('601.23');
    panels.terrain = { failed: words };
    sock.changed('terrain');
    await expect(page.locator('#klSrc')).toHaveText(words);
    await expect(page.locator('#klSrc')).toHaveAttribute('title', '');
    for (const id of ['#klSrc', '#klNet', '#klRegime']) {
      expect(await page.locator(id).evaluate((el) => el.style.color), id).toBe('');
    }
    await expect(page.locator('#klBody')).toHaveClass(/recede/);
    await expect(page.locator('#klSpot')).toHaveText('601.23');            // the price row's, not terrain's
  });

  test('Right Now says when the page cannot draw its answers, never "no console serving"', async ({ page }) => {
    // Induced condition: the per-strike answer (this file's STRIKES) without its `views`, so
    // drawing the migration section raises a TypeError after every endpoint has answered.
    panels.strikes = Object.assign({}, STRIKES, { views: undefined });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hPx')).not.toHaveText('CHOOSE A SYMBOL');
    const reported = page.waitForEvent('pageerror', (e) => /TypeError/.test(String(e)));
    await page.evaluate(() => { window.EdShell.setWorkspace('trade-desk'); window.EdShell.setSubview('right-now'); });
    await expect(page.locator('#tdBody')).toContainText('the page could not draw the answer of Right Now');
    await reported;
  });

  test('a surface the program could not produce says the program\'s words; the other panels keep theirs', async ({ page }) => {
    // Induced condition: the program's surface producer raised (live_ui `failed`), after a
    // surface it could produce was drawn.
    const words = 'the program could not produce this panel: RuntimeError: chain lock timed out';
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    panels.surface = { failed: words };
    sock.changed('surface');
    await expect(page.locator('#heatBody')).toContainText(words);
    await expect(page.locator('#heatBody .hcell')).toHaveCount(0);
    await expect(page.locator('#klFlip')).toHaveText('243.91');
  });

  test('a surface the page fails to draw says so, and the error is reported', async ({ page }) => {
    // Induced condition: the program sends a surface that has no `view`, so drawing it raises a
    // TypeError after it arrived.
    panels.surface = { available: true, ticker: 'SPY' };
    const reported = page.waitForEvent('pageerror', (e) => /TypeError/.test(String(e)));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody')).toContainText('the page could not draw the surface the program sent');
    await reported;                                       // and the error itself is reported
    await expect(page.locator('#heatBody .hcell')).toHaveCount(0);
  });

  test('a ticker switched on another view leaves no old surface for a theme change to redraw', async ({ page }) => {
    // SPY's captured surface is drawn; AAPL's is never sent.
    panels.surface = (key) => (key === 'SPY' ? realSpySurface() : undefined);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await page.locator('#viewbar .vtab[data-view="chart"]').click();
    await page.evaluate(() => window.EdShell.setTicker('AAPL'));
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    expect(await page.evaluate(() => window.EdShell.getState().selStrike)).toBeNull();   // no SPY strike chosen for AAPL
    await expect(page.locator('#heatBody .hcell')).toHaveCount(0);
  });

  test('a theme change while a new ticker\'s surface is on its way never redraws the old ticker\'s grid', async ({ page }) => {
    // SPY's captured surface is drawn; AAPL's is never sent.
    panels.surface = (key) => (key === 'SPY' ? realSpySurface() : undefined);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await page.locator('#symInput').fill('AAPL');
    await page.locator('#symInput').press('Enter');
    await page.evaluate(() => window.EdShell.setTheme('dark'));
    await expect(page.locator('#heatBody')).toHaveText('-');
    await expect(page.locator('.hcell')).toHaveCount(0);                 // none of SPY's cells under AAPL
  });

  test('each column streaming status is the served stream_by_expiry, never a page-side verdict', async ({ page }) => {
    // The server serves each column's state from its cells' stream states (server.py
    // _stream_state_of); the tooltip only picks the words.
    const surf = surfaceWithContracts(3, 3);
    const e = surf.expirations.map((x) => x.expiry);
    surf.front_expiry = e[0];
    surf.stream_by_expiry = { [e[0]]: 'partial', [e[1]]: 'pending', [e[2]]: 'stale' };
    panels.surface = surf;
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const col = page.locator('.heat thead th.hexp');
    await expect(col).toHaveCount(3);
    await expect(col.nth(0)).toHaveAttribute('title', 'partly streaming');
    await expect(col.nth(1)).toHaveAttribute('title', 'streaming requested');
    await expect(col.nth(2)).toHaveAttribute('title', 'stopped streaming');
  });

  test('each scope reads its window from the server and draws the columns it serves', async ({ page }) => {
    // The server picks the window for the scope (server.py _surface_view;
    // tests/test_heatmap_window_v1.py); the page asks with the scope and draws what is served.
    const byScope = { auto: surfaceWithContracts(1, 3), wider: surfaceWithContracts(2, 3), all: surfaceWithContracts(16, 3) };
    const asked = [];
    panels.surface = (key, params) => { asked.push(params.scope); return byScope[params.scope]; };
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    for (const scope of ['auto', 'wider', 'all']) {
      await page.evaluate((s) => window.EdShell.setScope(s), scope);
      await expect.poll(() => asked[asked.length - 1]).toBe(scope);
      await expect(page.locator('#heatBody .heat thead .hexp')).toHaveCount(byScope[scope].expirations.length);
    }
  });

  test('a levels push re-reads the scope on screen, never Auto', async ({ page }) => {
    // the program sends the surface again for the window the page last asked
    const asked = [];
    let value = 1000;
    panels.surface = (key, params) => {
      asked.push(params.scope);
      return Object.assign(oneCell(value, asked.length), { view: view({ scope: params.scope }) });
    };
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => asked[0]).toBe('auto');
    await page.locator('#scopeCtl .scbtn', { hasText: 'Wider' }).click();
    await expect.poll(() => asked[asked.length - 1]).toBe('wider');
    const fromPush = asked.length;
    value = 2000;                                      // the push's publication has a new value
    sock.changed('surface');                           // after the scope switch
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$2.0K', { timeout: 5000 });   // the push's surface landed
    expect(asked.slice(fromPush)).toEqual(asked.slice(fromPush).map(() => 'wider'));
    expect(asked.length).toBeGreaterThan(fromPush);
    expect(await page.evaluate(() => window.EdShell.getScope())).toBe('wider');
  });

  test('GEX-by-strike displays each row\'s own session volume, not just signed GEX$ (RC-UI-2 finding #5a)', async ({ page }) => {
    // Independent-review finding (2026-09-12), REPRODUCED: "GEX-by-strike does not display its
    // row's volume field" -- terrain_engine._per_strike_rows' own shape is
    // [strike, net_gex_1pct$, session_volume]; the THIRD element was read into _lastGbs but
    // never rendered anywhere. STRIKES.today.all above already carries real volume numbers
    // (1200/5400/900) -- this proves they actually reach the DOM now.
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // AMZN's real rows: 32,975 contracts traded at 270, 2,260 at 257.5
    const rowK = page.locator('.gbs-row[data-strike="' + K + '"]');
    await expect(rowK.locator('.gbs-vol')).toHaveText('33.0K');
    await expect(rowK).toHaveAttribute('data-volume', '32975');
    const rowLow = page.locator('.gbs-row[data-strike="257.5"]');
    await expect(rowLow.locator('.gbs-vol')).toHaveText('2.3K');
  });

  test('Strike Detail redraws on the program\'s next chain, not just on a new strike selection', async ({ page }) => {
    // induced: the real chain with the volume of the call at the price changed
    const withCallVolume = (vol) => Object.assign({}, CHAIN,
      { contracts: CHAIN.contracts.map((c) => (c === CALL_K ? Object.assign({}, c, { totalVolume: vol }) : c)) });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator(CELL).click();
    await expect(page.locator('#sdCtx')).toContainText('270');
    const callVolCell = page.locator('.sd tbody tr').first().locator('td').nth(2);   // Type, OI, Vol
    await expect(callVolCell).toHaveText('13152');          // Schwab's totalVolume of that call
    const subscribes = sock.subscribes.length;
    panels.chain = chainAt(withCallVolume(999999));
    sock.changed('chain');                                  // the program prices the next chain
    await expect(callVolCell).toHaveText('999999');
    expect(sock.subscribes.length).toBe(subscribes);         // the page asked for nothing
  });

  test('Strike Detail\'s Net GEX$ is this expiry\'s value from the chain panel, never GEX-by-Strike\'s all-expiry total', async ({ page }) => {
    // One value, one producer (2026-09-27): the Net row sits beside ONE expiry's contracts, so it
    // shows that expiry's net GEX at the strike -- the heatmap's own cell, served in the same
    // chain panel. It used to read GEX-by-Strike's rows (every expiry summed).
    // AMZN's real answers: 270's net GEX in the front expiry is $51.7M (the chain panel's
    // net_gex_by_strike, the heatmap's own cell); every expiry summed it is $156.8M (the strikes panel)
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator(CELL).click();
    await expect(page.locator('#sdCtx')).toContainText('270');
    await expect(page.locator('#sdBody .sd-net td').nth(4)).toHaveText('$51.7M');   // Net, OI, Vol, Gamma, GEX$
  });

  test('heatmap renders canonical cells verbatim (value == formatted payload; sign -> colour)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cellPos = page.locator(CELL);       // 270 in the front expiry: 51,735,223.55
    const cellNeg = page.locator(CELL_NEG);   // 262.5 on 2026-11-20: -3,907,027.65
    await expect(cellPos).toHaveText('$51.7M');    // E: formatting-only of the served value
    await expect(cellNeg).toHaveText('-$3.9M');
    // D: positive -> green-dominant fill, negative -> red-dominant fill (no inversion)
    const rgbOf = (s) => { const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(s); return [+m[1], +m[2], +m[3]]; };
    const bgPos = rgbOf(await cellPos.evaluate((el) => getComputedStyle(el).backgroundColor));
    const bgNeg = rgbOf(await cellNeg.evaluate((el) => getComputedStyle(el).backgroundColor));
    expect(bgPos[1]).toBeGreaterThan(bgPos[0]);   // green channel dominant
    expect(bgNeg[0]).toBeGreaterThan(bgNeg[1]);   // red channel dominant
    // the spot row is the 270 strike (nearest 269.425)
    await expect(page.locator('tr.spotrow .hstrike')).toHaveText('270');
    // The header never reads the word LIVE without per-cell confirmation: no contract of this
    // capture is streaming, and the server's coverage says so (0% STREAMING).
    await expect(page.locator('.heat-banner')).toHaveCount(0);
    await expect(page.locator('#heatScope')).toContainText(SURFACE.view.coverage.label);
    // #7: shade legend present — vertical magnitude legend at the heatmap's right edge
    await expect(page.locator('.heat-vlegend .bar')).toBeVisible();
    // C: nearest-expiry (front) column emphasised
    expect(await page.locator('.heat .hexp.col-front').count()).toBeGreaterThan(0);
    // A: clicking a heatmap cell syncs the selected strike across panels
    await page.locator(CELL).click();
    await expect(page.locator('.hcell.sel-strike')).toHaveCount(EXPIRIES.length);    // every expiry's cell at 270
    await expect(page.locator('.gbs-row.gbs-sel[data-strike="' + K + '"]')).toHaveCount(1);  // GEX-by-strike synced
    await expect(page.locator('#sdCtx')).toContainText('270');                       // Strike Detail loaded
  });

  test('always-live heatmap mandate: a confirmed-live cell renders its numeric value with no snapshot flag', async ({ page }) => {
    panels.surface = surfaceWithStreamState([{ call: 'live', put: 'live' }]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'live');
    await expect(cell).not.toHaveClass(/state-partial|state-stale|state-unavailable/);
  });

  test('always-live heatmap mandate: a stale cell (desired but not fresh) still shows its real value, honestly labelled as a snapshot -- never blanked', async ({ page }) => {
    // Operator directive (2026-09-15), FINAL: "Never blank valid data... keep the latest
    // valid timestamped GEX displayed when a contract is not actively updating."
    panels.surface = surfaceWithStreamState([{ call: 'stale', put: 'stale' }]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'stale');
    await expect(cell).toHaveAttribute('data-gex', '12345');
    await expect(cell).toHaveClass(/state-stale/);
    await expect(cell).toHaveAttribute('title', 'this cell has stopped streaming');
    // never mislabelled as live
    const cls = await cell.getAttribute('class');
    expect(cls).not.toMatch(/state-live/);
  });

  test('always-live heatmap mandate: an unavailable/not-yet-confirmed cell still shows its real value, honestly labelled, never dashed', async ({ page }) => {
    panels.surface = surfaceWithStreamState([{ call: 'unavailable', put: 'unavailable' }]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'unavailable');
    await expect(cell).toHaveAttribute('title', 'not streaming');
  });

  test('a cell with no value draws "-", whatever its stream state', async ({ page }) => {
    const surf = surfaceWithStreamState([{ call: 'live', put: 'live' }]);
    surf.cells[0].gex = [null];
    panels.surface = surf;
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('-');
    await expect(cell).toHaveAttribute('data-cell-state', 'live');   // stream state is beside the value
  });

  test('always-live heatmap mandate: a partial cell (one leg live, one not) shows the same value as fully live, visibly flagged distinct from fully live', async ({ page }) => {
    panels.surface = surfaceWithStreamState([{ call: 'live', put: 'unavailable' }]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
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
    panels.surface = () => Object.assign(
      surfaceWithStreamState([{ call: live ? 'live' : 'stale', put: live ? 'live' : 'stale' }]), { surface_seq: seq });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const cell = page.locator(CELL);
    await expect(cell).toHaveText('$12.3K');
    await expect(cell).toHaveAttribute('data-cell-state', 'live');

    live = false; seq = 2;   // the stream goes quiet -- no reload, no navigation, just the next push
    sock.changed('surface');
    await expect(cell).toHaveAttribute('data-cell-state', 'stale');
    await expect(cell).toHaveText('$12.3K');   // the same valid value -- never blanked
    await expect(cell).toHaveAttribute('title', 'this cell has stopped streaming');   // relabelled, not kept as live
  });

  test('a surface that is not live is shown as absent -- never as a reference', async ({ page }) => {
    // Operator rule 2026-09-23 (no fallbacks): the server no longer serves a banked morning chain
    // in place of the live surface; the heatmap says it is unavailable and why.
    panels.surface = { ticker: 'SPY', available: false, source: 'unavailable',
      warming: false, requested: true, reason: 'no live gamma surface for this ticker yet' };
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody .placeholder .big')).toContainText('Gamma surface unavailable');
    await expect(page.locator('#heatBody')).not.toContainText('REFERENCE');
    await expect(page.locator('#heatBody')).not.toContainText('banked');
  });

  test('persists workspace/view across reload (D: UI state, not market truth)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();       // restored from localStorage
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
  });

  test('key levels rail reflects the terrain panel', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klFlip')).toHaveText('243.91');
    // AMZN's real levels: flip 243.9135, both walls at 270, net GEX at the price 937,341,251
    await expect(page.locator('#klCall')).toHaveText('270.00');
    await expect(page.locator('#klPut')).toHaveText('270.00');
    await expect(page.locator('#klNet')).toHaveText('$937.3M');
    await expect(page.locator('#klRegime')).toContainText('Long γ');
    // a label with no served number is not on the rail
    await expect(page.locator('#klBody')).not.toContainText('NOT PROVEN');
    await expect(page.locator('#klAbs0')).toHaveCount(0);
    // PCR: with no expiry selected, the whole book's put/call OI ratio as served (pcr_all), its
    // scope disclosed -- the page no longer picks an expiry itself
    await expect(page.locator('#klPcr')).toHaveText('0.78');       // pcr_all 0.7843
    await expect(page.locator('#klPcrScope')).toContainText('OI');
    await expect(page.locator('#klPcrScope')).toContainText('all exp');
    // and the put/call VOLUME ratio (today's trading) on its own row, same scope
    await expect(page.locator('#klPcrVol')).toHaveText('0.30');    // pcr_volume_all 0.2952
    await expect(page.locator('#klPcrVolScope')).toContainText('volume');
  });

  test('a level built from a price that has stopped stays, and the rail says OFFLINE', async ({ page }) => {
    panels.terrain = Object.assign({}, TERRAIN, {
      levels_mark: 'OFFLINE',
      levels_mark_reason: 'Schwab LEVELONE_EQUITIES feed down during RTH' });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klCall')).toHaveText('270.00');
    await expect(page.locator('#klSrc')).toHaveText(TERRAIN.levels_time_ct + ' · OFFLINE · ' + TERRAIN.levels_age_text);
    await expect(page.locator('#klSrc')).toHaveAttribute('title', 'Schwab LEVELONE_EQUITIES feed down during RTH');
    await expect(page.locator('#klBody')).not.toHaveClass(/recede/);
  });

  test('key levels rail keeps the chain time when the price has stopped', async ({ page }) => {
    const CHAIN_TIME = 'Fri 09/25 06:59 PM CT';
    panels.terrain = Object.assign({}, TERRAIN, {
      levels_age_text: '4s', levels_time_ct: CHAIN_TIME,
      levels_mark: 'OFFLINE', levels_mark_reason: 'Schwab LEVELONE_EQUITIES feed down during RTH' });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klCall')).toHaveText('270.00');
    await expect(page.locator('#klSrc')).toHaveText(CHAIN_TIME + ' · OFFLINE · 4s');
    await expect(page.locator('#klSrc')).toHaveAttribute('title', 'Schwab LEVELONE_EQUITIES feed down during RTH');
  });

  test('key levels rail after its own option close reads CLOSE with the close values\' time and age (the route\'s own answer)', async ({ page }) => {
    // the terrain panel for SPY's 2026-10-22 close publication, read at 18:00 ET (tests/test_level_crosses_wire.py)
    const CLOSED = require(path.join(__dirname, '..', 'fixtures', 'real_spy_terrain_at_a_stopped_price_2026_10_22.json'));
    panels.terrain = CLOSED;
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSrc')).toHaveText(CLOSED.levels_time_ct + ' · CLOSE · ' + CLOSED.levels_age_text);
    await expect(page.locator('#klSrc')).not.toContainText('live');
  });

  test('PCR: the selected expiry re-scopes the ratio; an expiry the chain has no ratio for shows none', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // AMZN's real ratios: 0.7843 for every expiry, 0.4541 on 2026-11-16, 0.7317 on 2026-11-13
    await expect(page.locator('#klPcr')).toHaveText('0.78');
    await expect(page.locator('#klPcrScope')).toContainText('all exp');
    await page.locator('#expSel').selectOption(E2);
    await expect(page.locator('#klPcr')).toHaveText('0.45');
    await expect(page.locator('#klPcrScope')).toContainText(E2);
    await page.locator('#expSel').selectOption(E1);
    await expect(page.locator('#klPcr')).toHaveText('0.73');
  });

  test('PCR: a ticker whose terrain carries no ratio paints none, never a number', async ({ page }) => {
    panels.terrain = Object.assign({}, TERRAIN, { pcr_by_expiry: {}, pcr_all: null });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klFlip')).toHaveText('243.91');
    await expect(page.locator('#klPcr')).toHaveText('-');
  });

  // A real 116-strike x 16-expiration surface (SPY, captured 2026-09-10 06:35 CDT; 2026-09-09
  // expired), served whole as the All window (a stand-in for the server's window, which
  // tests/test_heatmap_window_v1.py proves): every cell is drawn at a legible size, the grid
  // scrolls rather than shrinks, and the expired column is labelled.
  test('REAL-DATA: the 116x16 All window is drawn whole, legible, EXPIRED labelled; the page asks for the columns it fits', async ({ page }) => {
    const stamped = realSpySurface();
    expect(stamped.strikes.length).toBe(116); expect(stamped.expirations.length).toBe(16);
    const asked = [];
    panels.surface = (key, params) => { asked.push(params); return stamped; };
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const rows = page.locator('#heatBody .heat tbody tr');
    const cols = page.locator('#heatBody .heat thead .hexp');
    await expect(rows).toHaveCount(116);
    const fits = asked[0].cols;
    expect(fits).toBeGreaterThanOrEqual(3); expect(fits).toBeLessThanOrEqual(11);
    // highest strike at the top, the price row marked
    await expect(rows.first().locator('.hstrike')).toHaveText(String(stamped.strikes[stamped.strikes.length - 1]));
    await expect(page.locator('#heatBody tr.spotrow .hstrike')).toHaveText('764');
    const cellFont = await page.locator('#heatBody .hcell').first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(cellFont).toBeGreaterThanOrEqual(13);
    await expect(page.locator('#heatBody')).not.toContainText('REFERENCE');   // no reference surface exists
    await expect(cols).toHaveCount(16);
    await expect(page.locator('#heatBody .heat thead .hexp.expired')).toHaveCount(1);
    await expect(page.locator('#heatBody .heat thead .hexp.expired .dte')).toHaveText('EXPIRED');
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
  });

  test('workspace switching + editable watchlist foundation', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
    // add a symbol via the shell API (the console's watchlist route: the daemon keeps the list)
    await page.evaluate(() => window.EdShell.addSymbol('AMD'));
    await expect(page.locator('.wl-row .wl-sym', { hasText: 'AMD' })).toHaveCount(1);
  });

  test('chart view: Price + GEX Profile and Dot Map render from canonical inputs', async ({ page }) => {
    // The chart's spot is the header's price row (audit of #280 removed the terrain's copy,
    // a second producer): the daemon's price socket delivers it.
    await socketWith(page, [priceRow('SPY', 583.41, { trade_time_ct: '14:00:01 CT' })]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#view-chart')).toHaveClass(/on/);
    // profile mode (default), on the shared chart: the bars, the signed profile, the flip level
    // line and the live price line
    const cs = async () => (await page.evaluate(() => window.EdGammaChart.state())) || { profile: {}, levels: [] };
    await expect(page.locator('#chartBody .gchart-plot canvas').first()).toBeVisible();
    await expect.poll(async () => (await cs()).bars).toBeGreaterThan(0);
    await expect.poll(async () => (await cs()).profile.rows).toBeGreaterThan(0);
    await expect.poll(async () => (await cs()).profile.style).toBe('bars');
    await expect.poll(async () => (await cs()).livePrice).toBe(583.41);
    await expect(page.locator('#chartBody .gchart-head')).toContainText('spot 583.41');
    await expect(page.locator('#chartBody .gchart-head')).toContainText('last trade 14:00:01 CT');
    await expect.poll(async () => (await cs()).liveTitle).toBe('LAST · last trade 14:00:01 CT');
    await expect(page.locator('#hFeed')).toHaveText('OFFLINE', { timeout: 6000 });
    await expect(page.locator('#chartBody .gchart-head')).toContainText('last trade 14:00:01 CT');
    await expect.poll(async () => (await cs()).liveTitle).toBe('LAST · last trade 14:00:01 CT');
    await expect.poll(async () => (await cs()).levels).toContain('flip');
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.screenshot({ path: require('path').join('test-results', 'console-gamma-chart-2560x1440.png') });
    // dot map mode: per-strike dots
    await page.locator('.cmode[data-cmode="dotmap"]').click();
    await expect.poll(async () => (await cs()).profile.style).toBe('dots');
    await expect(page.locator('#chartModes .cmode[data-cmode="dotmap"]')).toHaveClass(/on/);
  });

  test('header never paints a quote from a poll: no push -> -, not a fallback', async ({ page }) => {
    // the price and the session label come only from the program's push
    await page.routeWebSocket(/\/ws$/, (ws) => ws.close());          // the daemon is down
    await holdClock(page);   // the page's timers run when the test moves its time
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hPx')).toHaveText('-');
    await expect(page.locator('#hFeed')).toHaveText(/WAITING|OFFLINE/);
    await page.clock.runFor(3500);   // past the 3 s silence limit and every reconnect due in it
    await expect(page.locator('#hPx')).toHaveText('-');
    // the push is down, so no session was received: "-", and why
    await expect(page.locator('#hSession')).toHaveText('-');
    await expect(page.locator('#hSession')).toHaveAttribute('title', 'session unknown: the console push is down');
  });

  test('header paints the daemon price row the moment it arrives', async ({ page }) => {
    // Stage 1 of the live-UI architecture: the capture daemon pushes the finished row
    // (live_price_rows.price_row) straight to the page; the console is not in the path.
    await socketWith(page, [priceRow('SPY', 601.23, { bid: 601.20, ask: 601.25, chg_pct: 0.5,
      chg_pct_regular: 0.4 })]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hPx')).toHaveText('601.23');
    await expect(page.locator('#hFeed')).toContainText('LIVE');
    await expect(page.locator('#hBidAsk')).toHaveText('601.20 × 601.25');
    // Schwab's two change percents, each under its own label
    await expect(page.locator('#hChgReg')).toHaveText('REG +0.40%');
    await expect(page.locator('#hChg')).toHaveText('EXT +0.50%');
  });

  test('before the session the regular-session percent reads absent, the extended one live', async ({ page }) => {
    await socketWith(page, [priceRow('SPY', 601.23, { chg_pct: -0.495313, chg_pct_regular: null })]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hChg')).toHaveText('EXT -0.50%');
    await expect(page.locator('#hChgReg')).toHaveText('REG -');
  });

  test('a price that stops arriving stays, and the chip says OFFLINE', async ({ page }) => {
    await socketWith(page, [priceRow('SPY', 601.23, { trade_time_ct: '14:00:01 CT', trade_age_text: '4s',
      quote_time_ct: '14:00:02 CT' })]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hPx')).toHaveText('601.23');
    await expect(page.locator('#hAge')).toHaveText('last trade 14:00:01 CT · 4s');
    await expect(page.locator('#hBidAsk')).toHaveAttribute('title', 'quote 14:00:02 CT');
    await expect(page.locator('#klSpot')).toHaveText('601.23');
    await expect(page.locator('#klSpot')).toHaveAttribute('title', 'last trade 14:00:01 CT · 4s');
    await expect(page.locator('#hFeed')).toHaveText('OFFLINE', { timeout: 6000 });
    await expect(page.locator('#hPx')).toHaveText('601.23');
    await expect(page.locator('#hAge')).toHaveText('last trade 14:00:01 CT');        // the 4s age is not the age now
    await expect(page.locator('#klSpot')).toHaveText('601.23');
    await expect(page.locator('#klSpot')).toHaveAttribute('title', 'OFFLINE · last trade 14:00:01 CT');
    expect(await page.locator('#klSpot').evaluate((el) => el.style.color)).toBe('var(--ed-stale)');
  });

  test('a price whose market is not trading reads NOT LIVE in the header and on Key Levels\' Spot', async ({ page }) => {
    await socketWith(page, [priceRow('SPY', 601.23, { trade_time_ct: '14:00:01 CT', trade_age_text: '4s',
      feed_live: false, feed_label: 'NOT LIVE', outage: "outside Schwab's market hours" })]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hFeed')).toHaveText('NOT LIVE');
    await expect(page.locator('#klSpot')).toHaveText('601.23');
    await expect(page.locator('#klSpot')).toHaveAttribute('title', "NOT LIVE: outside Schwab's market hours · last trade 14:00:01 CT · 4s");
  });

  test('a ticker switch clears the last ticker\'s price from the header and Key Levels\' Spot', async ({ page }) => {
    await socketWith(page, [priceRow('SPY', 601.23)]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSpot')).toHaveText('601.23');
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect(page.locator('#hPx')).toHaveText('-');
    await expect(page.locator('#klSpot')).toHaveText('-');
    await expect(page.locator('#hFeed')).toHaveText('WAITING');
  });

  test('a watchlist symbol paints from its own row on the same socket', async ({ page }) => {
    await socketWith(page, [priceRow('SPY', 601.23), priceRow('AMD', 150.5, { chg_pct: -1.25, trade_time_ct: '14:00:01 CT' })]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.EdShell.addSymbol('AMD'));
    await expect(page.locator('.wl-px[data-wlpx="AMD"]')).toHaveText('150.50');
    await expect(page.locator('.wl-px[data-wlpx="AMD"]')).toHaveAttribute('title', 'last trade 14:00:01 CT');
    await expect(page.locator('.wl-chg[data-wlchg="AMD"]')).toHaveText('-1.25%');
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
    await page.addInitScript(() => { localStorage.setItem('ed_theme', 'system'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');   // SYSTEM + OS light -> light
  });

  test('theme SYSTEM follows LIVE OS changes; explicit ignores them (A-F)', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => { localStorage.setItem('ed_theme', 'system'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');     // A: SYSTEM + OS dark -> dark
    const cell = page.locator(CELL);
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
    await expect(page.locator('.hcell.sel-strike')).toHaveCount(EXPIRIES.length);
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
    const cell = page.locator(CELL);
    const darkVal = (await cell.textContent()).trim();
    await cell.click();                                   // select the strike at the price
    await page.evaluate(() => window.EdShell.setTheme('light'));
    // D: the displayed dollar value is unchanged by theme
    await expect(cell).toHaveText(darkVal);
    // E: positive cell green-dominant, negative cell red-dominant in LIGHT (no inversion)
    const rgbOf = (s) => { const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(s); return [+m[1], +m[2], +m[3]]; };
    const posBg = rgbOf(await cell.evaluate((el) => getComputedStyle(el).backgroundColor));
    const negBg = rgbOf(await page.locator(CELL_NEG).evaluate((el) => getComputedStyle(el).backgroundColor));
    expect(posBg[1]).toBeGreaterThan(posBg[0]);   // green channel dominant
    expect(negBg[0]).toBeGreaterThan(negBg[1]);   // red channel dominant
    // F: the selected strike + ticker survive the theme switch
    await expect(page.locator('.hcell.sel-strike')).toHaveCount(EXPIRIES.length);
    await expect(page.locator('#hSym')).toHaveText('SPY');
  });

  test('theme: ONE canonical owner (window.EdTheme) drives first-paint AND runtime resolution', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.addInitScript(() => { localStorage.setItem('ed_theme', 'system'); });
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

  test('#1 perf: a large heatmap surface renders without pathological jank', async ({ page }) => {
    const exps = [], strikes = [], cells = [];
    for (let i = 0; i < 20; i++) exps.push({ expiry: '2026-' + (i < 4 ? '09' : '12') + '-' + String(10 + (i % 20)).padStart(2, '0'), dte: i * 3 });
    for (let s = 0; s < 200; s++) strikes.push(500 + s);
    for (let si = 0; si < strikes.length; si++) {
      const row = [];
      for (let j = 0; j < exps.length; j++) row.push((j % 2 ? 1 : -1) * 1000 * ((si % 50) + 1));
      cells.push({ strike: strikes[si], gex: row });
    }
    await page.addInitScript(() => { localStorage.setItem('ed_scope', 'all'); });   // every strike on screen
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody .hcell').first()).toBeVisible();
    const big = { type: 'surface', ticker: 'SPY', available: true, source: 'terrain_live_cache', levels_state: 'LIVE',
      spot: 600, complete: false, expirations: exps, strikes, cells,
      view: view({ centre: 600, scope: 'all', max_abs: { gex: 50000 } }) };   // 200 strikes x 20 expiries
    // the page's own drawing of the frame as the socket delivers it: from the frame to the drawn table
    const before = await page.locator('#heatBody .hcell').count();
    const r = await page.evaluate(([n0, frame]) => new Promise((resolve) => {
      const t0 = performance.now();
      window.EdShell.emit('ed:panel', frame);
      (function wait() {
        const n = document.querySelectorAll('#heatBody .hcell').length;
        if (n > n0) resolve({ ms: performance.now() - t0, cells: n });
        else requestAnimationFrame(wait);
      })();
    }), [before, big]);
    const ms = r.ms;
    console.log('[#1 perf] heatmap load + render:', Math.round(ms), 'ms,', r.cells, 'cells');
    // no arbitrary tight SLA — a generous ceiling that only fails on pathological render behaviour
    expect(ms).toBeLessThan(1500);
  });

  test('#1 revision: DATA change rebuilds; STATUS change updates without rebuild (A-D)', async ({ page }) => {
    // induced: the real surface cut to one cell, with the named status and coverage
    const live = (age, stale) => Object.assign(oneCell(958600, 1), {
      levels_state: stale ? 'STALE' : 'LIVE', levels_age_text: age + 's', levels_stale_reason: stale ? 'chain overdue' : '',
      view: view({ coverage: served.cov }) });
    const served = { cov: { state: 'partial', label: '50% STREAMING', title: '1 of 2 cells streaming · 1 stale' } };
    served.s = live(3);
    panels.surface = () => served.s;
    const reload = async () => sock.changed('surface');
    const mark = () => page.evaluate(() => document.querySelector('#heatBody .hcell').setAttribute('data-marker', '1'));
    const marked = () => page.locator('#heatBody .hcell[data-marker="1"]');
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody .hcell').first()).toBeVisible();
    await expect(page.locator('#heatScope')).toHaveText('50% STREAMING');
    // A: same live DATA revision, coverage changes -> table preserved, the chip updates
    await mark();
    served.cov = { state: 'live', label: 'ALL STREAMING', title: 'all 2 cells streaming' };
    served.s = live(3); await reload();
    await expect(page.locator('#heatScope')).toHaveText('ALL STREAMING');
    await expect(page.locator('#heatScope')).toHaveClass(/cov-live/);
    await expect(marked()).toHaveCount(1);
    // D: stale flips with no cell change -> no rebuild, but the STALE banner appears (not frozen)
    await mark();
    served.s = live(3, true); await reload();
    await expect(page.locator('#heatBody .heat-banner')).toContainText('STALE');
    await expect(marked()).toHaveCount(1);
  });

  test('after its own option close the heatmap banner reads CLOSE with the close values\' time and age (the route\'s own answer)', async ({ page }) => {
    // the surface for SPY's 2026-10-22 close publication, read at 18:00 ET
    // (tests/test_level_crosses_wire.py)
    const CLOSED = require(path.join(__dirname, '..', 'fixtures', 'real_spy_gamma_surface_at_a_stopped_price_2026_10_22.json'));
    panels.surface = CLOSED;
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody .hcell').first()).toBeVisible();
    await expect(page.locator('#heatBody .heat-banner')).toContainText(
      'CLOSE · ' + CLOSED.levels_time_ct + ' · ' + CLOSED.levels_age_text);
    await expect(page.locator('#heatBody .heat-wrap')).toHaveClass(/recede/);
  });

  test('the next day after its close the heatmap banner reads STALE with the served reason (the route\'s own answer)', async ({ page }) => {
    // the surface for SPY's 2026-10-22 close publication after the next day's close,
    // 2026-10-23 16:30 ET, no chain fetched since (tests/test_level_crosses_wire.py)
    const STALE = require(path.join(__dirname, '..', 'fixtures', 'real_spy_gamma_surface_after_the_next_close_2026_10_23.json'));
    panels.surface = STALE;
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#heatBody .hcell').first()).toBeVisible();
    const banner = page.locator('#heatBody .heat-banner');
    await expect(banner).toContainText('STALE · ' + STALE.levels_time_ct + ' · ' + STALE.levels_age_text);
    await expect(banner).toHaveAttribute('title', STALE.levels_stale_reason);
  });

  test('#1.3 a warming (not yet live) surface shows LIVE SURFACE WARMING (never a final state)', async ({ page }) => {
    panels.surface = Object.assign({}, SURFACE, {
      available: false, source: 'unavailable', warming: true,
      requested: true, reason: 'no live gamma surface for this ticker yet',
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.heat-banner.warming')).toContainText('LIVE SURFACE WARMING');
  });

  test('switching ticker leaves a late chain frame of the old ticker undrawn', async ({ page }) => {
    // SPY's chain, sent before the program read the page's switch to QQQ, arrives after it
    // (QQQ's surface is never sent, so no new strike is selected): Strike Detail stays reset.
    panels.surface = (key) => (key === 'SPY' ? SURFACE : undefined);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator(CELL).click();
    await expect(page.locator('#sdCtx')).toContainText('270');
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect(page.locator('#sdBody')).toContainText('Select a strike/expiry');

    sock.frame('chain:detail', 'SPY', CHAIN);                                   // SPY's, late ...
    sock.frame('terrain:levels', 'QQQ', Object.assign({}, TERRAIN, { gamma_flip: 123.45 }));   // ... and QQQ's behind it
    await expect(page.locator('#klFlip')).toHaveText('123.45');
    await expect(page.locator('#sdBody')).toContainText('Select a strike/expiry');
    await expect(page.locator('.sd')).toHaveCount(0);
  });

  // Independent-review finding (2026-09-13), REPRODUCED, then a FOURTH review overturned the
  // first fix's own test: falling back to every column when the selected expiry is missing
  // avoided a blank grid, but silently SUBSTITUTED other expiries' data -- the operator's own
  // requirement is that this state reads UNAVAILABLE for the requested expiry, never a silent
  // substitution.
  // the server's own answer for a selected expiry the chain does not list (2026-11-14): no
  // columns, and the expiry named (server.py _surface_view `missing_expiry`)
  const MISSING_SURFACE = REAL.surface_missing_expiry;
  test('a selected expiry absent from the surface reads unavailable (no substitute expiries)', async ({ page }) => {
    panels.surface = (key, params) => (params.expiry === MISSING ? MISSING_SURFACE : SURFACE);
    sock = await pushExpiries(page, EXPIRIES.concat(MISSING), undefined, panels);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();

    // induced: the date is listed in the socket's expiries, and the surface does not have it
    await page.locator('#expSel').selectOption(MISSING);
    await expect(page.locator('#heatBody')).toContainText('Expiry ' + MISSING + ' unavailable');
    await expect(page.locator('#heatBody .hexp')).toHaveCount(0);   // NOT a silent substitute grid
  });

  test('recovers automatically once the requested expiry appears in a later surface poll', async ({ page }) => {
    let missing = MISSING_SURFACE;   // the chain lists no such expiry at first
    panels.surface = (key, params) => (params.expiry === MISSING ? missing : SURFACE);
    sock = await pushExpiries(page, EXPIRIES.concat(MISSING), undefined, panels);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();

    await page.locator('#expSel').selectOption(MISSING);
    await expect(page.locator('#heatBody')).toContainText('Expiry ' + MISSING + ' unavailable');

    // induced: the surface now includes the requested expiry: its one column, each real cell cut
    // to one column
    missing = Object.assign({}, SURFACE, {
      expirations: [{ expiry: MISSING, dte: 2, expired: false, front: false }],
      cells: SURFACE.cells.map((c) => Object.assign(cut(c, 1), { gex: [777000] })), surface_seq: 2,
    });
    sock.changed('surface');
    await expect(page.locator('#heatBody .hexp')).toHaveCount(1);
    await expect(page.locator('#heatBody')).not.toContainText('unavailable');
    await expect(page.locator('#heatBody .hexp .d')).toHaveText(MISSING.slice(5));
  });

  // ---------------------------------------------------------------------------
  // 2026-09-16 audit findings #3/#4/#5/#6 — bounded/consolidated live-UI architecture
  // ---------------------------------------------------------------------------

  test('audit #4: cold start hydrates every endpoint exactly once, never twice', async ({ page }) => {
    // The former design had TWO independent initial-hydration mechanisms (ed-core.js's own
    // ed:ticker/ed:view dispatch, and each view module's own bottom-of-file self-call) that
    // only avoided colliding because of a script-load-order coincidence. Now there is exactly
    // one (ed-core.js's dispatch, deferred to DOMContentLoaded) -- proven here by the asks for
    // panels owned by DIFFERENT modules across the initial render.
    const requests = watchRequests(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await expect(page.locator('#sdCtx')).toContainText('270');
    // Any accidental second trigger (a stray immediate self-call racing the deferred
    // dispatch) has made its ask by the time the page's work has all landed.
    await requests.settled();
    // each panel is asked for once: each subscribe that names it, names it alike
    const asksFor = (name) => sock.subscribes.map((s) => JSON.stringify(s.panels[name])).filter((a) => a !== undefined);
    expect(new Set(asksFor('tape')).size, 'tape must be asked for exactly once on cold start').toBe(1);
    expect(new Set(asksFor('chain:detail')).size, 'chain must be asked for exactly once on cold start').toBe(1);
  });

  // the program's levels sent again (server._levels_changed): the terrain, strikes and surface panels
  const levelsPush = () => { for (const kind of ['terrain', 'strikes', 'surface']) sock.changed(kind); };
  // the panels the page receives from here on, by name
  const watchPanels = (page) => page.evaluate(() => {
    window.__panels = [];
    document.addEventListener('ed:panel', (e) => window.__panels.push(e.detail.type));
  });
  const levelsLanded = (page) => page.evaluate(() => window.__panels.filter((t) => /^(terrain|strikes|surface)/.test(t)).length);

  test('one levels push sends only the levels\' panels again, not unrelated ones, and asks for nothing', async ({ page }) => {
    const requests = watchRequests(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    // clear the auto-selected strike and let the selection's own work finish
    await page.evaluate(() => window.EdShell.setStrike(null));
    await requests.settled();
    await watchPanels(page);
    const subscribesBefore = sock.subscribes.length;
    levelsPush();                     // lands after the baseline
    await expect.poll(() => levelsLanded(page)).toBeGreaterThan(0);
    await requests.settled();   // every request the push made has gone out
    expect(await page.evaluate(() => window.__panels.filter((t) => t === 'tape'))).toEqual([]);
    // the levels (Key Levels), the strikes (GEX by strike) and the surface (the heatmap) are the
    // program's to send on the socket: the push asks for nothing
    expect(sock.subscribes.length).toBe(subscribesBefore);
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(STRIKES.today.all.length);
  });

  test('one levels push with a strike selected asks for nothing', async ({ page }) => {
    const requests = watchRequests(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await expect(page.locator('#sdCtx')).toContainText('270');   // the auto-selected strike
    await requests.settled();   // cold-start hydration (including auto-select) has landed
    await watchPanels(page);
    const before = { subscribes: sock.subscribes.length };
    levelsPush();
    await expect.poll(() => levelsLanded(page)).toBeGreaterThan(0);
    await requests.settled();   // every request the push made has gone out and landed
    // the levels, the strikes, the surface and the chain are the program's to send on the
    // socket: the push asks for nothing there
    expect(sock.subscribes.length - before.subscribes).toBe(0);
    await expect(page.locator('.hcell').first()).toBeVisible();
    await expect(page.locator('#klFlip')).toHaveText('243.91');
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(STRIKES.today.all.length);
  });

  test('the Gamma Chart spot line moves with each price row (the header\'s price), not a terrain refetch', async ({ page }) => {
    // Was (2026-09-17): the chart's spot came from the terrain route and moved only when a gamma
    // push refetched it. Audit of #280: that was a second producer that could show a different
    // price than the header. Required now: the chart's spot line/label IS the header's price
    // row and follows every tick; the terrain panel carries flip/walls only.
    const rows = [priceRow('SPY', 583.41)];
    for (let i = 0; i < 20; i++) rows.push(priceRow('SPY', 601.23));   // the next ticks
    await socketWith(page, rows);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#chartBody .gchart-head')).toContainText(/spot (583\.41|601\.23)/);
    // the next tick moves the chart's live price line, and the chart and header show the same number
    await expect(page.locator('#chartBody .gchart-head')).toContainText('spot 601.23', { timeout: 8000 });
    await expect.poll(() => page.evaluate(() => window.EdGammaChart.state().livePrice)).toBe(601.23);
    await expect(page.locator('#hPx')).toHaveText('601.23');
  });

  test('the Key Levels rail shows regular and 0DTE in the same row', async ({ page }) => {
    panels.terrain = Object.assign({}, TERRAIN, {
      same_day: { gamma_flip: 571.25, call_wall: 575, put_wall: 570,
        absolute_gamma_strike: 572.5, lvp: 575, hvp: 565 },
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klBody .kl-pairs .h').nth(0)).toHaveText('Regular');
    await expect(page.locator('#klBody .kl-pairs .h').nth(1)).toHaveText('0DTE');
    await expect(page.locator('#klAbs0')).toHaveCount(0);
    await expect(page.locator('#klBody')).not.toContainText('0DTE γ pin');
    await expect(page.locator('#klFlip + #kl0Flip')).toHaveCount(1);
    await expect(page.locator('#kl0Flip')).toHaveText('571.25');
    await expect(page.locator('#kl0Call')).toHaveText('575.00');
    await expect(page.locator('#kl0Put')).toHaveText('570.00');
    await expect(page.locator('#kl0Abs')).toHaveText('572.50');
    await expect(page.locator('#kl0NetCall')).toHaveText('575.00');
    await expect(page.locator('#kl0NetPut')).toHaveText('565.00');
    await expect(page.locator('#klNetCall')).toHaveText('590.00');   // the whole book's two peaks
    await expect(page.locator('#klNetPut')).toHaveText('560.00');
    await expect(page.locator('#klBody')).not.toContainText('Net GEX peak');
    await expect(page.locator('#klNet')).toBeVisible();
  });

  test('Key Levels after a ticker switch: "-" until the new ticker\'s levels; a late frame of the old one is never drawn', async ({ page }) => {
    // the program's side: SPY's levels on SPY's subscribe; on QQQ's, a frame of SPY's that was
    // already on its way, and QQQ's own only when the test sends it
    let sendQqq = null;
    await page.routeWebSocket(/\/ws$/, (ws) => {
      ws.onMessage((m) => {
        const req = JSON.parse(String(m));
        if (req.op !== 'subscribe') return;
        ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
        if (!req.panels || !req.panels['terrain:levels']) return;
        if (req.ticker === 'SPY') { ws.send(panelFrame('terrain:levels', 'SPY', TERRAIN)); return; }
        ws.send(panelFrame('terrain:levels', 'SPY', Object.assign({}, TERRAIN, { gamma_flip: 111 })));
        sendQqq = () => ws.send(panelFrame('terrain:levels', req.ticker, Object.assign({}, TERRAIN, { gamma_flip: 480.5 })));
      });
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klFlip')).toHaveText('243.91');
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect(page.locator('#klFlip')).toHaveText('-');
    await expect(page.locator('#klSrc')).toHaveText('-');
    await expect.poll(() => sendQqq !== null).toBe(true);
    await expect(page.locator('#klFlip')).toHaveText('-');              // SPY's late frame not drawn
    sendQqq();
    await expect(page.locator('#klFlip')).toHaveText('480.50');
  });

  test('the Key Levels rail updates on a levels push', async ({ page }) => {
    // the program sends the terrain panel again when the levels change (_levels_changed)
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klFlip')).toHaveText('243.91');
    panels.terrain = Object.assign({}, TERRAIN, { gamma_flip: 590.00 });
    sock.changed('terrain');
    await expect(page.locator('#klFlip')).toHaveText('590.00');
  });

  test('Key Levels Spot is the header price, not the levels fetch', async ({ page }) => {
    panels.terrain = Object.assign({}, TERRAIN, { spot: 583.41 });   // the panel's copy
    await socketWith(page, [priceRow('SPY', 601.23)]);                    // the pushed price
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hPx')).toHaveText('601.23');
    await expect(page.locator('#klSpot')).toHaveText('601.23');
  });

  test('the Chain view is not asked for while inactive, and is asked for once on entry', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();   // lands on Gamma, not Chain
    await page.evaluate(() => window.EdShell.setStrike(null));
    const ladder = () => sock.subscribes.filter((s) => 'chain:ladder' in s.panels).length;
    expect(ladder()).toBe(0);   // never asked while Chain was never viewed
    // Entering the Chain view asks for its ladder once.
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect(page.locator('#chainBody table.chn-bodytbl')).toBeVisible();
    expect(ladder()).toBe(1);
  });

  test('the header chip shows the served coverage of the window; the page counts nothing', async ({ page }) => {
    // the server counts the cells of the window it serves
    // (server.py _stream_coverage); the page draws its words
    const surf = surfaceWithStreamState([{ call: 'live' }, { call: 'stale' }]);
    surf.view = view({ max_abs: { gex: 12345 },
      coverage: { state: 'partial', label: '50% STREAMING', title: '1 of 2 cells streaming · 1 stale' } });
    panels.surface = surf;
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await expect(page.locator('#heatScope')).toHaveText('50% STREAMING');
    await expect(page.locator('#heatScope')).toHaveAttribute('title', '1 of 2 cells streaming · 1 stale');
    await expect(page.locator('#heatScope')).toHaveClass(/cov-partial/);
  });

  test('no page timer reads /api: a minute with no push makes no request', async ({ page }) => {
    const requests = watchRequests(page);
    await holdClock(page);
    const reads = [];
    page.on('request', (r) => {
      const u = new URL(r.url());
      if (r.method() === 'GET' && u.pathname.startsWith('/api/')) reads.push(u.pathname);
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await requests.settled();   // hydration has landed
    const settled = reads.length;
    await page.clock.fastForward(60000);
    await requests.settled();   // and every read a timer would have made
    expect(reads.slice(settled)).toEqual([]);
  });
});
