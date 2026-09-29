// @ts-check
/**
 * Options/Gamma "Chart" subview (Price + GEX Profile / GEX Dot Map). /api/terrain/strikes is a
 * genuine all-expiry aggregate -- no single mark has one real expiry to attribute, confirmed by
 * reading terrain_engine.py's _per_strike_rows and compute_exposures_by_strike (they collapse
 * call+put across EVERY expiry sharing a strike; there is no principled way to pick "the" call
 * and put symbol for an aggregate row without first choosing one specific expiry, which the
 * aggregate deliberately does not track). But clicking a mark is still a deliberate strike
 * selection, and every OTHER view that calls EdShell.setStrike (heatmap: the column's real
 * expiry; Chain: the one displayed expiry) always supplies a real expiry so Strike Detail can
 * resolve one. Chart's click handler used to pass NO expiry at all, unconditionally clobbering
 * state.selExpiry to null (ed-core.js setStrike) even when the operator had a specific expiry
 * filter selected in the workspace -- silently discarding that context and sending Strike
 * Detail's /api/chain request to the server's own default-expiry resolution instead.
 *
 * Independent-review finding (2026-09-13), REPRODUCED. Fixed: the click now carries through
 * whatever workspace expiry filter (EdShell.getExpiry()) is currently set, matching the
 * established convention, while still passing null when the filter itself is null (Chart has no
 * per-mark expiry to invent in that case either).
 *
 * A FOURTH independent review (2026-09-13) challenged this file's own proof: it used
 * dispatchEvent (bypassing real pointer hit-testing after noting real clicks could miss the
 * ~2-real-pixel-tall profile bars) and a CHAIN fixture with no native `symbol` field, so it
 * proved the click HANDLER's logic, not the full operator workflow through to a real native
 * contract identity. Both are fixed at the root, not worked around: ed-gamma-chart.js now draws
 * an invisible, generously-sized hit target alongside every visible mark (a real click-target
 * usability fix, not a test-only shim -- a real pointer had the identical difficulty a
 * coordinate-based Playwright click did), so this file uses genuine `.click()` throughout; the
 * CHAIN fixture carries real native OSI-style symbols so the full path -- Chart click -> expiry
 * carried through -> Strike Detail's /api/chain fetch -> Strike Detail resolving the REAL call
 * and put symbols for that strike -> demanding streaming for those exact native symbols -- is
 * actually exercised end to end.
 */
const { test, expect } = require('@playwright/test');

const STRIKES = { spot: 100, spot_strike: 100, max_abs_strike: 100, today_source: 'terrain_live_cache', today_age_sec: 5, levels_stale: false,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] },
  measures: { dex: { rows: [[97, -41000], [98, -12000], [100, 88000], [102, 23000]], spot_strike: 100, max_abs_strike: 100 },
    oi: { rows: [[97, 300], [98, 1500], [100, 5200], [102, 2180], [104, 90]], spot_strike: 100, max_abs_strike: 100 } } };
const TERRAIN = { spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
const BARS = { bars: [{ t: 1757000000, o: 99, h: 101, l: 98, c: 100, v: 1 }] };
const CALL_SYM = 'SPY   260918C00102000';
const PUT_SYM = 'SPY   260918P00102000';
const CHAIN = { spot: 100, spot_strike: 102, expiry: '2026-09-18', status: 'ok', scope: { kind: 'complete_single_expiry' },
  contracts: [
    { symbol: CALL_SYM, putCall: 'CALL', strikePrice: 102, openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.5, volatility: 12 },
    { symbol: PUT_SYM, putCall: 'PUT', strikePrice: 102, openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.5, volatility: 12 },
  ] };

async function intercept(page) {
  const chainRequests = [];
  const demandCalls = [];
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    if (url.includes('/api/streaming/active-option-contract') && route.request().method() === 'POST') {
      let body = {}; try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
      demandCalls.push(body);
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, contracts: body.contracts || [] }) });
    }
    let body = { available: false };
    if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11', '2026-09-18'] };
    else if (url.includes('/api/chain')) {
      const u = new URL(url); chainRequests.push(u.searchParams.get('expiry'));
      body = CHAIN;
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return { chainRequests, demandCalls };
}

