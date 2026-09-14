/* Ed Console — Liquidity / "Map" subview. PRESENTATION ONLY, computes nothing.
   The original console.html placeholder for this workspace said it exactly: "Wires to
   /api/liquidity-snapshot ... A visual liquidity map, not a table." The Levels tab already
   gives the flat table (reusing ed-gamma-levels.js); this is that map. Renders the SAME
   canonical zones /api/liquidity-snapshot already computes (support/resistance bands with
   their own confluence_score and source levels) as a vertical price map, spot marked from
   the SAME /api/levels spot every other panel already uses — one spot authority, not a
   second one invented here. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isMap() { var s = st(); return s.workspace === 'liquidity' && s.subview === 'map'; }
  function ticker() { return (st().ticker || 'SPY'); }
  function host() { return document.getElementById('liqmBody'); }
  function stillMap(tk) { return isMap() && ticker() === tk; }

  function fetchJson(url, signal) {
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) { return r.ok ? r.json() : null; });
  }

  function zoneRow(z) {
    var tags = (z.source_levels || []).map(function (l) { return esc(l.label) + ' ' + num(l.value); }).join(' · ');
    return '<div class="fl-row"><span class="k">' + esc(z.zone_type === 'support_liquidity' ? 'Support' : 'Resistance') +
      ' ' + num(z.zone_low) + '–' + num(z.zone_high) + '</span>' +
      '<span class="v">confluence ' + esc(z.confluence_score) + '</span></div>' +
      '<div class="sm" style="padding:0 0 6px;color:var(--ed-ink-3);">' + (tags || '—') +
      (z.interpretation_notes ? ' — ' + esc(z.interpretation_notes) : '') + '</div>';
  }

  function render(h, tk, snap, levels) {
    if (!snap || snap.zones === undefined) {
      h.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/liquidity-snapshot</div></div>';
      return;
    }
    var zones = snap.zones || [];
    var spot = levels ? Number(levels.spot) : NaN;
    var raw = snap.raw_levels || {};
    var pd = raw.prev_day || {}, on = raw.overnight || {};
    var refLines = [
      pd.pdh != null ? { label: 'PDH', value: pd.pdh } : null,
      pd.pd_vah != null ? { label: 'PD VAH', value: pd.pd_vah } : null,
      pd.pd_poc != null ? { label: 'PD POC', value: pd.pd_poc } : null,
      pd.pd_val != null ? { label: 'PD VAL', value: pd.pd_val } : null,
      pd.pdl != null ? { label: 'PDL', value: pd.pdl } : null,
      pd.pdc != null ? { label: 'PDC', value: pd.pdc } : null,
      on.overnight_high != null ? { label: 'ON HIGH', value: on.overnight_high } : null,
      on.overnight_low != null ? { label: 'ON LOW', value: on.overnight_low } : null,
    ].filter(Boolean);

    if (!zones.length && !refLines.length) {
      h.innerHTML = '<div class="placeholder"><div class="sm">no liquidity levels available yet for ' + esc(tk) + '</div></div>';
      return;
    }

    // One zone/level with a missing or non-numeric bound must never poison the shared scale
    // for every other zone on the map -- isFinite() drops it instead of propagating NaN through
    // Math.min/max into `lo`/`hi`, which would otherwise mis-position everything (every yPct()
    // call, every band, every reference line, the spot marker) instead of just the bad entry.
    var lo = Infinity, hi = -Infinity;
    zones.forEach(function (z) {
      if (isFinite(z.zone_low)) lo = Math.min(lo, z.zone_low);
      if (isFinite(z.zone_high)) hi = Math.max(hi, z.zone_high);
    });
    refLines.forEach(function (l) { if (isFinite(l.value)) { lo = Math.min(lo, l.value); hi = Math.max(hi, l.value); } });
    if (isFinite(spot)) { lo = Math.min(lo, spot); hi = Math.max(hi, spot); }
    if (!isFinite(lo) || !isFinite(hi)) {
      h.innerHTML = '<div class="placeholder"><div class="sm">no usable zone/level bounds for ' + esc(tk) + '</div></div>';
      return;
    }
    var pad = (hi - lo) * 0.12 || 1;
    lo -= pad; hi += pad;
    var span = hi - lo || 1;
    function yPct(v) { return (1 - (v - lo) / span) * 100; }

    var mapH = 460;
    var zonesHtml = zones.filter(function (z) { return isFinite(z.zone_low) && isFinite(z.zone_high); }).map(function (z) {
      var top = yPct(z.zone_high), bottom = yPct(z.zone_low);
      var cls = z.zone_type === 'support_liquidity' ? 'support' : 'resistance';
      return '<div class="liqmap-zone ' + cls + '" style="top:' + top.toFixed(2) + '%;height:' + Math.max(0.6, bottom - top).toFixed(2) + '%;" ' +
        'title="' + esc(z.zone_type) + ' ' + num(z.zone_low) + '–' + num(z.zone_high) + ', confluence ' + esc(z.confluence_score) + '">' +
        '<span class="liqmap-zone-tag">' + esc(z.confluence_score) + '×</span></div>';
    }).join('');
    var linesHtml = refLines.filter(function (l) { return isFinite(l.value); }).map(function (l) {
      return '<div class="liqmap-line" style="top:' + yPct(l.value).toFixed(2) + '%;">' +
        '<span class="liqmap-line-label">' + esc(l.label) + ' ' + num(l.value) + '</span></div>';
    }).join('');
    var spotHtml = isFinite(spot)
      ? '<div class="liqmap-spot" style="top:' + yPct(spot).toFixed(2) + '%;"><span class="liqmap-spot-label">SPOT ' + num(spot) + '</span></div>'
      : '';

    var legendHtml =
      '<div class="fl-sec" style="margin-top:14px;"><div class="fl-sec-h">Zones (confluence-scored, /api/liquidity-snapshot)</div>' +
      (zones.length ? zones.map(zoneRow).join('') : '<div class="sm">no zones for this session yet</div>') + '</div>';

    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' + esc(tk) + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Session</span><span class="fl-badge live">' + esc((snap.snapshot_type || '—').toUpperCase()) + '</span></div></div>' +
      '<div class="liqmap-wrap-outer"><div class="liqmap-wrap" style="height:' + mapH + 'px;">' + zonesHtml + linesHtml + spotHtml + '</div></div>' +
      legendHtml +
      '<div class="fl-foot">Zones and reference levels come straight from /api/liquidity-snapshot and /api/levels — this view arranges them on a price axis and computes nothing new.</div>';
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillMap(tk)) return;
    h.setAttribute('aria-busy', 'true');
    return Promise.all([
      // snapshot=live: the endpoint's OWN default is "premarket" -- a frozen before-9:30ET
      // snapshot, not the current session. Omitting this silently showed a pre-market-only
      // picture all day; snapshot_type is still echoed in the header badge either way.
      fetchJson('/api/liquidity-snapshot?ticker=' + encodeURIComponent(tk) + '&snapshot=live', signal),
      fetchJson('/api/levels?ticker=' + encodeURIComponent(tk), signal),
    ]).then(function (results) {
      if (stillMap(tk)) render(h, tk, results[0], results[1]);
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      if (stillMap(tk)) h.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/liquidity-snapshot</div></div>';
    });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() {
    if (!isMap()) return;
    var tEl = document.getElementById('liqmTicker'); if (tEl) tEl.textContent = ticker().replace('$', '');
    _loader.trigger(ticker());
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
