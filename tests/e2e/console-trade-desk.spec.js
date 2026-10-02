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
    bins: [[769.99, 1200, false], [770.0, 5000, true], [770.01, 3000, true]], max_volume: 5000, poc: 770.0, vah: 770.01, val: 770.0 } };
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
    volume_total: 9000, rows: [[770, 500000, 400000, 100000], [771, 900000, 700000, 200000], [772, -200000, -100000, -100000]] } },
  views: { all: { centre: 771, max_abs: 900000, max_abs_with_prior: 900000 } } };
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

function watchErrors(page) {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  return errs;
}

test.describe('Trade Desk renders served values', () => {
  test('Desk after the close: levels drawn from the served order; dark by default', async ({ page }) => {
    // 2026-09-28 21:40 ET: after the close /api/levels served an empty by_distance and the chart drew
    // no key level; the spot is now Schwab's last trade at any hour and orders them (by_distance)
    const errs = watchErrors(page);
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = { available: false };
      if (url.includes('/api/levels')) body = LEVELS;
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('dark');
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
        spot_disp: (spot + i / 100).toFixed(2), feed_live: true, trade_age_sec: 1 } }));
    }, SPOT);
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).livePrice).toBeCloseTo(SPOT + 0.02, 6);
    expect((await chartState()).liveTitle).toBe('LAST · 1s');
    expect((await chartState()).bars).toBe(BARS.bars.length);          // the candles are untouched
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: { ticker: 'SPY', spot: null,
      spot_disp: null, feed_live: false, trade_age_sec: null } })));
    await expect.poll(async () => (await chartState()).livePrice).toBeNull();   // Schwab sent no price: no line
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

  test('Right Now re-reads all five reads on every push', async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    const reads = [];
    page.on('request', (r) => {
      const p = new URL(r.url()).pathname;
      if (['/api/order-flow/microstructure', '/api/levels', '/api/terrain', '/api/liquidity-snapshot', '/api/terrain/strikes'].includes(p)) reads.push(p);
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('Max pain 770.00');
    const push = async (kind) => {
      await page.waitForTimeout(300);                    // the first read has settled
      reads.length = 0;
      await page.evaluate((k) => document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: k } })), kind);
      await expect.poll(() => reads.length).toBeGreaterThan(0);
      await page.waitForTimeout(300);                    // every read that push makes has gone out
      return [...new Set(reads)].sort();
    };
    // each read serves values the server derives at read time (the live price, each level's
    // distance, the staleness of the chain), so a push of any kind re-reads every one
    const all = ['/api/levels', '/api/liquidity-snapshot', '/api/order-flow/microstructure', '/api/terrain', '/api/terrain/strikes'];
    for (const kind of ['flow', 'liquidity', 'levels', 'chain']) expect(await push(kind)).toEqual(all);
    await expect(body).toContainText('Max pain 770.00');
  });

  test('Right Now: a new scope\'s strike window stays drawn through the next push', async ({ page }) => {
    await intercept(page);
    const wider = Object.assign({}, STRIKES, { spot_strike: 791,
      today: { all: [[790, 500000, 1000], [791, 900000, 5000], [792, -200000, 3000]] },
      views: { all: { centre: 791, max_abs: 900000, max_abs_with_prior: 900000 } } });
    await page.route('**/api/terrain/strikes?**', (route) => route.request().url().includes('scope=wider')
      ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(wider) })
      : route.fallback());
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const strikes = page.locator('#tdMigration .gbs-k');
    await expect(strikes).toHaveText(['772', '771', '770']);
    await page.evaluate(() => window.EdShell.setScope('wider'));
    await expect(strikes).toHaveText(['792', '791', '790']);
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'flow' } })));
    await page.waitForTimeout(600);                                   // the push's reads have landed
    await expect(strikes).toHaveText(['792', '791', '790']);          // the window asked for, not the old one
  });

  test('Right Now: a read cut short by a venue switch never draws the old venue', async ({ page }) => {
    await intercept(page);
    let slow = false, inFlight = 0;
    await page.route('**/api/order-flow/microstructure?**', async (route) => {
      const venue = new URL(route.request().url()).searchParams.get('venue');
      if (slow && venue === 'NYSE_BOOK') { inFlight += 1; await new Promise((r) => setTimeout(r, 800)); }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(Object.assign({}, MICRO, { venue: venue })) });
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_book_venue', 'NYSE_BOOK'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('(NYSE_BOOK, depth 5)');
    await page.evaluate(() => {          // the venue each draw from here on shows
      window.__draws = [];
      new MutationObserver(() => window.__draws.push((document.getElementById('tdBody').textContent.match(/\((NYSE|NASDAQ)_BOOK/) || [''])[0]))
        .observe(document.getElementById('tdBody'), { childList: true });
    });
    slow = true;
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'flow' } })));
    await expect.poll(() => inFlight).toBe(1);
    await page.evaluate(() => document.querySelector('.bookvenue [data-venue="NASDAQ_BOOK"]').click());   // ... cut short
    await expect(body).toContainText('(NASDAQ_BOOK, depth 5)');
    await page.waitForTimeout(1200);                                 // the cut-short read would have landed
    expect(await page.evaluate(() => window.__draws)).toEqual(['(NASDAQ_BOOK']);
  });

  test('Right Now: a read cut short by a scope change never draws', async ({ page }) => {
    await intercept(page);
    const wider = Object.assign({}, STRIKES, { spot_strike: 791,
      today: { all: [[790, 500000, 1000], [791, 900000, 5000], [792, -200000, 3000]] },
      views: { all: { centre: 791, max_abs: 900000, max_abs_with_prior: 900000 } } });
    await page.route('**/api/terrain/strikes?**', (route) => route.request().url().includes('scope=wider')
      ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(wider) })
      : route.fallback());
    let slow = false, inFlight = 0;
    await page.route('**/api/levels?**', async (route) => {
      if (slow) { inFlight += 1; await new Promise((r) => setTimeout(r, 800)); }   // the push's read is in flight ...
      route.fallback();
    });
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdMigration .gbs-k')).toHaveText(['772', '771', '770']);
    await page.evaluate(() => {          // every draw of the page from here on: its strikes and its spot
      window.__draws = [];
      new MutationObserver(() => {
        const ks = [...document.querySelectorAll('#tdMigration .gbs-k')].map((e) => e.textContent).join(',');
        const meta = document.querySelector('#tdBody .fl-meta');
        window.__draws.push(ks + ' | ' + (meta ? meta.textContent : ''));
      }).observe(document.getElementById('tdBody'), { childList: true });
    });
    slow = true;
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'flow' } })));
    await expect.poll(() => inFlight).toBe(1);
    slow = false;
    await page.evaluate(() => window.EdShell.setScope('wider'));     // ... and the scope change cuts it short
    await expect(page.locator('#tdMigration .gbs-k')).toHaveText(['792', '791', '790']);
    await page.waitForTimeout(1200);                                 // the cut-short read would have landed
    expect(await page.evaluate(() => window.__draws)).toEqual(['792,791,790 | spot 771.30']);
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
    await page.locator('#tdmToolbar [data-act="style"]').click();
    await expect(page.locator('#tdmToolbar [data-act="style"]')).toHaveClass(/on/);
    expect(errs).toEqual([]);
  });
});
