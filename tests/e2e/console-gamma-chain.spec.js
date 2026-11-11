// @ts-check
/**
 * D — Options/Gamma "Chain" subview. Full vendor ladder from the socket's chain panel (calls left, puts right,
 * strike centre), served VERBATIM. Proves: single-expiry disclosure (B), exact CALL/PUT vendor-symbol
 * selection for the Flow panel, named to the console to stream (C), duplicate vendor rows retained
 * (D), and the centre strike selects only the shared strike. Symbols are the vendor's own, never
 * reconstructed.
 */
const { test, expect } = require('@playwright/test');
const { expiriesAnswer, pushExpiries } = require('./fixtures/expiries');
const { expiriesFrame, priceRow, served: servedSymbol } = require('./fixtures/price_socket');
const { served } = require('./fixtures/served_chain');
const { routeWatchlist } = require('./fixtures/watchlist');

function ct(side, strike, sym, oi, vol, iv, delta, expDate) {
  return { putCall: side, strikePrice: strike, symbol: sym, openInterest: oi, totalVolume: vol,
    volatility: iv, delta: delta, gamma: 0.01, expirationDate: expDate || '2026-09-11' };
}
// Real OSI-style symbol (root padded to 6 + YYMMDD + C/P + 8-digit strike*1000), matching the
// vendor's own verbatim format -- used where a test needs the symbol's OWN expirationDate to
// genuinely vary with the requested expiry (V01 test-quality review, 2026-09-13: a prior
// fixture hardcoded expirationDate to 2026-09-11 even in a 2026-09-18 response, and used a
// non-native "FIXTURE_" placeholder symbol instead of a real OCC-shaped one).
function occSymbol(root, isoExpiry, side, strike) {
  const yymmdd = isoExpiry.replace(/-/g, '').slice(2);
  const strikeStr = String(Math.round(strike * 1000)).padStart(8, '0');
  return root.padEnd(6, ' ') + yymmdd + (side === 'PUT' ? 'P' : 'C') + strikeStr;
}
const CHAIN = { ticker: 'SPY', spot: 100, spot_strike: 100, expiry: '2026-09-11', status: 'ok',
  scope: { kind: 'complete_single_expiry' },
  contracts: [
    ct('CALL', 102, 'SPY   260911C00102000', 1200, 300, 11.1, 0.35), ct('PUT', 102, 'SPY   260911P00102000', 900, 250, 12.1, -0.65),
    ct('CALL', 100, 'SPY   260911C00100000', 5400, 2100, 12.3, 0.52), ct('PUT', 100, 'SPY   260911P00100000', 4100, 1800, 12.6, -0.48),
    ct('CALL', 98, 'SPY   260911C00098000', 800, 150, 13.5, 0.68), ct('PUT', 98, 'SPY   260911P00098000', 1500, 600, 14.0, -0.32),
  ] };

//: each contract the page names to the console for the Flow panel (POST /api/flow-contract)
const flowPosts = [];

async function intercept(page) {
  await page.route('**/api/flow-contract', (route, request) => {
    const contract = JSON.parse(request.postData()).contract;
    flowPosts.push(contract);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contract: contract }) });
  });
  await routeWatchlist(page, ['SPY']);
  panels = chainPanels(() => CHAIN);
  sock = await pushExpiries(page, ['2026-09-11'], undefined, panels);
}
// the panels the page's socket sends this test: the chain panel `chainOf(expiry)` (each reader's
// expiry; null: the front one) as the program serves it, and the Gamma tab's own (a test may
// change one before the page opens); `sock` is the program's side of the socket
let panels, sock;
function chainPanels(chainOf) {
  return {
    chain: (key, params) => served(chainOf(params.expiry)),
    bars: { available: false }, tape: { available: false },
    terrain: { spot: 100, gamma_flip: 99.5, regime: 'LONG_GAMMA_CHOP', levels_state: 'LIVE', levels_mark: 'LIVE' },
    strikes: { spot: 100, levels_state: 'LIVE', today: { all: [[100, 1, 1]] }, views: { all: { centre: 100, note: null, max_abs: 1 } } },
    surface: { ticker: 'SPY', available: true, spot: 100,
      source: 'terrain_live_cache', levels_state: 'LIVE', expirations: [{ expiry: '2026-09-11', dte: 2 }],
      strikes: [100], cells: [{ strike: 100, gex: [1] }],
      view: { centre: 100, scope: 'auto', coverage: null, max_abs: { gex: 1 }, missing_expiry: null } },
  };
}

