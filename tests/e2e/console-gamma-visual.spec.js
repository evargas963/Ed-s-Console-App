// @ts-check
/**
 * VISUAL CONVERGENCE PROOF — full-viewport captures of the Options/Gamma workspace against the
 * approved reference hierarchy: dominant strike x expiry HEATMAP (hero), compact left nav rail,
 * narrow right KEY LEVELS rail, subordinate bottom strip (Strike Detail / GEX by Strike / Flow).
 *
 * Draws the server's own answers on AMZN's real chain (11 strikes x 24 expiries, levels LIVE), so
 * the screenshots show the heatmap as the hero on real data, offline.
 * Captures DARK and LIGHT at 2560x1440 and 1920x1080 (full viewport, not cropped).
 */
const { test, expect } = require('@playwright/test');
const { pushExpiries } = require('./fixtures/expiries');
const { chainAt } = require('./fixtures/price_socket');
const { routeWatchlist } = require('./fixtures/watchlist');

// the heatmap, the levels, the strikes and the front expiry's chain as the server sends them on
// AMZN's real chain of 2026-11-12 10:39 ET, 24 expiries, with the prior day's close compared
// (held to the server by tests/test_e2e_panels_two_day_v1.py)
const REAL = require('./fixtures/panels_amzn_two_day.json');
const SURFACE = REAL.surface, TERRAIN = REAL.terrain, STRIKES = REAL.strikes, CHAIN = REAL.chain;
const SPOT = TERRAIN.spot;
const EXPS = SURFACE.expirations;
// price bars around the real price (the set holds no bars)
const BARS = { ticker: 'AMZN', bars: Array.from({ length: 80 }, function (_v, i) {
  const c = SPOT - 1.2 + Math.sin(i / 6) * 0.9 + i * 0.012;
  return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i }; }) };

async function intercept(page) {
  await routeWatchlist(page, ['AMZN']);
  await pushExpiries(page, EXPS.map((e) => e.expiry), Object.fromEntries(EXPS.map((e) => [e.expiry, e.dte])), { bars: BARS, terrain: TERRAIN, strikes: STRIKES, surface: SURFACE,
    chain: chainAt(CHAIN) });
}

const VIEWPORTS = [{ w: 1672, h: 941 }, { w: 1920, h: 1080 }, { w: 2560, h: 1440 }];
const THEMES = ['dark', 'light'];

for (const theme of THEMES) {
  for (const vp of VIEWPORTS) {
    test(`hero composition ${theme} ${vp.w}x${vp.h}`, async ({ page }) => {
      await intercept(page);
      await page.addInitScript((t) => {
        localStorage.setItem('ed_ticker', 'AMZN'); localStorage.setItem('ed_theme', t);
          localStorage.setItem('ed_ws', 'options'); localStorage.setItem('ed_sub', 'gamma');
          localStorage.setItem('ed_view', 'heatmap'); localStorage.setItem('ed_rail_open', '1');      }, theme);
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      // the heatmap is the hero: its cells must render, dense
      await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();
      expect(await page.locator('#view-heatmap .hcell').count()).toBeGreaterThan(60);
      await expect(page.locator('#klFlip')).not.toHaveText('-');   // right rail populated
      // body must not scroll sideways
      const bodyScroll = await page.evaluate(() => document.body.scrollWidth - document.body.clientWidth);
      expect(bodyScroll).toBeLessThanOrEqual(1);
      await page.screenshot({ path: `test-results/gamma-hero-${theme}-${vp.w}x${vp.h}.png`, fullPage: false });
    });
  }
}
