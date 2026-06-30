// @ts-check
/**
 * Card fidelity — browser DOM proof for stale/pending/cache/partial/ticker-mismatch
 * suppression of actionable Horizon / ALL / PLAN paint.
 *
 * Two proof layers:
 *  1) Full production render path via window.render(d, source) — same entry as SSE/poll.
 *  2) Direct renderer calls (legacy narrow proof — subordinate to render path).
 *
 * Authority: analyticsCardTrustGate + render() + renderTimeframeSignalRow in static/index.html.
 */
const { test, expect } = require('@playwright/test');

const ANCHOR_TICKERS = ['SPY', 'QQQ', 'IWM'];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__ED_E2E__ = true;
  });
});

/** Full trusted tradeable payload — SPY/QQQ/IWM style. */
function fullTrustedPayload(ticker) {
  return {
    ticker,
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
    spot_disp: '441.30',
    final_tradeable: true,
    final_bias: 'LONG',
    final_confidence: 0.81,
    analytics_stale: false,
    analytics_pending_shell: false,
    analytics_partial_tier_c: false,
    analytics_refresh_in_progress: false,
    fusion_available: true,
    canonical_provenance: 'bayesian_fusion',
    mc_available: true,
    stack_runtime: {
      fusion_active: true,
      mc_participated: true,
      n_ml_layers_live: 3,
      stack_mode: 'FULL',
      contributing_models: ['xgb', 'lstm', 'transformer'],
    },
  };
}

/** Tier C payload shaped for production render(d, source). */
function tierCRenderPayload(ticker, overrides) {
  const base = fullTrustedPayload(ticker);
  return Object.assign(base, {
    _tier: 'C_analytics',
    decision_generation_id: 1,
    _server_build_ts: Math.floor(Date.now() / 1000),
    selected_exp: '2026-06-27',
    expiries: ['2026-06-27'],
  }, overrides || {});
}

async function gotoCardTrustSurface(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () =>
      typeof window.render === 'function'
      && typeof window.renderTimeframeSignalRow === 'function'
      && typeof window.analyticsCardTrustGate === 'function'
      && typeof window.renderDecisionCommandRail === 'function',
    null,
    { timeout: 30000 },
  );
}

async function resetRenderPipelineState(page) {
  await page.evaluate(() => {
    if (typeof window._resetTierCCardRenderDedup === 'function') {
      window._resetTierCCardRenderDedup();
    }
    window._lastRenderedDecisionGen = 0;
    window._lastData = null;
    if (window._eventSource) {
      try { window._eventSource.close(); } catch (e) { /* e2e isolate */ }
      window._eventSource = null;
    }
  });
}

async function setActiveTicker(page, ticker) {
  await page.evaluate((t) => {
    if (typeof setActiveTicker === 'function') {
      setActiveTicker(t, null);
    } else {
      // eslint-disable-next-line no-undef
      activeTicker = String(t).trim().toUpperCase();
    }
  }, ticker);
}

/** Production-like path: top-level render(d, source) used by SSE + REST poll. */
async function renderViaProductionPath(page, payload, source) {
  return page.evaluate(
    ({ d, src, bump }) => {
      d.decision_generation_id = bump;
      d._server_build_ts = Math.floor(Date.now() / 1000) + bump;
      const ok = window.render(d, src);
      return {
        ok,
        renderKind: (window._edRtDiag && window._edRtDiag.renderKind) || null,
      };
    },
    { d: payload, src: source || 'e2e_full_render', bump: payload.decision_generation_id || 1 },
  );
}

async function paintCardsDirect(page, payload) {
  await page.evaluate((d) => {
    window.renderDecisionCommandRail(d);
    window.renderTimeframeSignalRow(d);
  }, payload);
}

