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
      // #1-A: even with no surface to draw, disclose the collection status honestly — a requested
      // symbol that is NOT on the board must read "not currently active for this symbol", never a
      // promised refresh. buildBanner is the ONE place that wording lives (warming/requested/board).
      var b = surface ? buildBanner(surface) : '';
      host.innerHTML = b + '<div class="placeholder"><div class="big">Gamma surface unavailable</div>' +
        '<div class="sm">' + escapeHtml((surface && surface.reason) || 'no console / no banked wide chain for this symbol') +
        '</div></div>';
      return;
    }
    var exps = surface.expirations || [], strikes = surface.strikes || [], cells = surface.cells || [];
    var spot = Number(surface.spot);
    var ES = window.EdShell;
    // #5: expiry filter (from the canonical /api/expiries dropdown) is PRESENTATION — it selects which
    // already-computed expiry column(s) to show; it never recomputes a value.
    var expFilter = (ES && ES.getExpiry) ? ES.getExpiry() : null;
    var scope = (ES && ES.getScope) ? ES.getScope() : 'auto';
    // VIEWPORT (real-data repair 2026-09-10): the canonical surface is served complete (the live SPY
    // reference is 116 strikes x 16 expirations) and the heatmap used to draw ALL of it, collapsing
    // the approved ~11-row workstation into an unreadable dump. The display now SELECTS a viewport:
    //   rows    = the ONE shell scope policy (EdShell.scopeSelect: Auto 11 strikes around spot,
    //             Wider 23, All available = every canonical strike, scrolled at the same row height);
    //   columns = the expiry filter's column, else in Auto the nearest UNEXPIRED expirations that fit
    //             legibly (server-stamped `expired`; a prior session's 0DTE is never shown as current
    //             structure), else every canonical column with expired ones labelled EXPIRED.
    // Selection only: every cell value is the API value; nothing is dropped from the payload, and the
    // counts (canonical vs shown) are disclosed in the header and the scope note.
    var rowSel = (ES && ES.scopeSelect) ? ES.scopeSelect(strikes, spot)
      : { idx: strikes.map(function (_s, i) { return i; }), shown: strikes.length, total: strikes.length };
    var allCols = exps.map(function (_e, ix) { return ix; });
    var unexpired = allCols.filter(function (ix) { return exps[ix].expired !== true; });
    var viewCols, expiredHidden = 0;
    if (expFilter) {
      viewCols = allCols.filter(function (ix) { return exps[ix].expiry === expFilter; });
      if (!viewCols.length) viewCols = allCols;
    } else if (scope === 'auto') {
      var pool = unexpired.length ? unexpired : allCols;      // nothing unexpired: show what exists, labelled
      viewCols = pool.slice(0, autoColCount(host));
      expiredHidden = allCols.length - unexpired.length;
    } else if (scope === 'wider') {
      // twice the Auto column budget: nearest unexpired first, then expired (labelled); the grid scrolls
      var expiredCols = allCols.filter(function (ix) { return exps[ix].expired === true; });
      viewCols = unexpired.concat(expiredCols).slice(0, 2 * autoColCount(host)).sort(function (a, b) { return a - b; });
    } else {
      viewCols = allCols;                                       // every canonical column, scrolled at legible width
    }
    _lastSurface = surface;   // cached so a theme switch can re-render without a refetch
    // #1: skip the full table rebuild when the canonical surface REVISION (and the viewport choice)
    // is unchanged (only the age advances between terrain revisions). A theme switch clears
    // _lastRevision so the recolour still rebuilds.
    var rev = surfaceRevision(surface) + '|' + scope + '|' + viewCols.length;
    if (rev === _lastRevision && host.querySelector('.heat')) {
      applyStatus(host, surface); applyStrikeHighlight(host);   // data unchanged: refresh status only
      return;
    }
    _lastRevision = rev;
    var heat = readHeatColors();
    // maxAbs over DISPLAYED cells — visual normalisation only, not a semantic value
    var maxAbs = 0;
    rowSel.idx.forEach(function (i) { var r = cells[i] || {}; viewCols.forEach(function (j) { var v = (r.gex || [])[j]; if (v != null && Math.abs(v) > maxAbs) maxAbs = Math.abs(v); }); });

    var spotIdx = nearestStrikeIndex(strikes, spot);
    // freshness / source — fail stale visibly (RC-UI-1 live-source rewire)
    var live = surface.live !== false, stale = !!surface.stale;
    var banner = buildBanner(surface);   // status banners (warming/requested/stale/ref + narrowed)
    // C: emphasise the nearest UNEXPIRED expiry (front) column — presentation only, no predictive meaning
    var frontCol = -1, minDte = Infinity;
    exps.forEach(function (e, ix) { if (e.expired !== true && e.dte != null && e.dte < minDte) { minDte = e.dte; frontCol = ix; } });
    // B: a STALE / REFERENCE surface visually recedes (in addition to the banner)
    var recede = (!live || stale) ? ' recede' : '';
    var tbl = '<table class="heat"><thead><tr><th class="hcorner">Strike</th>';
    viewCols.forEach(function (j) {
      var e = exps[j], expired = e.expired === true;
      var dte = expired ? 'EXPIRED' : (e.dte === 0) ? '0DTE' : (e.dte != null ? e.dte + 'DTE' : '');
      tbl += '<th class="hexp' + (j === frontCol ? ' col-front' : '') + (expired ? ' expired' : '') + '"' +
        (expired ? ' title="this expiration has already expired — a prior-session column kept for reference, not current structure"' : '') +
        '><span class="d">' + escapeHtml((e.expiry || '').slice(5)) + '</span><span class="dte">' + dte + '</span></th>';
    });
    tbl += '</tr></thead><tbody>';
    // Operator finding (2026-09-11): rowSel.idx is ascending-index order into the
    // ascending `strikes` array (scopeSelect's own contract — shared by GEX-by-Strike
    // and other consumers, so it stays ascending there). The heatmap specifically must
    // read like a real strike ladder: highest strike at the top, lowest at the bottom.
    // Reversed here, in the render loop only -- a presentation-only iteration order, not
    // a mutation of rowSel.idx (still ascending for maxAbs above and any other reader)
    // or of any row's own strike/expiry/gex/isSpot binding, which is looked up by index
    // `i` exactly as before.
    rowSel.idx.slice().reverse().forEach(function (i) {
      var row = cells[i] || { strike: strikes[i], gex: [] }, isSpot = (i === spotIdx);
      tbl += '<tr' + (isSpot ? ' class="spotrow"' : '') + '>' +
        '<th class="hstrike' + (isSpot ? ' spot' : '') + '">' + fmtStrike(row.strike) + '</th>';
      for (var jj = 0; jj < viewCols.length; jj++) {
        var j2 = viewCols[jj];
        var v = (row.gex || [])[j2];
        var st = cellStyle(v, maxAbs, heat);
        tbl += '<td class="hcell' + (j2 === frontCol ? ' col-front' : '') + (exps[j2].expired === true ? ' expired' : '') +
          '" style="background:' + st.bg + ';color:' + st.fg + '" ' +
          'data-strike="' + row.strike + '" data-expiry="' + escapeHtml(exps[j2].expiry) + '" data-gex="' + (v == null ? '' : v) + '">' +
          (st.empty ? '' : formatUsd(v)) + '</td>';
      }
      tbl += '</tr>';
    });
    tbl += '</tbody></table>';
    // #3: the ONE disclosure line — how many canonical strikes / expirations are on screen vs clipped
    var colsTxt = viewCols.length + ' of ' + exps.length + ' expirations' +
      (expiredHidden ? ' (' + expiredHidden + ' expired hidden in Auto)' : '');
    var note = (ES && ES.scopeNote) ? ES.scopeNote({ total: strikes.length, shown: rowSel.shown, extra: colsTxt }) : '';
    // the grid fills the panel; a compact vertical magnitude legend sits at its right edge (the
    // dollar value is printed in every cell — shade = |GEX$|), matching the approved reference.
    var vlegend = '<div class="heat-vlegend"><span class="bar"></span>' +
      '<span class="caps"><span class="t">High<br>Call<br>GEX</span><span class="m">0</span>' +
      '<span class="b">High<br>Put<br>GEX</span></span></div>';
    host.innerHTML = banner + note +
      '<div class="heat-host"><div class="heat-main"><div class="heat-wrap' + recede + '">' +
      tbl + '</div></div>' + vlegend + '</div>';

    // scroll spot into view; presentation-only cell selection -> strike detail
    var srow = host.querySelector('.spotrow');
    if (srow && srow.scrollIntoView) srow.scrollIntoView({ block: 'center' });
    host.querySelectorAll('.hcell').forEach(function (c) {
      c.addEventListener('click', function () {
        // A: route through the shared selection so every panel syncs to this strike
        if (window.EdShell) window.EdShell.setStrike(Number(c.getAttribute('data-strike')), c.getAttribute('data-expiry'));
      });
    });
    // default the shared selection to the spot strike on first load, so Strike Detail and the
    // GEX-by-strike highlight are populated on arrival (like the approved reference) instead of an
    // empty placeholder. Never overrides a selection the operator has already made.
    if (window.EdShell && window.EdShell.getState().selStrike == null && strikes.length && spotIdx >= 0) {
      var _fe = expFilter || (exps[frontCol >= 0 ? frontCol : 0] || {}).expiry || null;
      window.EdShell.setStrike(strikes[spotIdx], _fe);
    }
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

  // Auto column budget: the nearest expirations that stay legible at the approved cell width. The
  // approved workstation shows ~11 columns at 1672px; a column narrower than MIN_COL_PX collapses
  // the header and the signed value, so the count is capped by width, never the other way round.
  var MIN_COL_PX = 84, MAX_AUTO_COLS = 11, MIN_AUTO_COLS = 3;
  function autoColCount(host) {
    var w = (host && host.clientWidth) || 0;
    if (!w) return MAX_AUTO_COLS;
    var avail = w - 70 /* strike column */ - 64 /* magnitude legend */;
    return Math.max(MIN_AUTO_COLS, Math.min(MAX_AUTO_COLS, Math.floor(avail / MIN_COL_PX)));
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
    // DATA revision only — decides whether the expensive TABLE rebuilds. Status (live/stale/warming/
    // age) is deliberately NOT here; it is refreshed every time via applyStatus. et_date discriminates
    // banked captures (whose chain/spot as-of are null) so a new morning capture cannot reuse the grid.
    if (!s || s.available === false) return 'unavailable|' + (s && s.source);
    // ticker + expiry filter are part of WHICH cells are shown: a symbol change or an expiry-column
    // change must always rebuild the grid, never reuse a prior symbol's/expiry's table.
    var expFilter = (window.EdShell && window.EdShell.getExpiry) ? window.EdShell.getExpiry() : null;
    // Independent-review finding (2026-09-12), REPRODUCED: a streamed update can change cell
    // VALUES (server.py's eager refresh_gamma_surface_from_stream) without touching
    // chain_as_of_ts_utc/spot_as_of_ts_utc at all — those are stamped only by the ~60s REST
    // cycle. With only REST-only fields in this key, a genuinely new surface hashed identical
    // to the old one and the table silently kept showing stale cells. surface_seq is a
    // server-owned counter bumped on EVERY publication, REST or streamed (server.py's
    // _next_gamma_surface_seq) — its inclusion is what makes a streamed-only change visible.
    return [s.ticker || s.symbol, s.source, s.chain_as_of_ts_utc, s.spot_as_of_ts_utc, s.chain_basis, s.et_date, expFilter, s.surface_seq].join('|');
  }
  // lightweight STATUS: banner (warming/requested/stale/reference/degraded) + recede dimming + scope
  // age — always refreshed, even when the DATA revision is unchanged, so nothing is left frozen.
  function buildBanner(surface) {
    var live = surface.live !== false, stale = !!surface.stale, out = '';
    if (!live || stale) {
      var warming = !live && surface.warming === true;
      var requested = !live && !warming && surface.requested === true;
      // #1-A: distinguish "on the board, a refresh is coming" from "not on the board, nothing is
      // collecting this symbol". Only the former may promise a next refresh.
      var onBoard = surface.on_board === true;
      var notCollecting = requested && !onBoard;
      // WHAT is on screen (identity, server-stamped): a banked reference from a PRIOR session is named
      // as such — a 2026-09-09 morning chain viewed on 2026-09-10 is never dressed as today's structure.
      var prior = surface.prior_session === true;
      var refLabel = !live ? ((prior ? 'PRIOR SESSION REFERENCE' : 'MORNING REFERENCE') +
        (surface.et_date ? ' · ' + escapeHtml(surface.et_date) : '')) : '';
      // WHERE the live surface stands (state)
      var stateLabel = warming ? 'LIVE SURFACE WARMING'
        : notCollecting ? 'NOT COLLECTING'
        : requested ? 'LIVE SURFACE REQUESTED'
        : (live ? 'STALE' : '');
      // identity class first (a reference surface always reads as REFERENCE), live-state class beside it
      var cls = (!live ? 'ref ' : '') + (warming ? 'warming'
        : (requested && !notCollecting) ? 'warming'
        : (live ? 'stale' : ''));
      // CONCISE primary line; the full reason is disclosed in the tooltip (title) — never a paragraph
      // that consumes the analytical panel.
      var brief = !live
        ? (prior ? 'banked chain from a prior session — not this session, not intraday' : 'banked morning chain — not intraday')
        : 'live surface is stale';
      var detail = surface.degraded
        || (notCollecting ? 'live terrain collection is not currently active for this symbol'
          : requested ? 'awaiting next eligible terrain refresh' : brief);
      var text = [refLabel, stateLabel].filter(Boolean).join(' — ') + ' · ' + brief +
        (notCollecting ? ' · collection is not currently active for this symbol' : '');
      out += '<div class="heat-banner ' + cls + '" title="' + escapeHtml(detail) + '"><span class="hb-main">' + text +
        '</span><span class="hb-more" aria-label="details">details</span></div>';
    }
    if (live && surface.chain_basis && surface.chain_basis !== 'full') {
      out += '<div class="heat-banner degraded">NARROWED — live chain basis "' + escapeHtml(surface.chain_basis) +
        '" (reduced expiry window under load), not the usual full basis</div>';
    }
    return out;
  }
  function applyStatus(host, surface) {   // refresh status WITHOUT rebuilding the table
    Array.prototype.slice.call(host.querySelectorAll('.heat-banner')).forEach(function (n) { n.remove(); });
    var b = buildBanner(surface);
    if (b) host.insertAdjacentHTML('afterbegin', b);
    var wrap = host.querySelector('.heat-wrap');
    if (wrap) wrap.classList.toggle('recede', surface.live === false || !!surface.stale);
    updateScope(surface);
  }
  function updateScope(surface) {   // lightweight: only the age/scope tag in the panel header
    var strikes = surface.strikes || [], exps = surface.expirations || [], spot = Number(surface.spot);
    var srcLabel = surface.source === 'terrain_live_cache' ? (surface.complete === false ? 'LIVE·window' : 'LIVE')
      : surface.source === 'banked_morning_reference' ? 'REF·morning' : (surface.source || '');
    var age = surface.age_sec != null ? ' ' + Math.round(surface.age_sec) + 's' : '';
    var basis = (surface.coverage && surface.coverage.chain_basis) ? ' ' + surface.coverage.chain_basis : '';
    var el = document.getElementById('heatScope');
    if (el) {
      var shownRows = document.querySelectorAll('#heatBody .heat tbody tr').length;
      var shownCols = document.querySelectorAll('#heatBody .heat thead .hexp').length;
      var shown = (shownRows && shownCols) ? ' · ' + shownRows + '×' + shownCols + ' shown' : '';
      el.textContent = strikes.length + '×' + exps.length + ' canonical' + shown + ' · spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') + ' · ' + srcLabel + age + basis;
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
    document.addEventListener('ed:expiry', function () {   // #5: re-window columns to the selected expiry (client-side; same canonical surface)
      var h = document.getElementById('heatBody'); if (!h) return; _lastRevision = null;
      if (_lastSurface) renderSurface(h, _lastSurface); else load();
    });
    document.addEventListener('ed:scope', function () {    // #3: Auto / Wider / All available re-selects the viewport (same canonical surface)
      var h = document.getElementById('heatBody'); if (!h) return; _lastRevision = null;
      if (_lastSurface) renderSurface(h, _lastSurface); else load();
    });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }

  var _root = (typeof window !== 'undefined') ? window : (typeof globalThis !== 'undefined' ? globalThis : this);
  _root.EdGamma = { formatUsd: formatUsd, cellStyle: cellStyle, nearestStrikeIndex: nearestStrikeIndex, renderSurface: renderSurface };
})();
