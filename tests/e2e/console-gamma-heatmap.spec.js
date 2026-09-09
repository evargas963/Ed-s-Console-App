// @ts-check
/**
 * RC-UI-1 — browser DOM proof for the rebuilt Ed Console shell + Options/Gamma heatmap.
 *
 * Proves the FRONTEND presentation contract in a real browser: the heatmap renders the
 * canonical /api/options/gamma-surface payload VERBATIM (cell text == formatted backend value,
 * invariant E), sign -> colour with no inversion (invariant D), spot row highlight, and the Key
 * Levels rail reflects /api/terrain. The endpoint==faucet equality is proven separately in
 * tests/test_gamma_surface_projection_v1.py; together they cover end-to-end.
 *
 * Endpoints are intercepted with synthetic payloads so the proof is deterministic and offline —
 * it exercises the real shell HTML/JS, not stubbed rendering.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SURFACE = {
  ticker: '$SPX', symbol: '$SPX', available: true, spot: 583.41,
  source: 'terrain_live_cache', live: true, stale: false, age_sec: 3,
  chain_as_of_ts_utc: 1757000200, spot_as_of_ts_utc: 1757000200, spot_source: 'last',
  expirations: [{ expiry: '2026-09-11', dte: 2 }, { expiry: '2026-09-18', dte: 9 }],
  strikes: [580, 583, 586],
  cells: [
    { strike: 580, gex: [-90000, null] },
    { strike: 583, gex: [958600, 300000] },
    { strike: 586, gex: [-264500, 120000] },
  ],
  provenance: { producer: 'math_exposure_core.compute_exposures_by_strike', classification: 'DERIVED' },
};
const TERRAIN = {
  ticker: '$SPX', spot: 583.41, gamma_flip: 582.90, call_wall: 586, put_wall: 580,
  absolute_gamma_strike: 583, net_gex_peak: 583, net_gex_at_spot: 2140000000,
  regime: 'LONG_GAMMA_CHOP', levels_stale: false,
};
const STRIKES = {
  ticker: '$SPX', spot: 583.41,
  today: { all: [[586, -264500, 1200], [583, 958600, 5400], [580, -90000, 900]] },
};
const LIVE = {
  spot: 583.41, spot_disp: '583.41', bid: 583.40, ask: 583.42,
  analytics_lightweight: { spy_chg_pct: 0.38 },
  streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 380 },
};
const BARS = {
  ticker: '$SPX', n: 8,
  bars: [582.6, 582.9, 583.1, 582.8, 583.3, 583.5, 583.2, 583.41].map(function (c, i) {
    return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i };
  }),
};

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/live/state')) body = LIVE;
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('Ed Console shell + gamma heatmap', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('shell structure: rail has all seven workspaces + 3-tier nav', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.navitem[data-ws]')).toHaveCount(7);
    for (const ws of ['trade-desk', 'order-flow', 'options', 'liquidity', 'desk', 'portfolio', 'system']) {
      await expect(page.locator(`.navitem[data-ws="${ws}"]`)).toHaveCount(1);
    }
    await expect(page.locator('#subnav .wtitle')).toContainText('OPTIONS');
    await expect(page.locator('.vtab', { hasText: 'Heatmap' })).toBeVisible();
  });

  test('heatmap renders canonical cells verbatim (value == formatted payload; sign -> colour)', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const cell583 = page.locator('.hcell[data-strike="583"][data-expiry="2026-09-11"]');
    const cell586 = page.locator('.hcell[data-strike="586"][data-expiry="2026-09-11"]');
    await expect(cell583).toHaveText('$958.6K');   // E: formatting-only of 958600
    await expect(cell586).toHaveText('-$264.5K');  // E: formatting-only of -264500
    // D: positive -> green fill, negative -> red fill (no inversion)
    const bg583 = await cell583.evaluate((el) => getComputedStyle(el).backgroundColor);
    const bg586 = await cell586.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg583).toMatch(/rgba?\(\s*35,\s*192,\s*107/);
    expect(bg586).toMatch(/rgba?\(\s*229,\s*72,\s*77/);
    // spot row is the 583 strike (nearest 583.41)
    await expect(page.locator('tr.spotrow .hstrike')).toHaveText('583');
    // a LIVE surface shows no stale/reference banner and tags the source LIVE
    await expect(page.locator('.heat-banner')).toHaveCount(0);
    await expect(page.locator('#heatScope')).toContainText('LIVE');
  });

  test('stale/reference gamma surface fails stale visibly (no morning snapshot passed as live)', async ({ page }) => {
    await page.route('**/api/options/gamma-surface**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, SURFACE, {
        source: 'banked_morning_reference', live: false, stale: true,
        degraded: 'live terrain surface unavailable — showing banked MORNING chain (reference only: morning spot + morning Greeks, NOT intraday)',
      })),
    }));
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const banner = page.locator('.heat-banner.ref');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('MORNING REFERENCE');
    await expect(banner).toContainText('intraday');
    await expect(page.locator('#heatScope')).toContainText('REF');
  });

  test('key levels rail reflects /api/terrain', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#klSpot')).toHaveText('583.41');
    await expect(page.locator('#klFlip')).toHaveText('582.90');
    await expect(page.locator('#klCall')).toHaveText('586.00');
    await expect(page.locator('#klPut')).toHaveText('580.00');
    await expect(page.locator('#klNet')).toHaveText('$2.1B');
    await expect(page.locator('#klRegime')).toContainText('Long γ');
    // NOT_PROVEN items are honestly labelled, never fabricated
    await expect(page.locator('#klBody')).toContainText('NOT PROVEN');
  });

  test('workspace switching + editable watchlist foundation', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(page.locator('[data-ws-pane="system"]')).toBeVisible();
    await expect(page.locator('#subnav .wtitle')).toContainText('SYSTEM');
    // add a symbol via the shell API (foundation is editable + localStorage-backed)
    await page.evaluate(() => window.EdShell.addSymbol('AMD'));
    await expect(page.locator('.wl-row .info .s', { hasText: 'AMD' })).toHaveCount(1);
  });

  test('chart view: Price + GEX Profile and Dot Map render from canonical inputs', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#view-chart')).toHaveClass(/on/);
    // profile mode (default): price line + signed profile bars + flip level line + spot
    const svg = page.locator('#chartBody svg');
    await expect(svg).toBeVisible();
    await expect(page.locator('#chartBody svg polyline')).toHaveCount(1);      // price line
    expect(await page.locator('#chartBody svg rect').count()).toBeGreaterThan(0); // profile bars
    await expect(page.locator('#chartBody svg')).toContainText('spot 583.41');
    await expect(page.locator('#chartBody svg')).toContainText('flip');
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.screenshot({ path: require('path').join('test-results', 'console-gamma-chart-2560x1440.png') });
    // dot map mode: per-strike dots
    await page.locator('.cmode[data-cmode="dotmap"]').click();
    expect(await page.locator('#chartBody svg circle').count()).toBeGreaterThan(0);
    await expect(page.locator('#chartModes .cmode[data-cmode="dotmap"]')).toHaveClass(/on/);
  });

  test('live-update: single scheduler + monotonic latest-wins on the header quote', async ({ page }) => {
    // a stale/slow response for the PREVIOUS ticker must never overwrite the newer one
    await page.route('**/api/live/state**', async (route) => {
      const url = route.request().url();
      if (url.includes('ticker=SPY')) {
        await new Promise((r) => setTimeout(r, 900));   // stale, arrives late
        return route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ spot: 111.11, spot_disp: '111.11', bid: 111, ask: 111.2,
            streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 100 } }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ spot: 222.22, spot_disp: '222.22', bid: 222, ask: 222.3,
          streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 100 } }) });
    });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });   // init ticker SPY -> delayed 111.11
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));        // newer -> immediate 222.22
    await expect(page.locator('#hPx')).toHaveText('222.22');
    await page.waitForTimeout(1300);                                   // let the stale SPY response land
    await expect(page.locator('#hPx')).toHaveText('222.22');          // not overwritten by the stale response
  });

  test('responsive proof: 2560x1440 and 1920x1080 screenshots', async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.hcell').first()).toBeVisible();
    await page.screenshot({ path: path.join('test-results', 'console-gamma-2560x1440.png'), fullPage: false });
    await page.setViewportSize({ width: 1920, height: 1080 });
    await expect(page.locator('.hcell').first()).toBeVisible();
    // body must not scroll sideways at the smaller target
    const overflow = await page.evaluate(() => document.body.scrollWidth <= window.innerWidth + 2);
    expect(overflow).toBe(true);
    await page.screenshot({ path: path.join('test-results', 'console-gamma-1920x1080.png'), fullPage: false });
  });
});
