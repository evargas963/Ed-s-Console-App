'use strict';
/**
 * The Vanna and Charm tabs draw the panels the program sends on the page's socket (/ws:
 * server.vanna_by_strike, server.charm_by_strike): while a tab is on, the subscribe names its
 * panel and the window it asks (the scope and the operator's pan), and the page asks no route
 * for it. The bars are the producer's own answer for CRWD's real 2026-10-07 chain at Schwab's
 * CRWD price (fixtures/vanna_charm_panels_crwd.json, held to the producer by
 * tests/test_vanna_charm_by_strike_v1.py); the "no levels" answer is the producer's own words
 * for a ticker with none published. Offline.
 */
const { test, expect } = require('@playwright/test');
const { served, priceRow } = require('./fixtures/price_socket');
const { routeWatchlist } = require('./fixtures/watchlist');
const PANELS = require('./fixtures/vanna_charm_panels_crwd.json');

// server.vanna_by_strike's answer for a ticker with no levels published yet
const NO_LEVELS = { available: false, reason: 'no levels published for this ticker yet' };
const AUTO = { scope: 'auto', centre: null, shift: 0 };

function frame(kind, ticker, body) {
  return JSON.stringify(Object.assign({}, body, { type: kind, ticker: served(ticker).key }));
}
// CRWD's panels as the program answers a subscribe on CRWD: each one it names
function answerCrwd(ws, req) {
  if (req.ticker !== 'CRWD') return;
  ['vanna', 'charm'].forEach((k) => { if (req.panels[k]) ws.send(frame(k, 'CRWD', PANELS[k])); });
}

// The page on the Options workspace's `sub` tab, on CRWD. `answer(ws, req, n)`: the program's
// side of the page's n-th connection, after its answer naming each symbol.
async function open(page, sub, answer) {
  const subscribes = [], asked = [];
  page.on('request', (r) => { if (/vanna|charm/.test(r.url())) asked.push(r.url()); });
  await page.route('**/api/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await routeWatchlist(page, ['CRWD', 'MRVL']);
  let n = 0;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const conn = ++n;
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== 'subscribe') return;
      subscribes.push(req);
      ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
      answer(ws, req, conn);
    });
  });
  await page.addInitScript((s) => {
    localStorage.setItem('ed_ticker', 'CRWD'); localStorage.setItem('ed_ws', 'options'); localStorage.setItem('ed_sub', s);
  }, sub);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  return { subscribes, asked, last: () => subscribes[subscribes.length - 1] };
}
// the strikes a bar list draws, highest first
function strikes(page, host) {
  return page.locator(host + ' .gbs-row').evaluateAll((rs) => rs.map((r) => Number(r.getAttribute('data-strike'))));
}
function sentStrikes(kind) { return PANELS[kind].rows.map((r) => r[0]).reverse(); }

