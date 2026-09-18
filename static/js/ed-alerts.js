/* Ed Console — Proximity Alerts. PRESENTATION ONLY, computes nothing.
   Preserved from legacy static/index.html's #alerts-card during the /console cutover
   (operator directive 2026-09-14): a real, backend-driven capability with no equivalent
   anywhere else in the new console, not a placeholder. Reads MarketState.rules_alerts —
   the rules engine's own alert strings (governed MARKET field, governance/provenance_roots.py)
   — via GET /api/analytics/state, the canonical Tier C bundle (server.py's deprecated
   GET /api/state is the same payload under an old name; this uses the current one).

   Deliberately reads ONLY rules_alerts from that payload. /api/analytics/state's ms_dict
   also carries a spot value from the SAME _state_cache side-cache RC spot/gamma-360-audit
   (2026-09-14) proved was a THIRD, stale spot producer for /api/liquidity-snapshot — this
   module must never become a fourth. resolve_spot() / /api/levels stay the one spot
   authority every other panel already uses; nothing here touches spot at all.

   Voice/sound/visual regime-change alerting (legacy's separate terrain alert engine) is a
   deliberate, deferred fast-follow per the same operator directive — not built here. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function ticker() { return (st().ticker || 'SPY'); }
  function strip() { return document.getElementById('alertsStrip'); }
  function listEl() { return document.getElementById('alertsList'); }

  function fetchJson(url, signal) {
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) { return r.ok ? r.json() : null; });
  }

  // Same substring filter as legacy's render(): rules_alerts can carry non-proximity
  // engine strings (e.g. "ENGINE CRASH — ...", a spot-unavailable notice); only the
  // level/wall/near class belongs in a card titled Proximity Alerts.
  function proximityAlerts(d) {
    return d && Array.isArray(d.rules_alerts) ? d.rules_alerts.filter(function (a) {
      return typeof a === 'string' && (a.indexOf('near') !== -1 || a.indexOf('wall') !== -1 || a.indexOf('level') !== -1);
    }) : [];
  }

  function render(d, tk) {
    if (ticker() !== tk) return;   // a since-abandoned ticker's response arrived late
    var s = strip(), list = listEl();
    if (!s || !list) return;
    var alerts = proximityAlerts(d);
    if (!alerts.length) { s.hidden = true; list.innerHTML = ''; return; }
    s.hidden = false;
    var gen = d.last_price_generation != null ? d.last_price_generation : '';
    list.innerHTML = (gen !== '' ? '<span class="alert-pill" data-last-price-gen="' + esc(gen) +
      '">LAST_PRICE gen ' + esc(gen) + '</span>' : '') +
      alerts.map(function (a) { return '<span class="alert-pill">' + esc(a) + '</span>'; }).join('');
  }

  function loadImpl(tk, signal) {
    // `_via=alerts`: a harmless, server-ignored tag (server.py's /api/analytics/state only
    // declares ticker/symbol/expiry/force) so tooling/tests can attribute this independent
    // periodic poll separately from ed-gamma-panels.js's own read-once-per-context PCR reader
    // -- the two are DIFFERENT consumers of the SAME endpoint with DIFFERENT cadence contracts
    // (this one intentionally polls on the shared ~12s slow tick; PCR does not), and without a
    // tag their identical GETs are indistinguishable on the wire.
    return fetchJson('/api/analytics/state?ticker=' + encodeURIComponent(tk) + '&_via=alerts', signal).then(function (d) {
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
