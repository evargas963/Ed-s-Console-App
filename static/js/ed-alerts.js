/* Proximity Alerts <- /api/alerts (spot near a gamma wall, levels just crossed). Presentation only. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function ticker() { return (st().ticker || ''); }
  function strip() { return document.getElementById('alertsStrip'); }
  function listEl() { return document.getElementById('alertsList'); }

  function fetchJson(url, signal) {
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) {
      if (!r.ok) throw new Error('alerts unavailable: HTTP ' + r.status);
      return r.json();
    });
  }

  // the server's alerts as sent; with none, the reason it gives (or the request's failure)
  function render(tk, alerts, reason) {
    if (ticker() !== tk) return;   // a since-abandoned ticker's response arrived late
    var s = strip(), list = listEl();
    if (!s || !list) return;
    s.hidden = !alerts.length && !reason;
    list.innerHTML = alerts.length
      ? alerts.map(function (a) { return '<span class="alert-pill">' + esc(a.text) + '</span>'; }).join('')
      : (reason ? '<span class="alert-pill alert-reason">' + esc(reason) + '</span>' : '');
  }

  function loadImpl(tk, signal) {
    return fetchJson('/api/alerts?ticker=' + encodeURIComponent(tk), signal).then(function (d) {
      render(tk, d.alerts || [], d.withheld);
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      render(tk, [], (e && e.message) || 'alerts unavailable');
    });
  }

  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() { _loader.trigger(ticker()); }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'levels') load(); });
    // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
    // deferred ed:ticker dispatch -- see that file's init() comment.
  }
})();
