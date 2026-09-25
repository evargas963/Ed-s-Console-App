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

  var SCOPE = {
    complete_single_expiry: { t: 'complete (ALL)', live: true },
    unavailable: { t: 'unavailable', stale: true },
  };
  function setSrc(d) {
    var el = document.getElementById('chSrc'); if (!el) return;
    var sc = d && d.scope, kind = sc && sc.kind;
    if (!kind) { el.innerHTML = ''; return; }
    var m = SCOPE[kind] || { t: kind };
    el.innerHTML = (window.EdShell && window.EdShell.asOfBadge)
      ? window.EdShell.asOfBadge({ label: 'vendor · ' + m.t,
          live: !!m.live, ref: !!m.ref, stale: !!m.stale, title: 'chain scope: ' + kind + (sc.reason ? ' — ' + sc.reason : '') }) : '';
  }

  // Independent-review finding (2026-09-13), REPRODUCED: render()'s scrollIntoView ran
  // UNCONDITIONALLY on every resolved load() -- including every routine ~12s ed:refresh{slow}
  // tick and every streamed gamma_surface_seq push, not just a genuine new ticker/expiry
  // context -- forcibly recentering on the spot row and discarding any manual scroll position
  // the operator had set in a long chain ladder. Fixed by only auto-scrolling the first time a
  // given ticker+expiry context is rendered; a routine data refresh of an already-rendered
  // context leaves the operator's own scroll position alone.
  var _lastScrollContext = null;

  function curExpiry() { return (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) || null; }
  // Coalesced load (see l1_sse_guards.js:makeCoalescedLoader) -- `ed:refresh{slow}` also
  // fires on every streamed gamma_surface_seq push, not just the 12s poll tick; a naive
  // per-call generation counter live-locks once pushes outrun the round trip. Context
  // invalidation (ticker or expiry filter changed mid-flight) is `stillChain()`, checked at
  // resolution time.
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
    var tkEl = document.getElementById('chTicker'); if (tkEl) tkEl.textContent = tk.replace('$', '');
    host.setAttribute('aria-busy', 'true');
    return fetch('/api/chain?ticker=' + encodeURIComponent(tk) + (exp ? '&expiry=' + encodeURIComponent(exp) : ''), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (current()) render(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (current()) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/chain</div></div>';
      });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(st().ticker || '', curExpiry(), signal); })
    : { trigger: function () { loadImpl(st().ticker || '', curExpiry()); }, reset: function () {} };
  function load() { _loader.trigger((st().ticker || '') + '|' + (curExpiry() || '')); }

  function render(host, d) {
    setSrc(d);
    var cs = (d && d.contracts) || [];
    if (!cs.length) { host.innerHTML = '<div class="placeholder"><div class="sm">' + esc(window.EdShell.chainEmptyText(d)) + '</div></div>'; return; }
    // D: preserve EVERY exact vendor contract identity — group by strike into ARRAYS per side, so a
    // second contract that shares (strike, side) is never silently overwritten. One display row per
    // duplicate index; a "dup" marker discloses when the single-expiry surface is not strike-unique.
    var byK = {}, dup = false;
    cs.forEach(function (c) {
      var k = Number(c.strikePrice); if (!isFinite(k)) return;
      byK[k] = byK[k] || { c: [], p: [] };
      var side = (c.putCall || '').toUpperCase() === 'PUT' ? 'p' : 'c';
      byK[k][side].push(c);
      if (byK[k][side].length > 1) dup = true;
    });
    var strikes = Object.keys(byK).map(Number).sort(function (a, b) { return b - a; });
    // null/'' spot is ABSENT: Number(null) is 0, which drew 'spot 0.00' (audit P0, 2026-09-23)
    var spot = (d.spot == null || d.spot === '') ? NaN : Number(d.spot);
    var spotK = strikes.reduce(function (best, k) { return (best == null || Math.abs(k - spot) < Math.abs(best - spot)) ? k : best; }, null);
    var desired = (window.EdStream && window.EdStream.getDesired && window.EdStream.getDesired()) || null;
    // B: /api/chain is a COMPLETE SINGLE-EXPIRY surface — say so, name the exact expiry returned, and
    // flag when the workspace filter was null (the server chose the default expiry).
    var filterNull = !(window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry());
    var head = '<div class="chn-head"><span>SINGLE EXPIRY · ' + esc(d.expiry || '—') +
      (filterNull ? ' <span class="chn-default">(server default)</span>' : '') + ' · ' + strikes.length + ' strikes' +
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
    var COLGROUP = '<colgroup><col style="width:10%"><col style="width:10%"><col style="width:10%"><col style="width:10%">' +
      '<col style="width:20%"><col style="width:10%"><col style="width:10%"><col style="width:10%"><col style="width:10%"></colgroup>';
    var h = '<table class="chn chn-headtbl">' + COLGROUP + '<thead><tr>' +
      '<th colspan="4" class="cflag" style="text-align:center">Calls</th><th class="mid">Strike</th>' +
      '<th colspan="4" class="pflag" style="text-align:center">Puts</th></tr>' +
      '<tr><th>OI</th><th>Vol</th><th>IV%</th><th>Δ</th><th class="mid"></th><th>Δ</th><th>IV%</th><th>Vol</th><th>OI</th></tr></thead></table>' +
      '<div class="chn-scroll" id="chainScroll">' + head +
      '<table class="chn chn-bodytbl">' + COLGROUP + '<tbody>';
    strikes.forEach(function (k) {
      var g = byK[k], n = Math.max(g.c.length, g.p.length);
      for (var i = 0; i < n; i++) {
        var c = g.c[i] || null, p = g.p[i] || null;
        var cSel = (c && sym(c) === desired) ? ' chn-selc' : '', pSel = (p && sym(p) === desired) ? ' chn-selc' : '';
        h += '<tr' + (k === spotK && i === 0 ? ' class="spot"' : '') + ' data-strike="' + k + '"' +
          (c ? ' data-csym="' + esc(sym(c)) + '"' : '') + (p ? ' data-psym="' + esc(sym(p)) + '"' : '') + '>' +
          '<td class="chn-call' + cSel + '"' + selAttr(c) + '>' + cell(c, 'openInterest', 0) + '</td>' +
          '<td class="chn-call' + cSel + '">' + cell(c, 'totalVolume', 0) + '</td>' +
          '<td class="chn-call' + cSel + '">' + cell(c, 'volatility', 1) + '</td>' +
          '<td class="chn-call' + cSel + '">' + cell(c, 'delta', 3) + '</td>' +
          '<td class="k">' + (i === 0 ? px(k, k % 1 ? 2 : 0) : '·') + '</td>' +
          '<td class="chn-put' + pSel + '">' + cell(p, 'delta', 3) + '</td>' +
          '<td class="chn-put' + pSel + '">' + cell(p, 'volatility', 1) + '</td>' +
          '<td class="chn-put' + pSel + '">' + cell(p, 'totalVolume', 0) + '</td>' +
          '<td class="chn-put' + pSel + '">' + cell(p, 'openInterest', 0) + '</td></tr>';
      }
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
    if (window.EdStream && window.EdStream.setActiveContract) {
      var pr = window.EdStream.setActiveContract(symbol);              // ONE explicit control request
      // re-notify once the control request RESOLVES so Flow moves off REQUESTED to
      // ACTIVE/PENDING/FAILED per the canonical ACK — a single request, not a re-POST.
      if (pr && pr.then) pr.then(function () { document.dispatchEvent(new CustomEvent('ed:contract', { detail: det })); });
    }
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
    // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
    // deferred ed:ticker/ed:view dispatch -- see that file's init() comment.
    //
    // Audit finding #5 (2026-09-16), FIXED: this used to also listen to the generic
    // `ed:refresh{slow}` broadcast, refetching the COMPLETE vendor chain (every strike,
    // both sides, strike_range=ALL) unconditionally every ~12s regardless of whether the
    // Chain view was even the active view, and regardless of whether anything in the chain
    // had actually changed. Replaced with an explicit, Chain-view-scoped, much slower
    // cadence: this ladder shows EVERY contract's OI/Volume/IV/Delta, not just the handful
    // the gamma heatmap's per-cell stream state already tracks, so there is no existing
    // canonical per-cell live path for it to update through incrementally -- a full re-fetch
    // is genuinely the only mechanism available today. The interval below is set to the
    // wide-chain REST cycle's OWN real cadence (TERRAIN_REFRESH_SEC, ~60s server-side,
    // documented at refresh_gamma_surface_from_stream's own docstring) rather than an
    // arbitrary guess: refreshing faster than the producer itself recomputes would only
    // ever re-serve the same response.
    var CHAIN_REFRESH_MS = 60000;
    setInterval(function () { if (isChain()) load(); }, CHAIN_REFRESH_MS);
  }
})();