/** Read DOM card paint state for Horizon / ALL / PLAN surfaces. */
async function readCardPaintState(page) {
  return page.evaluate(() => {
    const cardIds = ['1c', '5c', '15c', '60c', 'consolidated', 'plan'];
    const cards = cardIds.map((slug) => {
      const el = document.getElementById('tf-signal-' + slug);
      if (!el) return { slug, missing: true };
      return {
        slug,
        className: el.className || '',
        withhold: el.getAttribute('data-card-trust-withhold'),
        tradeActive: (el.className || '').includes('tf-signal-card--trade-active'),
        cardTrustWithheld: (el.className || '').includes('tf-signal-card--card-trust-withheld'),
        glow: /tf-glow-[123]/.test(el.className || ''),
        dir: el.querySelector('.tf-dir')?.textContent || '',
      };
    });
    const planState = document.getElementById('tf-plan-state')?.textContent || '';
    const anyTradeActive = cards.some((c) => c.tradeActive);
    const anyGlow = cards.some((c) => c.glow);
    const anyWithholdAttr = cards.some((c) => c.withhold != null);
    const planActionable = planState === 'ARMED' || planState === 'CONFIRMED' || planState === 'FILLED';
    const lastRenderKind = (window._edRtDiag && window._edRtDiag.renderKind) || null;
    return { cards, planState, anyTradeActive, anyGlow, anyWithholdAttr, planActionable, lastRenderKind };
  });
}

async function assertSuppressedActionablePaint(page) {
  const st = await readCardPaintState(page);
  expect(st.anyTradeActive, 'must not paint tf-signal-card--trade-active').toBe(false);
  expect(st.planActionable, 'PLAN must not show ARMED/CONFIRMED/FILLED').toBe(false);
  expect(st.anyGlow, 'must not paint confidence glow bands on untrusted bundle').toBe(false);
  expect(st.anyWithholdAttr || st.cards.some((c) => c.cardTrustWithheld), 'must show card-trust withhold markers').toBe(true);
  const consolidated = st.cards.find((c) => c.slug === 'consolidated');
  expect(consolidated?.className || '').toContain('tf-signal-card--non-actionable');
  expect(consolidated?.className || '').not.toMatch(/tf-state-up|tf-state-down/);
}

async function assertTrustedActionablePaint(page) {
  const st = await readCardPaintState(page);
  expect(st.anyTradeActive, 'trusted tradeable payload must paint trade-active').toBe(true);
  expect(['ARMED', 'CONFIRMED'], 'PLAN must show actionable entry state').toContain(st.planState);
  const consolidated = st.cards.find((c) => c.slug === 'consolidated');
  expect(consolidated?.className || '').toContain('tf-signal-card--trade-active');
  expect(consolidated?.className || '').toContain('tf-state-up');
  expect(st.anyWithholdAttr, 'trusted paint must not carry card-trust withhold').toBe(false);
}

// ── Full production render() path (primary proof) ─────────────────────────────

