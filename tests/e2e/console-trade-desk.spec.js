/*
 * Trade Desk (Desk + Right Now) renders what the server serves and computes nothing (P1-3, PR B,
 * 2026-09-27): the attention queue is /api/desk/events (numbered, ordered, window-counted on the
 * server); book side and imbalance, flip relation, wall distances, spot-vs-zones, levels by distance
 * and the positioning migration are served fields. Level crosses are real SPY rows
 * (tests/fixtures/real_spy_level_crosses.json). Any page error fails the test.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');
const { mockPriceSocket, priceRow } = require('./fixtures/price_socket');

const CROSSES = require(path.join(__dirname, '..', 'fixtures', 'real_spy_level_crosses.json')).rows.slice(0, 3);
const EVENTS = {
  ticker: 'SPY', tf: '30', window_start_ts_utc: CROSSES[2].ts_utc - 60, window_label: 'this session (served)',
  // the served shape (server.get_desk_events): each cross as recorded, at its level's price
  items: CROSSES.map((c, i) => ({ key: 'x' + c.cross_id, n: 3 - i, ts: c.ts_utc, dom: 'LEVELS', dir: c.direction, marker: true,
    price: c.level_value, title: 'Crossed ' + (c.direction === 'up' ? 'above ' : 'below ') + c.level_name,
    detail: c.level_value.toFixed(2), src: 'level_crosses' })),
  cross_counts: { up: CROSSES.filter((c) => c.direction === 'up').length, down: CROSSES.filter((c) => c.direction !== 'up').length },
};
const SPOT = 771.3;
const TERRAIN = { ticker: 'SPY', spot: SPOT, gamma_flip: 768, call_wall: 775, put_wall: 765, max_pain: 770, regime: 'LONG_GAMMA',
  posture: 'PINNED', levels_state: 'live', levels_stale: false, flip_relation: 'ABOVE', dist_to_call_wall: 3.7, dist_to_put_wall: 6.3,
  call_wall_relation: 'BELOW', put_wall_relation: 'ABOVE', pcr_all: 1.1,
  pcr_by_expiry: { '2026-09-25': 1.1, '2026-10-02': null, '2026-10-09': 0.9 }, atm_iv_pct_by_expiry: { '2026-09-25': 14.2, '2026-10-02': 15.1 } };
const LEVELS = { ticker: 'SPY', spot: SPOT, tf: '30', generation: 1, vwap_series: [], snapshot_age_sec: 45,
  session_levels: { state: 'current', stale: false, reason: '' },
  levels: [
    { id: 'PDH', price: 773.5, family: 'prior_day', label: 'Prior Day High', short: 'PDH', evidence_tier: 'MEASURED', distance: 2.2, side: 'ABOVE', },
    { id: 'max_pain', price: 770, family: 'gamma', label: 'Max pain', short: 'Max pain', evidence_tier: 'DERIVED', distance: -1.3, side: 'BELOW', },
  ],
  by_distance: ['max_pain', 'PDH'],
  families_absent: [{ family: 'overnight', reason: 'the overnight session is not stored' }],
  degraded: [{ family: 'prior_day', reason: 'prior session holds only 180 RTH bars' }],
  volume_profile: { basis: 'RTH 1-minute bars, each bar\'s volume spread evenly over its range (not trade prints)', tick_size: 0.01,
    bins: [[769.99, 1200, false], [770.0, 5000, true], [770.01, 3000, true]], poc: 770.0, vah: 770.01, val: 770.0 } };
const MICRO = { ticker: 'SPY', venue: 'NASDAQ_BOOK', status: 'ok', top_of_book: { bid: 771.29, ask: 771.31, bid_size: 300, ask_size: 200 },
  // imbalance_disp differs from imbalance on purpose: the page prints the served text, and
  // arithmetic on the number would print +21.0%
  spread_pts: 0.02, depth: { '1': { imbalance: 0.2, side: 'BID' }, '5': { bid_total: 3000, ask_total: 2000, imbalance: 0.21, imbalance_disp: '+20.0%', side: 'BID' } },
  depth_pressure: { bid: [{ price: 771.29, volume: 300, cum: 300 }, { price: 771.28, volume: 900, cum: 1200 }], ask: [{ price: 771.31, volume: 200, cum: 200 }] },
  ages: { book_age_sec: 1, book_stale: false }, wall_candidates: [], provenance: { book_source: 'NASDAQ_BOOK' } };
// the pivot zone below spot was named "support" by type-guessing on the page: each zone's label and
// side are served (liquidity_models.ZONE_DISPLAY), with the value context, the time the zones are
// as of and each input they lacked (server.get_liquidity_snapshot)
const LIQ = { ticker: 'SPY', zones: [{ zone_low: 772, zone_high: 773, zone_type: 'resistance_liquidity', zone_label: 'Resistance', zone_side: 'resistance', confluence_score: 3,
    source_levels: [{ label: 'TODAY_VAH', value: 772.22 }] },
  { zone_low: 768, zone_high: 769, zone_type: 'pivot_value', zone_label: 'Pivot / value', zone_side: 'value', confluence_score: 2,
    source_levels: [{ label: 'PD_POC', value: 768.5 }] }],
  spot_location: { inside: null, above: 0, below: 1 },
  summary: { value_state: 'shifted_higher', value_state_reason: null, vwap_relation: null, vwap_relation_reason: 'no value area today' },
  absent: [{ input: 'PDC', reason: 'CLOSE_PRICE is not streaming live' }], levels_as_of: 'Fri 09/25 03:00 PM CT',
  option_levels: { levels_source: 'wide_chain_loop', levels_state: 'live', levels_stale: false, levels_age_sec: 43, levels_stale_reason: '' } };
const STRIKES = { ticker: 'SPY', spot: SPOT, spot_strike: 771, today_source: 'terrain_live_cache', levels_state: 'live', levels_stale: false,
  today: { all: [[770, 500000, 1000], [771, 900000, 5000], [772, -200000, 3000]] }, prior: { all: [[770, 400000, 800], [771, 700000, 2000], [772, -100000, 900]] },
  migration: { all: { compared: true, drift: 'UP', grew: [771, 770], shrank: [772], busiest: [771, 772], busiest_vs_walls: 'INSIDE_WALLS',
    volume_total: 9000, rows: [[770, 500000, 400000, 100000], [771, 900000, 700000, 200000], [772, -200000, -100000, -100000]] } } };
const BARS = { ticker: 'SPY', tf: '30', bars: [{ t: 1790343000, o: 770, h: 772, l: 769, c: SPOT, v: 1000, chg: SPOT - 770, chg_pct: (SPOT - 770) / 770 * 100 }],
  last_bar: { t: 1790343660, label: 'Fri 09/25 09:21 AM CT' },
  // the newest hour of 1-minute bars, served with the history (the Order Flow card's)
  recent_1m: [{ t: 1790343600, o: 770.5, h: 771, l: 770, c: 770.8, v: 300, chg: 0.3, chg_pct: 0.04 },
    { t: 1790343660, o: 770.8, h: 771.4, l: 770.7, c: SPOT, v: 200, chg: 0.5, chg_pct: 0.06 }] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/desk/events')) body = Object.assign({}, EVENTS, { tf: new URL(url).searchParams.get('tf') });
    else if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/levels')) body = LEVELS;
    else if (url.includes('/api/order-flow/microstructure')) body = MICRO;
    else if (url.includes('/api/liquidity-snapshot')) body = LIQ;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/order-flow/book-heatmap')) body = HEAT;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
const HEAT = require(path.join(__dirname, 'fixtures', 'book_heatmap_payload.json'));

test('every chart is the one TradingView-style chart, with its controls', async ({ page }) => {
  // operator 2026-09-28: "each and every chart in the app needs to use the same TV controls" --
  // the Gamma chart (SVG), the book heatmap (canvas) and the liquidity map (DOM) each had their
  // own pan/zoom code; each now draws on ed-tv-chart.js (.tvc, its A / L controls, click-to-pin)
  const errs = watchErrors(page);
  await intercept(page);
  const views = [['trade-desk', 'desk', '', '#tdmChart'], ['options', 'gamma', 'chart', '#chartBody'],
    ['order-flow', 'heatmap', '', '#ofhBody'], ['liquidity', 'map', '', '#liqmBody']];
  for (const [ws, sub, view, host] of views) {
    await page.addInitScript(([w, s, v]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); } catch (e) {} }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator(host + ' .tvc-auto'), ws + '/' + sub).toBeVisible();
    await expect(page.locator(host + ' .tvc-log'), ws + '/' + sub).toBeVisible();
  }
  // the liquidity map draws the served zones and shows the prior-day level from /api/levels: a line
  // when it is inside the candles' price range, else named at the pane's edge (PDH 773.50 is above
  // this fixture's one bar, 769-772; the scale fits the candles, 2026-09-29)
  await expect.poll(() => page.evaluate(() => (window.EdLiquidityMap.state() || {}).zones)).toBe(LIQ.zones.length);
  await expect.poll(() => page.evaluate(() => ((window.EdLiquidityMap.state() || { levels: [] }).levels.join(' ') + ' ' +
    document.querySelector('#liqmBody .tvc-edge-top').textContent))).toContain('PDH');
  expect(errs).toEqual([]);
});

// 2026-09-29 RTH, measured in the operator's browser: a fresh desk load asked for every value twice
// (start() ran on ed:view and ed:ticker; the second saw no bars yet and loaded again), and a
// timeframe switch re-asked for the terrain, zones, strikes, forces and flow bars, none of which
// depend on the timeframe -- 6.8 s to redraw.
test('a desk load asks for each value once; a timeframe switch asks only for that timeframe and says it is loading', async ({ page }) => {
  const errs = watchErrors(page);
  await intercept(page);
  const asked = [];
  page.on('request', (r) => { const u = r.url(); if (u.includes('/api/')) asked.push(u.split('/api/')[1]); });
  let releaseBars;
  const barsHeld = new Promise((r) => { releaseBars = r; });
  await page.route(/\/api\/bars1m\?.*tf=15/, async (route) => { await barsHeld;
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(Object.assign({}, BARS, { tf: '15' })) }); });
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '5'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars)).toBeGreaterThan(0);
  await page.waitForTimeout(500);
  const count = (re) => asked.filter((u) => re.test(u)).length;
  for (const re of [/^levels\?/, /^desk\/events\?/, /^terrain\?/, /^liquidity-snapshot\?/, /^terrain\/strikes\?/, /^forces\?/,
    /^order-flow\/microstructure\?/, /^bars1m\?/]) expect(count(re), String(re)).toBe(1);
  // the Order Flow card's hour comes with the chart's history (recent_1m): no request of its own
  expect(count(/^bars1m\?.*tf=1&/)).toBe(0);

  asked.length = 0;
  await page.locator('#tdmToolbar [data-tf="15"]').click();
  // while the 15m bars are on their way the 5m view is gone and the chart says what is loading
  await expect(page.locator('#tdmChartEmpty')).toHaveText(/Loading SPY · 15m/);
  expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.bars)).toBe(0);
  expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers.length)).toBe(0);
  releaseBars();
  await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.tf)).toBe('15');
  await page.waitForTimeout(500);
  expect(asked.filter((u) => !/^(changes|streaming\/)/.test(u)).map((u) => u.split('?')[0]).sort())
    .toEqual(['bars1m', 'desk/events', 'levels']);
  expect(errs).toEqual([]);
});

test('the liquidity map fits its price scale to the candles; a far zone does not flatten them', async ({ page }) => {
  // 2026-09-29 RTH: SPY's served zones at 750 and 800 joined the auto-fit, the scale ran 735-805
  // and the candles (765) were a flat line
  const errs = watchErrors(page);
  await intercept(page);
  const far = { zone_low: 800, zone_high: 801, zone_type: 'resistance_liquidity', zone_label: 'Resistance', zone_side: 'resistance', confluence_score: 1 };
  await page.route('**/api/liquidity-snapshot**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify(Object.assign({}, LIQ, { zones: LIQ.zones.concat([far]) })) }));
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity'); localStorage.setItem('ed_sub', 'map'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => (window.EdLiquidityMap.state() || {}).zones)).toBe(LIQ.zones.length + 1);
  const st = await page.evaluate(() => window.EdLiquidityMap.state());
  expect(st.priceTop).toBeLessThan(far.zone_low);          // the bar's range (769-772) sets the scale
  expect(errs).toEqual([]);
});

