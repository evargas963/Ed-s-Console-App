// @ts-check
/**
 * PR214 — REAL BROWSER DOM proof for the options contract subscription binding.
 *
 * Loads the actual shipped static/options.html + static/js/options_subscription.js in
 * Chromium and drives the real click -> POST -> poll -> render path, with the backend
 * routes intercepted so every state transition is deterministic. No live Schwab
 * credentials are needed: these are UI state transitions, and the interception supplies
 * exactly the payload shapes the real API emits.
 *
 * Proves, in the DOM:
 *   1. valid POST ack -> subscription row says awaiting producer, NOT subscribed
 *   2. producer still A -> health unbound/unhealthy, never green
 *   3. producer L1=B and BOOK=B -> subscription row becomes subscribed, health may green
 *   4. partial producer (L1=B, BOOK=A) -> stays pending/unhealthy
 *   5. late A acknowledgement after B -> DOM remains on B
 *   6. POST failure -> no normal polling, explicit failure state
 */
const { test, expect } = require('@playwright/test');

const A = 'SPY   260920C00500000';
const B = 'SPY   260920C00510000';

const CHAIN = {
  ticker: 'SPY',
  expiry: '2026-09-20',
  spot: 505.0,
  status: 'ok',
  scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
  contracts: [
    { symbol: A, putCall: 'CALL', strikePrice: 500.0, bid: 6.1, ask: 6.3,
      delta: 0.61, gamma: 0.02, volatility: 18.2, totalVolume: 120, openInterest: 900 },
    { symbol: B, putCall: 'CALL', strikePrice: 510.0, bid: 2.1, ask: 2.3,
      delta: 0.39, gamma: 0.03, volatility: 19.4, totalVolume: 210, openInterest: 700 },
  ],
};

/** The real /api/order-flow/options-microstructure shape, with producer identity. */
function microstructure(contract, { l1, book, healthy = true, upstream = true } = {}) {
  const match = l1 === contract && book === contract;
  return {
    contract,
    status: 'ok',
    top_of_book: { bid: 2.1, ask: 2.3, bid_size: 10, ask_size: 12 },
    mid: 2.2, microprice: 2.21, spread_pts: 0.2,
    ages: { book_age_sec: 0.4 },
    depth: { 1: { bid_total: 10, ask_total: 12, imbalance: -0.09 } },
    streaming_plane: {
      streaming_connected: true,
      option_contract: contract,              // back-compat alias of REQUESTED
      server_requested_contract: contract,
      producer_l1_contract: l1,
      producer_book_contract: book,
      queried_contract: contract,
      contract_match: match,
      streaming_last_update_ts: Date.now() / 1000,
      streaming_staleness_ms: 120,
      streaming_healthy: healthy && match,
      daemon_upstream_health: upstream
        ? { LEVELONE_OPTIONS: { state: 'RUNNING', age_sec: 0.2 },
            OPTIONS_BOOK: { state: 'RUNNING', age_sec: 0.3 } }
        : {},
    },
  };
}

/** Serve the chain/expiries so the page renders clickable cells. */
async function stubChain(page) {
  await page.route('**/api/expiries*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json',
                body: JSON.stringify({ expiries: ['2026-09-20'] }) }));
  await page.route('**/api/chain*', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CHAIN) }));
}

async function clickContract(page, strikeText) {
  const row = page.locator('#chain-body tr', { hasText: strikeText });
  await row.locator('td.side-call').first().click();
}

const subRow = (page) => page.locator('#sel-subscription');
const healthDot = (page) => page.locator('#health-dot');
const healthSummary = (page) => page.locator('#health-summary');

test('1+2: valid ack shows awaiting-producer and never greens while producer is still A',
  async ({ page }) => {
    await stubChain(page);
    await page.route('**/api/streaming/active-option-contract', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ ok: true, contract: B }) }));
    // Producer has NOT switched yet: still holding A on both services.
    await page.route('**/api/order-flow/options-microstructure*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify(microstructure(B, { l1: A, book: A })) }));

    await page.goto('/options');
    await clickContract(page, '510.00');

    // 1. The ack is REQUEST ACCEPTANCE, not a subscription.
    await expect(subRow(page)).toContainText(/awaiting producer/i);
    await expect(subRow(page)).not.toContainText(/^subscribed$/i);

    // 2. Health must never render green while the producer is on another contract.
    //    Exact class match: 'healthy' is a SUBSTRING of 'unhealthy', so a regex here
    //    would pass on the wrong state (and did, until this was tightened).
    await expect(healthDot(page)).toHaveClass('unhealthy');
    await expect(healthSummary(page)).toContainText(/unbound/i);
  });

