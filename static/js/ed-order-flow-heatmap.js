/* Ed Console — Order Flow / "Heatmap" subview. PRESENTATION ONLY.
   The book with a time dimension: the `bookmap` panel carries the time x price grid of
   the selected Schwab book's displayed size (NYSE_BOOK or NASDAQ_BOOK, never combined), and this
   view draws it on the one TradingView-style chart every chart in the console uses
   (ed-tv-chart.js): the served buckets are the time axis, each served cell is drawn at its own
   bucket and price -- green where the bid side is served dominant, red the ask, brightness its
   size against the served max_size. Nothing is summed, re-binned or interpolated. */
(function () {
  'use strict';

  function isHeatmap() { var s = window.EdShell.getState(); return s.workspace === 'order-flow' && s.subview === 'heatmap'; }
  function fmtCT(ts) {
    try { return new Date(ts * 1000).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit' }); } catch (e) { return '-'; }
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

  function render(h, d) {
    var c = ensureChart(h); if (!c) return;
    var ok = !!(d.available && d.display_lo != null);
    c.setHeatmap(ok ? d : null);
    var empty = h.querySelector('.ofh-empty');
    empty.hidden = ok;
    empty.textContent = ok ? '' : !d.available ? d.reason
      : 'rows were captured but carried no populated price levels';
    h.querySelector('.ofh-foot').textContent = !ok ? '' : d.rows_scanned + ' books · ' +
      fmtCT(d.since_ts) + '–' + fmtCT(d.until_ts) + ' CT · latest capture ' + fmtCT(d.latest_captured_ts) + ' CT — every cell is a captured book tick; nothing is interpolated between ticks.';
  }

  // The grid is the `bookmap` panel (server.bookmap) on the page's socket while this view is on,
  // for the selected venue and window, at once and with each streamed quote or book.
  function load() {
    if (!isHeatmap()) { window.EdShell.showPanel('bookmap', null); return; }
    window.EdShell.showPanel('bookmap', { venue: window.EdShell.getState().bookVenue, minutes: _minutes });
  }
  document.addEventListener('ed:panel', function (e) {
    var d = e.detail, h = host();
    if (d.type !== 'bookmap' || !h || !isHeatmap()) return;
    render(h, d.failed != null ? { available: false, reason: d.failed } : d);
  });

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:book_venue', load);
    document.addEventListener('ed:book_window', load);
    document.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-ofh-minutes]');
      if (!btn) return;
      _minutes = Number(btn.getAttribute('data-ofh-minutes')) || 60;
      document.querySelectorAll('[data-ofh-minutes]').forEach(function (b) { b.classList.toggle('on', b === btn); });
      window.EdShell.emit('ed:book_window', { minutes: _minutes });
    });
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdBookHeatmap = { state: function () { return _chart ? _chart.state() : null; } };
})();
