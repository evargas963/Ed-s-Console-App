// @ts-check
/**
 * STACK-WIRE-3-UI-FUSION-TRADABILITY-GATE — behavioral spec for the UI mirror of
 * fusion_contract.is_ms_dict_fusion_authoritative.
 *
 * The split-brain payload (fusion_available=True + canonical_provenance="canonical_forecast_missing")
 * must NEVER report fusion as "active" or steer effectiveDirection off fusion_dominant_direction
 * — even when the bare flag is true. The server now keys stack_runtime.fusion_active off the
 * tradability gate (STACK-WIRE-4-CAND @ ebf2609); this spec pins the UI side end-to-end.
 */
const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ED_E2E__ = true;
  });
});

test('isFusionAuthoritative gates on stack_runtime.fusion_active and tradability provenance', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });

  await page.waitForFunction(
    () => typeof window.isFusionAuthoritative === 'function',
    null,
    { timeout: 30000 },
  );

  // Primary path: stack_runtime.fusion_active is server-stamped truth.
  const rtActive = await page.evaluate(() =>
    window.isFusionAuthoritative({ stack_runtime: { fusion_active: true } }),
  );
  expect(rtActive).toBe(true);

  const rtInactive = await page.evaluate(() =>
    window.isFusionAuthoritative({ stack_runtime: { fusion_active: false } }),
  );
  expect(rtInactive).toBe(false);

  // Split-brain payload: bare flag true + non-tradable provenance must resolve to false
  // when stack_runtime is absent (legacy/error path).
  const splitBrain = await page.evaluate(() =>
    window.isFusionAuthoritative({
      fusion_available: true,
      canonical_provenance: 'canonical_forecast_missing',
    }),
  );
  expect(splitBrain).toBe(false);

  // Authoritative provenance with bare flag (no stack_runtime) → true (mirrors
  // TRADABLE_CANONICAL_PROVENANCE = {"bayesian_fusion"}).
  const authoritative = await page.evaluate(() =>
    window.isFusionAuthoritative({
      fusion_available: true,
      canonical_provenance: 'bayesian_fusion',
    }),
  );
  expect(authoritative).toBe(true);

  // Empty / missing provenance with bare flag must NOT be treated as tradable.
  const emptyProv = await page.evaluate(() =>
    window.isFusionAuthoritative({ fusion_available: true, canonical_provenance: '' }),
  );
  expect(emptyProv).toBe(false);

  // stack_runtime authority outranks bare flag — even if the bare flag is true and
  // provenance is bayesian_fusion, rt.fusion_active=false (server's tightened gate)
  // must veto.
  const rtVeto = await page.evaluate(() =>
    window.isFusionAuthoritative({
      stack_runtime: { fusion_active: false },
      fusion_available: true,
      canonical_provenance: 'bayesian_fusion',
    }),
  );
  expect(rtVeto).toBe(false);
});

test('effectiveDirection refuses fusion_dominant_direction when not authoritative', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });

  await page.waitForFunction(
    () => typeof window.effectiveDirection === 'function',
    null,
    { timeout: 30000 },
  );

  // Authoritative → direction comes from fusion_dominant_direction.
  const auth = await page.evaluate(() =>
    window.effectiveDirection({
      stack_runtime: { fusion_active: true },
      fusion_dominant_direction: 'up',
      dominant_dir: 'down',
    }),
  );
  expect(auth).toBe('up');

  // Split-brain (non-tradable provenance) → withhold direction (LIVE-UI-A).
  const split = await page.evaluate(() =>
    window.effectiveDirection({
      fusion_available: true,
      canonical_provenance: 'canonical_forecast_missing',
      fusion_dominant_direction: 'up',
      dominant_dir: 'down',
    }),
  );
  expect(split).toBe(null);

  // Tradable canonical, non-authoritative fusion → fall back to dominant_dir.
  const tradableFallback = await page.evaluate(() =>
    window.effectiveDirection({
      fusion_available: true,
      canonical_provenance: 'bayesian_fusion',
      stack_runtime: { fusion_active: false },
      fusion_dominant_direction: 'up',
      dominant_dir: 'down',
    }),
  );
  expect(tradableFallback).toBe('down');
});
