// @ts-check
/**
 * D — Options/Gamma "Flow" subview + EdStream contract-binding invariants (#10 preserved).
 * Proves fail-closed observation of ONE explicitly-selected option contract: only an accepted control
 * request begins microstructure polling; ACTIVE only when the canonical producer confirms the desired
 * contract on BOTH services; MOVED/PENDING/FAILED render honestly; no re-POST/oscillation; the server's
 * NATIVE/DERIVED/PROXY classifications are shown; native_aggressor_available=false => no signed flow.
 */
const { test, expect } = require('@playwright/test');

const DESIRED = 'SPY   260911C00100000';
const OTHER = 'SPY   260911P00100000';

function chain() {
  function ct(side, k, sym) { return { putCall: side, strikePrice: k, symbol: sym, openInterest: 10, totalVolume: 5, volatility: 12, delta: side === 'CALL' ? 0.5 : -0.5, gamma: 0.01, expirationDate: '2026-09-11' }; }
  return { ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok', scope: { kind: 'complete_single_expiry' },
    contracts: [ct('CALL', 100, DESIRED), ct('PUT', 100, OTHER)] };
}
function microFor(plane) {
  return { contract: DESIRED, status: 'ok', top_of_book: { bid: 1.20, ask: 1.25, bid_size: 40, ask_size: 55 },
    mid: 1.225, microprice: 1.23, spread_pts: 0.05, depth: { '1': { bid_total: 40, ask_total: 55, imbalance: -0.16 },
    '3': { bid_total: 120, ask_total: 140, imbalance: -0.08 }, '5': { bid_total: 200, ask_total: 210, imbalance: -0.02 } },
    top_book_pressure: -0.16, tape_pressure_30s: 0.2, tape_pressure_2m: 0.1, tape_pressure_5m: 0.05,
    cum_delta_proxy: -1200, cum_delta_slope: -0.3, native_aggressor_available: false,
    classification: { 'top_of_book.bid': 'NATIVE', mid: 'DERIVED', tape_pressure_30s: 'PROXY' },
    streaming_plane: plane };
}

function makeContext() {
  return { post: { status: 200, ok: true, echo: DESIRED }, plane: { contract_match: true, book_age_sec: 3, quote_age_sec: 2, streaming_healthy: true, streaming_staleness_ms: 300 }, posts: 0, microGets: 0 };
}