test('3: producer L1=B and BOOK=B promotes the row to subscribed and health may green',
  async ({ page }) => {
    await stubChain(page);
    await page.route('**/api/streaming/active-option-contract', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ ok: true, contract: B }) }));
    await page.route('**/api/order-flow/options-microstructure*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify(microstructure(B, { l1: B, book: B })) }));

    await page.goto('/options');
    await clickContract(page, '510.00');

    await expect(subRow(page)).toHaveText('subscribed');
    await expect(healthDot(page)).toHaveClass('healthy');   // exact: not 'unhealthy'
    await expect(healthSummary(page)).toContainText(/all healthy/i);
  });

test('4: partial producer state (L1=B, BOOK=A) stays pending and unhealthy',
  async ({ page }) => {
    await stubChain(page);
    await page.route('**/api/streaming/active-option-contract', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ ok: true, contract: B }) }));
    await page.route('**/api/order-flow/options-microstructure*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify(microstructure(B, { l1: B, book: A })) }));

    await page.goto('/options');
    await clickContract(page, '510.00');

    await expect(subRow(page)).toContainText(/awaiting producer/i);
    await expect(healthDot(page)).toHaveClass('unhealthy');
  });

test('5: a LATE acknowledgement for A after B was selected leaves the DOM on B',
  async ({ page }) => {
    await stubChain(page);
    // A's POST is delayed past B's; B's resolves immediately.
    await page.route('**/api/streaming/active-option-contract', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      if (body.contract === A) {
        await new Promise((res) => setTimeout(res, 1200));   // late
      }
      await route.fulfill({ status: 200, contentType: 'application/json',
                            body: JSON.stringify({ ok: true, contract: body.contract }) });
    });
    const polled = [];
    await page.route('**/api/order-flow/options-microstructure*', (route) => {
      const url = new URL(route.request().url());
      const c = url.searchParams.get('contract');
      polled.push(c);
      return route.fulfill({ status: 200, contentType: 'application/json',
                             body: JSON.stringify(microstructure(c, { l1: c, book: c })) });
    });

    await page.goto('/options');
    await clickContract(page, '500.00');   // A first (its POST will resolve LATE)
    await clickContract(page, '510.00');   // B second, resolves first

    await expect(page.locator('#sel-symbol')).toHaveText(B);
    await expect(subRow(page)).toHaveText('subscribed');
    // Wait past A's delayed acknowledgement and confirm it never took over.
    await page.waitForTimeout(2500);
    await expect(page.locator('#sel-symbol')).toHaveText(B);
    await expect(subRow(page)).toHaveText('subscribed');
    // Every microstructure poll must be for B, never A.
    expect(polled.length).toBeGreaterThan(0);
    expect(polled.every((c) => c === B)).toBeTruthy();
  });

test('6: a failed POST starts no polling and shows an explicit failure state',
  async ({ page }) => {
    await stubChain(page);
    await page.route('**/api/streaming/active-option-contract', (r) =>
      r.fulfill({ status: 500, contentType: 'application/json',
                  body: JSON.stringify({ ok: false, error: 'signal write failed' }) }));
    let polls = 0;
    await page.route('**/api/order-flow/options-microstructure*', (r) => {
      polls += 1;
      return r.fulfill({ status: 200, contentType: 'application/json',
                         body: JSON.stringify(microstructure(B, { l1: B, book: B })) });
    });

    await page.goto('/options');
    await clickContract(page, '510.00');

    await expect(subRow(page)).toContainText(/subscribe failed/i);
    await expect(healthDot(page)).toHaveClass('unhealthy');
    await page.waitForTimeout(2500);   // past two poll intervals
    expect(polls).toBe(0);
  });

test('6b: an ok:false acknowledgement is also refused, with no polling',
  async ({ page }) => {
    await stubChain(page);
    await page.route('**/api/streaming/active-option-contract', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ ok: false, contract: B }) }));
    let polls = 0;
    await page.route('**/api/order-flow/options-microstructure*', (r) => {
      polls += 1;
      return r.fulfill({ status: 200, contentType: 'application/json',
                         body: JSON.stringify(microstructure(B, { l1: B, book: B })) });
    });

    await page.goto('/options');
    await clickContract(page, '510.00');

    await expect(subRow(page)).toContainText(/ack_not_ok/i);
    await page.waitForTimeout(2500);
    expect(polls).toBe(0);
  });
