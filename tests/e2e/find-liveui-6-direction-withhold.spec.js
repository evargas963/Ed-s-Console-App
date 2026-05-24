// @ts-check
/**
 * FIND-LIVEUI-6 — behavioral spec for Tier C direction-withhold helpers.
 *
 * Companion to tests/test_find_liveui_6_v1.py (static guard). Drives the
 * window-exposed helpers + the marker applier through the same DOM path
 * production uses (_updateLiveUiAe → _updateDirectionWithheldMarkers).
 *
 * Authority: LIVE-UI-1 inventory rows in governance/STACK_WIRING_INTEGRITY_MAP.md
 * "Live-UI direction transports (LIVE-UI-1, Phase 2)". OF strip is NOT
 * covered by these helpers (its own order_flow_stale clock — FIND-WIRE5-2..3).
 *
 * Operator note: CI runs this via `.github/workflows/pytest.yml` (`npm run test:all`).
 */
const { test, expect } = require('@playwright/test');

/** Reset live-integrity globals so synthesized payloads are not overridden by SSE ticks. */
async function resetWithholdGlobals(page) {
  await page.evaluate(() => {
    window._priceAheadOfBundle = false;
    window._liveUiIntegrity = {
      quoteAhead: false,
      pending: false,
      genStale: false,
      slowStaleVsFast: false,
    };
  });
}

async function gotoWithWithholdHelpers(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.bundleDirectionWithheld === 'function',
    null,
    { timeout: 30000 },
  );
  await resetWithholdGlobals(page);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ED_E2E__ = true;
  });
});

test('bundleDirectionWithheld returns withheld=false on clean integrity', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.bundleDirectionWithheld === 'function',
    null,
    { timeout: 30000 },
  );

  const clean = await page.evaluate(() =>
    window.bundleDirectionWithheld(
      { quoteAhead: false, genStale: false, pending: false, slowStaleVsFast: false },
      { analytics_pending_shell: false },
    ),
  );
  expect(clean.withheld).toBe(false);
  expect(clean.reason).toBeNull();
});

test('bundleDirectionWithheld emits each inventory reason on the corresponding condition', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.bundleDirectionWithheld === 'function',
    null,
    { timeout: 30000 },
  );

  const pendingShell = await page.evaluate(() =>
    window.bundleDirectionWithheld({}, { analytics_pending_shell: true }),
  );
  expect(pendingShell).toEqual({ withheld: true, reason: 'pending_shell' });

  // price_ahead_of_bundle drives off window._priceAheadOfBundle (set by
  // _refreshLiveUiIntegrityDerivations). Simulate by setting the window flag.
  const priceAhead = await page.evaluate(() => {
    window._priceAheadOfBundle = true;
    const r = window.bundleDirectionWithheld({}, {});
    window._priceAheadOfBundle = false;
    return r;
  });
  expect(priceAhead).toEqual({ withheld: true, reason: 'price_ahead_of_bundle' });

  const slowStale = await page.evaluate(() =>
    window.bundleDirectionWithheld({ slowStaleVsFast: true }, {}),
  );
  expect(slowStale).toEqual({ withheld: true, reason: 'slow_stale_vs_fast' });

  const quoteAhead = await page.evaluate(() =>
    window.bundleDirectionWithheld({ quoteAhead: true }, {}),
  );
  expect(quoteAhead).toEqual({ withheld: true, reason: 'quote_ahead' });

  const genStale = await page.evaluate(() =>
    window.bundleDirectionWithheld({ genStale: true }, {}),
  );
  expect(genStale).toEqual({ withheld: true, reason: 'gen_stale' });

  const pendingAnalytics = await page.evaluate(() =>
    window.bundleDirectionWithheld({ pending: true }, {}),
  );
  expect(pendingAnalytics).toEqual({ withheld: true, reason: 'pending_full_analytics' });
});