test('the liquidity map prints when its zones are as of and what they lacked; its live line is the pushed price', async ({ page }) => {
  // 2026-09-30 audit: the map's LAST line was the spot the levels request happened to carry, with
  // no age, and stayed there; the zone list named no time and no missing input
  const errs = watchErrors(page);
  await intercept(page);
  await mockPriceSocket(page, [priceRow('SPY', SPOT + 0.4)]);
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity'); localStorage.setItem('ed_sub', 'map'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const zones = page.locator('#liqmBody .liqm-zones');
  await expect(zones.locator('.liqm-inputs')).toContainText('bars as of ' + LIQ.levels_as_of);
  await expect(zones.locator('.liqm-inputs')).toContainText('option levels · 43s');
  await expect(zones.locator('.liqm-absent')).toHaveText('PDC: CLOSE_PRICE is not streaming live');
  await expect(zones.locator('.liqm-tags').first()).toHaveText('TODAY_VAH 772.22');
  await expect.poll(() => page.evaluate(() => (window.EdLiquidityMap.state() || {}).livePrice)).toBeCloseTo(SPOT + 0.4, 6);
  expect((await page.evaluate(() => window.EdLiquidityMap.state())).liveTitle).toBe('LAST · 1s');
  expect(errs).toEqual([]);
});

