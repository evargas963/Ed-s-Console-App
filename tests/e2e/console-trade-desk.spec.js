/*
 * Trade Desk (Desk + Right Now) renders what the server serves and computes nothing (P1-3, PR B,
 * 2026-09-27): the attention queue is /api/desk/events (numbered, ordered, window-counted on the
 * server); book side, tape side, flip relation, wall distances, spot-vs-zones, levels by distance
 * and the positioning migration are served fields. Level crosses are real SPY rows
 * (tests/fixtures/real_spy_level_crosses.json). Any page error fails the test.
 */
const { test, expect, pushBeat, pushChange, pushDown, setNotLive, holdViews } = require('./fixtures/live_socket');
const { expiriesAnswer } = require('./fixtures/expiries');
const path = require('path');
const { mockPriceSocket, schwabQuote, daemonDown, daemonBeat, daemonSend, daemonSeries } = require('./fixtures/price_socket');
const { routeWatchlist } = require('./fixtures/watchlist');

const CROSSES = require(path.join(__dirname, '..', 'fixtures', 'real_spy_level_crosses.json')).rows.slice(0, 3);
const EVENTS = {
  ticker: 'SPY', tf: '30', window_start_ts_utc: CROSSES[2].ts_utc - 60, window_label: 'this session (served)',
  // the served shape (server.get_desk_events): each cross as recorded, at its level's price
  items: CROSSES.map((c, i) => ({ key: 'x' + c.cross_id, n: 3 - i, ts: c.ts_utc, dom: 'LEVELS', dir: c.direction, marker: true,
    price: c.level_value, title: 'Crossed ' + (c.direction === 'up' ? 'above ' : 'below ') + c.level_name,
    detail: c.level_value.toFixed(2), src: 'level_crosses',
    // time_et.ct_label of each cross's ts_utc, as served
    time_ct: ['Fri 09/25 04:25 PM CT', 'Fri 09/25 04:18 PM CT', 'Fri 09/25 04:18 PM CT'][i] })),
  cross_counts: { up: CROSSES.filter((c) => c.direction === 'up').length, down: CROSSES.filter((c) => c.direction !== 'up').length },
};
const SPOT = 771.3;
const TERRAIN = { ticker: 'SPY', spot: SPOT, gamma_flip: 768, call_wall: 775, put_wall: 765, max_pain: 770, regime: 'LONG_GAMMA',
  posture: 'PINNED', levels_stale: false, as_of: { levels: 1790343600 }, flip_relation: 'ABOVE', dist_to_call_wall: 3.7, dist_to_put_wall: 6.3, pcr_all: 1.1,
  pcr_by_expiry: { '2026-09-25': 1.1, '2026-10-02': null, '2026-10-09': 0.9 }, atm_iv_pct_by_expiry: { '2026-09-25': 14.2, '2026-10-02': 15.1 } };
const LEVELS = { ticker: 'SPY', spot: SPOT, tf: '30', generation: 1, vwap_series: [], as_of: { snapshot: 1790343600 },
  levels: [
    { id: 'PDH', price: 773.5, family: 'prior_day', label: 'Prior Day High', short: 'PDH', evidence_tier: 'MEASURED', distance: 2.2, gap: 2.2, side: 'ABOVE', },
    { id: 'max_pain', price: 770, family: 'gamma', label: 'Max pain', short: 'Max pain', evidence_tier: 'DERIVED', distance: -1.3, gap: 1.3, side: 'BELOW', },
  ],
  by_distance: ['max_pain', 'PDH'], families_absent: [], degraded: [],
  volume_profile: { basis: 'RTH 1-minute bars, each bar\'s volume spread evenly over its range (not trade prints)', tick_size: 0.01,
    bins: [[769.99, 1200, false], [770.0, 5000, true], [770.01, 3000, true]], max_volume: 5000, poc: 770.0, vah: 770.01, val: 770.0 } };
