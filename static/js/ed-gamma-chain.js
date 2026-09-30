/* Ed Console — Options/Gamma "Chain" subview (D). PRESENTATION ONLY.
   Renders the full vendor chain ladder from /api/chain (strike_range=ALL, one expiry) — calls left,
   puts right, strike centre. Every field is served AS-IS from the vendor; this computes nothing and
   discloses the chain scope (complete / mismatch / fallback) honestly. The expiry is the workspace
   expiry dropdown (canonical /api/expiries); the ticker is the one selected-symbol state. */
(function () {
  'use strict';

  function px(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isChain() { var s = st(); return s.workspace === 'options' && s.subview === 'chain'; }

  function setSrc(d) {
    var el = document.getElementById('chSrc'); if (!el) return;
    el.innerHTML = window.EdShell.chainBadge(d, 'vendor · ');
  }

  // auto-scroll to spot only the first time a ticker+expiry is rendered
  var _lastScrollContext = null;

  function curExpiry() { return (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) || null; }
  function stillChain(tk, exp) { return isChain() && (st().ticker || '') === tk && curExpiry() === exp; }
  // Independent-review finding (2026-09-13), REPRODUCED: A -> B -> A can still let the FIRST
  // A request's response paint over the THIRD (fresh) A request's response. `stillChain`
  // proves the identity (ticker, expiry) still matches NOW, but two different requests issued
  // at different times for the identical identity are indistinguishable to it -- whichever
  // resolves LAST wins, not whichever was issued last. The loader's own AbortController
  // SHOULD prevent the stale first request from ever resolving normally, but does not
  // guarantee it (an abort raced against an already-buffered response can still resolve).
  // Fixed with an explicit monotonic request sequence, independent of AbortController
  // reliability: only the response whose sequence number is still the LATEST ISSUED one may
  // paint, so an old, superseded request for the SAME identity can never win a race against a
  // newer one for that identity, not merely against a DIFFERENT identity.
  var _reqSeq = 0;
  // ROUND 8 (2026-09-13): keyed on ticker+expiry so a held/slow fetch for an ABANDONED
  // context is aborted immediately once a different one is selected, instead of blocking it.
  function loadImpl(tk, exp, signal) {
    var host = document.getElementById('chainBody');
    if (!host || !stillChain(tk, exp)) return;
    var mySeq = ++_reqSeq;
    function current() { return mySeq === _reqSeq && stillChain(tk, exp); }
    host.setAttribute('aria-busy', 'true');
    return fetch('/api/chain?ticker=' + encodeURIComponent(tk) + (exp ? '&expiry=' + encodeURIComponent(exp) : ''), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (current()) render(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (current()) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/chain</div></div>';
      });
  }
  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(st().ticker || '', curExpiry(), signal); });
  function load() { _loader.trigger((st().ticker || '') + '|' + (curExpiry() || '')); }

  function render(host, d) {
    setSrc(d);
    var rows = (d && d.ladder) || [];   // served: strikes high to low, one row per listed contract
    if (!rows.length) { host.innerHTML = '<div class="placeholder"><div class="sm">' + esc(window.EdShell.chainEmptyText(d)) + '</div></div>'; return; }
    var dup = d.has_duplicate_contracts === true;   // served
    // null/'' spot is ABSENT: Number(null) is 0, which drew 'spot 0.00' (audit P0, 2026-09-23)
    var spot = (d.spot == null || d.spot === '') ? NaN : Number(d.spot);
    var desired = window.EdStream.getDesired();
    // B: /api/chain is a COMPLETE SINGLE-EXPIRY surface — say so, name the exact expiry returned, and
    // flag when the workspace filter was null (the server chose the default expiry).
    var filterNull = !(window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry());
    var head = '<div class="chn-head"><span>SINGLE EXPIRY · ' + esc(d.expiry || '—') +
      (filterNull ? ' <span class="chn-default">(server default)</span>' : '') + ' · ' + esc(d.n_strikes) + ' strikes' +
      (dup ? ' · <span class="chn-dup">duplicate contracts retained</span>' : '') + '</span>' +
      '<span>spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') + (d.spot_source ? ' · ' + esc(d.spot_source) : '') + '</span></div>';
    function cell(c, k, dg) { var v = c ? c[k] : null; return (v == null) ? '—' : (typeof v === 'number' ? v.toFixed(dg == null ? 2 : dg) : esc(v)); }
    function sym(c) { return c && c.symbol ? String(c.symbol) : ''; }
    function selAttr(c) { var s = sym(c); return s ? (' data-sym="' + esc(s) + '"' + (s === desired ? ' data-selc="1"' : '')) : ''; }
    // Independent-review finding (2026-09-13), REPRODUCED then narrowed to a two-sticky-row
    // defect, then a further review confirmed the operator kept seeing a real, moving visual
    // fault on genuine trackpad scrolling that neither `position:sticky` fix (a compositing-
    // layer promotion, then overscroll containment) could be proven to address, because
    // neither could be proven to reproduce the exact mechanism. Root-caused by removing
    // `position:sticky` entirely: the header table is now a FROZEN (non-scrolling) sibling of
    // a separate, genuinely scrollable `.chn-scroll` div holding only the body table (see
    // console.html's #chainBody/.chn-scroll rules) -- a standard "frozen header" layout with
    // no sticky positioning anywhere for a compositor or scroll-chaining bug to intermittently
    // mishandle. A shared fixed-percentage <colgroup> on both tables keeps every column
    // pixel-aligned between them despite being unrelated table layouts.
    var COLGROUP = '<colgroup>' + new Array(8).join('<col style="width:6.25%">') + '<col style="width:12.5%">' +
      new Array(8).join('<col style="width:6.25%">') + '</colgroup>';
    var h = '<table class="chn chn-headtbl">' + COLGROUP + '<thead><tr>' +
      '<th colspan="7" class="cflag" style="text-align:center">Calls</th><th class="mid">Strike</th>' +
      '<th colspan="7" class="pflag" style="text-align:center">Puts</th></tr>' +
      '<tr><th>OI</th><th>Vol</th><th>IV%</th><th>Δ</th><th>Γ</th><th>Bid</th><th>Ask</th><th class="mid"></th>' +
      '<th>Bid</th><th>Ask</th><th>Γ</th><th>Δ</th><th>IV%</th><th>Vol</th><th>OI</th></tr></thead></table>' +
      '<div class="chn-scroll" id="chainScroll">' + head +
      '<table class="chn chn-bodytbl">' + COLGROUP + '<tbody>';
    var CALL = [['openInterest', 0], ['totalVolume', 0], ['volatility', 1], ['delta', 3], ['gamma', 4], ['bid', 2], ['ask', 2]];
    var PUT = [['bid', 2], ['ask', 2], ['gamma', 4], ['delta', 3], ['volatility', 1], ['totalVolume', 0], ['openInterest', 0]];
    function side(c, cls, itm, cols) {   // itm: served per row (strike vs the live spot)
      var klass = cls + (c && sym(c) === desired ? ' chn-selc' : '') + (itm === true ? ' chn-itm' : '');
      return cols.map(function (f, j) {
        return '<td class="' + klass + '"' + (j === 0 ? selAttr(c) : '') + '>' + cell(c, f[0], f[1]) + '</td>';
      }).join('');
    }
    rows.forEach(function (r) {
      var c = r.call, p = r.put, k = r.strike;
      h += '<tr' + (r.spot ? ' class="spot"' : '') + ' data-strike="' + k + '"' +
        (c ? ' data-csym="' + esc(sym(c)) + '"' : '') + (p ? ' data-psym="' + esc(sym(p)) + '"' : '') + '>' +
        side(c, 'chn-call', r.call_itm, CALL) +
        '<td class="k">' + (r.first ? px(k, k % 1 ? 2 : 0) : '·') + '</td>' +
        side(p, 'chn-put', r.put_itm, PUT) + '</tr>';
    });
    h += '</tbody></table></div>';   // close .chn-scroll
    // Independent-review finding (2026-09-13), REPRODUCED by the frozen-header redesign's own
    // new regression test: `.chn-scroll` (the actual scrolling element) is a NEW DOM node on
    // every render now, unlike the old design where #chainBody itself never got replaced and
    // so kept its own scrollTop across re-renders for free. Captured here, before the old
    // `.chn-scroll` is torn out by the innerHTML replacement below, and restored onto the new
    // one afterward -- same "leave the operator's own scroll position alone on a routine
    // refresh" contract as before, just made explicit now that nothing does it automatically.
    var oldScroll = host.querySelector('.chn-scroll');
    var savedScrollTop = oldScroll ? oldScroll.scrollTop : 0;
    host.innerHTML = h;
    // C: the CALL side selects the exact CALL vendor symbol, the PUT side the exact PUT symbol; the
    // centre Strike selects ONLY the shared strike. The symbol is the vendor's own, verbatim — never
    // reconstructed. An explicit contract click routes through the ONE control owner (EdStream).
    host.querySelectorAll('tr[data-strike]').forEach(function (tr) {
      tr.addEventListener('click', function (e) {
        var k = Number(tr.getAttribute('data-strike'));
        var cell = e.target.closest ? e.target.closest('td') : null;
        if (cell && cell.classList.contains('chn-call') && tr.getAttribute('data-csym')) return selectContract(tr.getAttribute('data-csym'), k, d.expiry);
        if (cell && cell.classList.contains('chn-put') && tr.getAttribute('data-psym')) return selectContract(tr.getAttribute('data-psym'), k, d.expiry);
        if (window.EdShell) window.EdShell.setStrike(k, d.expiry);   // centre strike -> shared strike only
      });
    });
    var context = (st().ticker || '') + '|' + (d.expiry || '');
    var isNewContext = context !== _lastScrollContext;
    _lastScrollContext = context;
    if (isNewContext) {
      var sr = host.querySelector('tr.spot'); if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
    } else {
      var newScroll = host.querySelector('.chn-scroll');
      if (newScroll) newScroll.scrollTop = savedScrollTop;
    }
  }

  function selectContract(symbol, strike, expiry) {
    if (window.EdShell) window.EdShell.setStrike(strike, expiry);      // exact strike + expiry = shared context
    var det = { contract: symbol, strike: strike, expiry: expiry };
    // ONE explicit control request; re-notify once it RESOLVES so Flow moves off REQUESTED to
    // ACTIVE/PENDING/FAILED per the canonical ACK — a single request, not a re-POST.
    window.EdStream.setActiveContract(symbol).then(function () {
      document.dispatchEvent(new CustomEvent('ed:contract', { detail: det })); });
    var host = document.getElementById('chainBody'); if (host) {
      host.querySelectorAll('.chn-selc').forEach(function (n) { n.classList.remove('chn-selc'); });
      host.querySelectorAll('[data-sym="' + (window.CSS && CSS.escape ? CSS.escape(symbol) : symbol) + '"]').forEach(function (n) { n.classList.add('chn-selc'); });
    }
    document.dispatchEvent(new CustomEvent('ed:contract', { detail: det }));   // immediate: shows REQUESTED
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);       // fires on subview change too
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:expiry', load);
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'chain' && isChain()) load(); });
  }
})();
