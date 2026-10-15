/* Ed Console — Options/Gamma Chart view. PRESENTATION ONLY.
   On the one TradingView-style chart every chart in the console uses (ed-tv-chart.js): the price
   (completed Schwab bars at the toolbar's timeframe: the daemon's 1-minute series, /api/bars1m above it), the flip and the walls (/api/terrain) as level
   lines, the live price (the header's price row), and the selected measure's per-strike rows
   (/api/terrain/strikes: GEX `today.all`, DEX and OI `measures`) as a profile on the price axis --
   bars, or dots sized by magnitude (Dot Map). The same view serves the Gamma, Delta / DEX and Open
   Interest subviews. The strikes shown are the window the server sends for the Gamma scope. A click
   on a strike selects it for every panel. The page computes no exposure or level. */
(function () {
  'use strict';

  var usd = window.EdGamma.formatUsd;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function ctTime(sec) { try { return new Date(sec * 1000).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', timeZone: 'America/Chicago' }); } catch (e) { return ''; } }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isChart() {
    var s = st();
    return s.workspace === 'options' && ['gamma', 'dex', 'oi'].indexOf(s.subview) !== -1 && s.view === 'chart';
  }
  // the served profile for the selected measure: {rows (the window), its scale (the window's
  // largest |value|), max_abs_row, name}
  function served(sd) {
    var m = st().measure, x = sd && sd.measures && sd.measures[m];
    if (x) return { rows: x.rows || [], scale: (x.view || {}).max_abs, max_abs_row: x.max_abs_row,
      name: m === 'oi' ? 'OI' : 'DEX', signed: m !== 'oi' };
    return { rows: (sd && sd.today && sd.today.all) || [], scale: sd && sd.views && sd.views.all && sd.views.all.max_abs,
      max_abs_row: sd && sd.max_abs_row, name: 'GEX', signed: true };
  }
  function ticker() { return st().ticker || ''; }

  var _mode = 'profile';          // 'profile' (bars) | 'dotmap' (dots)
  var _chart = null;
  var _liveQuote = null;          // the header's price row (ed:quote_tick), the one displayed price
  var _last = { bars: undefined, strikes: undefined, terrain: undefined };
  // the chart's timeframe (the toolbar's), kept per viewer in the shell's view
  function tf() { return st().tfs.chart; }
  function tfLabel() { return window.EdTvChart.TFS.filter(function (t) { return t.id === tf(); })[0].lbl; }

  function liveSpot() {   // the row whose served key is the selected instrument's (EdShell state.key)
    var q = _liveQuote;
    return (q && q.ticker === st().key && q.spot != null) ? Number(q.spot) : null;
  }
  function ensureChart() {
    var host = document.getElementById('chartBody');
    if (!host || !window.EdTvChart || !window.LightweightCharts) return null;
    if (_chart && host.querySelector('.gchart-plot')) return _chart;
    host.innerHTML = '<div class="gchart-head"></div><div class="gchart-tb"></div><div class="gchart-plot"></div><div class="gchart-empty" hidden></div>';
    _chart = window.EdTvChart.create(host.querySelector('.gchart-plot'), { nearestN: 99,
      onProfileClick: function (row) {
        if (!window.EdShell) return;
        var exp = window.EdShell.getExpiry ? window.EdShell.getExpiry() : null;   // the workspace's expiry filter carries through
        window.EdShell.setStrike(row.price, exp || null);
      } });
    window.EdTvChart.toolbar(host.querySelector('.gchart-tb'), _chart, { tf: tf(), styleKey: 'ed.gchart.style',
      onTf: function (t) { window.EdShell.setTf('chart', t); } });
    return _chart;
  }

  // each part as the console pushes it for the view (the bars at the chart's timeframe, the
  // window of per-strike rows GEX by Strike shows unpanned, the terrain Key Levels shows); a
  // failed answer is absent (null); a part on its way for a new view is not drawn from the old one
  [['gamma.chart.bars', 'bars'], ['gamma.chart.strikes', 'strikes'], ['gamma.chart.terrain', 'terrain']].forEach(function (p) {
    window.EdShell.onPanel(p[0], function (a) {
      _last[p[1]] = a.waiting ? undefined : a.ok ? a.body : null;
      if (isChart() && ready()) render();
    });
  });
  function ready() { return _last.bars !== undefined && _last.strikes !== undefined && _last.terrain !== undefined; }

  function render() {
    var c = ensureChart(); if (!c) return;
    var host = document.getElementById('chartBody');
    var P = c.palette(), barsD = _last.bars, sd = _last.strikes, t = _last.terrain;
    var bars = (barsD && barsD.bars) || [];
    var prof = served(sd);
    var win = prof.rows.filter(function (r) { return r[1] != null; });   // the served window; unknown: nothing drawn
    c.setBars(bars, barsD ? barsD.tf : tf(), st().display || ticker(), barsD && barsD.last_bar && barsD.last_bar.label);
    c.setProfile(win.map(function (r) {
      return { price: Number(r[0]), value: Number(r[1]), color: !prof.signed ? P.accent : r[1] >= 0 ? P.up : P.down }; }),
      prof.scale, _mode === 'dotmap' ? 'dots' : 'bars');
    c.selectProfile(st().selStrike == null ? null : Number(st().selStrike));
    var lv = [];
    if (t && !t.error) {
      if (t.gamma_flip != null) lv.push({ id: 'gamma_flip', price: Number(t.gamma_flip), label: 'flip', color: P.accent, style: 2, width: 1 });
      if (t.call_wall != null) lv.push({ id: 'call_wall', price: Number(t.call_wall), label: 'call wall', color: P.down, style: 0, width: 1 });
      if (t.put_wall != null) lv.push({ id: 'put_wall', price: Number(t.put_wall), label: 'put wall', color: P.up, style: 0, width: 1 });
    }
    c.setLevels(lv);
    var spot = liveSpot();
    c.setLivePrice(spot, _liveQuote && spot != null ? window.EdShell.tradeLabel(_liveQuote) : null);
    var empty = host.querySelector('.gchart-empty');
    empty.hidden = !!(bars.length || win.length);
    empty.textContent = empty.hidden ? '' : (barsD || sd ? 'no bars / per-strike ' + prof.name + ' for this symbol'
      : 'the bars and per-strike ' + prof.name + ' requests failed');
    paintHead(host.querySelector('.gchart-head'), bars, win, prof, sd, spot);
  }
  function paintHead(el, bars, win, prof, sd, spot) {
    var n = prof.name;
    var ab = (window.EdShell && window.EdShell.asOfBadge) || function () { return ''; };
    var lastT = bars.length ? bars[bars.length - 1].t : null;
    var src = sd && sd.today_source;
    var asof = (lastT ? '<span class="asof">price ' + tfLabel() + ' · ' + ctTime(lastT) + ' CT</span>' : '') +
      (src ? ab({ label: n + ' ' + (src === 'terrain_live_cache' ? 'terrain live' : src), ageOf: 'levels',
        stale: !!sd.levels_stale, reason: sd.levels_stale_reason, live: src === 'terrain_live_cache' && sd.levels_stale === false }) : '');
    var top = prof.max_abs_row;   // served: the largest-magnitude row
    var shown = top ? (prof.signed ? usd(top[1]) : Number(top[1]).toLocaleString('en-US') + ' contracts') : '';
    el.innerHTML = (asof ? '<div class="chart-asof">' + asof + '</div>' : '') +
      '<div class="chart-legend">' + (prof.signed
        ? '<span><span class="sw" style="background:var(--ed-pos)"></span>+' + n + '</span>' +
          '<span><span class="sw" style="background:var(--ed-neg)"></span>−' + n + '</span>'
        : '<span><span class="sw" style="background:var(--ed-accent)"></span>' + n + '</span>') +
      '<span><span class="sw" style="background:var(--ed-accent)"></span>flip</span>' +
      '<span>spot ' + (spot == null ? '—' : spot.toFixed(2)) + '</span>' +
      (top ? '<span>largest |' + n + '| ' + esc(top[0]) + ' · ' + esc(shown) + '</span>' : '') + '</div>';
  }

  function bindModes() {
    var host = document.getElementById('chartModes');
    if (!host) return;
    host.querySelectorAll('.cmode').forEach(function (b) {
      b.addEventListener('click', function () {
        _mode = b.getAttribute('data-cmode');
        host.querySelectorAll('.cmode').forEach(function (x) { x.classList.toggle('on', x === b); });
        if (_chart) render();
      });
    });
  }

  window.addEventListener('ed:quote_tick', function (ev) {
    var q = (ev && ev.detail) || {};
    if (q.ticker !== st().key) return;
    _liveQuote = q;
    if (isChart() && _chart && ready()) render();
  });
  document.addEventListener('ed:measure', function () { if (_chart && isChart() && ready()) render(); });
  document.addEventListener('ed:strike', function () { if (_chart && isChart()) _chart.selectProfile(st().selStrike == null ? null : Number(st().selStrike)); });
  bindModes();
  // read-only view for tests (e2e) -- never a control surface
  window.EdGammaChart = {
    state: function () { return _chart ? _chart.state() : null; },
    profilePoint: function (price) { return _chart ? _chart.profilePoint(price) : null; }
  };
})();
