/* Ed Console — the ONE TradingView-style chart (window.EdTvChart). PRESENTATION ONLY.

   Engine: TradingView Lightweight Charts 5.2.1 (Apache-2.0), vendored unmodified at
   /static/vendor/lightweight-charts/ (npm tarball sha512 verified 2026-09-25). Its license asks
   for a link to tradingview.com; `attributionLogo: true` renders that link on every chart.

   The operator's chart standard (feedback_chart_interactions_mirror_tradingview), measured
   against the library on real SPY bars before use:
     - plot drag pans BOTH ways. The library pans price vertically only once the price scale is
       out of auto-fit; TradingView turns auto-fit off the moment you drag vertically. The one
       gap is closed below (installVerticalPan) -- everything else is the library's own.
     - price-axis drag rescales price, time-axis drag rescales time, double-click an axis
       resets it, Alt+R resets everything, the wheel zooms time.
     - the crosshair follows the mouse; the readout BOX appears only on click (pinned, with a
       close control) -- never a hover tooltip.
   Every number drawn here is the server's (bars from /api/bars1m, levels from /api/levels +
   /api/terrain). Choosing WHICH levels to draw (the nearest few inside the visible range) and
   placing a 1m series point on the bar that contains it are presentation, not computation. */
(function () {
  'use strict';
  var LWC = window.LightweightCharts;

  var CT_TIME = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit', hour12: false });
  var CT_DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', month: 'short', day: 'numeric' });
  var CT_FULL = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  var CT_YEAR = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', year: 'numeric' });
  var CT_MONTH = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', month: 'short' });

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function fmtVol(n) {
    if (n == null || isNaN(n)) return '—';
    var a = Math.abs(Number(n));
    if (a >= 1e9) return (a / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return (a / 1e6).toFixed(2) + 'M';
    if (a >= 1e3) return (a / 1e3).toFixed(1) + 'K';
    return String(Math.round(a));
  }
  function tok(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  function alpha(hex, a) {
    var m = /^#([0-9a-f]{6})$/i.exec(String(hex).trim());
    if (!m) return hex;
    var n = parseInt(m[1], 16);
    return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }
  function palette() {
    return {
      bg: tok('--ed-panel', '#0f1622'), text: tok('--ed-ink-2', '#d3ddeb'), ink: tok('--ed-ink', '#f6f9fd'),
      grid: tok('--ed-edge-soft', '#212d3d'), edge: tok('--ed-edge', '#324055'),
      up: tok('--ed-pos', '#23c06b'), down: tok('--ed-neg', '#e5484d'),
      accent: tok('--ed-accent', '#3d8bfd'), accent2: tok('--ed-accent-2', '#61a5ff'),
      warn: tok('--ed-warn', '#e9b949'), stale: tok('--ed-stale', '#d9822b'),
      ink3: tok('--ed-ink-3', '#a7b6c9'), research: tok('--ed-research', '#b18cff')
    };
  }
  function storageGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function storageSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* per-viewer only */ } }

  var TF_SECONDS = { '1': 60, '3': 180, '5': 300, '15': 900, '30': 1800, '60': 3600, 'D': 86400 };

  // ---- series primitives (drawn inside the pane, under/over the candles) ----
  // A horizontal band between two prices across the whole pane (value area).
  function BandPrimitive() {
    var self = this;
    this._series = null; this._lo = null; this._hi = null; this._fill = 'rgba(61,139,253,.08)'; this._req = null;
    var renderer = { draw: function (target) {
      if (self._series == null || self._lo == null || self._hi == null) return;
      var y1 = self._series.priceToCoordinate(self._hi), y2 = self._series.priceToCoordinate(self._lo);
      if (y1 == null || y2 == null) return;
      target.useBitmapCoordinateSpace(function (s) {
        var top = Math.min(y1, y2) * s.verticalPixelRatio, h = Math.abs(y2 - y1) * s.verticalPixelRatio;
        s.context.fillStyle = self._fill;
        s.context.fillRect(0, top, s.bitmapSize.width, h);
      });
    } };
    var view = { renderer: function () { return renderer; }, zOrder: function () { return 'bottom'; } };
    this.attached = function (p) { self._series = p.series; self._req = p.requestUpdate; };
    this.detached = function () { self._series = null; };
    this.updateAllViews = function () {};
    this.paneViews = function () { return [view]; };
    this.set = function (lo, hi, fill) { self._lo = lo; self._hi = hi; if (fill) self._fill = fill; if (self._req) self._req(); };
  }
  // User trend lines (and the one being placed). Points are {time, price}; x comes from the
  // chart's own time->logical mapping so a line survives a timeframe change.
  function DrawingPrimitive(ctx) {
    var self = this;
    this._series = null; this._req = null; this.lines = []; this.preview = null; this.color = '#61a5ff';
    function xy(p) {
      var lg = ctx.logicalOf(p.time);
      var x = lg == null ? null : ctx.chart.timeScale().logicalToCoordinate(lg);
      var y = self._series ? self._series.priceToCoordinate(p.price) : null;
      return (x == null || y == null) ? null : [x, y];
    }
    var renderer = { draw: function (target) {
      var all = self.lines.slice(); if (self.preview) all.push(self.preview);
      if (!all.length) return;
      target.useBitmapCoordinateSpace(function (s) {
        var c = s.context, hr = s.horizontalPixelRatio, vr = s.verticalPixelRatio;
        all.forEach(function (ln) {
          var a = xy(ln.a), b = xy(ln.b);
          if (!a || !b) return;
          c.strokeStyle = ln === self.preview ? alpha(self.color, 0.6) : self.color;
          c.lineWidth = Math.max(1, Math.round(1.5 * hr));
          c.beginPath(); c.moveTo(a[0] * hr, a[1] * vr); c.lineTo(b[0] * hr, b[1] * vr); c.stroke();
          [a, b].forEach(function (p) { c.fillStyle = self.color; c.beginPath(); c.arc(p[0] * hr, p[1] * vr, 2.5 * hr, 0, 2 * Math.PI); c.fill(); });
        });
      });
    } };
    var view = { renderer: function () { return renderer; }, zOrder: function () { return 'top'; } };
    this.attached = function (p) { self._series = p.series; self._req = p.requestUpdate; };
    this.detached = function () { self._series = null; };
    this.updateAllViews = function () {};
    this.paneViews = function () { return [view]; };
    this.redraw = function () { if (self._req) self._req(); };
  }

  function create(host, opts) {
    opts = opts || {};
    var P = palette();
    host.classList.add('tvc');
    host.innerHTML =
      '<div class="tvc-plot"></div>' +
      '<div class="tvc-legend"></div>' +
      '<div class="tvc-pin" hidden></div>' +
      '<div class="tvc-ctl">' +
        '<button type="button" class="tvc-btn tvc-latest" title="Scroll to the latest bar" hidden>&#187;</button>' +
        '<button type="button" class="tvc-btn tvc-auto on" title="Auto-fit price (A)">A</button>' +
        '<button type="button" class="tvc-btn tvc-log" title="Logarithmic price scale (L)">L</button>' +
      '</div>';
    var plot = host.querySelector('.tvc-plot'), legend = host.querySelector('.tvc-legend'),
      pinBox = host.querySelector('.tvc-pin'), btnLatest = host.querySelector('.tvc-latest'),
      btnAuto = host.querySelector('.tvc-auto'), btnLog = host.querySelector('.tvc-log');

    var chart = LWC.createChart(plot, {
      autoSize: true,
      layout: { background: { type: 'solid', color: P.bg }, textColor: P.text, fontSize: 11,
        fontFamily: tok('--ed-sans', 'system-ui'), attributionLogo: true },
      grid: { vertLines: { color: P.grid }, horzLines: { color: P.grid } },
      crosshair: { mode: LWC.CrosshairMode.Normal },
      rightPriceScale: { autoScale: true, borderColor: P.edge, scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 8, borderColor: P.edge,
        tickMarkFormatter: function (t, type) {
          var d = new Date(t * 1000);
          if (type === 0) return CT_YEAR.format(d);
          if (type === 1) return CT_MONTH.format(d);
          if (type === 2) return CT_DAY.format(d);
          return CT_TIME.format(d);
        } },
      localization: { timeFormatter: function (t) { return CT_FULL.format(new Date(t * 1000)) + ' CT'; } },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, axisDoubleClickReset: { time: true, price: true }, mouseWheel: true, pinch: true },
      kineticScroll: { mouse: false, touch: true }
    });
    var candles = chart.addSeries(LWC.CandlestickSeries, { upColor: P.up, downColor: P.down,
      wickUpColor: P.up, wickDownColor: P.down, borderVisible: false, priceLineVisible: true });
    var volume = chart.addSeries(LWC.HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' },
      lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    var vwapLine = chart.addSeries(LWC.LineSeries, { color: P.warn, lineWidth: 2, lastValueVisible: true,
      priceLineVisible: false, crosshairMarkerVisible: false, title: 'VWAP' });
    var bandLines = [1, 2, 3, 4].map(function () {
      return chart.addSeries(LWC.LineSeries, { color: alpha(P.warn, 0.45), lineWidth: 1, lineStyle: 2,
        lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    });
    var band = new BandPrimitive(); candles.attachPrimitive(band);
    var markers = LWC.createSeriesMarkers(candles, []);

    var S = { bars: [], tf: '5', symbol: '', levels: [], priceLines: [], nearestN: opts.nearestN || 6,
      pinned: null, tool: 'cursor', hlines: [], drawKey: null, markerMeta: {}, onMarkerClick: null };

    // ---- time <-> logical (bars are sorted, time = bar start in epoch seconds) ----
    function barIndexAt(t) {
      var b = S.bars, lo = 0, hi = b.length - 1, ans = -1;
      while (lo <= hi) { var mid = (lo + hi) >> 1; if (b[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
      return ans;
    }
    function logicalOf(t) {
      var b = S.bars; if (!b.length) return null;
      var i = barIndexAt(t), step = TF_SECONDS[S.tf] || 60;
      if (i < 0) return (t - b[0].t) / step;
      var next = i + 1 < b.length ? b[i + 1].t : b[i].t + step;
      return i + Math.min(1, (t - b[i].t) / Math.max(1, next - b[i].t));
    }
    var draw = new DrawingPrimitive({ chart: chart, logicalOf: logicalOf });
    draw.color = P.accent2;
    candles.attachPrimitive(draw);

    // ---- the one gap vs TradingView: vertical plot drag must pan price even in auto-fit ----
    (function installVerticalPan() {
      var start = null;
      plot.addEventListener('pointerdown', function (e) { start = { x: e.clientX, y: e.clientY }; }, true);
      document.addEventListener('pointermove', function (e) {
        if (!start || !(e.buttons & 1) || S.tool !== 'cursor') return;
        var dx = Math.abs(e.clientX - start.x), dy = Math.abs(e.clientY - start.y);
        if (dy > 4 && dy > dx && chart.priceScale('right').options().autoScale) setAuto(false);
      }, true);
      document.addEventListener('pointerup', function () { start = null; scheduleLevels(); syncButtons(); }, true);
    })();

    function setAuto(on) { chart.priceScale('right').applyOptions({ autoScale: !!on }); syncButtons(); scheduleLevels(); }
    function syncButtons() {
      btnAuto.classList.toggle('on', !!chart.priceScale('right').options().autoScale);
      btnLog.classList.toggle('on', chart.priceScale('right').options().mode === LWC.PriceScaleMode.Logarithmic);
      var pos = chart.timeScale().scrollPosition();
      btnLatest.hidden = !(S.bars.length && pos < -2);
    }
    btnAuto.addEventListener('click', function () { setAuto(!chart.priceScale('right').options().autoScale); });
    btnLog.addEventListener('click', function () {
      var log = chart.priceScale('right').options().mode === LWC.PriceScaleMode.Logarithmic;
      chart.priceScale('right').applyOptions({ mode: log ? LWC.PriceScaleMode.Normal : LWC.PriceScaleMode.Logarithmic });
      syncButtons(); scheduleLevels();
    });
    btnLatest.addEventListener('click', function () { chart.timeScale().scrollToRealTime(); });

    function showRecent() {
      var n = S.bars.length; if (!n) return;
      var span = S.tf === 'D' ? 60 : 140;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(-2, n - span), to: n + 8 });
    }
    function resetAll() {
      chart.priceScale('right').applyOptions({ autoScale: true, mode: LWC.PriceScaleMode.Normal });
      chart.timeScale().resetTimeScale(); showRecent(); syncButtons(); scheduleLevels();
    }

    // ---- legend + click-to-pin readout (no hover box, by the operator's standard) ----
    function barAt(t) { var i = barIndexAt(t); return i >= 0 && S.bars[i].t === t ? S.bars[i] : null; }
    function ohlcHtml(b) {
      if (!b) return '';
      var chg = b.c - b.o, cls = chg >= 0 ? 'up' : 'dn';
      return '<span>O <b class="' + cls + '">' + b.o.toFixed(2) + '</b></span><span>H <b class="' + cls + '">' + b.h.toFixed(2) +
        '</b></span><span>L <b class="' + cls + '">' + b.l.toFixed(2) + '</b></span><span>C <b class="' + cls + '">' + b.c.toFixed(2) +
        '</b></span><span>Vol <b>' + fmtVol(b.v) + '</b></span>' + (b.forming ? '<span class="tvc-forming">FORMING</span>' : '');
    }
    function paintLegend() {
      var b = S.pinned ? barAt(S.pinned.time) : S.bars[S.bars.length - 1];
      var tfLbl = S.tf === 'D' ? '1D' : (S.tf === '60' ? '1h' : S.tf + 'm');
      legend.innerHTML = '<span class="tvc-sym">' + esc(S.symbol) + '</span><span class="tvc-tf">' + tfLbl + '</span>' + ohlcHtml(b);
    }
    function paintPin() {
      if (!S.pinned) { pinBox.hidden = true; return; }
      var b = barAt(S.pinned.time);
      if (!b) { S.pinned = null; pinBox.hidden = true; return; }
      pinBox.hidden = false;
      var chg = b.c - b.o, pct = b.o ? (chg / b.o) * 100 : null;
      pinBox.innerHTML = '<div class="tvc-pin-h"><span>' + esc(CT_FULL.format(new Date(b.t * 1000))) + ' CT</span>' +
        '<button type="button" class="tvc-pin-x" title="Close (Esc)">&#215;</button></div>' +
        '<div class="tvc-pin-g"><span>Open</span><b>' + b.o.toFixed(2) + '</b><span>High</span><b>' + b.h.toFixed(2) +
        '</b><span>Low</span><b>' + b.l.toFixed(2) + '</b><span>Close</span><b>' + b.c.toFixed(2) +
        '</b><span>Bar change</span><b class="' + (chg >= 0 ? 'up' : 'dn') + '">' + (chg >= 0 ? '+' : '') + chg.toFixed(2) +
        (pct == null ? '' : ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%)') + '</b><span>Volume</span><b>' + fmtVol(b.v) + '</b>' +
        (S.pinned.price != null ? '<span>Price at click</span><b>' + S.pinned.price.toFixed(2) + '</b>' : '') + '</div>';
      pinBox.querySelector('.tvc-pin-x').addEventListener('click', function () { unpin(); });
    }
    function unpin() { S.pinned = null; paintPin(); paintLegend(); }

    // ---- drawing tools ----
    function saveDrawings() {
      if (!S.drawKey) return;
      storageSet(S.drawKey, JSON.stringify({ trend: draw.lines.map(function (l) { return { a: l.a, b: l.b }; }),
        hline: S.hlines.map(function (h) { return h.price; }) }));
    }
    function clearDrawingObjects() {
      S.hlines.forEach(function (h) { candles.removePriceLine(h.line); }); S.hlines = [];
      draw.lines = []; draw.preview = null; draw.redraw();
    }
    function addHline(price, save) {
      var line = candles.createPriceLine({ price: price, color: P.accent2, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: '' });
      S.hlines.push({ price: price, line: line, kind: 'hline' });
      if (save) { S.undo.push('hline'); saveDrawings(); }
    }
    function loadDrawings() {
      clearDrawingObjects(); S.undo = [];
      var raw = S.drawKey ? storageGet(S.drawKey) : null, d = null;
      try { d = raw ? JSON.parse(raw) : null; } catch (e) { d = null; }
      if (!d) return;
      (d.hline || []).forEach(function (p) { addHline(Number(p), false); });
      draw.lines = (d.trend || []).filter(function (l) { return l && l.a && l.b; });
      draw.redraw();
    }
    S.undo = [];
    function undo() {
      var k = S.undo.pop();
      if (k === 'hline' && S.hlines.length) { candles.removePriceLine(S.hlines.pop().line); }
      else if (k === 'trend' && draw.lines.length) { draw.lines.pop(); draw.redraw(); }
      saveDrawings();
    }
    function setTool(t) {
      S.tool = t; draw.preview = null; draw.redraw();
      host.classList.toggle('tvc-drawing', t !== 'cursor');
      chart.applyOptions({ handleScroll: { pressedMouseMove: t === 'cursor' } });
      if (opts.onTool) opts.onTool(t);
    }

    // Drawing tools read the pointer directly. The library reports no click for a second click
    // at a different spot inside its double-click window (measured: two quick trend-line clicks
    // left the line unfinished), which TradingView never drops.
    function timeAtX(x) {
      var lg = chart.timeScale().coordinateToLogical(x); if (lg == null || !S.bars.length) return null;
      var i = Math.max(0, Math.min(S.bars.length - 1, Math.floor(lg))), step = TF_SECONDS[S.tf] || 60;
      return S.bars[i].t + (lg - i) * step;
    }
    (function installDrawPointer() {
      var down = null;
      plot.addEventListener('pointerdown', function (e) { if (S.tool !== 'cursor') down = { x: e.clientX, y: e.clientY }; }, true);
      plot.addEventListener('pointerup', function (e) {
        if (S.tool === 'cursor' || !down) return;
        var moved = Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y); down = null;
        if (moved > 6) return;
        var r = plot.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
        if (x > chart.timeScale().width()) return;                 // on the price axis
        var price = candles.coordinateToPrice(y), time = timeAtX(x);
        if (price == null || time == null) return;
        S.drewAt = Date.now();                                     // this click is not a pin
        if (S.tool === 'hline') { addHline(price, true); setTool('cursor'); return; }
        var pt = { time: time, price: price };
        if (!draw.preview) { draw.preview = { a: pt, b: pt }; draw.redraw(); return; }
        draw.lines.push({ a: draw.preview.a, b: pt }); draw.preview = null; draw.redraw();
        S.undo.push('trend'); saveDrawings(); setTool('cursor');
      }, true);
    })();
    chart.subscribeClick(function (p) {
      if (!p.point || p.time == null || S.tool !== 'cursor' || Date.now() - (S.drewAt || 0) < 400) return;
      var price = candles.coordinateToPrice(p.point.y);
      if (p.hoveredObjectId != null && S.markerMeta[p.hoveredObjectId] && S.onMarkerClick) {
        S.onMarkerClick(S.markerMeta[p.hoveredObjectId]); return;
      }
      S.pinned = { time: p.time, price: price }; paintPin(); paintLegend();
    });
    chart.subscribeCrosshairMove(function (p) {
      if (S.tool === 'trend' && draw.preview && p.point) {
        var price = candles.coordinateToPrice(p.point.y), time = timeAtX(p.point.x);
        if (price != null && time != null) { draw.preview = { a: draw.preview.a, b: { time: time, price: price } }; draw.redraw(); }
      }
    });

    // ---- key levels: only the nearest few INSIDE the visible price range ----
    var _lvlRaf = 0, _lastRange = '';
    function scheduleLevels() { if (!_lvlRaf) _lvlRaf = requestAnimationFrame(function () { _lvlRaf = 0; paintLevels(false); }); }
    function paintLevels(force) {
      var h = plot.clientHeight, top = candles.coordinateToPrice(0), bot = candles.coordinateToPrice(Math.max(1, h - 30));
      var ref = S.bars.length ? S.bars[S.bars.length - 1].c : null;
      var key = [top, bot, ref, S.levels.length, S.nearestN].join('|');
      if (!force && key === _lastRange) return;
      _lastRange = key;
      S.priceLines.forEach(function (l) { candles.removePriceLine(l); }); S.priceLines = [];
      if (top == null || bot == null || ref == null) return;
      var lo = Math.min(top, bot), hi = Math.max(top, bot);
      var pick = S.levels.filter(function (l) { return l.price >= lo && l.price <= hi; })
        .sort(function (a, b) { return Math.abs(a.price - ref) - Math.abs(b.price - ref); })
        .slice(0, S.nearestN);
      pick.forEach(function (l) {
        S.priceLines.push(candles.createPriceLine({ price: l.price, color: l.color || P.ink3, lineWidth: l.width || 1,
          lineStyle: l.style == null ? 2 : l.style, axisLabelVisible: true, title: l.label || '' }));
      });
      if (opts.onLevelsShown) opts.onLevelsShown(pick);
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(function () { scheduleLevels(); syncButtons(); });
    plot.addEventListener('wheel', scheduleLevels, { passive: true });
    new ResizeObserver(scheduleLevels).observe(plot);

    // ---- keyboard (TradingView shortcuts), only while this chart is on screen ----
    document.addEventListener('keydown', function (e) {
      if (!host.offsetParent) return;
      var tag = (e.target && e.target.tagName) || '';
      if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
      if (e.altKey && (e.key === 'r' || e.key === 'R')) { e.preventDefault(); resetAll(); }
      else if (e.key === 'Escape') { if (S.tool !== 'cursor') setTool('cursor'); else unpin(); }
      else if (e.altKey && (e.key === 'h' || e.key === 'H')) { e.preventDefault(); setTool('hline'); }
      else if (e.altKey && (e.key === 't' || e.key === 'T')) { e.preventDefault(); setTool('trend'); }
      else if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); }
    });

    function applyTheme() {
      P = palette();
      chart.applyOptions({ layout: { background: { type: 'solid', color: P.bg }, textColor: P.text },
        grid: { vertLines: { color: P.grid }, horzLines: { color: P.grid } },
        rightPriceScale: { borderColor: P.edge }, timeScale: { borderColor: P.edge } });
      candles.applyOptions({ upColor: P.up, downColor: P.down, wickUpColor: P.up, wickDownColor: P.down });
      vwapLine.applyOptions({ color: P.warn });
      bandLines.forEach(function (s) { s.applyOptions({ color: alpha(P.warn, 0.45) }); });
      draw.color = P.accent2; draw.redraw();
      api.setVolume(S.bars);
      paintLevels(true);
    }
    document.addEventListener('ed:theme', applyTheme);

    var api = {
      chart: chart, candles: candles, palette: function () { return P; },
      TF_SECONDS: TF_SECONDS,
      // Replace the whole series (ticker or timeframe change).
      setBars: function (bars, tf, symbol) {
        var changed = tf !== S.tf || symbol !== S.symbol;
        S.bars = (bars || []).map(function (b) { return { t: Number(b.t), o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, forming: !!b.forming }; });
        S.tf = tf; S.symbol = symbol;
        candles.setData(S.bars.map(function (b) { return { time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }; }));
        api.setVolume(S.bars);
        if (changed) {
          S.pinned = null; paintPin();
          var dk = 'ed.tvc.draw.' + symbol;
          if (dk !== S.drawKey) { S.drawKey = dk; loadDrawings(); }
          chart.priceScale('right').applyOptions({ autoScale: true });
          showRecent();
        }
        paintLegend(); paintPin(); draw.redraw(); syncButtons(); paintLevels(true);
      },
      // The newest bars only (the forming bar and the one it replaced) -- series.update keeps
      // the operator's zoom/scroll exactly where it is.
      updateTail: function (tail) {
        if (!S.bars.length || !tail || !tail.length) return;
        var lastT = S.bars[S.bars.length - 1].t;
        tail.forEach(function (b0) {
          var b = { t: Number(b0.t), o: b0.o, h: b0.h, l: b0.l, c: b0.c, v: b0.v, forming: !!b0.forming };
          if (b.t < lastT) {
            var i = barIndexAt(b.t); if (i < 0 || S.bars[i].t !== b.t) return;
            // only the most recent completed bar may still be revised (forming -> closed)
            if (i < S.bars.length - 2) return;
            S.bars[i] = b;
          } else if (b.t === lastT) S.bars[S.bars.length - 1] = b;
          else { S.bars.push(b); lastT = b.t; }
          candles.update({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }, b.t < S.bars[S.bars.length - 1].t);
          volume.update(api._volPoint(b), b.t < S.bars[S.bars.length - 1].t);
        });
        paintLegend(); if (S.pinned) paintPin(); syncButtons(); scheduleLevels();
      },
      _volPoint: function (b) {
        return b.v == null ? { time: b.t } : { time: b.t, value: b.v, color: alpha(b.c >= b.o ? P.up : P.down, 0.45) };
      },
      setVolume: function (bars) { volume.setData((bars || []).map(api._volPoint)); },
      // VWAP + bands, one point per bar: the server's value as of that bar's close (the last
      // 1m series point inside the bar). Rows are [t, vwap, +1, -1, +2, -2].
      setVwap: function (rows) {
        rows = (rows || []).filter(function (r) { return r && r[1] != null; });
        var byBar = {}, order = [];
        rows.forEach(function (r) {
          var i = barIndexAt(Number(r[0])); if (i < 0) return;
          var t = S.bars[i].t; if (!(t in byBar)) order.push(t);
          byBar[t] = r;
        });
        var cols = [1, 2, 3, 4, 5], out = cols.map(function () { return []; });
        order.forEach(function (t) { cols.forEach(function (c, k) { if (byBar[t][c] != null) out[k].push({ time: t, value: byBar[t][c] }); }); });
        vwapLine.setData(out[0]);
        bandLines.forEach(function (s, k) { s.setData(out[k + 1]); });
      },
      setValueArea: function (val, vah) { band.set(val, vah, alpha(P.accent, 0.09)); },
      // levels: [{id, price, label, color, style, width}]
      setLevels: function (levels) { S.levels = (levels || []).filter(function (l) { return l && isFinite(l.price); }); paintLevels(true); },
      setNearestN: function (n) { S.nearestN = n; paintLevels(true); },
      // markers: [{id, time, text, color, position, shape, meta}]
      setMarkers: function (list, onClick) {
        S.markerMeta = {}; S.onMarkerClick = onClick || null;
        var m = [];
        (list || []).forEach(function (x) {
          var i = barIndexAt(Number(x.time)); if (i < 0) return;
          S.markerMeta[x.id] = x.meta;
          m.push({ id: x.id, time: S.bars[i].t, position: x.position || 'aboveBar', color: x.color || P.accent2,
            shape: x.shape || 'circle', text: x.text || '', size: 1 });
        });
        m.sort(function (a, b) { return a.time - b.time; });
        markers.setMarkers(m);
      },
      scrollToTime: function (t) {
        var lg = logicalOf(Number(t)); if (lg == null) return;
        var r = chart.timeScale().getVisibleLogicalRange(); var w = r ? (r.to - r.from) : 120;
        var to = Math.min(lg + w / 2, S.bars.length + 8);   // never scroll past the latest bar
        chart.timeScale().setVisibleLogicalRange({ from: to - w, to: to });
      },
      setTool: setTool, undo: undo,
      clearDrawings: function () { clearDrawingObjects(); S.undo = []; saveDrawings(); },
      resetAll: resetAll,
      screenshot: function () {
        var c = chart.takeScreenshot(), a = document.createElement('a');
        a.href = c.toDataURL('image/png');
        a.download = (S.symbol || 'chart') + '_' + (S.tf === 'D' ? '1D' : S.tf + 'm') + '.png';
        a.click();
      },
      fullscreen: function () {
        var el = opts.fullscreenEl || host;
        if (document.fullscreenElement) document.exitFullscreen(); else if (el.requestFullscreen) el.requestFullscreen();
      },
      state: function () {
        var r = chart.timeScale().getVisibleLogicalRange();
        return { bars: S.bars.length, tf: S.tf, symbol: S.symbol, from: r && r.from, to: r && r.to,
          autoScale: chart.priceScale('right').options().autoScale, levelsShown: S.priceLines.length,
          pinned: S.pinned, tool: S.tool, drawings: draw.lines.length + S.hlines.length };
      }
    };
    return api;
  }

  window.EdTvChart = { create: create, TF_SECONDS: TF_SECONDS };
})();
