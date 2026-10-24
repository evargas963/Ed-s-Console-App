/*
 * Confluence Matrix. The page draws /api/confluence and computes nothing. A priced-book
 * update (the `levels` notice, and a new `chain`) redraws the table and keeps the expiry
 * the operator picked. A flow notice does not.
 *
 * Real data: /api/confluence as the real code served it on MRVL's full chain captured
 * 2026-10-07 10:31:20 ET (tests/fixtures/real_mrvl_confluence_payloads_2026_10_07.json).
 */
const { test, expect } = require('@playwright/test');
const FX = require('../fixtures/real_mrvl_confluence_payloads_2026_10_07.json');

const FRONT = '2026-10-09';
const NEXT = '2026-10-16';

function served(expiry) {
  return FX.by_expiry[expiry] || FX.by_expiry[FRONT];
}

async function openMatrix(page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('ed_ticker', 'MRVL');
      localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'confluence');
    } catch (e) { /* storage unavailable */ }
  });
  await page.goto('/');
}

test('a price that has stopped marks the spot not live with its time and age', async ({ page }) => {
  // AGENTS rule 5: /api/confluence as the real code serves it on SPY's 2026-10-22 close
  // publication, its 16:39 print the last price and the daemon's connection ended, read at 18:00
  // (tests/test_level_crosses_wire.py keeps this file equal to the route's answer)
  const STOPPED = require('../fixtures/real_spy_confluence_at_a_stopped_price_2026_10_22.json');
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  await page.route('**/api/confluence**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STOPPED) }));
  await page.addInitScript(() => {
    try {
      localStorage.setItem('ed_ticker', 'SPY');
      localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'confluence');
    } catch (e) { /* storage unavailable */ }
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
  await page.route('**/api/confluence**', (route) => {
    const asked = new URL(route.request().url()).searchParams.get('expiry');
    expiries.push(asked);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(served(asked)) });
  });
  await openMatrix(page);
  const body = served(FRONT);
  const rows = body.rows;
  const hi = rows[0].strike;
  const lo = rows[rows.length - 1].strike;
  await expect(page.locator('#cmBody')).toContainText(rows[0].score_text);
  await expect(page.locator('#cmBody')).toContainText('—');
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

  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'levels' } }));
  });
  await expect.poll(() => expiries.length).toBe(opened + 1);
  expect(expiries[expiries.length - 1]).toBe(FRONT);
  await expect(page.locator('#cmDetail')).toContainText(first.label + ' ' + first.text);

  await page.locator('#cmExp').selectOption(NEXT);
  await expect.poll(() => expiries[expiries.length - 1]).toBe(NEXT);
  const picked = expiries.length;

  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'chain' } }));
  });
  await expect.poll(() => expiries.length).toBe(picked + 1);
  expect(expiries[expiries.length - 1]).toBe(NEXT);

  await page.getByRole('button', { name: 'Confluence Matrix' }).click();
  await expect.poll(() => expiries.length).toBe(picked + 2);
  expect(expiries[expiries.length - 1]).toBe(NEXT);

  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'flow' } }));
  });
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 300)));
  expect(expiries.length).toBe(picked + 2);
  expect(errs).toEqual([]);
});

test('a passed expiry is replaced by the one the server returns', async ({ page }) => {
  const asked = [];
  let afterItPassed = false;
  await page.route('**/api/confluence**', (route) => {
    asked.push(new URL(route.request().url()).searchParams.get('expiry'));
    const body = afterItPassed ? FX.front_passed : served(FRONT);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await openMatrix(page);
  await expect(page.locator('#cmBody')).toContainText(served(FRONT).rows[0].score_text);
  afterItPassed = true;
  const before = asked.length;
  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'levels' } }));
  });
  await expect.poll(() => asked.length).toBe(before + 1);
  expect(asked[asked.length - 1]).toBe(FRONT);
  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'chain' } }));
  });
  await expect.poll(() => asked[asked.length - 1]).toBe(FX.front_passed.expiry);
});