async function toChain(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
  // the ladder now renders as two separate tables (header + body) so the header can genuinely
  // stick on scroll -- see ed-gamma-chain.js's chn-headwrap/chn-bodytbl split (2026-09-13).
  await expect(page.locator('#chainBody table.chn-bodytbl')).toBeVisible();
}

test.describe('D — Gamma Chain subview', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); });
  });

  test('Chain swaps in the ladder + single-expiry disclosure; Gamma restores on switch back', async ({ page }) => {
    await toChain(page);
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeHidden();
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(3);
    await expect(page.locator('#chainBody tbody tr').first().locator('td.k')).toHaveText('102');
    await expect(page.locator('#chainBody tbody tr.spot td.k')).toHaveText('100');
    // B: single-expiry truth — the null filter is "Default Expiry", the ladder says SINGLE EXPIRY
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · 2026-09-11');
    await expect(page.locator('#chainBody .chn-head')).toContainText('server default');
    await expect(page.locator('#expSel option').first()).toHaveText('Default Expiry');
    await expect(page.locator('#chSrc .asof')).toContainText('complete (ALL)');
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeVisible();
    await expect(page.locator('#expSel option').first()).toHaveText('All Expirations');   // Gamma: null = all
  });

  test('the chain spot keeps its last trade time', async ({ page }) => {
    panels.chain = () => served(Object.assign({}, CHAIN, { spot_time_ct: 'Fri 09/25 06:59 PM CT' }));
    await toChain(page);
    await expect(page.locator('#chainBody .chn-head')).toContainText('spot 100.00');
    await expect(page.locator('#chainBody .chn-head')).toContainText('last trade Fri 09/25 06:59 PM CT');
  });

  test('CALL click selects the exact CALL vendor symbol; PUT click the exact PUT symbol, each named to stream', async ({ page }) => {
    flowPosts.length = 0;
    await toChain(page);
    // click the CALL side of strike 100
    await page.locator('#chainBody tr[data-csym="SPY   260911C00100000"] td.chn-call').first().click();
    expect(await page.evaluate(() => window.EdFlow.selected())).toBe('SPY   260911C00100000');
    // click the PUT side of strike 98
    await page.locator('#chainBody tr[data-psym="SPY   260911P00098000"] td.chn-put').first().click();
    expect(await page.evaluate(() => window.EdFlow.selected())).toBe('SPY   260911P00098000');
    await expect.poll(() => flowPosts).toEqual(['SPY   260911C00100000', 'SPY   260911P00098000']);
    // shared strike/expiry context follows the selection
    const s = await page.evaluate(() => window.EdShell.getState());
    expect(s.selStrike).toBe(98);
  });

  test('the centre Strike selects ONLY the shared strike (no contract)', async ({ page }) => {
    flowPosts.length = 0;
    await toChain(page);
    await page.locator('#chainBody tr[data-strike="102"] td.k').click();
    expect(await page.evaluate(() => window.EdShell.getState().selStrike)).toBe(102);
    expect(await page.evaluate(() => window.EdFlow.selected())).toBeNull();   // no contract chosen
    expect(flowPosts).toEqual([]);
  });

  // Independent-review finding (2026-09-13), REPRODUCED by direct browser measurement, then
  // narrowed to a two-sticky-row defect and "fixed" with a sticky div wrapping a header table
  // -- but the operator kept reproducing a real, moving visual fault on genuine trackpad
  // scrolling that survived TWO follow-up `position:sticky` fixes (a compositing-layer
  // promotion, then overscroll containment), neither provably addressing the actual
  // mechanism because neither could be reproduced by any scroll technique available in this
  // test harness. Root-caused instead of patched again: `position:sticky` is removed
  // entirely. The header is now a FROZEN (non-scrolling) sibling of a separate `.chn-scroll`
  // div that holds only the body table -- there is no sticky positioning anywhere left for a
  // compositor or scroll-chaining bug to intermittently mishandle, so the header's position
  // is asserted EXACTLY constant (no pixel tolerance needed, unlike the old sticky-offset
  // math), including through a real mouse-wheel scroll (not just programmatic scrollTop) and
  // a concurrent data refresh.
  test('the header table never moves regardless of scrolling the body, including real wheel scroll during a refresh (state-authority review)', async ({ page }) => {
    let vol = 10;
    const BIG = () => ({ ticker: 'SPY', spot: 100, spot_strike: 100, expiry: '2026-09-11', status: 'ok',
      scope: { kind: 'complete_single_expiry' },
      contracts: Array.from({ length: 80 }, (_, i) => ct('CALL', 50 + i, 'SPY   260911C00' + (50 + i) + '000', 10, vol, 10, 0.1)) });
    panels.chain = () => served(BIG());
    await page.setViewportSize({ width: 900, height: 640 });   // a representative, not maximal, size
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(80);

    const headBox = () => page.locator('.chn-headtbl').boundingBox();
    const scrollTop = () => page.locator('#chainScroll').evaluate((el) => el.scrollTop);
    const before = await headBox();
    expect(before).toBeTruthy();

    // A real wheel scroll (not a programmatic scrollTop assignment) on the actual scroll
    // element, exercising the same input path a real trackpad/mouse produces.
    await page.locator('#chainScroll').hover();
    await page.mouse.wheel(0, 1200);
    await expect.poll(scrollTop).toBeGreaterThan(0);   // the wheel has scrolled the body
    const duringScroll = await headBox();

    // Fire a background refresh (same context) WHILE scrolled, with genuinely changed data,
    // and confirm both the new value lands AND the header still has not moved at all.
    vol = 25;
    sock.changed('chain');   // the program sends the chain again: a new chain was priced
    await expect(page.locator('#chainBody tbody tr').first().locator('td').nth(1)).toHaveText('25');
    const afterRefresh = await headBox();

    const bottom = await page.locator('#chainScroll').evaluate((el) => el.scrollHeight - el.clientHeight);
    await page.mouse.wheel(0, 2000);
    await expect.poll(scrollTop).toBe(bottom);   // 2000 px more takes the body to its end
    const afterMoreScroll = await headBox();

    // Exact equality: a frozen (non-scrolling) header cannot move by even one pixel, at any
    // point in this sequence -- this is a structural guarantee now, not an approximation.
    expect(duringScroll.y).toBe(before.y);
    expect(afterRefresh.y).toBe(before.y);
    expect(afterMoreScroll.y).toBe(before.y);
    expect(duringScroll.x).toBe(before.x);
    expect(afterMoreScroll.x).toBe(before.x);

    // Column alignment: the header table and the body table are unrelated table layouts
    // sharing only a <colgroup> -- prove a header cell's left edge and width actually match
    // its corresponding body column, not merely that both tables render.
    const headCell = await page.locator('.chn-headtbl thead tr').last().locator('th').first().boundingBox();
    const bodyCell = await page.locator('.chn-bodytbl tbody tr').first().locator('td').first().boundingBox();
    expect(Math.abs(headCell.x - bodyCell.x)).toBeLessThan(1);
    expect(Math.abs(headCell.width - bodyCell.width)).toBeLessThan(1);

    // No gap and no overlap between the two header rows: the second row's top must equal
    // (within sub-pixel rounding) the first row's own bottom edge.
    const rows = await page.locator('.chn-headtbl thead tr').evaluateAll(
      (trs) => trs.map((tr) => tr.getBoundingClientRect()));
    expect(rows.length).toBe(2);
    expect(Math.abs(rows[1].top - rows[0].bottom)).toBeLessThan(1);

    await page.setViewportSize({ width: 1280, height: 800 });   // restore default
  });

  // A FOURTH independent review (2026-09-13) found this test waited a fixed 300ms without ever
  // establishing that a refresh with CHANGED data actually completed -- it could pass simply
  // because nothing re-rendered at all. Strengthened: the second chain response carries a
  // DIFFERENT value (volume), and the test asserts that value actually reached the DOM before
  // checking the scroll position was preserved.
  test('a routine background refresh with changed data completes, and preserves a manually-scrolled position', async ({ page }) => {
    let vol = 10;
    const BIG = () => ({ ticker: 'SPY', spot: 100, spot_strike: 100, expiry: '2026-09-11', status: 'ok',
      scope: { kind: 'complete_single_expiry' },
      contracts: Array.from({ length: 80 }, (_, i) => ct('CALL', 50 + i, 'SPY   260911C00' + (50 + i) + '000', 10, vol, 10, 0.1)) });
    panels.chain = () => served(BIG());
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(80);
    await expect(page.locator('#chainBody tbody tr').first().locator('td').nth(1)).toHaveText('10');

    await page.evaluate(() => { document.getElementById('chainScroll').scrollTop = 1800; });
    const before = await page.evaluate(() => document.getElementById('chainScroll').scrollTop);

    // The NEXT chain sent carries a genuinely different value -- proof a refresh actually
    // completed comes from the DOM showing THIS new value, not merely from time having passed.
    vol = 25;
    sock.changed('chain');
    await expect(page.locator('#chainBody tbody tr').first().locator('td').nth(1)).toHaveText('25');

    // A routine background refresh (same ticker/expiry context) must not recentre the ladder,
    // even though it just genuinely re-rendered with new data.
    const after = await page.evaluate(() => document.getElementById('chainScroll').scrollTop);
    expect(after).toBe(before);
  });

  // V01 (test-quality review, 2026-09-13): this file's own CHAIN fixture returns the SAME
  // contracts for every requested expiry, so nothing here could ever tell a correct re-fetch
  // apart from a frozen/stale display on an expiry switch. Closed with a mock that returns
  // DISTINGUISHABLE, expiry-keyed contracts and an assertion that the rendered ladder actually
  // changes to match each requested expiry -- this would fail if curExpiry()'s wiring broke and
  // the view kept showing a stale expiry's data after the dropdown moved.
  //
  // A FOURTH independent review (2026-09-13) found this test's OWN fixture still hardcoded
  // `expirationDate: '2026-09-11'` (via ct()'s old fixed default) even inside the 2026-09-18
  // response, and used a non-native "FIXTURE_"-prefixed symbol -- fixed with real per-expiry
  // expirationDate values and genuine OCC-shaped symbols (occSymbol above) so contract identity
  // itself is under real test, not just the strike number and a placeholder string.
  test('switching the expiry dropdown re-fetches and renders that expiry\'s own distinct contracts', async ({ page }) => {
    const EXP_A = '2026-09-11', EXP_B = '2026-09-18';
    const symA = occSymbol('SPY', EXP_A, 'CALL', 100);
    const symB = occSymbol('SPY', EXP_B, 'CALL', 200);
    panels = chainPanels((asked) => {
      const exp = asked || EXP_A;
      const strike = exp === EXP_A ? 100 : 200;   // distinct strike AND distinct symbol per expiry
      const sym = exp === EXP_A ? symA : symB;
      return { ticker: 'SPY', spot: strike, expiry: exp, status: 'ok',
        scope: { kind: 'complete_single_expiry' },
        contracts: [ct('CALL', strike, sym, 1, 1, 1, 0.1, exp)] };   // expirationDate == exp, genuinely
    });
    sock = await pushExpiries(page, [EXP_A, EXP_B], undefined, panels);
    await toChain(page);
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · ' + EXP_A);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('100');

    await page.locator('#expSel').selectOption(EXP_B);
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · ' + EXP_B);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('200');
    await expect(page.locator('#chainBody tr[data-csym="' + symB + '"]')).toHaveCount(1);
    await expect(page.locator('#chainBody tr[data-csym="' + symA + '"]')).toHaveCount(0);
  });

  // A -> B -> A: the program's B frame, sent before it read the page's return to A, arrives
  // after A's own frame has been drawn; it is not drawn.
  test('A -> B -> A: a frame of an expiry no longer selected is not drawn over the selected one', async ({ page }) => {
    const EXP_A = '2026-09-11', EXP_B = '2026-09-18';
    const ladder = (exp, strike) => ({ ticker: 'SPY', spot: strike, expiry: exp, status: 'ok',
      scope: { kind: 'complete_single_expiry' },
      contracts: [ct('CALL', strike, occSymbol('SPY', exp, 'CALL', strike), 1, 1, 1, 0.1, exp)] });
    panels = chainPanels((asked) => (asked === EXP_B ? ladder(EXP_B, 222) : ladder(EXP_A, 333)));
    sock = await pushExpiries(page, [EXP_A, EXP_B], undefined, panels);
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('333');
    await page.locator('#expSel').selectOption(EXP_B);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('222');
    await page.locator('#expSel').selectOption(EXP_A);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('333');

    await page.evaluate(() => {          // every ladder drawn from here on: its strikes
      window.__draws = [];
      new MutationObserver(() => window.__draws.push([...document.querySelectorAll('#chainBody tbody tr td.k')]
        .map((e) => e.textContent).join(','))).observe(document.getElementById('chainBody'), { childList: true, subtree: true });
    });
    sock.frame('chain:ladder', 'SPY', served(ladder(EXP_B, 222)));   // the late B frame ...
    sock.frame('chain:ladder', 'SPY', served(ladder(EXP_A, 444)));   // ... and A's next, behind it
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('444');
    expect((await page.evaluate(() => window.__draws)).filter((d) => d.includes('222'))).toEqual([]);
    await expect(page.locator('#chainBody .chn-head')).toContainText(EXP_A);
  });
});

