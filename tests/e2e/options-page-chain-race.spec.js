// @ts-check
/**
 * Independent-review finding (2026-09-13), REPRODUCED: the retained /options page's
 * loadChain() (static/options.html) was fixed in an earlier round for a stale-TICKER race
 * (a response for an abandoned ticker could still paint) but never gained the same guard for
 * a stale-EXPIRY race -- only tkEl.value was re-checked before painting, never expSelect.value.
 * A fast expiry-dropdown switch (A -> B) whose in-flight A-response resolves AFTER B's own
 * request could still pass the ticker check and paint expiry-A's chain under the
 * now-selected expiry-B label. Fixed by capturing expSelect.value at issue time too and
 * discarding the response if either identity has since moved on.
 *
 * REAL BROWSER DOM proof: loads the actual shipped static/options.html in Chromium and drives
 * the real fetch race with backend routes intercepted so the ordering is deterministic.
 */
const { test, expect } = require('@playwright/test');

const EXP_A = '2026-09-19';
const EXP_B = '2026-09-26';

function chainFor(expiry, spot) {
  return {
    ticker: 'SPY', expiry: expiry, spot: spot, status: 'ok',
    scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
    contracts: [
      { symbol: 'SPY   FIXTURE_' + expiry + 'C', putCall: 'CALL', strikePrice: spot,
        bid: 1, ask: 1.1, delta: 0.5, gamma: 0.01, volatility: 15, totalVolume: 10, openInterest: 20 },
    ],
  };
}

test('a delayed old-expiry chain response cannot overwrite the newly-selected expiry (state-authority review)',
  async ({ page }) => {
    await page.route('**/api/expiries*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ expiries: [EXP_A, EXP_B] }) }));
    await page.route('**/api/spot*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ ticker: 'SPY', spot: 650.25,
                                         last_price_generation: 7 }) }));

    const chainRequests = [];
    await page.route('**/api/chain*', async (route) => {
      const url = new URL(route.request().url());
      const exp = url.searchParams.get('expiry');
      chainRequests.push(exp);
      if (exp === EXP_A) {
        // A resolves LATE -- after B's own request, which is issued and resolves right after.
        await new Promise((res) => setTimeout(res, 900));
        return route.fulfill({ status: 200, contentType: 'application/json',
                               body: JSON.stringify(chainFor(EXP_A, 111)) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
                             body: JSON.stringify(chainFor(EXP_B, 222)) });
    });

    await page.goto('/options');
    // Initial load defaults expSelect to the first listed expiry (EXP_A) and fires loadChain()
    // for it -- that fetch is the one that will resolve late.
    await expect(page.locator('#exp-select')).toHaveValue(EXP_A);

    // Switch to EXP_B before A's delayed response has arrived. This fires a second,
    // independent loadChain() for B, which resolves immediately.
    await page.locator('#exp-select').selectOption(EXP_B);
    await expect(page.locator('#m-expiry')).toHaveText(EXP_B);
    await expect(page.locator('#m-spot')).toHaveText('650.25');
    await expect(page.locator('#chain-body td.strike')).toHaveText('222.00');

    // Wait past A's deliberately delayed response.
    await page.waitForTimeout(1300);

    // The page must still show B -- a non-retrying snapshot, not a retrying assertion that
    // could pass merely because a LATER correct render eventually overwrites the wrong one.
    const expiryText = await page.locator('#m-expiry').textContent();
    const spotText = await page.locator('#m-spot').textContent();
    expect(expiryText).toBe(EXP_B);
    expect(spotText).toBe('650.25');
    await expect(page.locator('#chain-body td.strike')).toHaveText('222.00');

    expect(chainRequests).toContain(EXP_A);
    expect(chainRequests).toContain(EXP_B);
  });

// A fourth independent review (2026-09-13), REPRODUCED: the guard above proves the CURRENT
// ticker/expiry selection matches, but two different requests for the SAME identity
// (A -> B -> A: the first A request, and the third request issued after returning to A) are
// indistinguishable to an equality check alone -- whichever resolves LAST wins, not whichever
// was issued last. Fixed with an explicit monotonic request sequence (chainReqSeq in
// options.html) so only the most-recently-ISSUED request for any identity may ever paint.
test('A -> B -> A: a held first-A response cannot overwrite the fresh second-A response (state-authority review)',
  async ({ page }) => {
    await page.route('**/api/expiries*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ expiries: [EXP_A, EXP_B] }) }));
    await page.route('**/api/spot*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json',
                  body: JSON.stringify({ ticker: 'SPY', spot: 650.25,
                                         last_price_generation: 7 }) }));

    let aCallCount = 0;
    const chainRequests = [];
    await page.route('**/api/chain*', async (route) => {
      const url = new URL(route.request().url());
      const exp = url.searchParams.get('expiry');
      chainRequests.push(exp);
      if (exp === EXP_A) {
        aCallCount += 1;
        if (aCallCount === 1) {
          // The FIRST A request is held -- it resolves LATE, after the return-to-A request
          // below has already resolved and painted the correct, newer value.
          await new Promise((res) => setTimeout(res, 900));
          return route.fulfill({ status: 200, contentType: 'application/json',
                                 body: JSON.stringify(chainFor(EXP_A, 111)) });
        }
        // The SECOND A request (after A -> B -> A) resolves immediately with the real,
        // current value.
        return route.fulfill({ status: 200, contentType: 'application/json',
                               body: JSON.stringify(chainFor(EXP_A, 333)) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json',
                             body: JSON.stringify(chainFor(EXP_B, 222)) });
    });

    await page.goto('/options');
    await expect(page.locator('#exp-select')).toHaveValue(EXP_A);   // fires the first, held A request

    await page.locator('#exp-select').selectOption(EXP_B);
    await expect(page.locator('#m-expiry')).toHaveText(EXP_B);
    await expect(page.locator('#m-spot')).toHaveText('650.25');
    await expect(page.locator('#chain-body td.strike')).toHaveText('222.00');

    await page.locator('#exp-select').selectOption(EXP_A);   // fires the second, fast A request
    await expect(page.locator('#m-expiry')).toHaveText(EXP_A);
    await expect(page.locator('#m-spot')).toHaveText('650.25');
    await expect(page.locator('#chain-body td.strike')).toHaveText('333.00');

    // Wait past the FIRST A request's deliberate 900ms delay.
    await page.waitForTimeout(1300);

    // Non-retrying snapshot: the held, stale first-A response must not have overwritten 333.
    const spotText = await page.locator('#m-spot').textContent();
    const expiryText = await page.locator('#m-expiry').textContent();
    expect(spotText).toBe('650.25');
    expect(expiryText).toBe(EXP_A);
    await expect(page.locator('#chain-body td.strike')).toHaveText('333.00');
    expect(aCallCount).toBe(2);
  });
