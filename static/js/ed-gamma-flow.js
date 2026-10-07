/* Ed Console — Options/Gamma "Flow" subview (D). PRESENTATION ONLY.
   Observes ONE explicitly-selected option contract's live microstructure via /api/order-flow/
   options-microstructure. The selection is this tab's own (window.EdFlow, set by a Chain click);
   which contracts stream is the daemon's option rule, never the page's — this view never POSTs,
   never constructs a symbol, never recomputes book/flow semantics.
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

  function host() { return document.getElementById('flowBody'); }

  // this tab's selected contract (a Chain click), cleared by a ticker or expiry change
  var _selected = null;
  window.EdFlow = {
    selected: function () { return _selected; },
    select: function (symbol) { _selected = symbol; document.dispatchEvent(new CustomEvent('ed:contract', { detail: { contract: symbol } })); },
  };

  // a response is current only while Flow is on screen and its contract is still the selected one
  function stillFlow(desired) { return isFlow() && _selected === desired; }
  // Only the microstructure fetch is coalesced, keyed on the contract: the NONE render runs at
  // once, and a held fetch for a contract no longer selected is aborted.
  function loadImpl(desired, signal) {
    var h = host();
    if (!h || !stillFlow(desired)) return;
    return fetch('/api/order-flow/options-microstructure?contract=' + encodeURIComponent(desired), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillFlow(desired)) render(h, desired, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;   // superseded by a newer contract -- that load renders instead
        if (stillFlow(desired)) shell(h, desired, 'DEGRADED', 'no console serving options-microstructure', null);
      });
  }
  var _pendingDesired = null;
  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(_pendingDesired, signal); });
  function load() {
    var h = host(); if (!h || !isFlow()) return;
    if (!_selected) { return shell(h, null, 'NONE', 'Select a Call or Put contract in Chain.', null); }
    _pendingDesired = _selected;
    _loader.trigger(_selected);
  }

  // the queried contract's subscription, served (streaming_plane.subscription_state): the
  // daemon's option rule streams it (ACTIVE), or it does not (the served words)
  function subState(plane) {
    var s = (plane || {}).subscription_state;
    if (s === 'SUBSCRIBED') return { label: 'ACTIVE', cls: 'live' };
    return { label: s || '—', cls: 'stale' };
  }

  // The backend's classification string for one canonical key, verbatim — or null when the
  // backend served no classification for it. Never defaulted, never inferred from the key.
  function classOf(map, key) { var v = map ? map[key] : null; return (typeof v === 'string' && v) ? v : null; }
  function bool3(v) { return v === true ? 'true' : (v === false ? 'false' : '—'); }

  function render(h, desired, d) {
    var plane = d.streaming_plane || {};
    var ss = subState(plane);
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
      ['Bid', d.top_outage || num(tob.bid), 'top_of_book.bid', bk('top_of_book.bid')],
      ['Ask', d.top_outage || num(tob.ask), 'top_of_book.ask', bk('top_of_book.ask')],
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
      ['Cum Δ (proxy)', num(flow.cum_delta_proxy, 1) + (flow.cum_delta_window ? ' · ' + flow.cum_delta_window : ''),
        'flow.cum_delta_proxy', fk('cum_delta_proxy')],
      ['Cum Δ slope (proxy)', num(flow.cum_delta_slope, 3), 'flow.cum_delta_slope', fk('cum_delta_slope')],
    ];
    var fh = plane.feed_health || {};   // served: the selected contract's three feeds
    function svc(x) { return x ? (x.state || '—') + (x.age_sec != null ? ' · ' + num(x.age_sec, 1) + 's' : '') : '—'; }
    var dim = ss.label === 'ACTIVE' ? '' : ' fl-dim';   // not-active data recedes (never presented as live)
    // Book/quote ages are the payload's own `ages` block (engine-stamped, classified); feed health
    // is the streaming plane — a binding/health fact with no classification (key undefined = no tag).
    var fresh = [
      ['Book age', ages.book_age_sec != null ? Math.round(ages.book_age_sec) + 's' : '—', 'ages.book_age_sec', bk('ages.book_age_sec')],
      ['Quote age', ages.quote_age_sec != null ? Math.round(ages.quote_age_sec) + 's' : '—', 'ages.quote_age_sec', bk('ages.quote_age_sec')],
      ['Replay', fh.replay || '—', 'streaming_plane.feed_health.replay', undefined],
      ['L1 upstream', svc(fh.l1), 'streaming_plane.feed_health.l1', undefined],
      ['Book upstream', svc(fh.book), 'streaming_plane.feed_health.book', undefined],
    ];
    h.innerHTML = header(desired, ss, d && d.put_call) +
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

  function header(desired, ss, putCall) {   // putCall: Schwab's CONTRACT_TYPE, served
    var strike = st().selStrike, expiry = st().selExpiry;
    return '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Selected contract</span>' +
      '<span class="fl-sym">' + esc(desired || '—') + '</span>' +
      '<span class="fl-meta">' + (putCall === 'CALL' ? 'Call' : putCall === 'PUT' ? 'Put' : '—') + (strike != null ? ' · ' + strike : '') + (expiry ? ' · ' + esc(expiry) : '') + '</span></div>' +
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
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'levels' || e.detail.kind === 'flow') load(); });
    // a ticker or expiry change clears the selection; a fresh Chain click observes again
    document.addEventListener('ed:ticker', function () { _selected = null; load(); });
    document.addEventListener('ed:expiry', function () { _selected = null; load(); });
    // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
    // deferred ed:ticker/ed:view dispatch -- see that file's init() comment.
  }
})();
