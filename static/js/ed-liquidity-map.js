/* Ed Console — Liquidity / "Map" subview. PRESENTATION ONLY, computes nothing.
   The zones /api/liquidity-snapshot computes (support / resistance / value bands, each with its
   served label, side and confluence score) on the one TradingView-style chart every chart in the
   console uses (ed-tv-chart.js), over the price (/api/bars1m, completed Schwab bars, the toolbar's timeframe),
   with the prior-day and overnight levels and the live price from /api/levels -- the one level
   route. The zone list below the chart names each zone's source levels. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isMap() { var s = st(); return s.workspace === 'liquidity' && s.subview === 'map'; }
  function ticker() { return (st().ticker || ''); }
  function host() { return document.getElementById('liqmBody'); }
  function stillMap(tk) { return isMap() && ticker() === tk; }
  function fetchJson(url, signal) {
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) { return r.ok ? r.json() : null; });
  }
  // the reference levels this map draws, by their served family
  var REF_FAMILIES = { prior_day: 1, overnight: 1 };

  var _chart = null;
  // the map's timeframe (the toolbar's), kept per viewer
  var _tf = (function () { try { return window.localStorage.getItem('ed.liqm.tf') || '5'; } catch (e) { return '5'; } })();
  function ensureChart(h) {
    if (_chart && h.querySelector('.liqm-plot')) return _chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    h.innerHTML = '<div class="liqm-tb"></div><div class="liqm-plot"></div><div class="liqm-empty" hidden></div><div class="liqm-zones"></div>' +
      '<div class="fl-foot">Zones from /api/liquidity-snapshot; prior-day and overnight levels and the price from /api/levels and /api/bars1m. The map arranges them; it computes nothing.</div>';
    _chart = window.EdTvChart.create(h.querySelector('.liqm-plot'), { nearestN: 99 });
    window.EdTvChart.toolbar(h.querySelector('.liqm-tb'), _chart, { tf: _tf, styleKey: 'ed.liqm.style',
      onTf: function (tf) { _tf = tf; try { window.localStorage.setItem('ed.liqm.tf', tf); } catch (e) { /* per-viewer only */ } load(); } });
    return _chart;
  }

  function zoneRow(z) {
    var tags = (z.source_levels || []).map(function (l) { return esc(l.label) + ' ' + num(l.value); }).join(' · ');
    return '<div class="fl-row"><span class="k">' + esc(z.zone_label) + ' ' + num(z.zone_low) + '–' + num(z.zone_high) + '</span>' +
      '<span class="v">confluence ' + esc(z.confluence_score) + '</span></div>' +
      '<div class="sm liqm-tags">' + (tags || '—') + (z.interpretation_notes ? ' — ' + esc(z.interpretation_notes) : '') + '</div>';
  }

  function render(h, tk, snap, levels, barsD) {
    var c = ensureChart(h); if (!c) return;
    var P = c.palette();
    var side = { support: P.up, resistance: P.down, value: P.ink3 };
    var zones = (snap && snap.zones) || [];
    c.setBars((barsD && barsD.bars) || [], (barsD && barsD.tf) || _tf, st().display || tk, barsD && barsD.last_bar && barsD.last_bar.label);
    c.setZones(zones.map(function (z) {
      return { lo: z.zone_low, hi: z.zone_high, color: side[z.zone_side] || P.ink3, label: z.zone_label + ' · ' + z.confluence_score + '×' };
    }));
    c.setLevels(((levels && levels.levels) || []).filter(function (l) { return REF_FAMILIES[l.family] && l.price != null; })
      .map(function (l) { return { id: l.id, price: Number(l.price), label: l.short, color: P.stale, style: 2, width: 1 }; }));
    c.setLivePrice(levels && levels.spot != null ? Number(levels.spot) : null, null);
    var empty = h.querySelector('.liqm-empty');
    empty.hidden = !!(snap && snap.zones !== undefined);
    empty.textContent = empty.hidden ? '' : 'the liquidity snapshot request failed for ' + tk;
    h.querySelector('.liqm-zones').innerHTML = '<div class="fl-sec"><div class="fl-sec-h">Zones (confluence-scored, /api/liquidity-snapshot)</div>' +
      (zones.length ? zones.map(zoneRow).join('') : '<div class="sm">no zones for this session yet</div>') + '</div>';
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillMap(tk)) return;
    return Promise.all([
      fetchJson('/api/liquidity-snapshot?ticker=' + encodeURIComponent(tk), signal),
      fetchJson('/api/levels?ticker=' + encodeURIComponent(tk), signal),
      fetchJson('/api/bars1m?ticker=' + encodeURIComponent(tk) + '&tf=' + _tf + '&limit=' + window.EdTvChart.BARS_LIMIT[_tf], signal)
    ]).then(function (r) {
      if (stillMap(tk)) render(h, tk, r[0], r[1], r[2]);
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      if (stillMap(tk)) render(h, tk, null, null, null);
    });
  }
  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); });
  function load() { if (isMap()) _loader.trigger(ticker()); }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'levels' || e.detail.kind === 'liquidity') load(); });
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdLiquidityMap = { state: function () { return _chart ? _chart.state() : null; } };
})();
