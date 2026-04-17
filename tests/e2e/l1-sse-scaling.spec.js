// @ts-check
// Issue 31 — measure simultaneous EventSource connections to L1 light SSE (browser limits).
const { test, expect } = require('@playwright/test');

/**
 * Opens N parallel EventSources to the same stream URL, waits, counts OPEN (readyState === 1).
 * Records a table for docs/l1_sse_scaling.md (browser-specific; run locally or in CI).
 */
test('measure simultaneous EventSource connections (same ticker)', async ({ page, baseURL }, testInfo) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const origin = baseURL || 'http://127.0.0.1:8765';
  const url = `${origin}/api/analytics/light/stream?ticker=SPY`;

  const rows = await page.evaluate(async (streamUrl) => {
    /** @type {{ connections: number, opened: number, connecting: number, closed: number }[]} */
    const out = [];
    for (let n = 1; n <= 10; n += 1) {
      const list = [];
      for (let i = 0; i < n; i += 1) {
        list.push(new EventSource(streamUrl));
      }
      // First byte + ": ok" may take >800ms under load; allow time to reach OPEN.
      await new Promise((r) => setTimeout(r, 1500));
      let opened = 0;
      let connecting = 0;
      let closed = 0;
      for (const es of list) {
        if (es.readyState === 1) opened += 1;
        else if (es.readyState === 0) connecting += 1;
        else closed += 1;
        es.close();
      }
      out.push({ connections: n, opened, connecting, closed });
    }
    return out;
  }, url);

  await testInfo.attach('l1-sse-scaling-table', {
    body: JSON.stringify(rows, null, 2),
    contentType: 'application/json',
  });

  // Soft sanity: first row should open at least one connection when N=1.
  expect(rows[0].opened).toBeGreaterThanOrEqual(1);

  // Document typical browser per-host behavior: by N=10, not all may be OPEN simultaneously.
  const row10 = rows.find((r) => r.connections === 10);
  expect(row10).toBeTruthy();
  if (row10) {
    expect(row10.opened + row10.connecting + row10.closed).toBe(10);
  }
});

test('different tickers each get their own EventSource URL', async ({ page, baseURL }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const origin = baseURL || 'http://127.0.0.1:8765';
  const a = `${origin}/api/analytics/light/stream?ticker=SPY`;
  const b = `${origin}/api/analytics/light/stream?ticker=QQQ`;

  const { openA, openB } = await page.evaluate(async (urls) => {
    const esA = new EventSource(urls.a);
    const esB = new EventSource(urls.b);
    await new Promise((r) => setTimeout(r, 1500));
    const oa = esA.readyState === 1 ? 1 : 0;
    const ob = esB.readyState === 1 ? 1 : 0;
    esA.close();
    esB.close();
    return { openA: oa, openB: ob };
  }, { a, b });

  expect(openA + openB).toBeGreaterThanOrEqual(1);
});
