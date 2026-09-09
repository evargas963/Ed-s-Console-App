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

  // ---- theme-aware colour: sign -> green/red, |value|/maxAbs -> intensity, ~0 -> recede.
  //      Fills are SOLID, interpolated from the active theme's heat tokens (zero -> pos/neg), so a
  //      cell reads correctly on ANY background — never dark-mode rgba re-used over a light canvas.
  //      Text contrast is picked from the resulting fill's luminance, so it is legible in both themes. ----
  var DEFAULT_HEAT = { pos: [35, 192, 107], neg: [229, 72, 77], zero: [18, 26, 37] };  // dark defaults (node/test)
  function _hex(h) {
    h = String(h || '').trim(); if (h.charAt(0) === '#') h = h.slice(1);
    if (h.length === 3) h = h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) + h.charAt(2) + h.charAt(2);
    if (h.length < 6) return null;
    var n = parseInt(h.slice(0, 6), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function _mix(a, b, t) { return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)]; }
  function _rgb(c) { return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; }
  function _lum(c) { return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]; }
  function cellStyle(n, maxAbs, colors) {
    colors = colors || DEFAULT_HEAT;
    if (n === null || n === undefined || isNaN(n)) return { bg: 'transparent', fg: 'var(--ed-ink-4)', empty: true };
    var v = Number(n);
    if (Math.abs(v) < 1) return { bg: _rgb(colors.zero), fg: 'var(--ed-ink-3)', empty: false };
    var t = maxAbs > 0 ? Math.min(1, Math.abs(v) / maxAbs) : 0;
    var intensity = Math.pow(t, 0.34);   // cube-root-ish so small-but-real cells stay visible
    var mixed = _mix(colors.zero, (v > 0 ? colors.pos : colors.neg), intensity);
    var fg = _lum(mixed) < 140 ? '#f4f7fb' : '#0a0e17';
    return { bg: _rgb(mixed), fg: fg, empty: false, sign: (v > 0 ? 1 : -1) };
  }
  function readHeatColors() {   // the active theme's heat palette (falls back to dark defaults)
    try {
      var cs = getComputedStyle(document.documentElement);
      var p = _hex(cs.getPropertyValue('--ed-heat-pos')), ng = _hex(cs.getPropertyValue('--ed-heat-neg')), z = _hex(cs.getPropertyValue('--ed-heat-zero'));
      if (p && ng && z) return { pos: p, neg: ng, zero: z };
    } catch (e) {}
    return DEFAULT_HEAT;
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
    _lastSurface = surface;   // cached so a theme switch can re-render without a refetch
    // #1: skip the full ~thousands-of-cells table rebuild when the canonical surface REVISION is
    // unchanged (only the age advances between ~60s/roster terrain revisions). A theme switch clears
    // _lastRevision so the recolour still rebuilds.
    var rev = surfaceRevision(surface);
    if (rev === _lastRevision && host.querySelector('.heat')) {
      updateScope(surface); applyStrikeHighlight(host);
      return;
    }
    _lastRevision = rev;
    var heat = readHeatColors();
    var maxAbs = 0;
    cells.forEach(function (r) { (r.gex || []).forEach(function (v) { if (v != null && Math.abs(v) > maxAbs) maxAbs = Math.abs(v); }); });

    var spotIdx = nearestStrikeIndex(strikes, spot);
    // freshness / source — fail stale visibly (RC-UI-1 live-source rewire)
    var live = surface.live !== false, stale = !!surface.stale;
    var banner = '';
    if (!live || stale) {
      // #1.3: a just-viewed ticker the terrain loop covers is WARMING (live surface arriving next
      // cycle) — never let the morning reference look like the final state after Gamma was opened.
      var warming = !live && surface.warming === true;
      var label = warming ? 'LIVE SURFACE WARMING' : (!live ? 'MORNING REFERENCE' : 'STALE');
      var cls = warming ? 'warming' : (!live ? 'ref' : 'stale');
      var msg = surface.degraded || (!live ? 'banked morning reference — not intraday' : 'live surface is stale');
      banner = '<div class="heat-banner ' + cls + '">' + label + ' — ' + escapeHtml(msg) + '</div>';
    }
    // #2: a NARROWED live chain basis (timeout ladder: full -> dte<=120 -> dte<=45) must not look
    // identical to the normal full basis — surface it prominently.
    if (live && surface.chain_basis && surface.chain_basis !== 'full') {
      banner += '<div class="heat-banner degraded">NARROWED — live chain basis "' + escapeHtml(surface.chain_basis) +
        '" (reduced expiry window under load), not the usual full basis</div>';
    }
    // #7: compact shade legend (shade = |GEX$| magnitude; the actual dollar value is printed in every cell)
    var legend = '<div class="heat-legend"><span>−' + formatUsd(maxAbs) + '</span><span class="grad"></span>' +
      '<span>+' + formatUsd(maxAbs) + '</span><span style="margin-left:8px">shade = |GEX$| · value in each cell</span></div>';
    // C: emphasise the nearest-expiry (front) column — presentation only, no predictive meaning
    var frontCol = -1, minDte = Infinity;
    exps.forEach(function (e, ix) { if (e.dte != null && e.dte < minDte) { minDte = e.dte; frontCol = ix; } });
    // B: a STALE / REFERENCE surface visually recedes (in addition to the banner)
    var recede = (!live || stale) ? ' recede' : '';
    var html = banner + legend + '<div class="heat-wrap' + recede + '"><table class="heat"><thead><tr>' +
      '<th class="hcorner">Strike</th>';
    exps.forEach(function (e, ix) {
      var dte = (e.dte === 0) ? '0DTE' : (e.dte != null ? e.dte + 'DTE' : '');
      html += '<th class="hexp' + (ix === frontCol ? ' col-front' : '') + '"><span class="d">' +
        escapeHtml((e.expiry || '').slice(5)) + '</span><span class="dte">' + dte + '</span></th>';
    });
    html += '</tr></thead><tbody>';
    for (var i = 0; i < cells.length; i++) {
      var row = cells[i], isSpot = (i === spotIdx);
      html += '<tr' + (isSpot ? ' class="spotrow"' : '') + '>' +
        '<th class="hstrike' + (isSpot ? ' spot' : '') + '">' + fmtStrike(row.strike) + '</th>';
      for (var j = 0; j < exps.length; j++) {
        var v = (row.gex || [])[j];
        var st = cellStyle(v, maxAbs, heat);
        html += '<td class="hcell' + (j === frontCol ? ' col-front' : '') + '" style="background:' + st.bg + ';color:' + st.fg + '" ' +
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
        // A: route through the shared selection so every panel syncs to this strike
        if (window.EdShell) window.EdShell.setStrike(Number(c.getAttribute('data-strike')), c.getAttribute('data-expiry'));
      });
    });
    applyStrikeHighlight(host);
    updateScope(surface);
  }

  function applyStrikeHighlight(host) {
    host = host || document.getElementById('heatBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.hcell.sel-strike').forEach(function (n) { n.classList.remove('sel-strike'); });
    if (sel == null) return;
    host.querySelectorAll('.hcell[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('sel-strike'); });
  }

  function fmtStrike(k) { return (Math.round(k * 100) / 100).toString(); }
  function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  // ---- fetch + render, guarded (latest-wins) ----
  var _gen = 0, _lastSurface = null, _lastRevision = null;

  // server-owned revision identity — the cells are identical while these are unchanged, so we can
  // skip the full table rebuild. Not a semantic client fingerprint of the data; just the canonical
  // as-of / source / basis / freshness fields the server already stamps.
  function surfaceRevision(s) {
    if (!s || s.available === false) return 'unavailable|' + (s && s.source);
    return [s.source, s.chain_as_of_ts_utc, s.spot_as_of_ts_utc, s.chain_basis, s.live, s.stale].join('|');
  }
  function updateScope(surface) {   // lightweight: only the age/scope tag in the panel header
    var strikes = surface.strikes || [], exps = surface.expirations || [], spot = Number(surface.spot);
    var srcLabel = surface.source === 'terrain_live_cache' ? (surface.complete === false ? 'LIVE·window' : 'LIVE')
      : surface.source === 'banked_morning_reference' ? 'REF·morning' : (surface.source || '');
    var age = surface.age_sec != null ? ' ' + Math.round(surface.age_sec) + 's' : '';
    var basis = (surface.coverage && surface.coverage.chain_basis) ? ' ' + surface.coverage.chain_basis : '';
    var el = document.getElementById('heatScope');
    if (el) {
      el.textContent = strikes.length + '×' + exps.length + ' · spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') + ' · ' + srcLabel + age + basis;
      el.title = (surface.coverage && surface.coverage.note) || '';
    }
  }
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
    document.addEventListener('ed:strike', function () { applyStrikeHighlight(); });   // A: cross-panel sync
    document.addEventListener('ed:theme', function () {   // recolour: force a rebuild (revision is unchanged but the palette changed)
      var h = document.getElementById('heatBody'); if (h && _lastSurface) { _lastRevision = null; renderSurface(h, _lastSurface); }
    });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }

  var _root = (typeof window !== 'undefined') ? window : (typeof globalThis !== 'undefined' ? globalThis : this);
  _root.EdGamma = { formatUsd: formatUsd, cellStyle: cellStyle, nearestStrikeIndex: nearestStrikeIndex, renderSurface: renderSurface };
})();
