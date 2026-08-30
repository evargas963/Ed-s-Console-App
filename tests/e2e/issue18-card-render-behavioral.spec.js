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
    stack_directional_authorized: true,
    horizon_directional_authorized: { '1c': true, '5c': true, '15c': true, '60c': true },
    horizon_fusion_available: { '1c': true, '5c': true, '15c': true, '60c': true },
    canonical_provenance: 'bayesian_fusion',
    mc_available: true,
  };
}

/**
 * RC-395 / RC-345-F05 — payloadAlignedLong() plus the S2B-1 operator mirror.
 *
 * server.py stamps operator_card_actionable and its siblings on EVERY Tier C payload
 * (server.py:2158-2161), and since RC-345 the frontend treats that mirror as the FINAL
 * actionability authority: engineTradeableSetup returns false outright when it is absent,
 * because a display-trust gate may suppress a verdict but never substitute one. A fixture
 * without it therefore cannot obtain actionable paint — correctly, since production never
 * emits such a payload.
 *
 * Deliberately a SEPARATE builder rather than a change to payloadAlignedLong(): several
 * tests below derive DEGRADED payloads from that base (split-brain stack_mode=INVALID,
 * fusion-gated, fusion-WAIT), where the server would emit actionable=FALSE. Adding an
 * actionable mirror to the shared base would hand those cases a trust authority the server
 * would never have granted them, and would silently retarget which gate they exercise.
 */
function actionableAlignedLong() {
  return Object.assign(payloadAlignedLong(), {
    operator_card_actionable: true,
    operator_card_trust_state: 'TRUSTED',
    operator_stale_reason_codes: [],
    operator_actionability_reason: null,
  });
}

test('tf-signal cards reflect mhap_rows call direction + confidence band', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );

  await page.evaluate((d) => window.renderTimeframeSignalRow(d), actionableAlignedLong());

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
  const mixed = actionableAlignedLong();
  mixed.mhap_rows[0] = { horizon: '1c', call: 'SHORT', confidence: 0.78, row_state: 'secondary' };
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), mixed);
  const c1Short = await page.getAttribute('#tf-signal-1c', 'class');
  expect(c1Short).toContain('tf-state-down');
  expect(c1Short).toContain('tf-glow-3'); // 0.78 → high band

  // UNAVAILABLE row → tf-state-dim (no glow).
  const unav = actionableAlignedLong();
  unav.mhap_rows[3] = { horizon: '60c', call: 'UNAVAILABLE', confidence: 0, row_state: 'missing' };
  await page.evaluate((d) => window.renderTimeframeSignalRow(d), unav);
  const c60Unav = await page.getAttribute('#tf-signal-60c', 'class');
  expect(c60Unav).toContain('tf-state-dim');
  expect(c60Unav || '').not.toMatch(/tf-glow-[123]/);
});

