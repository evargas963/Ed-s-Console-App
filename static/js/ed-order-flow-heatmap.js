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
  function ticker() { return (st().ticker || 'SPY'); }
  function stillHeatmap(tk) { return isHeatmap() && ticker() === tk; }

  var _minutes = 60;
  function host() { return document.getElementById('ofhBody'); }
  function canvasEl() { return document.getElementById('ofhCanvas'); }

  function fmtCT(ts) {
    try {
      return new Date(ts * 1000).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return '—'; }
  }

  // Robust Y-axis bounds: the raw price_min/price_max can be dragged wide by one thin resting
  // order far from the touch (real book data, but not what a reader should have to scroll past)
  // -- drop the outer 1% of cumulative displayed volume on each side instead of a hard clip.
  function tightRange(cells) {
    var totals = {};
    cells.forEach(function (c) { var v = (c.bid || 0) + (c.ask || 0); totals[c.price] = (totals[c.price] || 0) + v; });
    var prices = Object.keys(totals).map(Number).sort(function (a, b) { return a - b; });
    if (!prices.length) return null;
    var totalVol = prices.reduce(function (s, p) { return s + totals[p]; }, 0) || 1;
    var cum = 0, lo = null, hi = null;
    for (var i = 0; i < prices.length; i++) {
      cum += totals[prices[i]];
      if (lo == null && cum / totalVol >= 0.01) lo = prices[i];
      if (cum / totalVol <= 0.99) hi = prices[i];
    }
    if (lo == null) lo = prices[0];
    if (hi == null || hi <= lo) hi = prices[prices.length - 1];
    return { lo: lo, hi: Math.max(hi, lo + 0.01) };
  }

  function render(h, tk, d) {
    if (!d || !d.available) {
      h.innerHTML = '<div class="placeholder"><div class="sm">' + esc((d && d.reason) || 'no book history for ' + tk) + '</div></div>';
      return;
    }
    var range = tightRange(d.cells);
    if (!range) {
      h.innerHTML = '<div class="placeholder"><div class="sm">rows were captured but carried no populated price levels</div></div>';
      return;
    }
    var priceRows = 48;
    var priceStep = (range.hi - range.lo) / priceRows || 0.01;
    var nBuckets = d.n_buckets || 90;
    var bidGrid = new Float64Array(priceRows * nBuckets);
    var askGrid = new Float64Array(priceRows * nBuckets);
    var inRange = false;
    d.cells.forEach(function (c) {
      if (c.price < range.lo || c.price > range.hi) return;
      inRange = true;
      var row = Math.min(priceRows - 1, Math.max(0, Math.floor((c.price - range.lo) / priceStep)));
      // c.t is server-supplied; clamp it the same way `row` is clamped just above -- an
      // out-of-range bucket index (an off-by-one boundary tick, or a stale response racing a
      // `minutes` change) would otherwise land in the row directly above via integer overflow
      // of `row*nBuckets+col`, painting a false hot cell in an unrelated price row.
      var col = Math.min(nBuckets - 1, Math.max(0, c.t | 0));
      var idx = row * nBuckets + col;
      bidGrid[idx] += c.bid || 0; askGrid[idx] += c.ask || 0;
    });
    var maxV = 1;
    for (var i = 0; i < bidGrid.length; i++) { if (bidGrid[i] > maxV) maxV = bidGrid[i]; if (askGrid[i] > maxV) maxV = askGrid[i]; }

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
      for (var row = 0; row < priceRows; row++) {
        for (var col = 0; col < nBuckets; col++) {
          var idx2 = row * nBuckets + col;
          var bv = bidGrid[idx2], av = askGrid[idx2];
          var x = padLeft + col * colW, y = padTop + (priceRows - 1 - row) * rowH;
          if (bv === 0 && av === 0) continue;
          var dom = bv >= av ? bv : av, other = bv >= av ? av : bv;
          var t = Math.min(1, dom / maxV);
          var lo2 = Math.min(1, other / maxV);
          var base = bv >= av ? [35, 192, 107] : [229, 72, 77];
          var bright = 0.15 + 0.85 * t;
          var r = Math.round(base[0] * bright + 15 * (1 - bright));
          var g = Math.round(base[1] * bright + 22 * (1 - bright));
          var bl = Math.round(base[2] * bright + 34 * (1 - bright));
          ctx.fillStyle = 'rgb(' + r + ',' + g + ',' + bl + ')';
          ctx.fillRect(x, y, Math.max(1, colW - 0.5), rowH - 0.5);
          if (lo2 > 0.05) { ctx.fillStyle = 'rgba(255,255,255,' + (0.12 * lo2).toFixed(2) + ')'; ctx.fillRect(x, y, Math.max(1, colW - 0.5), rowH - 0.5); }
        }
      }
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
    }

    var rowsInfo = d.rows_scanned + (d.rows_capped ? '+ (capped)' : '') + ' book ticks · ' +
      fmtCT(d.since_ts) + '–' + fmtCT(d.until_ts) + ' CT · latest capture ' + fmtCT(d.latest_captured_ts) + ' CT';
    h.innerHTML = '';
    h.appendChild(canvas);
    var foot = document.createElement('div');
    foot.className = 'fl-foot';
    foot.textContent = rowsInfo + ' — every cell traces to a real captured tick; nothing is interpolated between ticks.';
    h.appendChild(foot);
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillHeatmap(tk)) return;
    h.setAttribute('aria-busy', 'true');
    return fetch('/api/order-flow/book-heatmap?ticker=' + encodeURIComponent(tk) + '&minutes=' + _minutes, { cache: 'no-store', signal: signal })
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
    _loader.trigger(ticker() + '|' + _minutes);
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    document.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-ofh-minutes]');
      if (!btn) return;
      _minutes = Number(btn.getAttribute('data-ofh-minutes')) || 60;
      document.querySelectorAll('[data-ofh-minutes]').forEach(function (b) { b.classList.toggle('on', b === btn); });
      load();
    });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
