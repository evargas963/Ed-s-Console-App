// @ts-check
/**
 * Options Flow tape (operator field-inventory audit, 2026-09-13) — the embedded #ofBody
 * widget on the Gamma pane, rebuilt to the operator's own required schema: Time | Symbol |
 * Expiry | Type | Strike | Bid x Size | Ask x Size | Trade | Size | Premium | Volume | OI |
 * IV | Delta | provenance. Sourced from /api/options/tape (native LEVELONE_OPTIONS trade
 * prints, already retained — see app.options.order_flow.history.tape_rows_for_symbol). No
 * buy/sell aggressor side is ever fabricated; `classification` states only the mechanical
 * fact of where a print landed relative to that same tick's own bid/ask.
 */
const { test, expect } = require('@playwright/test');

const TERRAIN = { ticker: 'SPY', spot: 100, gamma_flip: 99.5, call_wall: 106, put_wall: 94,
  absolute_gamma_strike: 100, net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
const BARS = { ticker: 'SPY', bars: [] };
const SURFACE = { ticker: 'SPY', symbol: 'SPY', available: true, spot: 100, source: 'terrain_live_cache',
  live: true, stale: false, age_sec: 3, chain_basis: 'full', complete: false,
  expirations: [{ expiry: '2026-09-18', dte: 2 }], strikes: [100],
  cells: [{ strike: 100, gex: [958600], contracts: [{ call: null, put: null }] }] };

const TAPE_ROW = {
  ts_recv: 1789166557.5, symbol: 'SPY   260918C00600000', underlying: 'SPY',
  expiry: '2026-09-18', type: 'CALL', strike: 600,
  bid: 1.17, bid_size: 187, ask: 1.19, ask_size: 180,
  trade: 1.18, size: 1, premium: 118.0,
  volume: 70984, oi: 901, iv: 7.16, delta: 0.357,
  multiplier: 100, classification: 'inside_spread',
};

function intercept(page, tapeBody) {
  return page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/tape')) body = tapeBody;
    else if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/terrain/strikes')) body = { ticker: 'SPY', spot: 100, today: { all: [] } };
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/session')) body = { session_label: 'RTH' };
    else if (url.includes('/api/chain')) body = { ticker: 'SPY', spot: 100, expiry: null, contracts: [], status: 'unavailable', scope: { kind: 'unavailable', requested_expiry: null, reason: 'no listed expiry for this ticker' } };
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-18'] };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('Options Flow tape (Gamma pane, native trade prints)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('an empty tape discloses the reason, never a fabricated row', async ({ page }) => {
    await intercept(page, { ticker: 'SPY', available: false, rows: [],
      reason: 'no active/additional option contract selected for this ticker' });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const of = page.locator('#ofBody');
    await expect(of).toContainText('no active/additional option contract selected');
    await expect(of.locator('tbody tr:not(.of-empty)')).toHaveCount(0);
  });

  test('a real trade print renders every required schema column with native values, never fabricated buy/sell', async ({ page }) => {
    await intercept(page, { ticker: 'SPY', available: true, symbols: [TAPE_ROW.symbol], rows: [TAPE_ROW] });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const of = page.locator('#ofBody');
    await expect(of.locator('thead th')).toHaveText(
      ['Time', 'Symbol', 'Exp', 'Type', 'Strike', 'Bid×Size', 'Ask×Size', 'Trade', 'Size',
       'Premium', 'Vol', 'OI', 'IV%', 'Δ', 'vs Market']);
    const row = of.locator('tbody tr').first();
    await expect(row.locator('td').nth(1)).toHaveText(TAPE_ROW.symbol);   // exact vendor symbol, verbatim
    await expect(row.locator('td').nth(2)).toHaveText('09-18');
    await expect(row.locator('td').nth(3)).toHaveText('CALL');
    await expect(row.locator('td').nth(4)).toHaveText('600');
    await expect(row.locator('td').nth(5)).toHaveText('1.17×187');
    await expect(row.locator('td').nth(6)).toHaveText('1.19×180');
    await expect(row.locator('td').nth(7)).toHaveText('1.18');
    await expect(row.locator('td').nth(8)).toHaveText('1');
    await expect(row.locator('td').nth(9)).toContainText('118');
    await expect(row.locator('td').nth(10)).toContainText('71.0K');
    await expect(row.locator('td').nth(11)).toHaveText('901');
    await expect(row.locator('td').nth(12)).toHaveText('7.2');
    await expect(row.locator('td').nth(13)).toHaveText('0.357');
    // classification is a mechanical bid/ask fact, never a buy/sell verdict
    await expect(row.locator('.of-cls')).toHaveText('inside');
    const bodyText = await of.innerText();
    expect(bodyText.toLowerCase()).not.toMatch(/\bbuy\b|\bsell\b|\bbought\b|\bsold\b/);
  });

  test('at-bid and at-ask prints are labelled by mechanical comparison, not aggressor inference', async ({ page }) => {
    const atBid = { ...TAPE_ROW, ts_recv: TAPE_ROW.ts_recv + 1, trade: 1.17, classification: 'at_bid' };
    const atAsk = { ...TAPE_ROW, ts_recv: TAPE_ROW.ts_recv + 2, trade: 1.19, classification: 'at_ask' };
    await intercept(page, { ticker: 'SPY', available: true, symbols: [TAPE_ROW.symbol], rows: [atAsk, atBid] });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const rows = page.locator('#ofBody tbody tr');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0).locator('.of-cls')).toHaveText('at ask');   // newest-first
    await expect(rows.nth(1).locator('.of-cls')).toHaveText('at bid');
  });
});