const MICRO = { ticker: 'SPY', venue: 'NASDAQ_BOOK', status: 'ok', top_of_book: { bid: 771.29, ask: 771.31, bid_size: 300, ask_size: 200 },
  spread_pts: 0.02, depth: { '1': { imbalance: 0.2, side: 'BID' }, '5': { bid_total: 3000, ask_total: 2000, imbalance: 0.2, side: 'BID' } },
  depth_pressure: { bid: [{ price: 771.29, volume: 300, cum: 300 }, { price: 771.28, volume: 900, cum: 1200 }], ask: [{ price: 771.31, volume: 200, cum: 200 }] },
  ages: { book_stale: false }, as_of: { book: 1790343659, quote: null }, wall_candidates: [], provenance: { book_source: 'NASDAQ_BOOK' },
  flow: { tape_pressure_5m: 0.3, tape_pressure_30s: 0.1, tape_pressure_2m: 0.2, cum_delta_proxy: 1000 } };
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
    let body = url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
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
  await routeWatchlist(page, ['SPY']);
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
  // (the daemon stand-in's read of the spec's bars is its fixture, not the page asking the console)
  page.on('request', (r) => { const u = r.url(); if (u.includes('/api/') && r.headers()['x-ed-stand-in'] !== 'daemon') asked.push(u.split('/api/')[1]); });
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
    /^order-flow\/microstructure\?/, /^bars1m\?.*tf=5/]) expect(count(re), String(re)).toBe(1);
  // the Order Flow card's 1-minute bars are Schwab's CHART_EQUITY from the daemon: never asked of the console
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
      let body = url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
      if (url.includes('/api/levels')) body = LEVELS;
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await routeWatchlist(page, ['SPY']);
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
    // when /api/desk/events answered. Each panel is pushed the moment its value is ready (Ed,
    // design A item 1: panels don't wait for each other).
    const errs = watchErrors(page);
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      if (url.includes('/api/desk/events')) return;               // the event queue has not answered
      let body = url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
      if (url.includes('/api/levels')) body = LEVELS;
      else if (url.includes('/api/bars1m')) body = BARS;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await routeWatchlist(page, ['SPY']);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown)).toBeGreaterThan(0);
    await expect(page.locator('#tdmQueue')).toContainText('Loading');
    expect(errs).toEqual([]);
  });

  test('Desk: the served queue, counts, book side, tape side and flip relation', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    // the Order Flow card's volume bars: the daemon's 1-minute series, SPY's real CHART_EQUITY bars
    // (2026-10-01) on its history (STAND-IN: the spec's bars)
    const live = require(path.join(__dirname, '..', 'fixtures', 'real_daemon_bars_spy_tsla_2026_10_01_02.json')).rows
      .filter((r) => r.native && r.symbol === 'SPY').slice(0, 3).map((r) => { const n = r.native, chg = n.CLOSE_PRICE - n.OPEN_PRICE;
        return { service: 'CHART_EQUITY', key: 'SPY', schwab_ts: r.schwab_ts, ts_recv: r.ts_recv, content: n, time_ct: 'bar ' + n.SEQUENCE,
          bar: { t: n.CHART_TIME_MILLIS / 1000, o: n.OPEN_PRICE, h: n.HIGH_PRICE, l: n.LOW_PRICE, c: n.CLOSE_PRICE, v: n.VOLUME,
            chg: chg, chg_pct: chg / n.OPEN_PRICE * 100 } }; });
    await mockPriceSocket(page, live);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmQueue .tdm-q')).toHaveCount(3);
    await expect(page.locator('#tdmQueueCount')).toHaveText('3');
    // each item's time as served: the page judges no day by its own clock
    await expect(page.locator('#tdmQueue .tdm-q-m')).toHaveText(EVENTS.items.map((it) => 'level_crosses · ' + it.time_ct));
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
    // the newest hour of the daemon's 1-minute series: the history (the spec's bars) and the bars sent live
    await expect(page.locator('#tdmCardFlow .tdm-plot svg rect')).toHaveCount(BARS.bars.length + live.length);
    await expect(page.locator('#tdmCardOpt .tdm-plot svg path')).toHaveCount(2);
    await expect(page.locator('#tdmCardVol .tdm-plot svg path')).toHaveCount(1);
    await expect(page.locator('#tdmCardVol figcaption')).toHaveText('ATM implied vol by expiry, nearest first');
    await expect(page.locator('#tdmAgree')).toContainText('Bid heavy');
    expect(errs).toEqual([]);
  });

  test('Desk: the ages are the console\'s labels, and with its push down nothing reads LIVE', async ({ page }) => {
    // operator 2026-10-14: "the server sends every age; the page only shows it", and "No value is
    // LIVE unless every feed it depends on is live, including the Desk PRICE pill"
    const errs = watchErrors(page);
    await intercept(page);
    await mockPriceSocket(page, [schwabQuote('SPY', SPOT)]);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const pill = (name) => page.locator('#tdmTrust .tdm-pill', { hasText: name });
    await expect(pill('PRICE')).toContainText('LIVE');
    pushBeat(page, { book: '4s', levels: '2m', snapshot: '9m' });     // the console's labels
    await expect(pill('BOOK')).toContainText('4s');
    await expect(pill('GAMMA')).toContainText('2m');
    await expect(pill('LEVELS')).toContainText('9m');
    await expect(page.locator('#tdmCardOpt .tdm-src')).toContainText('2m old');
    pushDown(page);                                   // the console's push: its values, not the price
    await expect(pill('BOOK')).toContainText('age not known', { timeout: 6000 });
    await expect(pill('PRICE')).toContainText('LIVE');
    daemonDown(page);                                 // the daemon's socket: the price
    await expect(pill('PRICE')).toContainText('OFFLINE', { timeout: 6000 });
    await expect(pill('PRICE')).toHaveAttribute('title', /the daemon's socket is down/);
    for (const id of ['#tdmChart', '#tdmCardLiq', '#tdmCardFlow', '#tdmCardOpt', '#tdmCardVol']) {
      await expect(page.locator(id)).toHaveClass(/not-live/);
      await expect(page.locator(id)).toHaveAttribute('data-not-live', /the console push is down/);
    }
    expect(errs).toEqual([]);
  });

  test('Desk: each card is marked by every panel drawn in it, whichever arrived last', async ({ page }) => {
    // the Options card reads the terrain and the forces: the terrain not live marks it even when
    // the forces arrive after, live (before, the last panel to arrive set the card's mark)
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmCardOpt .tdm-state')).not.toHaveText('');
    setNotLive(page, 'desk.terrain', 'Schwab LEVELONE_EQUITIES feed down during RTH');
    await pushChange(page, 'levels');          // the terrain and the forces again, the forces after it
    await expect(page.locator('#tdmCardOpt')).toHaveAttribute('data-not-live', /LEVELONE_EQUITIES feed down/);
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
    await mockPriceSocket(page, []);            // no price row; the console answers what SPY is (its served key)
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    const legend = page.locator('#tdmChart .tvc-legend');
    await expect(legend).toContainText('Last completed bar Fri 09/25 09:21 AM CT');
    const before = barReads.length;
    // three of Schwab's LEVELONE_EQUITIES messages from the daemon, its trade labels as it words them
    daemonBeat(page, { SPY: { time_ct: 'Fri 09/25 09:21 AM CT', age: '4s' } });
    daemonSend(page, [0, 1, 2].map((i) => schwabQuote('SPY', SPOT + i / 100)));
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).livePrice).toBeCloseTo(SPOT + 0.02, 6);
    await expect.poll(async () => (await chartState()).liveTitle).toBe('LAST · Fri 09/25 09:21 AM CT · 4s ago');   // Schwab's trade time, its served age
    expect((await chartState()).bars).toBe(BARS.bars.length);          // the candles are untouched
    // Schwab's own "no value" (AGENTS rule 2), marked absent as the daemon marks it
    // (tests/test_live_ui_daemon_to_browser_v1.py: the daemon's mark of each field that is not a number)
    daemonSend(page, [Object.assign(schwabQuote('SPY', -999), { absent: ['LAST_PRICE'] })]);
    await expect.poll(async () => (await chartState()).livePrice).toBeNull();   // Schwab sent no price: no line
    await page.waitForTimeout(1500);
    expect(barReads.length).toBe(before);
    await pushChange(page, 'liquidity');
    await expect.poll(() => barReads.length).toBeGreaterThan(before);
    expect(errs).toEqual([]);
  });

  test('Market Map 1m: each CHART_EQUITY bar from the daemon is drawn, in order; a headline is listed as sent', async ({ page }) => {
    // Real data: SPY's CHART_EQUITY items as Schwab sent them 2026-10-01 (the daemon's record,
    // tests/fixtures/real_daemon_bars_spy_tsla_2026_10_01_02.json); the bar and labels each carries
    // are the daemon's (proven in tests/test_live_ui_daemon_to_browser_v1.py), STAND-IN here.
    const errs = watchErrors(page);
    await intercept(page);
    const rows = require(path.join(__dirname, '..', 'fixtures', 'real_daemon_bars_spy_tsla_2026_10_01_02.json')).rows
      .filter((r) => r.native && r.symbol === 'SPY').slice(0, 3);
    const msgs = rows.map((r) => { const n = r.native, chg = n.CLOSE_PRICE - n.OPEN_PRICE;
      return { service: 'CHART_EQUITY', key: 'SPY', schwab_ts: r.schwab_ts, ts_recv: r.ts_recv, content: n,
        bar: { t: n.CHART_TIME_MILLIS / 1000, o: n.OPEN_PRICE, h: n.HIGH_PRICE, l: n.LOW_PRICE, c: n.CLOSE_PRICE, v: n.VOLUME,
          chg: chg, chg_pct: chg / n.OPEN_PRICE * 100 }, time_ct: 'bar ' + n.SEQUENCE }; });
    const news = require(path.join(__dirname, '..', 'fixtures', 'real_schwab_news_headline_spx_2026_10_05.json'));
    msgs.push({ service: 'NEWS_HEADLINE', key: 'SPY', schwab_ts: news.schwab_ts, ts_recv: news.ts_recv, content: news.content,
      time_ct: 'Mon 10/05 09:00 AM CT' });
    await page.route('**/api/bars1m**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, BARS, { tf: '1', bars: [{ t: rows[0].native.CHART_TIME_MILLIS / 1000 - 60,
        o: 769, h: 770, l: 768, c: 769.5, v: 10, chg: 0.5, chg_pct: 0.065 }] })) }));
    await mockPriceSocket(page, msgs);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '1'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).bars).toBe(1 + rows.length);
    await expect(page.locator('#tdmChart .tvc-legend')).toContainText('Last completed bar bar ' + rows[rows.length - 1].native.SEQUENCE);
    await expect(page.locator('#tdmNews')).toContainText(news.content['4']);
    await expect(page.locator('#tdmNews')).toContainText('Reuters · Mon 10/05 09:00 AM CT');
    expect(errs).toEqual([]);
  });

  test('Desk 1m: a series the daemon sends whole again (a reconnect, a /pricehistory answer) is drawn whole', async ({ page }) => {
    // Real data: SPY's CHART_EQUITY bars as Schwab sent them 2026-10-01 (the daemon's record); the
    // bars the daemon builds from them are proven in tests/test_live_ui_daemon_to_browser_v1.py,
    // STAND-IN here. A series sent whole is drawn whole, not as its newest two bars.
    const errs = watchErrors(page);
    await intercept(page);
    const all = require(path.join(__dirname, '..', 'fixtures', 'real_daemon_bars_spy_tsla_2026_10_01_02.json')).rows
      .filter((r) => r.native && r.symbol === 'SPY').slice(0, 8).map((r) => { const n = r.native, chg = n.CLOSE_PRICE - n.OPEN_PRICE;
        return { t: n.CHART_TIME_MILLIS / 1000, o: n.OPEN_PRICE, h: n.HIGH_PRICE, l: n.LOW_PRICE, c: n.CLOSE_PRICE, v: n.VOLUME,
          chg: chg, chg_pct: chg / n.OPEN_PRICE * 100 }; });
    const series = all.filter((b, i) => all.findIndex((x) => x.t === b.t) === i)        // one per minute, in time, as the daemon's
      .sort((x, y) => x.t - y.t);
    await page.route('**/api/bars1m**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, BARS, { tf: '1', bars: series.slice(0, 2) })) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '1'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).bars).toBe(2);
    daemonSeries(page, 'SPY', series, { t: series[series.length - 1].t, label: 'the newest' });   // the gap filled, whole
    await expect.poll(async () => (await chartState()).bars).toBe(series.length);
    // another chart ticker: its series replaces SPY's (the daemon keeps a page's chart series
    // current only while it is the chart), so switching back draws the daemon's series, never an old copy
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect.poll(() => page.evaluate(() => window.EdShell.series('SPY', 1200).length)).toBe(0);
    expect(errs).toEqual([]);
  });

  test('Desk 1m: the same index typed another way ($SPX after SPX) still draws the daemon\'s series', async ({ page }) => {
    // The page keeps the series by the daemon's key, which the daemon does not send again for the
    // same key; before, the page dropped it on the new spelling and the chart stayed waiting.
    // STAND-IN (named): the spec's bars as the daemon's series.
    const errs = watchErrors(page);
    await intercept(page);
    await page.route('**/api/bars1m**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, BARS, { tf: '1' })) }));
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPX'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '1'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length);
    await page.evaluate(() => window.EdShell.setTicker('$SPX'));
    await expect.poll(() => page.evaluate(() => window.EdShell.series('$SPX', 1200).length)).toBe(BARS.bars.length);
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length);
    expect(errs).toEqual([]);
  });

  test('Desk News: a headline held for another ticker is listed when that ticker is shown', async ({ page }) => {
    // Real data: a NEWS_HEADLINE item as Schwab sent it (tests/fixtures/real_schwab_news_headline_spx_2026_10_05.json);
    // STAND-IN: its key, QQQ. The list paints what is held for the ticker shown.
    const errs = watchErrors(page);
    await intercept(page);
    const news = require(path.join(__dirname, '..', 'fixtures', 'real_schwab_news_headline_spx_2026_10_05.json'));
    await mockPriceSocket(page, [{ service: 'NEWS_HEADLINE', key: 'QQQ', schwab_ts: news.schwab_ts, ts_recv: news.ts_recv,
      content: Object.assign({}, news.content, { key: 'QQQ' }), time_ct: 'Mon 10/05 09:00 AM CT' }]);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmNews')).toHaveText('-');           // none held for SPY: absent
    await page.evaluate(() => window.EdShell.setTicker('QQQ'));
    await expect(page.locator('#tdmNews')).toContainText(news.content['4']);
    expect(errs).toEqual([]);
  });

  test('the ticker already shown, picked again: its price keeps painting', async ({ page }) => {
    // Picking it again keeps what it is: the subscribe, the same as the last, is not sent again,
    // and the header keeps painting its price. STAND-IN (named): the price (schwabQuote).
    const errs = watchErrors(page);
    await intercept(page);
    await mockPriceSocket(page, [schwabQuote('SPY', 501.25)]);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#hPx')).toHaveText('501.25');
    await page.evaluate(() => window.EdShell.setTicker('SPY'));
    daemonSend(page, [schwabQuote('SPY', 502.5)]);
    await expect(page.locator('#hPx')).toHaveText('502.50');
    expect(errs).toEqual([]);
  });

  test('Desk 5m to 1m: an answer for 5 minutes in flight is never drawn on the 1-minute chart', async ({ page }) => {
    // The console's 5-minute bars answered under the view before (sent before the console took
    // the 1-minute view) are dropped, never drawn after the daemon's series as its newest two
    // bars. STAND-IN (named): the 5-minute buckets, later than every bar of the series.
    const errs = watchErrors(page);
    await intercept(page);
    const last = BARS.bars[BARS.bars.length - 1].t;
    const five = [1, 2].map((i) => Object.assign({}, BARS.bars[BARS.bars.length - 1], { t: last + 300 * i }));
    await page.route('**/api/bars1m**', (route) => {
      const tf = new URL(route.request().url()).searchParams.get('tf');
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(Object.assign({}, BARS, tf === '1' ? { tf: '1' } : { tf: tf, bars: BARS.bars.concat(five) })) });
    });
    await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '5'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length + five.length);
    const release = holdViews(page);                         // the 1-minute view, not yet at the console
    await page.locator('#tdmToolbar [data-tf="1"]').click();
    await pushChange(page, 'liquidity');                     // the 5-minute bars answered under the view before
    release();
    // the console's view answer drops the held 5-minute bars and draws the series, in one step
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length);
    expect(errs).toEqual([]);
  });

  test('Desk 1m to 5m: the series sent whole before the console takes the view is not drawn on the 5-minute chart', async ({ page }) => {
    // The daemon's series goes to the charts the console's newest view names: while the 5-minute
    // view is on its way, the 1-minute series sent whole (a /pricehistory answer) waits, and the
    // 5-minute chart draws the console's answer, never the 1-minute bars labelled 5 minutes.
    // Real data: SPY's CHART_EQUITY bar (tests/fixtures/real_daemon_bars_spy_tsla_2026_10_01_02.json).
    const errs = watchErrors(page);
    await intercept(page);
    const r = require(path.join(__dirname, '..', 'fixtures', 'real_daemon_bars_spy_tsla_2026_10_01_02.json')).rows
      .filter((x) => x.native && x.symbol === 'SPY')[0];
    const n = r.native, chg = n.CLOSE_PRICE - n.OPEN_PRICE;
    const bar = { service: 'CHART_EQUITY', key: 'SPY', schwab_ts: r.schwab_ts, ts_recv: r.ts_recv, content: n, time_ct: 'bar ' + n.SEQUENCE,
      bar: { t: n.CHART_TIME_MILLIS / 1000, o: n.OPEN_PRICE, h: n.HIGH_PRICE, l: n.LOW_PRICE, c: n.CLOSE_PRICE, v: n.VOLUME,
        chg: chg, chg_pct: chg / n.OPEN_PRICE * 100 } };
    await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '1'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length);   // the daemon's series
    const release = holdViews(page);                         // the 5-minute view, not yet at the console
    await page.locator('#tdmToolbar [data-tf="5"]').click();
    daemonSeries(page, 'SPY', BARS.bars.concat([bar.bar]), { t: bar.bar.t, label: bar.time_ct });
    await expect.poll(() => page.evaluate(() => window.EdShell.series('SPY', 1200).length)).toBe(BARS.bars.length + 1);
    expect((await chartState()).bars).toBe(0);               // the 5-minute chart, cleared: no 1-minute bar on it
    release();
    await expect.poll(async () => (await chartState()).tf).toBe('5');
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length);   // the console's 5-minute answer
    expect(errs).toEqual([]);
  });

  test('Desk 1m: with the console\'s push down, the daemon\'s bars still draw', async ({ page }) => {
    // The console never stands in the path from Schwab to the screen: a view that was on its way
    // when the console's push went down holds nothing back. Real data: as above.
    const errs = watchErrors(page);
    await intercept(page);
    const r = require(path.join(__dirname, '..', 'fixtures', 'real_daemon_bars_spy_tsla_2026_10_01_02.json')).rows
      .filter((x) => x.native && x.symbol === 'SPY')[0];
    const n = r.native, chg = n.CLOSE_PRICE - n.OPEN_PRICE;
    const bar = { service: 'CHART_EQUITY', key: 'SPY', schwab_ts: r.schwab_ts, ts_recv: r.ts_recv, content: n, time_ct: 'bar ' + n.SEQUENCE,
      bar: { t: n.CHART_TIME_MILLIS / 1000, o: n.OPEN_PRICE, h: n.HIGH_PRICE, l: n.LOW_PRICE, c: n.CLOSE_PRICE, v: n.VOLUME,
        chg: chg, chg_pct: chg / n.OPEN_PRICE * 100 } };
    await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '1'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length);
    holdViews(page);                                         // a view on its way that the console never takes
    await page.evaluate(() => window.EdShell.setTf('chart', '5'));   // another chart's timeframe: the Desk unchanged
    pushDown(page);
    daemonSend(page, [bar]);
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length + 1);
    expect(errs).toEqual([]);
  });

  test('Desk Volatility: VIX moves with its own price rows, not only the chart ticker\'s', async ({ page }) => {
    // A VIX row alone repaints the card's VIX. STAND-IN (named): the VIX price (schwabQuote).
    const errs = watchErrors(page);
    await intercept(page);
    await mockPriceSocket(page, []);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmCardVol .tdm-rows')).toContainText('waiting for the VIX stream');
    daemonSend(page, [schwabQuote('$VIX', 18.42)]);
    await expect(page.locator('#tdmCardVol .tdm-rows')).toContainText('18.42');
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

  test('Right Now: each section is marked by its own panels; with the push down its book reads NOT LIVE', async ({ page }) => {
    // operator 2026-10-14: "each panel gets its own screen element". The book's venue feed is down
    // (STAND-IN: the outage's words); only the Detect section, read from the book, says so.
    const errs = watchErrors(page);
    await intercept(page);
    setNotLive(page, 'rightnow.book', 'Schwab NASDAQ_BOOK feed down during RTH');
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdDetect')).toHaveAttribute('data-not-live', /NASDAQ_BOOK feed down during RTH/);
    for (const id of ['#tdFrame', '#tdConfirm', '#tdContext', '#tdMigration']) {
      await expect(page.locator(id)).not.toHaveAttribute('data-not-live', /NASDAQ_BOOK feed down during RTH/);
    }
    await expect(page.locator('#tdDetect .fl-badge')).toHaveText('LIVE');
    pushDown(page);
    await expect(page.locator('#tdDetect .fl-badge')).toHaveText('NOT LIVE', { timeout: 6000 });
    for (const id of ['#tdDetect', '#tdFrame', '#tdConfirm', '#tdContext', '#tdMigration']) {
      await expect(page.locator(id)).toHaveAttribute('data-not-live', /the console push is down/);
    }
    expect(errs).toEqual([]);
  });

  test('Right Now: Schwab\'s top of book shows from the daemon before the console\'s answers have landed', async ({ page }) => {
    // Operator 2026-10-14: "nothing should ever be in the way of the straight path from schwab to
    // the ui". The levels answer is held; Detect shows the daemon's bid × ask; the rest once it lands.
    const errs = watchErrors(page);
    await intercept(page);
    let release;
    const held = new Promise((r) => { release = r; });
    await page.route('**/api/levels**', async (route) => { await held;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LEVELS) }); });
    await mockPriceSocket(page, [schwabQuote('SPY', SPOT, { BID_PRICE: 771.29, ASK_PRICE: 771.31 })]);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdDetect')).toContainText('771.29 × 771.31');
    await expect(page.locator('#tdFrame')).toHaveCount(0);            // the console's levels: not yet
    release();
    await expect(page.locator('#tdFrame')).toHaveCount(1);
    await expect(page.locator('#tdDetect')).toContainText('771.29 × 771.31');
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
      await pushChange(page, kind);
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
    await pushChange(page, 'flow');
    await page.waitForTimeout(600);                                   // the push's reads have landed
    await expect(strikes).toHaveText(['792', '791', '790']);          // the window asked for, not the old one
  });

  test('no panel stays marked busy once its read has landed', async ({ page }) => {
    await intercept(page);
    const CONTRACT = 'SPY   261002C00768000';
    await page.route('**/api/flow-contract', (route) => route.fulfill({ status: 200,
      contentType: 'application/json', body: JSON.stringify({ ok: true, contract: CONTRACT }) }));
    // each panel and the read it makes; Flow reads only once a contract is chosen
    const panels = [['trade-desk', 'right-now', '', '/api/order-flow/microstructure'],
      ['options', 'gamma', 'heatmap', '/api/options/gamma-surface'], ['options', 'gamma', 'levels', '/api/levels'],
      ['options', 'chain', '', '/api/chain'], ['options', 'flow', '', '/api/order-flow/options-microstructure'],
      ['order-flow', 'book', '', '/api/order-flow/microstructure']];
    for (const [ws, sub, view, read] of panels) {
      await page.addInitScript(([w, s, v]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
        localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); } catch (e) {} }, [ws, sub, view]);
      const landed = page.waitForResponse((r) => new URL(r.url()).pathname === read);
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      if (sub === 'flow') await page.evaluate((c) => window.EdFlow.select(c), CONTRACT);
      await landed;                                                  // the read began, and so set its flag, before this
      expect(await page.locator('[aria-busy="true"]').count(), sub + ' ' + view).toBe(0);
    }
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
    await page.evaluate(() => {          // the venue each draw from here on shows, and the venue then on screen
      window.__draws = [];
      new MutationObserver(() => window.__draws.push([(document.getElementById('tdBody').textContent.match(/\((NYSE|NASDAQ)_BOOK/) || [''])[0],
        '(' + window.EdShell.getState().bookVenue]))
        .observe(document.getElementById('tdBody'), { childList: true });
    });
    slow = true;
    const pushed = pushChange(page, 'flow');                         // the console's answers are slow ...
    await expect.poll(() => inFlight).toBe(1);
    await page.evaluate(() => document.querySelector('.bookvenue [data-venue="NASDAQ_BOOK"]').click());   // ... cut short
    await expect(body).toContainText('(NASDAQ_BOOK, depth 5)');
    await pushed;                                                    // the slow NYSE answer has landed
    await page.waitForTimeout(400);
    const draws = await page.evaluate(() => window.__draws);
    // every draw is the venue on screen at that draw; the old venue's late answer never draws
    // after the switch (each panel's answer is drawn as it is pushed)
    expect(draws.filter((d) => d[1] === '(NASDAQ_BOOK').length).toBeGreaterThan(0);
    expect(draws.filter((d) => d[0] !== d[1])).toEqual([]);
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
    await mockPriceSocket(page, [schwabQuote('SPY', SPOT)]);      // the spot: the header's price row
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_scope', 'auto'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdMigration .gbs-k')).toHaveText(['772', '771', '770']);
    await expect(page.locator('#tdBody .fl-meta')).toHaveText('spot 771.30');
    await page.evaluate(() => {          // every draw of the page from here on: its strikes and its spot, and the scope then on screen
      window.__draws = [];
      new MutationObserver(() => {
        const ks = [...document.querySelectorAll('#tdMigration .gbs-k')].map((e) => e.textContent).join(',');
        const meta = document.querySelector('#tdBody .fl-meta');
        window.__draws.push([ks + ' | ' + (meta ? meta.textContent : ''), window.EdShell.getState().scope]);
      }).observe(document.getElementById('tdBody'), { childList: true });
    });
    slow = true;
    const pushed = pushChange(page, 'flow');                         // the console's answers are slow ...
    await expect.poll(() => inFlight).toBe(1);
    slow = false;
    await page.evaluate(() => window.EdShell.setScope('wider'));     // ... and the scope change cuts it short
    await expect(page.locator('#tdMigration .gbs-k')).toHaveText(['792', '791', '790']);
    await pushed;                                                    // the slow answer has landed
    await page.waitForTimeout(400);
    const draws = await page.evaluate(() => window.__draws);
    // every draw is the scope on screen at that draw; the old scope's late answer never draws
    // after the change
    const drawn = { auto: '772,771,770 | spot 771.30', wider: '792,791,790 | spot 771.30' };
    expect(draws.filter((d) => d[1] === 'wider').length).toBeGreaterThan(0);
    expect(draws.filter((d) => d[0] !== drawn[d[1]])).toEqual([]);
  });

  test('Market Map: 3m, line mode, a level beyond the visible range pinned at the edge, and the FORCES split', async ({ page }) => {
    const errs = watchErrors(page);
    const far = { id: 'grc', price: 837.58, family: 'gamma', label: 'GRC', short: 'GRC', evidence_tier: 'DERIVED', distance: 66.28, gap: 66.28, side: 'ABOVE', };
    const wall = { id: 'call_wall', price: 772, family: 'gamma', label: 'Call wall', evidence_tier: 'DERIVED', distance: 0.7, gap: 0.7, side: 'ABOVE', };
    await page.route('**/api/**', (route) => {
      const url = route.request().url();
      let body = url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
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
    await routeWatchlist(page, ['SPY']);
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

  test('Market Map: no shaded wall band, whatever the terrain carries', async ({ page }) => {
    // operator 2026-10-04: no shaded area on the chart. The call- and put-wall gamma ranges were
    // drawn as green and red bands across the pane; a terrain that still carries ranges (as the
    // server sent them before) draws exactly the same chart as one without them.
    async function chartImage(terrain) {
      await page.unrouteAll({ behavior: 'ignoreErrors' });
      await page.route('**/api/**', (route) => {
        const url = route.request().url();
        let body = url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
        if (url.includes('/api/desk/events')) body = EVENTS;
        else if (url.includes('/api/terrain/strikes')) body = STRIKES;
        else if (url.includes('/api/terrain')) body = terrain;
        else if (url.includes('/api/levels')) body = LEVELS;
        else if (url.includes('/api/order-flow/microstructure')) body = MICRO;
        else if (url.includes('/api/liquidity-snapshot')) body = LIQ;
        else if (url.includes('/api/bars1m')) body = BARS;
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });
      await routeWatchlist(page, ['SPY']);
      await Promise.all([page.waitForResponse((r) => /\/api\/terrain\?/.test(r.url())),
        page.goto('/', { waitUntil: 'domcontentloaded' })]);
      await expect.poll(() => page.evaluate(() => (window.EdTradeDeskMap.state().chart || {}).bars || 0)).toBeGreaterThan(0);
      // the chart's mark (the test console has no Schwab feed: its candles are not live) and the
      // terrain's answer are painted on the next frames
      await expect(page.locator('#tdmChart')).toHaveClass(/not-live/);
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await page.mouse.move(0, 0);
      return page.locator('#tdmChart').screenshot({ animations: 'disabled' });
    }
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    const plain = await chartImage(TERRAIN);
    const withRanges = await chartImage(Object.assign({}, TERRAIN, {
      call_wall_range: { lo: 700, hi: 800, coverage_pct: 70, method: 'gamma value area' },
      put_wall_range: { lo: 700, hi: 800, coverage_pct: 70, method: 'gamma value area' } }));
    expect(withRanges.equals(plain)).toBe(true);
  });
});
