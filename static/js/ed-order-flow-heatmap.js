/* Ed Console — Order Flow / "Heatmap" subview. PRESENTATION ONLY.
   The Bookmap-style view the live Book/DOM ladder cannot show: a real TIME dimension. Reads
   /api/order-flow/book-heatmap, a pure serializer over app.options.order_flow.history.
   book_heatmap_for_ticker, which bins the SAME persisted stream_book_raw rows the ladder reads
   (NASDAQ_BOOK+NYSE_BOOK) into a time x price grid of native TOTAL_VOLUME. Every cell traces to
   a real captured tick; nothing here interpolates, smooths, or invents a value between ticks.
   Color: green = bid-dominant displayed size, red = ask-dominant, brightness = relative size —
   the same pos/neg convention every other panel in this app already uses. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isHeatmap() { var s = st(); return s.workspace === 'order-flow' && s.subview === 'heatmap'; }
  function ticker() { return (st().ticker || ''); }
  function stillHeatmap(tk) { return isHeatmap() && ticker() === tk; }

  var _minutes = 60;
  function host() { return document.getElementById('ofhBody'); }
  function canvasEl() { return document.getElementById('ofhCanvas'); }

  // ---- Repo-wide chart interaction standard (same contract as ed-gamma-chart.js: axis-drag
  // rescales, plot-drag pans, wheel zooms around the cursor, a real click pins a crosshair
  // readout instead of following hover, double-click resets). Second wiring of it, first on a
  // canvas rather than an SVG -- geometry comes from CSS pixels via getBoundingClientRect()
  // instead of a viewBox transform, everything else is the same contract. ----
  var _view = null, _pin = null, _lastD = null, _viewTicker = null;
  var _interactionInstalled = false, _dragState = null;
  function clientToCanvas(canvas, clientX, clientY) {
    var r = canvas.getBoundingClientRect();
    return { px: clientX - r.left, py: clientY - r.top };
  }
  // Same floor/clamp contract as ed-gamma-chart.js's clampDomain and
  // ed-liquidity-map.js's clampPriceDomain (both independent-review findings,
  // REPRODUCED, on this exact interaction pattern): unclamped, repeated wheel-in/
  // axis-drag-in ticks shrink (hi-lo) toward zero with no floor. This is the same
  // price-axis pan/zoom contract on a third surface (canvas here, vs SVG/DOM percent
  // elsewhere) and needs the identical floor.
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
      var canvas = canvasEl();
      if (!canvas) return;
      var p = clientToCanvas(canvas, e.clientX, e.clientY);
      if (Math.abs(p.py - _dragState.startPy) > 2 || Math.abs(p.px - _dragState.startPx) > 2) _dragState.moved = true;
      var span = _dragState.startHi - _dragState.startLo, plotH = _dragState.plotH;
      var dy = p.py - _dragState.startPy;
      if (_dragState.mode === 'pan') {
        var priceDelta = dy / plotH * span;   // canvas y grows downward; price grows upward
        _view = clampPriceDomain(_dragState.startLo + priceDelta, _dragState.startHi + priceDelta);
      } else {
        var anchor = _dragState.startHi - (_dragState.startPy - _dragState.padTop) / plotH * span;
        var factor = Math.pow(1.006, dy);
        _view = clampPriceDomain(anchor - (anchor - _dragState.startLo) * factor, anchor + (_dragState.startHi - anchor) * factor);
      }
      rerenderFromCache();
    });
    document.addEventListener('mouseup', function (e) {
      if (!_dragState) return;
      if (!_dragState.moved) {
        var canvas = canvasEl();
        if (canvas) {
          var p = clientToCanvas(canvas, e.clientX, e.clientY);
          _pin = (_pin && Math.abs(_pin.px - p.px) < 0.5 && Math.abs(_pin.py - p.py) < 0.5) ? null : p;
          rerenderFromCache();
        }
      }
      _dragState = null;
    });
  }
  function wireHeatmapInteraction(canvas, padLeft, padTop, plotW, plotH, lo, hi) {
    installInteractionOnce();
    canvas.setAttribute('draggable', 'false');
    canvas.style.webkitUserDrag = 'none';
    canvas.style.cursor = 'crosshair';
    canvas.addEventListener('dragstart', function (e) { e.preventDefault(); });
    canvas.addEventListener('mousedown', function (e) {
      var p = clientToCanvas(canvas, e.clientX, e.clientY);
      _dragState = { mode: (p.px < padLeft ? 'axis' : 'pan'), startPx: p.px, startPy: p.py,
        startLo: lo, startHi: hi, padTop: padTop, plotH: plotH, moved: false };
      e.preventDefault();
    });
    canvas.addEventListener('wheel', function (e) {
      e.preventDefault();
      var p = clientToCanvas(canvas, e.clientX, e.clientY);
      var anchor = hi - (p.py - padTop) / plotH * (hi - lo);
      var factor = e.deltaY > 0 ? 1.12 : (1 / 1.12);
      _view = clampPriceDomain(anchor - (anchor - lo) * factor, anchor + (hi - anchor) * factor);
      rerenderFromCache();
    }, { passive: false });
    canvas.addEventListener('dblclick', function () { _view = null; _pin = null; rerenderFromCache(); });
  }
  function rerenderFromCache() {
    var h = host();
    if (!h || !_lastD) return;
    renderInto(h, _viewTicker, _lastD);
  }

  function fmtCT(ts) {
    try {
      return new Date(ts * 1000).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return '—'; }
  }

  function render(h, tk, d) {
    if (!d || !d.available) {
      h.innerHTML = '<div class="placeholder"><div class="sm">' + esc((d && d.reason) || 'no book history for ' + tk) + '</div></div>';
      return;
    }
    if (_viewTicker !== tk) { _view = null; _pin = null; _viewTicker = tk; }
    _lastD = d;
    renderInto(h, tk, d);
  }
  function renderInto(h, tk, d) {
    // the default window is served (display_lo/hi); the page only zooms and pans it
    var autoRange = d.display_lo == null ? null : { lo: d.display_lo, hi: d.display_hi };
    if (!autoRange) {
      h.innerHTML = '<div class="placeholder"><div class="sm">rows were captured but carried no populated price levels</div></div>';
      return;
    }
    var range = _view || autoRange;
    var priceRows = 48;
    var priceStep = (range.hi - range.lo) / priceRows || 0.01;
    var nBuckets = d.n_buckets || 90;
    // each served cell is drawn at its own price and bucket -- nothing is summed or re-binned;
    // colour is its served side, brightness its size against the served max_size
    var visible = d.cells.filter(function (c) { return c.price >= range.lo && c.price <= range.hi; });
    var inRange = visible.length > 0;
    var maxV = d.max_size || 1;
    function rowOf(price) { return Math.min(priceRows - 1, Math.max(0, Math.floor((price - range.lo) / priceStep))); }
    function colOf(t) { return Math.min(nBuckets - 1, Math.max(0, t | 0)); }

    var padLeft = 58, padBottom = 22, padTop = 4, padRight = 4;
    var plotW = Math.max(300, (h.clientWidth || 700) - padLeft - padRight);
    var colW = plotW / nBuckets;
    var rowH = 9;
    var plotH = priceRows * rowH;
    var cw = padLeft + plotW + padRight, ch = padTop + plotH + padBottom;

    var canvas = document.createElement('canvas');
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    canvas.style.width = cw + 'px'; canvas.style.height = ch + 'px';
    canvas.id = 'ofhCanvas';
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#0f1622'; ctx.fillRect(0, 0, cw, ch);

    if (!inRange) {
      ctx.fillStyle = '#c7d2e0'; ctx.font = '12px Inter, sans-serif';
      ctx.fillText('no cells fell inside the computed price window', padLeft, padTop + 16);
    } else {
      visible.forEach(function (c) {
          var bv = c.bid, av = c.ask;
          var x = padLeft + colOf(c.t) * colW, y = padTop + (priceRows - 1 - rowOf(c.price)) * rowH;
          if (!bv && !av) return;
          var bidSide = c.side !== 'ASK';
          var dom = bidSide ? bv : av, other = bidSide ? av : bv;
          var t = Math.min(1, dom / maxV);
          var lo2 = Math.min(1, other / maxV);
          var base = bidSide ? [35, 192, 107] : [229, 72, 77];
          var bright = 0.15 + 0.85 * t;
          var r = Math.round(base[0] * bright + 15 * (1 - bright));
          var g = Math.round(base[1] * bright + 22 * (1 - bright));
          var bl = Math.round(base[2] * bright + 34 * (1 - bright));
          ctx.fillStyle = 'rgb(' + r + ',' + g + ',' + bl + ')';
          ctx.fillRect(x, y, Math.max(1, colW - 0.5), rowH - 0.5);
          if (lo2 > 0.05) { ctx.fillStyle = 'rgba(255,255,255,' + (0.12 * lo2).toFixed(2) + ')'; ctx.fillRect(x, y, Math.max(1, colW - 0.5), rowH - 0.5); }
      });
      // Y axis price labels
      ctx.fillStyle = '#c7d2e0'; ctx.font = '10px Inter, sans-serif'; ctx.textAlign = 'right';
      var yTicks = 6;
      for (var yt = 0; yt <= yTicks; yt++) {
        var price = range.lo + (range.hi - range.lo) * (yt / yTicks);
        var yy = padTop + plotH - (yt / yTicks) * plotH;
        ctx.fillText(price.toFixed(2), padLeft - 6, yy + 3);
        ctx.strokeStyle = 'rgba(199,210,224,0.08)'; ctx.beginPath(); ctx.moveTo(padLeft, yy); ctx.lineTo(padLeft + plotW, yy); ctx.stroke();
      }
      ctx.textAlign = 'left';
      // X axis time labels (Central Time, per this app's own clock convention)
      var xTicks = 5;
      for (var xt = 0; xt <= xTicks; xt++) {
        var frac = xt / xTicks;
        var bucketIdx = Math.round(frac * (nBuckets - 1));
        var ts = d.since_ts + bucketIdx * d.bucket_sec;
        var xx = padLeft + bucketIdx * colW;
        ctx.fillText(fmtCT(ts), Math.min(xx, padLeft + plotW - 34), padTop + plotH + 15);
      }
      // click-to-pin crosshair -- never follows hover; stays put across the next redraw
      // (pan/zoom/data refresh) until clicked again or the ticker changes.
      if (_pin && _pin.px >= padLeft && _pin.px <= padLeft + plotW && _pin.py >= padTop && _pin.py <= padTop + plotH) {
        var pinPrice = range.lo + (range.hi - range.lo) * (1 - (_pin.py - padTop) / plotH);
        var pinCol = Math.min(nBuckets - 1, Math.max(0, Math.floor((_pin.px - padLeft) / colW)));
        var pinTs = d.since_ts + pinCol * d.bucket_sec;
        // the served cell drawn under the pin (hit-testing the drawing): its own bid and ask
        var pinRow = rowOf(pinPrice), hit = null;
        visible.forEach(function (c) { if (colOf(c.t) === pinCol && rowOf(c.price) === pinRow) hit = c; });
        var pinBid = hit ? hit.bid : null, pinAsk = hit ? hit.ask : null;
        ctx.strokeStyle = 'rgba(97,165,255,0.85)'; ctx.setLineDash([3, 2]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(padLeft, _pin.py); ctx.lineTo(padLeft + plotW, _pin.py); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(_pin.px, padTop); ctx.lineTo(_pin.px, padTop + plotH); ctx.stroke();
        ctx.setLineDash([]);
        var boxLines = [pinPrice.toFixed(2), fmtCT(pinTs) + ' CT', 'bid ' + (pinBid == null ? '—' : Math.round(pinBid)), 'ask ' + (pinAsk == null ? '—' : Math.round(pinAsk))];
        var boxX = Math.min(_pin.px + 8, cw - 100), boxY = Math.max(padTop, Math.min(_pin.py - 8, padTop + plotH - boxLines.length * 12 - 8));
        ctx.fillStyle = 'rgba(23,32,46,0.96)'; ctx.strokeStyle = 'rgba(97,165,255,0.9)';
        ctx.fillRect(boxX, boxY, 96, boxLines.length * 12 + 8); ctx.strokeRect(boxX, boxY, 96, boxLines.length * 12 + 8);
        ctx.fillStyle = '#f6f9fd'; ctx.font = '10px Inter, sans-serif'; ctx.textAlign = 'left';
        boxLines.forEach(function (t, i) { ctx.fillText(t, boxX + 5, boxY + 13 + i * 12); });
      }
    }

    var rowsInfo = d.rows_scanned + (d.rows_capped ? '+ (capped)' : '') + ' book ticks · ' +
      fmtCT(d.since_ts) + '–' + fmtCT(d.until_ts) + ' CT · latest capture ' + fmtCT(d.latest_captured_ts) + ' CT';
    h.innerHTML = '';
    h.appendChild(canvas);
    var foot = document.createElement('div');
    foot.className = 'fl-foot';
    foot.textContent = rowsInfo + ' — every cell traces to a real captured tick; nothing is interpolated between ticks. ' +
      'Drag the plot to pan, drag the price axis to rescale, scroll to zoom, click pins a readout, double-click resets.';
    h.appendChild(foot);
    wireHeatmapInteraction(canvas, padLeft, padTop, plotW, plotH, range.lo, range.hi);
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillHeatmap(tk)) return;
    h.setAttribute('aria-busy', 'true');
    // Operator-reproduced defect (2026-09-14): opening this tab directly made NO book-
    // subscription request of its own, so a fresh capture for this ticker depended entirely on
    // some OTHER screen (Book/DOM, Trade Desk) having already asked for it. This view reads
    // captured history, not the live ladder, but the history has nothing to bin until something
    // asks the stream to start capturing this ticker's book -- so it must ask too.
    if (window.EdStream && window.EdStream.warmActiveTicker) window.EdStream.warmActiveTicker(tk);
    return fetch('/api/order-flow/book-heatmap?ticker=' + encodeURIComponent(tk) + '&venue=' + st().bookVenue + '&minutes=' + _minutes, { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillHeatmap(tk)) render(h, tk, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillHeatmap(tk)) h.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/order-flow/book-heatmap</div></div>';
      });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() {
    if (!isHeatmap()) return;
    var tEl = document.getElementById('ofhTicker'); if (tEl) tEl.textContent = ticker().replace('$', '');
    // Key on ticker+minutes, not ticker alone -- clicking a different time-range button while
    // the previous window's fetch is still in flight must ABORT it (a real context change),
    // not just queue a trailing re-run behind it (what an unchanged key does).
    _loader.trigger(ticker() + '|' + st().bookVenue + '|' + _minutes);
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:book_venue', load);
    document.addEventListener('ed:changed', function (e) { if (e.detail.kind === 'flow') load(); });
    document.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-ofh-minutes]');
      if (!btn) return;
      _minutes = Number(btn.getAttribute('data-ofh-minutes')) || 60;
      document.querySelectorAll('[data-ofh-minutes]').forEach(function (b) { b.classList.toggle('on', b === btn); });
      load();
    });
    // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
    // deferred ed:ticker/ed:view dispatch -- see that file's init() comment.
  }
})();
