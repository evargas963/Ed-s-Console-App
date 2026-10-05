/* Ed Console — Options/Gamma heatmap view. PRESENTATION ONLY.
   Reads GET /api/options/gamma-surface with the window it wants (scope, the columns it fits, the
   selected expiry, a pan) and draws exactly the cells the server sends: the server picks the
   strikes and expiries (server._surface_view), counts the cells streaming, names the contracts to
   stream, marks the spot row and the front column, and sends each
   measure's colour scale. This module positions cells, formats each value, maps sign to colour and
   shade to the served scale. Pure helpers are exposed on globalThis.EdGamma for node tests. */
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
  // ---- compact contract count (1.0K, 23.1K): open interest and volume are counts, not dollars ----
  function formatCount(n) {
    if (n === null || n === undefined || isNaN(n)) return '';
    var v = Number(n), a = Math.abs(v), sign = v < 0 ? '-' : '';
    var s;
    if (a >= 1e9) s = (a / 1e9).toFixed(1) + 'B';
    else if (a >= 1e6) s = (a / 1e6).toFixed(1) + 'M';
    else if (a >= 1e3) s = (a / 1e3).toFixed(1) + 'K';
    else s = a.toFixed(0);
    return sign + s;
  }
  function formatMeasureValue(n, measure) {
    return (measure === 'oi' || measure === 'volume') ? formatCount(n) : formatUsd(n);
  }
  // the served words for why a cell has no value for a measure (server CELL_ABSENT_REASONS)
  function absentText(surface, row, measure, j) {
    var code = ((row.absent || {})[measure] || [])[j];
    return (surface.absent_reasons || {})[code];
  }

  // ---- theme-aware colour: sign -> green/red, shade -> |value| against the served scale ----
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
    if (n === null || n === undefined || isNaN(n)) return { bg: 'transparent', fg: 'var(--ed-ink-3)', empty: true };
    var v = Number(n);
    if (v === 0) return { bg: _rgb(colors.zero), fg: 'var(--ed-ink-3)', empty: false };
    var t = Math.abs(v) / maxAbs;   // the served scale is at least every |value| drawn
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
  // the selected measure's value per column: GEX/DEX a value, OI/volume the server's total
  function _measureRow(row, measure) {
    if (measure === 'oi' || measure === 'volume') {
      return (row[measure] || []).map(function (cp) { return cp ? cp.total : null; });
    }
    return row[measure] || [];
  }
  // the heatmap's streamed-contract demand is kept per ticker ('heatmap:<ticker>'), so one ticker's
  // demand never replaces another's in EdStream's union
  function _heatmapOwnerKey(tk) { return 'heatmap:' + (tk || ''); }

  // the words for each cell's and column's streaming state, served in the page (meta
  // ed-stream-words, server.STREAM_WORDS)
  var WORDS = JSON.parse(document.querySelector('meta[name="ed-stream-words"]').getAttribute('content'));
  var _pan = window.EdShell.newPan();
  var _panTicker = null;
  var _lastSurface = null, _lastRevision = null, _pendingTicker = null;

  function paintChip(cov) {   // the header's coverage chip: the served words
    var el = document.getElementById('heatScope'); if (!el) return;
    el.textContent = cov ? cov.label : '';
    el.title = cov ? cov.title : '';
    el.className = 'sub cov' + (cov ? ' cov-' + cov.state : '');
  }
  function buildBanner(surface) {
    var live = surface.live !== false, stale = !!surface.stale;
    if (live && !stale) return '';
    var warming = !live && surface.warming === true;
    var requested = !live && !warming && surface.requested === true;
    var stateLabel = warming ? 'LIVE SURFACE WARMING' : requested ? 'LIVE SURFACE REQUESTED' : (live ? 'STALE' : '');
    var cls = (warming || requested) ? 'warming' : (live ? 'stale' : '');
    var brief = !live ? 'no live surface for this symbol' : 'live surface is stale';
    var detail = surface.degraded || surface.reason || brief;
    return '<div class="heat-banner ' + cls + '" title="' + escapeHtml(detail) + '"><span class="hb-main">' +
      (stateLabel ? stateLabel + ' · ' : '') + brief + '</span><span class="hb-more" aria-label="details">details</span></div>';
  }
  function applyStatus(host, surface) {   // refresh status WITHOUT rebuilding the table
    Array.prototype.slice.call(host.querySelectorAll('.heat-banner')).forEach(function (n) { n.remove(); });
    var b = buildBanner(surface);
    if (b) host.insertAdjacentHTML('afterbegin', b);
    var wrap = host.querySelector('.heat-wrap');
    if (wrap) wrap.classList.toggle('recede', surface.live === false || !!surface.stale);
    paintChip(surface.view.coverage);
  }

  // ---- render the window the server sent (no math on its values) ----
  function renderSurface(host, surface) {
    var tk = _pendingTicker || (surface && surface.ticker);
    if (!surface || surface.available === false) {
      // every exit states the heatmap's demand, "none" included
      window.EdStream.setAdditionalContracts([], _heatmapOwnerKey(tk));
      _lastSurface = null; _lastRevision = null;
      paintChip(null);
      host.innerHTML = buildBanner(surface || { live: false }) + '<div class="placeholder"><div class="big">Gamma surface unavailable</div>' +
        '<div class="sm">' + escapeHtml((surface && surface.reason) || 'no console / no live surface for this symbol') + '</div></div>';
      return;
    }
    var view = surface.view;
    window.EdShell.panServed(_pan, view.centre);
    if (view.missing_expiry) {   // the selected expiry is not in this surface: nothing is drawn or streamed
      window.EdStream.setAdditionalContracts([], _heatmapOwnerKey(tk));
      _lastSurface = surface; _lastRevision = null;
      paintChip(null);
      host.innerHTML = '<div class="placeholder"><div class="big">Expiry ' + escapeHtml(view.missing_expiry) +
        ' unavailable</div><div class="sm">not in this surface — choose another expiry, or All Expirations</div></div>';
      return;
    }
    // stream every contract drawn (the served list); each cell's outcome comes back as its state
    window.EdStream.setAdditionalContracts(view.demand, _heatmapOwnerKey(tk));
    var measure = (window.EdShell && window.EdShell.getMeasure) ? window.EdShell.getMeasure() : 'gex';
    _lastSurface = surface;
    // the table is rebuilt only for a new publication or a new window, else its status refreshes
    var rev = [surface.ticker, surface.surface_seq, view.scope, view.centre, measure,
      (surface.expirations || []).map(function (e) { return e.expiry; }).join(',')].join('|');
    if (rev === _lastRevision && host.querySelector('.heat')) {
      applyStatus(host, surface); applyStrikeHighlight(host);
      return;
    }
    _lastRevision = rev;
    var words = WORDS;
    var exps = surface.expirations || [], cells = surface.cells || [];
    var maxAbs = view.max_abs[measure], heat = readHeatColors();
    var live = surface.live !== false, stale = !!surface.stale;
    var tbl = '<table class="heat"><thead><tr><th class="hcorner">Strike</th>';
    exps.forEach(function (e, j) {
      var dte = e.expired ? 'EXPIRED' : (e.dte === 0) ? '0DTE' : (e.dte != null ? e.dte + 'DTE' : '');
      var title = e.expired ? 'expired: a prior-session column, not current structure'
        : (words.column[(surface.stream_by_expiry || {})[e.expiry]] || '');
      tbl += '<th class="hexp' + (e.front ? ' col-front' : '') + (e.expired ? ' expired' : '') + '" data-col="' + j +
        '" title="' + escapeHtml(title) + '"><span class="d">' + escapeHtml((e.expiry || '').slice(5)) +
        '</span><span class="dte">' + dte + '</span></th>';
    });
    tbl += '</tr></thead><tbody>';
    cells.slice().reverse().forEach(function (row) {   // highest strike at the top
      var mrow = _measureRow(row, measure);
      tbl += '<tr' + (row.spot ? ' class="spotrow"' : '') + '><th class="hstrike' + (row.spot ? ' spot' : '') + '">' +
        fmtStrike(row.strike) + '</th>';
      exps.forEach(function (e, j) {
        var v = mrow[j], st = cellStyle(v, maxAbs, heat);
        var cellState = (row.stream || [])[j], liveState = cellState ? cellState.state : null;
        var reason = liveState === 'rejected' ? ((cellState.call || {}).rejected_reason || (cellState.put || {}).rejected_reason) : null;
        if (liveState === 'limited') { reason = cellState.limit_reason; }   // Schwab's message, as served
        var stateTitle = (words.cell[liveState] || '') + (reason ? ' (' + reason + ')' : '');
        tbl += '<td class="hcell' + (e.front ? ' col-front' : '') + (e.expired ? ' expired' : '') +
          (liveState ? ' state-' + liveState : '') +
          '" style="background:' + st.bg + ';color:' + st.fg + '" ' +
          (liveState ? 'data-cell-state="' + liveState + '" ' : '') +
          (stateTitle ? 'title="' + escapeHtml(stateTitle) + '" ' : '') +
          'data-strike="' + row.strike + '" data-expiry="' + escapeHtml(e.expiry) + '" data-gex="' + (v == null ? '' : v) + '">' +
          // no value: the served word ("-" where no contract is listed, or what Schwab did not send)
          (st.empty ? '<span class="absent">' + escapeHtml(absentText(surface, row, measure, j)) + '</span>'
            : formatMeasureValue(v, measure)) + '</td>';
      });
      tbl += '</tr>';
    });
    tbl += '</tbody></table>';
    // a pan is never silent: the strikes stop following the price until a double-click
    var note = (_pan.centre != null ? '<div class="heat-pan">Panned to ' + fmtStrike(_pan.served) +
      ' · double-click the strikes to follow the price</div>' : '') +
      (view.note ? '<div class="heat-pan">' + escapeHtml(view.note) + '</div>' : '');   // why not around the price
    var MEASURE_LEGEND = {
      gex: ['High<br>Call<br>GEX', 'High<br>Put<br>GEX'],
      dex: ['High<br>Call<br>DEX', 'High<br>Put<br>DEX'],
      oi: ['High<br>Open<br>Interest', 'Low<br>Open<br>Interest'],
      volume: ['High<br>Volume', 'Low<br>Volume'],
    };
    var legendPair = MEASURE_LEGEND[measure] || MEASURE_LEGEND.gex;
    var unsignedCls = (measure === 'oi' || measure === 'volume') ? ' unsigned' : '';
    var vlegend = '<div class="heat-vlegend' + unsignedCls + '"><span class="bar"></span>' +
      '<span class="caps"><span class="t">' + legendPair[0] + '</span><span class="m">0</span>' +
      '<span class="b">' + legendPair[1] + '</span></span></div>';
    host.innerHTML = buildBanner(surface) + note +
      '<div class="heat-host"><div class="heat-main"><div class="heat-wrap' + ((!live || stale) ? ' recede' : '') + '">' +
      tbl + '</div></div>' + vlegend + '</div>';

    var srow = host.querySelector('.spotrow');
    if (srow && srow.scrollIntoView) srow.scrollIntoView({ block: 'center' });
    host.querySelectorAll('.hcell').forEach(function (c) {
      c.addEventListener('click', function () {   // the shared selection: every panel follows this strike
        if (window.EdShell) window.EdShell.setStrike(Number(c.getAttribute('data-strike')), c.getAttribute('data-expiry'));
      });
    });
    var firstRow = host.querySelector('tbody tr');
    var rowPx = firstRow && firstRow.getBoundingClientRect ? firstRow.getBoundingClientRect().height : 0;
    window.EdShell.wireStrikeAxis(host.querySelectorAll('.hstrike, .hcorner'), host.querySelector('.heat-wrap'), _pan, rowPx, load);
    // the shared selection starts on the spot strike and the front expiry (never over a choice made)
    var spotRow = cells.filter(function (c) { return c.spot; })[0];
    var front = exps.filter(function (e) { return e.front; })[0];
    if (window.EdShell.getState().selStrike == null && spotRow) {
      window.EdShell.setStrike(spotRow.strike, window.EdShell.getExpiry() || (front ? front.expiry : null));
    }
    applyStrikeHighlight(host);
    paintChip(view.coverage);
  }

  function applyStrikeHighlight(host) {
    host = host || document.getElementById('heatBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.hcell.sel-strike').forEach(function (n) { n.classList.remove('sel-strike'); });
    if (sel == null) return;
    host.querySelectorAll('.hcell[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('sel-strike'); });
  }

  // how many expiry columns fit the panel at a legible width (a measurement of the page, sent with
  // the read; the server picks which columns)
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

  // gamma, dex and oi are the same heatmap pane under three subview ids
  function _isGammaFamilySubview(sv) { return sv === 'gamma' || sv === 'dex' || sv === 'oi'; }
  function stillCurrent(ticker) {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && _isGammaFamilySubview(s.subview) && s.view === 'heatmap' && (s.ticker || '') === ticker;
  }
  function surfaceUrl(ticker, host) {
    var expiry = window.EdShell.getExpiry();
    return '/api/options/gamma-surface?ticker=' + encodeURIComponent(ticker) +
      window.EdShell.windowQuery(_pan) + '&cols=' + autoColCount(host) +
      (expiry ? '&expiry=' + encodeURIComponent(expiry) : '');
  }
  // only the network fetch is coalesced (keyed on ticker: a newer ticker aborts the older read)
  function loadImpl(ticker, signal) {
    var host = document.getElementById('heatBody');
    if (!host || !stillCurrent(ticker)) return;
    return fetch(surfaceUrl(ticker, host), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillCurrent(ticker)) renderSurface(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;   // superseded by a newer read -- that one renders
        if (stillCurrent(ticker)) renderSurface(host, { available: false, ticker: ticker, reason: 'no console serving /api/options/gamma-surface' });
      });
  }
  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(_pendingTicker, signal); });
  function load() {
    var host = document.getElementById('heatBody');
    if (!host) return;
    var st = (window.EdShell && window.EdShell.getState()) || {};
    if (st.workspace !== 'options' || !_isGammaFamilySubview(st.subview) || st.view !== 'heatmap') {
      // leaving the heatmap: its demand is cleared at once, never behind an in-flight read
      window.EdStream.setAdditionalContracts([], _heatmapOwnerKey(_pendingTicker));
      _pendingTicker = null;
      return;
    }
    var nextTicker = st.ticker || '';
    if (_pendingTicker && _pendingTicker !== nextTicker) {
      window.EdStream.setAdditionalContracts([], _heatmapOwnerKey(_pendingTicker));   // the ticker just left
    }
    if (_panTicker !== nextTicker) { _pan.centre = null; _pan.shift = 0; _panTicker = nextTicker; }
    _pendingTicker = nextTicker;
    _loader.trigger(_pendingTicker);
  }
  function rerender() {   // a presentation change on the window on screen: no read needed
    var h = document.getElementById('heatBody'); if (!h) return;
    _lastRevision = null;
    if (_lastSurface) renderSurface(h, _lastSurface); else load();
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'levels') load(); });
    document.addEventListener('ed:strike', function () { applyStrikeHighlight(); });
    document.addEventListener('ed:theme', rerender);
    document.addEventListener('ed:measure', rerender);
    document.addEventListener('ed:expiry', load);   // a new window: the server picks it
    document.addEventListener('ed:scope', load);
    if (typeof window !== 'undefined' && window.addEventListener) window.addEventListener('resize', load);
  }

  var _root = (typeof window !== 'undefined') ? window : (typeof globalThis !== 'undefined' ? globalThis : this);
  _root.EdGamma = { formatUsd: formatUsd };
})();
