/* Ed Console — Liquidity / "Map" subview. PRESENTATION ONLY, computes nothing.
   The zones /api/liquidity-snapshot computes (support / resistance / value bands, each with its
   served label, side and confluence score) on the one TradingView-style chart every chart in the
   console uses (ed-tv-chart.js), over the price (/api/bars1m, completed Schwab bars, the toolbar's timeframe),
   with the prior-day levels from /api/levels -- the one level route -- and the live price from
   the header's price row (ed:quote_tick). The zone list below the chart names each zone's source
   levels, the time of each of their two inputs (the bars, the option levels), and each input
   they lacked with its reason. */
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
  var REF_FAMILIES = { prior_day: 1 };

  var _chart = null;
  var _liveQuote = null;          // the header's price row (ed:quote_tick), the one displayed price
  // the map's timeframe (the toolbar's), kept per viewer
  var _tf = (function () { try { return window.localStorage.getItem('ed.liqm.tf') || '5'; } catch (e) { return '5'; } })();
  function ensureChart(h) {
    if (_chart && h.querySelector('.liqm-plot')) return _chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    h.innerHTML = '<div class="liqm-tb"></div><div class="liqm-plot"></div><div class="liqm-empty" hidden></div><div class="liqm-zones"></div>' +
      '<div class="fl-foot">Zones from /api/liquidity-snapshot; prior-day levels from /api/levels; bars from /api/bars1m; the live price from the header\'s price row. The map arranges them; it computes nothing.</div>';
    _chart = window.EdTvChart.create(h.querySelector('.liqm-plot'), { nearestN: 99 });
    window.EdTvChart.toolbar(h.querySelector('.liqm-tb'), _chart, { tf: _tf, styleKey: 'ed.liqm.style',
      onTf: function (tf) { _tf = tf; try { window.localStorage.setItem('ed.liqm.tf', tf); } catch (e) { /* per-viewer only */ } load(); } });
    return _chart;
  }

  function zoneRow(z) {
    var tags = (z.source_levels || []).map(function (l) { return esc(l.label) + ' ' + num(l.value); }).join(' · ');
    return '<div class="fl-row"><span class="k">' + esc(z.zone_label) + ' ' + num(z.zone_low) + '–' + num(z.zone_high) + '</span>' +
      '<span class="v">confluence ' + esc(z.confluence_score) + '</span></div>' +
      '<div class="sm liqm-tags">' + (tags || '—') + '</div>';
  }
  function paintLive() {
    var q = _liveQuote, mine = q && q.ticker === st().key && q.spot_state === 'live';
    if (_chart) _chart.setLivePrice(mine ? q.spot : null, mine ? q.trade_age_sec : null);
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
    paintLive();
    var empty = h.querySelector('.liqm-empty');
    empty.hidden = !!(snap && snap.zones !== undefined);
    empty.textContent = empty.hidden ? '' : 'the liquidity snapshot request failed for ' + tk;
    // what the zones lacked, each with its served reason
    var absent = ((snap && snap.absent) || []).map(function (a) {
      return '<div class="sm liqm-absent">' + esc(a.input) + ': ' + esc(a.reason) + '</div>'; }).join('');
    // the zones' two inputs, each as served: the newest bar's time, and the option levels'
    // age, or the time they are as of after the close, or STALE with the reason
    var o = snap && snap.option_levels, closed = !!o && o.levels_market_closed === true, badge = window.EdShell.asOfBadge;
    var inputs = (snap && snap.levels_as_of ? badge({ label: 'bars as of ' + snap.levels_as_of }) : '') +
      (o ? ' ' + badge({ label: 'option levels' + (closed && o.levels_as_of ? ' as of ' + o.levels_as_of : ''),
        ageSec: closed ? null : o.levels_age_sec, stale: o.levels_stale === true, reason: o.levels_stale_reason,
        ref: closed, live: o.levels_stale === false && !closed }) : '');
    h.querySelector('.liqm-zones').innerHTML = '<div class="fl-sec"><div class="fl-sec-h">Zones (confluence-scored, /api/liquidity-snapshot) ' +
      '<span class="liqm-inputs">' + inputs + '</span></div>' +
      (o && o.levels_stale ? '<div class="sm liqm-absent">option levels: ' + esc(o.levels_stale_reason) + '</div>' : '') +
      (zones.length ? zones.map(zoneRow).join('') : '<div class="sm">' + esc((snap && snap.reason) || 'no zones for this session yet') + '</div>') +
      absent + '</div>';
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
    window.addEventListener('ed:quote_tick', function (e) {
      var q = e.detail; if (!q || q.ticker !== st().key) return;
      _liveQuote = q; if (isMap()) paintLive();
    });
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdLiquidityMap = { state: function () { return _chart ? _chart.state() : null; } };
})();
