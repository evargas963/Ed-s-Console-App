// Real-data visual proof capture for PR #238: opens the RUNNING candidate console, records the
// canonical vs displayed population in each scope, and saves full-viewport screenshots.
// Usage: node capture_real_console.mjs <baseUrl> <outDir> <tag> <width> <height> [ticker]
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const [,, baseUrl, outDir, tag, w, h, ticker] = process.argv;
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: +w, height: +h } });
const page = await ctx.newPage();
await page.addInitScript((t) => {
  try {
    if (t) localStorage.setItem('ed_ticker', t);
    localStorage.setItem('ed_ws', 'options'); localStorage.setItem('ed_sub', 'gamma'); localStorage.setItem('ed_view', 'heatmap');
    localStorage.setItem('ed_scope', 'auto');
  } catch (e) {}
}, ticker || null);
await page.goto(baseUrl + '/console', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('#heatBody .heat tbody tr', { timeout: 60000 });
await page.waitForTimeout(4000);
const record = { captured_local: new Date().toString(), viewport: `${w}x${h}`, url: baseUrl + '/console', scopes: {} };
record.build = await page.evaluate(async () => (await (await fetch('/api/build')).json()));
delete record.build.ui_maximize_sla_ms; delete record.build.ui_maximize_panel_warm_tickers;
record.surface_api = await page.evaluate(async () => {
  const t = window.EdShell.getState().ticker;
  const d = await (await fetch('/api/options/gamma-surface?ticker=' + encodeURIComponent(t))).json();
  return { ticker: d.ticker, source: d.source, live: d.live, stale: d.stale, et_date: d.et_date, session_date_et: d.session_date_et,
    prior_session: d.prior_session, spot: d.spot, strikes: (d.strikes || []).length, expirations: (d.expirations || []).length,
    expired_expirations: (d.expirations || []).filter((e) => e.expired).map((e) => e.expiry), cells: (d.cells || []).length };
});
record.strikes_api = await page.evaluate(async () => {
  const t = window.EdShell.getState().ticker;
  const d = await (await fetch('/api/terrain/strikes?ticker=' + encodeURIComponent(t))).json();
  return { rows: ((d.today || {}).all || []).length, source: d.today_source, stale: d.levels_stale, age: d.today_age_sec };
});
for (const scope of ['Auto', 'Wider', 'All available']) {
  await page.locator('#scopeCtl .scbtn', { hasText: scope }).click();
  await page.waitForTimeout(1500);
  const dom = await page.evaluate(() => {
    const rows = document.querySelectorAll('#heatBody .heat tbody tr');
    const cols = document.querySelectorAll('#heatBody .heat thead .hexp');
    const cell = document.querySelector('#heatBody .hcell');
    const wrap = document.querySelector('#heatBody .heat-wrap');
    return {
      heat_rows_shown: rows.length, heat_cols_shown: cols.length,
      heat_expired_cols_shown: document.querySelectorAll('#heatBody .heat thead .hexp.expired').length,
      heat_row_height_px: rows[0] ? Math.round(rows[0].getBoundingClientRect().height) : null,
      heat_cell_font_px: cell ? parseFloat(getComputedStyle(cell).fontSize) : null,
      heat_scrolls: wrap ? wrap.scrollHeight > wrap.clientHeight + 10 : null,
      heat_scope_header: (document.getElementById('heatScope') || {}).textContent,
      heat_scope_note: (document.querySelector('#heatBody .scope-note') || {}).textContent,
      heat_banner: (document.querySelector('#heatBody .heat-banner') || {}).textContent,
      spot_row: (document.querySelector('#heatBody tr.spotrow .hstrike') || {}).textContent,
      gbs_rows_shown: document.querySelectorAll('#gbsBody .gbs-row').length,
      gbs_scope_note: (document.querySelector('#gbsBody .scope-note') || {}).textContent,
      gbs_row_height_px: (document.querySelector('#gbsBody .gbs-row') || { getBoundingClientRect: () => ({ height: null }) }).getBoundingClientRect().height,
      key_levels_status: (document.getElementById('klSrc') || {}).textContent,
      key_levels_status_title: (document.getElementById('klSrc') || {}).title,
      body_horizontal_overflow: document.body.scrollWidth - document.body.clientWidth,
    };
  });
  record.scopes[scope] = dom;
  const file = path.join(outDir, `console_${tag}_${w}x${h}_${scope.replace(/\s+/g, '-').toLowerCase()}.png`);
  await page.screenshot({ path: file, fullPage: false });
  record.scopes[scope].screenshot = path.basename(file);
}
fs.writeFileSync(path.join(outDir, `console_${tag}_${w}x${h}_record.json`), JSON.stringify(record, null, 2) + '\n');
console.log(JSON.stringify({ viewport: record.viewport, build: record.build.git_sha, surface: record.surface_api, strikes_api: record.strikes_api,
  auto: record.scopes['Auto'], wider: { rows: record.scopes['Wider'].heat_rows_shown, cols: record.scopes['Wider'].heat_cols_shown },
  all: { rows: record.scopes['All available'].heat_rows_shown, cols: record.scopes['All available'].heat_cols_shown, rowH: record.scopes['All available'].heat_row_height_px, scrolls: record.scopes['All available'].heat_scrolls } }, null, 1));
await browser.close();
