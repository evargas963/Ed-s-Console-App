/*
 * Confluence Matrix. The page draws the `confluence` panel on its socket and computes nothing.
 * The panel sent again (the chain or the levels changed) redraws the table and keeps the expiry
 * the operator picked.
 *
 * Real data: the confluence body as the real code served it on MRVL's full chain captured
 * 2026-10-07 10:31:20 ET (tests/fixtures/real_mrvl_confluence_payloads_2026_10_07.json).
 */
const { test, expect } = require('@playwright/test');
const { mockPriceSocket } = require('./fixtures/price_socket');
const FX = require('../fixtures/real_mrvl_confluence_payloads_2026_10_07.json');

const FRONT = '2026-10-09';
const NEXT = '2026-10-16';

function served(expiry) {
  return FX.by_expiry[expiry] || FX.by_expiry[FRONT];
}

async function openMatrix(page) {
  await page.addInitScript(() => {
    localStorage.setItem('ed_ticker', 'MRVL');
    localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'confluence');
  });
  await page.goto('/');
}

test('a cell shades by its value against its column peak, in the theme heat colours', async ({ page }) => {
  // the straight proportion: the theme's zero toward its negative colour by |value| / peak,
  // worked out here from the served numbers and the page's own colour tokens
  const body = served(FRONT);
  await mockPriceSocket(page, [], [], undefined, { confluence: body });
  await openMatrix(page);
  const i =body.rows.findIndex((r, n) => n > 0 && r.net_gex != null && r.net_gex < 0);
  expect(i).toBeGreaterThan(0);
  const v = body.rows[i].net_gex, peak = body.peaks.net_gex;
  const cell = page.locator('#cmRows tr[data-i="' + i + '"] td').nth(3);   // strike, distance, score, net
  await expect(cell).toHaveText(body.rows[i].net_gex_text);
  const [zero, neg, bg] = await cell.evaluate((el) => {
    const cs = getComputedStyle(document.documentElement);
    return [cs.getPropertyValue('--ed-heat-zero'), cs.getPropertyValue('--ed-heat-neg'), getComputedStyle(el).backgroundColor];
  });
  const rgb = (h) => { const n = parseInt(h.trim().slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
  const t = Math.abs(v) / peak, a = rgb(zero), b = rgb(neg);
  expect(t).toBeGreaterThan(0);
  expect(t).toBeLessThan(1);
  expect(bg).toBe('rgb(' + a.map((x, k) => Math.round(x + (b[k] - x) * t)).join(', ') + ')');
});

test('a price that has stopped marks the spot not live with its time and age', async ({ page }) => {
  // AGENTS rule 5: the confluence panel as the real code serves it on SPY's 2026-10-22 close
  // publication, its 16:39 print the last price and the daemon's connection ended, read at 18:00
  // (tests/test_level_crosses_wire.py keeps this file equal to the program's answer)
  const STOPPED = require('../fixtures/real_spy_confluence_at_a_stopped_price_2026_10_22.json');
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  await mockPriceSocket(page, [], [], undefined, { confluence: STOPPED });
  await page.addInitScript(() => {
    localStorage.setItem('ed_ticker', 'SPY');
    localStorage.setItem('ed_ws', 'trade-desk');
    localStorage.setItem('ed_sub', 'confluence');
  });
  await page.goto('/');
  expect(STOPPED.spot_not_live_text).toContain('last trade');
  await expect(page.locator('#cmBody')).toContainText(STOPPED.spot_text);
  await expect(page.locator('#cmBody')).toContainText(STOPPED.spot_not_live_text);
  expect(errs).toEqual([]);
});

test('the matrix redraws when the priced chain updates and keeps the expiry', async ({ page }) => {
  const errs = [];
  const expiries = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text());
  });
  // the expiry each confluence panel sent was asked with (none: the program's front one)
  const sock = await mockPriceSocket(page, [], [], undefined, { confluence: (key, params) => {
    expiries.push(params.expiry);
    return served(params.expiry);
  } });
  const confluenceAsks = () => sock.subscribes.map((s) => JSON.stringify(s.panels.confluence));
  await openMatrix(page);
  const body = served(FRONT);
  const rows = body.rows;
  const hi = rows[0].strike;
  const lo = rows[rows.length - 1].strike;
  await expect(page.locator('#cmBody')).toContainText(rows[0].score_text);
  await expect(page.locator('#cmBody td', { hasText: /^-$/ }).first()).toBeVisible();
  await expect(page.locator('#cmBody h1')).toHaveCount(0);
  await expect(page.locator('#cmBody')).not.toContainText('Hover a level to trace its price');
  await expect(page.locator('#cmExp')).toHaveValue(FRONT);
  const inside = body.levels.filter((l) => l.price <= hi && l.price >= lo);
  expect(inside.length).toBeGreaterThan(0);
  for (const lv of inside) {
    await expect(page.locator('.level-pill', { hasText: lv.abbrev + ' ' + lv.price_text }).first()).toBeAttached();
  }
  for (const lv of body.levels.filter((l) => l.price > hi)) {
    await expect(page.locator('#cmAbove')).toContainText(lv.abbrev + ' ' + lv.price_text);
  }
  for (const lv of body.levels.filter((l) => l.price < lo)) {
    await expect(page.locator('#cmBelow')).toContainText(lv.abbrev + ' ' + lv.price_text);
  }
  const font = await page.locator('.cm-page').evaluate((el) => getComputedStyle(el).fontSize);
  expect(font).toBe('13px');
  const opened = expiries.length;
  expect(opened).toBeGreaterThan(0);

  const row = rows.find((r) => r.score_text && r.contributions.length);
  const first = row.contributions[0];
  await page.locator('#cmBody tbody tr[data-i="' + rows.indexOf(row) + '"]').click();
  await expect(page.locator('#cmDetail')).toContainText(first.label + ' ' + first.text);
  await expect(page.locator('#cmDetail')).toContainText(row.net_gex_text + 'M');
  await expect(page.locator('#cmDetail')).toContainText(row.charm_text + 'k');
  await expect(page.locator('#cmDetail')).toContainText('$ per 1% move');
  await expect(page.locator('#cmDetail')).toContainText('delta-shares / day');

  // the panel sent again: the front expiry stays (the page asked none, the program's front one)
  sock.changed('confluence');
  await expect.poll(() => expiries.length).toBe(opened + 1);
  expect(expiries[expiries.length - 1]).toBeUndefined();
  await expect(page.locator('#cmExp')).toHaveValue(FRONT);
  await expect(page.locator('#cmDetail')).toContainText(first.label + ' ' + first.text);

  await page.locator('#cmExp').selectOption(NEXT);
  await expect.poll(() => expiries[expiries.length - 1]).toBe(NEXT);
  const picked = expiries.length;

  sock.changed('confluence');
  await expect.poll(() => expiries.length).toBe(picked + 1);
  expect(expiries[expiries.length - 1]).toBe(NEXT);
  await expect(page.locator('#cmExp')).toHaveValue(NEXT);

  // the view opened again asks for the same panel of the same expiry: nothing new is asked or sent
  const asks = confluenceAsks();
  expect(asks[asks.length - 1]).toBe(JSON.stringify({ expiry: NEXT }));
  await page.getByRole('button', { name: 'Confluence Matrix' }).click();
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 300)));
  expect(confluenceAsks()).toEqual(asks);
  expect(expiries.length).toBe(picked + 1);
  await expect(page.locator('#cmExp')).toHaveValue(NEXT);
  expect(errs).toEqual([]);
});