test.describe('expiry dropdown (register P-03): the list on the page\'s socket', () => {
  // it formatted each date on the page and ignored the served reason when none is listed; the
  // list is the program's, sent on /ws after each subscribe on the selected ticker and again on
  // each new chain (server.expiries), and the page asks no route for it
  const SPY_LIST = expiriesAnswer(['2026-10-16'], { '2026-10-16': 18 });
  const QQQ_LIST = expiriesAnswer(['2026-10-17'], { '2026-10-17': 19 });
  const LISTS = { SPY: SPY_LIST, QQQ: QQQ_LIST };
  // `onSocket(ws, n)`: the stand-in for the program's side of the page's n-th connection
  async function open(page, onSocket) {
    const asked = [];
    page.on('request', (r) => { if (r.url().includes('/api/expiries')) asked.push(r.url()); });
    await page.route('**/api/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await routeWatchlist(page, ['SPY']);
    let n = 0;
    await page.routeWebSocket(/\/ws$/, (ws) => onSocket(ws, ++n));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    return asked;
  }
  // the program's answer to each subscribe: what each symbol is, then the selected ticker's list
  function answering(ws, lists) {
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== 'subscribe') return;
      ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(servedSymbol) }));
      if (req.ticker && lists[req.ticker]) ws.send(expiriesFrame(req.ticker, lists[req.ticker]));
    });
  }
  function options(page) {
    return page.locator('#expSel option').evaluateAll((os) => os.map((o) => o.textContent));
  }

  test('each option shows its served label, at once on the subscribe, with no request', async ({ page }) => {
    const asked = await open(page, (ws) => answering(ws, LISTS));
    await expect(page.locator('#expSel option[value="2026-10-16"]')).toHaveText('10/16/2026 · 18DTE');
    expect(asked).toEqual([]);
  });

  test('a ticker with no chain yet shows the served reason', async ({ page }) => {
    await open(page, (ws) => answering(ws, { SPY: { expiries: null, dte: null, labels: null, dte_text: null, reason: 'market closed; no chain capture of this ticker yet' } }));
    await expect(page.locator('#expSel option[disabled]')).toHaveText('market closed; no chain capture of this ticker yet');
  });

  test('no list received (the socket down): "-", never a list', async ({ page }) => {
    await open(page, (ws) => ws.close());
    await expect(page.locator('#expSel option[disabled]')).toHaveText('-');
    expect(await options(page)).toEqual(['All Expirations', '-']);
  });

  test('switching ticker shows the new ticker\'s list at once; a list for the ticker left is ignored', async ({ page }) => {
    let program;
    await open(page, (ws) => { program = ws; answering(ws, LISTS); });
    await expect(page.locator('#expSel option[value="2026-10-16"]')).toHaveCount(1);
    await page.locator('#symInput').fill('QQQ');
    await page.locator('#symInput').press('Enter');
    await expect.poll(() => options(page)).toEqual(['All Expirations', '10/17/2026 · 19DTE']);
    // SPY's next chain, still in flight to a page that has left SPY; then a row of QQQ's, drawn
    // after it: once the row is on screen, the list before it was read
    program.send(expiriesFrame('SPY', SPY_LIST));
    program.send(JSON.stringify({ type: 'quotes', rows: [priceRow('QQQ', 512.34)] }));
    await expect(page.locator('#hPx')).toContainText('512.34');
    expect(await options(page)).toEqual(['All Expirations', '10/17/2026 · 19DTE']);
  });

  test('the socket drops and returns: the list is sent again on the resubscribe', async ({ page }) => {
    let first;
    await open(page, (ws, n) => {
      if (n === 1) { first = ws; answering(ws, LISTS); return; }
      // the program's list after the drop: the next chain's, so the page shows the one resent
      answering(ws, { SPY: expiriesAnswer(['2026-10-30'], { '2026-10-30': 23 }) });
    });
    await expect(page.locator('#expSel option[value="2026-10-16"]')).toHaveCount(1);
    first.close();
    await expect.poll(() => options(page)).toEqual(['All Expirations', '10/30/2026 · 23DTE']);
  });
});