test('bundleDirectionWithheld precedence — pending_shell wins over every other condition', async ({ page }) => {
  // The inventory documents the precedence: pending_shell first because the
  // payload itself is a placeholder — no values are believable until first
  // non-shell bundle arrives. Lock the order.
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.bundleDirectionWithheld === 'function',
    null,
    { timeout: 30000 },
  );

  const r = await page.evaluate(() => {
    window._priceAheadOfBundle = true;
    const out = window.bundleDirectionWithheld(
      {
        quoteAhead: true,
        genStale: true,
        pending: true,
        slowStaleVsFast: true,
      },
      { analytics_pending_shell: true },
    );
    window._priceAheadOfBundle = false;
    return out;
  });
  expect(r.withheld).toBe(true);
  expect(r.reason).toBe('pending_shell');
});

test('horizonDirectionWithheld reads horizon_fusion_available map per Schwab-canonical slug', async ({ page }) => {
  await gotoWithWithholdHelpers(page);

  // MHMLB-NS1 hook: per-horizon availability map keyed on 1c/5c/15c/60c.
  const payload = {
    horizon_fusion_available: { '1c': false, '5c': true, '15c': true, '60c': true },
  };
  const clean = {};

  const one = await page.evaluate(
    ([integ, d]) => {
      window._priceAheadOfBundle = false;
      return window.horizonDirectionWithheld(integ, d, '1c');
    },
    [clean, payload],
  );
  expect(one).toEqual({ withheld: true, reason: 'horizon_fusion_unavailable' });

  const five = await page.evaluate(
    ([integ, d]) => {
      window._priceAheadOfBundle = false;
      return window.horizonDirectionWithheld(integ, d, '5c');
    },
    [clean, payload],
  );
  expect(five.withheld).toBe(false);
});

test('horizonDirectionWithheld falls back to bundle-level fusion_available when map absent', async ({ page }) => {
  await gotoWithWithholdHelpers(page);

  // No horizon_fusion_available map; fusion_available=false on the payload.
  const bundleOff = await page.evaluate(() => {
    window._priceAheadOfBundle = false;
    return window.horizonDirectionWithheld({}, { fusion_available: false }, '15c');
  });
  expect(bundleOff).toEqual({ withheld: true, reason: 'fusion_unavailable' });

  // No map, no fusion_available flag → not withheld (bundle-level handled elsewhere).
  const noSignal = await page.evaluate(() => {
    window._priceAheadOfBundle = false;
    return window.horizonDirectionWithheld({}, {}, '15c');
  });
  expect(noSignal.withheld).toBe(false);
});

test('horizonDirectionWithheld inherits bundle-level withhold', async ({ page }) => {
  await gotoWithWithholdHelpers(page);

  // Bundle quoteAhead → every horizon also withheld with that reason.
  const r = await page.evaluate(() => {
    window._priceAheadOfBundle = false;
    return window.horizonDirectionWithheld(
      { quoteAhead: true },
      { horizon_fusion_available: { '1c': true, '5c': true, '15c': true, '60c': true } },
      '60c',
    );
  });
  expect(r).toEqual({ withheld: true, reason: 'quote_ahead' });
});

test('_updateDirectionWithheldMarkers applies data-direction-withhold to Decision Command rail IDs', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window._refreshLiveUiIntegrityDerivations === 'function',
    null,
    { timeout: 30000 },
  );

  // Force bundle-level withhold via genStale path.
  const result = await page.evaluate(() => {
    window._lastData = {
      decision_generation_id: 99,
      _server_build_ts: Date.now() / 1000,
    };
    window._tierCCardsPaintedAtGen = 0;
    window._lastFullStateServerTs = Date.now() / 1000;
    window.lastFastTs = 0;
    window.lastRenderTimestamp = 0;
    if (typeof _updateLiveUiAe === 'function') _updateLiveUiAe();
    const ids = ['dr-trade-pill', 'dr-bias-pill', 'dr-confidence-pill', 'dr-action-chip'];
    return ids.map((id) => {
      const n = document.getElementById(id);
      return { id, present: !!n, attr: n ? n.getAttribute('data-direction-withhold') : null };
    });
  });
  // At least one direction-bearing node must exist and be marked withheld with a non-empty reason.
  const present = result.filter((r) => r.present);
  expect(present.length).toBeGreaterThan(0);
  const withMarker = present.filter((r) => r.attr != null && r.attr !== '');
  expect(withMarker.length).toBeGreaterThan(0);
});

