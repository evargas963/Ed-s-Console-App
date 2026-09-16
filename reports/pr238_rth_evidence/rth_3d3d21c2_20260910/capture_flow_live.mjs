// RTH D-Flow live proof for PR #238: on the RUNNING candidate, select the nearest-spot Call in
// Chain (EdStream posts the ONE control request), open Flow, wait for ACTIVE, and record DOM + API.
// Usage: node capture_flow_live.mjs <baseUrl> <outDir> <ticker> <width> <height>
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const [,, baseUrl, outDir, ticker, w, h] = process.argv;
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: +w, height: +h } });
const page = await ctx.newPage();
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e)));
await page.addInitScript((t) => {
  try {
    localStorage.setItem('ed_ticker', t);
    localStorage.setItem('ed_ws', 'options'); localStorage.setItem('ed_sub', 'chain');
  } catch (e) {}
}, ticker);
await page.goto(baseUrl + '/console', { waitUntil: 'domcontentloaded' });
await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
await page.waitForSelector('#chainBody table.chn tr[data-csym]', { timeout: 90000 });
await page.waitForTimeout(1500);
const rec = { captured_local: new Date().toString(), viewport: `${w}x${h}`, ticker, page_errors: pageErrors };
rec.build = await page.evaluate(async () => { const b = await (await fetch('/api/build')).json(); return { git_sha: b.git_sha, pid: b.process_identity.process_id, dirty: b.process_identity.startup_git_dirty }; });
// Chain: pick the Call row whose strike is nearest the live spot (spot from EdShell state / spot row).
const pick = await page.evaluate(() => {
  const rows = Array.from(document.querySelectorAll('#chainBody table.chn tr[data-csym]'));
  const spotEl = document.querySelector('#chainBody .spot, #chainBody tr.spotrow');
  const strikes = rows.map((r) => ({ sym: r.getAttribute('data-csym'), strike: parseFloat((r.querySelector('.chn-strike, td.strike') || {}).textContent || 'NaN'), text: r.textContent.trim().slice(0, 120) }));
  return { rows: rows.length, spot_text: spotEl ? spotEl.textContent.trim().slice(0, 80) : null, sample: strikes.slice(0, 3), all: strikes };
});
rec.chain = { rows: pick.rows, spot_text: pick.spot_text, sample: pick.sample };
const spot = await page.evaluate(async (t) => (await (await fetch('/api/options/gamma-surface?ticker=' + encodeURIComponent(t))).json()).spot, ticker);
rec.spot = spot;
let best = null;
for (const s of pick.all) { if (!isNaN(s.strike) && (best === null || Math.abs(s.strike - spot) < Math.abs(best.strike - spot))) best = s; }
if (!best) { best = pick.all[Math.floor(pick.all.length / 2)]; }
rec.selected_row = best;
await page.locator('#chainBody tr[data-csym="' + best.sym + '"] td.chn-call').first().click();
await page.waitForTimeout(500);
rec.desired = await page.evaluate(() => (window.EdStream && window.EdStream.getDesired && window.EdStream.getDesired()) || null);
await page.locator('#subnav .tab', { hasText: 'Flow' }).click();
await page.waitForSelector('#flowBody .fl-badge', { timeout: 30000 });
// wait up to 90s for ACTIVE (daemon must accept + bind both producers)
const t0 = Date.now(); let badge = '';
while (Date.now() - t0 < 90000) {
  badge = (await page.locator('#flowBody .fl-badge').first().textContent().catch(() => '')) || '';
  if (badge.trim() === 'ACTIVE') break;
  await page.waitForTimeout(2000);
}
rec.badge = badge.trim(); rec.seconds_to_badge = Math.round((Date.now() - t0) / 1000);
await page.waitForTimeout(6000);   // let a few refresh cycles land
rec.flow_dom = await page.evaluate(() => {
  const rows = Array.from(document.querySelectorAll('#flowBody .fl-row[data-k]')).map((r) => ({
    k: r.getAttribute('data-k'), v: (r.querySelector('.v') || {}).textContent, tag: (r.querySelector('.fl-tag') || {}).textContent, tagcls: (r.querySelector('.fl-tag') || {}).className }));
  return { badge: (document.querySelector('#flowBody .fl-badge') || {}).textContent, sym: (document.querySelector('#flowBody .fl-sym') || {}).textContent,
    foot: (document.querySelector('#flowBody .fl-foot') || {}).textContent, rows,
    header_static_chips: document.querySelectorAll('[data-sub-pane="flow"] .panel-h .prov').length };
});
rec.flow_api = await page.evaluate(async (d) => {
  const j = await (await fetch('/api/order-flow/options-microstructure?contract=' + encodeURIComponent(d), { cache: 'no-store' })).json();
  const sp = j.streaming_plane || {};
  return { contract: j.contract || j.symbol, flow: j.flow, ages: j.ages, classification: j.classification, top_of_book: j.top_of_book, mid: j.mid, microprice: j.microprice, spread_pts: j.spread_pts,
    streaming_plane: { producer_l1_contract: sp.producer_l1_contract, producer_book_contract: sp.producer_book_contract, daemon_pid: (sp.stream_db_identity || {}).producer_heartbeat ? sp.stream_db_identity.producer_heartbeat.daemon_pid : undefined, keys: Object.keys(sp) } };
}, rec.desired);
const shot = path.join(outDir, `console_flow_${ticker}_${w}x${h}.png`);
await page.screenshot({ path: shot, fullPage: false });
rec.screenshot = path.basename(shot);
fs.writeFileSync(path.join(outDir, `console_flow_${ticker}_${w}x${h}_record.json`), JSON.stringify(rec, null, 2) + '\n');
console.log(JSON.stringify(rec, null, 1));
await browser.close();