async function setup(page, ctx) {
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  await page.route('**/api/**', (route, request) => {
    const url = request.url();
    if (url.includes('/api/streaming/active-option-contract') && request.method() === 'POST') {
      ctx.posts++;
      let contract = ''; try { contract = JSON.parse(request.postData() || '{}').contract || ''; } catch (e) {}
      const p = ctx.post;
      return route.fulfill({ status: p.status, contentType: 'application/json',
        body: JSON.stringify({ ok: p.ok, contract: (p.echo != null ? p.echo : contract), command_generation: 1, superseded: p.status === 409 }) });
    }
    if (url.includes('/api/order-flow/options-microstructure')) { ctx.microGets++; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(microFor(ctx.plane)) }); }
    let body = { available: false };
    if (url.includes('/api/chain')) body = chain();
    else if (url.includes('/api/options/gamma-surface')) body = { ticker: 'SPY', available: true, spot: 100, source: 'terrain_live_cache', live: true, stale: false, expirations: [{ expiry: '2026-09-11', dte: 2 }], strikes: [100], cells: [{ strike: 100, gex: [1] }] };
    else if (url.includes('/api/terrain/strikes')) body = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 5, levels_stale: false, today: { all: [[100, 1, 1]] } };
    else if (url.includes('/api/terrain')) body = { spot: 100, gamma_flip: 99.5, levels_stale: false };
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11'] };
    else if (url.includes('/api/live/state')) body = { ticker: 'SPY', spot: 100, spot_disp: '100.00', session_label: 'RTH', analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function selectCallAndOpenFlow(page) {
  await page.goto('/console', { waitUntil: 'domcontentloaded' });
  await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
  await expect(page.locator('#chainBody table.chn')).toBeVisible();
  await page.locator('#chainBody tr[data-csym="' + DESIRED + '"] td.chn-call').first().click();
  await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
  await expect(page.locator('#flowBody')).toBeVisible();
}

test.describe('D — Gamma Flow subview (EdStream contract binding)', () => {
  test('no contract selected -> fail closed (Select a Call or Put contract), no subscription request', async ({ page }) => {
    const ctx = makeContext(); await setup(page, ctx);
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
    await expect(page.locator('#flowBody')).toContainText('Select a Call or Put contract');
    expect(ctx.posts).toBe(0); expect(ctx.microGets).toBe(0);
  });

  test('ACTIVE only when producer confirms desired on both services; classifications + no signed flow', async ({ page }) => {
    const ctx = makeContext(); await setup(page, ctx);   // plane.contract_match:true
    await selectCallAndOpenFlow(page);
    await expect(page.locator('#flowBody .fl-badge')).toHaveText('ACTIVE');
    await expect(page.locator('#flowBody .fl-sym')).toHaveText(DESIRED);
    await expect(page.locator('#flowBody')).toContainText('1.20');                 // native bid served
    await expect(page.locator('#flowBody .fl-tag.native').first()).toBeVisible();  // NATIVE/DERIVED/PROXY labels
    await expect(page.locator('#flowBody .fl-tag.derived').first()).toBeVisible();
    await expect(page.locator('#flowBody .fl-tag.proxy').first()).toBeVisible();
    await expect(page.locator('#flowBody .fl-foot')).toContainText('NOT PROVEN');  // no signed buys/sells
    await expect(page.locator('#flowBody .fl-foot')).toContainText('native_aggressor_available=false');
    expect(ctx.posts).toBe(1);
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: 'test-results/gamma-flow-1672x941.png', fullPage: false });
  });

  test('producer partial (L1 desired, book other) = NOT ACTIVE (PENDING, dimmed)', async ({ page }) => {
    const ctx = makeContext();
    ctx.plane = { contract_match: false, producer_l1_contract: DESIRED, producer_book_contract: OTHER, book_age_sec: 3 };
    await setup(page, ctx);
    await selectCallAndOpenFlow(page);
    await expect(page.locator('#flowBody .fl-badge')).toHaveText('PENDING');
    await expect(page.locator('#flowBody .fl-sec.fl-dim').first()).toBeVisible();  // data recedes when not active
  });

  test('slot taken by another contract = MOVED; desired shown, no re-POST', async ({ page }) => {
    const ctx = makeContext();
    ctx.plane = { contract_match: false, producer_l1_contract: OTHER, producer_book_contract: OTHER, book_age_sec: 3 };
    await setup(page, ctx);
    await selectCallAndOpenFlow(page);
    await expect(page.locator('#flowBody .fl-badge')).toHaveText('MOVED');
    await expect(page.locator('#flowBody .fl-sym')).toHaveText(DESIRED);           // still shows OUR desired, not the other
    const postsAfter = ctx.posts;
    await page.waitForTimeout(500);
    expect(ctx.posts).toBe(postsAfter);                                            // no automatic re-POST
  });

  test('failed control request (500) = FAILED, no microstructure polling', async ({ page }) => {
    const ctx = makeContext(); ctx.post = { status: 500, ok: false, echo: DESIRED };
    await setup(page, ctx);
    await selectCallAndOpenFlow(page);
    await expect(page.locator('#flowBody .fl-badge')).toHaveText('FAILED');
    expect(ctx.microGets).toBe(0);                                                 // never polled a non-accepted contract
  });

  test('ticker change clears local intent (no POST); Flow -> Gamma -> Flow makes no new request', async ({ page }) => {
    const ctx = makeContext(); await setup(page, ctx);
    await selectCallAndOpenFlow(page);
    await expect(page.locator('#flowBody .fl-badge')).toHaveText('ACTIVE');
    const posts1 = ctx.posts;
    // Flow -> Gamma -> Flow: no new subscription request
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
    expect(ctx.posts).toBe(posts1);
    // ticker change clears the desired locally, no POST
    await page.locator('#symSel').selectOption('QQQ');
    await expect(page.locator('#flowBody')).toContainText('Select a Call or Put contract');
    expect(await page.evaluate(() => window.EdStream.getDesired())).toBeNull();
    expect(ctx.posts).toBe(posts1);                                                // clearing never POSTs
  });
});
