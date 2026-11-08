/**
 * Render one served gamma surface through static/js/ed-gamma.js (its own load path) and print
 * each drawn cell as JSON lines: {strike, expiry, text}. Run by tests/gamma_render_helper.py
 * with the surface the server serves.
 * Usage: node tests/ed_gamma_cells_node.mjs <surface.json>
 */
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
// the page's own stylesheet, its default (dark) theme: the first :root block's custom properties
const DARK = Object.fromEntries(
  [...readFileSync(join(ROOT, 'static/css/ed-tokens.css'), 'utf8').split(':root[data-theme="light"]')[0]
    .matchAll(/(--ed-[a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
const surface = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const events = new EventTarget();   // the document's events, as a browser dispatches them
const host = { innerHTML: '', setAttribute: () => {}, removeAttribute: () => {}, querySelector: () => null, querySelectorAll: () => [] };
// the page's served metas: the scopes and market context the shell reads, and the
// streaming-state words (none needed for the cell text)
const METAS = {
  'ed-scopes': '[{"key": "all"}]', 'ed-market-context': '[]', 'ed-stream-words': '{"cell": {}, "column": {}}',
};
const ctx = {
  document: {
    documentElement: {},
    readyState: 'loading',
    getElementById: (id) => (id === 'heatBody' ? host : id === 'app' ? { getAttribute: () => null } : null),
    querySelectorAll: () => [],
    querySelector: (sel) => ({ getAttribute: () => METAS[/name="([^"]*)"/.exec(sel)[1]] }),
    addEventListener: events.addEventListener.bind(events),
  },
  localStorage: { getItem: () => null, setItem: () => {} },
  getComputedStyle: () => ({ getPropertyValue: (name) => DARK[name] }),
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(surface) }),
  AbortController, Promise, JSON, Math, Number, String, Object, Array, Date, isNaN, URL, console,
};
ctx.window = ctx;
ctx.globalThis = ctx;
vm.createContext(ctx);
// the shell (ed-core.js) itself, its intensity rule and heat colours as the page has them; the
// view it reports held at the heatmap, no pan, no expiry selected
vm.runInContext(readFileSync(join(ROOT, 'static/js/ed-core.js'), 'utf8'), ctx, { filename: 'ed-core.js' });
Object.assign(ctx.EdShell, {
  getState: () => ({ workspace: 'options', subview: 'gamma', view: 'heatmap', ticker: surface.ticker }),
  getMeasure: () => 'gex', getExpiry: () => null, setStrike: () => {},
  windowQuery: () => '&scope=all', wireStrikeAxis: () => {},
});
vm.runInContext(readFileSync(join(ROOT, 'static/js/l1_sse_guards.js'), 'utf8'), ctx, { filename: 'l1_sse_guards.js' });
vm.runInContext(readFileSync(join(ROOT, 'static/js/ed-gamma.js'), 'utf8'), ctx, { filename: 'ed-gamma.js' });
events.dispatchEvent(new CustomEvent('ed:view', { detail: {} }));   // the shell's view change
await new Promise((r) => setTimeout(r, 50));
const cell = /<td class="hcell[^"]*"[^>]*data-strike="([^"]*)" data-expiry="([^"]*)"[^>]*>(.*?)<\/td>/g;
let m;
while ((m = cell.exec(host.innerHTML)) !== null) {
  console.log(JSON.stringify({ strike: Number(m[1]), expiry: m[2], text: m[3].replace(/<[^>]*>/g, '') }));
}