test('the liquidity map says when the option levels in its zones are stale, or as of when after the close', async ({ page }) => {
  // measured 2026-09-30 11:51 ET on the running app: SNDK's zones were fused with option levels
  // computed 84 minutes earlier, which /api/terrain called stale, and the map's route said only
  // "live / fused" (1 of 44 tickers at that moment)
  const errs = watchErrors(page);
  await intercept(page);
  const why = 'levels are 5045s old; the refresh loop is running but has not reached this ticker in two of its cycles (65s each)';
  let option = { levels_source: 'wide_chain_loop', levels_state: 'stale', levels_stale: true, levels_age_sec: 5045, levels_stale_reason: why };
  await page.route('**/api/liquidity-snapshot**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify(Object.assign({}, LIQ, { absent: [], option_levels: option })) }));
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity'); localStorage.setItem('ed_sub', 'map'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const zones = page.locator('#liqmBody .liqm-zones');
  await expect(zones.locator('.liqm-inputs .asof.stale')).toHaveText('option levels · 84m · STALE');
  await expect(zones.locator('.liqm-absent')).toHaveText('option levels: ' + why);
  await expect(zones.locator('.liqm-inputs')).toContainText('bars as of ' + LIQ.levels_as_of);   // the bars keep their own time
  option = { levels_source: 'wide_chain_loop', levels_state: 'closed', levels_stale: false, levels_age_sec: 60000, levels_stale_reason: '', levels_market_closed: true, levels_as_of: 'Fri 09/25 03:15 PM CT' };
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(zones.locator('.liqm-inputs .asof.ref')).toHaveText('option levels as of Fri 09/25 03:15 PM CT');
  await expect(zones.locator('.liqm-absent')).toHaveCount(0);
  // no option levels in the zones: no option-levels time is printed
  option = null;
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(zones.locator('.liqm-inputs')).toHaveText('bars as of ' + LIQ.levels_as_of);
  expect(errs).toEqual([]);
});

test('the Gamma chart and the liquidity map carry the Trade Desk toolbar; a timeframe click redraws at that timeframe', async ({ page }) => {
  // operator 2026-09-29: "for all other charts you were supposed to apply the tv characteristics" --
  // only the Trade Desk had the timeframes, candles/line, drawing tools, reset, screenshot and full screen
  const errs = watchErrors(page);
  await intercept(page);
  const asked = [];
  await page.route('**/api/bars1m**', (route) => { const tf = new URL(route.request().url()).searchParams.get('tf'); asked.push(tf);
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(Object.assign({}, BARS, { tf })) }); });
  for (const [ws, sub, view, host, api] of [['options', 'gamma', 'chart', '#chartBody', 'EdGammaChart'], ['liquidity', 'map', '', '#liqmBody', 'EdLiquidityMap']]) {
    await page.addInitScript(([w, s, v]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); } catch (e) {} }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    for (const sel of ['[data-act="style"]', '[data-tool="hline"]', '[data-act="reset"]', '[data-act="shot"]', '[data-act="full"]'])
      await expect(page.locator(host + ' .tvc-toolbar ' + sel), ws + ' ' + sel).toBeVisible();
    asked.length = 0;
    await page.locator(host + ' .tvc-toolbar [data-tf="15"]').click();
    await expect(page.locator(host + ' .tvc-toolbar [data-tf="15"]')).toHaveClass(/on/);
    await expect.poll(() => page.evaluate((a) => (window[a].state() || {}).tf, api), ws).toBe('15');
    expect(asked, ws).toContain('15');
  }
  expect(errs).toEqual([]);
});

test('the Gamma chart and the liquidity map draw each bar the daemon pushes, at their timeframe, with no read', async ({ page }) => {
  // the charts read /api/bars1m again after every completed minute (the console's `liquidity`
  // push); the daemon now pushes the chart bar itself (live_ui {type:'bars'})
  const errs = watchErrors(page);
  await intercept(page);
  const asked = [];
  await page.route('**/api/bars1m**', (route) => { const tf = new URL(route.request().url()).searchParams.get('tf'); asked.push(tf);
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(Object.assign({}, BARS, { tf })) }); });
  const daemon = await mockPriceSocket(page, []);
  for (const [ws, sub, view, api] of [['options', 'gamma', 'chart', 'EdGammaChart'], ['liquidity', 'map', '', 'EdLiquidityMap']]) {
    await page.addInitScript(([w, s, v]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); } catch (e) {} }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const bars = () => page.evaluate((a) => (window[a].state() || {}).bars, api);
    await expect.poll(bars, ws).toBe(BARS.bars.length);
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    const tf = await page.evaluate((a) => window[a].state().tf, api);
    const reads = asked.length;
    const next = { t: BARS.bars[0].t + 3600, o: 771, h: 772, l: 770.5, c: 771.8, v: 900, chg: 0.8, chg_pct: 0.1 };
    const byTf = {}; ['1', '3', '5', '15', '30', '60', 'D'].forEach((k) => { byTf[k] = next; });
    daemon.send({ type: 'bars', bars: [{ ticker: 'SPY', ts_recv: next.t + 62.7, last_bar: { t: next.t, label: 'Fri 09/25 10:21 AM CT' }, tf: byTf }] });
    await expect.poll(bars, ws + ' ' + tf).toBe(BARS.bars.length + 1);
    await page.waitForTimeout(300);
    expect(asked.length, ws).toBe(reads);
  }
  expect(errs).toEqual([]);
});

function watchErrors(page) {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  return errs;
}

