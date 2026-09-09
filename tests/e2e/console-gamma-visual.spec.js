// @ts-check
/**
 * VISUAL CONVERGENCE PROOF — full-viewport captures of the Options/Gamma workspace against the
 * approved reference hierarchy: dominant strike x expiry HEATMAP (hero), compact left nav rail,
 * narrow right KEY LEVELS rail, subordinate bottom strip (Strike Detail / GEX by Strike / Flow).
 *
 * Uses a DENSE, representative synthetic surface (SPX-scale: ~25 strikes x 6 expiries) so the
 * screenshots show the heatmap as the hero the way real data would — clearly synthetic, offline.
 * Captures DARK and LIGHT at 2560x1440 and 1920x1080 (full viewport, not cropped).
 */
const { test, expect } = require('@playwright/test');

const SPOT = 5000;
const EXPS = [
  { expiry: '2026-09-11', dte: 0 }, { expiry: '2026-09-12', dte: 1 }, { expiry: '2026-09-15', dte: 4 },
  { expiry: '2026-09-18', dte: 7 }, { expiry: '2026-09-22', dte: 11 }, { expiry: '2026-09-30', dte: 19 },
  { expiry: '2026-10-17', dte: 36 }, { expiry: '2026-11-21', dte: 71 }, { expiry: '2026-12-19', dte: 99 },
  { expiry: '2027-01-15', dte: 126 }, { expiry: '2027-03-19', dte: 189 },
];
const STRIKE_LIST = (function () { const a = []; for (let k = SPOT + 100; k >= SPOT - 100; k -= 20) a.push(k); return a; })();
function gexAt(k, ci) {
  // signed net GEX$ — magnitude peaks near spot / at round strikes, decays with distance and DTE, so
  // the grid has real K-to-M texture (presentation only, synthetic — clearly not live data).
  const d = Math.abs(k - SPOT) / 20;
  const sign = (k % 100 === 0) ? 1 : ((k > SPOT) ? -1 : 1);
  const base = 7.6e6 / (1 + d * d * 0.35) / (1 + ci * 0.55);
  const jitter = 0.6 + ((k / 20 + ci * 7) % 5) * 0.16;
  return Math.round(sign * base * jitter);
}
const SURFACE = {
  ticker: '$SPX', symbol: '$SPX', available: true, spot: SPOT, source: 'terrain_live_cache',
  live: true, stale: false, age_sec: 4, chain_basis: 'full', complete: false,
  coverage: { window: 'live_near_money', chain_basis: 'full', strike_count: STRIKE_LIST.length,
    note: 'near-money LIVE window (strike_count-bounded terrain chain) — NOT the full strike_range=ALL book' },
  chain_as_of_ts_utc: 1757000200, spot_as_of_ts_utc: 1757000200, spot_source: 'last',
  expirations: EXPS, strikes: STRIKE_LIST,
  cells: STRIKE_LIST.map(function (k) { return { strike: k, gex: EXPS.map(function (_e, ci) { return gexAt(k, ci); }) }; }),
  provenance: { producer: 'math_exposure_core.compute_exposures_by_strike', classification: 'DERIVED' },
};
const TERRAIN = { ticker: '$SPX', spot: SPOT, gamma_flip: 4992.4, call_wall: 5100, put_wall: 4900,
  absolute_gamma_strike: 5000, net_gex_peak: 5000, net_gex_at_spot: 3.14e9, regime: 'LONG_GAMMA_CHOP',
  levels_stale: false, levels_age_sec: 4 };
const STRIKES = { ticker: '$SPX', spot: SPOT, today_source: 'terrain_live_cache', today_age_sec: 4,
  levels_stale: false, levels_age_sec: 4,
  today: { all: STRIKE_LIST.map(function (k) { return [k, gexAt(k, 0), 1000 + (k % 500)]; }) } };
const BARS = { ticker: '$SPX', bars: Array.from({ length: 80 }, function (_v, i) {
  const c = SPOT - 12 + Math.sin(i / 6) * 9 + i * 0.12;
  return { t: 1757000000 + i * 60, o: c - 1, h: c + 2, l: c - 2, c: c, v: 1000 + i }; }) };
const CHAIN = { ticker: '$SPX', spot: SPOT, expiry: '2026-09-11', status: 'ok',
  contracts: [
    { putCall: 'CALL', strikePrice: 5000, openInterest: 12400, totalVolume: 5400, gamma: 0.0021, delta: 0.52, volatility: 12.3, expirationDate: '2026-09-11' },
    { putCall: 'PUT', strikePrice: 5000, openInterest: 9800, totalVolume: 4100, gamma: 0.0019, delta: -0.48, volatility: 12.6, expirationDate: '2026-09-11' } ] };
const LIVE = { spot: SPOT, spot_disp: '5000.00', bid: 4999.75, ask: 5000.25, session_label: 'RTH',
  analytics_lightweight: { spy_chg_pct: 0.42 }, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 320 } };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/chain')) body = CHAIN;
    else if (url.includes('/api/expiries')) body = { expiries: EXPS.map(function (e) { return e.expiry; }) };
    else if (url.includes('/api/live/state')) body = LIVE;
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

const VIEWPORTS = [{ w: 1672, h: 941 }, { w: 1920, h: 1080 }, { w: 2560, h: 1440 }];
const THEMES = ['dark', 'light'];

for (const theme of THEMES) {
  for (const vp of VIEWPORTS) {
    test(`hero composition ${theme} ${vp.w}x${vp.h}`, async ({ page }) => {
      await intercept(page);
      await page.addInitScript((t) => {
        try { localStorage.setItem('ed_ticker', '$SPX'); localStorage.setItem('ed_theme', t);
          localStorage.setItem('ed_ws', 'options'); localStorage.setItem('ed_sub', 'gamma');
          localStorage.setItem('ed_view', 'heatmap'); localStorage.setItem('ed_rail_open', '1'); } catch (e) {}
      }, theme);
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.goto('/console', { waitUntil: 'domcontentloaded' });
      // the heatmap is the hero: its cells must render, dense
      await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();
      expect(await page.locator('#view-heatmap .hcell').count()).toBeGreaterThan(60);
      await expect(page.locator('#klFlip')).not.toHaveText('—');   // right rail populated
      // body must not scroll sideways
      const bodyScroll = await page.evaluate(() => document.body.scrollWidth - document.body.clientWidth);
      expect(bodyScroll).toBeLessThanOrEqual(1);
      await page.screenshot({ path: `test-results/gamma-hero-${theme}-${vp.w}x${vp.h}.png`, fullPage: false });
    });
  }
}
