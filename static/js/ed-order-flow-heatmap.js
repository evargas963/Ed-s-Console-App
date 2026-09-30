/* Ed Console — Order Flow / "Heatmap" subview. PRESENTATION ONLY.
   The book with a time dimension: /api/order-flow/book-heatmap serves the time x price grid of
   the selected Schwab book's displayed size (NYSE_BOOK or NASDAQ_BOOK, never combined), and this
   view draws it on the one TradingView-style chart every chart in the console uses
   (ed-tv-chart.js): the served buckets are the time axis, each served cell is drawn at its own
   bucket and price -- green where the bid side is served dominant, red the ask, brightness its
   size against the served max_size. Nothing is summed, re-binned or interpolated. */
(function () {
  'use strict';

  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isHeatmap() { var s = st(); return s.workspace === 'order-flow' && s.subview === 'heatmap'; }
  function ticker() { return (st().ticker || ''); }
  function stillHeatmap(tk) { return isHeatmap() && ticker() === tk; }
  function fmtCT(ts) {
    try { return new Date(ts * 1000).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit' }); } catch (e) { return '—'; }
  }

  var _minutes = 60, _chart = null;
  function host() { return document.getElementById('ofhBody'); }
  function ensureChart(h) {
    if (_chart && h.querySelector('.ofh-plot')) return _chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    h.innerHTML = '<div class="ofh-plot"></div><div class="ofh-empty" hidden></div><div class="fl-foot ofh-foot"></div>';
    _chart = window.EdTvChart.create(h.querySelector('.ofh-plot'), { nearestN: 0 });
    return _chart;
  }

  function render(h, tk, d) {
    var c = ensureChart(h); if (!c) return;
    var ok = !!(d && d.available && d.display_lo != null);
    c.setHeatmap(ok ? d : null);
    var empty = h.querySelector('.ofh-empty');
    empty.hidden = ok;
    empty.textContent = ok ? '' : !d ? 'the book heatmap request failed' : !d.available ? ((d.reason) || 'no book history for ' + tk)
      : 'rows were captured but carried no populated price levels';
    h.querySelector('.ofh-foot').textContent = !ok ? '' : d.rows_scanned + (d.rows_capped ? '+ (capped)' : '') + ' book ticks · ' +
      fmtCT(d.since_ts) + '–' + fmtCT(d.until_ts) + ' CT · latest capture ' + fmtCT(d.latest_captured_ts) + ' CT — every cell is a captured book tick; nothing is interpolated between ticks.';
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillHeatmap(tk)) return;
    return fetch('/api/order-flow/book-heatmap?ticker=' + encodeURIComponent(tk) + '&venue=' + st().bookVenue + '&minutes=' + _minutes, { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillHeatmap(tk)) render(h, tk, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillHeatmap(tk)) render(h, tk, null);
      });
  }
  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); });
  function load() {
    if (!isHeatmap()) return;
    // keyed on ticker + venue + minutes: a different window while a fetch is in flight aborts it
    _loader.trigger(ticker() + '|' + st().bookVenue + '|' + _minutes);
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:book_venue', load);
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'flow') load(); });
    document.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-ofh-minutes]');
      if (!btn) return;
      _minutes = Number(btn.getAttribute('data-ofh-minutes')) || 60;
      document.querySelectorAll('[data-ofh-minutes]').forEach(function (b) { b.classList.toggle('on', b === btn); });
      load();
    });
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdBookHeatmap = { state: function () { return _chart ? _chart.state() : null; } };
})();
