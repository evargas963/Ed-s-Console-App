// @ts-check
/**
 * Proximity Alerts strip (ed-alerts.js) -- preserved from legacy static/index.html's
 * #alerts-card during the /console cutover (operator directive 2026-09-14): a real,
 * backend-driven capability (MarketState.rules_alerts via /api/analytics/state), not a
 * fabricated client-side one. Proves: hidden with no qualifying alerts; shows only the
 * near/wall/level class of rules_alerts strings (never an unrelated engine-status string);
 * hides again once the backend reports nothing. Offline.
 */
const { test, expect } = require('@playwright/test');

let alertsBody = { rules_alerts: [] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/analytics/state')) body = alertsBody;
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-18'] };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    else if (url.includes('/api/live/state')) body = { ticker: 'SPY', spot: 100, spot_disp: '100.00',
      bid: 99.99, ask: 100.01, session_label: 'RTH', analytics_lightweight: {},
      streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('proximity alerts strip', () => {
  test.beforeEach(async ({ page }) => {
    alertsBody = { rules_alerts: [] };
    await intercept(page);
  });

  test('hidden when the backend reports no qualifying alerts', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#alertsStrip')).toBeHidden();
  });

  test('shows only the near/wall/level class of rules_alerts, filtering out an unrelated engine string', async ({ page }) => {
    alertsBody = { rules_alerts: [
      'SPY approaching call wall near 590',
      'ENGINE CRASH — TypeError: unrelated',
      'QQQ near put wall level',
    ] };
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#alertsStrip')).toBeVisible();
    await expect(page.locator('.alert-pill')).toHaveCount(2);
    await expect(page.locator('.alert-pill').nth(0)).toHaveText('SPY approaching call wall near 590');
    await expect(page.locator('.alert-pill').nth(1)).toHaveText('QQQ near put wall level');
    await expect(page.locator('.alert-pill', { hasText: 'ENGINE CRASH' })).toHaveCount(0);
  });

  test('a ticker switch to a symbol with no alerts hides the strip again', async ({ page }) => {
    alertsBody = { rules_alerts: ['SPY near put wall level'] };
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#alertsStrip')).toBeVisible();
    alertsBody = { rules_alerts: [] };
    await page.locator('#symInput').fill('QQQ');
    await page.locator('#symInput').press('Enter');
    await expect(page.locator('#alertsStrip')).toBeHidden();
  });
});
