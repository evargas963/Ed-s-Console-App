// INDUCED TEST CONDITION (throwaway branch, never merged): one deliberate failure on the loaded
// console, to prove CI uploads the playwright-failures artifact with the failing test's trace.
import { test, expect } from '@playwright/test';

test('induced failure: an element that does not exist', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#induced-failure-no-such-element')).toBeVisible({ timeout: 2000 });
});
