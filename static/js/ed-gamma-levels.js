/* Ed Console — Options/Gamma "Levels" view (D). PRESENTATION ONLY.
   Serializes the canonical /api/levels contract (the ONE materialized PriceLevelSnapshot:
   per-level price/family/evidence_tier/provenance/staleness + carried VWAP curve). It renders the
   contract verbatim and computes NO levels — /api/levels is the authority. */
(function () {
  'use strict';

  function px(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  // Two homes render the SAME canonical /api/levels contract, same function, same host-id
  // resolution pattern -- Options > Gamma > Levels (the original) and Liquidity > Levels
  // (operator, 2026-09-13: "one page" work owes Liquidity a real view, not another
  // placeholder). Never two renderers for one contract -- see this file's own docstring.
  function activeHostId() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    if (s.workspace === 'options' && s.subview === 'gamma' && s.view === 'levels') return 'levelsBody';
    if (s.workspace === 'liquidity' && s.subview === 'levels') return 'lvlBody';
    return null;
  }
  function ticker() { return ((window.EdShell && window.EdShell.getState()) || {}).ticker || 'SPY'; }

  // Coalesced load (see l1_sse_guards.js:makeCoalescedLoader) -- `ed:refresh{slow}` also
  // fires on every streamed gamma_surface_seq push, not just the 12s poll tick; a naive
  // per-call generation counter live-locks once pushes outrun the round trip. Context
  // invalidation is `stillLevels()`, checked at resolution time.
  function stillLevels(tk) { return !!activeHostId() && ticker() === tk; }
  // ROUND 8 (2026-09-13): keyed on ticker so a held/slow fetch for an ABANDONED ticker is
  // aborted immediately once a different ticker is selected, instead of blocking it.
  function loadImpl(tk, signal) {
    var hostId = activeHostId();
    var host = hostId && document.getElementById(hostId);
    if (!host || !stillLevels(tk)) return;
    host.setAttribute('aria-busy', 'true');
    return fetch('/api/levels?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillLevels(tk)) render(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillLevels(tk)) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/levels</div></div>';
      });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() { _loader.trigger(ticker()); }

  function render(host, d) {
    var levels = (d && d.levels) || [];
    if (!levels.length) {
      host.innerHTML = '<div class="placeholder"><div class="big">No canonical levels</div>' +
        '<div class="sm">' + esc((d && (d.degraded || []).join(', ')) || 'the levels snapshot is empty for this symbol') + '</div></div>';
      return;
    }
    var now = (d.served_ts_utc || (Date.now() / 1000));
    // sort by price desc (like a levels ladder); spot marked
    var rows = levels.slice().sort(function (a, b) { return (b.price || 0) - (a.price || 0); });
    var spot = Number(d.spot);
    var head = '<div class="lv-head"><span>Canonical levels · gen ' + esc(d.generation) + '</span>' +
      '<span class="lv-spot">spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') +
      (d.spot_source ? ' · ' + esc(d.spot_source) : '') + '</span></div>';
    var body = '<table class="lv"><thead><tr><th>Family</th><th>Level</th><th>Price</th>' +
      '<th>Evidence</th><th>Source</th><th>As-of</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var prov = r.provenance || {}, st = r.staleness || {};
      var age = st.age_sec != null ? (Math.round(st.age_sec) + 's') : '—';
      var stale = st.stale ? ' stale' : '';
      var nearSpot = (isFinite(spot) && r.price != null && Math.abs(r.price - spot) / spot < 0.0015) ? ' near-spot' : '';
      body += '<tr class="lv-row' + nearSpot + '"><td class="lv-fam">' + esc(r.family || '—') + '</td>' +
        '<td>' + esc(r.label || r.id || '—') + '</td>' +
        '<td class="lv-px">' + px(r.price) + '</td>' +
        '<td class="lv-ev">' + esc(r.evidence_tier || '—') + '</td>' +
        '<td class="lv-src">' + esc(prov.producer || '—') + '</td>' +
        '<td class="lv-age' + stale + '">' + esc(age) + '</td></tr>';
    });
    body += '</tbody></table>';
    // carried VWAP curve + honest absences/degradation, disclosed (never fabricated)
    var vwapN = (d.vwap_series || []).length;
    var foot = '<div class="lv-foot">';
    foot += '<span>VWAP curve: ' + (vwapN ? (vwapN + ' pts carried (±1σ/±2σ)') : 'not available') + '</span>';
    var absent = (d.families_absent || []).map(function (f) { return (f && f.family) || f; });
    if (absent.length) foot += '<span class="lv-absent">absent: ' + esc(absent.join(', ')) + '</span>';
    if ((d.degraded || []).length) foot += '<span class="lv-absent">degraded: ' + esc((d.degraded || []).join(', ')) + '</span>';
    foot += '<span class="lv-provsrc">/api/levels · schema v' + esc(d.schema_version) + '</span></div>';
    host.innerHTML = head + body + foot;
    // A canonical level PRICE (VWAP / value / liquidity / structural) is NOT necessarily a listed
    // option strike, so a level click must never write selStrike (that identity belongs to a real
    // option strike). Clicking only highlights the level locally — presentation, no global state,
    // no rounding, no snap-to-strike, no inferred strike.
    host.querySelectorAll('.lv-row').forEach(function (tr) {
      tr.addEventListener('click', function () {
        host.querySelectorAll('.lv-row.lv-sel').forEach(function (n) { n.classList.remove('lv-sel'); });
        tr.classList.add('lv-sel');
      });
    });
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