for (const ticker of ANCHOR_TICKERS) {
  test(`[render/${ticker}] analytics_stale suppresses actionable card paint`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await resetRenderPipelineState(page);
    await setActiveTicker(page, ticker);
    let gen = 1;
    const trusted = tierCRenderPayload(ticker, { decision_generation_id: gen++ });
    const baseline = await renderViaProductionPath(page, trusted, 'e2e_baseline');
    expect(baseline.ok).toBe(true);
    const stale = tierCRenderPayload(ticker, {
      decision_generation_id: gen++,
      analytics_stale: true,
    });
    const staleRender = await renderViaProductionPath(page, stale, 'e2e_stale');
    expect(staleRender.ok).toBe(true);
    expect(staleRender.renderKind).toBe('full_analytical');
    await assertSuppressedActionablePaint(page);
  });

  test(`[render/${ticker}] analytics_pending_shell suppresses prior tradeable mhap chrome`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await resetRenderPipelineState(page);
    await setActiveTicker(page, ticker);
    let gen = 10;
    const trusted = tierCRenderPayload(ticker, { decision_generation_id: gen++ });
    expect(await renderViaProductionPath(page, trusted, 'e2e_baseline')).toMatchObject({ ok: true });
    const pending = tierCRenderPayload(ticker, {
      decision_generation_id: gen++,
      analytics_pending_shell: true,
      // Prior tradeable rows remain on payload (server merge / cache) — must not paint actionable.
    });
    const pendingRender = await renderViaProductionPath(page, pending, 'e2e_pending_shell');
    expect(pendingRender.ok).toBe(true);
    expect(pendingRender.renderKind).toBe('tier_c_pending_shell');
    await assertSuppressedActionablePaint(page);
  });

  test(`[render/${ticker}] client_ticker_cache restore suppresses stale cached paint`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await resetRenderPipelineState(page);
    await setActiveTicker(page, ticker);
    const cached = tierCRenderPayload(ticker, {
      decision_generation_id: 20,
      analytics_refresh_in_progress: true,
      analytics_stale: true,
      _update_source: 'client_ticker_cache',
    });
    expect(await renderViaProductionPath(page, cached, 'e2e_cache_restore')).toMatchObject({ ok: true });
    await assertSuppressedActionablePaint(page);
  });

  test(`[render/${ticker}] partial mhap withholds ALL/PLAN despite final_tradeable`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await resetRenderPipelineState(page);
    await setActiveTicker(page, ticker);
    const partial = tierCRenderPayload(ticker, {
      decision_generation_id: 30,
      mhap_rows: fullTrustedPayload(ticker).mhap_rows.slice(0, 2),
    });
    expect(await renderViaProductionPath(page, partial, 'e2e_partial_mhap')).toMatchObject({ ok: true });
    await assertSuppressedActionablePaint(page);
  });

  test(`[render/${ticker}] wrong ticker payload rejected — no card bypass`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await resetRenderPipelineState(page);
    await setActiveTicker(page, ticker);
    const other = ANCHOR_TICKERS.find((t) => t !== ticker) || 'QQQ';
    let gen = 40;
    const trusted = tierCRenderPayload(ticker, { decision_generation_id: gen++ });
    expect(await renderViaProductionPath(page, trusted, 'e2e_baseline')).toMatchObject({ ok: true });
    await assertTrustedActionablePaint(page);
    const wrong = tierCRenderPayload(other, { decision_generation_id: gen++ });
    const accepted = await renderViaProductionPath(page, wrong, 'e2e_wrong_ticker');
    expect(accepted.ok).toBe(false);
    await assertTrustedActionablePaint(page);
  });

  test(`[render/${ticker}] trusted payload regression retains actionable card parity`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await resetRenderPipelineState(page);
    await setActiveTicker(page, ticker);
    const trusted = tierCRenderPayload(ticker, { decision_generation_id: 50 });
    expect(await renderViaProductionPath(page, trusted, 'e2e_trusted')).toMatchObject({ ok: true });
    await assertTrustedActionablePaint(page);
    const c5 = await page.getAttribute('#tf-signal-5c', 'class');
    expect(c5).toContain('tf-state-up');
    expect(c5).toContain('tf-glow-3');
  });
}

test('[render] SYNCING non-cache refresh keeps trusted actionable paint (last-known-good)', async ({ page }) => {
  await gotoCardTrustSurface(page);
  await resetRenderPipelineState(page);
  await setActiveTicker(page, 'SPY');
  const syncing = tierCRenderPayload('SPY', {
    decision_generation_id: 60,
    analytics_refresh_in_progress: true,
    analytics_stale: false,
    _update_source: 'sse_tier_c',
  });
  expect(await renderViaProductionPath(page, syncing, 'e2e_syncing')).toMatchObject({ ok: true });
  await assertTrustedActionablePaint(page);
  const gate = await page.evaluate((d) => window.analyticsCardTrustGate(d, { checkTicker: false }), syncing);
  expect(gate.trusted).toBe(true);
  const fresh = await page.textContent('#analytics-freshness');
  expect(fresh || '').toMatch(/syncing|refreshing/i);
});

test('[render] plane diag on _lastPlaneDiag does not alter card paint when ms_dict is trusted', async ({ page }) => {
  await gotoCardTrustSurface(page);
  await resetRenderPipelineState(page);
  await setActiveTicker(page, 'SPY');
  await page.evaluate(() => {
    window._lastPlaneDiag = {
      plane_quote_authority: 'rest_fallback_explicit',
      streaming_fallback_explicit: true,
      ticker: 'SPY',
    };
    window._planeDiagMeta = { gen: typeof requestGeneration !== 'undefined' ? requestGeneration : 1, ticker: 'SPY', at: Date.now() };
  });
  const trusted = tierCRenderPayload('SPY', { decision_generation_id: 70 });
  expect(await renderViaProductionPath(page, trusted, 'e2e_plane_diag_separation')).toMatchObject({ ok: true });
  await assertTrustedActionablePaint(page);
});

