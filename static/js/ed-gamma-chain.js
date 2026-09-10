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
    var byK = {};
    cs.forEach(function (c) {
      var k = Number(c.strikePrice); if (!isFinite(k)) return;
      byK[k] = byK[k] || {};
      byK[k][(c.putCall || '').toUpperCase() === 'PUT' ? 'p' : 'c'] = c;
    });
    var strikes = Object.keys(byK).map(Number).sort(function (a, b) { return b - a; });
    var spot = Number(d.spot);
    var spotK = strikes.reduce(function (best, k) { return (best == null || Math.abs(k - spot) < Math.abs(best - spot)) ? k : best; }, null);
    var head = '<div class="chn-head"><span>' + esc(d.expiry || '') + ' · ' + strikes.length + ' strikes</span>' +
      '<span>spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') + (d.spot_source ? ' · ' + esc(d.spot_source) : '') + '</span></div>';
    function cell(c, k, dg) { var v = c ? c[k] : null; return (v == null) ? '—' : (typeof v === 'number' ? v.toFixed(dg == null ? 2 : dg) : esc(v)); }
    var h = head + '<table class="chn"><thead><tr>' +
      '<th colspan="4" class="cflag" style="text-align:center">Calls</th><th class="mid">Strike</th>' +
      '<th colspan="4" class="pflag" style="text-align:center">Puts</th></tr>' +
      '<tr><th>OI</th><th>Vol</th><th>IV%</th><th>Δ</th><th class="mid"></th><th>Δ</th><th>IV%</th><th>Vol</th><th>OI</th></tr></thead><tbody>';
    strikes.forEach(function (k) {
      var c = byK[k].c, p = byK[k].p;
      h += '<tr' + (k === spotK ? ' class="spot"' : '') + ' data-strike="' + k + '">' +
        '<td>' + cell(c, 'openInterest', 0) + '</td><td>' + cell(c, 'totalVolume', 0) + '</td>' +
        '<td>' + cell(c, 'volatility', 1) + '</td><td>' + cell(c, 'delta', 3) + '</td>' +
        '<td class="k">' + px(k, k % 1 ? 2 : 0) + '</td>' +
        '<td>' + cell(p, 'delta', 3) + '</td><td>' + cell(p, 'volatility', 1) + '</td>' +
        '<td>' + cell(p, 'totalVolume', 0) + '</td><td>' + cell(p, 'openInterest', 0) + '</td></tr>';
    });
    h += '</tbody></table>';
    host.innerHTML = h;
    host.querySelectorAll('tr[data-strike]').forEach(function (tr) {   // click a strike -> shared selection
      tr.addEventListener('click', function () { if (window.EdShell) window.EdShell.setStrike(Number(tr.getAttribute('data-strike')), d.expiry); });
    });
    var sr = host.querySelector('tr.spot'); if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
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