// a real mouse click where the chart draws the strike's profile row
async function clickStrike(page, strike) {
  const pt = await page.evaluate((k) => window.EdGammaChart.profilePoint(k), strike);
  expect(pt).not.toBeNull();
  await page.mouse.click(pt.x, pt.y);
}

test.describe('Options/Gamma Chart subview', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('a real click on a Chart mark carries the workspace expiry through to Strike Detail\'s real native call/put identity (state-authority review)', async ({ page }) => {
    const { chainRequests, demandCalls } = await intercept(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await page.locator('#expSel').selectOption('2026-09-18');
    await expect.poll(() => page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows)).toBeGreaterThan(0);

    chainRequests.length = 0;
    demandCalls.length = 0;
    // A genuine pointer click on strike 102's profile row on the shared chart
    await clickStrike(page, 102);

    // the page applies a click on its own schedule: wait for the selection, never read it at once
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().selStrike)).toBe(102);
    const state = await page.evaluate(() => window.EdShell.getState());
    expect(state.selExpiry).toBe('2026-09-18');   // NOT null -- the workspace filter, carried through
    await expect.poll(() => chainRequests.length).toBeGreaterThan(0);
    expect(chainRequests.every((e) => e === '2026-09-18')).toBeTruthy();

    // Strike Detail resolved the REAL, vendor-verbatim call AND put symbols for strike 102 at
    // this expiry, and demanded streaming for exactly those -- the complete workflow, not just
    // the numeric strike+expiry handoff.
    //
    // A SEVENTH independent review (2026-09-13), REPRODUCED: this assertion only ever
    // checked CALL_SYM was present -- a regression that dropped PUT_SYM from the demand set
    // entirely (e.g. a call-only bug in the strike-to-contracts resolution) would have passed
    // this test unnoticed. Both legs of the same strike must be demanded together.
    await expect.poll(() => demandCalls.length).toBeGreaterThan(0);
    const lastDemand = demandCalls[demandCalls.length - 1];
    const demanded = [lastDemand.contract, ...(lastDemand.contracts || [])].filter(Boolean);
    expect(demanded).toEqual(expect.arrayContaining([CALL_SYM, PUT_SYM]));
  });

  test('with no expiry filter set, a Chart click leaves selExpiry null (no invented expiry)', async ({ page }) => {
    await intercept(page);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#expSel')).toHaveValue('');
    await expect.poll(() => page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows)).toBeGreaterThan(0);

    await clickStrike(page, 102);
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().selStrike)).toBe(102);
    expect(await page.evaluate(() => window.EdShell.getState().selExpiry)).toBeNull();
  });

  test('the Delta / DEX and Open Interest Chart views draw the served profile of their measure', async ({ page }) => {
    // operator 2026-09-29: "dex has a chart, oi has a chart" -- both views were blank
    await intercept(page);
    for (const [sub, rows, title] of [['dex', STRIKES.measures.dex.rows.length, 'Price + DEX Profile'],
      ['oi', STRIKES.measures.oi.rows.length, 'Price + Open Interest Profile']]) {
      await page.addInitScript((s) => { try { localStorage.setItem('ed_ws', 'options'); localStorage.setItem('ed_sub', s);
        localStorage.setItem('ed_view', 'chart'); localStorage.setItem('ed_scope', 'all'); } catch (e) {} }, sub);
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#mvTitle')).toHaveText(title);
      await expect.poll(() => page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows)).toBe(rows);
      await expect(page.locator('#chartBody .chart-legend')).toContainText('largest |' + (sub === 'oi' ? 'OI' : 'DEX') + '| 100');
    }
  });
});
