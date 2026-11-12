// @ts-check
/**
 * The ONE presentation-scope control (Auto / Wider / All available) governs every Gamma panel: each
 * panel asks the server for its window with the scope and draws the rows it is sent. The server
 * picks the rows (terrain_engine.strike_window, proven in tests/test_heatmap_window_v1.py); here
 * the socket sends the server's own answer per scope on CRWD's real chain -- 11, 23 or all 122
 * strikes around 270 -- and the page is proved to ask with the scope, draw what it is sent and
 * keep the choice.
 */
const { test, expect } = require('@playwright/test');
const { routeWatchlist } = require('./fixtures/watchlist');
const { mockPriceSocket } = require('./fixtures/price_socket');
const { watchRequests } = require('./fixtures/settled');

// the strikes panel per scope, the levels and the heatmap as the server sends them on CRWD's real
// chain (held to the server by tests/test_vanna_charm_by_strike_v1.py)
const REAL = require('./fixtures/vanna_charm_panels_crwd.json');
const BY_SCOPE = { auto: REAL.strikes, wider: REAL.strikes_wider, all: REAL.strikes_all };
const WINDOW = { auto: BY_SCOPE.auto.today.all, wider: BY_SCOPE.wider.today.all, all: BY_SCOPE.all.today.all };
function strikesFor(scope) { return BY_SCOPE[scope]; }
const SPOT = REAL.strikes.spot_strike;                                  // the strike at the price
const label = (k) => (k % 1 ? k.toFixed(2) : String(k));                // a strike as the page writes it
const TERRAIN = REAL.terrain;
const BARS = { ticker: 'SPY', bars: [-0.4, -0.1, 0.1, -0.2, 0.3, 0.5, 0.2, 0.0].map(function (d, i) {
  const c = SPOT + d;
  return { t: 1757000000 + i * 60, o: c - 0.1, h: c + 0.2, l: c - 0.2, c: c, v: 1000 + i }; }) };
const SURFACE = REAL.surface;

// the page's socket sends `panels` (a test may change one before the page opens); the strikes
// panel is the window per scope each reader asks, its scope noted in `asked`
async function intercept(page, asked, panels) {
  await routeWatchlist(page, ['SPY']);
  panels.terrain = TERRAIN;
  panels.bars = BARS;
  panels.surface = SURFACE;
  panels.strikes = (key, params) => { asked.push(params.scope); return strikesFor(params.scope); };
  return mockPriceSocket(page, [], [], undefined, panels);
}

