/* Ed Console — Desk / Radar. PRESENTATION ONLY.
   Wires the main-console Desk workspace to /api/terrain/radar. Each row's spot is
   plane LAST_PRICE when fresh (server._radar_apply_plane_spot); otherwise the
   snapshot is labeled historical/as-of and must never be painted as current. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isRadar() { var s = st(); return s.workspace === 'desk' && (s.subview === 'radar' || !s.subview); }
  function host() { return document.getElementById('deskRadarBody'); }

  function rowHtml(r) {
    var current = r.current_spot != null ? r.current_spot : r.spot;
    var hist = r.snapshot_spot;
    var px = current != null ? Number(current).toFixed(2)
      : (hist != null ? Number(hist).toFixed(2) + ' as-of' : '—');
    var st = current != null
      ? (r.current_spot_state || r.spot_state || 'live')
      : (hist != null ? 'historical' : (r.spot_state || 'unavailable'));
    var gen = r.last_price_generation != null ? r.last_price_generation : '';
    return '<tr>' +
      '<td>' + esc(r.ticker) + '</td>' +
      '<td data-last-price-gen="' + esc(gen) + '">' + px + '</td>' +
      '<td>' + esc(st) + '</td>' +
      '<td>' + esc(r.contact || r.kind || r.wall_name || '—') + '</td>' +
      '<td>' + (gen !== '' ? esc(gen) : '—') + '</td>' +
      '</tr>';
  }

  function render(d) {
    var h = host(); if (!h) return;
    var rows = (d && d.rows) || [];
    if (!rows.length) {
      h.innerHTML = '<div class="placeholder"><div class="sm">no radar contacts — plane LAST_PRICE rows only appear when fresh</div></div>';
      return;
    }
    h.innerHTML = '<table class="desk-radar"><thead><tr>' +
      '<th>Ticker</th><th>Spot</th><th>State</th><th>Contact</th><th>LAST_PRICE gen</th>' +
      '</tr></thead><tbody>' + rows.map(rowHtml).join('') + '</tbody></table>' +
      '<div class="fl-foot">tracked ' + esc(d.tracked) + ' · scanned ' + esc(d.scanned) +
      ' · /api/terrain/radar reprices from plane LAST_PRICE</div>';
    var current = (st().ticker || '').toUpperCase();
    var mine = rows.filter(function (r) { return String(r.ticker || '').toUpperCase() === current; })[0] || rows[0];
    if (mine && window.EdSpotIdentity && window.EdSpotIdentity.stamp) {
      var currentPx = mine.current_spot != null ? mine.current_spot : mine.spot;
      window.EdSpotIdentity.stamp(h, {
        ticker: mine.ticker,
        last_price: currentPx,
        last_price_native_ts: mine.last_price_native_ts,
        last_price_received_ts: mine.last_price_received_ts,
        source: Object.prototype.hasOwnProperty.call(mine, 'current_spot_source')
          ? mine.current_spot_source : null,
        generation: mine.last_price_generation
      });
    }
  }

  function loadImpl(signal) {
    var h = host(); if (!h || !isRadar()) return;
    h.setAttribute('aria-busy', 'true');
    return fetch('/api/terrain/radar', { cache: 'no-store', signal: signal })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (isRadar()) render(d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (isRadar() && h) h.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/terrain/radar</div></div>';
      });
  }

  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(signal); })
    : { trigger: function () { loadImpl(); }, reset: function () {} };

  function load() { if (isRadar()) _loader.trigger('radar'); }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function () { if (isRadar()) load(); });
  }
})();
