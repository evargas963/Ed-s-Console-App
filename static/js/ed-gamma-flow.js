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

  // the selected contract (a Chain click; in the shell's view), cleared by a ticker or expiry
  // change; the daemon streams it on both option services on top of its rule (POST /api/flow-contract)
  function setSelected(symbol) {
    window.EdShell.setInput('contract', symbol);
    fetch('/api/flow-contract', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contract: symbol }) });
    none();
  }
  window.EdFlow = {
    selected: function () { return st().contract; },
    select: setSelected,
  };

  // the selected contract's microstructure as the console pushes it (only ever the current contract's)
  var _flow = null;                  // the console's reads of the contract, drawn again on each Schwab message
  window.EdShell.onPanel('flow', function (a) {
    _flow = null;                    // a new contract's reads on their way: never the old contract's
    var h = host(); if (!h || a.waiting) return;
    if (!a.ok) { shell(h, st().contract, 'DEGRADED', '/api/order-flow/options-microstructure answered HTTP ' + a.status, null); return; }
    _flow = a.body;
    render(h, st().contract, a.body);
  });
  // LEVELONE_OPTIONS (Change) and OPTIONS_BOOK (Whole) for the selected contract, straight from the daemon
  var _optBook = {};
  window.addEventListener('ed:schwab', function (e) {
    var m = e.detail; if (!m || (m.service !== 'LEVELONE_OPTIONS' && m.service !== 'OPTIONS_BOOK')) return;
    if (m.service === 'OPTIONS_BOOK') _optBook[m.key] = m;
    var h = host();
    if (!h || !isFlow() || m.key !== st().contract) return;
    if (_flow) render(h, st().contract, _flow); else renderSchwab(h, st().contract);
  });
  // a Schwab book's side as rows: each level's price × total size, as sent
  // (the daemon's levels: each price and total size as Schwab sent them, engine.book_levels)
  function bookRows(side, label) {
    return side.map(function (lv, i) { return [label + ' ' + (i + 1), num(lv[0]) + ' × ' + int(lv[1]), 'OPTIONS_BOOK', undefined]; });
  }
  // no contract selected: nothing to observe
  // (a contract selected and the console's reads not yet in: the daemon's values for it, now)
  function none() {
    var h = host();
    if (!h || !isFlow()) return;
    if (!st().contract) shell(h, null, 'NONE', 'Select a Call or Put contract in Chain.', null);
    else if (!_flow) renderSchwab(h, st().contract);
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

  // The contract's Schwab values, straight from the daemon, whether or not the console has
  // answered for it yet: its LEVELONE_OPTIONS top of book and OPTIONS_BOOK, each with the daemon's verdict
  function schwabSections(desired) {
    var f = function (name) { return window.EdShell.schwabNumber(desired, name); };
    var l1v = window.EdShell.feedVerdict(desired, 'LEVELONE_OPTIONS');
    var topLive = !!l1v && l1v.live === true;      // the daemon's verdict; not reported: not live
    // Schwab's last top of book; with its feed down, marked not live with the daemon's reason
    var rowsTob = [
      ['Bid', num(f('BID_PRICE')), 'top_of_book.bid', undefined],
      ['Ask', num(f('ASK_PRICE')), 'top_of_book.ask', undefined],
      ['Bid size', int(f('BID_SIZE')), 'top_of_book.bid_size', undefined],
      ['Ask size', int(f('ASK_SIZE')), 'top_of_book.ask_size', undefined],
    ].concat(!topLive ? [['Top of book', 'NOT LIVE' + (l1v && l1v.outage ? ' · ' + l1v.outage : ''), 'top_outage', undefined]] : []);
    var ob = _optBook[desired], obv = window.EdShell.feedVerdict(desired, 'OPTIONS_BOOK');
    var rowsOb = !ob ? [['Book', '-', 'OPTIONS_BOOK', undefined]]
      : [['Book time', ob.time_ct == null ? '-' : ob.time_ct, 'OPTIONS_BOOK', undefined]]
        .concat(!(obv && obv.live) ? [['Book', 'NOT LIVE' + (obv && obv.outage ? ' · ' + obv.outage : ''), 'OPTIONS_BOOK', undefined]] : [])
        .concat(bookRows(ob.levels.asks, 'Ask'), bookRows(ob.levels.bids, 'Bid'));
    return section('Top of book · Schwab LEVELONE_OPTIONS', rowsTob, '') + section('Book · Schwab OPTIONS_BOOK, as sent', rowsOb, '');
  }
  // before the console's reads of the contract land: the daemon's values, the rest '-'
  function renderSchwab(h, desired) {
    h.innerHTML = header(desired, subState(null), null) + '<div class="fl-grid">' + schwabSections(desired) + '</div>';
  }

  function render(h, desired, d) {
    var plane = d.streaming_plane || {};
    var ss = subState(plane);
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
    var pricedAt = d.top_of_book;                  // the top of book the console priced these at (the engine's input)
    var rowsBook = [
      ['Priced at', pricedAt ? num(pricedAt.bid) + ' × ' + num(pricedAt.ask) : '-', 'top_of_book', undefined],
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
    var dim = ss.label === 'ACTIVE' ? '' : ' fl-dim';   // not-active data recedes (never presented as live)
    // Book/quote ages are the payload's own `ages` block (engine-stamped, classified); each feed's
    // live verdict is the daemon's, in the Top of book and Book sections
    var fresh = [
      ['Book age', d.as_of && d.as_of.book != null ? { pre: '', ageOf: 'book' } : '—', 'as_of.book', bk('as_of.book')],
      ['Quote age', d.as_of && d.as_of.quote != null ? { pre: '', ageOf: 'quote' } : '—', 'as_of.quote', bk('as_of.quote')],
    ];
    h.innerHTML = header(desired, ss, d && d.put_call) +
      '<div class="fl-grid">' +
      schwabSections(desired) +
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
      var v = r[1] && r[1].ageOf ? esc(r[1].pre) + window.EdShell.ageSpan(r[1].ageOf) : esc(r[1]);   // a served age
      h += '<div class="fl-row" data-k="' + esc(r[2]) + '"><span class="k">' + esc(r[0]) + '</span><span class="v">' + v +
        '</span>' + tag(r[3]) + '</div>';
    });
    return h + '</div>';
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', none);
    // a ticker or expiry change clears the selection; a fresh Chain click observes again
    // a page that selected nothing releases nothing (another tab's selection stands)
    function clearSelected() { if (st().contract) setSelected(null); else none(); }
    document.addEventListener('ed:ticker', clearSelected);
    document.addEventListener('ed:expiry', clearSelected);
  }
})();
