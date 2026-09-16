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

  // ---- Repo-wide chart interaction standard: axis-drag rescales, plot-drag pans, scroll
  // zooms, click-to-pin readout not hover, double-click resets. Unlike the strike-window
  // panels (GEX by Strike, Positioning Migration, the gamma heatmap grid), this map has a
  // genuinely continuous, unbounded price axis with no pre-existing scroll/click behaviour to
  // protect -- the SAME contract as ed-gamma-chart.js (SVG) and ed-order-flow-heatmap.js
  // (canvas), just applied to a DOM percent-positioned plot instead of pixels. No separate
  // axis gutter exists here (no left-margin tick column), so the whole plot both pans (drag)
  // and zooms (wheel, continuous -- .liqmap-wrap has no native scroll to preserve, unlike the
  // .gbs-scroll/.heat-wrap panels, so a plain wheel is safe here without a modifier gate). ----
  var _view = null, _viewTicker = null;
  var _dragState = null, _interactionInstalled = false;
  // Independent-review finding, REPRODUCED: unlike ed-gamma-chart.js's clampDomain, nothing
  // here floored the zoomed span -- repeated wheel-in ticks (factor 1/1.12 each) shrink
  // (hi-lo) toward zero with no floor, and `span = (hi-lo)||1` never catches it since span
  // stays nonzero-but-tiny, so yPct blows up and every zone/line/spot renders at a garbage
  // percentage. Applied to BOTH _view writers below, matching the chart's own discipline.
  function clampPriceDomain(lo, hi) {
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return { lo: lo, hi: hi };
    if (hi - lo < 0.02) { var mid = (lo + hi) / 2; return { lo: mid - 0.01, hi: mid + 0.01 }; }
    return { lo: lo, hi: hi };
  }
  function installInteractionOnce() {
    if (_interactionInstalled || typeof document === 'undefined') return;
    _interactionInstalled = true;
    document.addEventListener('mousemove', function (e) {
      if (!_dragState) return;
      var dy = e.clientY - _dragState.startY;
      if (Math.abs(dy) > 2) _dragState.moved = true;
      var span = _dragState.startHi - _dragState.startLo;
      var priceDelta = dy / _dragState.height * span;   // DOM y grows downward, price grows upward
      _view = clampPriceDomain(_dragState.startLo + priceDelta, _dragState.startHi + priceDelta);
      rerenderLiqMapFromCache();
    });
    document.addEventListener('mouseup', function () { _dragState = null; });
  }
  var _lastLiq = null;   // { h, tk, snap, levels } -- render()'s own inputs, for a presentation-only redraw
  function rerenderLiqMapFromCache() {
    if (!_lastLiq) return;
    render(_lastLiq.h, _lastLiq.tk, _lastLiq.snap, _lastLiq.levels);
  }
  function wireLiqMapInteraction(wrap, lo, hi) {
    installInteractionOnce();
    wrap.style.cursor = 'ns-resize';
    wrap.setAttribute('draggable', 'false');
    wrap.addEventListener('dragstart', function (e) { e.preventDefault(); });
    wrap.addEventListener('mousedown', function (e) {
      var r = wrap.getBoundingClientRect();
      _dragState = { startY: e.clientY, startLo: lo, startHi: hi, height: r.height, moved: false };
      e.preventDefault();
    });
    wrap.addEventListener('wheel', function (e) {
      e.preventDefault();
      var r = wrap.getBoundingClientRect();
      var anchor = hi - (e.clientY - r.top) / r.height * (hi - lo);
      var factor = e.deltaY > 0 ? 1.12 : (1 / 1.12);
      _view = clampPriceDomain(anchor - (anchor - lo) * factor, anchor + (hi - anchor) * factor);
      rerenderLiqMapFromCache();
    }, { passive: false });
    wrap.addEventListener('dblclick', function () { _view = null; rerenderLiqMapFromCache(); });
  }

  function render(h, tk, snap, levels) {
    _lastLiq = { h: h, tk: tk, snap: snap, levels: levels };
    if (_viewTicker !== tk) { _view = null; _viewTicker = tk; }
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
    var autoLo = lo - pad, autoHi = hi + pad;
    // A manual pan/zoom (_view) replaces the auto-fit range outright -- the operator's own
    // framing IS the desired view, the same contract _view carries in the SVG/canvas charts.
    // Double-click (wireLiqMapInteraction) clears it, returning to this auto-fit range.
    if (_view) { lo = _view.lo; hi = _view.hi; } else { lo = autoLo; hi = autoHi; }
    var span = (hi - lo) || 1;
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
    // A manual pan/zoom is never silent (same discipline every other panel's own note uses).
    var panNote = _view ? '<div class="sm" style="color:var(--ed-ink-3);padding:2px 0 6px;">PANNED/ZOOMED ' +
      num(lo) + '–' + num(hi) + ' — not auto-fit; double-click the map to resume</div>' : '';

    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' + esc(tk) + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Session</span><span class="fl-badge live">' + esc((snap.snapshot_type || '—').toUpperCase()) + '</span></div></div>' +
      panNote +
      '<div class="liqmap-wrap-outer"><div class="liqmap-wrap" style="height:' + mapH + 'px;">' + zonesHtml + linesHtml + spotHtml + '</div></div>' +
      legendHtml +
      '<div class="fl-foot">Zones and reference levels come straight from /api/liquidity-snapshot and /api/levels — this view arranges them on a price axis and computes nothing new.</div>';
    var wrap = h.querySelector('.liqmap-wrap');
    if (wrap) wireLiqMapInteraction(wrap, lo, hi);
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
      if (stillMap(tk)) {
        // Independent-review finding, REPRODUCED: this branch used to set innerHTML directly,
        // bypassing render() -- _lastLiq kept pointing at the last SUCCESSFUL render's data, so
        // a drag/wheel/dblclick already in flight (delegated on `document`, not gated on this
        // request's own outcome) would call rerenderLiqMapFromCache() and silently repaint the
        // stale pre-error map right over this placeholder. Nothing left to redraw from now.
        _lastLiq = null;
        h.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/liquidity-snapshot</div></div>';
      }
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
