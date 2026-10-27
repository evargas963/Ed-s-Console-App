// No built-in ticker or watchlist: a first run with nothing chosen asks for a symbol and asks
// the server for nothing about any ticker. The page itself carries no history notes.
const { test, expect } = require('@playwright/test');

test.use({ storageState: { cookies: [], origins: [] } });

test('first run: no ticker is assumed, no ticker data is requested', async ({ page }) => {
  const tickerCalls = [];
  page.on('request', (req) => {
    const u = req.url();
    if (/[?&]ticker=/.test(u) || /\/api\/(chain|terrain|levels|options\/gamma-surface)/.test(u)) tickerCalls.push(u);
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hPx')).toHaveText('CHOOSE A SYMBOL');
  await expect(page.locator('#hFeed')).toHaveText('NO SYMBOL');
  // no panel header names a ticker nobody chose
  expect(await page.locator('.hticker').allTextContents()).toEqual(
    Array(await page.locator('.hticker').count()).fill('—'));
  await page.waitForTimeout(3500);                     // a full scheduler tick
  expect(tickerCalls, 'nothing may be fetched for an unchosen ticker').toEqual([]);
  expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe('');
});

test('the page the console serves carries no dates or ticket ids in its comments', async ({ request }) => {
  const page = await (await request.get('/')).text();
  const comments = [...page.matchAll(/<!--[\s\S]*?-->|\/\*[\s\S]*?\*\//g)].map((m) => m[0]);
  expect(comments.length, 'the page has comments to read').toBeGreaterThan(0);
  const history = comments.filter((c) => /\b20\d\d-\d\d-\d\d\b|\bRC-\d|\boperator,? 20\d\d|\baudit P\d/i.test(c));
  expect(history, 'history belongs in the commit message (AGENTS.md rule 1)').toEqual([]);
});

test('no symbol chosen: no view asks for a ticker on a view change, a resize, a theme change or its own controls', async ({ page }) => {
  const tickerCalls = [], asked = [];
  page.on('request', (req) => { if (/[?&]ticker=/.test(req.url())) tickerCalls.push(req.url()); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hPx')).toHaveText('CHOOSE A SYMBOL');
  for (const ws of await page.locator('.navitem[data-ws]').evaluateAll((ns) => ns.map((n) => n.dataset.ws))) {
    await page.locator(`.navitem[data-ws="${ws}"]`).click();
    for (const sub of await page.locator('#subnav button[data-sub]:not(.na)').evaluateAll((bs) => bs.map((b) => b.dataset.sub))) {
      await page.locator(`#subnav button[data-sub="${sub}"]`).click();
      const views = await page.locator('#viewbar .vtab:not(.na)').evaluateAll((bs) => bs.map((b) => b.dataset.view));
      for (const view of views.length ? views : [null]) {
        if (view) await page.locator(`#viewbar .vtab[data-view="${view}"]`).click();
        await page.setViewportSize({ width: 1500, height: 900 });
        await page.setViewportSize({ width: 1280, height: 800 });
        await page.evaluate(() => { window.EdShell.setTheme('dark'); window.EdShell.setTheme('light'); });
        for (const control of await page.locator('.cmode:visible, .scbtn:visible').all()) await control.click();
        await page.waitForTimeout(100);
        if (tickerCalls.length) asked.push(`${ws} > ${sub} > ${view}: ${tickerCalls.splice(0).join(', ')}`);
      }
    }
  }
  expect(asked, 'nothing may be fetched for an unchosen ticker').toEqual([]);
});