test.describe('the Gamma presentation scope', () => {
  let asked, panels, sock;
  test.beforeEach(async ({ page }) => {
    asked = []; panels = {};
    sock = await intercept(page, asked, panels);
    // each Playwright test gets a fresh context (localStorage already empty), so we only seed the
    // ticker — NOT localStorage.clear(), which would re-run on reload and wipe the persisted scope.
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); });
  });

  test('one control governs the workspace, labelled "All available" not "Full"', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const ctl = page.locator('#scopeCtl');
    await expect(ctl).toBeVisible();                                   // shown for the gamma subview
    await expect(ctl.locator('.scbtn')).toHaveCount(3);
    await expect(ctl.locator('.scbtn', { hasText: 'Auto' })).toBeVisible();
    await expect(ctl.locator('.scbtn', { hasText: 'Wider' })).toBeVisible();
    await expect(ctl.locator('.scbtn', { hasText: 'All available' })).toBeVisible();
    await expect(ctl).not.toContainText('Full');                      // never mislabel as a full book
    // hidden outside options/gamma
    await page.locator('.navitem[data-ws="system"]').click();
    await expect(ctl).toBeHidden();
    await page.locator('.navitem[data-ws="options"]').click();
    await expect(ctl).toBeVisible();
  });

  test('a strike of GEX not known keeps its row: no bar, the dash, no page error', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    // induced: the real rows with the GEX and volume of the strike at the price not known
    const rows = WINDOW.auto.map((r) => (r[0] === SPOT ? [r[0], null, null] : r));
    panels.strikes = Object.assign({}, strikesFor('auto'), { today: { all: rows } });
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const row = page.locator('#gbsBody .gbs-row[data-strike="' + SPOT + '"]');
    await expect(row.locator('.gbs-v')).toHaveText('-');
    await expect(row.locator('.gbs-vol')).toHaveText('-');
    await expect(row.locator('.gbs-chg')).toHaveText('-');
    expect(await row.locator('.gbs-bar').evaluate((el) => el.style.width)).toBe('0%');
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(rows.length);
    expect(errors).toEqual([]);
  });

  test('GEX-by-strike asks with the scope and draws the served window, legible at every scope', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const gbs = page.locator('#gbsBody');
    for (const [label, scope] of [['Auto', 'auto'], ['All available', 'all'], ['Wider', 'wider']]) {
      await page.locator('#scopeCtl .scbtn', { hasText: label }).click();
      await expect.poll(() => asked[asked.length - 1]).toBe(scope);
      const rows = WINDOW[scope];
      await expect(gbs.locator('.gbs-row')).toHaveCount(rows.length);
      await expect(gbs.locator('.gbs-row').first().locator('.gbs-k')).toHaveText(label(rows[rows.length - 1][0]));
      await expect(gbs.locator('.gbs-row').last().locator('.gbs-k')).toHaveText(label(rows[0][0]));
      // rows keep a legible height at every count (never shrunk to fit)
      const rowH = await gbs.locator('.gbs-row').first().evaluate((el) => el.getBoundingClientRect().height);
      expect(rowH).toBeGreaterThanOrEqual(24);
      await expect(gbs.locator('.scope-note')).toHaveCount(0);   // no structure notes
    }
  });

  test('the Chart view asks with the same control and draws the served window', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab', { hasText: 'Chart' }).click();
    const rows = () => page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows);
    await expect.poll(rows).toBe(WINDOW.auto.length);
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect.poll(rows).toBe(WINDOW.all.length);
  });

  test('a drag that ends while a read is in flight settles where the drag ended', async ({ page }) => {
    // a panel answered mid-drag must not reset the pan, or the window asked after it is the
    // earlier one and the drag snaps back
    const requests = watchRequests(page);
    // a slow answer: a panned window's panel is sent 400 ms after it is asked, for the window
    // the page then shows
    let late = false;
    panels.strikes = (key, params) => {
      if (params.centre == null || late) return strikesFor(params.scope);
      setTimeout(() => { late = true; sock.changed('strikes'); late = false; }, 400);
      return undefined;
    };
    // the window GEX by Strike asks on each subscribe
    const asks = () => sock.subscribes.map((s) => s.panels['strikes:gbs']).filter(Boolean)
      .map((w) => ({ centre: w.centre, shift: w.shift }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const atPrice = page.locator('#gbsBody .gbs-row.spot .gbs-k');    // the row at the price, in view
    await expect(atPrice).toBeVisible();
    const box = await atPrice.boundingBox();
    const rowH = await page.locator('#gbsBody .gbs-row').first().evaluate((el) => el.getBoundingClientRect().height);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    for (let i = 1; i <= 3; i++) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + i * rowH);
    await page.mouse.up();
    const centre = REAL.strikes.views.all.centre;
    await expect.poll(() => asks().pop(), { timeout: 5000 }).toEqual({ centre: centre, shift: 3 });
    await requests.settled();                                        // every held read has run
    await page.waitForTimeout(600);                                  // and the slow panels have been sent
    expect(asks().pop()).toEqual({ centre: centre, shift: 3 });
  });

  test('the scope choice persists across reloads (ed_scope)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('#scopeCtl .scbtn', { hasText: 'All available' }).click();
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(WINDOW.all.length);
    asked.length = 0;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#scopeCtl .scbtn.on')).toHaveText('All available');
    await expect.poll(() => asked[0]).toBe('all');
    await expect(page.locator('#gbsBody .gbs-row')).toHaveCount(WINDOW.all.length);
  });
});
