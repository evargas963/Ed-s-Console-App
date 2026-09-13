// @ts-check
/**
 * D — Options/Gamma "Chain" subview. Full vendor ladder from /api/chain (calls left, puts right,
 * strike centre), served VERBATIM. Proves: single-expiry disclosure (B), exact CALL/PUT vendor-symbol
 * selection through the ONE control owner EdStream (C), duplicate vendor rows retained (D), and the
 * centre strike selects only the shared strike. Symbols are the vendor's own, never reconstructed.
 */
const { test, expect } = require('@playwright/test');

function ct(side, strike, sym, oi, vol, iv, delta) {
  return { putCall: side, strikePrice: strike, symbol: sym, openInterest: oi, totalVolume: vol,
    volatility: iv, delta: delta, gamma: 0.01, expirationDate: '2026-09-11' };
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

  // Independent-review finding (2026-09-13), REPRODUCED by direct browser measurement (not
  // source inspection): the column headers never actually stuck to the top while scrolling --
  // confirmed the fix (a separate sticky-wrapped header table + a body table sharing one
  // <colgroup>) with a real, long ladder (far more strikes than fit the viewport at once).
  test('column headers stay pinned to the top while scrolling a long ladder (state-authority review)', async ({ page }) => {
    const BIG = { ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok',
      scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
      contracts: Array.from({ length: 80 }, (_, i) => ct('CALL', 50 + i, 'SPY   260911C00' + (50 + i) + '000', 10, 10, 10, 0.1)) };
    await page.route('**/api/chain*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BIG) }));
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(80);

    const headerTop = () => page.locator('.chn-headwrap thead tr').first().boundingBox().then((b) => b.y);
    const containerTop = await page.locator('#chainBody').boundingBox().then((b) => b.y);

    await page.evaluate(() => { document.getElementById('chainBody').scrollTop = 0; });
    await page.evaluate(() => { document.getElementById('chainBody').scrollTop = 1200; });
    const y1 = await headerTop();
    await page.evaluate(() => { document.getElementById('chainBody').scrollTop = 2600; });
    const y2 = await headerTop();

    // Stuck: the same position at two different (large) scroll depths, and at the container's
    // own top edge -- not silently scrolling away with the body content underneath it.
    expect(Math.abs(y1 - y2)).toBeLessThan(2);
    expect(Math.abs(y1 - containerTop)).toBeLessThan(15);
  });

  test('a routine background refresh does not reset a manually-scrolled position', async ({ page }) => {
    const BIG = { ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok',
      scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
      contracts: Array.from({ length: 80 }, (_, i) => ct('CALL', 50 + i, 'SPY   260911C00' + (50 + i) + '000', 10, 10, 10, 0.1)) };
    await page.route('**/api/chain*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BIG) }));
    await toChain(page);
    await expect(page.locator('#chainBody tbody tr')).toHaveCount(80);

    await page.evaluate(() => { document.getElementById('chainBody').scrollTop = 1800; });
    const before = await page.evaluate(() => document.getElementById('chainBody').scrollTop);
    // A routine background refresh (same ticker/expiry context) must not recentre the ladder.
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { slow: true } })));
    await page.waitForTimeout(300);
    const after = await page.evaluate(() => document.getElementById('chainBody').scrollTop);
    expect(after).toBe(before);
  });

  // V01 (test-quality review, 2026-09-13): this file's own CHAIN fixture returns the SAME
  // contracts for every requested expiry, so nothing here could ever tell a correct re-fetch
  // apart from a frozen/stale display on an expiry switch. Closed with a mock that returns
  // DISTINGUISHABLE, expiry-keyed contracts and an assertion that the rendered ladder actually
  // changes to match each requested expiry -- this would fail if curExpiry()'s wiring broke and
  // the view kept showing a stale expiry's data after the dropdown moved.
  test('switching the expiry dropdown re-fetches and renders that expiry\'s own distinct contracts', async ({ page }) => {
    const EXP_A = '2026-09-11', EXP_B = '2026-09-18';
    await page.route('**/api/expiries*', (r) => r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ expiries: [EXP_A, EXP_B] }) }));
    await page.route('**/api/chain*', (route) => {
      const exp = new URL(route.request().url()).searchParams.get('expiry') || EXP_A;
      const strike = exp === EXP_A ? 100 : 200;   // distinct strike AND distinct symbol per expiry
      const body = { ticker: 'SPY', spot: strike, expiry: exp, status: 'ok',
        scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
        contracts: [ct('CALL', strike, 'SPY   FIXTURE_' + exp + 'C', 1, 1, 1, 0.1)] };
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await toChain(page);
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · ' + EXP_A);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('100');

    await page.locator('#expSel').selectOption(EXP_B);
    await expect(page.locator('#chainBody .chn-head')).toContainText('SINGLE EXPIRY · ' + EXP_B);
    await expect(page.locator('#chainBody tbody tr td.k')).toHaveText('200');
    await expect(page.locator('#chainBody tr[data-csym="SPY   FIXTURE_' + EXP_B + 'C"]')).toHaveCount(1);
    await expect(page.locator('#chainBody tr[data-csym="SPY   FIXTURE_' + EXP_A + 'C"]')).toHaveCount(0);
  });
});
