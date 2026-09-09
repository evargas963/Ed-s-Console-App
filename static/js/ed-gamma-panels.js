/* Ed Console — Options/Gamma supporting panels (RC-UI-1). PRESENTATION ONLY.
   Key Levels rail  <- GET /api/terrain      (canonical levels SSOT)
   GEX by Strike    <- GET /api/terrain/strikes  (per-strike net_gex_1pct$)
   Strike Detail    <- GET /api/chain         (vendor per-contract OI/vol/greeks)
   No trading semantics are computed here. Bar scaling is visual normalisation over the
   already-computed displayed values; distances/positions are formatting only. */
(function () {
  'use strict';

  var usd = (window.EdGamma && window.EdGamma.formatUsd) || function (n) {
    if (n == null || isNaN(n)) return '';
    var a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'K';
    return s + '$' + a.toFixed(0);
  };
  function px(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function txt(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  function isGamma() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && s.subview === 'gamma';
  }
  function ticker() { return ((window.EdShell && window.EdShell.getState()) || {}).ticker || 'SPY'; }

  var REGIME = {
    LONG_GAMMA_CHOP: { t: 'Long γ · chop', c: 'var(--ed-pos-ink)' },
    SHORT_GAMMA_TREND: { t: 'Short γ · trend', c: 'var(--ed-warn)' },
    SIGN_UNPROVEN: { t: 'sign unproven', c: 'var(--ed-ink-3)' },
    UNAVAILABLE: { t: 'unavailable', c: 'var(--ed-ink-3)' },
  };

  // ---------- Key Levels rail ----------
  var _lgen = 0;
  function loadLevels() {
    if (!isGamma() || !document.getElementById('klSpot')) return;
    var g = ++_lgen, tk = ticker();
    fetch('/api/terrain?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _lgen) renderLevels(d); })
      .catch(function () { if (g === _lgen) renderLevels(null); });
  }
  function renderLevels(d) {
    var ids = ['klSpot', 'klFlip', 'klCall', 'klPut', 'klAbs', 'klPeak', 'klNet', 'klRegime', 'klPcr'];
    if (!d || d.error) {
      ids.forEach(function (id) { txt(id, '—'); });
      txt('klSrc', d && d.error ? 'terrain not ready' : 'offline');
      return;
    }
    txt('klSpot', px(d.spot));
    txt('klFlip', px(d.gamma_flip));
    txt('klCall', px(d.call_wall));
    txt('klPut', px(d.put_wall));
    txt('klAbs', px(d.absolute_gamma_strike));
    txt('klPeak', px(d.net_gex_peak));
    // Net GEX / 1% move — signed $, coloured by sign (formatting only)
    var net = document.getElementById('klNet');
    if (net) {
      var v = d.net_gex_at_spot;
      net.textContent = (v == null) ? '—' : usd(v);
      net.style.color = (v == null) ? '' : (v >= 0 ? 'var(--ed-pos-ink)' : 'var(--ed-neg-ink)');
    }
    var reg = document.getElementById('klRegime');
    if (reg) {
      var rm = REGIME[d.regime] || { t: (d.regime || '—'), c: 'var(--ed-ink-2)' };
      reg.textContent = rm.t; reg.style.color = rm.c;
    }
    txt('klPcr', '—');  // PCR lives on the analytics plane; wired with the header analytics pass
    // B: the levels rail recedes when terrain reports stale
    var klb = document.getElementById('klBody');
    if (klb) klb.classList.toggle('recede', !!d.levels_stale);
    // freshness / provenance line
    var src = document.getElementById('klSrc');
    if (src) {
      if (d.levels_stale) {
        src.textContent = 'STALE ' + (d.levels_age_sec != null ? Math.round(d.levels_age_sec) + 's' : '') +
          (d.levels_stale_reason ? ' · ' + d.levels_stale_reason : '');
        src.style.color = 'var(--ed-stale)';
      } else {
        src.textContent = '/api/terrain · live';
        src.style.color = '';
      }
    }
  }

  // ---------- GEX by Strike ----------
  var _ggen = 0;
  function loadGbs() {
    var host = document.getElementById('gbsBody');
    if (!isGamma() || !host) return;
    var g = ++_ggen, tk = ticker();
    fetch('/api/terrain/strikes?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _ggen) renderGbs(host, d); })
      .catch(function () { if (g === _ggen) renderGbs(host, null); });
  }
  function renderGbs(host, d) {
    var rows = d && d.today && d.today.all;
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        (d ? 'no banked per-strike gamma for this symbol' : 'no console serving /api/terrain/strikes') + '</div></div>';
      return;
    }
    var spot = Number(d.spot);
    // #3: window around spot for readability (presentation), high strikes on top. The window is the
    // ONE shared Gamma scope (Auto ±6% / Wider / All available); `rows` is the current canonical
    // input, so the disclosure below states exactly how many of them are on screen vs clipped.
    var GBS_BASE = 0.06;
    var frac = (window.EdShell && window.EdShell.scopeWindow) ? window.EdShell.scopeWindow(GBS_BASE) : GBS_BASE;
    var win = rows.filter(function (r) { return (isFinite(spot) && isFinite(frac)) ? Math.abs(r[0] - spot) <= spot * frac : true; })
      .sort(function (a, b) { return b[0] - a[0]; });
    var note = (window.EdShell && window.EdShell.scopeNote)
      ? window.EdShell.scopeNote({ base: GBS_BASE, total: rows.length, shown: win.length, spot: spot }) : '';
    var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
    var spotStrike = win.reduce(function (best, r) {
      return (best == null || Math.abs(r[0] - spot) < Math.abs(best - spot)) ? r[0] : best; }, null);
    var h = note + '<div class="gbs">';
    win.forEach(function (r) {
      var k = r[0], v = Number(r[1]) || 0, w = Math.min(100, Math.abs(v) / maxAbs * 100);
      var pos = v >= 0;
      h += '<div class="gbs-row' + (k === spotStrike ? ' spot' : '') + '" data-strike="' + k + '">' +
        '<span class="gbs-k">' + px(k, k % 1 ? 2 : 0) + '</span>' +
        '<span class="gbs-track"><i class="gbs-bar ' + (pos ? 'pos' : 'neg') + '" style="width:' + w.toFixed(1) + '%"></i></span>' +
        '<span class="gbs-v ' + (pos ? 'pos' : 'neg') + '">' + usd(v) + '</span></div>';
    });
    h += '</div>';
    host.innerHTML = h;
    host.querySelectorAll('.gbs-row').forEach(function (rr) {   // A: click a strike -> sync all panels
      rr.addEventListener('click', function () { if (window.EdShell) window.EdShell.setStrike(Number(rr.getAttribute('data-strike'))); });
    });
    applyGbsHighlight(host);
    var sr = host.querySelector('.gbs-row.spot');
    if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
  }
  function applyGbsHighlight(host) {
    host = host || document.getElementById('gbsBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.gbs-row.gbs-sel').forEach(function (n) { n.classList.remove('gbs-sel'); });
    if (sel == null) return;
    host.querySelectorAll('.gbs-row[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('gbs-sel'); });
  }

  // ---------- Strike Detail ----------
  var _sgen = 0, _lastExpiry = null;
  function loadStrike(strike, expiry) {
    var host = document.getElementById('sdBody');
    if (!host) return;
    var g = ++_sgen, tk = ticker();
    var q = '/api/chain?ticker=' + encodeURIComponent(tk) + (expiry ? '&expiry=' + encodeURIComponent(expiry) : '');
    fetch(q, { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _sgen) renderStrike(host, d, strike, expiry); })
      .catch(function () { if (g === _sgen) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/chain</div></div>'; });
  }
  function renderStrike(host, d, strike, expiry) {
    var cs = (d && d.contracts) || [];
    if (!cs.length) { host.innerHTML = '<div class="placeholder"><div class="sm">no chain for this expiry</div></div>'; return; }
    function pick(side) {
      return cs.filter(function (c) {
        return (c.putCall || '').toUpperCase() === side &&
          Math.abs(Number(c.strikePrice) - Number(strike)) < 0.01; })[0];
    }
    var call = pick('CALL'), put = pick('PUT');
    txt('sdCtx', px(strike, strike % 1 ? 2 : 0) + (expiry ? ' · ' + esc(expiry.slice(5)) : ''));
    function cell(c, k, d2) { var v = c ? c[k] : null; return (v == null) ? '—' : (typeof v === 'number' ? v.toFixed(d2 == null ? 2 : d2) : esc(v)); }
    host.innerHTML =
      '<table class="sd"><thead><tr><th></th><th>OI</th><th>Vol</th><th>Gamma</th><th>Delta</th><th>IV%</th></tr></thead><tbody>' +
      '<tr><td class="side c">Call</td><td>' + cell(call, 'openInterest', 0) + '</td><td>' + cell(call, 'totalVolume', 0) +
      '</td><td>' + cell(call, 'gamma', 4) + '</td><td>' + cell(call, 'delta', 3) + '</td><td>' + cell(call, 'volatility', 1) + '</td></tr>' +
      '<tr><td class="side p">Put</td><td>' + cell(put, 'openInterest', 0) + '</td><td>' + cell(put, 'totalVolume', 0) +
      '</td><td>' + cell(put, 'gamma', 4) + '</td><td>' + cell(put, 'delta', 3) + '</td><td>' + cell(put, 'volatility', 1) + '</td></tr>' +
      '</tbody></table><div class="sd-src">vendor chain fields · /api/chain</div>';
  }

  // ---------- events ----------
  function loadAll() { loadLevels(); loadGbs(); }
  document.addEventListener('ed:ticker', loadAll);
  document.addEventListener('ed:view', loadAll);
  document.addEventListener('ed:scope', loadGbs);   // #3: re-window the GEX-by-strike panel only
  document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) loadAll(); });
  document.addEventListener('ed:strike', function (e) {
    var det = e.detail || {}; _lastExpiry = det.expiry || _lastExpiry;
    applyGbsHighlight();                       // A: sync the GEX-by-strike highlight
    if (det.strike != null) loadStrike(det.strike, det.expiry);
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadAll);
  else loadAll();
})();
