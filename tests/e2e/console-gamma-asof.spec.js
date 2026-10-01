// @ts-check
/**
 * #4 PER-PANEL SOURCE / AS-OF / FRESHNESS - each Gamma panel discloses ITS OWN canonical source and
 * as-of, formatted from server-owned fields. There is NO single global "LIVE": the terrain-derived
 * panels (GEX-by-strike) show the terrain generation's age, while Strike Detail shows the vendor
 * chain scope and the chart shows the price-bars clock AND the GEX levels clock as two separate
 * badges. Stale server state -> stale badge styling. Offline.
 */
const { test, expect } = require('@playwright/test');

const SURFACE = { ticker: 'SPY', symbol: 'SPY', available: true, spot: 100, spot_strike: 100, front_expiry: '2026-09-11', source: 'terrain_live_cache',
  live: true, stale: false, age_sec: 6, chain_basis: 'full', complete: false,
  expirations: [{ expiry: '2026-09-11', dte: 2 }], strikes: [98, 100, 102],
  cells: [{ strike: 98, gex: [-90000] }, { strike: 100, gex: [958600] }, { strike: 102, gex: [-264500] }] };
const TERRAIN = { ticker: 'SPY', spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98,
  absolute_gamma_strike: 100, net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP',
  levels_state: 'live', levels_stale: false, levels_age_sec: 21 };
const STRIKES = { ticker: 'SPY', spot: 100, spot_strike: 100, spot_source: 'schwab_quote_last',
  today_source: 'terrain_live_cache', today_age_sec: 21, levels_state: 'live', levels_stale: false, levels_age_sec: 21,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] } };
const BARS = { ticker: 'SPY', bars: [99.6, 99.9, 100.1, 100.0].map(function (c, i) {
  return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i }; }),
  last_bar: { t: 1757000180, label: 'Thu 09/04 10:36 AM CT' } };
const CHAIN = { ticker: 'SPY', spot: 100, spot_strike: 100, expiry: '2026-09-11', status: 'ok',
  scope: { kind: 'complete_single_expiry', requested_expiry: '2026-09-11', completeness_basis: 'strike_range=ALL' },
  contracts: [
    { putCall: 'CALL', strikePrice: 100, openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.52, volatility: 12.3, expirationDate: '2026-09-11' },
    { putCall: 'PUT', strikePrice: 100, openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.48, volatility: 12.6, expirationDate: '2026-09-11' } ] };
function routes(over) {
  over = over || {};
  return async (page) => {
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = { available: false };
      if (url.includes('/api/options/gamma-surface')) body = over.surface || SURFACE;
      else if (url.includes('/api/terrain/strikes')) body = over.strikes || STRIKES;
      else if (url.includes('/api/terrain')) body = over.terrain || TERRAIN;
      else if (url.includes('/api/bars1m')) body = BARS;
      else if (url.includes('/api/chain')) body = over.chain || CHAIN;      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
  };
}

test.describe('#4 per-panel source / as-of / freshness', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('GEX-by-strike discloses its terrain source + as-of (not a global LIVE)', async ({ page }) => {
    await routes()(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const badge = page.locator('#gbsSrc .asof');
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('terrain live');
    await expect(badge).toContainText('21s');            // the server's own today_age_sec, formatted
  });

  test('Strike Detail discloses the vendor chain scope', async ({ page }) => {
    await routes()(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    // the spot strike is auto-selected on load -> Strike Detail loads the chain
    const badge = page.locator('#sdSrc .asof');
    await expect(badge).toContainText('vendor');
    await expect(badge).toContainText('complete (ALL)');
  });

  test('the two panels show DIFFERENT source truths, not one merged status', async ({ page }) => {
    await routes()(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#gbsSrc .asof')).toContainText('terrain live');
    await expect(page.locator('#sdSrc .asof')).toContainText('vendor');
    const gbs = await page.locator('#gbsSrc .asof').innerText();
    const sd = await page.locator('#sdSrc .asof').innerText();
    expect(gbs).not.toEqual(sd);   // independent disclosures, never one global LIVE
  });

  test('the Chart shows the price-bars clock AND the GEX levels clock separately', async ({ page }) => {
    await routes()(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab', { hasText: 'Chart' }).click();
    const asof = page.locator('#chartBody .chart-asof');
    await expect(asof).toContainText('price 1m · ' + BARS.last_bar.label);   // bars clock, as served
    await expect(asof).toContainText('GEX terrain live'); // levels clock (separate)
  });

  test('GEX-by-strike with no rows prints the served reason, not words of its own', async ({ page }) => {
    // /api/terrain/strikes serves why there are no rows (today.absent_reason); the panel had its
    // own wording ("no banked per-strike gamma") and the reason was deleted (fourth review)
    const why = 'no levels published for this ticker yet';
    const none = Object.assign({}, STRIKES, { today: { all: [], near: [], far: [], expiry_unknown: null, absent_reason: why } });
    await routes({ strikes: none })(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#gbsBody')).toHaveText(why);
  });

  test('the Key Levels line prints the terrain\'s one served state', async ({ page }) => {
    await routes()(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSrc')).toContainText('terrain · live');
  });

  test('after the close the Key Levels line and the GEX-by-strike badge carry the time the levels are as of', async ({ page }) => {
    const closed = { levels_state: 'closed', levels_stale: false, levels_market_closed: true, levels_as_of: 'Fri 09/25 03:15 PM CT' };
    await routes({ terrain: Object.assign({}, TERRAIN, closed), strikes: Object.assign({}, STRIKES, closed) })(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSrc')).toContainText('as of Fri 09/25 03:15 PM CT');
    await expect(page.locator('#gbsSrc .asof')).toHaveClass(/ref/);
    await expect(page.locator('#gbsSrc .asof')).not.toHaveClass(/live/);   // a closed market's levels never read live
  });

  test('a stale terrain generation makes the GEX-by-strike badge read stale', async ({ page }) => {
    const staleStrikes = Object.assign({}, STRIKES, { levels_state: 'stale', levels_stale: true, levels_age_sec: 900,
      today_age_sec: 900, levels_stale_reason: 'levels loop paused' });
    await routes({ strikes: staleStrikes })(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const badge = page.locator('#gbsSrc .asof');
    await expect(badge).toHaveClass(/stale/);
    await expect(badge).toContainText('terrain live');
  });
});
