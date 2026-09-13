/* Ed Console — Options/Gamma "Flow" subview (D). PRESENTATION ONLY.
   Observes ONE explicitly-selected option contract's live microstructure via /api/order-flow/
   options-microstructure. The desired contract + control lifecycle are owned by EdStream (the ONE
   streaming-control writer) — this view never POSTs, never re-asserts, never constructs a symbol,
   never recomputes book/flow semantics.
   ONE canonical payload contract (app/options/order_flow/live_payload.py over engine.py):
     d.top_of_book / d.mid / d.microprice / d.spread_pts / d.depth / d.ages — book microstructure,
       classified by d.classification (engine keys, e.g. "top_of_book.bid", "mid", "depth.*.imbalance");
     d.flow.{tape_pressure_30s,tape_pressure_2m,tape_pressure_5m,cum_delta_proxy,cum_delta_slope,
       top_book_pressure} — classified by d.flow.classification; d.flow.native_aggressor_available;
     d.streaming_plane — producer binding / feed health (no classification concept).
   Every NATIVE/DERIVED/PROXY tag is the backend's own string, verbatim; a served value the backend
   did not classify is tagged UNKNOWN. Nothing is classified, inferred, or defaulted here.
   native_aggressor_available=false => no signed buys/sells are ever shown. */
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

  // Independent-review finding (2026-09-12, state-authority review), REPRODUCED
  // ("Flow resurrection"): a ticker switch calls EdStream.clearDesired() then load();
  // with `desired` now null the old code path returned before ever invalidating a fetch
  // still in flight for the PRIOR contract, so its late response could still land and
  // paint under the new ticker's label. Fixed by checking desired identity AT RESOLUTION
  // time (stillFlow) instead of a generation counter captured at issue time.
  //
  // ROOT-CAUSE FIX (2026-09-13, controlled reproduction confirmed): separately, `ed:refresh
  // {slow}` also fires on every streamed gamma_surface_seq push now, not just the 12s poll
  // tick; a naive per-call generation counter live-locks (never applies a response) once
  // pushes outrun the round trip -- see l1_sse_guards.js:makeCoalescedLoader, which every
  // gamma view module now uses for this same reason.
  // Independent-review finding (2026-09-13), REPRODUCED ("Flow can repaint ACTIVE from an
  // older observation after a newer subscription attempt has failed"): `stillFlow` checked
  // only DESIRED-CONTRACT identity, not the CURRENT control state. Scenario: contract A is
  // desired and accepted, a microstructure fetch for A starts; a reconnect/resubscribe
  // attempt for the SAME desired contract A then fails (controlState() -> 'failed'), but
  // the earlier in-flight fetch for A still resolves -- `desired` never changed, so the old
  // check let it through and painted ACTIVE/live data over what should now read FAILED.
  // Fixed: a response is only current if BOTH the desired contract AND the control state
  // it was fetched under are still what they were.
  function stillFlow(desired) {
    var ES = window.EdStream;
    return isFlow() && ((ES && ES.getDesired && ES.getDesired()) || null) === desired
      && ((ES && ES.controlState && ES.controlState()) || 'none') === 'accepted';
  }
  // Only the actual microstructure fetch is coalesced. The NONE/REQUESTED/FAILED branches are
  // synchronous, state-authority-visible renders (no network) and must run the INSTANT load()
  // is called -- never deferred behind a stale/hung fetch the coalescing loader is still
  // waiting on. Reproduced exactly this way (2026-09-13): a ticker switch clears `desired` and
  // must repaint Flow to NONE immediately even while a HUNG microstructure fetch for the OLD
  // contract is still in flight; wrapping this whole function in the coalescing loader made
  // that repaint wait for the hung fetch to settle (it never does), so the NONE state never
  // appeared and the eventual late response was the only thing left to (wrongly) render.
  //
  // ROUND 8 (2026-09-13): the loader is now keyed on the desired contract symbol, so a held
  // fetch for an ABANDONED contract is aborted immediately once a DIFFERENT contract becomes
  // desired, instead of blocking the new contract's own first observation.
  function loadImpl(desired, signal) {
    var h = host();
    if (!h || !stillFlow(desired)) return;
    h.setAttribute('aria-busy', 'true');
    return fetch('/api/order-flow/options-microstructure?contract=' + encodeURIComponent(desired), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillFlow(desired)) render(h, desired, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;   // superseded by a newer contract -- that load renders instead
        if (stillFlow(desired)) shell(h, desired, 'DEGRADED', 'no console serving options-microstructure', null);
      });
  }
  var _pendingDesired = null;
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(_pendingDesired, signal); })
    : { trigger: function () { loadImpl(_pendingDesired); }, reset: function () {} };
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
    _pendingDesired = desired;
    _loader.trigger(desired);
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

  // The backend's classification string for one canonical key, verbatim — or null when the
  // backend served no classification for it. Never defaulted, never inferred from the key.
  function classOf(map, key) { var v = map ? map[key] : null; return (typeof v === 'string' && v) ? v : null; }
  function bool3(v) { return v === true ? 'true' : (v === false ? 'false' : '—'); }

  function render(h, desired, d) {
    var plane = d.streaming_plane || {};
    var ss = subState(plane, desired);
    var tob = d.top_of_book || {};
    var depth = d.depth || {};
    var ages = d.ages || {};
    var flow = d.flow || {};                        // the ONE flow block (never flattened)
    var bookCls = d.classification || {};           // engine's book/microstructure classification
    var flowCls = flow.classification || {};        // live_payload's flow classification
    function dep(n, side) { var x = depth[String(n)] || {}; return x[side]; }
    function bk(k) { return classOf(bookCls, k); }
    function fk(k) { return classOf(flowCls, k); }
    // row = [label, displayed value, canonical key (data-k), backend classification | null]
    // The depth ladder is classified by the engine under its own wildcard keys ("depth.*.<leaf>").
    var rowsTob = [
      ['Bid', num(tob.bid), 'top_of_book.bid', bk('top_of_book.bid')],
      ['Ask', num(tob.ask), 'top_of_book.ask', bk('top_of_book.ask')],
      ['Bid size', int(tob.bid_size), 'top_of_book.bid_size', bk('top_of_book.bid_size')],
      ['Ask size', int(tob.ask_size), 'top_of_book.ask_size', bk('top_of_book.ask_size')],
    ];
    var rowsBook = [
      ['Mid', num(d.mid), 'mid', bk('mid')], ['Microprice', num(d.microprice), 'microprice', bk('microprice')],
      ['Spread (pts)', num(d.spread_pts), 'spread_pts', bk('spread_pts')],
      ['Depth 1 · imbalance', num(dep(1, 'imbalance'), 3), 'depth.1.imbalance', bk('depth.*.imbalance')],
      ['Depth 3 · imbalance', num(dep(3, 'imbalance'), 3), 'depth.3.imbalance', bk('depth.*.imbalance')],
      ['Depth 5 · imbalance', num(dep(5, 'imbalance'), 3), 'depth.5.imbalance', bk('depth.*.imbalance')],
      ['Bid total (5)', int(dep(5, 'bid_total')), 'depth.5.bid_total', bk('depth.*.bid_total')],
      ['Ask total (5)', int(dep(5, 'ask_total')), 'depth.5.ask_total', bk('depth.*.ask_total')],
    ];
    var rowsFlow = [
      ['Top-book pressure', num(flow.top_book_pressure, 3), 'flow.top_book_pressure', fk('top_book_pressure')],
      ['Tape pressure 30s', num(flow.tape_pressure_30s, 3), 'flow.tape_pressure_30s', fk('tape_pressure_30s')],
      ['Tape pressure 2m', num(flow.tape_pressure_2m, 3), 'flow.tape_pressure_2m', fk('tape_pressure_2m')],
      ['Tape pressure 5m', num(flow.tape_pressure_5m, 3), 'flow.tape_pressure_5m', fk('tape_pressure_5m')],
      ['Cum Δ (proxy)', num(flow.cum_delta_proxy, 1), 'flow.cum_delta_proxy', fk('cum_delta_proxy')],
      ['Cum Δ slope (proxy)', num(flow.cum_delta_slope, 3), 'flow.cum_delta_slope', fk('cum_delta_slope')],
    ];
    var dim = ss.label === 'ACTIVE' ? '' : ' fl-dim';   // not-active data recedes (never presented as live)
    // Book/quote ages are the payload's own `ages` block (engine-stamped, classified); feed health
    // is the streaming plane — a binding/health fact with no classification (key undefined = no tag).
    var fresh = [
      ['Book age', ages.book_age_sec != null ? Math.round(ages.book_age_sec) + 's' : '—', 'ages.book_age_sec', bk('ages.book_age_sec')],
      ['Quote age', ages.quote_age_sec != null ? Math.round(ages.quote_age_sec) + 's' : '—', 'ages.quote_age_sec', bk('ages.quote_age_sec')],
      ['Streaming', (plane.streaming_healthy === true ? 'healthy' : (plane.streaming_healthy === false ? 'unhealthy' : '—')) +
        (plane.streaming_staleness_ms != null ? ' · ' + Math.round(plane.streaming_staleness_ms) + 'ms' : ''),
        'streaming_plane.streaming_healthy', undefined],
    ];
    h.innerHTML = header(desired, ss) +
      '<div class="fl-grid">' +
      section('Top of book', rowsTob, '') +
      section('Book microstructure', rowsBook, dim) +
      section('Flow observations', rowsFlow, dim) +
      section('Freshness / health', fresh, '') +
      '</div>' +
      '<div class="fl-foot">signed aggressor classification NOT PROVEN — native_aggressor_available=' +
      bool3(flow.native_aggressor_available) + '; tape_classification=' + esc(flow.tape_classification || '—') +
      '; no signed buys/sells, CVD, or bull/bear verdict is canonical.</div>';
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
  // Classification tag: text is the backend string verbatim; the CSS hook is its leading token
  // (NATIVE/DERIVED/PROXY styled; anything else renders neutral). null => the backend served
  // no classification for a classified metric => UNKNOWN. undefined => not a classified metric.
  function tag(c) {
    if (c === undefined) return '';
    var text = c === null ? 'UNKNOWN' : c;
    var hook = (String(text).toLowerCase().match(/^[a-z0-9-]+/) || ['unknown'])[0];
    return '<span class="fl-tag ' + hook + '" data-cls="' + esc(text) + '">' + esc(text) + '</span>';
  }
  function section(title, rows, dim) {
    var h = '<div class="fl-sec' + dim + '"><div class="fl-sec-h">' + esc(title) + '</div>';
    rows.forEach(function (r) {
      h += '<div class="fl-row" data-k="' + esc(r[2]) + '"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) +
        '</span>' + tag(r[3]) + '</div>';
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
