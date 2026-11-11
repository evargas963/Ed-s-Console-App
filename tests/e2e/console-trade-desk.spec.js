/*
 * Trade Desk (Desk + Right Now) renders what the server serves and computes nothing (P1-3, PR B,
 * 2026-09-27): the attention queue is the desk panel (numbered, ordered, window-counted on the
 * server); book side, tape side, flip relation, wall distances, spot-vs-zones, levels by distance
 * and the positioning migration are served fields. Level crosses are real SPY rows
 * (tests/fixtures/real_spy_level_crosses.json). Any page error fails the test.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');
const { mockPriceSocket, priceRow } = require('./fixtures/price_socket');
const { routeWatchlist } = require('./fixtures/watchlist');
const { watchRequests, holdClock } = require('./fixtures/settled');

const {
  EVENTS, SPOT, TERRAIN, LEVELS, READOUT_LIVE, LIVE_COMP, MICRO, LIQ, STRIKES, BARS, intercept, watchErrors,
  deskPanels, deskSocket, levelsAt, tfAt,
} = require('./fixtures/trade_desk');

test('every chart is the one TradingView-style chart, with its controls', async ({ page }) => {
  // operator 2026-09-28: "each and every chart in the app needs to use the same TV controls" --
  // the Gamma chart (SVG), the book heatmap (canvas) and the liquidity map (DOM) each had their
  // own pan/zoom code; each now draws on ed-tv-chart.js (.tvc, its A / L controls, click-to-pin)
  const errs = watchErrors(page);
  await intercept(page);
  const views = [['trade-desk', 'desk', '', '#tdmChart'], ['options', 'gamma', 'chart', '#chartBody'],
    ['order-flow', 'heatmap', '', '#ofhBody'], ['liquidity', 'map', '', '#liqmBody']];
  for (const [ws, sub, view, host] of views) {
    await page.addInitScript(([w, s, v]) => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator(host + ' .tvc-auto'), ws + '/' + sub).toBeVisible();
    await expect(page.locator(host + ' .tvc-log'), ws + '/' + sub).toBeVisible();
  }
  // the liquidity map draws the served zones and shows the prior-day level from the levels panel: a line
  // when it is inside the candles' price range, else named at the pane's edge (PDH 773.50 is above
  // this fixture's one bar, 769-772; the scale fits the candles, 2026-09-29)
  await expect.poll(() => page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones)).toBe(LIQ.zones.length);
  await expect.poll(() => page.evaluate(() => ((window.EdLiquidityMap.state() || { levels: [] }).levels.join(' ') + ' ' +
    document.querySelector('#liqmBody .tvc-edge-top').textContent))).toContain('PDH');
  expect(errs).toEqual([]);
});

// 2026-09-29 RTH, measured in the operator's browser: a fresh desk load asked for every value twice
// (start() ran on ed:view and ed:ticker; the second saw no bars yet and loaded again), and a
// timeframe switch re-asked for the zones, strikes, forces and flow bars (and the terrain, now the
// socket's panel), none of which
// depend on the timeframe -- 6.8 s to redraw.
test('a desk load asks for each value once; a timeframe switch asks only for that timeframe and says it is loading', async ({ page }) => {
  const errs = watchErrors(page);
  const sock = await intercept(page);
  // each ask the desk made of a panel, in order (one per change of its parameters)
  const asks = (name) => sock.subscribes.map((s) => s.panels[name]).filter((p) => p !== undefined)
    .filter((p, i, a) => i === 0 || JSON.stringify(p) !== JSON.stringify(a[i - 1]));
  const levelsAsks = () => asks('levels:map').map((p) => p.tf);
  let barsHeld = true;   // the 15m bars are not sent until the test says
  deskPanels().bars = (key, params) => (barsHeld && params.tf === '15' ? undefined : Object.assign({}, BARS, { tf: params.tf }));
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '5'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars)).toBeGreaterThan(0);
  const DESK = ['desk', 'liquidity:deskmap', 'forces', 'book:deskmap', 'bars:deskmap', 'bars:flow'];
  for (const name of DESK) expect(asks(name).length, name).toBe(1);
  expect(asks('bars:deskmap')[0].tf).toBe('5');
  expect(asks('bars:flow')[0].tf).toBe('1');
  expect(levelsAsks()).toEqual(['5']);

  await page.locator('#tdmToolbar [data-tf="15"]').click();
  // while the 15m bars are on their way the 5m view is gone and the chart says what is loading
  await expect(page.locator('#tdmChartEmpty')).toHaveText(/Loading SPY · 15m/);
  expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.bars)).toBe(0);
  expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers.length)).toBe(0);
  barsHeld = false;
  sock.changed('bars');
  await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.tf)).toBe('15');
  // the switch changed the ask of the timeframe's panels alone
  expect(DESK.filter((name) => asks(name).length !== 1)).toEqual(['desk', 'bars:deskmap']);
  expect(asks('desk').map((p) => p.tf)).toEqual(['5', '15']);
  expect(asks('bars:deskmap').map((p) => p.tf)).toEqual(['5', '15']);
  expect(levelsAsks()).toEqual(['5', '15']);
  expect(errs).toEqual([]);
});

test('Liquidity map: the live price keeps its last trade time', async ({ page }) => {
  await intercept(page);
  deskPanels().levels = levelsAt(Object.assign({}, LEVELS, { spot_time_ct: 'Fri 10/02 10:00 AM CT' }));
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity');
    localStorage.setItem('ed_sub', 'map'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().liveTitle)).toBe('LAST · last trade Fri 10/02 10:00 AM CT');
  await expect.poll(() => page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().livePrice)).toBe(SPOT);
});

test('a level at 0 draws as a price: the map lists its zone, the desk its value words', async ({ page }) => {
  // the route's answer on SPY's bars with a session's prices at 0 (tests/test_data_path_liquidity_zero_v1.py
  // keeps this file equal to it): a reported 0 is 0
  const AT_ZERO = require(path.join(__dirname, 'fixtures', 'standin_liquidity_with_a_session_at_zero.json'));
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().liquidity = AT_ZERO;
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity'); localStorage.setItem('ed_sub', 'map'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.liqm-zones')).toContainText('Resistance 0.00');
  await expect.poll(() => page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones)).toBe(AT_ZERO.zones.length);
  await page.addInitScript(() => { localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdmAgree')).toContainText('shifted lower');
  await expect(page.locator('#tdmAgree')).toContainText('above value');
  expect(errs).toEqual([]);
});

test('Liquidity map: a failed request is named, and an empty snapshot shows the served reason', async ({ page }) => {
  // server.liquidity_snapshot's answer with no price levels published (NO_PRICE_LEVELS_REASON), and
  // the bars panel not produced (the program's words on the socket): the map says so for each,
  // never draws a failure as an empty answer
  const REASON = 'no price levels published for this ticker for the market\'s session yet (they are ' +
    'built from its 1-minute bars on each new bar and at the console\'s start)';
  const barsWords = 'the program could not produce this panel: RuntimeError: bars lock timed out';
  const liqWords = 'the program could not produce this panel: KeyError: \'SPY\'';
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().liquidity = { ticker: 'SPY', zones: [], reason: REASON };
  deskPanels().bars = { failed: barsWords };
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity'); localStorage.setItem('ed_sub', 'map'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.liqm-zones')).toContainText(REASON);
  await expect(page.locator('.liqm-empty')).toHaveText(barsWords);
  deskPanels().liquidity = { failed: liqWords };
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('.liqm-zones .sm')).toHaveText('-');   // no zones known: never "no zones for this session yet"
  await expect(page.locator('.liqm-empty')).toHaveText(liqWords + ' · ' + barsWords);
  expect(errs).toEqual([]);
});

test('the liquidity map fits its price scale to the candles; a far zone does not flatten them', async ({ page }) => {
  // 2026-09-29 RTH: SPY's served zones at 750 and 800 joined the auto-fit, the scale ran 735-805
  // and the candles (765) were a flat line
  const errs = watchErrors(page);
  await intercept(page);
  const far = { zone_low: 800, zone_high: 801, zone_type: 'resistance_liquidity', zone_label: 'Resistance', zone_side: 'resistance', confluence_score: 1 };
  deskPanels().liquidity = Object.assign({}, LIQ, { zones: LIQ.zones.concat([far]) });
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'liquidity'); localStorage.setItem('ed_sub', 'map'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones)).toBe(LIQ.zones.length + 1);
  const st = await page.evaluate(() => window.EdLiquidityMap.state());
  expect(st.priceTop).toBeLessThan(far.zone_low);          // the bar's range (769-772) sets the scale
  expect(errs).toEqual([]);
});

test('the Gamma chart and the liquidity map carry the Trade Desk toolbar; a timeframe click redraws at that timeframe', async ({ page }) => {
  // operator 2026-09-29: "for all other charts you were supposed to apply the tv characteristics" --
  // only the Trade Desk had the timeframes, candles/line, drawing tools, reset, screenshot and full screen
  const errs = watchErrors(page);
  const sock = await intercept(page);
  for (const [ws, sub, view, host, api, bars] of [['options', 'gamma', 'chart', '#chartBody', 'EdGammaChart', 'bars:chart'],
    ['liquidity', 'map', '', '#liqmBody', 'EdLiquidityMap', 'bars:liq']]) {
    await page.addInitScript(([w, s, v]) => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    for (const sel of ['[data-act="style"]', '[data-tool="hline"]', '[data-act="reset"]', '[data-act="shot"]', '[data-act="full"]'])
      await expect(page.locator(host + ' .tvc-toolbar ' + sel), ws + ' ' + sel).toBeVisible();
    const before = sock.subscribes.length;
    await page.locator(host + ' .tvc-toolbar [data-tf="15"]').click();
    await expect(page.locator(host + ' .tvc-toolbar [data-tf="15"]')).toHaveClass(/on/);
    await expect.poll(() => page.evaluate((a) => window[a].state() && window[a].state().tf, api), ws).toBe('15');
    expect(sock.subscribes.slice(before).map((s) => s.panels[bars] && s.panels[bars].tf), ws).toContain('15');
  }
  expect(errs).toEqual([]);
});

test('Desk: an offline price keeps its last trade time on the map', async ({ page }) => {
  await intercept(page);
  await deskSocket(page, [
    priceRow('$SPX', 5800.12, { trade_time_ct: '14:00:01 CT', feed_live: false, feed_label: 'OFFLINE', outage: 'Schwab LEVELONE_EQUITIES feed down during RTH' }),
    priceRow('$VIX', 16.4, { trade_time_ct: '14:00:02 CT', chg_pct: 1.2, feed_live: false, feed_label: 'OFFLINE', outage: 'Schwab LEVELONE_EQUITIES feed down during RTH' }),
    priceRow('SPY', 771.3, { trade_time_ct: '14:00:03 CT', feed_live: false, feed_label: 'OFFLINE', outage: 'Schwab LEVELONE_EQUITIES feed down during RTH', total_volume: 1000 }),
  ]);
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdmIdxSPX')).toContainText('last trade 14:00:01 CT');
  await expect(page.locator('#tdmIdxSPX')).toHaveAttribute('title', 'last trade 14:00:01 CT');
  await expect(page.locator('#tdmCardVol')).toContainText('16.40 (+1.20%) · last trade 14:00:02 CT');
  await expect(page.locator('#tdmCardFlow')).toContainText('OFFLINE');
  await expect(page.locator('#tdmCardFlow .tdm-src')).toContainText('last trade 14:00:03 CT');
  await expect(page.locator('#tdmCardFlow .tdm-src')).toContainText('Schwab LEVELONE_EQUITIES feed down during RTH');
});

test('Desk: a price push that stops reads OFFLINE on the map, not its last row\'s LIVE', async ({ page }) => {
  // the daemon's own rows for SPY's and $SPX's real messages in regular hours (tests/test_order_flow_book_payload_v1.py)
  const ROWS = require(path.join(__dirname, 'fixtures', 'price_rows_live.json'));
  const BOOK_TIME = 'Fri 09/25 06:59 PM CT';
  await intercept(page);
  // SPY's row, nothing for 8 s (the push down), then the push resumes with $SPX's row, and SPY's at 12 s
  const sock = await deskSocket(page, [ROWS.SPY], [{ afterMs: 8000, row: ROWS['$SPX'] }, { afterMs: 12000, row: ROWS.SPY }]);
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdmTrust')).toContainText('PRICE LIVE');
  await expect(page.locator('#hFeed')).toHaveText('OFFLINE', { timeout: 6000 });    // the socket sends nothing more
  await expect(page.locator('#tdmTrust')).toContainText('PRICE OFFLINE');
  await expect(page.locator('#tdmTrust')).not.toContainText('PRICE LIVE');
  await expect(page.locator('#tdmCardFlow')).toContainText('OFFLINE');
  // the push resumes with another symbol's row: SPY's last row is not SPY's state now, here or in
  // the header, even after the map repaints (a new book, sent on the socket, redraws it)
  await expect(page.locator('#tdmIdxSPX')).toContainText('last trade ' + ROWS['$SPX'].trade_time_ct, { timeout: 10000 });
  deskPanels().book = Object.assign({}, MICRO, { book_time_ct: BOOK_TIME });
  sock.changed('book');
  await expect(page.locator('#tdmTrust')).toContainText('BOOK ' + BOOK_TIME);   // the new book has landed and the map has repainted
  // read once, before SPY's row at 12 s ends the outage (no retrying: a retry would wait for it)
  expect(await page.locator('#hFeed').textContent()).toBe('OFFLINE');
  const trust = await page.locator('#tdmTrust').textContent();
  expect(trust).toContain('PRICE OFFLINE');
  expect(trust).not.toContain('PRICE LIVE');
  // SPY's own row ends the outage: the header and the map read LIVE again
  await expect(page.locator('#hFeed')).toHaveText('LIVE', { timeout: 6000 });
  await expect(page.locator('#tdmTrust')).toContainText('PRICE LIVE');
  await expect(page.locator('#tdmCardFlow')).not.toContainText('OFFLINE');
});

test('Desk: a book whose market is closed reads BOOK NOT LIVE and keeps Schwab\'s book time (the route\'s own answer)', async ({ page }) => {
  // SPY's real book and quotes at 22:00 ET as the route serves them (tests/test_order_flow_book_payload_v1.py)
  const CLOSED_BOOK = require(path.join(__dirname, 'fixtures', 'order_flow_book_closed_payload.json'));
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().book = CLOSED_BOOK;
  // the fixture holds NYSE_BOOK only: the card shows that book
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed_book_venue', 'NYSE_BOOK'); localStorage.setItem('ed.desk.liqvenue', 'BOOK'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdmCardLiq')).toContainText('BOOK NOT LIVE');
  await expect(page.locator('#tdmCardLiq .tdm-src')).toContainText('book ' + CLOSED_BOOK.book_time_ct + ' · ' +
    CLOSED_BOOK.readout.venues.NYSE_BOOK.book_age_text + ' old · not live');
  // Schwab's top-5 totals as served (800 and 2,160 shares), the last numbers kept
  await expect(page.locator('#tdmCardLiq .liq-body')).toContainText('2,160');
  await expect(page.locator('#tdmCardLiq .liq-bar-h').first()).toHaveText('Bids800');
  await expect(page.locator('#tdmTrust')).toContainText('BOOK ' + CLOSED_BOOK.book_time_ct + ' · NOT LIVE');
  await expect(page.locator('#tdmTrust')).not.toContainText('STALE');
  // with one book held, the composite is that book: its numbers, named on the source line
  const comp = CLOSED_BOOK.readout.venues.COMPOSITE;
  await page.locator('#tdmCardLiq [data-liqvenue="COMPOSITE"]').click();
  await expect(page.locator('#tdmCardLiq .liq-pct')).toHaveText(comp.views.weighted.pct_text);
  await expect(page.locator('#tdmCardLiq .liq-body')).toContainText('2,160');
  await expect(page.locator('#tdmCardLiq .tdm-src')).toContainText('Schwab NYSE_BOOK · composite, newest quote of each exchange');
  expect(errs).toEqual([]);
});

test('Desk: the book age keeps Schwab\'s book time', async ({ page }) => {
  const errs = watchErrors(page);
  const BOOK_TIME = 'Fri 09/25 06:59 PM CT';
  await intercept(page);
  deskPanels().book = Object.assign({}, MICRO, { book_time_ct: BOOK_TIME });
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  // the card's footnote keeps the served composite's book time; its side word and totals are served
  await expect(page.locator('#tdmCardLiq')).toContainText('Book ' + LIVE_COMP.book_time_ct);
  await expect(page.locator('#tdmCardLiq .liq-word')).toHaveText(LIVE_COMP.views.weighted.side_word);
  await expect(page.locator('#tdmCardLiq .liq-body')).toContainText(LIVE_COMP.views.weighted.ask_text);
  await expect(page.locator('#tdmTrust')).toContainText('BOOK ' + BOOK_TIME + ' · 1s');
  expect(errs).toEqual([]);
});

test('Desk: the chain age keeps the chain\'s time', async ({ page }) => {
  const errs = watchErrors(page);
  const CHAIN_TIME = 'Fri 09/25 06:59 PM CT';
  await intercept(page);
  deskPanels().terrain = Object.assign({}, TERRAIN, {
    levels_age_sec: 4, levels_age_text: '4s', levels_state: 'LIVE', levels_time_ct: CHAIN_TIME,
  });
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdmCardOpt .tdm-src')).toContainText('Schwab option chain · ' + CHAIN_TIME + ' · LIVE · 4s');
  await expect(page.locator('#tdmCardOpt')).toContainText('775.00');
  // the served regime word, toned from the one regime table
  await expect(page.locator('#tdmCardOpt .tdm-state')).toHaveText('LONG GAMMA CHOP');
  await expect(page.locator('#tdmCardOpt .tdm-state')).toHaveClass('tdm-state up');
  await expect(page.locator('#tdmCardVol .tdm-src')).toContainText(CHAIN_TIME + ' · LIVE · 4s');
  await expect(page.locator('#tdmTrust')).toContainText('GAMMA ' + CHAIN_TIME + ' · LIVE · 4s');
  expect(errs).toEqual([]);
});

test('Desk: the levels pill keeps the snapshot time', async ({ page }) => {
  const SNAP_TIME = 'Fri 09/25 06:59 PM CT';
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  await intercept(page);
  deskPanels().levels = levelsAt(Object.assign({}, LEVELS, {
    snapshot_as_of_ts_utc: 1790380799.830, snapshot_time_ct: SNAP_TIME, snapshot_age_text: '2d',
  }));
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'desk'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdmTrust')).toContainText('LEVELS ' + SNAP_TIME + ' · 2d');   // the served age, not the page's clock
  expect(errs).toEqual([]);
});

test('Right Now: the spot keeps its last trade time', async ({ page }) => {
  await intercept(page);
  deskPanels().levels = levelsAt(Object.assign({}, LEVELS, { spot_time_ct: 'Fri 10/02 10:00 AM CT' }));
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'right-now'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tdBody .fl-meta')).toHaveText('spot 771.30 · last trade Fri 10/02 10:00 AM CT');
});

test.describe('Trade Desk renders served values', () => {
  test('Desk after the close: levels drawn from the served order; dark by default', async ({ page }) => {
    // 2026-09-28 21:40 ET: after the close the levels served an empty by_distance and the chart drew
    // no key level; the spot is now Schwab's last trade at any hour and orders them (by_distance)
    const errs = watchErrors(page);
    await intercept(page);   // every panel sent in its real shape; after the close, nothing crossed
    deskPanels().desk = tfAt(Object.assign({}, EVENTS, { items: [], cross_counts: { up: 0, down: 0 } }));
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe('dark');
    // max pain (770) is inside the one bar's price range; PDH (773.50) is above it, pinned at the edge
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown)).toBe(1);
    await expect(page.locator('#tdmChart .tvc-edge-top')).toContainText('PDH 773.50');
    // the profile is drawn after the close too (the session's served profile) and names its basis
    await expect(page.locator('#tdmProfNote')).toHaveText(LEVELS.volume_profile.basis);
    expect(errs).toEqual([]);
  });

  test('Desk: a failed request is named on its cards, never told as an empty market', async ({ page }) => {
    // the terrain panel not produced (the program's words on the socket) and the flow bars
    // failing: the options, volatility and flow cards say so; before, they said no expiry
    // carries open interest and no bars for the symbol
    const errs = watchErrors(page);
    const words = 'the program could not produce this panel: RuntimeError: chain lock timed out';
    await intercept(page);   // every panel sent in its real shape, then the two that fail
    deskPanels().terrain = { failed: words };
    deskPanels().bars = (key, params, name) => (name === 'bars:flow' ? { failed: words } : tfAt(BARS)(key, params));
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmCardOpt .tdm-plot-none')).toHaveText(words);
    await expect(page.locator('#tdmCardVol .tdm-plot-none')).toHaveText(words);
    await expect(page.locator('#tdmTrust')).toContainText('GAMMA DOWN');
    await expect(page.locator('#tdmCardFlow .tdm-plot-none')).toHaveText('the program could not produce the bars');
    expect(errs).toEqual([]);
  });

  test('Desk: the levels are drawn when they arrive, not held for the event queue', async ({ page }) => {
    // 2026-09-29 14:52 CT, deployed: QQQ's levels answered in 28 ms and were drawn after 1.34 s,
    // when the event queue answered
    const errs = watchErrors(page);
    await intercept(page);   // every panel sent in its real shape, but the event queue
    deskPanels().desk = () => undefined;   // the event queue has not been sent
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown)).toBeGreaterThan(0);
    await expect(page.locator('#tdmQueue')).toContainText('Loading');
    expect(errs).toEqual([]);
  });

  test('Desk: levels sent for a timeframe the chart has left are not drawn', async ({ page }) => {
    // the program's 5m levels, sent before it read the switch to 15m, arrive after it
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed.desk.tf', '5'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown)).toBeGreaterThan(0);
    await page.locator('#tdmToolbar [data-tf="15"]').click();
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.tf)).toBe('15');
    const far = { id: 'grc', price: 837.58, family: 'gamma', label: 'GRC', short: 'GRC', evidence_tier: 'DERIVED', distance: 66.28, side: 'ABOVE' };
    sock.frame('levels:map', 'SPY', Object.assign({}, LEVELS, { tf: '5', levels: LEVELS.levels.concat([far]),
      by_distance: LEVELS.by_distance.concat(['grc']) }));                                   // 5m's, late ...
    sock.frame('terrain:map', 'SPY', Object.assign({}, TERRAIN, { call_wall: 776 }));       // ... and a panel behind it
    await expect(page.locator('#tdmCardOpt')).toContainText('776.00');
    await expect(page.locator('#tdmChart .tvc-edge-top')).not.toContainText('GRC');
    expect(errs).toEqual([]);
  });

  test('Desk: the served queue, counts, book side, tape side and flip relation', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmQueue .tdm-q')).toHaveCount(3);
    await expect(page.locator('#tdmQueueCount')).toHaveText('3');
    await expect(page.locator('#tdmCardLiq .liq-word')).toHaveText(LIVE_COMP.views.weighted.side_word);
    // Schwab sends no trade side: the Order Flow card claims none (operator 2026-09-29)
    await expect(page.locator('#tdmCardFlow')).not.toContainText(/NET BUYING|NET SELLING|tick rule|PROXY|delta/i);
    await expect(page.locator('#tdmCardFlow')).toContainText(EVENTS.cross_counts.up + ' up · ' + EVENTS.cross_counts.down + ' down');
    // the window's words are the server's (a page copy of the lookback table: register P-15)
    await expect(page.locator('#tdmCardFlow')).toContainText('Crosses (this session (served))');
    await expect(page.locator('#tdmLookback')).toHaveText('this session (served)');
    await expect(page.locator('#tdmAgree')).toContainText('Above flip');
    // the served session volume profile, every bin drawn at the chart's left edge, with its basis
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.volumeProfileBins)).toBe(LEVELS.volume_profile.bins.length);    await expect(page.locator('#tdmProfNote')).toHaveText(LEVELS.volume_profile.basis);
    // each card draws its served series (2026-09-28): the Liquidity card's 2m and 5m lean lines,
    // volume bars, and lines for put/call OI and ATM IV by expiry (a null expiry breaks the line)
    await expect(page.locator('#tdmCardLiq .liq-lean svg path')).toHaveCount(2);
    await expect(page.locator('#tdmCardFlow .tdm-plot svg rect')).toHaveCount(BARS.bars.length);
    await expect(page.locator('#tdmCardOpt .tdm-plot svg path')).toHaveCount(2);
    await expect(page.locator('#tdmCardVol .tdm-plot svg path')).toHaveCount(1);
    await expect(page.locator('#tdmCardVol figcaption')).toHaveText('ATM implied vol by expiry, nearest first');
    await expect(page.locator('#tdmAgree')).toContainText(LIVE_COMP.views.weighted.side_word.toLowerCase());
    expect(errs).toEqual([]);
  });

  test('Desk: each chart marker is its queue entry, and selecting the entry selects that marker', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const want = EVENTS.items.filter((it) => it.marker).map((it) => it.key).sort();
    await expect.poll(async () => (await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers)).slice().sort()).toEqual(want);
    const key = EVENTS.items[1].key;
    await page.locator('#tdmQueue [data-q="' + key + '"]').click();
    await expect(page.locator('#tdmQueue [data-q="' + key + '"]')).toHaveClass(/sel/);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected)).toBe(key);
    // and the other way: a click on a callout's number on the chart selects its queue entry
    const other = EVENTS.items[2].key;
    const all = await page.evaluate(() => window.EdTradeDeskMap.state().chart.callouts);
    const c = all.filter((x) => x.id === other)[0];
    expect(c).toBeTruthy();
    // the three crosses share one bar here; no callout's number covers another's
    for (const a of all) for (const b of all) if (a !== b) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(22);
    // the chart may still be settling its opening view: read the number where it is drawn now, click it
    const box = await page.locator('#tdmChart .tvc-plot').boundingBox();
    await expect.poll(async () => {
      const now = (await page.evaluate(() => window.EdTradeDeskMap.state().chart.callouts)).filter((x) => x.id === other)[0];
      await page.mouse.click(box.x + now.x, box.y + now.y);
      return page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected);
    }).toBe(other);
    await expect(page.locator('#tdmQueue [data-q="' + other + '"]')).toHaveClass(/sel/);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected)).toBe(other);
    expect(errs).toEqual([]);
  });

  test('Desk: the footer names the bars source only while this ticker has bars', async ({ page }) => {
    await routeWatchlist(page, ['SPY', 'MU']);
    await mockPriceSocket(page, [], [], undefined,
      { bars: (key, params) => Object.assign({}, key === 'SPY' ? BARS : { bars: [] }, { tf: params.tf }) });
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const bars = page.locator('#tdmFoot span', { hasText: 'Bars:' }).locator('b');
    await expect(bars).toHaveText('streamed 1m bars');
    await page.evaluate(() => window.EdShell.setTicker('MU'));
    await expect(page.locator('#tdmChartEmpty')).toContainText('No bars for MU');
    await expect(bars).toHaveText('-');
  });

  test('Desk: selecting a ticker asks for its book on the socket', async ({ page }) => {
    const sock = await intercept(page);
    // the ticker of each subscribe that asks for the desk's book
    const opened = () => sock.subscribes.filter((s) => s.panels['book:deskmap']).map((s) => s.ticker);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(opened).toContain('SPY');
    await page.evaluate(() => window.EdShell.setTicker('MU'));
    await expect.poll(opened).toContain('MU');
  });

  test('Market Map: the wheel over the price axis rescales price (as TradingView); over the plot it does not', async ({ page }) => {
    // operator 2026-09-29: "in tv all you do is scroll [on the price legend] and it will expand the
    // chart vertically; the way you have it you have to click and drag"
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
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
    const range = () => page.evaluate(() => { const c = window.EdTradeDeskMap.state().chart; return [c.from, c.to]; });
    const times = await range();
    await page.mouse.move(box.x + box.width / 3, box.y + box.height / 2);    // on the plot: time, not price
    await page.mouse.wheel(0, 400);
    await expect.poll(range).not.toEqual(times);                              // the wheel has been taken: time moved
    expect(await span()).toBeCloseTo(widened, 6);
  });

  test('Desk: the live price line keeps its last trade time', async ({ page }) => {
    await intercept(page);
    await deskSocket(page, []);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars)).toBeGreaterThan(0);
    await page.evaluate((spot) => window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: {
      ticker: 'SPY', spot: spot, feed_live: false, feed_label: 'OFFLINE', trade_age_text: '1s', trade_time_ct: '14:00:01 CT',
      outage: 'Schwab LEVELONE_EQUITIES feed down during RTH' } })), SPOT);
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart && window.EdTradeDeskMap.state().chart.liveTitle)).toBe('LAST · last trade 14:00:01 CT');
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart && window.EdTradeDeskMap.state().chart.livePrice)).toBe(SPOT);
  });

  test('Market Map: the served last completed bar; a price tick moves the live LAST line and asks for no bars', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    const requests = watchRequests(page);
    const sock = await deskSocket(page, []);            // the daemon answers what SPY is (its served key)
    const barReads = sock.subscribes;           // each ask the page makes of the program, the bars among them
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await holdClock(page);                      // the page's timers run when the test moves its time
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe('SPY');
    const legend = page.locator('#tdmChart .tvc-legend');
    await expect(legend).toContainText('Last completed bar Fri 09/25 09:21 AM CT');
    const before = barReads.length;
    await page.evaluate((spot) => {
      for (let i = 0; i < 3; i++) window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: { ticker: 'SPY', spot: spot + i / 100,
        spot_disp: (spot + i / 100).toFixed(2), feed_live: true, trade_age_text: '1s' } }));
    }, SPOT);
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).livePrice).toBeCloseTo(SPOT + 0.02, 6);
    expect((await chartState()).liveTitle).toBe('LAST · 1s');
    expect((await chartState()).bars).toBe(BARS.bars.length);          // the candles are untouched
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: { ticker: 'SPY', spot: null,
      spot_disp: null, feed_live: false, feed_label: 'OFFLINE', trade_age_text: null } })));
    await expect.poll(async () => (await chartState()).livePrice).toBeNull();   // Schwab sent no price: no line
    await requests.settled();                   // the ticks' own work, and any read it made, is done
    await page.clock.runFor(1500);              // every page timer due in 1.5 s has run
    await requests.settled();                   // and every read those made
    expect(barReads.length).toBe(before);
    // a bar completes: the program sends the bars again, whole, and the chart shows the new bar
    const last = BARS.bars[BARS.bars.length - 1];
    deskPanels().bars = tfAt(Object.assign({}, BARS, { bars: BARS.bars.concat([Object.assign({}, last, { t: last.t + 1800 })]) }));
    sock.changed('bars');
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length + 1);
    expect(barReads.length).toBe(before);
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
    deskPanels().bars = tfAt(Object.assign({}, BARS, { bars: bars }));
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
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
    const sock = await intercept(page);
    // the venue of each ask the desk made of the book and of the event queue, in order
    const venues = (name) => sock.subscribes.map((s) => s.panels[name]).filter((p) => p !== undefined).map((p) => p.venue);
    const asked = () => [venues('book:deskmap'), venues('desk')].map((v) => v[v.length - 1]);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); localStorage.removeItem('ed_book_venue'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const nyse = page.locator('#tdmCardLiq .bookvenue [data-venue="NYSE_BOOK"]');
    const nasdaq = page.locator('#tdmCardLiq .bookvenue [data-venue="NASDAQ_BOOK"]');
    await expect(nyse).toHaveClass(/on/);
    await expect.poll(asked).toEqual(['NYSE_BOOK', 'NYSE_BOOK']);
    await nasdaq.click();
    await expect(nasdaq).toHaveClass(/on/);
    await expect.poll(asked).toEqual(['NASDAQ_BOOK', 'NASDAQ_BOOK']);
    expect(venues('book:deskmap').concat(venues('desk')).every((v) => /^(NYSE|NASDAQ)_BOOK$/.test(v))).toBe(true);
    expect(errs).toEqual([]);
  });

  // AGENTS rule 5: the levels as the real code serves them on SPY's 2026-10-22 close publication,
  // its 16:39 print (773.1269) the last price and the daemon's connection ended, read at 18:00
  // (tests/test_level_crosses_wire.py keeps this file equal to the panel's answer)
  const STOPPED = require(path.join(__dirname, '..', 'fixtures', 'real_spy_levels_at_a_stopped_price_2026_10_22.json'));
  async function routeStopped(page) {
    const terrain = Object.assign({}, TERRAIN, { spot_feed_live: false, spot_not_live_text: STOPPED.spot_not_live_text });
    await intercept(page);   // every route answered in its real shape, then the stopped price's two
    deskPanels().terrain = terrain;
    deskPanels().levels = levelsAt(STOPPED);
  }

  test('Right Now: distances from a price that has stopped are marked not live with its time and age', async ({ page }) => {
    const errs = watchErrors(page);
    await routeStopped(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const row = (id) => STOPPED.levels.find((r) => r.id === id);
    const nearest = row(STOPPED.by_distance[0]);
    const body = page.locator('#tdBody');
    expect(STOPPED.spot_not_live_text).toContain('last trade');
    await expect(body).toContainText(nearest.from_spot_text + ' · ' + STOPPED.spot_not_live_text);
    await expect(body).toContainText('Put wall ' + row('put_wall').from_spot_text + ', call wall ' +
      row('call_wall').from_spot_text + ' · ' + STOPPED.spot_not_live_text);
    expect(errs).toEqual([]);
  });

  test('Market Map: the flip side from a price that has stopped is marked not live with its time and age', async ({ page }) => {
    const errs = watchErrors(page);
    await routeStopped(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmAgree')).toContainText('Above flip · ' + STOPPED.spot_not_live_text);
    expect(errs).toEqual([]);
  });

  test('Right Now: a failed read is named, never told as no book, no levels or no gamma', async ({ page }) => {
    // the book, the levels and the per-strike panels not produced (the program's words on the
    // socket): before, they read "No book yet", "No levels" and "no per-strike gamma for this
    // symbol yet"
    const errs = watchErrors(page);
    const words = 'the program could not produce this panel: RuntimeError: chain lock timed out';
    const levelsWords = 'the program could not produce this panel: KeyError: \'SPY\'';
    const bookWords = 'the program could not produce this panel: OSError: book read failed';
    await intercept(page);   // every panel sent in its real shape, then the three that fail
    deskPanels().strikes = { failed: words };
    deskPanels().levels = { failed: levelsWords };
    deskPanels().book = { failed: bookWords };
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdBody')).toContainText(bookWords);
    await expect(page.locator('#tdBody')).toContainText(levelsWords);
    await expect(page.locator('#tdMigration')).toContainText(words);
    expect(errs).toEqual([]);
  });

  test('Right Now: detect, frame, context and the migration read the served fields', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    // the book's lean is the Liquidity readout's, served (one producer for the desk)
    const nq5 = READOUT_LIVE.readout.venues.NASDAQ_BOOK.views['5'];
    await expect(body).toContainText(nq5.pct_text + nq5.side_word.toLowerCase() + ' (NASDAQ_BOOK, depth 5)');
    await expect(body).toContainText('Max pain 770.00');           // nearest by the served by_distance
    await expect(body).toContainText('1.30 below spot');
    await expect(body).toContainText('Put wall 6.30 below spot, call wall 3.70 above spot');   // the levels panel's own rows
    await expect(body).toContainText('Resistance zone above at 772.00');
    await expect(body).toContainText('Pivot / value zone below at 769.00');
    // the walls' and the flip's own moves since the prior close, as served (no drift word)
    await expect(body).toContainText('Call wall 774 → 775 (+1) · Put wall 765 → 765 (unchanged) · Gamma flip 768.25 → 767.50 (-0.75)');
    await expect(body).toContainText('Gamma grew most at 771/770');
    await expect(body).toContainText('inside the wall range');
    expect(errs).toEqual([]);
  });

  test('Right Now: the book age keeps Schwab\'s book time', async ({ page }) => {
    const errs = watchErrors(page);
    const BOOK_TIME = 'Fri 09/25 06:59 PM CT';
    await intercept(page);
    deskPanels().book = Object.assign({}, MICRO, {
      book_time_ct: BOOK_TIME, book_when_age_text: BOOK_TIME + ' · 1s',
      top_outage: 'Schwab NASDAQ_BOOK feed down during RTH', top_feed_label: 'OFFLINE',
    });
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('OFFLINE');
    await expect(body).toContainText(BOOK_TIME + ' · 1s');
    await expect(body).toContainText('771.29 × 771.31');
    await expect(body).toContainText(READOUT_LIVE.readout.venues.NASDAQ_BOOK.views['5'].side_word.toLowerCase() + ' (NASDAQ_BOOK, depth 5)');
    expect(errs).toEqual([]);
  });

  test('Right Now draws each of its panels again when the program sends it, and asks for each once', async ({ page }) => {
    const sock = await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('Max pain 770.00');
    const asked = sock.subscribes.length;
    // DETECT's book and FRAME's zones, FRAME's levels (each with its distance from the live
    // price), CONFIRM's levels and the migration's rows are the book, liquidity, levels, terrain
    // and strikes panels the program sends on the socket when they change, the levels with each
    // price row too
    deskPanels().book = Object.assign({}, MICRO, { top_of_book: Object.assign({}, MICRO.top_of_book, { bid: 771.2 }) });
    sock.changed('book');
    await expect(body).toContainText('771.20 × 771.31');                  // DETECT's book
    deskPanels().liquidity = Object.assign({}, LIQ, { zones: LIQ.zones.map((z) =>
      (z.zone_side === 'resistance' ? Object.assign({}, z, { zone_low: 772.5 }) : z)) });
    sock.changed('liquidity');
    await expect(body).toContainText('Resistance zone above at 772.50');  // FRAME's zones
    await expect(body).toContainText('Max pain 770.00');
    deskPanels().terrain = Object.assign({}, TERRAIN, { max_pain: 771 });
    sock.changed('terrain');
    await expect(body).toContainText('Gamma flip768.00Max pain771.00');   // CONFIRM's rows
    deskPanels().levels = levelsAt(Object.assign({}, LEVELS, { levels: LEVELS.levels.map((r) =>
      (r.id === 'max_pain' ? Object.assign({}, r, { from_spot_text: '0.30 below spot' }) : r)) }));
    sock.changed('levels');
    await expect(body).toContainText('0.30 below spot');                  // FRAME's nearest level
    expect(sock.subscribes.length).toBe(asked);                           // a panel sent is drawn, never asked for again
  });

  test('Right Now: a new scope\'s strike window stays drawn through the next push', async ({ page }) => {
    const sock = await intercept(page);
    const wider = Object.assign({}, STRIKES, { spot_strike: 791,
      today: { all: [[790, 500000, 1000], [791, 900000, 5000], [792, -200000, 3000]] },
      views: { all: { centre: 791, max_abs: 900000, max_abs_with_prior: 900000 } } });
    deskPanels().strikes = (key, params) => (params.scope === 'wider' ? wider : STRIKES);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_scope', 'auto'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const strikes = page.locator('#tdMigration .gbs-k');
    await expect(strikes).toHaveText(['772', '771', '770']);
    await page.evaluate(() => window.EdShell.setScope('wider'));
    await expect(strikes).toHaveText(['792', '791', '790']);
    for (const kind of ['strikes', 'liquidity']) sock.changed(kind);  // the program sends the panels again
    deskPanels().book = Object.assign({}, MICRO, { top_of_book: Object.assign({}, MICRO.top_of_book, { bid: 771.2 }) });
    sock.changed('book');
    await expect(page.locator('#tdBody')).toContainText('771.20 × 771.31');   // the push has been drawn
    await expect(strikes).toHaveText(['792', '791', '790']);          // the window asked for, not the old one
  });

  test('no panel stays marked busy once its panel has landed', async ({ page }) => {
    await intercept(page);
    const CONTRACT = 'SPY   261002C00768000';
    deskPanels().contract = (key, params) => ({ available: false, contract: params.contract });
    await page.route('**/api/flow-contract', (route) => route.fulfill({ status: 200,
      contentType: 'application/json', body: JSON.stringify({ ok: true, contract: CONTRACT }) }));
    // every panel the page takes, by its name, in the order it arrives
    await page.addInitScript(() => { window.__landed = [];
      document.addEventListener('ed:panel', (e) => window.__landed.push(e.detail.type)); });
    // each view and the panel it shows; Flow asks only once a contract is chosen
    const panels = [['trade-desk', 'right-now', '', 'book:desk'],
      ['options', 'gamma', 'heatmap', 'tape'],
      ['options', 'flow', '', 'contract'],
      ['order-flow', 'book', '', 'book:dom']];
    for (const [ws, sub, view, name] of panels) {
      await page.addInitScript(([w, s, v]) => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
        localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); }, [ws, sub, view]);
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      if (sub === 'flow') await page.evaluate((c) => window.EdFlow.select(c), CONTRACT);
      await expect.poll(() => page.evaluate(() => window.__landed), sub + ' ' + view).toContain(name);   // the panel has landed
      expect(await page.locator('[aria-busy="true"]').count(), sub + ' ' + view).toBe(0);
    }
  });

  test('Right Now: the old venue\'s book arriving after a venue switch is never drawn',async ({ page }) => {
    const sock = await intercept(page);
    let held = false;   // NASDAQ's book is sent when the test says
    deskPanels().book = (key, params) => (held && params.venue === 'NASDAQ_BOOK' ? undefined : Object.assign({}, MICRO, { venue: params.venue }));
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_book_venue', 'NYSE_BOOK'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('(NYSE_BOOK, depth 5)');
    await page.evaluate(() => {          // the venue each draw from here on shows
      window.__draws = [];
      new MutationObserver(() => window.__draws.push((document.getElementById('tdBody').textContent.match(/\((NYSE|NASDAQ)_BOOK/) || [''])[0]))
        .observe(document.getElementById('tdBody'), { childList: true });
    });
    held = true;
    await page.evaluate(() => document.querySelector('.bookvenue [data-venue="NASDAQ_BOOK"]').click());
    await expect.poll(() => sock.subscribes.some((s) => s.panels && s.panels['book:desk'] && s.panels['book:desk'].venue === 'NASDAQ_BOOK')).toBe(true);
    sock.frame('book:desk', 'SPY', Object.assign({}, MICRO, { venue: 'NYSE_BOOK' }));   // NYSE's, already on its way ...
    held = false;
    sock.changed('book');                                            // ... and NASDAQ's behind it
    await expect(body).toContainText('(NASDAQ_BOOK, depth 5)');
    expect(await page.evaluate(() => window.__draws)).toEqual(['(NASDAQ_BOOK']);
  });

  test('Right Now: a strike of GEX not known keeps its row: no bar, no ghost, the dash, no page error', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await intercept(page);
    const today = [[770, 500000, 1000], [771, null, null], [772, -200000, 3000]];
    deskPanels().strikes = Object.assign({}, STRIKES, { today: { all: today }, migration: { all: Object.assign({}, STRIKES.migration.all,
      { rows: [[770, 500000, 400000, 100000], [771, null, 700000, null], [772, -200000, -100000, -100000]] }) } });
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdMigration .gbs-k')).toHaveText(['772', '771', '770']);
    const row = page.locator('#tdMigration .mig-row', { hasText: '771' });
    await expect(row.locator('.gbs-v')).toHaveText('-');
    await expect(row.locator('.mig-delta')).toHaveText('-');
    await expect(row.locator('.gbs-vol')).toHaveText('-');
    expect(await row.locator('.gbs-bar').evaluate((el) => el.style.width)).toBe('0%');
    await expect(row.locator('.mig-ghost')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('Right Now: a panel landing after a scope change draws only the new window',async ({ page }) => {
    const sock = await intercept(page);
    const wider = Object.assign({}, STRIKES, { spot_strike: 791,
      today: { all: [[790, 500000, 1000], [791, 900000, 5000], [792, -200000, 3000]] },
      views: { all: { centre: 791, max_abs: 900000, max_abs_with_prior: 900000 } } });
    deskPanels().strikes = (key, params) => (params.scope === 'wider' ? wider : STRIKES);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'right-now'); localStorage.setItem('ed_scope', 'auto'); });
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
    await page.evaluate(() => window.EdShell.setScope('wider'));     // the scope changes ...
    await expect(page.locator('#tdMigration .gbs-k')).toHaveText(['792', '791', '790']);
    deskPanels().liquidity = Object.assign({}, LIQ, { zones: LIQ.zones.map((z) =>
      (z.zone_side === 'resistance' ? Object.assign({}, z, { zone_low: 772.5 }) : z)) });
    sock.changed('liquidity');                                       // ... and a panel of another kind lands after it
    await expect(page.locator('#tdBody')).toContainText('Resistance zone above at 772.50');
    // once the new window is drawn, every later draw is the new window: none goes back to the
    // old one, the later panel's included
    const draws = await page.evaluate(() => window.__draws);
    const first = draws.indexOf('792,791,790 | spot 771.30');
    expect(first).toBeGreaterThan(-1);
    expect(draws.slice(first).filter((d) => d !== '792,791,790 | spot 771.30')).toEqual([]);
  });

  test('Market Map: 3m, line mode, a level beyond the visible range pinned at the edge, and the FORCES split', async ({ page }) => {
    const errs = watchErrors(page);
    const far = { id: 'grc', price: 837.58, family: 'gamma', label: 'GRC', short: 'GRC', evidence_tier: 'DERIVED', distance: 66.28, side: 'ABOVE', };
    const wall = { id: 'call_wall', price: 772, family: 'gamma', label: 'Call wall', evidence_tier: 'DERIVED', distance: 0.7, side: 'ABOVE', };
    await routeWatchlist(page, ['SPY']);
    await mockPriceSocket(page, [], [], undefined,
      { desk: tfAt(EVENTS), book: MICRO, liquidity: LIQ, bars: tfAt(BARS),
        forces: { ticker: 'SPY', available: true, doi_below: 1200, doi_above: null,
          dex_below_dollars: 5e8, dex_above_dollars: null, charm_below: 0.0123, charm_above: null, older_et_date: '2026-10-07' },
        terrain: Object.assign({}, TERRAIN, { call_wall: 772, call_wall_lean: 'DEALERS SELL' }),
        strikes: Object.assign({}, STRIKES, { today_side_sums: { gex_below: -1.2e9, gex_above: null } }),
        levels: levelsAt(Object.assign({}, LEVELS, { levels: LEVELS.levels.concat([wall, far]),
          by_distance: ['call_wall', 'max_pain', 'PDH', 'grc'] })) });
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmToolbar [data-tf="3"]')).toHaveText('3m');
    await expect(page.locator('#tdmChart .tvc-edge-top')).toContainText('GRC 837.58');
    await expect(page.locator('#tdmCardOpt')).toContainText('GEX below / above');
    await expect(page.locator('#tdmCardOpt')).toContainText('−$1.20B / -');          // GEX, one side not known
    await expect(page.locator('#tdmCardOpt')).toContainText('ΔOI since 2026-10-07 below / above 1200 / -');   // from its served day
    await expect(page.locator('#tdmCardOpt')).toContainText('0.0123 / -');           // charm, one side not known
    await expect(page.locator('#tdmCardOpt')).toContainText('+$500.0M / -');         // DEX, one side not known
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
      await routeWatchlist(page, ['SPY']);
      await mockPriceSocket(page, [], [], undefined, { terrain: terrain, strikes: STRIKES, levels: levelsAt(LEVELS),
        desk: tfAt(EVENTS), book: MICRO, liquidity: LIQ, bars: tfAt(BARS), forces: { available: false } });
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#tdmCardOpt')).toContainText('775.00');   // the terrain panel has landed
      await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart && window.EdTradeDeskMap.state().chart.bars)).toBeGreaterThan(0);
      // the terrain's answer is painted on the next frames
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await page.mouse.move(0, 0);
      // what the chart draws: every canvas's pixels and the chart's DOM (its labels and
      // controls: each element, its attributes in name order, its text). A screenshot of the same
      // drawing differs by a level in a few anti-aliased pixels under load, and the order the
      // chart library writes a canvas's attributes in varies, so the drawing itself is compared.
      return page.evaluate(() => {
        const host = document.getElementById('tdmChart');
        const tree = (n) => n.nodeType !== Node.ELEMENT_NODE ? n.textContent
          : [n.nodeName, Array.from(n.attributes, (a) => [a.name, a.value]).sort(), Array.from(n.childNodes, tree)];
        return { canvases: Array.from(host.querySelectorAll('canvas'), (c) => c.toDataURL()), dom: tree(host) };
      });
    }
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); });
    const plain = await chartImage(TERRAIN);
    const withRanges = await chartImage(Object.assign({}, TERRAIN, {
      call_wall_range: { lo: 700, hi: 800, coverage_pct: 70, method: 'gamma value area' },
      put_wall_range: { lo: 700, hi: 800, coverage_pct: 70, method: 'gamma value area' } }));
    expect(plain.canvases.length).toBeGreaterThan(0);
    expect(withRanges).toEqual(plain);
  });
});
