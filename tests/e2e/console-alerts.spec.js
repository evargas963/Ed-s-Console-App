// @ts-check
/**
 * Proximity Alerts strip (ed-alerts.js) <- /api/alerts: the server's alert strings, shown as sent.
 * Hidden with none; one pill per alert; hidden again when the next ticker has none. Offline.
 */
const { test, expect } = require('@playwright/test');

let alertsBody = { alerts: [] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/alerts')) body = alertsBody;
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-18'] };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    else if (url.includes('/api/session')) body = { session_label: 'RTH' };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('proximity alerts strip', () => {
  test.beforeEach(async ({ page }) => {
    alertsBody = { alerts: [] };
    await intercept(page);
  });

  test('hidden when the server reports no alerts', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#alertsStrip')).toBeHidden();
  });

  test('shows each alert the server sends, as sent', async ({ page }) => {
    alertsBody = { alerts: ['Within 0.8pts of 590.00 ceiling wall', 'Just crossed down through gamma_flip level'] };
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#alertsStrip')).toBeVisible();
    await expect(page.locator('.alert-pill')).toHaveCount(2);
    await expect(page.locator('.alert-pill').nth(0)).toHaveText('Within 0.8pts of 590.00 ceiling wall');
    await expect(page.locator('.alert-pill').nth(1)).toHaveText('Just crossed down through gamma_flip level');
  });

  test('a ticker switch to a symbol with no alerts hides the strip again', async ({ page }) => {
    alertsBody = { alerts: ['Within 0.8pts of 580.00 floor wall'] };
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#alertsStrip')).toBeVisible();
    alertsBody = { alerts: [] };
    await page.locator('#symInput').fill('QQQ');
    await page.locator('#symInput').press('Enter');
    await expect(page.locator('#alertsStrip')).toBeHidden();
  });
});
