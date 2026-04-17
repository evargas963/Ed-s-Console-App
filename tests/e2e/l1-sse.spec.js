// @ts-check
const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ED_E2E__ = true;
  });
});

test('L1 EventSource URL matches active ticker (SPY default)', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => !!(window.__edTestHooks && window.__edTestHooks.getL1LightStreamUrl && window.__edTestHooks.getL1LightStreamUrl()),
    null,
    { timeout: 90000 },
  );
  await page.waitForFunction(
    () => {
      const e = window.__edTestHooks.getL1LightEventSource();
      return e && e.readyState === 1;
    },
    null,
    { timeout: 90000 },
  );
  const url = await page.evaluate(() => window.__edTestHooks.getL1LightStreamUrl());
  expect(url).toContain('ticker=SPY');
  const es = await page.evaluate(() => {
    const e = window.__edTestHooks.getL1LightEventSource();
    return e ? e.readyState : null;
  });
  expect(es).toBe(1);
});

test('L1 stream URL updates after ticker switch', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => !!(window.__edTestHooks && window.__edTestHooks.fetchState),
    null,
    { timeout: 90000 },
  );
  await page.evaluate(async () => {
    const inp = document.getElementById('ticker-input');
    inp.value = 'QQQ';
    await window.__edTestHooks.fetchState(true);
  });
  await page.waitForFunction(
    () => window.__edTestHooks.getActiveTicker() === 'QQQ',
    null,
    { timeout: 90000 },
  );
  const url = await page.evaluate(() => window.__edTestHooks.getL1LightStreamUrl());
  expect(url).toContain('ticker=QQQ');
});

test('renderTierBLight rejects stale l1_generation vs prior SSE/HTTP', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.__edTestHooks?.renderTierBLight, null, { timeout: 90000 });
  const ok = await page.evaluate(() => {
    window._l1GenByScope = { 'SPY|': 99 };
    window._l1ServerTsByScope = { 'SPY|': 500 };
    return window.__edTestHooks.renderTierBLight(
      {
        ticker: 'SPY',
        _tier: 'B_light',
        l1_generation: 3,
        _server_build_ts: 100,
      },
      'e2e',
    );
  });
  expect(ok).toBe(false);
});

test('same l1_generation + older _server_build_ts rejected (HTTP vs SSE reorder)', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.__edTestHooks?.renderTierBLight, null, { timeout: 90000 });
  const ok = await page.evaluate(() => {
    window._l1GenByScope = {};
    window._l1ServerTsByScope = {};
    window.__edTestHooks.renderTierBLight(
      {
        ticker: 'SPY',
        _tier: 'B_light',
        l1_generation: 5,
        _server_build_ts: 200,
      },
      'e2e',
    );
    return window.__edTestHooks.renderTierBLight(
      {
        ticker: 'SPY',
        _tier: 'B_light',
        l1_generation: 5,
        _server_build_ts: 100,
      },
      'e2e',
    );
  });
  expect(ok).toBe(false);
});

test('diagnostics object tracks schema', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.__edTestHooks?.getEdL1SseDiagnostics, null, { timeout: 90000 });
  const d = await page.evaluate(() => window.__edTestHooks.getEdL1SseDiagnostics());
  expect(d.schema).toBe('ed.l1_sse_client.v2');
});

test('L1 stream URL includes expiry after synthetic expiry commit', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.__edTestHooks?.fetchState, null, { timeout: 90000 });
  await page.evaluate(async () => {
    const sel = document.getElementById('expiry-select');
    const opt = document.createElement('option');
    opt.value = '2026-12-19';
    opt.textContent = '2026-12-19';
    sel.appendChild(opt);
    sel.value = '2026-12-19';
    await window.__edTestHooks.fetchState(true);
  });
  await page.waitForFunction(
    () => window.__edTestHooks.getActiveExpiry() === '2026-12-19',
    null,
    { timeout: 90000 },
  );
  const url = await page.evaluate(() => window.__edTestHooks.getL1LightStreamUrl());
  expect(url).toContain('expiry=2026-12-19');
});
