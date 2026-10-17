/* Ed Console — Options/Gamma "Levels" view (D). PRESENTATION ONLY.
   One glance table: the level, the regular price, and the same-day price. The page
   joins rows the server already paired (zero_dte carries both prices) and draws the
   other served levels under them. It computes no level. /api/levels is the authority. */
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
  function ticker() { return ((window.EdShell && window.EdShell.getState()) || {}).ticker || ''; }

  function stillLevels(tk) { return !!activeHostId() && ticker() === tk; }
  // ROUND 8 (2026-09-13): keyed on ticker so a held/slow fetch for an ABANDONED ticker is
  // aborted immediately once a different ticker is selected, instead of blocking it.
  function loadImpl(tk, signal) {
    var hostId = activeHostId();
    var host = hostId && document.getElementById(hostId);
    if (!host || !stillLevels(tk)) return;
    return fetch('/api/levels?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillLevels(tk)) render(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillLevels(tk)) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/levels</div></div>';
      });
  }
  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); });
  function load() { _loader.trigger(ticker()); }

  function levelName(r) {
    if (r.label != null && r.label !== '') return r.label;
    if (r.id != null && r.id !== '') return r.id;
    return '—';
  }
  function pairRow(name, nowPrice, sameDay, paired) {
    var cls = paired ? 'lv-row zd-row' : 'lv-row';
    var third = paired ? px(sameDay) : '—';
    return '<tr class="' + cls + '"><td>' + esc(name) + '</td>' +
      '<td class="lv-px">' + px(nowPrice) + '</td>' +
      '<td class="lv-px">' + third + '</td></tr>';
  }
  function render(host, d) {
    var levels = (d && d.levels != null) ? d.levels : null;
    var zd = (d && d.zero_dte != null) ? d.zero_dte : null;
    var shown = {};
    var body = '';
    var snap = null;
    if (zd != null) {
      zd.forEach(function (r) {
        if (!r) return;
        if (r.id != null) shown[r.id] = true;
        var st = (r.staleness != null) ? r.staleness : null;
        if (snap == null && st != null && st.as_of_time_ct != null) snap = st.as_of_time_ct;
        body += pairRow(levelName(r), r.carried, r.price, true);
      });
    }
    if (levels != null) {
      levels.forEach(function (r) {
        if (!r) return;
        if (r.id != null && shown[r.id]) return;
        body += pairRow(levelName(r), r.price, null, false);
      });
    }
    if (!body) {
      var degraded = (d && d.degraded != null) ? d.degraded : null;
      var note = (degraded && degraded.length) ? degraded.join(', ') : 'the levels snapshot is empty for this symbol';
      host.innerHTML = '<div class="placeholder"><div class="big">No canonical levels</div>' +
        '<div class="sm">' + esc(note) + '</div></div>';
      return;
    }
    // null/'' spot is ABSENT: Number(null) is 0, which drew 'spot 0.00' (audit P0, 2026-09-23)
    var spot = (d.spot == null || d.spot === '') ? NaN : Number(d.spot);
    var trade = '';
    if (d.spot_time_ct) trade = ' · last trade ' + esc(d.spot_time_ct);
    var snapWord = '';
    if (snap != null) snapWord = ' · 0DTE ' + esc(snap);
    var source = '';
    if (d.spot_source) source = ' · ' + esc(d.spot_source);
    var head = '<div class="lv-head"><span>Levels · gen ' + esc(d.generation) + '</span>' +
      '<span class="lv-spot">spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') +
      source + trade + snapWord + '</span></div>';
    var table = '<table class="lv"><thead><tr><th>Level</th><th>Regular</th><th>0DTE</th>' +
      '</tr></thead><tbody>' + body + '</tbody></table>';
    // carried VWAP curve + honest absences/degradation, disclosed (never fabricated)
    var vwapN = 0;
    if (d.vwap_series != null) vwapN = d.vwap_series.length;
    var foot = '<div class="lv-foot">';
    foot += '<span>VWAP curve: ' + (vwapN ? (vwapN + ' pts carried (±1σ/±2σ)') : 'not available') + '</span>';
    var absentSrc = (d.families_absent != null) ? d.families_absent : null;
    var absent = [];
    if (absentSrc != null) {
      absentSrc.forEach(function (f) {
        if (f && f.family) absent.push(f.family);
        else if (f) absent.push(f);
      });
    }
    if (absent.length) foot += '<span class="lv-absent">absent: ' + esc(absent.join(', ')) + '</span>';
    var degradedFoot = (d.degraded != null) ? d.degraded : null;
    if (degradedFoot != null && degradedFoot.length) {
      foot += '<span class="lv-absent">degraded: ' + esc(degradedFoot.join(', ')) + '</span>';
    }
    foot += '<span class="lv-provsrc">/api/levels · schema v' + esc(d.schema_version) + '</span></div>';
    host.innerHTML = head + table + foot;
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
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'levels') load(); });
    // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
    // deferred ed:ticker/ed:view dispatch -- see that file's init() comment.
  }
})();
