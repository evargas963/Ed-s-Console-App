// The Trade Desk's served answers the desk specs route (console-trade-desk.spec.js,
// console-liquidity-card.spec.js): the attention queue, terrain, levels, the book and its
// readout, the liquidity zones, strikes, bars and the book heatmap, and the page-error watch.
// Level crosses are real SPY rows (tests/fixtures/real_spy_level_crosses.json); the readouts are
// the route's answers for SPY's real books (tests/test_liquidity_readout_v1.py).
const path = require('path');
const { routeWatchlist } = require('./watchlist');

const CROSSES = require(path.join(__dirname, '..', '..', 'fixtures', 'real_spy_level_crosses.json')).rows.slice(0, 3);
const EVENTS = {
  ticker: 'SPY', tf: '30', window_start_ts_utc: CROSSES[2].ts_utc - 60, window_label: 'this session (served)',
  // the served shape (server.get_desk_events): each cross as recorded, at its level's price
  items: CROSSES.map((c, i) => ({ key: 'x' + c.cross_id, n: 3 - i, ts: c.ts_utc, dom: 'LEVELS', dir: c.direction, marker: true,
    price: c.level_value, title: 'Crossed ' + (c.direction === 'up' ? 'above ' : 'below ') + c.level_name,
    detail: c.level_value.toFixed(2), src: 'level_crosses' })),
  cross_counts: { up: CROSSES.filter((c) => c.direction === 'up').length, down: CROSSES.filter((c) => c.direction !== 'up').length },
};
const SPOT = 771.3;
const TERRAIN = { ticker: 'SPY', spot: SPOT, gamma_flip: 768, call_wall: 775, put_wall: 765, max_pain: 770, regime: 'LONG_GAMMA_CHOP',
  posture: 'PINNED', levels_state: 'LIVE', levels_age_text: '1s', flip_relation: 'ABOVE', pcr_all: 1.1,
  pcr_by_expiry: { '2026-09-25': 1.1, '2026-10-02': null, '2026-10-09': 0.9 }, atm_iv_pct_by_expiry: { '2026-09-25': 14.2, '2026-10-02': 15.1 } };
const LEVELS = { ticker: 'SPY', spot: SPOT, tf: '30', generation: 1, vwap_series: [],
  levels: [
    { id: 'PDH', price: 773.5, family: 'prior_day', label: 'Prior Day High', short: 'PDH', evidence_tier: 'MEASURED', distance: 2.2, side: 'ABOVE', },
    { id: 'max_pain', price: 770, family: 'gamma', label: 'Max pain', short: 'Max pain', evidence_tier: 'DERIVED', distance: -1.3, side: 'BELOW', from_spot_text: '1.30 below spot', },
    { id: 'call_wall', price: 775, family: 'gamma', label: 'Call wall', short: 'Call wall', evidence_tier: 'DERIVED', distance: 3.7, side: 'ABOVE', from_spot_text: '3.70 above spot', },
    { id: 'put_wall', price: 765, family: 'gamma', label: 'Put wall', short: 'Put wall', evidence_tier: 'DERIVED', distance: -6.3, side: 'BELOW', from_spot_text: '6.30 below spot', },
  ],
  by_distance: ['max_pain', 'PDH'], families_absent: [], degraded: [],
  volume_profile: { basis: 'RTH 1-minute bars, each bar\'s volume spread evenly over its range (not trade prints)', tick_size: 0.01,
    bins: [[769.99, 1200, false], [770.0, 5000, true], [770.01, 3000, true]], max_volume: 5000, poc: 770.0, vah: 770.01, val: 770.0 } };
// the route's answers for SPY's real books (tests/test_liquidity_readout_v1.py): live, the daemon's
// connection ended, no book, and crossed inside the closing auction
const READOUT_LIVE = require(path.join(__dirname, 'liquidity_readout_live.json'));
const READOUT_OFFLINE = require(path.join(__dirname, 'liquidity_readout_offline.json'));
const READOUT_NO_BOOK = require(path.join(__dirname, 'liquidity_readout_no_book.json'));
// (the books when the composite was first crossed, read inside the closing auction window)
const READOUT_AUCTION = require(path.join(__dirname, 'liquidity_readout_close_auction.json'));
const LIVE_COMP = READOUT_LIVE.readout.venues.COMPOSITE;
const MICRO = { ticker: 'SPY', venue: 'NASDAQ_BOOK', status: 'ok', readout: READOUT_LIVE.readout, top_of_book: { bid: 771.29, ask: 771.31, bid_size: 300, ask_size: 200 },
  spread_pts: 0.02, depth: { '1': { imbalance: 0.2 }, '5': { bid_total: 3000, ask_total: 2000, imbalance: 0.2 } },
  depth_pressure: { bid: [{ price: 771.29, volume: 300, cum: 300 }, { price: 771.28, volume: 900, cum: 1200 }], ask: [{ price: 771.31, volume: 200, cum: 200 }] },
  ages: { book_age_sec: 1, book_stale: false }, book_feed_label: 'LIVE', wall_candidates: [], provenance: { book_source: 'NASDAQ_BOOK' },
  flow: { tape_pressure_5m: 0.3, tape_pressure_30s: 0.1, tape_pressure_2m: 0.2, cum_delta_proxy: 1000 } };
// the pivot zone below spot was named "support" by type-guessing on the page: each zone's label and
// side are served (liquidity_models.ZONE_DISPLAY)
const LIQ = { ticker: 'SPY', zones: [{ zone_low: 772, zone_high: 773, zone_type: 'resistance_liquidity', zone_label: 'Resistance', zone_side: 'resistance', confluence_score: 3 },
  { zone_low: 768, zone_high: 769, zone_type: 'pivot_value', zone_label: 'Pivot / value', zone_side: 'value', confluence_score: 2 }],
  spot_location: { inside: null, above: 0, below: 1 }, summary: null };
const STRIKES = { ticker: 'SPY', spot: SPOT, spot_strike: 771, levels_state: 'LIVE',
  today: { all: [[770, 500000, 1000], [771, 900000, 5000], [772, -200000, 3000]] }, prior: { all: [[770, 400000, 800], [771, 700000, 2000], [772, -100000, 900]] },
  migration: { all: { compared: true, drift: 'UP', grew: [771, 770], shrank: [772], busiest: [771, 772], busiest_vs_walls: 'INSIDE_WALLS',
    volume_total: 9000, rows: [[770, 500000, 400000, 100000], [771, 900000, 700000, 200000], [772, -200000, -100000, -100000]] } },
  views: { all: { centre: 771, max_abs: 900000, max_abs_with_prior: 900000 } } };
const BARS = { ticker: 'SPY', tf: '30', bars: [{ t: 1790343000, o: 770, h: 772, l: 769, c: SPOT, v: 1000, chg: SPOT - 770, chg_pct: (SPOT - 770) / 770 * 100 }],
  last_bar: { t: 1790343660, label: 'Fri 09/25 09:21 AM CT' } };
const HEAT = require(path.join(__dirname, 'book_heatmap_payload.json'));

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
  await routeWatchlist(page, ['SPY']);
}

function watchErrors(page) {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  return errs;
}

module.exports = {
  CROSSES, EVENTS, SPOT, TERRAIN, LEVELS, READOUT_LIVE, READOUT_OFFLINE, READOUT_NO_BOOK, READOUT_AUCTION, LIVE_COMP,
  MICRO, LIQ, STRIKES, BARS, HEAT, intercept, watchErrors,
};
