/*
 * Trade Desk (Desk + Right Now) renders what the server serves and computes nothing (P1-3, PR B,
 * 2026-09-27): the attention queue is /api/desk/events (numbered, ordered, window-counted on the
 * server); book side, tape side, flip relation, wall distances, spot-vs-zones, levels by distance
 * and the positioning migration are served fields. Level crosses are real SPY rows
 * (tests/fixtures/real_spy_level_crosses.json). Any page error fails the test.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');
const { mockPriceSocket } = require('./fixtures/price_socket');

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
  posture: 'PINNED', levels_stale: false, flip_relation: 'ABOVE', dist_to_call_wall: 3.7, dist_to_put_wall: 6.3, pcr_all: 1.1,
  pcr_by_expiry: { '2026-09-25': 1.1, '2026-10-02': null, '2026-10-09': 0.9 }, atm_iv_pct_by_expiry: { '2026-09-25': 14.2, '2026-10-02': 15.1 } };
const LEVELS = { ticker: 'SPY', spot: SPOT, tf: '30', generation: 1, vwap_series: [],
  levels: [
    { id: 'PDH', price: 773.5, family: 'prior_day', label: 'Prior Day High', short: 'PDH', evidence_tier: 'MEASURED', distance: 2.2, side: 'ABOVE', },
    { id: 'max_pain', price: 770, family: 'gamma', label: 'Max pain', short: 'Max pain', evidence_tier: 'DERIVED', distance: -1.3, side: 'BELOW', },
  ],
  by_distance: ['max_pain', 'PDH'], families_absent: [], degraded: [],
  volume_profile: { basis: 'RTH 1-minute bars, each bar\'s volume spread evenly over its range (not trade prints)', tick_size: 0.01,
    bins: [[769.99, 1200, false], [770.0, 5000, true], [770.01, 3000, true]], poc: 770.0, vah: 770.01, val: 770.0 } };
const MICRO = { ticker: 'SPY', venue: 'NASDAQ_BOOK', status: 'ok', top_of_book: { bid: 771.29, ask: 771.31, bid_size: 300, ask_size: 200 },
  spread_pts: 0.02, depth: { '1': { imbalance: 0.2, side: 'BID' }, '5': { bid_total: 3000, ask_total: 2000, imbalance: 0.2, side: 'BID' } },
  depth_pressure: { bid: [{ price: 771.29, volume: 300, cum: 300 }, { price: 771.28, volume: 900, cum: 1200 }], ask: [{ price: 771.31, volume: 200, cum: 200 }] },
  ages: { book_age_sec: 1, book_stale: false }, wall_candidates: [], provenance: { book_source: 'NASDAQ_BOOK' },
  flow: { tape_pressure_5m: 0.3, tape_side_5m: 'BUY', tape_pressure_30s: 0.1, tape_pressure_2m: 0.2, cum_delta_proxy: 1000 } };
// the pivot zone below spot was named "support" by type-guessing on the page: each zone's label and
// side are served (liquidity_models.ZONE_DISPLAY)
const LIQ = { ticker: 'SPY', zones: [{ zone_low: 772, zone_high: 773, zone_type: 'resistance_liquidity', zone_label: 'Resistance', zone_side: 'resistance', confluence_score: 3 },
  { zone_low: 768, zone_high: 769, zone_type: 'pivot_value', zone_label: 'Pivot / value', zone_side: 'value', confluence_score: 2 }],
  spot_location: { inside: null, above: 0, below: 1 }, summary: null };
const STRIKES = { ticker: 'SPY', spot: SPOT, spot_strike: 771, today_source: 'terrain_live_cache', levels_stale: false,
  today: { all: [[770, 500000, 1000], [771, 900000, 5000], [772, -200000, 3000]] }, prior: { all: [[770, 400000, 800], [771, 700000, 2000], [772, -100000, 900]] },
  migration: { all: { compared: true, drift: 'UP', grew: [771, 770], shrank: [772], busiest: [771, 772], busiest_vs_walls: 'INSIDE_WALLS',
    volume_total: 9000, rows: [[770, 500000, 400000, 100000], [771, 900000, 700000, 200000], [772, -200000, -100000, -100000]] } } };
const BARS = { ticker: 'SPY', tf: '30', bars: [{ t: 1790343000, o: 770, h: 772, l: 769, c: SPOT, v: 1000, chg: SPOT - 770, chg_pct: (SPOT - 770) / 770 * 100 }],
  last_bar: { t: 1790343660, label: 'Fri 09/25 09:21 AM CT' } };

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
    /^order-flow\/microstructure\?/, /^bars1m\?.*tf=5/, /^bars1m\?.*tf=1&/]) expect(count(re), String(re)).toBe(1);

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

  test('Desk: the served queue, counts, book side, tape side and flip relation', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmQueue .tdm-q')).toHaveCount(3);
    await expect(page.locator('#tdmQueueCount')).toHaveText('3');
    await expect(page.locator('#tdmCardLiq')).toContainText('BID HEAVY');
    // Schwab sends no trade side: the Order Flow card claims none (operator 2026-09-29)
    await expect(page.locator('#tdmCardFlow')).not.toContainText(/NET BUYING|NET SELLING|tick rule|PROXY|delta/i);
    await expect(page.locator('#tdmCardFlow')).toContainText(EVENTS.cross_counts.up + ' up · ' + EVENTS.cross_counts.down + ' down');
    // the window's words are the server's (a page copy of the lookback table: register P-15)
    await expect(page.locator('#tdmCardFlow')).toContainText('Crosses (this session (served))');
    await expect(page.locator('#tdmLookback')).toHaveText('this session (served)');
    await expect(page.locator('#tdmAgree')).toContainText('Above flip');
    // the served session volume profile, every bin drawn at the chart's left edge, with its basis
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.volumeProfileBins)).toBe(LEVELS.volume_profile.bins.length);    await expect(page.locator('#tdmProfNote')).toHaveText(LEVELS.volume_profile.basis);
    // each card draws its served series in the reference's chart type (2026-09-28): depth areas,
    // volume bars, and lines for put/call OI and ATM IV by expiry (a null expiry breaks the line)
    await expect(page.locator('#tdmCardLiq .tdm-plot svg path')).toHaveCount(4);
    await expect(page.locator('#tdmCardFlow .tdm-plot svg rect')).toHaveCount(BARS.bars.length);
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

  test('Market Map: the served last completed bar; a price tick moves the live LAST line and reads no bars', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    const barReads = [];
    page.on('request', (r) => { if (r.url().includes('/api/bars1m')) barReads.push(r.url()); });
    await mockPriceSocket(page, []);            // the daemon answers what SPY is (its served key)
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
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'liquidity' } })));
    await expect.poll(() => barReads.length).toBeGreaterThan(before);
    expect(errs).toEqual([]);
  });

  test('Market Map: a pinned bar shows its served change (the chart kept the bar without it)', async ({ page }) => {
    // 2026-09-28 (ONE-16): the chart copied each served bar without chg/chg_pct, so the pinned
    // readout's "Bar change" always read "—" while the legend recomputed close - open.
    const errs = watchErrors(page);
    await intercept(page);
    // 60 served 30-minute bars, each with its served change (0.25 each), so a click lands on one
    const bars = Array.from({ length: 60 }, (_v, i) => ({ t: 1790343000 - (59 - i) * 1800, o: 770 + i * 0.1,
      h: 771 + i * 0.1, l: 769 + i * 0.1, c: 770.25 + i * 0.1, v: 1000, chg: 0.25, chg_pct: 0.0325 }));
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
      else if (url.includes('/api/terrain/strikes')) body = Object.assign({}, STRIKES, { today_side_sums: { gex_below: -1.2e9, gex_above: 8e8 } });
      else if (url.includes('/api/forces')) body = { ticker: 'SPY', available: true, doi_below: 1200, doi_above: -300,
        dex_below_dollars: 5e8, dex_above_dollars: -2e8, charm_below: 0.0123, charm_above: -0.0045 };
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
    await expect(page.locator('#tdmCardOpt')).toContainText('GEX below / above');
    await expect(page.locator('#tdmCardOpt')).toContainText('1200 / -300');          // ΔOI, served
    await expect(page.locator('#tdmCardOpt')).toContainText('0.0123 / -0.0045');     // charm, served
    await page.locator('#tdmStyle').click();
    await expect(page.locator('#tdmStyle')).toHaveClass(/on/);
    expect(errs).toEqual([]);
  });
});