// RC-395 (was: '1M LONG stays visually LONG when final_tradeable=false'). That title quoted
// the 2026-06-11 render contract sentence — "ALL final_tradeable=false may dim actionability
// but must not erase horizon direction" — which RC-133 REVOKED and deleted from the source on
// 2026-07-29 under the operator Decide mandate, after audits v10/v13/v26 graded Decide
// OUTSTANDING. With the admission registry empty, final_bias is WAIT every session, so a LONG
// pill under !tradeable was standing exposure advice from an engine with nothing admitted.
// The current contract (static/index.html, resolveHorizonCardVisualState -> visual.dirText)
// is: under !tradeable a horizon pill is dim, unglowed, em-dash, arrow neutral, tags null —
// while the per-horizon CONFIDENCE still renders, because confidence is not direction.
// Asserting LONG here would re-assert the fail-open defect RC-133 burned.
test('1M horizon withholds direction when final_tradeable=false (ALL WAIT)', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );

  const payload = {
    primary_horizon: '1c',
    mhap_rows: [
      { horizon: '1c', call: 'LONG', confidence: 0.41, row_state: 'primary' },
      { horizon: '5c', call: 'WAIT', confidence: 0.35, row_state: 'secondary' },
      { horizon: '15c', call: 'WAIT', confidence: 0.45, row_state: 'secondary' },
      { horizon: '60c', call: 'WAIT', confidence: 0.35, row_state: 'secondary' },
    ],
    final_bias: 'WAIT',
    final_tradeable: false,
    final_confidence: 0.41,
    entry_state: 'no_setup',
    wait_reason: 'fewer than 2 tradeable horizons agree — insufficient confluence',
    fusion_available: true,
    stack_directional_authorized: true,
    horizon_directional_authorized: { '1c': true, '5c': true, '15c': true, '60c': true },
    horizon_fusion_available: { '1c': true, '5c': true, '15c': true, '60c': true },
    canonical_provenance: 'bayesian_fusion',
    stack_runtime: { fusion_active: true, stack_mode: 'FULL' },
  };

  await page.evaluate((d) => {
    window.activeTicker = 'SPY';
    window.renderTimeframeSignalRow(d);
  }, payload);

  const c1 = await page.getAttribute('#tf-signal-1c', 'class');
  expect(c1).toContain('tf-state-dim');
  expect(c1).toContain('tf-signal-card--non-actionable');
  expect(c1 || '').not.toContain('tf-signal-card--trade-active');
  // No direction chrome survives !tradeable — not the word, not the arrow, not the glow.
  expect(c1 || '').not.toMatch(/tf-glow-[123]/);
  expect(c1 || '').not.toContain('tf-state-up');
  expect(await page.textContent('#tf-signal-1c .tf-dir')).toBe('—');
  expect(await page.textContent('#tf-signal-1c .tf-arrow')).toBe('→');
  expect(await page.getAttribute('#tf-signal-1c', 'data-tf-signal-dir')).toBe('neutral');
  expect(await page.getAttribute('#tf-signal-1c', 'data-horizon-actionability')).toBe('NON_ACTIONABLE');
  // Confidence is NOT direction — the horizon's supporting assessment still renders.
  expect(await page.textContent('#tf-signal-1c .tf-pct')).toBe('41%');

  const cAll = await page.getAttribute('#tf-signal-consolidated', 'class');
  expect(cAll).toContain('tf-state-dim');
  expect(await page.textContent('#tf-signal-consolidated .tf-dir')).toBe('NEUTRAL');

  expect(await page.textContent('#tf-plan-state')).toBe('NO SETUP');
  expect(await page.getAttribute('#tf-signal-plan', 'class')).toContain('tf-state-dim');
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
  }, actionableAlignedLong());

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

test('per-horizon source chips consume authorization and never infer ML authority', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.deriveSourceForHorizon === 'function',
    null,
    { timeout: 30000 },
  );

  const labels = await page.evaluate(() => {
    const payload = {
      fusion_available: true,
      canonical_provenance: 'bayesian_fusion',
      stack_directional_authorized: false,
      stack_runtime: { fusion_active: true, stack_mode: 'FULL' },
      mh_prob_source_by_horizon: {
        '1c': 'fusion_ml_primary',
        '5c': 'fusion_ml_primary',
      },
      horizon_directional_authorized: { '1c': true, '5c': false },
      horizon_fusion_available: { '1c': true, '5c': true },
    };
    return {
      one: window.deriveSourceForHorizon(payload, '1c'),
      five: window.deriveSourceForHorizon(payload, '5c'),
      consolidated: window.deriveSourceForHorizon(payload, 'consolidated'),
    };
  });
  expect(labels.one).toBe('ML FUSION');
  expect(labels.five).toBe('UNAVAILABLE');
  expect(labels.consolidated).toBe('UNAVAILABLE');
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

  const cAllInvalid = await page.getAttribute('#tf-signal-consolidated', 'class');
  expect(cAllInvalid).toContain('tf-signal-card--card-trust-withheld');
  expect(cAllInvalid || '').not.toContain('tf-signal-card--trade-active');
  const chipInvalid = await page.textContent('#tf-signal-consolidated .tf-source-chip');
  expect(chipInvalid).toBe('—');
  const detail = await page.textContent('#tf-signal-consolidated .tf-source-detail');
  expect(detail).toBe('—');

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
  expect(chipEmpirical).toBe('—');
  const cEmp = await page.getAttribute('#tf-signal-consolidated', 'class');
  expect(cEmp).toContain('tf-signal-card--card-trust-withheld');

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