test('a passed expiry is replaced by the one the server returns', async ({ page }) => {
  const asked = [];
  let afterItPassed = false;
  const sock = await mockPriceSocket(page, [], [], undefined, { confluence: (key, params) => {
    asked.push(params.expiry);
    return afterItPassed ? FX.front_passed : served(params.expiry);
  } });
  await openMatrix(page);
  await expect(page.locator('#cmBody')).toContainText(served(FRONT).rows[0].score_text);
  // the operator's own pick of the front expiry, so the page asks for it by name
  await page.locator('#cmExp').selectOption(NEXT);
  await expect.poll(() => asked[asked.length - 1]).toBe(NEXT);
  await page.locator('#cmExp').selectOption(FRONT);
  await expect.poll(() => asked[asked.length - 1]).toBe(FRONT);
  await expect(page.locator('#cmExp')).toHaveValue(FRONT);
  afterItPassed = true;
  const before = asked.length;
  sock.changed('confluence');
  await expect.poll(() => asked.length).toBe(before + 1);
  expect(asked[asked.length - 1]).toBe(FRONT);
  await expect(page.locator('#cmExp')).toHaveValue(FX.front_passed.expiry);
  await expect(page.locator('#cmExp option[value="' + FRONT + '"]')).toHaveCount(0);
});
