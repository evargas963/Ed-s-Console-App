/* Ed Console — Options/Gamma heatmap view (RC-UI-1). PRESENTATION ONLY.
   Consumes GET /api/options/gamma-surface (canonical projection of compute_exposures_by_strike)
   and renders the strike × expiry grid. This module performs NO exposure math: it positions
   cells, formats the signed dollar value verbatim, maps sign->colour, and derives visual shade
   from the ABSOLUTE DISPLAYED magnitude only. The number shown equals the API value after
   formatting. Pure helpers are exposed on globalThis.EdGamma for node tests (invariants D/E). */
(function () {
  'use strict';

  // ---- pure formatter: compact signed USD ($958.6K, $7.6M, -$264.5K) ----
  function formatUsd(n) {
    if (n === null || n === undefined || isNaN(n)) return '';
    var v = Number(n), a = Math.abs(v), sign = v < 0 ? '-' : '';
    var s;
    if (a >= 1e9) s = (a / 1e9).toFixed(1) + 'B';
    else if (a >= 1e6) s = (a / 1e6).toFixed(1) + 'M';
    else if (a >= 1e3) s = (a / 1e3).toFixed(1) + 'K';
    else s = a.toFixed(0);
    return sign + '$' + s;
  }

  // ---- pure colour: sign -> green/red, |value|/maxAbs -> intensity, ~0 -> recede ----
  function cellStyle(n, maxAbs) {
    if (n === null || n === undefined || isNaN(n)) return { bg: 'transparent', fg: 'var(--ed-ink-4)', empty: true };
    var v = Number(n);
    var t = maxAbs > 0 ? Math.min(1, Math.abs(v) / maxAbs) : 0;
    // gamma cube-root so small-but-real cells stay visible; near-zero recedes to panel
    var intensity = Math.pow(t, 0.34);
    if (Math.abs(v) < 1) return { bg: 'var(--ed-heat-zero)', fg: 'var(--ed-ink-3)', empty: false };
    var base = v > 0 ? '35,192,107' : '229,72,77';           // --ed-pos / --ed-neg rgb
    var alpha = (0.10 + 0.80 * intensity).toFixed(3);
    var fg = intensity > 0.55 ? '#0a0e17' : (v > 0 ? 'var(--ed-pos-ink)' : 'var(--ed-neg-ink)');
    return { bg: 'rgba(' + base + ',' + alpha + ')', fg: fg, empty: false };
  }

  function nearestStrikeIndex(strikes, spot) {
    var best = -1, bd = Infinity;
    for (var i = 0; i < strikes.length; i++) {
      var d = Math.abs(strikes[i] - spot);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  // ---- render the grid from a canonical surface payload (no math) ----
  function renderSurface(host, surface) {
    if (!surface || surface.available === false) {
      host.innerHTML = '<div class="placeholder"><div class="big">Gamma surface unavailable</div>' +
        '<div class="sm">' + escapeHtml((surface && surface.reason) || 'no console / no banked wide chain for this symbol') +
        '</div></div>';
      return;
    }
    var exps = surface.expirations || [], strikes = surface.strikes || [], cells = surface.cells || [];
    var spot = Number(surface.spot);
    // maxAbs over displayed cells — visual normalisation only, not a semantic value
    var maxAbs = 0;
    cells.forEach(function (r) { (r.gex || []).forEach(function (v) { if (v != null && Math.abs(v) > maxAbs) maxAbs = Math.abs(v); }); });

    var spotIdx = nearestStrikeIndex(strikes, spot);
    // freshness / source — fail stale visibly (RC-UI-1 live-source rewire)
    var live = surface.live !== false, stale = !!surface.stale;
    var banner = '';
    if (!live || stale) {
      var msg = surface.degraded || (!live ? 'banked morning reference — not intraday' : 'live surface is stale');
      banner = '<div class="heat-banner ' + (!live ? 'ref' : 'stale') + '">' +
        (!live ? 'MORNING REFERENCE' : 'STALE') + ' — ' + escapeHtml(msg) + '</div>';
    }
    var html = banner + '<div class="heat-wrap"><table class="heat"><thead><tr>' +
      '<th class="hcorner">Strike</th>';
    exps.forEach(function (e) {
      var dte = (e.dte === 0) ? '0DTE' : (e.dte != null ? e.dte + 'DTE' : '');
      html += '<th class="hexp"><span class="d">' + escapeHtml((e.expiry || '').slice(5)) + '</span>' +
        '<span class="dte">' + dte + '</span></th>';
    });
    html += '</tr></thead><tbody>';
    for (var i = 0; i < cells.length; i++) {
      var row = cells[i], isSpot = (i === spotIdx);
      html += '<tr' + (isSpot ? ' class="spotrow"' : '') + '>' +
        '<th class="hstrike' + (isSpot ? ' spot' : '') + '">' + fmtStrike(row.strike) + '</th>';
      for (var j = 0; j < exps.length; j++) {
        var v = (row.gex || [])[j];
        var st = cellStyle(v, maxAbs);
        html += '<td class="hcell" style="background:' + st.bg + ';color:' + st.fg + '" ' +
          'data-strike="' + row.strike + '" data-expiry="' + escapeHtml(exps[j].expiry) + '" data-gex="' + (v == null ? '' : v) + '">' +
          (st.empty ? '' : formatUsd(v)) + '</td>';
      }
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    host.innerHTML = html;

    // scroll spot into view; presentation-only cell selection -> strike detail
    var srow = host.querySelector('.spotrow');
    if (srow && srow.scrollIntoView) srow.scrollIntoView({ block: 'center' });
    host.querySelectorAll('.hcell').forEach(function (c) {
      c.addEventListener('click', function () {
        host.querySelectorAll('.hcell.sel').forEach(function (n) { n.classList.remove('sel'); });
        c.classList.add('sel');
        document.dispatchEvent(new CustomEvent('ed:strike', {
          detail: { strike: Number(c.getAttribute('data-strike')), expiry: c.getAttribute('data-expiry'),
                    gex: c.getAttribute('data-gex') } }));
      });
    });
    var srcLabel = surface.source === 'terrain_live_cache' ? 'LIVE'
      : surface.source === 'banked_morning_reference' ? 'REF·morning' : (surface.source || '');
    var age = surface.age_sec != null ? ' ' + Math.round(surface.age_sec) + 's' : '';
    var scopeEl = document.getElementById('heatScope');
    if (scopeEl) scopeEl.textContent = strikes.length + '×' + exps.length + ' · spot ' +
      (isFinite(spot) ? spot.toFixed(2) : '—') + ' · ' + srcLabel + age;
  }

  function fmtStrike(k) { return (Math.round(k * 100) / 100).toString(); }
  function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  // ---- fetch + render, guarded (latest-wins) ----
  var _gen = 0;
  function load() {
    var host = document.getElementById('heatBody');
    if (!host) return;
    var st = (window.EdShell && window.EdShell.getState()) || {};
    if (st.workspace !== 'options' || st.subview !== 'gamma' || st.view !== 'heatmap') return;
    var ticker = st.ticker || 'SPY';
    var mygen = ++_gen;
    host.setAttribute('aria-busy', 'true');
    fetch('/api/options/gamma-surface?ticker=' + encodeURIComponent(ticker), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (mygen === _gen) renderSurface(host, d); })
      .catch(function () { if (mygen === _gen) renderSurface(host, { available: false, reason: 'no console serving /api/options/gamma-surface' }); });
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }

  var _root = (typeof window !== 'undefined') ? window : (typeof globalThis !== 'undefined' ? globalThis : this);
  _root.EdGamma = { formatUsd: formatUsd, cellStyle: cellStyle, nearestStrikeIndex: nearestStrikeIndex, renderSurface: renderSurface };
})();
