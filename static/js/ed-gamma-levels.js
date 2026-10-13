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
  // the levels the console pushes, in whichever home is on screen (one answer for both)
  ['gamma.levels', 'liquidity.levels'].forEach(function (name) {
    window.EdShell.onPanel(name, function (a) {
      var hostId = activeHostId(), host = hostId && document.getElementById(hostId);
      if (!host || a.waiting) return;
      if (!a.ok) { host.innerHTML = '<div class="placeholder"><div class="sm">/api/levels answered HTTP ' + a.status + '</div></div>'; return; }
      render(host, a.body);
    });
  });

  function render(host, d) {
    var levels = (d && d.levels) || [];
    if (!levels.length) {
      host.innerHTML = '<div class="placeholder"><div class="big">No canonical levels</div>' +
        '<div class="sm">' + esc((d && (d.degraded || []).join(', ')) || 'the levels snapshot is empty for this symbol') + '</div></div>';
      return;
    }
    // served in ladder order (price, highest first)
    var rows = levels;
    var head = '<div class="lv-head"><span>Canonical levels · gen ' + esc(d.generation) + '</span>' +
      '<span class="lv-spot">spot <span class="lv-spot-v">' + esc(_spotDisp) + '</span></span></div>';
    var body = '<table class="lv"><thead><tr><th>Family</th><th>Level</th><th>Price</th>' +
      '<th>Evidence</th><th>Source</th><th>As-of</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var prov = r.provenance || {}, st = r.staleness || {};
      var age = st.age_sec != null ? (Math.round(st.age_sec) + 's') : '—';
      var stale = st.stale ? ' stale' : '';
      body += '<tr class="lv-row"><td class="lv-fam">' + esc(r.family || '—') + '</td>' +
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

  // the spot is the header's price row (the daemon's Schwab LAST_PRICE), painted on every row
  var _spotDisp = '—';
  window.addEventListener('ed:quote_tick', function (e) {
    var q = e.detail, s = (window.EdShell && window.EdShell.getState()) || {};
    if (!q || q.ticker !== s.key) return;
    _spotDisp = q.spot_disp != null ? q.spot_disp : '—';
    document.querySelectorAll('.lv-spot-v').forEach(function (el) { el.textContent = _spotDisp; });
  });
  document.addEventListener('ed:ticker', function () { _spotDisp = '—'; });   // until the new ticker's row
})();
