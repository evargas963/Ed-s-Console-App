// @ts-check
/**
 * The ONE presentation-scope control (Auto / Wider / All available) governs every Gamma panel: each
 * panel asks the server for its window with the scope and draws the rows it is sent. The server
 * picks the rows (terrain_engine.strike_window, proven in tests/test_heatmap_window_v1.py); here a
 * stand-in serves the window per scope -- 11, 23 or all 41 strikes of 80..120 around spot 100 --
 * and the page is proved to ask with the scope, draw what it is sent and keep the choice.
 */
const { test, expect } = require('@playwright/test');

// spot 100, 41 strikes 80..120; the stand-in's window per scope, as the server serves it
const ALL_ROWS = [];
for (let k = 80; k <= 120; k++) ALL_ROWS.push([k, (k % 2 ? 1 : -1) * (100000 + k * 10), 1000]);
const WINDOW = { auto: ALL_ROWS.slice(15, 26), wider: ALL_ROWS.slice(9, 32), all: ALL_ROWS };
function strikesFor(scope) {
  const rows = WINDOW[scope];
  return { ticker: 'SPY', spot: 100, spot_strike: 100, scope: scope, today: { all: rows },
    views: { all: { centre: 100, max_abs: 101200 } }, max_abs_row: [120, 101200, 1000] };
}
const TERRAIN = { ticker: 'SPY', spot: 100, gamma_flip: 99.5, call_wall: 106, put_wall: 94,
  absolute_gamma_strike: 100, net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
const BARS = { ticker: 'SPY', bars: [99.6, 99.9, 100.1, 99.8, 100.3, 100.5, 100.2, 100.0].map(function (c, i) {
  return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i }; }) };
const SURFACE = { ticker: 'SPY', symbol: 'SPY', available: true, spot: 100, front_expiry: '2026-09-11', source: 'terrain_live_cache',
  live: true, stale: false, age_sec: 3, chain_basis: 'full', complete: false,
  expirations: [{ expiry: '2026-09-11', dte: 2, front: true }], strikes: [99, 100, 101],
  cells: [{ strike: 99, gex: [-90000], spot: false }, { strike: 100, gex: [958600], spot: true },
    { strike: 101, gex: [-264500], spot: false }],
  view: { centre: 100, scope: 'auto', coverage: null, demand: [], max_abs: { gex: 958600 }, missing_expiry: null } };

async function intercept(page, asked) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/terrain/strikes')) {
      const scope = new URL(url).searchParams.get('scope');
      asked.push(scope);
      body = strikesFor(scope);
    } else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('the Gamma presentation scope', () => {
  let asked;
  test.beforeEach(async ({ page }) => {
    asked = [];
    await intercept(page, asked);
    // each Playwright test gets a fresh context (localStorage already empty), so we only seed the
    // ticker — NOT localStorage.clear(), which would re-run on reload and wipe the persisted scope.
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('one control governs the workspace, labelled "All available" not "Full"', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const ctl = page.locator('#scopeCtl');
    await expect(ctl).toBeVisible();                                   // shown for the gamma subview
    await expect(ctl.locator('.scbtn')).toHaveCount(3);
    await expect(ctl.locator('.scbtn', { hasText: 'Auto' })).toBeVisible();
    await expect(ctl.locator('.scbtn', { hasText: 'Wider' })).toBeVisible();
    await expect(ctl.locator('.scbtn', { hasText: 'All available' })).toBeVisible();
    await expect(ctl).not.toContainText('Full');                      // never mislabel as a full book
    // hidden outside options/gamma
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(ctl).toBeHidden();
    await page.locator('.navitem[data-ws="options"]').click();
    await expect(ctl).toBeVisible();
  });

  test('GEX-by-strike asks with the scope and draws the served window, legible at every scope', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const gbs = page.locator('#gbsBody');
    for (const [label, scope] of [['Auto', 'auto'], ['All available', 'all'], ['Wider', 'wider']]) {
      await page.locator('#scopeCtl .scbtn', { hasText: label }).click();
      await expect.poll(() => asked[asked.length - 1]).toBe(scope);
      const rows = WINDOW[scope];
      await expect(gbs.locator('.gbs-row')).toHaveCount(rows.length);
      await expect(gbs.locator('.gbs-row').first().locator('.gbs-k')).toHaveText(String(rows[rows.length - 1][0]));
      await expect(gbs.locator('.gbs-row').last().locator('.gbs-k')).toHaveText(String(rows[0][0]));
      // rows keep a legible height at every count (never shrunk to fit)
      const rowH = await gbs.locator('.gbs-row').first().evaluate((el) => el.getBoundingClientRect().height);
      expect(rowH).toBeGreaterThanOrEqual(24);
      await expect(gbs.locator('.scope-note')).toHaveCount(0);   // no structure notes (operator 2026-10-01)
    }
  });

  test('the Chart view asks with the same control and draws the served window', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab', { hasText: 'Chart' }).click();
    const rows = () => page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows);
    await expect.poll(rows).toBe(WINDOW.auto.length);
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect.poll(rows).toBe(WINDOW.all.length);
  });

  test('the scope choice persists across reloads (ed_scope)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(WINDOW.all.length);
    asked.length = 0;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#scopeCtl .scbtn.on')).toHaveText('All available');
    await expect.poll(() => asked[0]).toBe('all');
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(WINDOW.all.length);
  });
});
