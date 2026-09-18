/**
 * RC-UI-1 — node assertions for static/js/ed-gamma.js heatmap presentation helpers.
 * Run: node tests/ed_gamma_node.mjs
 *
 * Proves the operator's frontend invariants D (sign -> colour, no inversion) and E (the
 * displayed dollar text is FORMATTING-ONLY and equals the backend value). These CALL the real
 * functions (a source-text test cannot detect a wrong colour, only a missing one).
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
vm.runInThisContext(readFileSync(join(ROOT, 'static/js/ed-gamma.js'), 'utf8'),
  { filename: 'ed-gamma.js' });

const G = globalThis.EdGamma;
assert(G && typeof G.formatUsd === 'function' && typeof G.cellStyle === 'function', 'EdGamma missing');
globalThis.window = globalThis;
let gen = 1;
function installShell(ticker) {
  globalThis.EdShell = {
    getState() { return { ticker: ticker, workspace: 'options', subview: 'gamma', view: 'heatmap' }; },
    getTickerGeneration() { return gen; },
    setStrike() {},
  };
  G.beginSurfaceRequest(ticker, gen);
}
function withId(surf, ticker) {
  return Object.assign({}, surf, { ticker: ticker, requested_ticker: ticker });
}
installShell('SPY');

// ---- E: value formatting is formatting-only and equals the backend number ----
assert.strictEqual(G.formatUsd(958600), '$958.6K');
assert.strictEqual(G.formatUsd(-264500), '-$264.5K');
assert.strictEqual(G.formatUsd(7600000), '$7.6M');
assert.strictEqual(G.formatUsd(2140000000), '$2.1B');
assert.strictEqual(G.formatUsd(807500), '$807.5K');
assert.strictEqual(G.formatUsd(0), '$0');
assert.strictEqual(G.formatUsd(null), '');
assert.strictEqual(G.formatUsd(undefined), '');
// formatting must not change sign or magnitude scale
for (const v of [958600, -264500, 7600000, -1, 42, -999999]) {
  const s = G.formatUsd(v);
  assert.strictEqual(s.startsWith('-'), v < 0, 'formatUsd changed sign for ' + v);
}

// ---- D: sign -> colour, no inversion (theme-aware solid fills, interpolated from heat tokens) ----
const HEAT = { pos: [35, 192, 107], neg: [229, 72, 77], zero: [18, 26, 37] };
function rgb(s) { const m = /rgb\((\d+),(\d+),(\d+)\)/.exec(s || ''); return m ? [+m[1], +m[2], +m[3]] : null; }

const pos = rgb(G.cellStyle(500000, 1000000, HEAT).bg);
const neg = rgb(G.cellStyle(-500000, 1000000, HEAT).bg);
assert.ok(pos[1] > pos[0] && pos[1] > pos[2], 'positive cell is not green-dominant');   // G channel wins
assert.ok(neg[0] > neg[1] && neg[0] > neg[2], 'negative cell is not red-dominant');     // R channel wins
assert.strictEqual(G.cellStyle(500000, 1000000, HEAT).sign, 1);
assert.strictEqual(G.cellStyle(-500000, 1000000, HEAT).sign, -1);

// larger |magnitude| -> stronger fill (monotone toward full green, same sign, no inversion)
const gLow = rgb(G.cellStyle(200000, 1000000, HEAT).bg)[1];
const gHigh = rgb(G.cellStyle(900000, 1000000, HEAT).bg)[1];
assert.ok(gHigh > gLow, 'shade intensity is not monotone in |value|');

// null -> empty; near-zero recedes to the theme's zero colour, never a signed fill
assert.strictEqual(G.cellStyle(null, 1000000, HEAT).empty, true);
assert.deepStrictEqual(rgb(G.cellStyle(0.4, 1000000, HEAT).bg), [18, 26, 37], 'near-zero cell is not the recede colour');

// a DIFFERENT theme palette must still map positive->its green and negative->its red (no inversion)
const LIGHT = { pos: [26, 158, 92], neg: [214, 59, 59], zero: [230, 235, 241] };
assert.ok(rgb(G.cellStyle(800000, 1000000, LIGHT).bg)[1] > rgb(G.cellStyle(800000, 1000000, LIGHT).bg)[0], 'light-theme positive not green-dominant');
assert.ok(rgb(G.cellStyle(-800000, 1000000, LIGHT).bg)[0] > rgb(G.cellStyle(-800000, 1000000, LIGHT).bg)[1], 'light-theme negative not red-dominant');

// nearestStrikeIndex is a pure locator (spot highlight), no math on values
assert.strictEqual(G.nearestStrikeIndex([90, 100, 110], 101), 1);
assert.strictEqual(G.nearestStrikeIndex([90, 100, 110], 104.9), 1);

// ---- F: heatmap rows render highest strike at the top, lowest at the bottom (operator
// finding, 2026-09-11) -- calls the REAL renderSurface against a minimal DOM/EdShell stub,
// so this proves actual row order and actual per-row strike/gex binding, not source text.
global.document = {
  documentElement: {},
  getElementById: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
installShell('SPY');

function makeHost() {
  return { innerHTML: '', querySelector: () => null, querySelectorAll: () => [] };
}

const strikes = [759, 760, 761, 762, 763, 764, 765, 766, 767, 768, 769]; // ascending, as the API serves them
const cells = strikes.map((k, i) => ({ strike: k, gex: [1000 * (i + 1)],
  contracts: [{ call: 'SPY_C_' + k, put: 'SPY_P_' + k }] }));
const surface = {
  available: true,
  ticker: 'SPY', requested_ticker: 'SPY',
  current_spot: 764,
  current_spot_state: 'live',
  spot: 764,
  strikes,
  cells,
  expirations: [{ expiry: '2026-09-11', dte: 0, expired: false }],
  live: true,
  stale: false,
};

const host1 = makeHost();
installShell('SPY');
G.renderSurface(host1, surface);
const rowStrikes = [...host1.innerHTML.matchAll(/data-strike="(\d+)"/g)].map((m) => Number(m[1]));
// one data-strike per <td> per row (single expiry column here) -> one value per row, in
// render order
assert.deepStrictEqual(rowStrikes, [...strikes].reverse(),
  'heatmap rows must descend from the highest strike to the lowest');

// each row's own gex value travels with its own strike (no cross-row value shuffle from the
// reversal -- this is the "preserve identity" requirement, checked against the real cell text)
const rows = [...host1.innerHTML.matchAll(/data-strike="(\d+)"[^>]*data-gex="(-?\d+)"/g)];
for (const [, strikeStr, gexStr] of rows) {
  const strike = Number(strikeStr);
  const expectedGex = cells[strikes.indexOf(strike)].gex[0];
  assert.strictEqual(Number(gexStr), expectedGex, `strike ${strike} lost its own gex value under reversal`);
}

// the "all available" fallback path (no EdShell.scopeSelect) must ALSO descend -- this is the
// path a bare surface actually exercises when EdShell is absent, and it is the same path real
// scopeSelect output flows through, so this proves the render loop's own reversal, not a
// scopeSelect-specific behaviour.
const host2 = makeHost();
G.renderSurface(host2, withId({ ...surface, current_spot: 200, current_spot_state: 'live', strikes: [100, 200, 300], cells: [
  { strike: 100, gex: [1], contracts: [{ call: 'C100', put: 'P100' }] },
  { strike: 200, gex: [2], contracts: [{ call: 'C200', put: 'P200' }] },
  { strike: 300, gex: [3], contracts: [{ call: 'C300', put: 'P300' }] },
] }, 'SPY'));
const rowStrikes2 = [...host2.innerHTML.matchAll(/data-strike="(\d+)"/g)].map((m) => Number(m[1]));
assert.deepStrictEqual(rowStrikes2, [300, 200, 100]);

// Banked morning cells cannot enter the current heatmap.
const bankedHost = makeHost();
G.renderSurface(bankedHost, Object.assign({}, surface, {
  source: 'banked_morning_reference', available: true, live: false,
}));
assert.ok(bankedHost.innerHTML.includes('Gamma surface unavailable'),
  'banked morning reference must not paint current heatmap cells');
assert.ok(!bankedHost.innerHTML.includes('data-strike='),
  'banked morning reference must not emit heatmap cells');

// Rendered live-capable contracts == demanded contracts (one selected set).
const demandHost = makeHost();
G.renderSurface(demandHost, surface);
const rendered = G.heatmapVisibleContracts();
const demanded = G.heatmapDemandSymbols();
assert.deepStrictEqual(demanded, rendered, 'demand set must equal rendered selected-contract set');
assert.ok(rendered.length > 0, 'live surface with contracts must demand them');

// Missing contract arrays fail closed — no empty successful state.
assert.throws(() => G.selectLiveHeatmap({
  available: true, source: 'terrain_live_cache',
  current_spot: 100, current_spot_state: 'live',
  strikes: [100], expirations: [{ expiry: '2026-09-11', expired: false }],
  cells: [{ strike: 100, gex: [1] }],
}, 'all', null, null, null), /contracts missing/);
assert.throws(() => G.selectLiveHeatmap({
  available: true, source: 'terrain_live_cache', spot: 999,
  strikes: [100], expirations: [{ expiry: '2026-09-11', expired: false }],
  cells: [{ strike: 100, gex: [1], contracts: [{ call: 'C', put: 'P' }] }],
}, 'all', null, null, null), /no live selected-contract set/);
const noSpotHost = makeHost();
G.renderSurface(noSpotHost, withId({
  available: true, source: 'terrain_live_cache', live: true, stale: false,
  spot: 999, strikes: [100],
  expirations: [{ expiry: '2026-09-11', dte: 1, expired: false }],
  cells: [{ strike: 100, gex: [500000], contracts: [{ call: 'C100', put: 'P100' }] }],
}, 'SPY'));
assert.ok(noSpotHost.innerHTML.includes('UNAVAILABLE'),
  'missing current_spot must fail closed even when surface.spot is present');
assert.ok(!noSpotHost.innerHTML.includes('999'),
  'surface.spot must never be substituted for current_spot');
G.renderSurface(makeHost(), withId({ available: false, source: 'unavailable' }, 'SPY'));
assert.throws(() => G.heatmapVisibleContracts(), /no selected-contract set/);
assert.throws(() => G.heatmapVisibleContracts(undefined, { idx: [0] }, [0]), /cells array required/);

// An expiry column with contracts but no GEX must stay on the grid. Null GEX is not NO OI.
const emptyColHost = makeHost();
G.renderSurface(emptyColHost, withId({
  available: true, source: 'terrain_live_cache', live: true, stale: false,
  current_spot: 100, current_spot_state: 'live',
  spot: 100, strikes: [100, 101],
  expirations: [
    { expiry: '2026-09-18', dte: 1, expired: false },
    { expiry: '2026-10-01', dte: 14, expired: false },
  ],
  cells: [
    { strike: 100, gex: [500000, null], contracts: [{ call: 'C100a', put: 'P100a' }, { call: 'C100b', put: 'P100b' }] },
    { strike: 101, gex: [-200000, null], contracts: [{ call: 'C101a', put: 'P101a' }, { call: 'C101b', put: 'P101b' }] },
  ],
}, 'SPY'));
assert.ok(!emptyColHost.innerHTML.includes('NO OI'), 'null GEX must not produce a NO OI label');
assert.ok(emptyColHost.innerHTML.includes('OI UNAVAILABLE'),
  'listed contracts with no OI field must read OI UNAVAILABLE');
assert.ok((emptyColHost.innerHTML.match(/data-expiry="2026-10-01"/g) || []).length === 2,
  'all-null expiry column must still render every row');

const statesHost = makeHost();
G.renderSurface(statesHost, withId({
  available: true, source: 'terrain_live_cache', live: true, stale: false,
  current_spot: 100, current_spot_state: 'live',
  strikes: [90, 100, 110],
  expirations: [{ expiry: '2026-09-18', dte: 1, expired: false }],
  cells: [
    { strike: 90, gex: [null], contracts: [{ call: null, put: null }],
      value_states: ['no_contract'],
      stream: [{ state: 'unavailable' }] },
    { strike: 100, gex: [0], oi: [{ call: 0, put: 0 }],
      contracts: [{ call: 'C100', put: 'P100' }],
      value_states: ['zero_oi'],
      stream: [{ state: 'pending' }] },
    { strike: 110, gex: [null], oi: [{ call: 40, put: 20 }],
      contracts: [{ call: 'C110', put: 'P110' }],
      value_states: ['gamma_unavailable'],
      stream: [{ state: 'rejected', call: { rejected_reason: 'vendor' } }] },
  ],
}, 'SPY'));
assert.ok(statesHost.innerHTML.includes('NO CONTRACT'), 'no listed contract stays NO CONTRACT');
assert.ok(statesHost.innerHTML.includes('$0'), 'zero OI must render numerical zero, not an em dash');
assert.ok(statesHost.innerHTML.includes('GAMMA UNAVAILABLE'), 'missing gamma stays GAMMA UNAVAILABLE');
assert.ok(statesHost.innerHTML.includes('data-cell-state="pending"'), 'pending stream state stays distinct');
assert.ok(statesHost.innerHTML.includes('data-cell-state="rejected"'), 'rejected stream state stays distinct');
assert.ok(!statesHost.innerHTML.includes('>—<'), 'em dash must not stand in for a proven zero');
assert.strictEqual(G.classifyHeatmapCell({ gex: [null], contracts: [{ call: 'C', put: 'P' }] }, 0),
  'oi_unavailable', 'null GEX with listed contracts is not NO CONTRACT');
assert.strictEqual(G.canonicalCurrentSpot({ spot: 12, current_spot: 34 }), 34);
assert.ok(Number.isNaN(G.canonicalCurrentSpot({ spot: 12 })), 'absent current_spot is not surface.spot');

function makeQueryableHost() {
  const host = { innerHTML: '' };
  host.querySelector = function (sel) { return host.querySelectorAll(sel)[0] || null; };
  host.querySelectorAll = function (sel) {
    const tags = host.innerHTML.match(/<td class="hcell[^"]*"[^>]*>/g) || [];
    return tags.filter((tag) => {
      if (sel.indexOf('.hcell') === -1) return false;
      if (sel.indexOf('data-cell-state') !== -1 && tag.indexOf('data-cell-state=') === -1) return false;
      if (sel.indexOf('data-has-contract-identity="1"') !== -1 &&
          tag.indexOf('data-has-contract-identity="1"') === -1) return false;
      return true;
    }).map((tag) => ({
      getAttribute: function (name) {
        const m = tag.match(new RegExp(name + '="([^"]*)"'));
        return m ? m[1] : null;
      },
    }));
  };
  return host;
}

const mixedHost = makeHost();
const mixedSurface = {
  available: true, source: 'terrain_live_cache', live: true, stale: false,
  ticker: 'SPY', requested_ticker: 'SPY', current_spot: 100, current_spot_state: 'live',
  strikes: [90, 95, 100, 105, 110],
  expirations: [{ expiry: '2026-09-18', dte: 1, expired: false }],
  cells: [
    { strike: 90, gex: [null], contracts: [{ call: null, put: null }],
      value_states: ['no_contract'],
      stream: [{ state: 'unavailable', has_contract_identity: false }] },
    { strike: 95, gex: [0], oi: [{ call: 0, put: 0 }],
      contracts: [{ call: 'C95', put: 'P95' }],
      value_states: ['zero_oi'],
      stream: [{ state: 'pending', has_contract_identity: true }] },
    { strike: 100, gex: [5000], contracts: [{ call: 'C100', put: 'P100' }],
      value_states: ['computed'],
      stream: [{ state: 'live', has_contract_identity: true }] },
    { strike: 105, gex: [2000], contracts: [{ call: 'C105', put: 'P105' }],
      value_states: ['computed'],
      stream: [{ state: 'stale', has_contract_identity: true }] },
    { strike: 110, gex: [1000], contracts: [{ call: 'C110', put: 'P110' }],
      value_states: ['computed'],
      stream: [{ state: 'rejected', has_contract_identity: true,
        call: { rejected_reason: 'vendor' } }] },
  ],
};
G.renderSurface(mixedHost, mixedSurface);
assert.ok(mixedHost.innerHTML.includes('NO CONTRACT'), 'NO CONTRACT stays labelled');
assert.ok(mixedHost.innerHTML.includes('data-has-contract-identity="0"'),
  'NO CONTRACT is stamped ineligible');
assert.ok(mixedHost.innerHTML.includes('$0'), 'ZERO OI stays a real contract with $0');
const mixedQuery = makeQueryableHost();
mixedQuery.innerHTML = mixedHost.innerHTML;
const mixedCov = G.visibleCellCoverage(mixedQuery);
assert.strictEqual(mixedCov.schema, 'gamma_stream_coverage_eligibility_v1');
assert.strictEqual(mixedCov.total_visible_cells, 4, JSON.stringify(mixedCov));
assert.strictEqual(mixedCov.live, 1);
assert.strictEqual(mixedCov.pending, 1);
assert.strictEqual(mixedCov.stale, 1);
assert.strictEqual(mixedCov.rejected, 1);
assert.strictEqual(mixedCov.unavailable, 0);
assert.strictEqual(
  mixedCov.live + mixedCov.partial + mixedCov.stale + mixedCov.pending +
    mixedCov.daemon_unavailable + mixedCov.rejected + mixedCov.unavailable,
  mixedCov.total_visible_cells,
);
assert.strictEqual(mixedCov.meets_live_requirement, false);
assert.strictEqual(G.cellHasContractIdentity({}, 0, { has_contract_identity: true }), true);
assert.strictEqual(G.cellHasContractIdentity({}, 0, { has_contract_identity: false }), false);
assert.strictEqual(G.cellHasContractIdentity({ contracts: [{ call: 'C' }] }, 0, {}), false,
  'missing server stamp is ineligible');
assert.strictEqual(G.cellHasContractIdentity({ contracts: [{ call: 'C' }] }, 0, { has_contract_identity: 'true' }), false,
  'malformed stamp is ineligible');
assert.strictEqual(G.cellHasContractIdentity({ contracts: [{ call: 'C' }] }, 0, null), false);
assert.ok(!G.gammaCellHasContractIdentity, 'no JS identity parser');

const rejectHost = makeHost();
G.renderSurface(rejectHost, { available: true, current_spot: 100, current_spot_state: 'live',
  strikes: [100], expirations: [{ expiry: '2026-09-18', expired: false }],
  cells: [{ strike: 100, gex: [1], contracts: [{ call: 'C', put: 'P' }] }] });
assert.ok(rejectHost.innerHTML.includes('Gamma surface unavailable'),
  'direct render without request context must reject');

assert.strictEqual(G.surfaceTickerAdmitted({ ticker: 'SPY', requested_ticker: 'SPY' }), true);
assert.strictEqual(G.surfaceTickerAdmitted({ ticker: 'SPY' }), false, 'missing requested_ticker');
assert.strictEqual(G.surfaceTickerAdmitted({ requested_ticker: 'SPY' }), false, 'missing payload ticker');
assert.strictEqual(G.surfaceTickerAdmitted({ ticker: '$SPX', requested_ticker: 'SPX' }), false,
  'index alias drift must not be normalized on the client');
assert.strictEqual(G.surfaceTickerAdmitted({ ticker: 'SPX', requested_ticker: '$SPX' }), false,
  'bare vs dollar index mismatch must reject');
const saved = global.window.EdShell;
global.window.EdShell = { getState() { return { ticker: 'SPY' }; } };
assert.strictEqual(G.surfaceTickerAdmitted({ ticker: 'SPY', requested_ticker: 'SPY' }), false,
  'missing getTickerGeneration rejects');
global.window.EdShell = null;
assert.strictEqual(G.surfaceTickerAdmitted({ ticker: 'SPY', requested_ticker: 'SPY' }), false,
  'missing EdShell identity authority rejects');
global.window.EdShell = saved;
G.beginSurfaceRequest('SPY', gen);
assert.strictEqual(G.surfaceTickerAdmitted({ ticker: 'SPY', requested_ticker: 'SPY' }, 'QQQ', gen), false,
  'request-ticker mismatch rejects');
G.beginSurfaceRequest();
const bypassHost = makeHost();
G.renderSurface(bypassHost, withId(surface, 'SPY'));
assert.ok(bypassHost.innerHTML.includes('Gamma surface unavailable'),
  'direct render bypassing request context must reject');
assert.ok(!bypassHost.innerHTML.includes('data-strike='),
  'direct render bypassing request context must not paint cells');
installShell('SPY');

console.log('ed_gamma: all assertions passed');
