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
 *  - PLAN pill card (tf-plan-*) textContent comes from the payload plan fields
 *    (rail dr-plan-* + dr-align-* blocks retired 2026-06-10 — duplicative with
 *    the PLAN pill and the per-horizon pills).
 *  - ALL pill withholds (UNAVAILABLE chip + WAIT reason detail) on split-brain
 *    payloads (closes the WIRE-4-CAND → cards path on the operator surface;
 *    the rail Why/gates + Readiness/trust + Stack-behind-the-call blocks were
 *    retired 2026-06-10 — duplicative with pills/header chips/signal chain).
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

test('PLAN pill card renders from payload', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderDecisionCommandRail === 'function'
      && typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );

  await page.evaluate((d) => {
    window.renderDecisionCommandRail(d);
    window.renderTimeframeSignalRow(d);
  }, payloadAlignedLong());

  // Rail dr-align-* block retired 2026-06-10 — per-horizon direction lives on
  // the pills (covered by the tf-signal test above).
  expect(await page.$('#dr-align-1m')).toBeNull();

  // PLAN pill card values come straight from payload (single-line folded).
  expect(await page.textContent('#tf-plan-entry')).toBe('441.25 zone');
  expect(await page.textContent('#tf-plan-stop')).toBe('440.50');
  expect(await page.textContent('#tf-plan-targets')).toBe('442.10 / 442.85');
  expect(await page.textContent('#tf-plan-invalidation')).toBe('below 440.30');
  // entry_state 'armed' + final_bias LONG → state line + green chrome.
  expect(await page.textContent('#tf-plan-state')).toBe('ARMED');
  expect(await page.getAttribute('#tf-signal-plan', 'class')).toContain('tf-state-up');
});

test('ALL pill withholds with WAIT reason on split-brain payload (WIRE-4-CAND → cards)', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );

  // Happy path: fusion authoritative + tradeable → ALL pill carries ML FUSION.
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), payloadAlignedLong());
  const chipHappy = await page.textContent('#tf-signal-consolidated .tf-source-chip');
  expect(chipHappy).toBe('ML FUSION');

  // Split-brain: server-side WIRE-4-CAND would have stamped stack_mode=INVALID
  // + fusion_active=false. The ALL pill must withhold (UNAVAILABLE chip) and
  // carry the operator-readable WAIT reason on its detail line — the rail
  // Why/gates block that used to show it was retired 2026-06-10.
  const splitBrain = payloadAlignedLong();
  splitBrain.canonical_provenance = 'canonical_forecast_missing';
  splitBrain.final_tradeable = false;
  splitBrain.final_bias = 'WAIT';
  splitBrain.wait_reason = 'fewer than 2 tradeable horizons agree — insufficient confluence';
  splitBrain.stack_runtime = {
    fusion_active: false,           // server would have set this via is_ms_dict_fusion_authoritative
    mc_participated: true,
    n_ml_layers_live: 3,
    stack_mode: 'INVALID',
    contributing_models: [],
  };
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), splitBrain);

  const chipInvalid = await page.textContent('#tf-signal-consolidated .tf-source-chip');
  expect(chipInvalid).toBe('UNAVAILABLE');
  const detail = await page.textContent('#tf-signal-consolidated .tf-source-detail');
  expect(detail).toBe('WAIT — fewer than 2 tradeable horizons agree — insufficient confluence');
  // Full reason also on hover (detail line truncates on the narrow pill).
  const detailTitle = await page.getAttribute('#tf-signal-consolidated .tf-source-detail', 'title');
  expect(detailTitle).toBe(detail);

  // Bugbot 2026-06-11: empirical consensus WITHOUT fusion authority must not
  // borrow the ML FUSION chip. multi_horizon LONG can form from
  // predictive_empirical_fallback horizons (tradeable without fusion in
  // multi_horizon_decision._forecast_horizon_live) while fusion_active=false —
  // the ALL chip must stay UNAVAILABLE on that payload.
  const empiricalConsensus = payloadAlignedLong();
  empiricalConsensus.decision_provenance = 'multi_horizon_consensus';
  empiricalConsensus.final_bias = 'LONG';
  empiricalConsensus.final_tradeable = false;
  empiricalConsensus.fusion_available = false;
  empiricalConsensus.canonical_provenance = 'fusion_unavailable';
  empiricalConsensus.stack_runtime = {
    ...empiricalConsensus.stack_runtime,
    fusion_active: false,
  };
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), empiricalConsensus);
  const chipEmpirical = await page.textContent('#tf-signal-consolidated .tf-source-chip');
  expect(chipEmpirical).toBe('UNAVAILABLE');

  // Counter-case: fusion authoritative + multi_horizon directional consensus but
  // entry-gated (final_tradeable=false) keeps the honest ML FUSION provenance chip.
  const fusionGated = payloadAlignedLong();
  fusionGated.decision_provenance = 'multi_horizon_consensus';
  fusionGated.final_tradeable = false;
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), fusionGated);
  const chipFusionGated = await page.textContent('#tf-signal-consolidated .tf-source-chip');
  expect(chipFusionGated).toBe('ML FUSION');

  // Operator 2026-06-11: fusion authoritative + policy WAIT (live market state —
  // all horizons weak, insufficient confluence). The stack is up and deliberately
  // holding, so the provenance chip must stay ML FUSION (not UNAVAILABLE, which
  // reads as broken pipeline) while the detail line carries the WAIT reason.
  const fusionWait = payloadAlignedLong();
  fusionWait.final_bias = 'WAIT';
  fusionWait.final_tradeable = false;
  fusionWait.wait_reason = 'fewer than 2 tradeable horizons agree — insufficient confluence';
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), fusionWait);
  const chipFusionWait = await page.textContent('#tf-signal-consolidated .tf-source-chip');
  expect(chipFusionWait).toBe('ML FUSION');
  const detailFusionWait = await page.textContent('#tf-signal-consolidated .tf-source-detail');
  expect(detailFusionWait).toBe('WAIT — fewer than 2 tradeable horizons agree — insufficient confluence');
});
