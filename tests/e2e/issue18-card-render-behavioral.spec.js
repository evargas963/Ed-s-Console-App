// @ts-check
/**
 * Issue 18 — behavioral DOM verification of the horizon card + Decision Rail
 * render contract.
 *
 * Replaces the static-HTML substring-only checks in tests/test_issue18_ui_contract.py
 * with real-browser DOM assertions: inject a payload, call the renderers, read back
 * actual classes/textContent. Closes the “Issue18 tests are static-HTML weak” gap
 * Cursor's db3f017 re-audit reiterated.
 *
 * Coverage:
 *  - tf-signal-<slug> card class reflects horizon call direction (LONG→tf-state-up,
 *    SHORT→tf-state-down, UNAVAILABLE→tf-state-dim) AND confidence band (tf-glow-1/2/3).
 *  - dr-align-<bar> slot textContent is "<CALL> · <conf>" from mhap_rows.
 *  - dr-plan-entry textContent comes from d.entry_display_text.
 *  - liveReady chip is NOT_LIVE_READY when stack_runtime.stack_mode === "INVALID"
 *    (closes the WIRE-4-CAND → cards path on the operator surface).
 */
const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ED_E2E__ = true;
  });
});

function payloadAlignedLong() {
  return {
    primary_horizon: '5c',
    mhap_rows: [
      { horizon: '1c', call: 'LONG', confidence: 0.62, row_state: 'secondary' },
      { horizon: '5c', call: 'LONG', confidence: 0.81, row_state: 'primary' },
      { horizon: '15c', call: 'LONG', confidence: 0.55, row_state: 'secondary' },
      { horizon: '60c', call: 'LONG', confidence: 0.45, row_state: 'secondary' },
    ],
    timeframe_cards: [],
    entry_display_text: '441.25 zone',
    stop_display_text: '440.50',
    targets_display: '442.10 / 442.85',
    invalidation: 'below 440.30',
    validation_passed: true,
    alignment_state_display: 'fully aligned',
    call_readiness: { call_state: 'ARMED' },
    entry_state: 'armed',
    spot: 441.30,
    final_tradeable: true,        // → tradeable = true (needed for liveReady)
    final_bias: 'LONG',           // → bias LONG/SHORT (needed for tradeable)
    stack_runtime: {
      fusion_active: true,
      mc_participated: true,
      n_ml_layers_live: 3,
      stack_mode: 'FULL',
      contributing_models: ['xgb', 'lstm', 'transformer'],
    },
    fusion_available: true,
    canonical_provenance: 'bayesian_fusion',
    mc_available: true,
  };
}

test('tf-signal cards reflect mhap_rows call direction + confidence band', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );

  await page.evaluate((d) => window.renderTimeframeSignalRow(d), payloadAlignedLong());

  // 1c: LONG @ 0.62 → tf-state-up + tf-glow-2 (61 <= 62 < 76).
  const c1 = await page.getAttribute('#tf-signal-1c', 'class');
  expect(c1).toContain('tf-state-up');
  expect(c1).toContain('tf-glow-2');

  // 5c: LONG @ 0.81 → tf-state-up + tf-glow-3 (>=76).
  const c5 = await page.getAttribute('#tf-signal-5c', 'class');
  expect(c5).toContain('tf-state-up');
  expect(c5).toContain('tf-glow-3');

  // 15c: LONG @ 0.55 → tf-state-up + tf-glow-1 (<61).
  const c15 = await page.getAttribute('#tf-signal-15c', 'class');
  expect(c15).toContain('tf-state-up');
  expect(c15).toContain('tf-glow-1');

  // Mixed-direction payload: 1c SHORT, others LONG → 1c card flips to tf-state-down.
  const mixed = payloadAlignedLong();
  mixed.mhap_rows[0] = { horizon: '1c', call: 'SHORT', confidence: 0.78, row_state: 'secondary' };
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), mixed);
  const c1Short = await page.getAttribute('#tf-signal-1c', 'class');
  expect(c1Short).toContain('tf-state-down');
  expect(c1Short).toContain('tf-glow-3'); // 0.78 → high band

  // UNAVAILABLE row → tf-state-dim (no glow).
  const unav = payloadAlignedLong();
  unav.mhap_rows[3] = { horizon: '60c', call: 'UNAVAILABLE', confidence: 0, row_state: 'missing' };
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), unav);
  const c60Unav = await page.getAttribute('#tf-signal-60c', 'class');
  expect(c60Unav).toContain('tf-state-dim');
  expect(c60Unav || '').not.toMatch(/tf-glow-[123]/);
});

test('Decision Rail dr-align-* + dr-plan-* render from payload', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderDecisionCommandRail === 'function',
    null,
    { timeout: 30000 },
  );

  await page.evaluate((d) => window.renderDecisionCommandRail(d), payloadAlignedLong());

  // Each dr-align-<bar> slot reads stanceFromRow → "<CALL> · <conf>" string.
  expect(await page.textContent('#dr-align-1m')).toBe('LONG · 0.62');
  expect(await page.textContent('#dr-align-5m')).toBe('LONG · 0.81');
  expect(await page.textContent('#dr-align-15m')).toBe('LONG · 0.55');
  expect(await page.textContent('#dr-align-60m')).toBe('LONG · 0.45');

  // Trade plan slots come straight from payload.
  expect(await page.textContent('#dr-plan-entry')).toBe('441.25 zone');
  expect(await page.textContent('#dr-plan-stop')).toBe('440.50');
  expect(await page.textContent('#dr-plan-targets')).toBe('442.10 / 442.85');
  expect(await page.textContent('#dr-plan-invalidation')).toBe('below 440.30');
});

test('liveReady chip flips to NOT_LIVE_READY when stack_mode=INVALID (WIRE-4-CAND → cards)', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderDecisionCommandRail === 'function',
    null,
    { timeout: 30000 },
  );

  // Happy path: liveReady=true, ACTIONABLE NOW.
  const happy = payloadAlignedLong();
  // primary_horizon='5c' + 5c row_state='primary' → rankOk=true; final_tradeable=true +
  // final_bias='LONG' → tradeable=true; validation_passed=true → valOk=true; stack_mode=FULL.
  await page.evaluate((d) => window.renderDecisionCommandRail(d), happy);

  const lrHappy = await page.textContent('#dr-live-ready-chip');
  expect(lrHappy).toBe('LIVE_READY');
  const blockHappy = await page.textContent('#dr-blocking-reason');
  expect(blockHappy).toBe('—');

  // Split-brain: server-side WIRE-4-CAND would have stamped stack_mode=INVALID.
  // Cards path must surface NOT_LIVE_READY + "stack INVALID" blocking reason.
  const splitBrain = payloadAlignedLong();
  splitBrain.canonical_provenance = 'canonical_forecast_missing';
  splitBrain.stack_runtime = {
    fusion_active: false,           // server would have set this via is_ms_dict_fusion_authoritative
    mc_participated: true,
    n_ml_layers_live: 3,
    stack_mode: 'INVALID',
    contributing_models: [],
  };
  await page.evaluate((d) => window.renderDecisionCommandRail(d), splitBrain);

  const lrInvalid = await page.textContent('#dr-live-ready-chip');
  expect(lrInvalid).toBe('NOT_LIVE_READY');
  const blockInvalid = await page.textContent('#dr-blocking-reason');
  expect(blockInvalid).toBe('stack INVALID (fusion/MC prerequisites)');
  const action = await page.textContent('#dr-action-chip');
  expect(action).toBe('CONFIRMATION NEEDED');
});
