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
    expiry_scope_mismatch: { t: 'expiry mismatch', ref: true },
    persisted_complete_capture_fallback: { t: 'captured', ref: true },
    stored_analytical_snapshot_fallback: { t: 'analytical (not complete)', ref: true },
  };
  function setSrc(d) {
    var el = document.getElementById('chSrc'); if (!el) return;
    var sc = d && d.scope, kind = sc && sc.kind;
    if (!kind) { el.innerHTML = ''; return; }
    var m = SCOPE[kind] || { t: kind };
    el.innerHTML = (window.EdShell && window.EdShell.asOfBadge)
      ? window.EdShell.asOfBadge({ label: 'vendor · ' + m.t, ageSec: (sc.captured_age_sec != null ? sc.captured_age_sec : null),
          live: !!m.live, ref: !!m.ref, title: 'chain scope: ' + kind }) : '';
  }

  var _gen = 0;
  function load() {
    var host = document.getElementById('chainBody');
    if (!host || !isChain()) return;
    var g = ++_gen, tk = st().ticker || 'SPY';
    var exp = (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) || null;
    var tkEl = document.getElementById('chTicker'); if (tkEl) tkEl.textContent = tk.replace('$', '');
    host.setAttribute('aria-busy', 'true');
    fetch('/api/chain?ticker=' + encodeURIComponent(tk) + (exp ? '&expiry=' + encodeURIComponent(exp) : ''), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _gen) render(host, d); })
      .catch(function () { if (g === _gen) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/chain</div></div>'; });
  }

  function render(host, d) {
    setSrc(d);
    var cs = (d && d.contracts) || [];
    if (!cs.length) { host.innerHTML = '<div class="placeholder"><div class="sm">no chain for this expiry</div></div>'; return; }
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
    var spot = Number(d.spot);
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
    var h = head + '<table class="chn"><thead><tr>' +
      '<th colspan="4" class="cflag" style="text-align:center">Calls</th><th class="mid">Strike</th>' +
      '<th colspan="4" class="pflag" style="text-align:center">Puts</th></tr>' +
      '<tr><th>OI</th><th>Vol</th><th>IV%</th><th>Δ</th><th class="mid"></th><th>Δ</th><th>IV%</th><th>Vol</th><th>OI</th></tr></thead><tbody>';
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
    h += '</tbody></table>';
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
    var sr = host.querySelector('tr.spot'); if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
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
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