test.describe('Trade Desk renders served values', () => {
  test('Desk after the close: levels drawn from the served order, named from the last trade; dark by default', async ({ page }) => {
    // 2026-09-28 21:40 ET: after the close /api/levels served an empty by_distance and the chart drew
    // no key level; the server now orders them from the last trade and names it (by_distance_ref)
    const errs = watchErrors(page);
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = { available: false };
      if (url.includes('/api/levels')) body = Object.assign({}, LEVELS, { spot: null,
        levels: LEVELS.levels.map((l) => Object.assign({}, l, { distance: null, side: null })),
        by_distance_ref: { price: SPOT, source: 'last trade', as_of: 'Fri 09/25 03:59 PM CT' } });
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('dark');
    await expect(page.locator('#tdmLevelsRef')).toHaveText('Levels nearest the last trade ' + SPOT.toFixed(2) + ' (Fri 09/25 03:59 PM CT)');
    // max pain (770) is inside the one bar's price range; PDH (773.50) is above it, pinned at the edge
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown)).toBe(1);
    await expect(page.locator('#tdmChart .tvc-edge-top')).toContainText('PDH 773.50');
    // the profile is drawn after the close too (the session's served profile) and names its basis
    await expect(page.locator('#tdmProfNote')).toHaveText(LEVELS.volume_profile.basis);
    expect(errs).toEqual([]);
  });

  test('Desk: the levels are drawn when they arrive, not held for the event queue', async ({ page }) => {
    // 2026-09-29 14:52 CT, deployed: QQQ's levels answered in 28 ms and were drawn after 1.34 s,
    // when /api/desk/events answered
    const errs = watchErrors(page);
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      if (url.includes('/api/desk/events')) return;               // the event queue has not answered
      let body = { available: false };
      if (url.includes('/api/levels')) body = LEVELS;
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown)).toBeGreaterThan(0);
    await expect(page.locator('#tdmQueue')).toContainText('Loading');
    expect(errs).toEqual([]);
  });

  test('Desk: before the session starts the LEVELS pill reads NOT STARTED with the served reason', async ({ page }) => {
    // premarket the pill showed the prior session's newest bar age in green (it read only
    // session_levels.stale); it prints the served state and reason (server.price_level_staleness)
    const why = "today's session has not started: its first 1-minute bar ends Wed 09/30 08:16 AM CT";
    const errs = watchErrors(page);
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = { available: false };
      if (url.includes('/api/levels')) body = Object.assign({}, LEVELS, { degraded: [], snapshot_age_sec: 56700,
        session_levels: { state: 'session_not_started', stale: false, reason: why } });
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const pill = page.locator('#tdmTrust .tdm-pill', { hasText: 'LEVELS' });
    await expect(pill).toContainText('NOT STARTED');
    await expect(pill).toHaveAttribute('title', why);
    await expect(pill).toHaveClass(/warn/);
    await expect(pill).not.toHaveClass(/ok/);
    expect(errs).toEqual([]);
  });

  test('Desk: session levels whose bars stopped read STALE with the served reason', async ({ page }) => {
    // /api/levels served the session levels with no stale rule; it now judges them by their bars
    // (server.price_level_staleness) and the LEVELS pill prints the served state and reason
    const why = 'no 1-minute bar has arrived since the one ending Tue 09/29 09:30 AM CT; the bar ending Tue 09/29 09:32 AM CT is due';
    const errs = watchErrors(page);
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = { available: false };
      if (url.includes('/api/levels')) body = Object.assign({}, LEVELS, { degraded: [],
        session_levels: { state: 'stale', stale: true, reason: why } });
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const pill = page.locator('#tdmTrust .tdm-pill', { hasText: 'LEVELS' });
    await expect(pill).toContainText('STALE');
    await expect(pill).toHaveAttribute('title', why);
    await expect(pill).toHaveClass(/warn/);
    expect(errs).toEqual([]);
  });

  test('Desk: the served queue, counts, book side and imbalance, and flip relation', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmQueue .tdm-q')).toHaveCount(3);
    await expect(page.locator('#tdmQueueCount')).toHaveText('3');
    await expect(page.locator('#tdmCardLiq')).toContainText('BID HEAVY');
    await expect(page.locator('#tdmCardLiq .tdm-hero span')).toHaveText(MICRO.depth['5'].imbalance_disp);
    // Schwab sends no trade side: the Order Flow card claims none (operator 2026-09-29)
    await expect(page.locator('#tdmCardFlow')).not.toContainText(/NET BUYING|NET SELLING|tick rule|PROXY|delta/i);
    await expect(page.locator('#tdmCardFlow')).toContainText(EVENTS.cross_counts.up + ' up · ' + EVENTS.cross_counts.down + ' down');
    // the window's words are the server's (a page copy of the lookback table: register P-15)
    await expect(page.locator('#tdmCardFlow')).toContainText('Crosses (this session (served))');
    await expect(page.locator('#tdmLookback')).toHaveText('this session (served)');
    await expect(page.locator('#tdmAgree')).toContainText('Above flip');
    // the value context is the served state, or the served reason there is none
    await expect(page.locator('#tdmAgree')).toContainText('shifted higher');
    await expect(page.locator('#tdmAgree')).toContainText(LIQ.summary.vwap_relation_reason);
    // a level family with no value keeps its button and says why; the LEVELS pill is the served age
    const overnight = page.locator('#tdmFamilies [data-fam="overnight"]');
    await expect(overnight).toHaveClass(/absent/);
    await expect(overnight).toHaveAttribute('title', 'Not available: ' + LEVELS.families_absent[0].reason);
    await expect(overnight).toContainText('not available');
    const pill = page.locator('#tdmTrust .tdm-pill', { hasText: 'LEVELS' });
    await expect(pill).toContainText('45s');
    await expect(pill).toHaveAttribute('title', 'prior_day: ' + LEVELS.degraded[0].reason);
    // the served session volume profile, every bin drawn at the chart's left edge, with its basis
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.volumeProfileBins)).toBe(LEVELS.volume_profile.bins.length);    await expect(page.locator('#tdmProfNote')).toHaveText(LEVELS.volume_profile.basis);
    // each card draws its served series in the reference's chart type (2026-09-28): depth areas,
    // volume bars, and lines for put/call OI and ATM IV by expiry (a null expiry breaks the line)
    await expect(page.locator('#tdmCardLiq .tdm-plot svg path')).toHaveCount(4);
    await expect(page.locator('#tdmCardFlow .tdm-plot svg rect')).toHaveCount(BARS.recent_1m.length);   // the served hour
    await expect(page.locator('#tdmCardOpt .tdm-plot svg path')).toHaveCount(2);
    await expect(page.locator('#tdmCardVol .tdm-plot svg path')).toHaveCount(1);
    await expect(page.locator('#tdmCardVol figcaption')).toHaveText('ATM implied vol by expiry, nearest first');
    await expect(page.locator('#tdmAgree')).toContainText('Bid heavy');
    expect(errs).toEqual([]);
  });

  test('Desk: each chart marker is its queue entry, and selecting the entry selects that marker', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const want = EVENTS.items.filter((it) => it.marker).map((it) => it.key).sort();
    await expect.poll(async () => ((await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers)) || []).slice().sort()).toEqual(want);
    const key = EVENTS.items[1].key;
    await page.locator('#tdmQueue [data-q="' + key + '"]').click();
    await expect(page.locator('#tdmQueue [data-q="' + key + '"]')).toHaveClass(/sel/);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected)).toBe(key);
    // and the other way: a click on a callout's number on the chart selects its queue entry
    const other = EVENTS.items[2].key;
    const all = (await page.evaluate(() => window.EdTradeDeskMap.state().chart.callouts)) || [];
    const c = all.filter((x) => x.id === other)[0];
    expect(c).toBeTruthy();
    // the three crosses share one bar here; no callout's number covers another's
    for (const a of all) for (const b of all) if (a !== b) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(22);
    // the chart may still be settling its opening view: read the number where it is drawn now, click it
    const box = await page.locator('#tdmChart .tvc-plot').boundingBox();
    await expect.poll(async () => {
      const now = ((await page.evaluate(() => window.EdTradeDeskMap.state().chart.callouts)) || []).filter((x) => x.id === other)[0];
      await page.mouse.click(box.x + now.x, box.y + now.y);
      return page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected);
    }).toBe(other);
    await expect(page.locator('#tdmQueue [data-q="' + other + '"]')).toHaveClass(/sel/);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected)).toBe(other);
    expect(errs).toEqual([]);
  });

  test('no proximity alerts anywhere: no strip, no request for them', async ({ page }) => {
    // operator 2026-09-29: remove the alert strip, the queue's alert items and every other
    // presentation of proximity alerts
    const asked = [];
    page.on('request', (r) => { if (r.url().includes('/api/alerts')) asked.push(r.url()); });
    await intercept(page);
    for (const [ws, sub] of [['trade-desk', 'desk'], ['options', 'gamma'], ['liquidity', 'map'], ['order-flow', 'book']]) {
      await page.addInitScript(([w, s]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w); localStorage.setItem('ed_sub', s); } catch (e) {} }, [ws, sub]);
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(400);
      await expect(page.locator('#alertsStrip')).toHaveCount(0);
      await expect(page.locator('body')).not.toContainText(/Proximity Alerts/i);
    }
    expect(asked).toEqual([]);
  });

  test('Desk: selecting a ticker opens its /api/changes connection (the book request)', async ({ page }) => {
    await intercept(page);
    const opened = [];
    page.on('request', (r) => { if (r.url().includes('/api/changes')) opened.push(new URL(r.url()).searchParams.get('ticker')); });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => opened).toContain('SPY');
    await page.evaluate(() => window.EdShell.setTicker('MU'));
    await expect.poll(() => opened).toContain('MU');
    expect(await page.evaluate(() => window.EdStream.setActiveTicker)).toBeUndefined();   // no separate request
  });

  test('Market Map: the wheel over the price axis rescales price (as TradingView); over the plot it does not', async ({ page }) => {
    // operator 2026-09-29: "in tv all you do is scroll [on the price legend] and it will expand the
    // chart vertically; the way you have it you have to click and drag"
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars)).toBeGreaterThan(0);
    const box = await page.locator('#tdmChart').boundingBox();
    const span = async () => page.evaluate(() => { const c = window.EdTradeDeskMap.state().chart; return c.priceTop - c.priceBottom; });
    const before = await span();
    await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2);   // on the price axis
    await page.mouse.wheel(0, 400);
    await expect.poll(span).toBeGreaterThan(before * 1.5);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.autoScale)).toBe(false);
    const widened = await span();
    await page.mouse.move(box.x + box.width / 3, box.y + box.height / 2);    // on the plot: time, not price
    await page.mouse.wheel(0, 400);
    await page.waitForTimeout(200);
    expect(await span()).toBeCloseTo(widened, 6);
  });

  test('Market Map: the served last completed bar; a price tick moves the live LAST line; a completed bar arrives on the daemon\'s push, not a read', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    const barReads = [];
    page.on('request', (r) => { if (r.url().includes('/api/bars1m')) barReads.push(r.url()); });
    const daemon = await mockPriceSocket(page, []);   // the daemon answers what SPY is (its served key)
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    const legend = page.locator('#tdmChart .tvc-legend');
    await expect(legend).toContainText('Last completed bar Fri 09/25 09:21 AM CT');
    const before = barReads.length;
    await page.evaluate((spot) => {
      for (let i = 0; i < 3; i++) window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: { ticker: 'SPY', spot: spot + i / 100,
        spot_disp: (spot + i / 100).toFixed(2), spot_state: 'live', feed_live: true, trade_age_sec: 1 } }));
    }, SPOT);
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).livePrice).toBeCloseTo(SPOT + 0.02, 6);
    expect((await chartState()).liveTitle).toBe('LAST · 1s');
    expect((await chartState()).bars).toBe(BARS.bars.length);          // the candles are untouched
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: { ticker: 'SPY', spot: null,
      spot_disp: null, spot_state: 'unavailable', feed_live: false, trade_age_sec: null } })));
    await expect.poll(async () => (await chartState()).livePrice).toBeNull();   // no line left at an old price
    await page.waitForTimeout(1500);
    expect(barReads.length).toBe(before);
    // the daemon's bar push (live_ui {type:'bars'}): the chart bar the new minute extends, then the
    // next chart bar a later minute opens -- each drawn as pushed, with no read (the same bar at
    // every timeframe here: the desk draws its own timeframe's)
    const pushed = (t, last, c) => {
      const tf = {};
      window_tfs.forEach((id) => { tf[id] = { t: t, o: 770, h: 772.5, l: 769, c: c.close, v: 1500, chg: c.close - 770, chg_pct: 0.1 }; });
      tf['1'] = { t: last, o: c.close, h: c.close, l: c.close, c: c.close, v: 10, chg: 0, chg_pct: 0 };
      // the daemon's newest hour of 1-minute bars (live_price_rows.RECENT_1M_BARS), served whole
      const recent = [{ t: last - 120, o: 770, h: 771, l: 769.5, c: 770.5, v: 20, chg: 0.5, chg_pct: 0.06 },
        { t: last - 60, o: 770.5, h: 771, l: 770, c: 770.6, v: 15, chg: 0.1, chg_pct: 0.01 }, tf['1']];
      return { ticker: 'SPY', ts_recv: last + 62.7, last_bar: { t: last, label: 'Fri 09/25 ' + c.label }, tf: tf, recent_1m: recent };
    };
    const window_tfs = ['3', '5', '15', '30', '60', 'D'];
    daemon.send({ type: 'bars', bars: [pushed(1790343000, 1790343720, { close: 772.4, label: '09:22 AM CT' })] });
    await expect(legend).toContainText('Last completed bar Fri 09/25 09:22 AM CT');
    expect((await chartState()).bars).toBe(BARS.bars.length);          // the same bar, extended
    // the Order Flow card draws the pushed hour as served: no window kept on the page
    await expect(page.locator('#tdmCardFlow .tdm-plot svg rect')).toHaveCount(3);
    daemon.send({ type: 'bars', bars: [pushed(1790344800, 1790344800, { close: 772.1, label: '09:40 AM CT' })] });
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length + 1);
    await expect(legend).toContainText('Last completed bar Fri 09/25 09:40 AM CT');
    // a bar for another symbol is not drawn
    daemon.send({ type: 'bars', bars: [Object.assign(pushed(1790346600, 1790346600, { close: 1, label: '10:10 AM CT' }), { ticker: 'QQQ' })] });
    await page.waitForTimeout(300);
    expect((await chartState()).bars).toBe(BARS.bars.length + 1);
    // a minute Schwab sent late: the daemon pushes no chart bar for it (live_price_rows.bar_update),
    // only the Order Flow hour that holds it; the chart is untouched and nothing raises
    daemon.send({ type: 'bars', bars: [Object.assign(pushed(1790344800, 1790344740, { close: 772.0, label: '09:40 AM CT' }), { tf: {} })] });
    await expect(page.locator('#tdmCardFlow .tdm-plot svg rect')).toHaveCount(3);
    await page.waitForTimeout(300);
    expect((await chartState()).bars).toBe(BARS.bars.length + 1);
    expect(barReads.length).toBe(before);
    expect(errs).toEqual([]);
  });

  test('Market Map: a bar whose minutes are not all received reads unavailable with the served missing span', async ({ page }) => {
    // the daemon pushes a bar above 1m only when every minute of it is covered
    // (live_price_rows.bar_update `unavailable`, per timeframe): no partial bar is drawn
    const errs = watchErrors(page);
    await intercept(page);
    const daemon = await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    const chartBars = () => page.evaluate(() => window.EdTradeDeskMap.state().chart.bars);
    await expect.poll(chartBars).toBe(BARS.bars.length);
    const why = "minutes Fri 09/25 08:15 AM CT – Fri 09/25 09:20 AM CT not received from Schwab (Schwab's price history: RuntimeError: HTTP 429 Too Many Requests)";
    const minute = { t: 1790343720, o: 772, h: 772.5, l: 771.9, c: 772.4, v: 10, chg: 0.4, chg_pct: 0.05, label: 'Fri 09/25 09:22 AM CT' };
    const unavailable = { recent_1m: why };
    ['3', '5', '15', '30', '60', 'D'].forEach((tf) => { unavailable[tf] = why; });
    daemon.send({ type: 'bars', bars: [{ ticker: 'SPY', ts_recv: 1790343782.7, last_bar: { t: 1790343720, label: 'Fri 09/25 09:22 AM CT' },
      tf: { '1': minute }, recent_1m: null, unavailable: unavailable }] });
    const legend = page.locator('#tdmChart .tvc-legend');
    await expect(legend).toContainText(why);                          // the desk's 30m chart
    await expect(page.locator('#tdmCardFlow .tdm-plot')).toContainText(why);   // the Order Flow hour
    expect(await chartBars()).toBe(BARS.bars.length);                  // no partial bar drawn
    // a late minute's push (09:21 after 09:22) carries no bar and no reason for this timeframe:
    // the reason stays (setUnavailable(undefined) cleared it)
    daemon.send({ type: 'bars', bars: [{ ticker: 'SPY', ts_recv: 1790343790.0, last_bar: { t: 1790343720, label: 'Fri 09/25 09:22 AM CT' },
      tf: {}, recent_1m: null, unavailable: { recent_1m: why }, notes: {} }] });
    await page.waitForTimeout(300);
    await expect(legend).toContainText(why);
    expect(errs).toEqual([]);
  });

  test('Market Map: the session volume and the daily candle show the one served day volume with its date, and a day Schwab sends no candle for prints why', async ({ page }) => {
    // the day's values are Schwab's day fields on the price row (`day`, live_price_rows.day_candle,
    // operator 2026-10-01): the Order Flow card's session volume and the daily chart's candle
    // read the same served value. Schwab's SPY daily candle of 2026-09-30 (TOTAL_VOLUME 62,110,041,
    // tests/fixtures/real_day_fields_2026_09_30.json), stamped as the day after the bars' last
    // (the stand-in for "today", so the chart places it as its newest).
    const errs = watchErrors(page);
    await intercept(page);
    const day = { t: 1790395200, label: 'Sat 09/26/2026', unavailable: null, bar: { t: 1790395200, o: 766.45, h: 769.41, l: 762.18, c: 762.63, v: 62110041, chg: -3.82,
      chg_pct: -0.4984, label: 'Sat 09/26/2026', v_text: '62.11M' }, volume: 62110041, volume_text: '62.11M',
      absent: {}, as_of: 'Fri 09/25 07:59 PM CT', source: 'Schwab LEVELONE_EQUITIES day fields' };
    const daemon = await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    await page.locator('#tdmToolbar [data-tf="D"]').click();
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.tf)).toBe('D');
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.bars)).toBe(BARS.bars.length);
    await expect.poll(() => daemon.ws !== null).toBe(true);
    daemon.send({ type: 'quotes', rows: [priceRow('SPY', 762.63, { day: day })] });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.bars)).toBe(BARS.bars.length + 1);
    await expect(page.locator('#tdmCardFlow .tdm-hero')).toContainText('62.11M');           // the session volume
    await expect(page.locator('#tdmCardFlow .tdm-hero')).toContainText('Sat 09/26/2026');   // labeled with its date
    await expect(page.locator('#tdmChart .tvc-legend')).toContainText('Vol 62.11M');       // the daily candle's
    // Schwab's fields make no candle for the day (its open, high and low 0 before a regular-session
    // trade): the served reason is printed, and the candle already drawn for that date stays --
    // what Schwab sent is shown (operator 2026-10-01: "if we have it we display it")
    const why = "No daily candle for Sat 09/26/2026: Schwab's open, high and low are 0: no regular-session trade yet (Streamer Guide p.17-18)";
    daemon.send({ type: 'quotes', rows: [priceRow('SPY', 762.63, { day: { t: day.bar.t, label: day.label, bar: null,
      volume: 62110041, volume_text: '62.11M', absent: {}, unavailable: why, as_of: day.as_of, source: day.source } })] });
    await expect(page.locator('#tdmChart .tvc-legend')).toContainText(why);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.bars)).toBe(BARS.bars.length + 1);
    expect(errs).toEqual([]);
  });

  test('Market Map: back from a price-socket drop, the chart names the gap in its live bars and draws no bar for it', async ({ page }) => {
    // live bars are only the ones Schwab sends while the page is connected: after a drop the
    // chart's missing time is named, never filled from the daemon's memory
    const errs = watchErrors(page);
    await intercept(page);
    const barReads = [];
    page.on('request', (r) => { if (r.url().includes('/api/bars1m')) barReads.push(r.url()); });
    const daemon = await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    const chartBars = () => page.evaluate(() => window.EdTradeDeskMap.state().chart.bars);
    await expect.poll(chartBars).toBe(BARS.bars.length);
    expect(daemon.subscribes[0].disconnected_since).toBeUndefined();  // a first subscribe names no gap
    const lastBeat = 1790343700.5;                                     // the daemon's clock
    daemon.send({ type: 'feed', feed: { ts: lastBeat, schwab_socket_open: true }, rows: [] });
    await page.waitForTimeout(200);
    const first = daemon.ws;
    await first.close();                                               // the socket drops
    await expect.poll(() => daemon.subscribes.length).toBe(2);         // the page reconnects
    expect(daemon.subscribes[1].disconnected_since).toBe(lastBeat);
    const reads = barReads.length;
    // the daemon's answer (live_ui.bars_gap), its note as served
    const note = 'No live bars from Fri 09/25 09:21 AM CT to Fri 09/25 09:40 AM CT: this page was disconnected ' +
      'from the price feed, and bars completed then are not drawn. Reopening the chart loads the stored history.';
    daemon.send({ type: 'bars_gap', gap: { from_ts: lastBeat - 2, to_ts: 1790344800, note: note } });
    const legend = page.locator('#tdmChart .tvc-legend');
    await expect(legend).toContainText(note);
    await page.waitForTimeout(300);
    expect(await chartBars()).toBe(BARS.bars.length);                 // no bar drawn for the gap
    expect(barReads.length).toBe(reads);                               // and none read to fill it
    expect(errs).toEqual([]);
  });

  test('Market Map: a pinned bar shows its served change (the chart kept the bar without it)', async ({ page }) => {
    // 2026-09-28 (ONE-16): the chart copied each served bar without chg/chg_pct, so the pinned
    // readout's "Bar change" always read "—" while the legend recomputed close - open.
    const errs = watchErrors(page);
    await intercept(page);
    // 60 served 30-minute bars, each with its served change (0.25 each), so a click lands on one
    const bars = Array.from({ length: 60 }, (_v, i) => ({ t: 1790343000 - (59 - i) * 1800, o: 770 + i * 0.1,
      h: 771 + i * 0.1, l: 769 + i * 0.1, c: 770.25 + i * 0.1, v: 1000, chg: 0.25, chg_pct: 0.0325,
      label: 'served label ' + i }));   // live_price_rows.served_bar: the chart prints it, formats no time
    await page.route('**/api/bars1m**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, BARS, { bars: bars })) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmChart .tvc-legend')).toContainText('Last completed bar');
    const box = await page.locator('#tdmChart .tvc-plot').boundingBox();
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
    const pin = page.locator('#tdmChart .tvc-pin');
    await expect(pin).toBeVisible();
    await expect(pin).toContainText('Bar change+0.25 (+0.03%)');
    await expect(pin.locator('.tvc-pin-h span')).toHaveText(/^served label \d+$/);   // the bar's served label
    expect(errs).toEqual([]);
  });

  test('Desk: the venue switch asks for one Schwab book at a time', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    const reads = [];
    page.on('request', (r) => { if (/\/api\/(order-flow\/microstructure|desk\/events)/.test(r.url())) reads.push(r.url()); });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); localStorage.removeItem('ed_book_venue'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const nyse = page.locator('#tdmCardLiq .bookvenue [data-venue="NYSE_BOOK"]');
    const nasdaq = page.locator('#tdmCardLiq .bookvenue [data-venue="NASDAQ_BOOK"]');
    await expect(nyse).toHaveClass(/on/);
    await expect.poll(() => reads.filter((u) => u.includes('venue=NYSE_BOOK')).length).toBeGreaterThan(1);
    await nasdaq.click();
    await expect(nasdaq).toHaveClass(/on/);
    await expect.poll(() => reads.filter((u) => u.includes('venue=NASDAQ_BOOK')).length).toBeGreaterThan(1);
    expect(reads.every((u) => /venue=(NYSE|NASDAQ)_BOOK/.test(u))).toBe(true);
    expect(errs).toEqual([]);
  });

  test('Right Now: detect, frame, context and the migration read the served fields', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('bid-heavy (NASDAQ_BOOK, depth 5)');
    await expect(body).toContainText('Max pain 770.00');           // nearest by the served by_distance
    await expect(body).toContainText('1.30 below spot');
    await expect(body).toContainText('6.30 above put wall, 3.70 below call wall');
    await expect(body).toContainText('Resistance zone above at 772.00');
    await expect(body).toContainText('Pivot / value zone below at 769.00');
    await expect(body).toContainText('moved UP the chain');
    await expect(body).toContainText('Grew most at 771/770');
    await expect(body).toContainText('inside the wall range');
    await expect(body).toContainText('Session levels' + '45s old');       // the served snapshot age
    expect(errs).toEqual([]);
  });

  test('Right Now: a stale regime is badged STALE with the served reason; after the close it carries its time', async ({ page }) => {
    // 2026-09-30 audit: the Confirm card showed the regime with its confidence and no age, so
    // levels an hour old read like current ones
    const errs = watchErrors(page);
    await intercept(page);
    let t = Object.assign({}, TERRAIN, { confidence: 'TRUSTED', levels_state: 'stale', levels_stale: true, levels_age_sec: 3600,
      levels_stale_reason: 'levels are 3600s old and every refresh since is failing — HTTP 502' });
    await page.route('**/api/terrain?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(t) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const confirm = page.locator('#tdBody .td-stage.td-accent-amber');
    await expect(confirm.locator('.fl-badge')).toHaveText('STALE');
    await expect(confirm).toContainText('levels are 3600s old and every refresh since is failing — HTTP 502');
    t = Object.assign({}, TERRAIN, { confidence: 'TRUSTED', levels_state: 'closed', levels_stale: false, levels_market_closed: true, levels_as_of: 'Fri 09/25 03:15 PM CT' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(confirm).toContainText('Levels' + 'as of Fri 09/25 03:15 PM CT');
    await expect(confirm.locator('.fl-badge')).toHaveText('TRUSTED');
    expect(errs).toEqual([]);
  });

  test('Desk: stale terrain reads STALE with its served reason on the Volatility card and the GAMMA pill', async ({ page }) => {
    // the Volatility card printed stale terrain as "N old" with no STALE label, and the GAMMA pill
    // decided its state on the page from levels_stale; both print the served levels_state
    const why = 'levels are 3600s old and every refresh since is failing — HTTP 502';
    const errs = watchErrors(page);
    await intercept(page);
    await page.route('**/api/terrain?**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, TERRAIN, { levels_state: 'stale', levels_stale: true, levels_age_sec: 3600, levels_stale_reason: why,
        implied_1d_move: { iv_pct_atm: 14.2, points: 6.1, dte_used: 1 } })) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmCardVol .tdm-src')).toHaveText('Schwab option chain · STALE 60m — ' + why);
    await expect(page.locator('#tdmCardOpt .tdm-src')).toHaveText('Schwab option chain · STALE 60m — ' + why);
    const pill = page.locator('#tdmTrust .tdm-pill', { hasText: 'GAMMA' });
    await expect(pill).toContainText('STALE 60m');
    await expect(pill).toHaveAttribute('title', why);
    await expect(pill).toHaveClass(/warn/);
    expect(errs).toEqual([]);
  });

  test('a flip caveat and the regime basis are printed as served on Right Now and the Desk card', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    let t = Object.assign({}, TERRAIN, { regime_basis: 'side of the gamma flip', regime_reason: '',
      gamma_flip_caveat: 'flip level approximate' });
    await page.route('**/api/terrain?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(t) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const confirm = page.locator('#tdBody .td-stage.td-accent-amber');
    await expect(confirm).toContainText('Flip note' + 'flip level approximate');
    await expect(confirm).toContainText('Basis' + 'side of the gamma flip');
    t = Object.assign({}, TERRAIN, { regime_basis: 'side of the gamma flip', regime_reason: 'no gamma flip in the prices searched', gamma_flip_caveat: '' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(confirm).toContainText('No regime' + 'no gamma flip in the prices searched');
    await expect(confirm).not.toContainText('Flip note');
    // a put wall spot has fallen through: the served side, never "above put wall" on a negative
    t = Object.assign({}, TERRAIN, { put_wall: 773, dist_to_put_wall: 1.7, put_wall_relation: 'BELOW' });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdBody')).toContainText('1.70 below put wall, 3.70 below call wall');
    t = Object.assign({}, TERRAIN, { gamma_flip_caveat: 'flip level approximate' });
    await page.addInitScript(() => { try { localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmCardOpt .tdm-rows')).toContainText('* Flip flip level approximate');
    expect(errs).toEqual([]);
  });

  test('no gamma flip: Desk and Right Now print the served reason, never a bare dash', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    // the terrain of a ticker whose curve holds one sign over the prices searched (served fields)
    const noFlip = Object.assign({}, TERRAIN, { gamma_flip: null, gamma_flip_reason: 'none in 655.61–887.00', flip_relation: null });
    await page.route('**/api/terrain?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(noFlip) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmCardOpt .tdm-rows')).toContainText('Flip none in 655.61–887.00');
    await expect(page.locator('#tdmAgree')).toContainText('Flip none in 655.61–887.00');
    await expect(page.locator('#tdmAgree')).not.toContainText(/Above flip|Below flip/);
    await page.addInitScript(() => { try { localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdBody')).toContainText('Gamma flip' + 'none in 655.61–887.00');
    expect(errs).toEqual([]);
  });

  test('spot at the gamma flip: the GAMMA tile says so (served flip_relation AT), on neither side', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    const atFlip = Object.assign({}, TERRAIN, { gamma_flip: SPOT, flip_relation: 'AT' });
    await page.route('**/api/terrain?**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(atFlip) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmAgree')).toContainText('At flip');
    await expect(page.locator('#tdmAgree')).not.toContainText(/Above flip|Below flip/);
    expect(errs).toEqual([]);
  });

  test('Market Map: 3m, line mode, a level beyond the visible range pinned at the edge, and the FORCES split', async ({ page }) => {
    const errs = watchErrors(page);
    const far = { id: 'grc', price: 837.58, family: 'gamma', label: 'GRC', short: 'GRC', evidence_tier: 'DERIVED', distance: 66.28, side: 'ABOVE', };
    const wall = { id: 'call_wall', price: 772, family: 'gamma', label: 'Call wall', evidence_tier: 'DERIVED', distance: 0.7, side: 'ABOVE', };
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = { available: false };
      if (url.includes('/api/desk/events')) body = EVENTS;
      else if (url.includes('/api/terrain/strikes')) body = Object.assign({}, STRIKES, { today_side_sums: { gex_below: -1.2e9, gex_above: 8e8, spot_basis: 771.3 } });
      else if (url.includes('/api/forces')) body = { ticker: 'SPY', available: true, doi_below: 1200, doi_above: -300,
        dex_below_dollars: 5e8, dex_above_dollars: -2e8, charm_below: 0.0123, charm_above: -0.0045,
        basis: "2026-09-24 chain capture against 2026-09-23, split at that capture's price 769.10; open interest compared on 312 strikes" };
      else if (url.includes('/api/terrain')) body = Object.assign({}, TERRAIN, { call_wall: 772, call_wall_lean: 'DEALERS SELL' });
      else if (url.includes('/api/levels')) body = Object.assign({}, LEVELS, { levels: LEVELS.levels.concat([wall, far]),
        by_distance: ['call_wall', 'max_pain', 'PDH', 'grc'] });
      else if (url.includes('/api/order-flow/microstructure')) body = MICRO;
      else if (url.includes('/api/liquidity-snapshot')) body = LIQ;
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmToolbar [data-tf="3"]')).toHaveText('3m');
    await expect(page.locator('#tdmChart .tvc-edge-top')).toContainText('GRC 837.58');
    await expect(page.locator('#tdmCardOpt')).toContainText('GEX below / above 771.30');   // the price it is split at, served
    await expect(page.locator('#tdmCardOpt')).toContainText('1200 / -300');          // ΔOI, served
    await expect(page.locator('#tdmCardOpt')).toContainText('0.0123 / -0.0045');     // charm, served
    // the capture rows say which two captures they are, and at what price they are split
    await expect(page.locator('#tdmCardOpt .tdm-basis')).toHaveText(/^2026-09-24 chain capture against 2026-09-23, split at that capture's price 769\.10/);
    // the card's one line is cut where the card ends (at 1672 px, after P/C OI): the whole line is its hover text
    await expect(page.locator('#tdmCardOpt .tdm-rows')).toHaveAttribute('title', /Call wall 772\.00 · .*ΔOI below \/ above 1200 \/ -300 · .*2026-09-24 chain capture against 2026-09-23/);
    await page.locator('#tdmToolbar [data-act="style"]').click();
    await expect(page.locator('#tdmToolbar [data-act="style"]')).toHaveClass(/on/);
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: 'test-results/trade-desk-1672x941.png', fullPage: false });
    expect(errs).toEqual([]);
  });
});