test('T0 __edMoneyPathLatency diagnostics object is initialized on load', async ({ page }) => {
  await gotoCardTrustSurface(page);
  const diag = await page.evaluate(() => {
    const o = window.__edMoneyPathLatency;
    return o && typeof o === 'object'
      ? { initialized: o.initialized, hasRenderMs: 'last_render_ms' in o, hasOverlap: 'rest_poll_overlap_count' in o }
      : null;
  });
  expect(diag).toEqual({ initialized: true, hasRenderMs: true, hasOverlap: true });
});

test('T2 rAF latest-wins scheduler exposes observational diagnostics', async ({ page }) => {
  await gotoCardTrustSurface(page);
  const diag = await page.evaluate(() => {
    const o = window.__edMoneyPathLatency;
    return o && typeof o === 'object'
      ? {
          hasSchedulerFn: typeof window.scheduleMoneyPathRender === 'function',
          rafEnabled: 'raf_scheduler_enabled' in o,
          rafSchedule: 'raf_schedule_count' in o,
          rafCoalesce: 'raf_coalesce_count' in o,
          rafFlush: 'raf_flush_count' in o,
          rafSupersede: 'raf_latest_wins_supersede_count' in o,
          rafPending: 'raf_pending' in o,
        }
      : null;
  });
  expect(diag).toMatchObject({
    hasSchedulerFn: true,
    rafEnabled: true,
    rafSchedule: true,
    rafCoalesce: true,
    rafFlush: true,
    rafSupersede: true,
    rafPending: true,
  });
});

test('T3 monotonic gate accepts newer and rejects older out-of-order payloads', async ({ page }) => {
  await gotoCardTrustSurface(page);
  const result = await page.evaluate(() => {
    if (typeof window._edMplMonotonicGateReset === 'function') window._edMplMonotonicGateReset();
    const base = {
      ticker: typeof activeTicker !== 'undefined' ? activeTicker : 'SPY',
      decision_generation_id: 100,
      _server_build_ts: 1000,
      _tier: 'C_analytics',
    };
    const acceptNewer = window.acceptMoneyPathPayload(Object.assign({}, base), 'e2e_t3');
    const rejectOlder = window.acceptMoneyPathPayload(
      Object.assign({}, base, { decision_generation_id: 99, _server_build_ts: 999 }),
      'e2e_t3'
    );
    const rejectDuplicate = window.acceptMoneyPathPayload(Object.assign({}, base), 'e2e_t3');
    const mpl = window.__edMoneyPathLatency;
    return {
      acceptNewer,
      rejectOlder,
      rejectDuplicate,
      monotonic_accept_count: mpl.monotonic_accept_count,
      monotonic_reject_count: mpl.monotonic_reject_count,
      monotonic_last_reject_reason: mpl.monotonic_last_reject_reason,
      out_of_order_reject_count: mpl.out_of_order_reject_count,
      hasMonotonicFn: typeof window.acceptMoneyPathPayload === 'function',
    };
  });
  expect(result.hasMonotonicFn).toBe(true);
  expect(result.acceptNewer).toBe(true);
  expect(result.rejectOlder).toBe(false);
  expect(result.rejectDuplicate).toBe(false);
  expect(result.monotonic_accept_count).toBeGreaterThanOrEqual(1);
  expect(result.monotonic_reject_count).toBeGreaterThanOrEqual(2);
  expect(result.out_of_order_reject_count).toBeGreaterThanOrEqual(2);
});

// ── Direct renderer path (subordinate — same card-trust gate) ─────────────────

for (const ticker of ANCHOR_TICKERS) {
  test(`[direct/${ticker}] analytics_stale suppresses actionable card paint`, async ({ page }) => {
    await gotoCardTrustSurface(page);
    await setActiveTicker(page, ticker);
    const payload = fullTrustedPayload(ticker);
    payload.analytics_stale = true;
    await paintCardsDirect(page, payload);
    await assertSuppressedActionablePaint(page);
  });
}