function trustedExecutionPayload(callState, ticker = 'SPY', overrides = {}) {
  return {
    ticker,
    primary_horizon: '5c',
    mhap_rows: [
      { horizon: '1c', call: 'LONG', confidence: 0.62, row_state: 'secondary' },
      { horizon: '5c', call: 'LONG', confidence: 0.81, row_state: 'primary' },
      { horizon: '15c', call: 'LONG', confidence: 0.55, row_state: 'secondary' },
      { horizon: '60c', call: 'LONG', confidence: 0.45, row_state: 'secondary' },
    ],
    final_bias: 'WAIT',
    final_tradeable: false,
    entry_state: 'no_setup',
    call_state: callState,
    fusion_available: true,
    canonical_provenance: 'bayesian_fusion',
    stack_runtime: { fusion_active: true, stack_mode: 'FULL', mc_participated: true },
    ...overrides,
  };
}

async function readExecutionChip(page) {
  return page.evaluate(() => {
    const el = document.getElementById('tf-execution-state-chip');
    if (!el) return null;
    return {
      text: el.textContent,
      callState: el.getAttribute('data-call-state'),
      trusted: el.getAttribute('data-call-state-trusted'),
      className: el.className,
    };
  });
}

for (const ticker of ['SPY', 'QQQ', 'IWM']) {
  for (const execState of ['WAIT', 'WATCH', 'ACTIVE']) {
    test(`execution chip renders payload.call_state=${execState} for ${ticker}`, async ({ page }) => {
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(
        () => typeof window.renderTimeframeSignalRow === 'function',
        null,
        { timeout: 30000 },
      );
      const payload = trustedExecutionPayload(execState, ticker);
      await page.evaluate(({ d, sym }) => {
        if (typeof window.setActiveTicker === 'function') {
          window.setActiveTicker(sym, null);
        } else {
          window.activeTicker = sym;
        }
        window.renderTimeframeSignalRow(d);
      }, { d: payload, sym: ticker });
      const chip = await readExecutionChip(page);
      expect(chip).not.toBeNull();
      expect(chip.callState).toBe(execState);
      expect(chip.text).toBe(execState);
      expect(chip.trusted).toBe('true');
      expect(chip.className).toContain('tf-exec-chip--trusted');
      // RC-395: the payload is deliberately final_tradeable=false, so RC-133 withholds the
      // horizon direction word. That is the POINT of this test — the execution channel
      // (WAIT/WATCH/ACTIVE) is independent of the forecast-direction channel, so the chip
      // must read its state while the pill still refuses to name a direction. Asserting
      // 'LONG' here proved the opposite of the separation the test is named for.
      expect(await page.textContent('#tf-signal-1c .tf-dir')).toBe('—');
      expect(await page.getAttribute('#tf-signal-1c', 'data-tf-signal-dir')).toBe('neutral');
    });
  }
}

test('execution chip WITHHELD when analytics_stale with call_state ACTIVE', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );
  const payload = trustedExecutionPayload('ACTIVE', 'SPY', { analytics_stale: true });
  await page.evaluate((d) => {
    window.activeTicker = 'SPY';
    window.renderTimeframeSignalRow(d);
  }, payload);
  const chip = await readExecutionChip(page);
  expect(chip.text).toBe('WITHHELD');
  expect(chip.callState).toBe('ACTIVE');
  expect(chip.trusted).toBe('false');
  expect(chip.className).toContain('tf-exec-chip--withheld');
  const c1 = await page.getAttribute('#tf-signal-1c', 'class');
  expect(c1).toContain('tf-signal-card--card-trust-withheld');
});

test('execution chip WITHHELD when analytics_pending_shell with call_state ACTIVE', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );
  const payload = trustedExecutionPayload('ACTIVE', 'SPY', {
    analytics_pending_shell: true,
    mhap_rows: [],
  });
  await page.evaluate((d) => {
    window.activeTicker = 'SPY';
    window.renderTimeframeSignalRow(d);
  }, payload);
  const chip = await readExecutionChip(page);
  expect(chip.text).toBe('WITHHELD');
  expect(chip.trusted).toBe('false');
});

test('missing call_state shows unknown chip without inventing ACTIVE', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderTimeframeSignalRow === 'function',
    null,
    { timeout: 30000 },
  );
  const payload = trustedExecutionPayload(undefined, 'SPY');
  delete payload.call_state;
  await page.evaluate((d) => {
    window.activeTicker = 'SPY';
    window.renderTimeframeSignalRow(d);
  }, payload);
  const chip = await readExecutionChip(page);
  expect(chip.text).toBe('—');
  expect(chip.callState).toBe('');
  expect(chip.className).toContain('tf-exec-chip--unknown');
});
