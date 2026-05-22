// @ts-check
/**
 * STACK-WIRE-3-UI Phase 3 closure — behavioral verification of the three dynamic items:
 *   - spread_semantic consumer dispatch (fraction / dollar / heuristic) via computeSpreadGate
 *   - signals_engine_failed badge (dr-signals-engine-fail-chip) via _updateLiveUiAe
 *   - iv_rank / iv_percentile withhold semantic (em-dash, not zero) via renderContextLayer
 *
 * Cursor's audit of the static-only guards caught a real fraction-path bug — fraction +
 * valid spot was driving _spdIsPxWidth=true and the gate to spread < 0.05/spot instead of
 * spread < 0.05 directly. This spec exercises that case under example values, plus the
 * dollar and heuristic paths, plus the signals chip toggle and iv withhold.
 */
const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ED_E2E__ = true;
  });
});

test('computeSpreadGate dispatches on producer-stamped spread_semantic', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.computeSpreadGate === 'function',
    null,
    { timeout: 30000 },
  );

  // Fraction path: spread=0.02 (2%) at spot=100. Gate compares against 0.05 (5%) DIRECTLY —
  // no /spot conversion. 0.02 < 0.05 → OK. (Pre-fix bug: 0.02 < 0.0005 → wrongly BAD.)
  const fractionOk = await page.evaluate(() =>
    window.computeSpreadGate({ spread: 0.02, spread_semantic: 'fraction', spot: 100 }),
  );
  expect(fractionOk.spdIsPxWidth).toBe(false);
  expect(fractionOk.gateOk).toBe(true);
  expect(fractionOk.label).toBe('SPD 2.0%');

  // Fraction path, just over the cap: spread=0.06 → 6% > 5% → BAD.
  const fractionBad = await page.evaluate(() =>
    window.computeSpreadGate({ spread: 0.06, spread_semantic: 'fraction', spot: 100 }),
  );
  expect(fractionBad.spdIsPxWidth).toBe(false);
  expect(fractionBad.gateOk).toBe(false);

  // Dollar path: spread=0.04 (dollars). Legacy gate compares dollar width < 0.05.
  const dollarOk = await page.evaluate(() =>
    window.computeSpreadGate({ spread: 0.04, spread_semantic: 'dollar', spot: 441.25 }),
  );
  expect(dollarOk.spdIsPxWidth).toBe(false);
  expect(dollarOk.gateOk).toBe(true);

  // Heuristic path (no semantic tag): slow-stale vs fast + fast-lane spread + valid spot
  // → px-width mode, gate uses fastLaneSpread < 0.05/spot.
  const heuristicOk = await page.evaluate(() =>
    window.computeSpreadGate({
      spread: null,
      spot: 441.25,
      _slowStaleVsFast: true,
      _fastLaneSpread: 0.0001,
      _fastLaneSpot: 441.25,
    }),
  );
  expect(heuristicOk.spdIsPxWidth).toBe(true);
  expect(heuristicOk.gateOk).toBe(true);
  expect(heuristicOk.label.startsWith('Px SPD ')).toBe(true);

  // Withheld: spread null with no semantic.
  const withheld = await page.evaluate(() =>
    window.computeSpreadGate({ spread: null, spot: 441.25 }),
  );
  expect(withheld.spdForGate).toBe(null);
  expect(withheld.gateOk).toBe(false);
  expect(withheld.label).toBe('SPD —');
});

test('dr-signals-engine-fail-chip surfaces signals_engine_failed=true distinctly from stack INVALID', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window._updateLiveUiAe === 'function'
      && typeof window._updateSignalsEngineFailChip === 'function',
    null,
    { timeout: 30000 },
  );

  // Default: chip hidden.
  const chip = page.locator('#dr-signals-engine-fail-chip');
  await expect(chip).toBeAttached();

  // Drive the chip from _liveUiIntegrity directly (renderer reads integrity).
  await page.evaluate(() => {
    window._lastData = { stack_runtime: { signals_engine_failed: true, stack_mode: 'FULL' } };
    window._updateLiveUiAe();
  });
  await expect(chip).toBeVisible();
  expect(await chip.textContent()).toBe('SIGNALS ENGINE FAILED');
  const cls = await chip.getAttribute('class');
  expect(cls || '').toContain('bad');

  // signals_engine_failed=false + stack_mode=INVALID: signals chip hidden, stack chip handles INVALID.
  await page.evaluate(() => {
    window._lastData = { stack_runtime: { signals_engine_failed: false, stack_mode: 'INVALID' } };
    window._updateLiveUiAe();
  });
  await expect(chip).toBeHidden();
});

test('renderContextLayer binds iv_rank / iv_percentile with em-dash withhold (not zero)', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof window.renderContextLayer === 'function',
    null,
    { timeout: 30000 },
  );

  // Withheld (null) → em-dash. Producer convention: None means insufficient history.
  await page.evaluate(() => {
    window.renderContextLayer({ iv_rank: null, iv_percentile: null });
  });
  expect(await page.textContent('#ctx-iv-rank')).toBe('—');
  expect(await page.textContent('#ctx-iv-percentile')).toBe('—');

  // Mixed: one valid, one withheld.
  await page.evaluate(() => {
    window.renderContextLayer({ iv_rank: null, iv_percentile: 50 });
  });
  expect(await page.textContent('#ctx-iv-rank')).toBe('—');
  expect(await page.textContent('#ctx-iv-percentile')).toBe('50');

  // Zero is a REAL value (lowest-on-record), not withheld — must render '0', not '—'.
  await page.evaluate(() => {
    window.renderContextLayer({ iv_rank: 0, iv_percentile: 0 });
  });
  expect(await page.textContent('#ctx-iv-rank')).toBe('0');
  expect(await page.textContent('#ctx-iv-percentile')).toBe('0');

  // High band.
  await page.evaluate(() => {
    window.renderContextLayer({ iv_rank: 85, iv_percentile: 92 });
  });
  expect(await page.textContent('#ctx-iv-rank')).toBe('85');
  expect(await page.textContent('#ctx-iv-percentile')).toBe('92');
});
