/**
 * Issue 25 / no-flicker + Issue 27 / cold start — Tier B contract, EXECUTED on the SHIPPED JS.
 *
 * tests/test_l1_no_flicker.py and tests/test_l1_cold_start_transition.py used to
 * re-implement the client logic in Python ("Mirrors client logic in static/index.html")
 * and test the COPY, so drift in the shipped `renderTierBLight` pipeline could never fail
 * them. This harness extracts the REAL functions from static/index.html (and loads the
 * real static/js/l1_sse_guards.js), runs the same scenarios through the real
 * `renderTierBLight`, and prints a JSON map of outcomes for the pytest side to assert on:
 *   - a_* .. f_* keys → tests/test_l1_no_flicker.py (Issue 25 dedupe/no-flicker)
 *   - cold_* keys     → tests/test_l1_cold_start_transition.py (Issue 27 authority machine)
 *
 * Outcome vocabulary matches the old Python mirrors: "rejected" | "deduped" | "painted".
 * ("deduped" is the real renderer returning true after logging its Issue 25
 * "SKIP duplicate semantic Tier B paint" DIAG warn — the repaint was skipped.)
 *
 * Run: node tests/l1_tier_b_no_flicker_node.mjs   → prints JSON on stdout, exit 0.
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(__dirname, '..', 'static/index.html'), 'utf8');
const guardsSrc = readFileSync(join(__dirname, '..', 'static/js/l1_sse_guards.js'), 'utf8');

/** src[j] === '`': index just past the closing backtick (handles nested ${…}). */
function skipTemplate(src, j) {
  const n = src.length;
  j += 1;
  while (j < n) {
    const c = src[j];
    if (c === '\\') { j += 2; continue; }
    if (c === '`') return j + 1;
    if (c === '$' && src[j + 1] === '{') { j = balancedEnd(src, j + 1); continue; }
    j += 1;
  }
  throw new Error('unterminated template literal');
}

/** src[j] === '/' opening a regex literal: index just past the closing '/'. */
function skipRegex(src, j) {
  const n = src.length;
  j += 1;
  let inClass = false;
  while (j < n) {
    const c = src[j];
    if (c === '\\') { j += 2; continue; }
    if (inClass) {
      if (c === ']') inClass = false;
    } else if (c === '[') {
      inClass = true;
    } else if (c === '/') {
      return j + 1;
    } else if (c === '\n') {
      return j; // not actually a regex; treat as division and resync
    }
    j += 1;
  }
  return j;
}

/** True when a '/' at j begins a regex literal (prev-token heuristic). */
function regexCanStart(src, j) {
  let k = j - 1;
  while (k >= 0 && ' \t\r\n'.includes(src[k])) k -= 1;
  return k < 0 || '(,=:[!&|?{};<>+-*%~^'.includes(src[k]);
}

/** Index just past the brace matching the first '{' at/after `start` (skips strings/comments). */
function balancedEnd(src, start) {
  let j = src.indexOf('{', start);
  assert(j !== -1, 'no opening brace after ' + start);
  let depth = 0;
  const n = src.length;
  while (j < n) {
    const c = src[j];
    if (c === '`') {
      j = skipTemplate(src, j);
      continue;
    }
    if (c === "'" || c === '"') {
      j += 1;
      while (j < n) {
        if (src[j] === '\\') { j += 2; continue; }
        if (src[j] === c) break;
        j += 1;
      }
    } else if (c === '/' && src[j + 1] === '/') {
      j = src.indexOf('\n', j);
    } else if (c === '/' && src[j + 1] === '*') {
      j = src.indexOf('*/', j) + 1;
    } else if (c === '/' && regexCanStart(src, j)) {
      j = skipRegex(src, j);
      continue;
    } else if (c === '{') {
      depth += 1;
    } else if (c === '}') {
      depth -= 1;
      if (depth === 0) return j + 1;
    }
    j += 1;
  }
  throw new Error('unbalanced braces from ' + start);
}

function extractFn(name) {
  const marker = 'function ' + name + '(';
  const i = html.indexOf(marker);
  assert(i !== -1, name + ' is gone from static/index.html');
  return html.slice(i, balancedEnd(html, i));
}

// ── Real shipped code under test ────────────────────────────────────────────────
vm.runInThisContext(guardsSrc, { filename: 'static/js/l1_sse_guards.js' });
assert(globalThis.EdL1SseGuards, 'l1_sse_guards.js did not install EdL1SseGuards');
assert.strictEqual(typeof globalThis.EdL1SseGuards.l1ApplyTierBLightMonotonic, 'function');
assert.strictEqual(typeof globalThis.EdL1SseGuards.l1PayloadMatchesActiveScope, 'function');

/** Extract a shipped top-level `var NAME = ...;` tuning constant verbatim. */
function extractVar(name) {
  const m = html.match(new RegExp('var ' + name + '\\s*=[^;\\n]*;'));
  assert(m, name + ' is gone from static/index.html');
  return m[0];
}