test.describe('Vanna and Charm by strike: the panels on the page\'s socket', () => {
  test('the Vanna tab names its panel and window on the subscribe and draws the bars sent, asking no route', async ({ page }) => {
    const s = await open(page, 'vanna', answerCrwd);
    await expect.poll(() => strikes(page, '#vnBody')).toEqual(sentStrikes('vanna'));
    expect(s.last().panels).toEqual({ expiries: {}, vanna: AUTO });
    expect(s.asked).toEqual([]);
  });

  test('switching to the Charm tab swaps the panel the subscribe names', async ({ page }) => {
    const s = await open(page, 'vanna', answerCrwd);
    await expect.poll(() => strikes(page, '#vnBody')).toEqual(sentStrikes('vanna'));
    await page.evaluate(() => window.EdShell.setSubview('charm'));
    await expect.poll(() => strikes(page, '#chmBody')).toEqual(sentStrikes('charm'));
    expect(s.last().panels).toEqual({ expiries: {}, charm: AUTO });
  });

  test('a new scope and a pan ask the new window; a double-click follows the price again', async ({ page }) => {
    const s = await open(page, 'vanna', answerCrwd);
    await expect.poll(() => strikes(page, '#vnBody')).toEqual(sentStrikes('vanna'));
    await page.evaluate(() => window.EdShell.setScope('all'));
    await expect.poll(() => s.last().panels.vanna).toEqual({ scope: 'all', centre: null, shift: 0 });
    // drag the strike labels two rows down: two rows from the centre on screen (the one sent)
    const label = page.locator('#vnBody .gbs-k').first();
    const box = await label.boundingBox();
    const row = (await page.locator('#vnBody .gbs-row').first().boundingBox()).height;
    await page.mouse.move(box.x + 2, box.y + 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 2, box.y + 2 + 2 * row, { steps: 4 });
    await page.mouse.up();
    await expect.poll(() => s.last().panels.vanna).toEqual({ scope: 'all', centre: PANELS.vanna.view.centre, shift: 2 });
    await label.dblclick();
    await expect.poll(() => s.last().panels.vanna).toEqual({ scope: 'all', centre: null, shift: 0 });
  });

  test('a ticker switch shows "-" until the new ticker\'s panel; a late one for the ticker left is ignored', async ({ page }) => {
    let program;
    await open(page, 'vanna', (ws, req) => { program = ws; answerCrwd(ws, req); });
    await expect.poll(() => strikes(page, '#vnBody')).toEqual(sentStrikes('vanna'));
    await page.evaluate(() => window.EdShell.setTicker('MRVL'));   // MRVL's panel is held back
    await expect(page.locator('#vnBody .placeholder')).toHaveText('-');
    // CRWD's next panel, still in flight to a page that has left CRWD; then a MRVL row drawn
    // after it: once the row is on screen, the panel before it was read
    program.send(frame('vanna', 'CRWD', PANELS.vanna));
    program.send(JSON.stringify({ type: 'quotes', rows: [priceRow('MRVL', 87.65)] }));
    await expect(page.locator('#hPx')).toContainText('87.65');
    await expect(page.locator('#vnBody .placeholder')).toHaveText('-');
    expect(await page.locator('#vnBody .gbs-row').count()).toBe(0);
    program.send(frame('vanna', 'MRVL', NO_LEVELS));   // MRVL's own: no levels yet, said so
    await expect(page.locator('#vnBody .placeholder')).toHaveText(NO_LEVELS.reason);
  });

  test('the socket drops and returns: the subscribe names the panel again and the bars sent are drawn', async ({ page }) => {
    let first;
    const s = await open(page, 'vanna', (ws, req, n) => {
      if (n === 1) { first = ws; answerCrwd(ws, req); return; }
      if (req.panels.vanna) ws.send(frame('vanna', 'CRWD', NO_LEVELS));   // the program after the drop
    });
    await expect.poll(() => strikes(page, '#vnBody')).toEqual(sentStrikes('vanna'));
    const before = s.subscribes.length;
    first.close();
    await expect(page.locator('#vnBody .placeholder')).toHaveText(NO_LEVELS.reason);
    expect(s.subscribes.slice(before).map((r) => r.panels.vanna)).toContainEqual(AUTO);
  });

  // live_ui._produce's frame for a producer that raised: the panel's words, nothing else
  const FAILED = { failed: "the program could not produce this panel: TypeError: 'NoneType' object is not iterable" };

  test('a panel the program could not produce says why; the other panels and the prices keep coming', async ({ page }) => {
    await open(page, 'vanna', (ws, req) => {
      ws.send(frame('vanna', 'CRWD', FAILED));
      ws.send(frame('expiries', 'CRWD', FAILED));
      ws.send(JSON.stringify({ type: 'quotes', rows: [priceRow('CRWD', 269.4)] }));
      if (req.panels.charm) ws.send(frame('charm', 'CRWD', PANELS.charm));
    });
    await expect(page.locator('#vnBody .placeholder')).toHaveText(FAILED.failed);
    await expect(page.locator('#expSel option[disabled]')).toHaveText(FAILED.failed);
    await expect(page.locator('#hPx')).toContainText('269.40');
    await page.evaluate(() => window.EdShell.setSubview('charm'));   // the same socket, still open
    await expect.poll(() => strikes(page, '#chmBody')).toEqual(sentStrikes('charm'));
  });

  test('leaving the tab drops the panel from the subscribe', async ({ page }) => {
    const s = await open(page, 'vanna', answerCrwd);
    await expect.poll(() => strikes(page, '#vnBody')).toEqual(sentStrikes('vanna'));
    await page.evaluate(() => window.EdShell.setSubview('gamma'));
    // the Gamma tab's own panels (Key Levels, GEX by Strike) in its place
    await expect.poll(() => s.last().panels).toEqual({ expiries: {}, 'terrain:levels': {}, 'strikes:gbs': AUTO });
  });
});