test('_updateDirectionWithheldMarkers per-horizon: tf-signal-{slug} card marked when horizon unavailable', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window._refreshLiveUiIntegrityDerivations === 'function',
    null,
    { timeout: 30000 },
  );

  const result = await page.evaluate(() => {
    // Clean bundle but per-horizon withheld for 1c. Call the marker applier directly
    // so live SSE ticks cannot republish window._priceAheadOfBundle via integrity refresh.
    window._priceAheadOfBundle = false;
    window._lastData = {
      decision_generation_id: 1,
      horizon_fusion_available: { '1c': false, '5c': true, '15c': true, '60c': true },
    };
    window._liveUiIntegrity = {
      quoteAhead: false,
      pending: false,
      genStale: false,
      slowStaleVsFast: false,
    };
    if (typeof _updateDirectionWithheldMarkers === 'function') _updateDirectionWithheldMarkers();
    const card1 = document.getElementById('tf-signal-1c');
    const card5 = document.getElementById('tf-signal-5c');
    return {
      one_attr: card1 ? card1.getAttribute('data-direction-withhold') : null,
      one_present: !!card1,
      five_attr: card5 ? card5.getAttribute('data-direction-withhold') : null,
      five_present: !!card5,
    };
  });
  // 1c card must be marked horizon_fusion_unavailable; 5c card must NOT be marked.
  if (result.one_present) expect(result.one_attr).toBe('horizon_fusion_unavailable');
  if (result.five_present) expect(result.five_attr).toBeNull();
});

test('price DOM (#sb-spot / quote header) is NOT marked direction-withhold', async ({ page }) => {
  // The cross-tier rule applies to direction-bearing surfaces only. Price DOM
  // (Tier A) must stay live even when the bundle is stale.
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window._refreshLiveUiIntegrityDerivations === 'function',
    null,
    { timeout: 30000 },
  );

  const result = await page.evaluate(() => {
    window._lastData = { decision_generation_id: 5 };
    window._tierCCardsPaintedAtGen = 0;
    window._priceAheadOfBundle = true;
    if (typeof _updateLiveUiAe === 'function') _updateLiveUiAe();
    const priceIds = ['sb-spot', 'sb-bidask', 'ub-price', 'ub-bid-price', 'ub-ask-price'];
    return priceIds.map((id) => {
      const n = document.getElementById(id);
      return { id, attr: n ? n.getAttribute('data-direction-withhold') : 'missing' };
    });
  });
  for (const row of result) {
    if (row.attr !== 'missing') {
      expect(row.attr).toBeNull();
    }
  }
});

test('OF strip ids are NOT marked direction-withhold (independent order_flow_stale clock)', async ({ page }) => {
  // OF strip stays on its own clock (FIND-WIRE5-2..3). Even with bundle-stale
  // conditions firing, b-of-verdict and order-flow surfaces must not gain
  // data-direction-withhold from this code path.
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window._refreshLiveUiIntegrityDerivations === 'function',
    null,
    { timeout: 30000 },
  );

  const result = await page.evaluate(() => {
    window._lastData = { decision_generation_id: 99 };
    window._tierCCardsPaintedAtGen = 0;
    window._priceAheadOfBundle = true;
    if (typeof _updateLiveUiAe === 'function') _updateLiveUiAe();
    const ofIds = ['b-of-verdict'];
    return ofIds.map((id) => {
      const n = document.getElementById(id);
      return { id, present: !!n, attr: n ? n.getAttribute('data-direction-withhold') : null };
    });
  });
  for (const row of result) {
    if (row.present) expect(row.attr).toBeNull();
  }
});