const REAL_VARS = [
  'L1_UI_QUOTE_FRESH_SEC',
  'L1_UI_QUOTE_AGING_SEC',
  'L1_UI_OF_FRESH_SEC',
  'L1_UI_OF_AGING_SEC',
];

const REAL_FNS = [
  'l1GetAuthority',
  'l1SetAuthority',
  'l1FormatAgeCompact',
  'l1QuoteFreshTier',
  'l1OfFreshTier',
  'l1TierBComputeVisiblePaintInputs',
  'l1TierBSemanticSignatureFromPaintInputs',
  'l1TierBPayloadMatchesActiveScope',
  'renderTierBLight',
];

// ── Minimal environment: DOM/paint stubs only — no decision logic re-implemented ─
const sandbox = `
var window = globalThis;
window.__ED_E2E__ = true;
var DIAG = true;
var activeTicker = 'SPY';
var activeExpiry = '';
var _lastRenderTs = 0;
function $(id) { return null; }
function domIf(id, fn) {}
function paintStructureLevelsFromKl(d) {}
function l1ShouldPaintFreshness(sig, gen, scopeKey) { return false; }
function l1MarkFreshnessPainted(sig, gen, scopeKey) {}
function l1ApplyDotClass(el, tier) {}
function clearHardStaleUi() {}
function renderTimeframeSignalRow(d) {}
`;
vm.runInThisContext(
  sandbox + '\n' + REAL_VARS.map(extractVar).join('\n') + '\n' + REAL_FNS.map(extractFn).join('\n\n'), {
  filename: 'index.html#tier_b_pipeline',
});
assert.strictEqual(typeof globalThis.renderTierBLight, 'function');

// ── Outcome classifier around the real renderer ────────────────────────────────
let warns = [];
const realWarn = console.warn;
console.warn = (...args) => { warns.push(args.map(String).join(' ')); };
const realAssert = console.assert;
console.assert = (cond, ...args) => { assert(cond, 'console.assert failed: ' + args.join(' ')); };

function resetState() {
  globalThis._l1AuthorityByScope = {};
  globalThis._l1GenByScope = {};
  globalThis._l1ServerTsByScope = {};
  globalThis._l1LastPaintedIdentityByScope = {};
  globalThis._l1FreshnessPaintByScope = {};
  globalThis._lastData = {};
}

function step(activeTk, payload, source) {
  globalThis.activeTicker = activeTk;
  globalThis.activeExpiry = '';
  warns = [];
  const accepted = globalThis.renderTierBLight(payload, source);
  if (!accepted) return 'rejected';
  if (warns.some((w) => w.includes('SKIP duplicate semantic Tier B paint'))) return 'deduped';
  return 'painted';
}

const results = {};

// A. Duplicate SSE (same scope, gen, semantic) → dedupe
resetState();
{
  const p = () => ({
    ticker: 'SPY', selected_exp: null,
    l1_payload_fingerprint: 'abc123abc123abc123abc123abcdef00',
    l1_generation: 2, _server_build_ts: 100.0,
    quote_overlay_age_sec: 0.5, order_flow_age_sec: 1.0,
  });
  results.a_duplicate_sse = [step('SPY', p(), 'l1_sse'), step('SPY', p(), 'l1_sse')];
}

// B. Late HTTP after SSE does not repaint; authority stays SSE_LIVE
resetState();
{
  const http1 = () => ({ ticker: 'SPY', selected_exp: null, l1_generation: 1, _server_build_ts: 10.0, l1_payload_fingerprint: 'a'.repeat(32) });
  const sse2 = { ticker: 'SPY', selected_exp: null, l1_generation: 2, _server_build_ts: 20.0, l1_payload_fingerprint: 'b'.repeat(32) };
  const o1 = step('SPY', http1(), 'rest_manual');
  const o2 = step('SPY', sse2, 'l1_sse');
  const late = http1();
  late._server_build_ts = 99.0;
  const o3 = step('SPY', late, 'rest_manual');
  results.b_late_http = [o1, o2, o3];
  results.b_authority = globalThis._l1AuthorityByScope['SPY|'] || null;
}

// C. Same gen + newer ts, identical fingerprint → dedupe
resetState();
{
  const fp = 'c'.repeat(32);
  const p1 = { ticker: 'SPY', selected_exp: null, l1_generation: 5, _server_build_ts: 50.0, l1_payload_fingerprint: fp };
  const p2 = { ticker: 'SPY', selected_exp: null, l1_generation: 5, _server_build_ts: 51.0, l1_payload_fingerprint: fp, _pipeline_ms: 9.9 };
  results.c_same_gen_newer_ts = [step('SPY', p1, 'l1_sse'), step('SPY', p2, 'l1_sse')];
}

