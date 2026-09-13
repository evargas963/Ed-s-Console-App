/* Ed Console — Options/Gamma "Levels" view (D). PRESENTATION ONLY.
   Serializes the canonical /api/levels contract (the ONE materialized PriceLevelSnapshot:
   per-level price/family/evidence_tier/provenance/staleness + carried VWAP curve). It renders the
   contract verbatim and computes NO levels — /api/levels is the authority. */
(function () {
  'use strict';

  function px(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function isLevels() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && s.subview === 'gamma' && s.view === 'levels';
  }
  function ticker() { return ((window.EdShell && window.EdShell.getState()) || {}).ticker || 'SPY'; }

  var _gen = 0;
  function load() {
    var host = document.getElementById('levelsBody');
    if (!host || !isLevels()) return;
    var g = ++_gen, tk = ticker();
    host.setAttribute('aria-busy', 'true');
    fetch('/api/levels?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _gen) render(host, d); })
      .catch(function () { if (g === _gen) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/levels</div></div>'; });
  }

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
