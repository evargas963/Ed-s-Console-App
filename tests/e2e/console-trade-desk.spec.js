/*
 * Trade Desk (Desk + Right Now) renders what the server serves and computes nothing (P1-3, PR B,
 * 2026-09-27): the attention queue is /api/desk/events (numbered, ordered, window-counted on the
 * server); book side, tape side, flip relation, wall distances, spot-vs-zones, levels by distance
 * and the positioning migration are served fields. Level crosses are real SPY rows
 * (tests/fixtures/real_spy_level_crosses.json). Any page error fails the test.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const CROSSES = require(path.join(__dirname, '..', 'fixtures', 'real_spy_level_crosses.json')).rows.slice(0, 3);
const EVENTS = {
  ticker: 'SPY', tf: '30', window_start_ts_utc: CROSSES[2].ts_utc - 60,
  items: CROSSES.map((c, i) => ({ key: 'x' + c.cross_id, n: 3 - i, ts: c.ts_utc, dom: 'LEVELS', dir: c.direction, marker: true,
    title: 'Crossed ' + (c.direction === 'up' ? 'above ' : 'below ') + c.level_name, detail: c.level_value.toFixed(2), src: '/api/level_crosses' })),
  cross_counts: { up: CROSSES.filter((c) => c.direction === 'up').length, down: CROSSES.filter((c) => c.direction !== 'up').length },
};
const SPOT = 771.3;
const TERRAIN = { ticker: 'SPY', spot: SPOT, gamma_flip: 768, call_wall: 775, put_wall: 765, max_pain: 770, regime: 'LONG_GAMMA',
  posture: 'PINNED', levels_stale: false, flip_relation: 'ABOVE', dist_to_call_wall: 3.7, dist_to_put_wall: 6.3, pcr_all: 1.1 };
const LEVELS = { ticker: 'SPY', spot: SPOT, tf: '30', generation: 1, vwap_series: [],
  levels: [
    { id: 'PDH', price: 773.5, family: 'prior_day', label: 'Prior Day High', evidence_tier: 'MEASURED', distance: 2.2, side: 'ABOVE', near_spot: false },
    { id: 'max_pain', price: 770, family: 'gamma', label: 'Max pain', evidence_tier: 'DERIVED', distance: -1.3, side: 'BELOW', near_spot: false },
  ],
  by_distance: ['max_pain', 'PDH'], families_absent: [], degraded: [] };
const MICRO = { ticker: 'SPY', status: 'ok', top_of_book: { bid: 771.29, ask: 771.31, bid_size: 300, ask_size: 200 },
  spread_pts: 0.02, depth: { '1': { imbalance: 0.2, side: 'BID' }, '5': { bid_total: 3000, ask_total: 2000, imbalance: 0.2, side: 'BID' } },
  ages: { book_age_sec: 1, book_stale: false }, wall_candidates: [], provenance: { book_source: 'NASDAQ_BOOK' },
  flow: { tape_pressure_5m: 0.3, tape_side_5m: 'BUY', tape_pressure_30s: 0.1, tape_pressure_2m: 0.2, cum_delta_proxy: 1000 } };
const LIQ = { ticker: 'SPY', zones: [{ zone_low: 772, zone_high: 773, zone_type: 'resistance_liquidity', confluence_score: 3 },
  { zone_low: 768, zone_high: 769, zone_type: 'support_liquidity', confluence_score: 2 }],
  spot_location: { inside: null, above: 0, below: 1 }, summary: null };
const STRIKES = { ticker: 'SPY', spot: SPOT, spot_strike: 771, today_source: 'terrain_live_cache', levels_stale: false,
  today: { all: [[770, 500000, 1000], [771, 900000, 5000], [772, -200000, 3000]] }, prior: { all: [[770, 400000, 800], [771, 700000, 2000], [772, -100000, 900]] },
  migration: { all: { compared: true, drift: 'UP', grew: [771, 770], shrank: [772], busiest: [771, 772], busiest_vs_walls: 'INSIDE_WALLS',
    volume_total: 9000, rows: [[770, 500000, 400000, 100000], [771, 900000, 700000, 200000], [772, -200000, -100000, -100000]] } } };
const BARS = { ticker: 'SPY', tf: '30', bars: [{ t: 1790343000, o: 770, h: 772, l: 769, c: SPOT, v: 1000, chg: SPOT - 770, chg_pct: (SPOT - 770) / 770 * 100 }] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/desk/events')) body = EVENTS;
    else if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/levels')) body = LEVELS;
    else if (url.includes('/api/order-flow/microstructure')) body = MICRO;
    else if (url.includes('/api/liquidity-snapshot')) body = LIQ;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/session')) body = { session_label: 'RTH' };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

function watchErrors(page) {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  return errs;
}

test.describe('Trade Desk renders served values', () => {
  test('Desk: the served queue, counts, book side, tape side and flip relation', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'desk'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tdmQueue .tdm-q')).toHaveCount(3);
    await expect(page.locator('#tdmQueueCount')).toHaveText('3');
    await expect(page.locator('#tdmCardLiq')).toContainText('BID HEAVY');
    await expect(page.locator('#tdmCardFlow')).toContainText('NET BUYING');
    await expect(page.locator('#tdmCardFlow')).toContainText(EVENTS.cross_counts.up + ' up · ' + EVENTS.cross_counts.down + ' down');
    await expect(page.locator('#tdmAgree')).toContainText('Above flip');
    await expect(page.locator('#tdmAgree')).toContainText('Bid heavy');
    expect(errs).toEqual([]);
  });

  test('Right Now: detect, frame, context and the migration read the served fields', async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk'); localStorage.setItem('ed_sub', 'right-now'); } catch (e) {} });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const body = page.locator('#tdBody');
    await expect(body).toContainText('bid-heavy (depth 5)');
    await expect(body).toContainText('Max pain 770.00');           // nearest by the served by_distance
    await expect(body).toContainText('1.30 below spot');
    await expect(body).toContainText('6.30 above put wall, 3.70 below call wall');
    await expect(body).toContainText('resistance near 772.00');
    await expect(body).toContainText('moved UP the chain');
    await expect(body).toContainText('Grew most at 771/770');
    await expect(body).toContainText('inside the wall range');
    expect(errs).toEqual([]);
  });
});
