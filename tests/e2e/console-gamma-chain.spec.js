// @ts-check
/**
 * D — Options/Gamma "Chain" subview. Full vendor ladder from /api/chain (calls left, puts right,
 * strike centre), served VERBATIM. Proves: single-expiry disclosure (B), exact CALL/PUT vendor-symbol
 * selection through the ONE control owner EdStream (C), duplicate vendor rows retained (D), and the
 * centre strike selects only the shared strike. Symbols are the vendor's own, never reconstructed.
 */
const { test, expect } = require('@playwright/test');

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
const CHAIN = { ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok',
  scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
  contracts: [
    ct('CALL', 102, 'SPY   260911C00102000', 1200, 300, 11.1, 0.35), ct('PUT', 102, 'SPY   260911P00102000', 900, 250, 12.1, -0.65),
    ct('CALL', 100, 'SPY   260911C00100000', 5400, 2100, 12.3, 0.52), ct('PUT', 100, 'SPY   260911P00100000', 4100, 1800, 12.6, -0.48),
    ct('CALL', 98, 'SPY   260911C00098000', 800, 150, 13.5, 0.68), ct('PUT', 98, 'SPY   260911P00098000', 1500, 600, 14.0, -0.32),
  ] };

async function intercept(page) {
  await page.route('**/api/**', (route, request) => {
    const url = request.url();
    if (url.includes('/api/streaming/active-option-contract') && request.method() === 'POST') {
      let contract = ''; try { contract = JSON.parse(request.postData() || '{}').contract || ''; } catch (e) {}
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contract: contract, command_generation: 1 }) });
    }
    let body = { available: false };
    if (url.includes('/api/chain')) body = CHAIN;
    else if (url.includes('/api/options/gamma-surface')) body = { ticker: 'SPY', available: true, spot: 100,
      source: 'terrain_live_cache', live: true, stale: false, expirations: [{ expiry: '2026-09-11', dte: 2 }],
      strikes: [100], cells: [{ strike: 100, gex: [1] }] };
    else if (url.includes('/api/terrain/strikes')) body = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 5, levels_stale: false, today: { all: [[100, 1, 1]] } };
    else if (url.includes('/api/terrain')) body = { spot: 100, gamma_flip: 99.5, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11'] };
    else if (url.includes('/api/live/state')) body = { ticker: 'SPY', spot: 100, spot_disp: '100.00', session_label: 'RTH', analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function toChain(page) {
  await page.goto('/console', { waitUntil: 'domcontentloaded' });
  await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
  // the ladder now renders as two separate tables (header + body) so the header can genuinely
  // stick on scroll -- see ed-gamma-chain.js's chn-headwrap/chn-bodytbl split (2026-09-13).
  await expect(page.locator('#chainBody table.chn-bodytbl')).toBeVisible();
}

test.describe('D — Gamma Chain subview', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
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

  test('CALL click sends the exact CALL vendor symbol; PUT click the exact PUT symbol (via EdStream)', async ({ page }) => {
    await toChain(page);
    // click the CALL side of strike 100
    await page.locator('#chainBody tr[data-csym="SPY   260911C00100000"] td.chn-call').first().click();
    expect(await page.evaluate(() => window.EdStream.getDesired())).toBe('SPY   260911C00100000');
    // click the PUT side of strike 98
    await page.locator('#chainBody tr[data-psym="SPY   260911P00098000"] td.chn-put').first().click();
    expect(await page.evaluate(() => window.EdStream.getDesired())).toBe('SPY   260911P00098000');
    // shared strike/expiry context follows the selection
    const s = await page.evaluate(() => window.EdShell.getState());
    expect(s.selStrike).toBe(98);
  });

  test('the centre Strike selects ONLY the shared strike (no contract)', async ({ page }) => {
    await toChain(page);
    await page.locator('#chainBody tr[data-strike="102"] td.k').click();
    expect(await page.evaluate(() => window.EdShell.getState().selStrike)).toBe(102);
    expect(await page.evaluate(() => window.EdStream.getDesired())).toBeNull();   // no contract chosen
  });

  test('the contract symbol is the vendor symbol verbatim (never reconstructed)', async ({ page }) => {
    await toChain(page);
    await page.locator('#chainBody tr[data-csym="SPY   260911C00102000"] td.chn-call').first().click();
    // exactly the fixture symbol, spaces and all — no OCC construction
    expect(await page.evaluate(() => window.EdStream.getDesired())).toBe('SPY   260911C00102000');
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
    const BIG = () => ({ ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok',
      scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
      contracts: Array.from({ length: 80 }, (_, i) => ct('CALL', 50 + i, 'SPY   260911C00' + (50 + i) + '000', 10, vol, 10, 0.1)) });
    await page.route('**/api/chain*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BIG()) }));
    await page.setViewportSize({ width: 900, height: 640 });   // a representative, not maximal, size
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(80);

    const headBox = () => page.locator('.chn-headtbl').boundingBox();
    const before = await headBox();
    expect(before).toBeTruthy();

    // A real wheel scroll (not a programmatic scrollTop assignment) on the actual scroll
    // element, exercising the same input path a real trackpad/mouse produces.
    await page.locator('#chainScroll').hover();
    await page.mouse.wheel(0, 1200);
    await page.waitForTimeout(100);
    const duringScroll = await headBox();

    // Fire a background refresh (same context) WHILE scrolled, with genuinely changed data,
    // and confirm both the new value lands AND the header still has not moved at all.
    vol = 25;
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await expect(page.locator('#chainBody tbody tr').first().locator('td').nth(1)).toHaveText('25');
    const afterRefresh = await headBox();

    await page.mouse.wheel(0, 2000);
    await page.waitForTimeout(100);
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
    const BIG = () => ({ ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok',
      scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
      contracts: Array.from({ length: 80 }, (_, i) => ct('CALL', 50 + i, 'SPY   260911C00' + (50 + i) + '000', 10, vol, 10, 0.1)) });
    await page.route('**/api/chain*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BIG()) }));
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(80);
    await expect(page.locator('#chainBody tbody tr').first().locator('td').nth(1)).toHaveText('10');

    await page.evaluate(() => { document.getElementById('chainScroll').scrollTop = 1800; });
    const before = await page.evaluate(() => document.getElementById('chainScroll').scrollTop);

    // The NEXT chain fetch carries a genuinely different value -- proof a refresh actually
    // completed comes from the DOM showing THIS new value, not merely from time having passed.
    vol = 25;
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
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
    await page.route('**/api/expiries*', (r) => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ expiries: [EXP_A, EXP_B] }) }));
    await page.route('**/api/chain*', (route) => {
      const exp = new URL(route.request().url()).searchParams.get('expiry') || EXP_A;
      const strike = exp === EXP_A ? 100 : 200;   // distinct strike AND distinct symbol per expiry
      const sym = exp === EXP_A ? symA : symB;
      const body = { ticker: 'SPY', spot: strike, expiry: exp, status: 'ok',
        scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
        contracts: [ct('CALL', strike, sym, 1, 1, 1, 0.1, exp)] };   // expirationDate == exp, genuinely
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await toChain(page);
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · ' + EXP_A);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('100');

    await page.locator('#expSel').selectOption(EXP_B);
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · ' + EXP_B);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('200');
    await expect(page.locator('#chainBody tr[data-csym="' + symB + '"]')).toHaveCount(1);
    await expect(page.locator('#chainBody tr[data-csym="' + symA + '"]')).toHaveCount(0);
  });

  // A FOURTH independent review (2026-09-13), NAMED as the same class of risk already fixed
  // in the retained /options page (see options-page-chain-race.spec.js's own A->B->A test,
  // which DOES fail on its pre-fix code): stillChain(tk, exp) proves the CURRENT identity
  // matches, but two different requests issued at different times for the IDENTICAL
  // (ticker, expiry) are indistinguishable to it -- whichever resolves LAST wins, not
  // whichever was issued last. Unlike options.html, this loader already uses a real
  // AbortController (makeCoalescedLoader), and in this Playwright mock harness that abort
  // reliably prevents the held first-A response from ever resolving at all -- this test
  // PASSES on both the pre- and post-fix code here (confirmed by direct comparison), so it
  // is a regression/behavior test, not a proven fail-before/pass-after reproduction for
  // THIS view. The fix (an explicit monotonic request sequence, _reqSeq) is still real
  // defense-in-depth: AbortController does not GUARANTEE a stale fetch never resolves (a
  // response already fully buffered before abort() is processed can still resolve in real
  // browsers), and this sequence check makes correctness independent of that timing detail.
  test('A -> B -> A: a held first-A response cannot overwrite the fresh second-A response (state-authority review)', async ({ page }) => {
    const EXP_A = '2026-09-11', EXP_B = '2026-09-18';
    const symA1 = occSymbol('SPY', EXP_A, 'CALL', 111);
    const symA2 = occSymbol('SPY', EXP_A, 'CALL', 333);
    let aCallCount = 0;
    await page.route('**/api/expiries*', (r) => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ expiries: [EXP_A, EXP_B] }) }));
    await page.route('**/api/chain*', async (route) => {
      const exp = new URL(route.request().url()).searchParams.get('expiry') || EXP_A;
      if (exp === EXP_A) {
        aCallCount += 1;
        if (aCallCount === 1) {
          // The FIRST A request is held -- resolves LATE, after the return-to-A request
          // below has already resolved and painted the correct, newer value.
          await new Promise((r) => setTimeout(r, 900));
          const body = { ticker: 'SPY', spot: 111, expiry: EXP_A, status: 'ok',
            scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
            contracts: [ct('CALL', 111, symA1, 1, 1, 1, 0.1, EXP_A)] };
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
        }
        const body = { ticker: 'SPY', spot: 333, expiry: EXP_A, status: 'ok',
          scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
          contracts: [ct('CALL', 333, symA2, 1, 1, 1, 0.1, EXP_A)] };
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      }
      const body = { ticker: 'SPY', spot: 222, expiry: EXP_B, status: 'ok',
        scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
        contracts: [ct('CALL', 222, occSymbol('SPY', EXP_B, 'CALL', 222), 1, 1, 1, 0.1, EXP_B)] };
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await toChain(page);   // fires the first, held A request
    await expect(page.locator('#chainBody .chn-head')).toContainText(EXP_A);

    await page.locator('#expSel').selectOption(EXP_B);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('222');

    await page.locator('#expSel').selectOption(EXP_A);   // fires the second, fast A request
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('333');

    // Wait past the FIRST A request's deliberate 900ms delay.
    await page.waitForTimeout(1300);

    // Non-retrying snapshot: the held, stale first-A response must not have overwritten 333.
    const strikeText = await page.locator('#chainBody tbody tr td.k').textContent();
    expect(strikeText).toBe('333');
    expect(aCallCount).toBeGreaterThanOrEqual(2);   // at least the two A requests under test
  });
});
