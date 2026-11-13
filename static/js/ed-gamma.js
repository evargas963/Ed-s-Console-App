/* Ed Console — Options/Gamma heatmap view. PRESENTATION ONLY.
   Shows the page's socket's `surface` panel in the window it asks (scope, the columns it fits,
   the selected expiry, a pan) and draws exactly the cells the program sends: the server picks the
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

  // ---- theme colour: sign -> green/red, shade -> the shell's one strength rule against the
  // served scale (EdShell.heatFill) ----
  function _rgb(c) { return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; }
  function cellStyle(n, maxAbs, colors) {
    if (n === null || n === undefined || isNaN(n)) return { bg: 'transparent', fg: 'var(--ed-ink-3)', empty: true };
    var v = Number(n);
    if (v === 0) return { bg: _rgb(colors.zero), fg: 'var(--ed-ink-3)', empty: false };
    var mixed = window.EdShell.heatFill(v, maxAbs, colors);   // the served scale is at least every |value| drawn
    if (mixed == null) return { bg: 'transparent', fg: 'var(--ed-ink-3)', empty: false };
    return { bg: _rgb(mixed), fg: window.EdShell.heatInk(mixed), empty: false };
  }
  // the selected measure's value per column: GEX/DEX a value, OI/volume the server's total
  function _measureRow(row, measure) {
    if (measure === 'oi' || measure === 'volume') {
      return row[measure].map(function (cp) { return cp ? cp.total : null; });
    }
    return row[measure];
  }

  // the words for each cell's and column's streaming state, served in the page (meta
  // ed-stream-words, server.STREAM_WORDS)
  var WORDS = JSON.parse(document.querySelector('meta[name="ed-stream-words"]').getAttribute('content'));
  var _pan = window.EdShell.newPan();
  var _panTicker = null;
  var _lastSurface = null, _lastRevision = null;

  function paintChip(cov) {   // the header's coverage chip: the served words
    var el = document.getElementById('heatScope'); if (!el) return;
    el.textContent = cov ? cov.label : '';
    el.title = cov ? cov.title : '';
    el.className = 'sub cov' + (cov ? ' cov-' + cov.state : '');
  }
  function buildBanner(surface) {
    if (surface.available !== false) {
      // a surface is shown: its levels' served word (levels_state: CLOSE, STALE, NOT LIVE), the
      // chain's time and age; nothing while it is LIVE
      if (surface.levels_state === 'LIVE') return '';
      var words = [surface.levels_state, surface.levels_time_ct, surface.levels_age_text]
        .filter(function (w) { return w; }).join(' · ');
      return '<div class="heat-banner ' + (surface.levels_state === 'STALE' ? 'stale' : '') + '" title="' +
        escapeHtml(surface.levels_stale_reason || surface.levels_state) + '"><span class="hb-main">' + escapeHtml(words) +
        '</span><span class="hb-more" aria-label="details">details</span></div>';
    }
    // no surface: why, from the served flags (warming: its chain is coming; requested: a page asked)
    var warming = surface.warming === true, requested = !warming && surface.requested === true;
    var stateLabel = warming ? 'LIVE SURFACE WARMING' : requested ? 'LIVE SURFACE REQUESTED' : '';
    var brief = 'no live surface for this symbol';
    return '<div class="heat-banner ' + (stateLabel ? 'warming' : '') + '" title="' + escapeHtml(surface.reason || brief) +
      '"><span class="hb-main">' + (stateLabel ? stateLabel + ' · ' : '') + brief +
      '</span><span class="hb-more" aria-label="details">details</span></div>';
  }
  function applyStatus(host, surface) {   // refresh status WITHOUT rebuilding the table
    Array.prototype.slice.call(host.querySelectorAll('.heat-banner')).forEach(function (n) { n.remove(); });
    var b = buildBanner(surface);
    if (b) host.insertAdjacentHTML('afterbegin', b);
    var wrap = host.querySelector('.heat-wrap');
    if (wrap) wrap.classList.toggle('recede', surface.levels_state !== 'LIVE');
    paintChip(surface.view.coverage);
  }

  // ---- render the window the server sent (no math on its values) ----
  function renderSurface(host, surface) {
    if (surface.failed != null || surface.available === false) {   // not produced, or not held: why
      _lastSurface = null; _lastRevision = null;
      paintChip(null);
      host.innerHTML = (surface.failed != null ? '' : buildBanner(surface)) +
        '<div class="placeholder"><div class="big">Gamma surface unavailable</div>' +
        '<div class="sm">' + escapeHtml(surface.failed != null ? surface.failed : surface.reason) + '</div></div>';
      return;
    }
    var view = surface.view;
    window.EdShell.panServed(_pan, view.centre);
    if (view.missing_expiry) {   // the selected expiry is not in this surface: nothing is drawn
      _lastSurface = surface; _lastRevision = null;
      paintChip(null);
      host.innerHTML = '<div class="placeholder"><div class="big">Expiry ' + escapeHtml(view.missing_expiry) +
        ' unavailable</div><div class="sm">not in this surface — choose another expiry, or All Expirations</div></div>';
      return;
    }
    var measure = window.EdShell.getMeasure();
    _lastSurface = surface;
    // the table is rebuilt only for a new publication or a new window, else its status refreshes
    var rev = [surface.ticker, surface.surface_seq, view.scope, view.centre, measure,
      surface.expirations.map(function (e) { return e.expiry; }).join(',')].join('|');
    if (rev === _lastRevision && host.querySelector('.heat')) {
      applyStatus(host, surface); applyStrikeHighlight(host);
      return;
    }
    _lastRevision = rev;
    var words = WORDS;
    var exps = surface.expirations, cells = surface.cells;   // always served (server._surface_view)
    var maxAbs = view.max_abs[measure], heat = window.EdShell.heatColors();
    var tbl = '<table class="heat"><thead><tr><th class="hcorner">Strike</th>';
    exps.forEach(function (e, j) {
      var dte = e.expired ? 'EXPIRED' : (e.dte === 0) ? '0DTE' : (e.dte != null ? e.dte + 'DTE' : '');
      var title = e.expired ? 'expired: a prior-session column, not current structure'
        : words.column[surface.stream_by_expiry[e.expiry]];   // the served words cover every state
      tbl += '<th class="hexp' + (e.front ? ' col-front' : '') + (e.expired ? ' expired' : '') + '" data-col="' + j +
        '" title="' + escapeHtml(title) + '"><span class="d">' + escapeHtml(e.expiry.slice(5)) +
        '</span><span class="dte">' + dte + '</span></th>';
    });
    tbl += '</tr></thead><tbody>';
    cells.slice().reverse().forEach(function (row) {   // highest strike at the top
      var mrow = _measureRow(row, measure);
      tbl += '<tr' + (row.spot ? ' class="spotrow"' : '') + '><th class="hstrike' + (row.spot ? ' spot' : '') + '">' +
        fmtStrike(row.strike) + '</th>';
      exps.forEach(function (e, j) {
        var v = mrow[j], st = cellStyle(v, maxAbs, heat);
        var cellState = row.stream[j], liveState = cellState ? cellState.state : null;
        var stateTitle = (cellState && cellState.title) || words.cell[liveState];
        tbl += '<td class="hcell' + (e.front ? ' col-front' : '') + (e.expired ? ' expired' : '') +
          (liveState ? ' state-' + liveState : '') +
          '" style="background:' + st.bg + ';color:' + st.fg + '" ' +
          (liveState ? 'data-cell-state="' + liveState + '" ' : '') +
          (stateTitle ? 'title="' + escapeHtml(stateTitle) + '" ' : '') +
          'data-strike="' + row.strike + '" data-expiry="' + escapeHtml(e.expiry) + '" data-gex="' + (v == null ? '' : v) + '">' +
          (st.empty ? '<span class="absent">-</span>'
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
      '<div class="heat-host"><div class="heat-main"><div class="heat-wrap' + (surface.levels_state !== 'LIVE' ? ' recede' : '') + '">' +
      tbl + '</div></div>' + vlegend + '</div>';

    var srow = host.querySelector('.spotrow');
    if (srow && srow.scrollIntoView) srow.scrollIntoView({ block: 'center' });
    host.querySelectorAll('.hcell').forEach(function (c) {
      c.addEventListener('click', function () {   // the shared selection: every panel follows this strike
        window.EdShell.setStrike(Number(c.getAttribute('data-strike')), c.getAttribute('data-expiry'));
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
    var sel = (window.EdShell.getState()).selStrike;
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
  var escapeHtml = window.EdShell.esc;

  // gamma, dex and oi are the same heatmap pane under three subview ids
  function _isGammaFamilySubview(sv) { return sv === 'gamma' || sv === 'dex' || sv === 'oi'; }
  function heatOn() {
    var s = window.EdShell.getState();
    return s.workspace === 'options' && _isGammaFamilySubview(s.subview) && s.view === 'heatmap';
  }
  // The heatmap is the `surface` panel (server.gamma_surface) the program sends on the page's
  // socket while the heatmap is on, in the window it asks (the scope, its pan, the columns it
  // fits, the selected expiry or null for all), at once and each time the levels change. Nothing
  // received yet for the ticker on screen is '-'.
  function load() {
    var host = document.getElementById('heatBody');
    if (!host) return;
    var nextTicker = window.EdShell.getState().ticker;   // the shell's: '' while none is chosen
    if (_panTicker !== nextTicker) {   // a new ticker, in any view: the last one's grid leaves at once
      _pan.centre = null; _pan.shift = 0; _panTicker = nextTicker;
      _lastSurface = null; _lastRevision = null;
      paintChip(null);
      window.EdShell.placeholder(host, '-');
    }
    if (!heatOn()) { window.EdShell.showPanel('surface', null); return; }
    var params = window.EdShell.windowParams(_pan);
    params.cols = autoColCount(host);
    params.expiry = window.EdShell.getExpiry();   // null, none selected: every column
    window.EdShell.showPanel('surface', params);
  }
  if (typeof document !== 'undefined') {
    document.addEventListener('ed:panel', function (e) {
      var host = document.getElementById('heatBody');
      if (e.detail.type !== 'surface' || !host || !heatOn()) return;
      try { renderSurface(host, e.detail); } catch (err) {   // said, then reported
        window.EdShell.placeholder(host, 'the page could not draw the surface the program sent');
        throw err;
      }
    });
  }
  function rerender() {   // a presentation change on the window on screen: no read needed
    var h = document.getElementById('heatBody'); if (!h) return;
    _lastRevision = null;
    if (_lastSurface) renderSurface(h, _lastSurface);
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:strike', function () { applyStrikeHighlight(); });
    document.addEventListener('ed:theme', rerender);
    document.addEventListener('ed:measure', rerender);
    document.addEventListener('ed:expiry', load);   // a new window: the server picks it
    document.addEventListener('ed:scope', load);
    document.addEventListener('ed:resize', load);   // the columns it fits change with the width
  }

  var _root = (typeof window !== 'undefined') ? window : (typeof globalThis !== 'undefined' ? globalThis : this);
  _root.EdGamma = { formatUsd: formatUsd, formatCount: formatCount };
})();
