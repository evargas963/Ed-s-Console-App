// RC-123 rendered-proof probe: the cross-page ticker carrier (localStorage ed_ticker)
// must survive console -> chart -> console.
//
// v21 graded the original proof THEATER because this script lived in a scratchpad — a
// verification nobody can re-run is a story, not evidence. It is repo-tracked now:
//   node tools/ticker_journey_probe.js
// Runs against the static files (file:// shares one origin, so localStorage carries);
// API calls fail harmlessly — only the carrier mechanics are under test. Exit 0 = the
// journey held; exit 1 with the observed state = it broke.
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext();
  const p = await ctx.newPage();
  const root = path.resolve(__dirname, '..');
  const toUrl = f => 'file:///' + path.join(root, f).split(path.sep).join('/');
  const idx = toUrl('static/index.html');
  const cht = toUrl('static/chart.html');

  await p.goto(idx, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await p.waitForTimeout(2500);
  const typed = await p.evaluate(() => {
    const cands = [...document.querySelectorAll('input')]
      .filter(i => (i.value || '').toUpperCase() === 'SPY');
    if (!cands.length) return 'no-input';
    const el = cands[0];
    el.value = 'QQQ';
    el.dispatchEvent(new Event('blur'));
    // the legacy path commits via Enter -> triggerRefresh -> fetchState -> setActiveTicker
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    return el.id || 'anon';
  });
  await p.waitForTimeout(1200);
  const stored = await p.evaluate(() => localStorage.getItem('ed_ticker'));

  await p.goto(cht, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await p.waitForTimeout(2000);
  const chartTk = await p.evaluate(() => (document.getElementById('tk') || {}).value);

  await p.goto(idx, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await p.waitForTimeout(2500);
  const backTk = await p.evaluate(() => {
    const i = [...document.querySelectorAll('input')]
      .find(x => /^[A-Z]{1,5}$/.test(x.value || ''));
    return i ? i.value : null;
  });

  const result = { typedInto: typed, stored, chartTk, backTk };
  console.log(JSON.stringify(result));
  await b.close();
  const ok = stored === 'QQQ' && chartTk === 'QQQ' && backTk === 'QQQ';
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error('PROBE FAIL:', e.message); process.exit(1); });
