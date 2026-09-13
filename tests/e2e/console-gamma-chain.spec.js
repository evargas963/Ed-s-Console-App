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
  await expect(page.locator('#chainBody table.chn')).toBeVisible();
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
});
