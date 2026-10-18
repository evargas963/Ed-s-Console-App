/*
 * Confluence Matrix. The page draws /api/confluence and computes nothing. A priced-book
 * update (the `levels` notice, and a new `chain`) redraws the table and keeps the expiry
 * the operator picked. A flow notice does not.
 */
const { test, expect } = require('@playwright/test');

function matrix(expiry) {
  return {
    available: true, ticker: 'SPY', preset: '0DTE', ceiling: 72,
    chain_as_of_time_ct: '10:00:00 AM CT',
    expiry: expiry || '2026-10-16',
    expiries: [{ expiry: '2026-10-16', dte: 0 }, { expiry: '2026-10-23', dte: 7 }],
    weights_in_score: { CHARMM: 0.22, DGEXM: 0, GEXM: 0.15, FLOWM: 0 },
    spot: 670, spot_under: 671, thin: true, flat_factors: [], slopes: [], offscreen: [],
    rows: [{
      strike: 671, distance_text: '1.00', score: 40, score_text: '40', heat: 0.55,
      net_gex_text: '18.00', gross_text: '42.00', oi_text: '14', pc_gex_text: '0.40',
      dgex_text: null, volume_text: '4', pc_vol_text: '0.33', vol_oi_text: '0.29',
      flow_text: null, dex_text: '0.00', vanna_text: '0.00', iv_text: '20.0', charm_text: '1.00',
      markers: [], missing: [], spot_line: true,
      contributions: [{ label: 'net gamma', text: '12.0', raw_text: '18.00', normalized_text: '0.80', weight_text: '0.15' }],
      factors: [{ label: 'net gamma', text: '12.0', raw_text: '18.00', normalized_text: '0.80', weight_text: '0.15' }],
    }],
  };
}

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
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(matrix(asked)),
    });
  });
  await page.addInitScript(() => {
    try {
      localStorage.setItem('ed_ticker', 'SPY');
      localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'confluence');
    } catch (e) { /* storage unavailable */ }
  });
  await page.goto('/');
  await expect(page.locator('#cmBody')).toContainText('40');
  await expect(page.locator('#cmBody')).toContainText('—');
  const opened = expiries.length;
  expect(opened).toBeGreaterThan(0);

  await page.locator('#cmBody tbody tr[data-i]').click();
  await expect(page.locator('#cmDetail')).toContainText('net gamma 12.0');

  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'levels' } }));
  });
  await expect.poll(() => expiries.length).toBe(opened + 1);
  expect(expiries[expiries.length - 1]).toBe('2026-10-16');
  await expect(page.locator('#cmDetail')).toContainText('net gamma 12.0');

  await page.getByRole('button', { name: '2026-10-23 · 7' }).click();
  await expect.poll(() => expiries[expiries.length - 1]).toBe('2026-10-23');
  const picked = expiries.length;

  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'chain' } }));
  });
  await expect.poll(() => expiries.length).toBe(picked + 1);
  expect(expiries[expiries.length - 1]).toBe('2026-10-23');

  await page.getByRole('button', { name: 'Confluence Matrix' }).click();
  await expect.poll(() => expiries.length).toBe(picked + 2);
  expect(expiries[expiries.length - 1]).toBe('2026-10-23');

  await page.evaluate(() => {
    document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'flow' } }));
  });
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 300)));
  expect(expiries.length).toBe(picked + 2);
  expect(errs).toEqual([]);
});
