// @ts-check
/**
 * #8 PANEL MAXIMIZE — maximize/restore the Gamma main analytical panel (Heatmap/Chart). Presentation
 * only: it hides the Key Levels rail + bottom strip and lets the heatmap fill the workspace, WITHOUT
 * touching the shared ticker / strike / expiry / scope state — so Restore returns to the exact same
 * context. Esc restores; the choice persists. Offline.
 */
const { test, expect } = require('@playwright/test');
const { pushExpiries } = require('./fixtures/expiries');
const { chainAt } = require('./fixtures/price_socket');
const { routeWatchlist } = require('./fixtures/watchlist');

// every panel is the server's own answer on AMZN's real chain of 2026-11-12 10:39 ET, 24 expiries
// (held to the server by tests/test_e2e_panels_two_day_v1.py)
const REAL = require('./fixtures/panels_amzn_two_day.json');
const EXPS = REAL.surface.expirations;
const E2 = EXPS[1].expiry;                 // 2026-11-16, the second expiry
const K = 272.5;                           // the strike above the one at the price

async function intercept(page) {
  await routeWatchlist(page, ['AMZN']);
  await pushExpiries(page, EXPS.map((e) => e.expiry), Object.fromEntries(EXPS.map((e) => [e.expiry, e.dte])), {
    bars: REAL.bars['1'], terrain: REAL.terrain, strikes: REAL.strikes, surface: REAL.surface,
    chain: chainAt(REAL.chain) });
}

test.describe('#8 Gamma panel maximize', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'AMZN'); });
  });

  test('maximize hides the rail + bottom and lets the heatmap fill; Esc restores', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#maxBtn')).toBeVisible();
    await expect(page.locator('.p-levels')).toBeVisible();
    await expect(page.locator('.p-bottom')).toBeVisible();
    await page.locator('#maxBtn').click();
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(1);
    await expect(page.locator('.p-levels')).toBeHidden();
    await expect(page.locator('.p-bottom')).toBeHidden();
    await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();   // heatmap still there, filling
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: 'test-results/gamma-maximized-1672x941.png', fullPage: false });
    await page.keyboard.press('Escape');
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(0);
    await expect(page.locator('.p-levels')).toBeVisible();
    await expect(page.locator('.p-bottom')).toBeVisible();
  });

  test('maximize preserves the shared ticker / strike / expiry context', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('#expSel').selectOption(E2);                              // pick a single expiry
    await page.locator('#view-heatmap .hcell[data-strike="' + K + '"]').first().click(); // pick a strike
    const before = await page.evaluate(() => window.EdShell.getState());
    await page.locator('#maxBtn').click();
    await page.locator('#maxBtn').click();                                        // maximize then restore
    const after = await page.evaluate(() => window.EdShell.getState());
    expect(after.ticker).toBe(before.ticker);
    expect(after.selStrike).toBe(K);
    expect(after.expiryFilter).toBe(E2);
    await expect(page.locator('#expSel')).toHaveValue(E2);
    await expect(page.locator('#sdCtx')).toContainText('272.50');                 // Strike Detail context intact
  });

  test('the maximize choice persists across reload', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('#maxBtn').click();
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(1);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(1);
    await expect(page.locator('.p-bottom')).toBeHidden();
  });
});
