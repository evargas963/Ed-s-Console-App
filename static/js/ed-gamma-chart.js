/* Ed Console — Options/Gamma Chart view (RC-UI-1). PRESENTATION ONLY.
   Two modes on the same canonical inputs, spatially aligned to the price axis:
     A. Price + GEX Profile  — price line (/api/bars1m) beside a signed per-strike GEX
        profile (/api/terrain/strikes), with spot/flip/call-wall/put-wall overlays (/api/terrain).
     B. GEX Dot Map          — per-strike dots: colour=sign, size=|$ magnitude|, label=$ value.
   All numbers come from canonical endpoints; this module maps value->pixel (visualisation) and
   formats text. It computes NO exposure/levels semantics. */
(function () {
  'use strict';

  var usd = (window.EdGamma && window.EdGamma.formatUsd) || function (n) {
    if (n == null || isNaN(n)) return ''; var a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'K'; return s + '$' + a.toFixed(0);
  };
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c];});}
  function ctTime(sec){try{return new Date(sec*1000).toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',timeZone:'America/Chicago'});}catch(e){return'';}}
  function isChart(){var s=(window.EdShell&&window.EdShell.getState())||{};return s.workspace==='options'&&s.subview==='gamma'&&s.view==='chart';}
  function ticker(){return((window.EdShell&&window.EdShell.getState())||{}).ticker||'';}
  // Mirrors server.py's SPOT_SOURCE_* constants -- short, human labels for the same strings
  // resolve_spot() already stamps on every payload it produces.
  var SPOT_SOURCE_LABEL = { streaming_plane: 'streaming' };   // resolve_spot has one source
  function spotSourceLabel(s) { return s ? (SPOT_SOURCE_LABEL[s] || s) : null; }

  var _mode = 'profile';
  var COL = { pos: 'var(--ed-pos)', neg: 'var(--ed-neg)', spot: 'var(--ed-ink)', flip: 'var(--ed-accent)',
    call: 'var(--ed-neg)', put: 'var(--ed-pos)', axis: 'var(--ed-edge)', ink3: 'var(--ed-ink-3)' };

  // ---- Repo-wide chart interaction standard (operator directive: "chart interactions mirror
  // TradingView... all charts should work the same way") -- FIRST wiring of it anywhere in the
  // rebuilt console, on the one genuine chart here. Axis-drag (left of the price labels)
  // RESCALES the visible price domain; plot-drag PANS it; a real click (not a drag) PINS a
  // crosshair readout -- it does not follow the mouse on hover, and it stays pinned across the
  // next data refresh until the operator clicks again or switches ticker/mode. Wheel zooms
  // around the cursor's price, the same axis-rescale math as an axis-drag. This never fetches
  // new data -- it only remaps the SAME already-rendered bars/strikes to a different pixel
  // window, exactly like Options-workspace's own scopeSelect never invents a value either. */
  var _view = null;            // {lo, hi} once the operator has zoomed/panned; null = auto-fit
  var _pin = null;             // {vx, vy} pinned crosshair in viewBox space, or null
  var _lastCtx = null;         // {bars, win, spot, terrain} from the last successful render
  var _lastBarsData = null;    // the latest /api/bars1m payload (null after a failed fetch)
  // THE displayed price: the same quote_tick the header paints (server _quote_tick_event).
  // The chart used to take its spot from /api/terrain -- a second producer that could differ.
  var _liveQuote = null;
  function sameSym(a, b) { return String(a || '').toUpperCase().replace(/^\$/, '') === String(b || '').toUpperCase().replace(/^\$/, ''); }
  function liveSpot() {
    return (_liveQuote && sameSym(_liveQuote.ticker, ticker()) && _liveQuote.spot_state === 'live'
            && _liveQuote.spot != null) ? Number(_liveQuote.spot) : NaN;
  }
  var _viewTicker = null, _viewMode = null;   // domain resets only on a genuine context change
  // Deep-research finding (operator directive, 2026-09-14): real TradingView gives its
  // SECONDARY axis the same independent drag-to-rescale the primary axis gets (there, time is
  // primary -- candle-keyed -- and price is secondary, with its own right-axis drag). This
  // chart's bars are STRIKE-keyed (price is what the +GEX/-GEX profile actually plots against),
  // so price is correctly the primary interactive axis here -- but time (the price-history
  // line's own axis) never got the secondary-axis treatment at all: no pan, no rescale, always
  // the full fetched bars1m window. _timeView mirrors _view's own contract exactly, just over
  // bar INDICES instead of a price domain (bars are evenly index-spaced along x, not spaced by
  // elapsed time -- see the x = x0 + i/(n-1)*(x1-x0) mapping below).
  var _timeView = null;        // {loIdx, hiIdx} once the operator has zoomed/panned time; null = full window

  // The time axis only has meaning in 'profile' mode: dotSvg draws no bars and no time-axis
  // labels at all (verified -- it plots strikes around a fixed centerline, nothing time-keyed).
  // profileSvg's own candles span x0=L to x1=xSplit-10, NOT the full W-L-R chart width --
  // independent review, REPRODUCED: using the full width as the anchor denominator computed a
  // fraction roughly half of the real one over most of the visible bar area, so a wheel-zoom
  // "centered under the cursor" actually centered well to the left of it. Both interaction
  // sites below (mousemove drag and wheel) must use this SAME width the renderer actually uses.
  function timeAxisPlotWidth() { return Math.round(W * 0.60) - 10 - L; }
  function isTimeAxisHit(vy) { return _mode === 'profile' && vy > H - B; }
  function clientToViewBox(svg, clientX, clientY) {
    var r = svg.getBoundingClientRect();
    return { vx: (clientX - r.left) / r.width * W, vy: (clientY - r.top) / r.height * H };
  }
  function priceAtVy(vy, lo, hi) { return hi - (vy - T) / (H - T - B) * (hi - lo); }
  function clampDomain(lo, hi) {
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return { lo: lo, hi: hi };
    // never rescale to a degenerate sliver -- a TradingView-style zoom still has a floor.
    if (hi - lo < 0.02) { var mid = (lo + hi) / 2; return { lo: mid - 0.01, hi: mid + 0.01 }; }
    return { lo: lo, hi: hi };
  }
  // Same floor/clamp contract as clampDomain, over integer bar indices into the FULL fetched
  // array (never the already-windowed slice -- indices must stay meaningful across repeated
  // zooms) instead of a continuous price range. At least 3 bars stay visible; bounds are
  // rounded and pinned inside [0, totalLen-1] so a fast drag/wheel burst can never request a
  // slice outside what was actually fetched.
  function clampTimeDomain(loIdx, hiIdx, totalLen) {
    if (!isFinite(loIdx) || !isFinite(hiIdx) || totalLen < 4) return null;
    loIdx = Math.round(loIdx); hiIdx = Math.round(hiIdx);
    if (hiIdx - loIdx < 3) { var mid = Math.round((loIdx + hiIdx) / 2); loIdx = mid - 1; hiIdx = mid + 2; }
    if (loIdx < 0) { hiIdx -= loIdx; loIdx = 0; }
    if (hiIdx > totalLen - 1) { loIdx -= (hiIdx - (totalLen - 1)); hiIdx = totalLen - 1; }
    loIdx = Math.max(0, loIdx);
    return { loIdx: loIdx, hiIdx: hiIdx };
  }

  var _interactionInstalled = false;
  var _dragState = null;   // {mode:'pan'|'axis', startVY, startLo, startHi, moved}
  function installInteractionOnce() {
    if (_interactionInstalled || typeof document === 'undefined') return;
    _interactionInstalled = true;
    // liveSvg() is re-queried on every event rather than trusted from _dragState: every
    // rerenderFromCache() call during a drag replaces #chartBody's innerHTML (a fresh SVG
    // element), so a reference captured once at mousedown-time goes stale (detached, zero-size
    // getBoundingClientRect) the moment the FIRST mousemove of that same drag repaints -- every
    // coordinate computed from it after that point was NaN. Re-querying by id finds whichever
    // SVG element is currently live, which is exactly what a drag gesture needs.
    function liveSvg() { var h = document.getElementById('chartBody'); return h && h.querySelector('.chart-svg'); }
    document.addEventListener('mousemove', function (e) {
      if (!_dragState) return;
      var svg = liveSvg();
      if (!svg) return;
      var p = clientToViewBox(svg, e.clientX, e.clientY);
      if (Math.abs(p.vy - _dragState.startVY) > 2 || Math.abs(p.vx - _dragState.startVX) > 2) _dragState.moved = true;
      var span = _dragState.startHi - _dragState.startLo, plotH = H - T - B;
      var dy = p.vy - _dragState.startVY;
      if (_dragState.mode === 'pan') {
        var priceDelta = dy / plotH * span;
        _view = clampDomain(_dragState.startLo + priceDelta, _dragState.startHi + priceDelta);
      } else if (_dragState.mode === 'axis') {   // rescale the domain around the price under the drag's START point
        var anchor = priceAtVy(_dragState.startVY, _dragState.startLo, _dragState.startHi);
        var factor = Math.pow(1.006, dy);   // dragging down widens the range (zoom out)
        _view = clampDomain(anchor - (anchor - _dragState.startLo) * factor, anchor + (_dragState.startHi - anchor) * factor);
      } else {   // time-axis drag: rescale the visible bar-index window, mirroring the price axis
        var idxSpan = _dragState.startHiIdx - _dragState.startLoIdx, plotW = timeAxisPlotWidth();
        var dx = p.vx - _dragState.startVX;
        var tFactor = Math.pow(1.006, -dx);   // dragging right narrows (zoom in), left widens (zoom out)
        var idxAnchor = _dragState.startLoIdx + (_dragState.startVX - L) / plotW * idxSpan;
        _timeView = clampTimeDomain(
          idxAnchor - (idxAnchor - _dragState.startLoIdx) * tFactor,
          idxAnchor + (_dragState.startHiIdx - idxAnchor) * tFactor,
          _dragState.fullLen);
      }
      rerenderFromCache();
    });
    document.addEventListener('mouseup', function (e) {
      if (!_dragState) return;
      if (!_dragState.moved) {
        var svg = liveSvg();
        if (svg) {
          // a real click, not a drag -- PIN the crosshair here; it never just follows hover.
          var p = clientToViewBox(svg, e.clientX, e.clientY);
          _pin = (_pin && Math.abs(_pin.vx - p.vx) < 0.5 && Math.abs(_pin.vy - p.vy) < 0.5) ? null : p;   // click again to unpin
          rerenderFromCache();
        }
      }
      _dragState = null;
    });
  }
  function wireChartInteraction(host, lo, hi) {
    installInteractionOnce();
    var svg = host.querySelector('.chart-svg');
    if (!svg) return;
    svg.setAttribute('draggable', 'false');
    svg.style.webkitUserDrag = 'none';
    svg.style.cursor = 'crosshair';
    svg.addEventListener('dragstart', function (e) { e.preventDefault(); });
    svg.addEventListener('mousedown', function (e) {
      // CI-caught regression: a real click on a .gmark-hit (the strike-selection target
      // every workspace's cross-panel sync depends on) used to reach setStrike() via the
      // browser's native click event -- but this module's own mouseup handler re-renders
      // the WHOLE innerHTML synchronously (for pan/pin), which detaches the very element
      // mousedown just fired on before that native click ever dispatches, so the strike
      // selection was silently lost. A click that starts on a strike mark is the mark's own
      // click-to-select gesture, not this chart's pan/zoom/crosshair gesture -- let it
      // proceed completely undisturbed.
      if (e.target && e.target.closest && e.target.closest('.gmark-hit')) return;
      var p = clientToViewBox(svg, e.clientX, e.clientY);
      // Bottom strip (below the plot, regardless of x) is the time axis -- checked first, the
      // same "whole margin band, not just a corner" convention TradingView's own axes use, so
      // the price-axis / time-axis corner never falls through to the wrong mode.
      var fullLen = (_lastCtx && _lastCtx.bars) ? _lastCtx.bars.length : 0;
      var curLoIdx = _timeView ? _timeView.loIdx : 0;
      var curHiIdx = _timeView ? _timeView.hiIdx : Math.max(0, fullLen - 1);
      var mode = isTimeAxisHit(p.vy) ? 'time-axis' : (p.vx < L ? 'axis' : 'pan');
      _dragState = { mode: mode, startVX: p.vx, startVY: p.vy, startLo: lo, startHi: hi,
        startLoIdx: curLoIdx, startHiIdx: curHiIdx, fullLen: fullLen, moved: false };
      e.preventDefault();
    });
    svg.addEventListener('wheel', function (e) {
      e.preventDefault();
      var p = clientToViewBox(svg, e.clientX, e.clientY);
      // Hovering the time axis zooms TIME instead of price -- the same "hover the axis you
      // want to zoom" convention real TradingView uses for its own (there, price) secondary
      // axis, mirrored onto this chart's secondary axis.
      if (isTimeAxisHit(p.vy)) {
        var fullLen = (_lastCtx && _lastCtx.bars) ? _lastCtx.bars.length : 0;
        var curLoIdx = _timeView ? _timeView.loIdx : 0;
        var curHiIdx = _timeView ? _timeView.hiIdx : Math.max(0, fullLen - 1);
        var idxSpan = curHiIdx - curLoIdx, plotW = timeAxisPlotWidth();
        var idxAnchor = curLoIdx + (p.vx - L) / plotW * idxSpan;
        var tFactor = e.deltaY > 0 ? 1.12 : (1 / 1.12);
        _timeView = clampTimeDomain(
          idxAnchor - (idxAnchor - curLoIdx) * tFactor, idxAnchor + (curHiIdx - idxAnchor) * tFactor, fullLen);
      } else {
        var anchor = priceAtVy(p.vy, lo, hi);
        var factor = e.deltaY > 0 ? 1.12 : (1 / 1.12);
        _view = clampDomain(anchor - (anchor - lo) * factor, anchor + (hi - anchor) * factor);
      }
      rerenderFromCache();
    }, { passive: false });
    // Double-click resets to the auto-fit domain -- the operator's own escape hatch, the same
    // convention every TradingView-style chart uses, instead of a dead end once zoomed.
    svg.addEventListener('dblclick', function () { _view = null; _pin = null; _timeView = null; rerenderFromCache(); });
  }
  function nearestBarAt(bars, vx, xLo, xHi) {
    if (!bars.length) return null;
    var frac = (vx - xLo) / (xHi - xLo);
    var i = Math.round(frac * (bars.length - 1));
    return bars[Math.max(0, Math.min(bars.length - 1, i))];
  }
  function nearestStrikeAt(win, vy, lo, hi) {
    if (!win.length) return null;
    var best = null, bestD = Infinity;
    win.forEach(function (r) { var d = Math.abs(yOf(r[0], lo, hi) - vy); if (d < bestD) { bestD = d; best = r; } });
    return best;
  }
  function crosshairSvg(lo, hi, mode, bars) {
    if (!_pin || !_lastCtx) return '';
    var vx = _pin.vx, vy = _pin.vy;
    var price = priceAtVy(vy, lo, hi);
    var lines = '<g pointer-events="none">' +
      '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + vy.toFixed(1) + '" y2="' + vy.toFixed(1) + '" stroke="var(--ed-accent-2)" stroke-width="1" stroke-dasharray="3 2"/>' +
      '<line x1="' + vx.toFixed(1) + '" x2="' + vx.toFixed(1) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="var(--ed-accent-2)" stroke-width="1" stroke-dasharray="3 2"/>';
    var readLines = ['price ' + price.toFixed(2)];
    if (mode === 'profile') {
      var xSplit = Math.round(W * 0.60);
      if (vx < xSplit) {
        // bars here is renderInto's own (possibly time-windowed) slice, NOT _lastCtx.bars --
        // x-position maps to an index within whatever is actually visible, so a pin taken while
        // zoomed into a narrow time window must resolve against that same visible slice or it
        // would read back a bar many screens away from where the operator actually clicked.
        var bar = nearestBarAt(bars, vx, L, xSplit - 10);
        if (bar) readLines.push('close ' + Number(bar.c).toFixed(2), ctTime(bar.t) + ' CT');
      } else {
        var srow = nearestStrikeAt(_lastCtx.win, vy, lo, hi);
        if (srow) readLines.push('strike ' + srow[0], 'GEX ' + usd(srow[1]));
      }
    } else {
      var srow2 = nearestStrikeAt(_lastCtx.win, vy, lo, hi);
      if (srow2) readLines.push('strike ' + srow2[0], 'GEX ' + usd(srow2[1]));
    }
    var boxX = Math.min(vx + 8, W - 118), boxY = Math.max(T, Math.min(vy - 8, H - B - readLines.length * 13 - 8));
    lines += '<rect x="' + boxX.toFixed(1) + '" y="' + boxY.toFixed(1) + '" width="112" height="' + (readLines.length * 13 + 8) +
      '" rx="3" fill="var(--ed-panel-3)" stroke="var(--ed-accent-2)" opacity="0.96"/>';
    readLines.forEach(function (t, i) {
      lines += '<text x="' + (boxX + 6).toFixed(1) + '" y="' + (boxY + 14 + i * 13).toFixed(1) + '" font-size="10" fill="var(--ed-ink)">' + esc(String(t)) + '</text>';
    });
    return lines + '</g>';
  }
  function rerenderFromCache() {
    var host = document.getElementById('chartBody');
    if (!host || !_lastCtx) return;
    renderInto(host, _lastCtx.bars, _lastCtx.win, _lastCtx.spot, _lastCtx.terrain, _lastCtx.legend);
  }

  // Coalesced load (see l1_sse_guards.js:makeCoalescedLoader) -- required because
  // `ed:refresh{slow}` now also fires on every streamed gamma_surface_seq push (ed-core.js),
  // not just the 12s poll tick; a naive per-call generation counter live-locks (never applies
  // a response) once pushes arrive faster than this 3-endpoint round trip. Ticker/view
  // changed mid-flight is checked at resolution time (stillChart), not inferred from a
  // counter.
  function stillChart(tk) { return isChart() && ticker() === tk; }
  // ROUND 8 (2026-09-13): keyed on ticker so a held/slow fetch for an ABANDONED ticker is
  // aborted immediately once a different ticker is selected, instead of blocking it.
  function loadImpl(tk, signal) {
    var host = document.getElementById('chartBody');
    if (!host || !stillChart(tk)) return;
    host.setAttribute('aria-busy', 'true');
    return Promise.all([
      fetch('/api/bars1m?ticker=' + encodeURIComponent(tk) + '&limit=180', { cache: 'no-store', signal: signal }).then(okJson).catch(nullp),
      fetch('/api/terrain/strikes?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal }).then(okJson).catch(nullp),
      fetch('/api/terrain?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal }).then(okJson).catch(nullp),
    ]).then(function (res) {
      if (!stillChart(tk)) return;
      _lastBarsData = res[0];            // a failed fetch clears the old bars, never re-shows them
      render(host, res[0], res[1], res[2]);
    });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() { _loader.trigger(ticker()); }
  function okJson(r){ if(!r.ok) throw new Error(r.status); return r.json(); }
  function nullp(){ return null; }

  // Audit finding #3 (2026-09-16, follow-up): a streamed gamma-surface push carries no new
  // information for /api/bars1m (price history) -- that alone stays on the 12s/view-entry
  // cadence. /api/terrain/strikes (the GEX-by-strike profile this chart's 'profile' mode
  // plots) IS gamma-surface-derived and always was.
  //
  // CONFIRMED REGRESSION (2026-09-17, live-UI field audit): /api/terrain was ALSO excluded
  // here on the reasoning "a streamed OPTION tick carries no new terrain/spot information" --
  // true when this was written, but FALSE now that ed:gamma-push also fires on a canonical
  // SPOT-ONLY tick (refresh_gamma_surface_from_spot_tick, server.py) with no option tick at
  // all. (Then /api/terrain's spot field was this chart's spot; since the audit of #280 the
  // spot is the header's quote_tick and /api/terrain supplies only flip/walls.) It was left pointing at `_lastRaw.terrain` -- the STALE
  // object from the last full 12s-cadence load() -- so the header's spot could move on every
  // tick while this chart's own spot line sat frozen for up to 12s. The exact same class of
  // "header moves, this panel does not" defect the heatmap fix (2026-09-17) already closed,
  // now closed here too: /api/terrain is refetched on every push, alongside /api/terrain/
  // strikes (both via the shared, cross-module deduped fetch -- l1_sse_guards.js:
  // sharedFetchJson -- so a simultaneous panels.js loadGbs() reading /api/terrain/strikes
  // for the SAME ticker on the SAME push still collapses to one real network call each).
  // /api/bars1m stays excluded -- a streamed tick, spot or option, cannot change PRIOR
  // minute bars.
  function loadGammaPushOnlyImpl(tk, _signal) {
    var host = document.getElementById('chartBody');
    if (!host || !stillChart(tk)) return;
    var sharedFetch = (window.EdL1SseGuards && window.EdL1SseGuards.sharedFetchJson) || function (u) {
      return fetch(u, { cache: 'no-store' }).then(okJson);
    };
    return Promise.all([
      sharedFetch('/api/terrain/strikes?ticker=' + encodeURIComponent(tk)).catch(nullp),
      sharedFetch('/api/terrain?ticker=' + encodeURIComponent(tk)).catch(nullp),
    ]).then(function (res) {
      if (!stillChart(tk)) return;
      var strikesData = res[0], terrain = res[1];
      if (strikesData == null || terrain == null) return;
      render(host, _lastBarsData, strikesData, terrain);
    });
  }
  var _gammaPushLoader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadGammaPushOnlyImpl(ticker(), signal); })
    : { trigger: function () { loadGammaPushOnlyImpl(ticker()); }, reset: function () {} };
  function loadGammaPushOnly() { _gammaPushLoader.trigger(ticker()); }

  function render(host, barsData, strikesData, terrain) {
    var bars = (barsData && barsData.bars) || [];
    var srows = (strikesData && strikesData.today && strikesData.today.all) || [];
    // ONE spot faucet: the chart's spot is the header's quote_tick (liveSpot), never
    // /api/terrain's or /api/terrain/strikes' copy -- those were separate producers that could
    // show a different price than the header (audit of #280). No live price -> NaN -> '-'.
    var spot = liveSpot();
    // Operator directive (2026-09-14, spot 360 audit): every payload already carries WHICH
    // spot authority answered it (resolve_spot's own design intent, "so a divergence is
    // impossible to hide") -- this was computed server-side but never shown anywhere. Reading
    // it here and rendering it below is how the NEXT divergence, if the plane/REST/stored
    // hierarchy ever disagrees again, is visible on screen instead of requiring a screenshot
    // comparison to notice.
    var spotSource = (isFinite(spot) && _liveQuote) ? _liveQuote.spot_source : null;
    if (!bars.length && !srows.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        (barsData || strikesData ? 'no bars / per-strike gamma for this symbol' : 'no console serving /api/bars1m + /api/terrain/strikes') + '</div></div>';
      return;
    }
    // A genuine context change (ticker or profile/dot mode) resets any operator zoom/pan/pin --
    // an old zoomed price window from SPY has no meaning once the ticker is AMD.
    var tk = ticker();
    if (_viewTicker !== tk || _viewMode !== _mode) { _view = null; _pin = null; _timeView = null; _viewTicker = tk; _viewMode = _mode; }
    // #3: price domain over bars + a strikes window around spot. The window is the ONE shared Gamma
    // scope policy (EdShell.scopeSelect: a strike COUNT around spot — Auto 11 / Wider / All available,
    // shared with the heatmap and GEX-by-strike); srows is the current canonical input, disclosed below.
    var asc = srows.slice().sort(function (a, b) { return a[0] - b[0]; });
    var sel = (window.EdShell && window.EdShell.scopeSelect)
      ? window.EdShell.scopeSelect(asc.map(function (r) { return r[0]; }), spot)
      : { idx: asc.map(function (_r, i) { return i; }), shown: asc.length, total: asc.length };
    var win = sel.idx.map(function (i) { return asc[i]; });
    var lo = Infinity, hi = -Infinity;
    bars.forEach(function (b) { if (b.l != null) lo = Math.min(lo, b.l); if (b.h != null) hi = Math.max(hi, b.h); });
    win.forEach(function (r) { lo = Math.min(lo, r[0]); hi = Math.max(hi, r[0]); });
    if (!isFinite(lo) || !isFinite(hi) || lo === hi) {
      if (!isFinite(spot)) {             // no bars, no strikes, no live price: say so, no fake axis
        host.innerHTML = '<div class="placeholder"><div class="sm">no price data for this symbol yet</div></div>';
        return;
      }
      lo = spot * 0.98; hi = spot * 1.02;
    }
    var pad = (hi - lo) * 0.04; lo -= pad; hi += pad;

    var note = (window.EdShell && window.EdShell.scopeNote)
      ? window.EdShell.scopeNote({ total: srows.length, shown: win.length }) : '';
    // #4: the chart overlays TWO different canonical clocks - disclose each separately, never merged.
    // price bars carry their own last-bar timestamp; the GEX profile rides the terrain generation.
    var _ab = (window.EdShell && window.EdShell.asOfBadge) ? window.EdShell.asOfBadge : function () { return ''; };
    var lastT = bars.length ? bars[bars.length - 1].t : null;
    var barsBadge = lastT ? ('<span class="asof">price 1m · ' + ctTime(lastT) + ' CT</span>') : '';
    var lvlSrc = strikesData && strikesData.today_source;
    var lvlBadge = lvlSrc ? _ab({ label: 'GEX ' + (lvlSrc === 'terrain_live_cache' ? 'terrain live' : lvlSrc),
      ageSec: strikesData.today_age_sec, stale: !!strikesData.levels_stale, reason: strikesData.levels_stale_reason,
      live: (lvlSrc === 'terrain_live_cache' && !strikesData.levels_stale) }) : '';
    var asofLine = (barsBadge || lvlBadge) ? ('<div class="chart-asof">' + barsBadge + lvlBadge + '</div>') : '';
    var legendHead = note + asofLine;
    var legend = buildLegend(legendHead, spot, spotSource);
      // The TIME PANNED/ZOOMED disclosure (see renderInto) is NOT built here: `legend` is
      // cached once per real fetch in _lastCtx and reused verbatim by every interactive
      // rerenderFromCache() call (pan/zoom/pin), so a condition on _timeView baked in at this
      // point would freeze at whatever _timeView was at the LAST REAL FETCH, never reflecting
      // an interactive drag/wheel that happens after it -- REPRODUCED live: dragging the time
      // axis visibly narrowed the window but the note never appeared. renderInto re-evaluates
      // it fresh on every call instead, the same way it already does for `lo`/`hi` under _view.
    _lastCtx = { bars: bars, win: win, spot: spot, terrain: terrain, legend: legend, legendHead: legendHead };
    renderInto(host, bars, win, spot, terrain, legend);
  }
  function buildLegend(head, spot, spotSource) {
    return head + '<div class="chart-legend">' +
      '<span><span class="sw" style="background:var(--ed-pos)"></span>+GEX</span>' +
      '<span><span class="sw" style="background:var(--ed-neg)"></span>−GEX</span>' +
      '<span><span class="sw" style="background:var(--ed-ink)"></span>spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') +
      (spotSourceLabel(spotSource) ? ' <span class="chart-spot-src">(' + esc(spotSourceLabel(spotSource)) + ')</span>' : '') + '</span>' +
      '<span><span class="sw" style="background:var(--ed-accent)"></span>flip</span>' +
      '<span class="chart-hint">drag plot to pan · drag price or time axis to rescale · scroll to zoom (hover the time axis to zoom time) · click pins a readout · double-click resets</span></div>';
  }
  // Repaints from already-fetched data at a possibly operator-overridden [lo,hi] domain -- used
  // by BOTH the real load path (auto-fit domain) and every pan/zoom/crosshair frame (cached
  // domain), so a drag never re-fetches network data to redraw.
  function renderInto(host, bars, win, spot, terrain, legend) {
    // Time window applies FIRST -- everything below (auto-fit price domain when _view is null,
    // the price line itself, the time-axis labels, crosshair bar lookup via _lastCtx.bars) must
    // see only the currently-visible slice, the same way TradingView's own price auto-fits to
    // whichever candles are actually on screen. Clamped against THIS call's bars.length, not
    // trusted from whenever _timeView was set, so a shorter fetch after a ticker/mode switch
    // (already null'd by the context-change reset above) or any other length drift can never
    // index out of bounds.
    if (_timeView && bars.length > 2) {
      var loIdx = Math.max(0, Math.min(bars.length - 2, _timeView.loIdx));
      var hiIdx = Math.max(loIdx + 1, Math.min(bars.length - 1, _timeView.hiIdx));
      bars = bars.slice(loIdx, hiIdx + 1);
    }
    var lo, hi;
    if (_view) { lo = _view.lo; hi = _view.hi; }
    else {
      lo = Infinity; hi = -Infinity;
      bars.forEach(function (b) { if (b.l != null) lo = Math.min(lo, b.l); if (b.h != null) hi = Math.max(hi, b.h); });
      win.forEach(function (r) { lo = Math.min(lo, r[0]); hi = Math.max(hi, r[0]); });
      if (!isFinite(lo) || !isFinite(hi) || lo === hi) {
        if (!isFinite(spot)) {
          host.innerHTML = legend + '<div class="placeholder"><div class="sm">no price data for this symbol yet</div></div>';
          return;
        }
        lo = spot * 0.98; hi = spot * 1.02;
      }
      var pad = (hi - lo) * 0.04; lo -= pad; hi += pad;
    }
    var svg = (_mode === 'profile')
      ? profileSvg(bars, win, spot, terrain, lo, hi)
      : dotSvg(win, spot, terrain, lo, hi);
    svg = svg.slice(0, -6) + crosshairSvg(lo, hi, _mode, bars) + '</svg>';   // insert before the closing </svg>
    // A manual time pan/zoom is never silent (same discipline every other panel's own PANNED
    // note uses) -- computed HERE, not in the cached `legend` string, specifically so an
    // interactive drag/wheel (which only ever calls renderInto, never rebuilds legend) is
    // reflected the instant it happens, not just on the next real data fetch.
    var timePannedNote = _timeView
      ? '<div class="chart-hint" style="color:var(--ed-accent-2);">TIME PANNED/ZOOMED — not the full fetched window; double-click resets</div>' : '';
    host.innerHTML = legend + timePannedNote + svg;
    // Independent-review finding (2026-09-13), REPRODUCED: binding click listeners to EVERY
    // `[data-strike]` element (both the tiny visible mark AND its invisible, larger hit
    // target) put two overlapping elements in direct competition for the same click -- a
    // real pointer (or Playwright's own actionability check) resolving to the visible one
    // finds the invisible one intercepting on top of it, and vice versa, regardless of paint
    // order. Fixed: only `.gmark-hit` (the invisible, generously-sized target) is ever
    // click-bound; the visible `.gmark` mark itself is purely visual (still the one
    // `applyChartHighlight` styles with `.csel` on selection).
    host.querySelectorAll('.gmark-hit').forEach(function (el) {   // A: click a mark -> sync all panels
      el.style.cursor = 'pointer';
      // Independent-review finding (2026-09-13), REPRODUCED: this click always passed NO
      // expiry, unlike the heatmap (real per-column expiry) and Chain (the one displayed
      // expiry) -- both of which always supply setStrike a real expiry. /api/terrain/strikes
      // is a genuine all-expiry aggregate (no per-mark expiry exists to attribute), but a
      // Chart click is still a deliberate strike selection and should carry through whatever
      // workspace expiry filter is currently set, the same as every other view does, instead
      // of unconditionally clobbering state.selExpiry to null via ed-core.js:setStrike.
      el.addEventListener('click', function () {
        if (!window.EdShell) return;
        var expFilter = window.EdShell.getExpiry ? window.EdShell.getExpiry() : null;
        window.EdShell.setStrike(Number(el.getAttribute('data-strike')), expFilter || null);
      });
    });
    applyChartHighlight(host);
    wireChartInteraction(host, lo, hi);
  }
  function applyChartHighlight(host) {
    host = host || document.getElementById('chartBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.gmark.csel').forEach(function (n) { n.classList.remove('csel'); });
    if (sel == null) return;
    host.querySelectorAll('.gmark[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('csel'); });
  }

  var W = 1000, H = 540, T = 12, B = 24, L = 52, R = 10;
  function yOf(p, lo, hi) { return T + (1 - (p - lo) / (hi - lo)) * (H - T - B); }

  // A SEVENTH independent review (2026-09-13), REPRODUCED: `.gmark-hit`'s fixed minimum
  // size (10px half-height / radius, so a tiny visible bar/dot stays real-pointer-clickable
  // -- see the click-target-widening comments below) never shrank back down at DENSE scope.
  // At 61 strikes the adjacent-strike pixel spacing can fall well under 20px, so three
  // neighboring strikes' fixed-10px hit targets all cover the SAME point at the middle
  // strike's own center -- reproduced: strikes 119/120/121's hit rects all overlap strike
  // 120's centre, making a real click there ambiguous among three strikes instead of
  // unambiguously hitting one. Fixed at the root: the hit target's half-size is capped to
  // half the ACTUAL minimum pixel gap between any two adjacent visible strikes (never
  // assumed uniform -- real chains mix $0.50/$1/$5 strike spacing), so adjacent targets can
  // touch but never overlap, even though that means shrinking below the 10px minimum at the
  // very densest scopes (a smaller-but-unambiguous target beats a larger-but-ambiguous one).
  function _hitTargetHalfSize(win, lo, hi, desiredHalf) {
    if (!win || win.length < 2) return desiredHalf;
    var ys = win.map(function (r) { return yOf(r[0], lo, hi); }).sort(function (a, b) { return a - b; });
    var minGap = Infinity;
    for (var i = 1; i < ys.length; i++) {
      var gap = ys[i] - ys[i - 1];
      if (gap > 0 && gap < minGap) minGap = gap;
    }
    if (!isFinite(minGap)) return desiredHalf;
    return Math.min(desiredHalf, minGap / 2);
  }

  // Independent-review finding (2026-09-13), REPRODUCED: a level line (flip/call-wall/put-wall)
  // drawn at the SAME price as a visible strike mark sits on top of it in SVG paint order and
  // intercepted real pointer clicks meant for that mark -- not a test artifact (a real Playwright
  // click on strike 102 hit the call-wall line drawn at that exact height, since the fixture's
  // call_wall genuinely equals 102) but a real interaction defect for an actual mouse user too.
  // These lines/labels have no click handler of their own; wrapped in a `pointer-events="none"`
  // group so they are purely visual and never steal a click from whatever mark sits beneath them.
  function levelLines(terrain, lo, hi, x1, x2) {
    if (!terrain) return '';
    var out = '';
    function line(v, color, label, dash) {
      if (v == null || isNaN(v) || v < lo || v > hi) return;
      var y = yOf(v, lo, hi).toFixed(1);
      out += '<line x1="' + x1 + '" x2="' + x2 + '" y1="' + y + '" y2="' + y + '" stroke="' + color +
        '" stroke-width="1"' + (dash ? ' stroke-dasharray="4 3"' : '') + ' opacity="0.85"/>' +
        '<text x="' + (x2 - 3) + '" y="' + (y - 3) + '" text-anchor="end" font-size="10" fill="' + color + '">' + esc(label) + '</text>';
    }
    line(terrain.gamma_flip, COL.flip, 'flip ' + fmt(terrain.gamma_flip), true);
    line(terrain.call_wall, COL.call, 'call wall ' + fmt(terrain.call_wall), false);
    line(terrain.put_wall, COL.put, 'put wall ' + fmt(terrain.put_wall), false);
    return out ? '<g pointer-events="none">' + out + '</g>' : '';
  }
  function fmt(v){ return (v==null||isNaN(v))?'':Number(v).toFixed(2); }

  function priceAxis(lo, hi) {
    var out = '', n = 5;
    for (var i = 0; i <= n; i++) {
      var p = lo + (hi - lo) * i / n, y = yOf(p, lo, hi).toFixed(1);
      out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="' + COL.axis + '" stroke-width="0.5" opacity="0.5"/>' +
        '<text x="' + (L - 5) + '" y="' + (Number(y) + 3) + '" text-anchor="end" font-size="9">' + p.toFixed(2) + '</text>';
    }
    return '<g pointer-events="none">' + out + '</g>';
  }

  function profileSvg(bars, win, spot, terrain, lo, hi) {
    var xSplit = Math.round(W * 0.60);
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart-svg" preserveAspectRatio="none" role="img" aria-label="Price and GEX profile">';
    s += priceAxis(lo, hi);
    // price line (closes) in the left region
    if (bars.length) {
      var x0 = L, x1 = xSplit - 10, n = bars.length;
      var pts = bars.map(function (b, i) {
        var x = x0 + (n === 1 ? 0 : i / (n - 1) * (x1 - x0));
        return x.toFixed(1) + ',' + yOf(b.c, lo, hi).toFixed(1);
      }).join(' ');
      s += '<polyline points="' + pts + '" fill="none" stroke="var(--ed-ink-2)" stroke-width="1.2"/>';
      // time ticks
      [0, Math.floor(n / 2), n - 1].forEach(function (i) {
        if (!bars[i]) return; var x = (x0 + (n === 1 ? 0 : i / (n - 1) * (x1 - x0)));
        s += '<text x="' + x.toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="9">' + ctTime(bars[i].t) + '</text>';
      });
    }
    // GEX profile in the right region, signed bars from a zero axis
    var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
    var cx = xSplit + 8, right = W - R - 4, halfW = (right - cx);
    var hitHalfH = _hitTargetHalfSize(win, lo, hi, 10);
    s += '<line x1="' + cx + '" x2="' + cx + '" y1="' + T + '" y2="' + (H - B) + '" stroke="' + COL.axis + '" stroke-width="1"/>';
    win.forEach(function (r) {
      var k = r[0], v = Number(r[1]) || 0, w = Math.abs(v) / maxAbs * halfW;
      var y = yOf(k, lo, hi), pos = v >= 0;
      s += '<rect class="gmark" data-strike="' + k + '" x="' + (pos ? cx : cx - w).toFixed(1) + '" y="' + (y - 3).toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="6" fill="' + (pos ? COL.pos : COL.neg) + '" opacity="0.85"/>';
      // A visible 6-unit-tall bar renders as ~2 real screen pixels in this panel's usual
      // size -- a genuine click-target usability defect for a real pointer, not just a test
      // artifact (independent-review finding, 2026-09-13: "real clicks can miss"). A
      // SEPARATE, distinctly-classed (`gmark-hit`, not `gmark`) invisible, much taller hit
      // target carries the click binding instead of sharing the visible mark's own class --
      // two overlapping same-class elements competing for one pointer event intercepted each
      // other regardless of paint order (reproduced with a real Playwright click); giving the
      // hit target its OWN class makes it the one and only interactive element at this spot.
      // `hitHalfH` (a SEVENTH independent review, 2026-09-13) caps that height to the actual
      // inter-strike spacing at DENSE scope -- see `_hitTargetHalfSize`'s own docstring --
      // so adjacent strikes' hit rects can never overlap each other's centre.
      s += '<rect class="gmark-hit" data-strike="' + k + '" x="' + (cx - halfW).toFixed(1) + '" y="' + (y - hitHalfH).toFixed(1) +
        '" width="' + (2 * halfW).toFixed(1) + '" height="' + (2 * hitHalfH).toFixed(1) + '" fill="transparent"/>';
    });
    // biggest-magnitude label
    var top = win.slice().sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); })[0];
    if (top) { var yt = yOf(top[0], lo, hi); s += '<text x="' + (cx + 4) + '" y="' + (yt - 5).toFixed(1) + '" font-size="10" fill="var(--ed-ink-2)">' + esc(usd(top[1])) + '</text>'; }
    // overlays
    s += levelLines(terrain, lo, hi, L, W - R);
    if (isFinite(spot)) {
      var ys = yOf(spot, lo, hi).toFixed(1);
      // Independent-review finding (2026-09-13): the spot line/label, unlike levelLines and
      // priceAxis right above, was never wrapped in `pointer-events="none"` -- the same real
      // paint-order click interception those two were fixed for (a mark drawn UNDER a
      // non-interactive overlay line at the same screen height loses the click to the line)
      // remains possible here whenever a strike's own y-position coincides with spot's.
      s += '<g pointer-events="none"><line x1="' + L + '" x2="' + (W - R) + '" y1="' + ys + '" y2="' + ys + '" stroke="' + COL.spot + '" stroke-width="1.2" stroke-dasharray="2 2"/>' +
        '<text x="' + (L + 3) + '" y="' + (Number(ys) - 3) + '" font-size="10" fill="' + COL.spot + '">spot ' + spot.toFixed(2) + '</text></g>';
    }
    return s + '</svg>';
  }

  function dotSvg(win, spot, terrain, lo, hi) {
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart-svg" preserveAspectRatio="none" role="img" aria-label="GEX dot map">';
    s += priceAxis(lo, hi);
    var cx = Math.round(W * 0.5);
    var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
    var hitR = _hitTargetHalfSize(win, lo, hi, 10);
    s += '<line x1="' + cx + '" x2="' + cx + '" y1="' + T + '" y2="' + (H - B) + '" stroke="' + COL.axis + '" stroke-width="0.5" opacity="0.4"/>';
    win.forEach(function (r) {
      var k = r[0], v = Number(r[1]) || 0, y = yOf(k, lo, hi);
      var rad = 3 + Math.sqrt(Math.abs(v) / maxAbs) * 22;
      var pos = v >= 0, x = cx + (pos ? 1 : -1) * (rad + 10);
      s += '<circle class="gmark" data-strike="' + k + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + rad.toFixed(1) +
        '" fill="' + (pos ? COL.pos : COL.neg) + '" opacity="0.55" stroke="' + (pos ? COL.pos : COL.neg) + '"/>' +
        // Same click-target widening as profileSvg's bars, on its own `gmark-hit` class (see
        // that comment) -- a small-magnitude dot can shrink to a real-pointer-unfriendly few
        // pixels; the invisible hit circle never shrinks below a usable minimum radius UNLESS
        // (a SEVENTH independent review, 2026-09-13) the actual inter-strike spacing at dense
        // scope is itself narrower than that minimum -- `hitR` caps to that spacing so
        // adjacent strikes' hit circles can never overlap each other's centre.
        '<circle class="gmark-hit" data-strike="' + k + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + hitR.toFixed(1) +
        '" fill="transparent"/>' +
        '<text x="' + (pos ? x + rad + 4 : x - rad - 4).toFixed(1) + '" y="' + (y + 3).toFixed(1) + '" text-anchor="' + (pos ? 'start' : 'end') +
        '" font-size="9" fill="var(--ed-ink-2)">' + esc(usd(v)) + '</text>';
    });
    s += levelLines(terrain, lo, hi, L, W - R);
    if (isFinite(spot)) {
      var ys = yOf(spot, lo, hi).toFixed(1);
      // Independent-review finding (2026-09-13): see profileSvg's identical fix -- the spot
      // line/label was never wrapped in `pointer-events="none"` like levelLines/priceAxis.
      s += '<g pointer-events="none"><line x1="' + L + '" x2="' + (W - R) + '" y1="' + ys + '" y2="' + ys + '" stroke="' + COL.spot + '" stroke-width="1.2" stroke-dasharray="2 2"/>' +
        '<text x="' + (L + 3) + '" y="' + (Number(ys) - 3) + '" font-size="10" fill="' + COL.spot + '">spot ' + spot.toFixed(2) + '</text></g>';
    }
    return s + '</svg>';
  }

  // mode toggle (buttons live in #chartModes; shown only on the Chart view)
  function bindModes() {
    var host = document.getElementById('chartModes');
    if (!host) return;
    host.querySelectorAll('.cmode').forEach(function (b) {
      b.addEventListener('click', function () {
        _mode = b.getAttribute('data-cmode');
        host.querySelectorAll('.cmode').forEach(function (x) { x.classList.toggle('on', x === b); });
        load();
      });
    });
  }

  function applyQuoteTick(q) {
    if (!q || !sameSym(q.ticker, ticker())) return;
    _liveQuote = q;
    if (!isChart() || !_lastCtx) return;
    var bars = (_lastCtx.bars || []).slice();
    var f = q.forming_1m;                 // THE forming candle, built server-side
    if (f && f.t != null) {
      var lastT = bars.length ? bars[bars.length - 1].t : null;
      if (lastT != null && Number(f.t) === Number(lastT)) bars[bars.length - 1] = f;
      else if (lastT == null || Number(f.t) > Number(lastT)) bars = bars.concat([f]);
    }
    var spot = liveSpot();
    _lastCtx.bars = bars;
    _lastCtx.spot = spot;
    _lastCtx.legend = buildLegend(_lastCtx.legendHead || '', spot, isFinite(spot) ? q.spot_source : null);
    var host = document.getElementById('chartBody');
    if (host) renderInto(host, bars, _lastCtx.win, spot, _lastCtx.terrain, _lastCtx.legend);
  }
  window.addEventListener('ed:quote_tick', function (ev) { applyQuoteTick((ev && ev.detail) || {}); });

  document.addEventListener('ed:view', load);
  document.addEventListener('ed:ticker', function () { _lastBarsData = null; load(); });
  document.addEventListener('ed:scope', load);   // #3: re-window on a scope change
  document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
  // Audit finding #3 (2026-09-16, follow-up): only /api/terrain/strikes (this widget's
  // GEX-by-strike profile) is gamma-surface-derived -- react to the narrow push with the
  // SCOPED reload (loadGammaPushOnlyImpl, above), never the full load() the 12s poll uses,
  // which would also refetch /api/bars1m and /api/terrain for no reason on every streamed tick.
  document.addEventListener('ed:gamma-push', loadGammaPushOnly);
  document.addEventListener('ed:strike', function () { applyChartHighlight(); });   // A: cross-panel sync
  document.addEventListener('ed:theme', load);   // re-render SVG for the new theme's tokens
  // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
  // deferred ed:ticker/ed:view dispatch (see that file's init() comment) -- bindModes() is
  // pure DOM/button wiring with no data dependency, so it still runs immediately here.
  bindModes();
})();
