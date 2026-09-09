// @ts-check
/**
 * #3 VIEW-WINDOW DISCLOSURE — browser DOM proof for the ONE presentation-scope control.
 *
 * The Chart and GEX-by-strike panels window the canonical strikes around spot for readability.
 * Before this change that clip was SILENT. This proves:
 *   - ONE control (Auto / Wider / All available) governs the whole Gamma workspace, and it is
 *     labelled "All available" — never "Full" (the canonical input is not a strike_range=ALL book).
 *   - Every windowed panel prints a disclosure line: how many of the canonical strikes are on
 *     screen, and — when strikes are clipped — that they are outside the view and how to widen.
 *   - AUTO clips (fewer strikes, a clip warning); ALL AVAILABLE shows every canonical strike with
 *     no clip warning; WIDER falls between. The choice persists (ed_scope).
 *
 * A wide synthetic /api/terrain/strikes (spot 100, strikes 80..120) makes the window observable and
 * offline. It exercises the real shell HTML/JS, not stubbed rendering.
 */
const { test, expect } = require('@playwright/test');

// spot 100, 41 strikes 80..120 step 1. AUTO GEX ±6% -> 94..106 (13). WIDER ±12% -> 88..112 (25).
// ALL -> 41. Chart AUTO ±4% -> 96..104 (9).
const STRIKES_WIDE = (function () {
  const all = [];
  for (let k = 120; k >= 80; k--) all.push([k, (k % 2 ? 1 : -1) * (100000 + k * 10), 1000]);
  return { ticker: 'SPY', spot: 100, today: { all: all } };
})();
const TERRAIN = { ticker: 'SPY', spot: 100, gamma_flip: 99.5, call_wall: 106, put_wall: 94,
  absolute_gamma_strike: 100, net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
const BARS = { ticker: 'SPY', bars: [99.6, 99.9, 100.1, 99.8, 100.3, 100.5, 100.2, 100.0].map(function (c, i) {
  return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i }; }) };
const LIVE = { spot: 100, spot_disp: '100.00', bid: 99.99, ask: 100.01, session_label: 'RTH',
  analytics_lightweight: { spy_chg_pct: 0.1 }, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };
const SURFACE = { ticker: 'SPY', symbol: 'SPY', available: true, spot: 100, source: 'terrain_live_cache',
  live: true, stale: false, age_sec: 3, chain_basis: 'full', complete: false,
  expirations: [{ expiry: '2026-09-11', dte: 2 }], strikes: [99, 100, 101],
  cells: [{ strike: 99, gex: [-90000] }, { strike: 100, gex: [958600] }, { strike: 101, gex: [-264500] }] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/terrain/strikes')) body = STRIKES_WIDE;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/live/state')) body = LIVE;
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('#3 Gamma presentation-scope (view-window disclosure)', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    // each Playwright test gets a fresh context (localStorage already empty), so we only seed the
    // ticker — NOT localStorage.clear(), which would re-run on reload and wipe the persisted scope.
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('one control governs the workspace, labelled "All available" not "Full"', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
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

  test('GEX-by-strike discloses the window and clip count; ALL AVAILABLE shows every canonical strike', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const gbs = page.locator('#gbsBody');
    const note = gbs.locator('.scope-note');
    await expect(note).toBeVisible();
    // AUTO: only the near-money window is shown, and the clip is disclosed (not silent)
    await expect(note).toContainText('Auto');
    await expect(note).toContainText('of 41 strikes');
    await expect(note.locator('.clip')).toContainText('outside view');
    const autoRows = await gbs.locator('.gbs-row').count();
    expect(autoRows).toBeGreaterThan(0);
    expect(autoRows).toBeLessThan(41);
    await page.screenshot({ path: 'test-results/gamma-scope-auto.png', fullPage: false });
    // ALL AVAILABLE: every canonical strike, no clip warning
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect(note).toContainText('41 of 41 strikes');
    await expect(gbs.locator('.scope-note .clip')).toHaveCount(0);
    await expect(gbs.locator('.gbs-row')).toHaveCount(41);
    await page.screenshot({ path: 'test-results/gamma-scope-all.png', fullPage: false });
    // WIDER falls between AUTO and ALL
    await page.locator('#scopeCtl .scbtn', { hasText: 'Wider' }).click();
    const widerRows = await gbs.locator('.gbs-row').count();
    expect(widerRows).toBeGreaterThan(autoRows);
    expect(widerRows).toBeLessThan(41);
  });

  test('the Chart view also discloses its window and responds to the same control', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab', { hasText: 'Chart' }).click();
    const chart = page.locator('#chartBody');
    await expect(chart.locator('.scope-note')).toContainText('of 41 strikes');
    const autoMarks = await chart.locator('.gmark').count();
    expect(autoMarks).toBeGreaterThan(0);
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect(chart.locator('.scope-note')).toContainText('41 of 41 strikes');
    expect(await chart.locator('.gmark').count()).toBeGreaterThan(autoMarks);
  });

  test('the scope choice persists across reloads (ed_scope)', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect(page.locator('#gbsBody .scope-note')).toContainText('41 of 41 strikes');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#scopeCtl .scbtn.on')).toHaveText('All available');
    await expect(page.locator('#gbsBody .scope-note')).toContainText('41 of 41 strikes');
  });
});
