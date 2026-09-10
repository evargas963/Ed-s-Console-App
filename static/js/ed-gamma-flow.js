/* Ed Console — Options/Gamma "Flow" subview (D). PRESENTATION ONLY.
   Observes ONE explicitly-selected option contract's live microstructure via /api/order-flow/
   options-microstructure. The desired contract + control lifecycle are owned by EdStream (the ONE
   streaming-control writer) — this view never POSTs, never re-asserts, never constructs a symbol,
   never recomputes book/flow semantics, and renders the server's own NATIVE/DERIVED/PROXY
   classification. native_aggressor_available=false => no signed buys/sells are ever shown. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function int(n) { return (n == null || isNaN(n)) ? '—' : String(Math.round(Number(n))); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isFlow() { var s = st(); return s.workspace === 'options' && s.subview === 'flow'; }
  function cpOf(symbol) { var s = String(symbol || ''); return s.length >= 13 ? (s.charAt(12) === 'P' ? 'Put' : (s.charAt(12) === 'C' ? 'Call' : '—')) : '—'; }

  function host() { return document.getElementById('flowBody'); }
  function set(label) { var el = document.getElementById('flTicker'); if (el) el.textContent = (st().ticker || 'SPY').replace('$', ''); }

  var _gen = 0;
  function load() {
    var h = host(); if (!h || !isFlow()) return;
    set();
    var ES = window.EdStream;
    var desired = (ES && ES.getDesired && ES.getDesired()) || null;
    var ctl = (ES && ES.controlState && ES.controlState()) || 'none';
    if (!desired) { return shell(h, null, 'NONE', 'Select a Call or Put contract in Chain.', null); }   // L: fail closed
    if (ctl === 'requested') { return shell(h, desired, 'REQUESTED', 'control request sent — awaiting acknowledgement', null); }
    if (ctl === 'failed') { return shell(h, desired, 'FAILED', 'control request was not accepted — no observation started', null); }
    // I: only an ACCEPTED control request begins normal microstructure observation.
    var g = ++_gen;
    h.setAttribute('aria-busy', 'true');
    fetch('/api/order-flow/options-microstructure?contract=' + encodeURIComponent(desired), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _gen) render(h, desired, d); })
      .catch(function () { if (g === _gen) shell(h, desired, 'DEGRADED', 'no console serving options-microstructure', null); });
  }

  // subscription state from the CANONICAL producer truth (EdStream.status over the payload's plane).
  function subState(plane, desired) {
    var ES = window.EdStream;
    var s = (ES && ES.status) ? ES.status(plane, desired) : { active: false };
    if (s.active) return { label: 'ACTIVE', cls: 'live' };
    plane = plane || {};
    var pl1 = plane.producer_l1_contract, pbk = plane.producer_book_contract;
    // H: MOVED = the slot is clearly held by ANOTHER single contract (both producers on the same
    // non-desired contract). A partial state (only one service matches) is PENDING, not MOVED.
    if (pl1 && pbk && pl1 === pbk && pl1 !== desired) return { label: 'MOVED', cls: 'stale' };
    return { label: 'PENDING', cls: 'warn' };                 // accepted, awaiting/partial producer binding
  }

  function render(h, desired, d) {
    var plane = d.streaming_plane || {};
    var ss = subState(plane, desired);
    var tob = d.top_of_book || {};
    var depth = d.depth || {};
    function dep(n, side) { var x = depth[String(n)] || {}; return x[side]; }
    // sections; every value is served/classified by the backend — "—" where canonical value absent
    var rowsN = [
      ['Bid', num(tob.bid), 'NATIVE'], ['Ask', num(tob.ask), 'NATIVE'],
      ['Bid size', int(tob.bid_size), 'NATIVE'], ['Ask size', int(tob.ask_size), 'NATIVE'],
    ];
    var rowsD = [
      ['Mid', num(d.mid), 'DERIVED'], ['Microprice', num(d.microprice), 'DERIVED'],
      ['Spread (pts)', num(d.spread_pts), 'DERIVED'],
      ['Depth 1 · imbalance', num(dep(1, 'imbalance'), 3), 'DERIVED'],
      ['Depth 3 · imbalance', num(dep(3, 'imbalance'), 3), 'DERIVED'],
      ['Depth 5 · imbalance', num(dep(5, 'imbalance'), 3), 'DERIVED'],
      ['Bid total (5)', int(dep(5, 'bid_total')), 'DERIVED'], ['Ask total (5)', int(dep(5, 'ask_total')), 'DERIVED'],
      ['Top-book pressure', num(d.top_book_pressure, 3), 'DERIVED'],
    ];
    var rowsP = [
      ['Tape pressure 30s', num(d.tape_pressure_30s, 3), 'PROXY'], ['Tape pressure 2m', num(d.tape_pressure_2m, 3), 'PROXY'],
      ['Tape pressure 5m', num(d.tape_pressure_5m, 3), 'PROXY'], ['Cum Δ (proxy)', num(d.cum_delta_proxy, 1), 'PROXY'],
      ['Cum Δ slope (proxy)', num(d.cum_delta_slope, 3), 'PROXY'],
    ];
    var dim = ss.label === 'ACTIVE' ? '' : ' fl-dim';   // not-active data recedes (never presented as live)
    var fresh = [
      ['Book age', plane.book_age_sec != null ? Math.round(plane.book_age_sec) + 's' : '—'],
      ['Quote age', plane.quote_age_sec != null ? Math.round(plane.quote_age_sec) + 's' : '—'],
      ['Streaming', plane.streaming_healthy === true ? 'healthy' : (plane.streaming_healthy === false ? 'unhealthy' : '—') +
        (plane.streaming_staleness_ms != null ? ' · ' + Math.round(plane.streaming_staleness_ms) + 'ms' : '')],
    ];
    h.innerHTML = header(desired, ss) +
      '<div class="fl-grid">' +
      section('Top of book', 'NATIVE', rowsN, '') +
      section('Book microstructure', 'DERIVED', rowsD, dim) +
      section('Flow observations', 'PROXY', rowsP, dim) +
      section('Freshness / health', '', fresh.map(function (r) { return [r[0], r[1], '']; }), '') +
      '</div>' +
      '<div class="fl-foot">signed aggressor classification NOT PROVEN — native_aggressor_available=' +
      (d.native_aggressor_available === true ? 'true' : 'false') + '; no signed buys/sells, CVD, or bull/bear verdict is canonical.</div>';
  }

  function header(desired, ss) {
    var strike = st().selStrike, expiry = st().selExpiry;
    return '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Selected contract</span>' +
      '<span class="fl-sym">' + esc(desired || '—') + '</span>' +
      '<span class="fl-meta">' + cpOf(desired) + (strike != null ? ' · ' + strike : '') + (expiry ? ' · ' + esc(expiry) : '') + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Subscription</span><span class="fl-badge ' + ss.cls + '">' + ss.label + '</span></div></div>';
  }
  function shell(h, desired, badge, msg, x) {
    var cls = badge === 'NONE' ? 'warn' : (badge === 'FAILED' || badge === 'DEGRADED' ? 'stale' : 'warn');
    h.innerHTML = '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Selected contract</span>' +
      '<span class="fl-sym">' + esc(desired || '—') + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Subscription</span><span class="fl-badge ' + cls + '">' + esc(badge) + '</span></div></div>' +
      '<div class="placeholder"><div class="sm">' + esc(msg) + '</div></div>';
  }
  function section(title, tag, rows, dim) {
    var h = '<div class="fl-sec' + dim + '"><div class="fl-sec-h">' + esc(title) +
      (tag ? ' <span class="fl-tag ' + tag.toLowerCase() + '">' + tag + '</span>' : '') + '</div>';
    rows.forEach(function (r) {
      h += '<div class="fl-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) +
        '</span>' + (r[2] ? '<span class="fl-tag ' + r[2].toLowerCase() + '">' + r[2] + '</span>' : '') + '</div>';
    });
    return h + '</div>';
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);           // fires on subview change too
    document.addEventListener('ed:contract', load);       // an explicit Chain selection
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    // E: a ticker or expiry-context change clears THIS tab's old contract intent LOCALLY (no POST,
    // no fight for the slot). A fresh explicit selection is then required to observe again.
    document.addEventListener('ed:ticker', function () { if (window.EdStream && window.EdStream.clearDesired) window.EdStream.clearDesired(); load(); });
    document.addEventListener('ed:expiry', function () { if (window.EdStream && window.EdStream.clearDesired) window.EdStream.clearDesired(); load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
