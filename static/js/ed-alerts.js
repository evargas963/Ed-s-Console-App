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
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) { return r.ok ? r.json() : null; });
  }

  function render(d, tk) {
    if (ticker() !== tk) return;   // a since-abandoned ticker's response arrived late
    var s = strip(), list = listEl();
    if (!s || !list) return;
    var alerts = (d && d.alerts) || [];
    if (!alerts.length) { s.hidden = true; list.innerHTML = ''; return; }
    s.hidden = false;
    list.innerHTML = alerts.map(function (a) { return '<span class="alert-pill">' + esc(a) + '</span>'; }).join('');
  }

  function loadImpl(tk, signal) {
    return fetchJson('/api/alerts?ticker=' + encodeURIComponent(tk), signal).then(function (d) {
      render(d, tk);
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      if (ticker() === tk) { var s = strip(); if (s) s.hidden = true; }
    });
  }

  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() { _loader.trigger(ticker()); }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:ticker', load);
    // Same "slow" (~12s) cadence every other periodic-poll panel uses off ed-core.js's one
    // scheduler (see ed-liquidity-map.js) -- not the legacy page's unrelated 5s interval.
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
    // deferred ed:ticker dispatch -- see that file's init() comment.
  }
})();
