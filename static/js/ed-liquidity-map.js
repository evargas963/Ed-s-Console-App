/* Ed Console — Liquidity / "Map" subview. PRESENTATION ONLY, computes nothing.
   The zones the `liquidity` panel carries (support / resistance / value bands, each with its
   served label, side and confluence score) on the one TradingView-style chart every chart in the
   console uses (ed-tv-chart.js), over the price (the `bars` panel, completed Schwab bars, the toolbar's timeframe),
   with the prior-day and overnight levels and the live price from the levels panel on the page's
   socket -- the one level producer. The zone list below the chart names each zone's source levels. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '-' : Number(n).toFixed(d == null ? 2 : d); }
  function isMap() { var s = window.EdShell.getState(); return s.workspace === 'liquidity' && s.subview === 'map'; }
  function ticker() { return window.EdShell.getState().ticker; }
  function host() { return document.getElementById('liqmBody'); }
  // the reference levels this map draws, by their served family
  var REF_FAMILIES = { prior_day: 1, overnight: 1 };

  var _chart = null;
  // the map's timeframe (the toolbar's), kept per viewer
  var _tf = (function () { try { return window.localStorage.getItem('ed.liqm.tf') || '5'; } catch (e) { return '5'; } })();
  function ensureChart(h) {
    if (_chart && h.querySelector('.liqm-plot')) return _chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    h.innerHTML = '<div class="liqm-tb"></div><div class="liqm-plot"></div><div class="liqm-empty" hidden></div><div class="liqm-zones"></div>' +
      '<div class="fl-foot">Zones from the liquidity panel; prior-day and overnight levels and the price from the levels and bars panels. The map arranges them; it computes nothing.</div>';
    _chart = window.EdTvChart.create(h.querySelector('.liqm-plot'), { nearestN: 99 });
    window.EdTvChart.toolbar(h.querySelector('.liqm-tb'), _chart, { tf: _tf, styleKey: 'ed.liqm.style',
      onTf: function (tf) { _tf = tf; try { window.localStorage.setItem('ed.liqm.tf', tf); } catch (e) { /* per-viewer only */ } load(); } });
    return _chart;
  }

  function zoneRow(z) {
    var tags = (z.source_levels || []).map(function (l) { return esc(l.label) + ' ' + num(l.value); }).join(' · ');
    return '<div class="fl-row"><span class="k">' + esc(z.zone_label) + ' ' + num(z.zone_low) + '–' + num(z.zone_high) + '</span>' +
      '<span class="v">confluence ' + esc(z.confluence_score) + '</span></div>' +
      '<div class="sm liqm-tags">' + (tags || '-') + (z.interpretation_notes ? ' — ' + esc(z.interpretation_notes) : '') + '</div>';
  }

  // a panel as served: one not received yet, or one the program could not produce, draws nothing
  function served(p) { return p && p.failed == null ? p : null; }
  function render(h, tk) {
    var c = ensureChart(h); if (!c) return;
    var P = c.palette();
    var side = { support: P.up, resistance: P.down, value: P.ink3 };
    var snap = served(_panels.liquidity), levels = served(_panels.levels), barsD = served(_panels.bars);
    // the program's words for each panel it could not produce, never drawn as empty
    var words = [_panels.liquidity, _panels.bars, _panels.levels]
      .filter(function (p) { return p && p.failed != null; }).map(function (p) { return p.failed; });
    var zones = snap ? snap.zones : [];
    c.setBars(barsD ? barsD.bars : [], barsD ? barsD.tf : _tf, window.EdShell.getState().display || tk, barsD && barsD.last_bar && barsD.last_bar.label);
    c.setZones(zones.map(function (z) {
      return { lo: z.zone_low, hi: z.zone_high, color: side[z.zone_side] || P.ink3, label: z.zone_label + ' · ' + z.confluence_score + '×' };
    }));
    c.setLevels((levels ? levels.levels : []).filter(function (l) { return REF_FAMILIES[l.family] && l.price != null; })
      .map(function (l) { return { id: l.id, price: Number(l.price), label: l.short, color: P.stale, style: 2, width: 1 }; }));
    var spot = (levels && levels.spot != null) ? Number(levels.spot) : null;
    c.setLivePrice(spot, null, (spot != null && levels.spot_time_ct != null) ? levels.spot_time_ct : null);
    var empty = h.querySelector('.liqm-empty');
    empty.hidden = !words.length;
    empty.textContent = words.join(' · ');
    var none = !snap ? '-' : snap.reason ? esc(snap.reason) : 'no zones for this session yet';
    h.querySelector('.liqm-zones').innerHTML = '<div class="fl-sec"><div class="fl-sec-h">Zones (confluence-scored)</div>' +
      (zones.length ? zones.map(zoneRow).join('') : '<div class="sm">' + none + '</div>') + '</div>';
  }

  // The zones, the levels and the bars at the toolbar's timeframe: the `liquidity:map`,
  // `levels:liquidity` and `bars:liq` panels (server.liquidity, server.levels, server.bars) the
  // program sends on the page's socket while the map is on, at once and each time one changes;
  // each for the ticker on screen.
  var PANELS = { 'liquidity:map': 'liquidity', 'levels:liquidity': 'levels', 'bars:liq': 'bars' };
  var _panels = {}, _panelsTicker = null;
  function load() {
    var on = isMap();
    if (_panelsTicker !== ticker()) { _panelsTicker = ticker(); _panels = {}; }
    window.EdShell.showPanel('liquidity:map', on ? {} : null);
    window.EdShell.showPanel('levels:liquidity', on ? { tf: '1' } : null);
    window.EdShell.showPanel('bars:liq', on ? { tf: _tf, limit: window.EdTvChart.BARS_LIMIT[_tf] } : null);
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:panel', function (e) {
      var key = PANELS[e.detail.type], h = host();
      if (!key) return;
      _panels[key] = e.detail;
      if (h && isMap()) render(h, ticker());
    });
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdLiquidityMap = { state: function () { return _chart ? _chart.state() : null; } };
})();