// D. Higher generation repaints
resetState();
{
  const p2 = { ticker: 'SPY', selected_exp: null, l1_generation: 2, _server_build_ts: 1.0, l1_payload_fingerprint: 'd'.repeat(32) };
  const p3 = { ticker: 'SPY', selected_exp: null, l1_generation: 3, _server_build_ts: 2.0, l1_payload_fingerprint: 'e'.repeat(32) };
  results.d_higher_gen = [step('SPY', p2, 'l1_sse'), step('SPY', p3, 'l1_sse')];
}

// E. Wrong ticker payload rejected (active QQQ, payload SPY)
resetState();
{
  const p = { ticker: 'SPY', selected_exp: null, l1_generation: 1, _server_build_ts: 1.0, l1_payload_fingerprint: 'f'.repeat(32) };
  results.e_wrong_ticker = [step('QQQ', p, 'l1_sse')];
}

// F. Monotonic rejects stale generation after a higher one painted
resetState();
{
  const p3 = { ticker: 'SPY', selected_exp: null, l1_generation: 3, _server_build_ts: 10.0, l1_payload_fingerprint: 'g'.repeat(32) };
  const p2 = { ticker: 'SPY', selected_exp: null, l1_generation: 2, _server_build_ts: 20.0, l1_payload_fingerprint: 'h'.repeat(32) };
  results.f_monotonic_stale = [step('SPY', p3, 'l1_sse'), step('SPY', p2, 'l1_sse')];
}

// ── Issue 27 — cold start → live: authority state machine + generation acceptance ──
// Scenarios for tests/test_l1_cold_start_transition.py. Each trace records, per step:
// the real renderer outcome, the l1_generation SENT, and (post-step) the authority
// string + accepted-generation store for the active scope key 'SPY|'.
const COLD_SCOPE = 'SPY|';
let coldFpSeq = 0;

/** Payload for the cold-start lane; omit gen/ts by passing undefined (fresh fingerprint each call). */
function coldPayload(gen, serverTs) {
  const p = { ticker: 'SPY', selected_exp: null };
  if (gen !== undefined) p.l1_generation = gen;
  if (serverTs !== undefined) p._server_build_ts = serverTs;
  p.l1_payload_fingerprint = 'cold' + String(coldFpSeq++).padStart(28, '0');
  return p;
}

/** Drive [source, payload] steps through the real renderTierBLight from a fresh state. */
function runColdStart(steps) {
  resetState();
  const trace = { outcomes: [], sent: [], auth: [], gen: [] };
  for (const [source, payload] of steps) {
    trace.sent.push(payload.l1_generation !== undefined ? payload.l1_generation : null);
    trace.outcomes.push(step('SPY', payload, source));
    trace.auth.push((globalThis._l1AuthorityByScope || {})[COLD_SCOPE] || 'INIT');
    const gAcc = (globalThis._l1GenByScope || {})[COLD_SCOPE];
    trace.gen.push(gAcc !== undefined ? gAcc : null);
  }
  return trace;
}

// cold_a — HTTP (gen=1) loads, SSE (gen=2) becomes authority; later HTTP ignored.
results.cold_a = runColdStart([
  ['rest_manual', coldPayload(1, 100.0)],
  ['l1_sse', coldPayload(2, 200.0)],
  ['rest_manual', coldPayload(99, 300.0)],
]);

// cold_b — SSE gen=10 accepted; late stale HTTP gen=9 rejected; store stays 10.
results.cold_b = runColdStart([
  ['rest_manual', coldPayload(1, 10.0)],
  ['l1_sse', coldPayload(10, 50.0)],
  ['rest_manual', coldPayload(9, 60.0)],
]);

// cold_c — after SSE_LIVE, HTTP with HIGHER gen=3 still ignored (hard HTTP block).
results.cold_c = runColdStart([
  ['rest_manual', coldPayload(1, 1.0)],
  ['l1_sse', coldPayload(2, 2.0)],
  ['rest_manual', coldPayload(3, 3.0)],
]);

// cold_d — accepted sequence must never decrease l1_generation.
results.cold_d = runColdStart([
  ['rest_manual', coldPayload(1, 10.0)],
  ['l1_sse', coldPayload(2, 20.0)],
  ['l1_sse', coldPayload(3, 30.0)],
  ['rest_manual', coldPayload(50, 99.0)],
]);

// cold_e — once SSE_LIVE, authority string never goes back to HTTP_INIT.
results.cold_e = runColdStart([
  ['rest_manual', coldPayload(1, 1.0)],
  ['l1_sse', coldPayload(2, 2.0)],
  ['rest_manual', coldPayload(1, 9.0)],
]);

// cold_f — HTTP payload with no l1_generation still promotes INIT → HTTP_INIT.
results.cold_f = runColdStart([
  ['rest_manual', coldPayload(undefined, undefined)],
]);

console.warn = realWarn;
console.assert = realAssert;
process.stdout.write(JSON.stringify(results));
