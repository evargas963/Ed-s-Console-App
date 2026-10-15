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
const surface = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const listeners = {};
const host = { innerHTML: '', setAttribute: () => {}, removeAttribute: () => {}, querySelector: () => null, querySelectorAll: () => [] };
const ctx = {
  document: {
    documentElement: {},
    getElementById: (id) => (id === 'heatBody' ? host : null),
    querySelectorAll: () => [],
    // the page's served metas: the streaming-state words (none needed for the cell text)
    querySelector: () => ({ getAttribute: () => '{"cell": {}, "column": {}}' }),
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
  },
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  AbortController, Promise, JSON, Math, Number, String, Object, Array, Date, isNaN, URL, console,
};
ctx.window = ctx;
ctx.globalThis = ctx;
// the shell (ed-core.js) as the heatmap uses it: the view, no pan, no expiry selected, and the
// panel the console pushes (EdShell.onPanel)
const panels = {};
ctx.EdShell = {
  onPanel: (name, fn) => { panels[name] = fn; }, setInput: () => {},
  getState: () => ({ workspace: 'options', subview: 'gamma', view: 'heatmap', ticker: surface.ticker }),
  getMeasure: () => 'gex', getExpiry: () => null, setStrike: () => {},
  pan: () => ({ centre: null, shift: 0, served: null }), panServed: (pan, c) => { pan.served = c; },
  wireStrikeAxis: () => {},
};
vm.createContext(ctx);
vm.runInContext(readFileSync(join(ROOT, 'static/js/ed-gamma.js'), 'utf8'), ctx, { filename: 'ed-gamma.js' });
panels['gamma.surface']({ ok: true, status: 200, body: surface });
const cell = /<td class="hcell[^"]*"[^>]*data-strike="([^"]*)" data-expiry="([^"]*)"[^>]*>(.*?)<\/td>/g;
let m;
while ((m = cell.exec(host.innerHTML)) !== null) {
  console.log(JSON.stringify({ strike: Number(m[1]), expiry: m[2], text: m[3].replace(/<[^>]*>/g, '') }));
}
