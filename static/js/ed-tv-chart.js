/* Ed Console — the ONE TradingView-style chart (window.EdTvChart). PRESENTATION ONLY.

   Engine: TradingView Lightweight Charts 5.2.1 (Apache-2.0), vendored unmodified at
   /static/vendor/lightweight-charts/ (npm tarball sha512 verified 2026-09-25). Its license asks
   for a link to tradingview.com; `attributionLogo: true` renders that link on every chart.

   The operator's chart standard (feedback_chart_interactions_mirror_tradingview), measured
   against the library on real SPY bars before use:
     - plot drag pans BOTH ways. The library pans price vertically only once the price scale is
       out of auto-fit; TradingView turns auto-fit off the moment you drag vertically. The two
       gaps are closed below (installVerticalPan, installPriceAxisWheel) -- everything else is
       the library's own.
     - price-axis drag or wheel rescales price, time-axis drag rescales time, double-click an
       axis resets it, Alt+R resets everything, the wheel over the plot zooms time.
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
  var LEVEL_TITLE_W = 150;   // px along the pane's right edge where the level lines' titles are drawn
  var LEVEL_LABEL_GAP = 18;  // px: a level label's height; closer labels would overlap
  var PROFILE_FRAC = 0.16;   // the volume profile's share of the pane's width, from the left edge
  // event callouts sit in a strip above the candles: rows of numbers (and their labels) from
  // CALLOUT_TOP, CALLOUT_ROW apart, CALLOUT_ROWS rows; the price scale keeps the strip clear
  var CALLOUT_TOP = 50, CALLOUT_ROW = 28, CALLOUT_ROWS = 2, CALLOUT_R = 11;

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
  // Values at prices on the price axis, drawn from the pane's right edge (a GEX profile: signed
  // bars, or dots sized by magnitude) or its left edge (the volume profile). rows: [{price,
  // value, color}] and `scale`, the served largest |value| (the full band); with `fit` the rows'
  // prices join the auto-fit so every row is on screen. Scaling to the pane is drawing; the values
  // and the scale are served.
  function ProfilePrimitive(side, frac, fit, z) {
    var self = this;
    this._series = null; this._req = null; this.rows = []; this.scale = null; this.style = 'bars'; this.frac = frac; this.sel = null; this.mark = null;
    var renderer = { draw: function (target) {
      if (!self._series || !self.rows.length || !self.scale) return;
      var mx = self.scale;
      target.useBitmapCoordinateSpace(function (s) {
        var c = s.context, hr = s.horizontalPixelRatio, vr = s.verticalPixelRatio, W = s.bitmapSize.width, band = W * self.frac;
        var ys = self.rows.map(function (r) { return self._series.priceToCoordinate(r.price); });
        var gap = Infinity;
        ys.filter(function (y) { return y != null; }).sort(function (a, b) { return a - b; })
          .forEach(function (y, i, a) { if (i && a[i] - a[i - 1] > 0) gap = Math.min(gap, a[i] - a[i - 1]); });
        var th = Math.max(1, Math.min(8, isFinite(gap) ? gap * 0.7 : 8)) * vr;
        self.rows.forEach(function (r, i) {
          if (ys[i] == null) return;
          var y = ys[i] * vr, f = Math.abs(r.value) / mx;
          c.fillStyle = r.color; c.globalAlpha = 0.85;
          if (self.style === 'dots') {
            var rad = (3 + Math.sqrt(f) * 16) * hr;
            c.beginPath(); c.arc(W - band / 2, y, rad, 0, 2 * Math.PI); c.globalAlpha = 0.55; c.fill();
          } else {
            c.fillRect(side === 'left' ? 0 : W - f * band, y - th / 2, f * band, th);
          }
          if (self.sel != null && r.price === self.sel) {
            c.globalAlpha = 1; c.strokeStyle = r.color; c.lineWidth = Math.max(1, hr);
            c.strokeRect(W - band, y - th / 2 - 2 * vr, band, th + 4 * vr);
          }
          c.globalAlpha = 1;
        });
        // one marked price across the band, named (the volume profile's served POC)
        var mk = self.mark, my = mk && self._series.priceToCoordinate(mk.price);
        if (my != null) {
          var x0 = side === 'left' ? 0 : W - band;
          c.fillStyle = mk.color; c.fillRect(x0, my * vr - hr, band, 2 * vr);
          c.font = '600 ' + Math.round(11 * vr) + 'px ' + tok('--ed-sans', 'sans-serif'); c.textBaseline = 'bottom';
          c.textAlign = side === 'left' ? 'left' : 'right';
          c.fillText(mk.label, side === 'left' ? x0 + 4 * hr : W - 4 * hr, my * vr - 3 * vr);
        }
      });
    } };
    var view = { renderer: function () { return renderer; }, zOrder: function () { return z || 'normal'; } };
    this.attached = function (p) { self._series = p.series; self._req = p.requestUpdate; };
    this.detached = function () { self._series = null; };
    this.updateAllViews = function () {};
    this.paneViews = function () { return [view]; };
    this.autoscaleInfo = function () {
      if (!fit || !self.rows.length) return null;
      var ps = self.rows.map(function (r) { return r.price; });
      return { priceRange: { minValue: Math.min.apply(null, ps), maxValue: Math.max.apply(null, ps) } };
    };
    this.set = function (rows, scale, style, mark) {
      self.rows = rows || []; self.scale = scale; if (style) self.style = style; self.mark = mark || null; if (self._req) self._req();
    };
    this.select = function (price) { self.sel = price; if (self._req) self._req(); };
    // the row nearest a pane point, when the point is inside the profile band
    this.rowAt = function (x, y, paneWidth) {
      if (!self._series || !self.rows.length || x < paneWidth * (1 - self.frac)) return null;
      var best = null, bd = Infinity;
      self.rows.forEach(function (r) { var ry = self._series.priceToCoordinate(r.price); if (ry == null) return;
        var d = Math.abs(ry - y); if (d < bd) { bd = d; best = r; } });
      return bd <= 12 ? best : null;
    };
  }
  // Served price zones across the pane: [{lo, hi, color, label}], each a shaded band with its
  // edges and label, where it falls in the price range the candles set (a zone far from price does
  // not widen the scale: SPY's zones at 750 and 800 flattened its candles, 2026-09-29).
  function ZonesPrimitive() {
    var self = this;
    this._series = null; this._req = null; this.zones = [];
    var renderer = { draw: function (target) {
      if (!self._series || !self.zones.length) return;
      target.useBitmapCoordinateSpace(function (s) {
        var c = s.context, vr = s.verticalPixelRatio, hr = s.horizontalPixelRatio, W = s.bitmapSize.width;
        self.zones.forEach(function (z) {
          var y1 = self._series.priceToCoordinate(z.hi), y2 = self._series.priceToCoordinate(z.lo);
          if (y1 == null || y2 == null) return;
          var top = Math.min(y1, y2) * vr, h = Math.max(1, Math.abs(y2 - y1) * vr);
          c.fillStyle = alpha(z.color, 0.13); c.fillRect(0, top, W, h);
          c.fillStyle = alpha(z.color, 0.6); c.fillRect(0, top, W, Math.max(1, vr)); c.fillRect(0, top + h - Math.max(1, vr), W, Math.max(1, vr));
          // the label sits inside its band, below the legend line (28px) when the band's top is above it
          if (z.label) { c.fillStyle = z.color; c.font = Math.round(11 * vr) + 'px ' + tok('--ed-sans', 'sans-serif');
            c.fillText(z.label, 6 * hr, Math.min(Math.max(top, 28 * vr) + 12 * vr, top + h - 3 * vr)); }
        });
      });
    } };
    var view = { renderer: function () { return renderer; }, zOrder: function () { return 'bottom'; } };
    this.attached = function (p) { self._series = p.series; self._req = p.requestUpdate; };
    this.detached = function () { self._series = null; };
    this.updateAllViews = function () {};
    this.paneViews = function () { return [view]; };
    this.set = function (zones) { self.zones = (zones || []).filter(function (z) { return isFinite(z.lo) && isFinite(z.hi); }); if (self._req) self._req(); };
  }
  // Numbered event callouts, as the reference draws them: in the strip above the candles each
  // event's number in a circle with its boxed label beside it (turned left before the level titles
  // along the pane's right edge, LEVEL_TITLE_W wide), at its bar in the first of CALLOUT_ROWS rows
  // where it overlaps no other callout, else beside the callouts in a row; a dashed line to its bar
  // and down it, and a dot at its price. list: [{id, time,
  // price, num, text, color}]; sel: the selected id, drawn heavier. hitAt(x, y) -> id; centers:
  // each number's {id, x, y} in pane px.
  function CalloutPrimitive(chartRef, P) {
    var self = this;
    this._series = null; this._req = null; this.list = []; this.sel = null; this.hits = []; this.centers = [];
    var renderer = { draw: function (target) {
      self.hits = []; self.centers = [];
      if (!self._series || !self.list.length) return;
      var ts = chartRef().timeScale();
      target.useMediaCoordinateSpace(function (s) {
        var c = s.context, W = s.mediaSize.width, H = s.mediaSize.height, rows = [], R = CALLOUT_R;
        for (var k = 0; k < CALLOUT_ROWS; k++) rows.push([]);
        c.font = '600 12px ' + tok('--ed-sans', 'sans-serif');
        self.list.forEach(function (m) {
          var x = ts.timeToCoordinate(m.time), y = self._series.priceToCoordinate(m.price);
          if (x == null || y == null) return;
          var w = m.text ? c.measureText(m.text).width + 14 : 0;
          // the callout's extent with its number at cx: label to the right, or left near the edge
          var ext = function (cx) {
            var left = w && cx + R + 6 + w > W - LEVEL_TITLE_W;
            return { cx: cx, left: left, x0: left ? cx - R - 6 - w : cx - R, x1: left ? cx + R : cx + R + (w ? 6 + w : 0) };
          };
          var clashes = function (row, e) { return row.filter(function (b) { return e.x0 < b[1] + 6 && e.x1 > b[0] - 6; }); };
          // at its own bar in the first free row; else beside the callouts already in a row
          var pick = null, row = 0;
          rows.forEach(function (rw, i) { if (!pick && !clashes(rw, ext(x)).length) { pick = ext(x); row = i; } });
          rows.forEach(function (rw, i) {
            if (pick) return;
            var cl = clashes(rw, ext(x));
            var right = ext(Math.max.apply(null, cl.map(function (b) { return b[1]; })) + 6 + R);
            var leftOf = ext(Math.min.apply(null, cl.map(function (b) { return b[0]; })) - 6 - R - (w ? 6 + w : 0));
            [right, leftOf].forEach(function (e) {
              if (!pick && e.x0 >= 0 && e.x1 <= W && !clashes(rw, e).length) { pick = e; row = i; }
            });
          });
          pick = pick || ext(x);
          rows[row].push([pick.x0, pick.x1]);
          var on = m.id === self.sel, cy = CALLOUT_TOP + row * CALLOUT_ROW, cx = pick.cx;
          var stripBottom = CALLOUT_TOP + (CALLOUT_ROWS - 1) * CALLOUT_ROW + R + 4;
          c.save();
          c.strokeStyle = alpha(m.color, on ? 0.95 : 0.6); c.lineWidth = on ? 2 : 1; c.setLineDash([4, 4]);
          c.beginPath(); c.moveTo(cx, cy + R); c.lineTo(cx, stripBottom); c.lineTo(x, stripBottom + 8); c.lineTo(x, H); c.stroke();
          c.setLineDash([]);
          c.fillStyle = m.color; c.beginPath(); c.arc(x, y, on ? 5 : 4, 0, 2 * Math.PI); c.fill();
          c.fillStyle = P.bg; c.lineWidth = on ? 3 : 2; c.strokeStyle = m.color;
          c.beginPath(); c.arc(cx, cy, R, 0, 2 * Math.PI); c.fill(); c.stroke();
          c.fillStyle = P.ink; c.textAlign = 'center'; c.textBaseline = 'middle';
          c.fillText(String(m.num), cx, cy + 0.5);
          if (w) {
            var bx = pick.left ? cx - R - 6 - w : cx + R + 6, by = cy - 11;
            c.fillStyle = alpha(P.bg, 0.94); c.strokeStyle = alpha(m.color, on ? 1 : 0.8); c.lineWidth = on ? 2 : 1;
            c.fillRect(bx, by, w, 22); c.strokeRect(bx, by, w, 22);
            c.fillStyle = P.ink; c.textAlign = 'left'; c.fillText(m.text, bx + 7, cy + 0.5);
            self.hits.push({ id: m.id, x0: bx, x1: bx + w, y0: by, y1: by + 22 });
          }
          self.hits.push({ id: m.id, x0: cx - R, x1: cx + R, y0: cy - R, y1: cy + R });
          self.centers.push({ id: m.id, x: cx, y: cy });
          c.restore();
        });
      });
    } };
    var view = { renderer: function () { return renderer; }, zOrder: function () { return 'top'; } };
    this.attached = function (p) { self._series = p.series; self._req = p.requestUpdate; };
    this.detached = function () { self._series = null; };
    this.updateAllViews = function () {};
    this.paneViews = function () { return [view]; };
    this.set = function (list, sel) { self.list = list; self.sel = sel; if (self._req) self._req(); };
    this.hitAt = function (x, y) {
      var h = self.hits.filter(function (b) { return x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1; })[0];
      return h ? h.id : null;
    };
  }
  // A time x price grid of served cells (the book heatmap): each cell {t: bucket index, price,
  // bid, ask, side} is drawn at its own bucket and price, coloured by its served side, brightness
  // its size against the served max_size. Nothing is summed, re-binned or interpolated.
  function HeatPrimitive(chartRef) {
    var self = this;
    this._series = null; this._req = null; this.h = null; this.step = 0.01; this.up = '#22c55e'; this.down = '#ef4444';
    var renderer = { draw: function (target) {
      var h = self.h; if (!self._series || !h || !h.cells.length) return;
      var ts = chartRef().timeScale();
      target.useBitmapCoordinateSpace(function (s) {
        var c = s.context, hr = s.horizontalPixelRatio, vr = s.verticalPixelRatio;
        var bw = Math.max(1, ts.options().barSpacing);
        h.cells.forEach(function (cell) {
          var x = ts.timeToCoordinate(h.since_ts + cell.t * h.bucket_sec);
          var y1 = self._series.priceToCoordinate(cell.price + self.step / 2), y2 = self._series.priceToCoordinate(cell.price - self.step / 2);
          if (x == null || y1 == null || y2 == null) return;
          // the served side: BID green, ASK red, EVEN (equal sizes) neutral
          var dom = cell.side === 'ASK' ? cell.ask : cell.bid;
          if (dom == null) return;   // a size of 0 is drawn as sent
          c.fillStyle = cell.side === 'BID' ? self.up : cell.side === 'ASK' ? self.down : self.even;
          c.globalAlpha = 0.15 + 0.85 * Math.min(1, dom / (h.max_size || 1));
          c.fillRect((x - bw / 2) * hr, Math.min(y1, y2) * vr, bw * hr, Math.max(1, Math.abs(y2 - y1)) * vr);
        });
        c.globalAlpha = 1;
      });
    } };
    var view = { renderer: function () { return renderer; }, zOrder: function () { return 'bottom'; } };
    this.attached = function (p) { self._series = p.series; self._req = p.requestUpdate; };
    this.detached = function () { self._series = null; };
    this.updateAllViews = function () {};
    this.paneViews = function () { return [view]; };
    this.autoscaleInfo = function () {
      var h = self.h; if (!h || h.display_lo == null) return null;
      return { priceRange: { minValue: h.display_lo, maxValue: h.display_hi } };   // the served default window
    };
    this.set = function (h, up, down, even) {
      self.h = h; self.up = up; self.down = down; self.even = even;
      // a cell's height: the smallest gap between two served prices (drawing only)
      var ps = h ? h.cells.map(function (c) { return c.price; }).sort(function (a, b) { return a - b; }) : [];
      var gap = Infinity; for (var i = 1; i < ps.length; i++) if (ps[i] > ps[i - 1]) gap = Math.min(gap, ps[i] - ps[i - 1]);
      self.step = isFinite(gap) ? gap : 0.01;
      if (self._req) self._req();
    };
    // the served cell drawn under a time and price (hit-testing the drawing)
    this.cellAt = function (time, price) {
      var h = self.h; if (!h) return null;
      var t = Math.round((time - h.since_ts) / h.bucket_sec);
      return h.cells.filter(function (c) { return c.t === t && Math.abs(c.price - price) <= self.step / 2; })[0] || null;
    };
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
      '<div class="tvc-edge tvc-edge-top"></div><div class="tvc-edge tvc-edge-bot"></div>' +
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
      wickUpColor: P.up, wickDownColor: P.down, borderVisible: false, priceLineVisible: false, lastValueVisible: false });
    // the live Schwab LAST_PRICE (the header's value), drawn as its own line; the candles are
    // Schwab's completed bars only
    var liveLine = null;
    // line mode: the closes as one line; the candles stay (transparent) so price lines keep their series
    var closeLine = chart.addSeries(LWC.LineSeries, { color: P.accent, lineWidth: 2, visible: false,
      lastValueVisible: false, priceLineVisible: false });
    var volume = chart.addSeries(LWC.HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' },
      lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    var vwapLine = chart.addSeries(LWC.LineSeries, { color: P.accent, lineWidth: 2, lastValueVisible: true,
      priceLineVisible: false, crosshairMarkerVisible: false, title: 'VWAP' });
    var bandLines = [1, 2, 3, 4].map(function () {
      return chart.addSeries(LWC.LineSeries, { color: alpha(P.accent, 0.4), lineWidth: 1, lineStyle: 2,
        lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    });
    var band = new BandPrimitive(); candles.attachPrimitive(band);
    var callouts = new CalloutPrimitive(function () { return chart; }, P); candles.attachPrimitive(callouts);
    var profile = new ProfilePrimitive('right', 0.32, true); candles.attachPrimitive(profile);
    // the session volume profile on the left edge, as the reference draws it (the candles set
    // the price range; the profile does not widen it)
    var vprofile = new ProfilePrimitive('left', PROFILE_FRAC, false, 'bottom'); candles.attachPrimitive(vprofile);   // behind the candles
    var zones = new ZonesPrimitive(); candles.attachPrimitive(zones);
    // the heatmap's buckets on the time axis (no values: whitespace points), carrying its cells
    var timeline = chart.addSeries(LWC.LineSeries, { color: 'rgba(0,0,0,0)', lastValueVisible: false, priceLineVisible: false,
      crosshairMarkerVisible: false, lineVisible: false, pointMarkersVisible: false });
    var heat = new HeatPrimitive(function () { return chart; }); timeline.attachPrimitive(heat);

    var S = { bars: [], tf: '5', symbol: '', levels: [], priceLines: [], unlabelled: [], nearestN: opts.nearestN || 6,
      pinned: null, tool: 'cursor', style: 'candles', hlines: [], drawKey: null, markerMeta: {}, onMarkerClick: null };

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

    // ---- the wheel over the price axis rescales price about the middle of the visible range, as
    // TradingView does (the library's wheel zooms time only); auto-fit turns off ----
    (function installPriceAxisWheel() {
      plot.addEventListener('wheel', function (e) {
        if (e.clientX - plot.getBoundingClientRect().left <= chart.timeScale().width()) return;   // the plot: time
        e.preventDefault(); e.stopPropagation();
        var ps = chart.priceScale('right'), r = ps.getVisibleRange(); if (!r) return;
        var log = ps.options().mode === LWC.PriceScaleMode.Logarithmic && r.from > 0;
        var lo = log ? Math.log(r.from) : r.from, hi = log ? Math.log(r.to) : r.to;
        var mid = (lo + hi) / 2, half = (hi - lo) / 2 * Math.exp(e.deltaY * 0.002);   // down: wider range
        setAuto(false);
        ps.setVisibleRange(log ? { from: Math.exp(mid - half), to: Math.exp(mid + half) } : { from: mid - half, to: mid + half });
        scheduleLevels();
      }, { passive: false, capture: true });
    })();

    // ---- vertical plot drag must pan price even in auto-fit ----
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

    // the default view: from the first bar at or after S.viewFrom (a served time, e.g. the
    // session's open) to the latest; with no bar there yet, the newest 140 (60 daily)
    function showRecent() {
      var n = S.bars.length; if (!n) return;
      var from = n - (S.tf === 'D' ? 60 : 140);
      if (S.viewFrom != null) {
        var i = barIndexAt(S.viewFrom); if (i < 0 || S.bars[i].t < S.viewFrom) i += 1;
        if (i < n) from = i;
      }
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(-2, from - 1), to: n + 8 });
    }
    function resetAll() {
      chart.priceScale('right').applyOptions({ autoScale: true, mode: LWC.PriceScaleMode.Normal });
      chart.timeScale().resetTimeScale(); showRecent(); syncButtons(); scheduleLevels();
    }

    // ---- legend + click-to-pin readout (no hover box, by the operator's standard) ----
    function barAt(t) { var i = barIndexAt(t); return i >= 0 && S.bars[i].t === t ? S.bars[i] : null; }
    function ohlcHtml(b) {
      if (!b) return '';
      var cls = b.chg == null ? '' : b.chg >= 0 ? 'up' : 'dn';   // the served bar change
      return '<span>O <b class="' + cls + '">' + b.o.toFixed(2) + '</b></span><span>H <b class="' + cls + '">' + b.h.toFixed(2) +
        '</b></span><span>L <b class="' + cls + '">' + b.l.toFixed(2) + '</b></span><span>C <b class="' + cls + '">' + b.c.toFixed(2) +
        '</b></span><span>Vol <b>' + fmtVol(b.v) + '</b></span>';
    }
    function paintLegend() {
      var b = S.pinned ? barAt(S.pinned.time) : S.bars[S.bars.length - 1];
      var tfLbl = S.tf === 'D' ? '1D' : (S.tf === '60' ? '1h' : S.tf + 'm');
      legend.innerHTML = '<span class="tvc-sym">' + esc(S.symbol) + '</span><span class="tvc-tf">' + tfLbl + '</span>' + ohlcHtml(b) +
        (S.lastBarLabel ? '<span>Last completed bar ' + esc(S.lastBarLabel) + '</span>' : '') +
        (S.backfillLine ? '<span class="tvc-backfill">' + esc(S.backfillLine) + '</span>' : '');   // served, printed as is
    }
    function paintPin() {
      if (!S.pinned) { pinBox.hidden = true; return; }
      var b = barAt(S.pinned.time);
      var cell = !b && heat.h ? heat.cellAt(S.pinned.time, S.pinned.price) : null;
      if (!b && heat.h) {   // the heatmap's readout: the served cell under the pin, its own bid and ask
        pinBox.hidden = false;
        pinBox.innerHTML = '<div class="tvc-pin-h"><span>' + esc(CT_FULL.format(new Date(S.pinned.time * 1000))) + ' CT</span>' +
          '<button type="button" class="tvc-pin-x" title="Close (Esc)">&#215;</button></div>' +
          '<div class="tvc-pin-g"><span>Price</span><b>' + S.pinned.price.toFixed(2) + '</b><span>Bid size</span><b>' +
          (cell && cell.bid != null ? fmtVol(cell.bid) : '—') + '</b><span>Ask size</span><b>' + (cell && cell.ask != null ? fmtVol(cell.ask) : '—') + '</b></div>';
        pinBox.querySelector('.tvc-pin-x').addEventListener('click', function () { unpin(); });
        return;
      }
      if (!b) { S.pinned = null; pinBox.hidden = true; return; }
      pinBox.hidden = false;
      var chg = b.chg, pct = b.chg_pct;   // served per bar
      pinBox.innerHTML = '<div class="tvc-pin-h"><span>' + esc(CT_FULL.format(new Date(b.t * 1000))) + ' CT</span>' +
        '<button type="button" class="tvc-pin-x" title="Close (Esc)">&#215;</button></div>' +
        '<div class="tvc-pin-g"><span>Open</span><b>' + b.o.toFixed(2) + '</b><span>High</span><b>' + b.h.toFixed(2) +
        '</b><span>Low</span><b>' + b.l.toFixed(2) + '</b><span>Close</span><b>' + b.c.toFixed(2) +
        '</b><span>Bar change</span><b class="' + (chg == null ? '' : chg >= 0 ? 'up' : 'dn') + '">' + (chg == null ? '—' : (chg >= 0 ? '+' : '') + chg.toFixed(2)) +
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
      toolListeners.forEach(function (fn) { fn(t); });
    }
    var toolListeners = [];   // the toolbar's tool buttons follow the tool, keyboard included

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
      if (!p.point || S.tool !== 'cursor' || Date.now() - (S.drewAt || 0) < 400) return;
      // a click on a profile row selects it (the row's own gesture, e.g. a strike for every panel)
      var row = opts.onProfileClick ? profile.rowAt(p.point.x, p.point.y, chart.timeScale().width()) : null;
      if (row) { opts.onProfileClick(row); return; }
      var hit = callouts.hitAt(p.point.x, p.point.y);
      if (hit != null && S.onMarkerClick) { S.onMarkerClick(S.markerMeta[hit]); return; }
      if (p.time == null) return;
      var price = (heat.h ? timeline : candles).coordinateToPrice(p.point.y);   // the series carrying the price axis
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
      S.priceLines.concat(S.unlabelled).forEach(function (l) { candles.removePriceLine(l); }); S.priceLines = []; S.unlabelled = [];
      if (top == null || bot == null || ref == null) return;
      var lo = Math.min(top, bot), hi = Math.max(top, bot);
      // the levels arrive nearest-first (served); keep the first N inside the visible range
      var pick = S.levels.filter(function (l) { return l.price >= lo && l.price <= hi; }).slice(0, S.nearestN);
      // levels beyond the visible range, pinned at the edge (served order: nearest first)
      function edge(sel, list, arrow) {
        host.querySelector(sel).innerHTML = list.slice(0, 2).map(function (l) {
          return '<span style="color:' + (l.color || P.ink3) + '">' + arrow + ' ' + esc(l.label || '') + ' ' + l.price.toFixed(2) + '</span>'; }).join('');
      }
      edge('.tvc-edge-top', S.levels.filter(function (l) { return l.price > hi; }), '&#9650;');
      edge('.tvc-edge-bot', S.levels.filter(function (l) { return l.price < lo; }), '&#9660;');
      // one label per LEVEL_LABEL_GAP of height: a level whose label would overlap a nearer
      // level's keeps its line, and the nearer label counts it (+N; all are in the levels list)
      var labelled = [];
      pick.forEach(function (l) {
        var y = candles.priceToCoordinate(l.price);
        var near = y == null ? null : labelled.filter(function (x) { return Math.abs(x.y - y) < LEVEL_LABEL_GAP; })[0];
        if (near) {
          near.n += 1;
          near.line.applyOptions({ title: near.first + ' +' + (near.n - 1) });
          if (Math.abs(near.y - y) >= 0.5) S.unlabelled.push(candles.createPriceLine({ price: l.price, color: l.color || P.ink3,
            lineWidth: l.width || 1, lineStyle: l.style == null ? 2 : l.style, axisLabelVisible: false, title: '' }));
          return;
        }
        var line = candles.createPriceLine({ price: l.price, color: l.color || P.ink3, lineWidth: l.width || 1,
          lineStyle: l.style == null ? 2 : l.style, axisLabelVisible: true, title: l.label || '' });
        labelled.push({ line: line, first: l.label || '', n: 1, y: y });
        S.priceLines.push(line);
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
      paintStyle();
      vwapLine.applyOptions({ color: P.accent });
      bandLines.forEach(function (s) { s.applyOptions({ color: alpha(P.accent, 0.4) }); });
      draw.color = P.accent2; draw.redraw();
      api.setVolume(S.bars);
      paintLevels(true);
    }
    document.addEventListener('ed:theme', applyTheme);
    function paintStyle() {
      var line = S.style === 'line', none = 'rgba(0,0,0,0)';
      candles.applyOptions({ upColor: line ? none : P.up, downColor: line ? none : P.down,
        wickUpColor: line ? none : P.up, wickDownColor: line ? none : P.down });
      closeLine.applyOptions({ visible: line, color: P.accent });
    }

    var api = {
      chart: chart, candles: candles, palette: function () { return P; },
      // Replace the whole series (ticker or timeframe change).
      setBars: function (bars, tf, symbol, lastBarLabel, backfillLine) {
        var changed = tf !== S.tf || symbol !== S.symbol;
        S.lastBarLabel = lastBarLabel || null;
        S.backfillLine = backfillLine;
        S.bars = (bars || []).map(function (b) { return { t: Number(b.t), o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, chg: b.chg, chg_pct: b.chg_pct }; });
        S.tf = tf; S.symbol = symbol;
        candles.setData(S.bars.map(function (b) { return { time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }; }));
        closeLine.setData(S.bars.map(function (b) { return { time: b.t, value: b.c }; }));
        api.setVolume(S.bars);
        if (changed) {
          api.setLivePrice(null);
          S.pinned = null; paintPin();
          var dk = 'ed.tvc.draw.' + symbol;
          if (dk !== S.drawKey) { S.drawKey = dk; loadDrawings(); }
          chart.priceScale('right').applyOptions({ autoScale: true });
          showRecent();
        }
        paintLegend(); paintPin(); draw.redraw(); syncButtons(); paintLevels(true);
      },
      // The newest bars only -- series.update keeps the operator's zoom/scroll exactly where it is.
      updateTail: function (tail, lastBarLabel, backfillLine) {
        if (!S.bars.length || !tail || !tail.length) return;
        if (lastBarLabel) S.lastBarLabel = lastBarLabel;
        if (backfillLine) S.backfillLine = backfillLine;
        var lastT = S.bars[S.bars.length - 1].t;
        tail.forEach(function (b0) {
          var b = { t: Number(b0.t), o: b0.o, h: b0.h, l: b0.l, c: b0.c, v: b0.v, chg: b0.chg, chg_pct: b0.chg_pct };
          if (b.t < lastT) {
            var i = barIndexAt(b.t); if (i < 0 || S.bars[i].t !== b.t) return;
            if (i < S.bars.length - 2) return;
            S.bars[i] = b;
          } else if (b.t === lastT) S.bars[S.bars.length - 1] = b;
          else { S.bars.push(b); lastT = b.t; }
          candles.update({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }, b.t < S.bars[S.bars.length - 1].t);
          closeLine.update({ time: b.t, value: b.c }, b.t < S.bars[S.bars.length - 1].t);
          volume.update(api._volPoint(b), b.t < S.bars[S.bars.length - 1].t);
        });
        paintLegend(); if (S.pinned) paintPin(); syncButtons(); scheduleLevels();
      },
      _volPoint: function (b) {
        return b.v == null ? { time: b.t } : { time: b.t, value: b.v, color: alpha(b.chg >= 0 ? P.up : P.down, 0.7) };
      },
      setVolume: function (bars) { volume.setData((bars || []).map(api._volPoint)); },
      // VWAP + bands, one point per bar, served for the chart's timeframe (/api/levels?tf=:
      // the value as of the bar's last minute, stamped with the bar's t). Rows are
      // [t, vwap, +1, -1, +2, -2].
      setVwap: function (rows) {
        var cols = [1, 2, 3, 4, 5], out = cols.map(function () { return []; });
        (rows || []).forEach(function (r) { cols.forEach(function (c, k) { if (r && r[c] != null) out[k].push({ time: r[0], value: r[c] }); }); });
        vwapLine.setData(out[0]);
        bandLines.forEach(function (s, k) { s.setData(out[k + 1]); });
      },
      setStyle: function (style) { S.style = style === 'line' ? 'line' : 'candles'; paintStyle(); },
      setValueArea: function (val, vah) { band.set(val, vah, alpha(P.warn, 0.10)); },
      // levels: [{id, price, label, color, style, width}]
      setLevels: function (levels) { S.levels = (levels || []).filter(function (l) { return l && isFinite(l.price); }); paintLevels(true); },
      setNearestN: function (n) { S.nearestN = n; paintLevels(true); },
      // markers: [{id, time, price, num, text, color, meta}], drawn as numbered callouts at their
      // bar and price; one with no price or no bar is not drawn; the selected one (selectMarker)
      // is drawn heavier; a click on one calls onClick(meta)
      setMarkers: function (list, onClick) {
        S.markerList = list || []; S.onMarkerClick = onClick || null;
        api.selectMarker(S.markerSel);
      },
      selectMarker: function (id) {
        S.markerSel = id; S.markerMeta = {};
        var m = [];
        (S.markerList || []).forEach(function (x) {
          var i = barIndexAt(Number(x.time)); if (i < 0 || x.price == null) return;
          S.markerMeta[x.id] = x.meta;
          m.push({ id: x.id, time: S.bars[i].t, price: x.price, num: x.num, text: x.text || '', color: x.color || P.accent2 });
        });
        m.sort(function (a, b) { return a.time - b.time; });
        callouts.set(m, id);
        S.markersShown = m.map(function (x) { return x.id; });
        var strip = CALLOUT_TOP + (CALLOUT_ROWS - 1) * CALLOUT_ROW + CALLOUT_R + 10;   // px the callouts take
        chart.priceScale('right').applyOptions({ scaleMargins: { top: m.length ? Math.min(0.4, strip / Math.max(1, plot.clientHeight)) : 0.08, bottom: 0.22 } });
        scheduleLevels();
      },
      scrollToTime: function (t) {
        var lg = logicalOf(Number(t)); if (lg == null) return;
        var r = chart.timeScale().getVisibleLogicalRange(); var w = r ? (r.to - r.from) : 120;
        var to = Math.min(lg + w / 2, S.bars.length + 8);   // never scroll past the latest bar
        chart.timeScale().setVisibleLogicalRange({ from: to - w, to: to });
      },
      setTool: setTool, undo: undo, onTool: function (fn) { toolListeners.push(fn); fn(S.tool); },
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
      // The live price row's LAST_PRICE and its served age since the Schwab trade; null when the
      // price is not live (the line is removed, never left at an old price).
      setLivePrice: function (price, ageSec) {
        if (price == null) { if (liveLine) { candles.removePriceLine(liveLine); liveLine = null; } return; }
        var opts = { price: price, color: P.accent, lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
          title: 'LAST' + (ageSec != null ? ' · ' + Math.round(ageSec) + 's' : '') };
        if (liveLine) liveLine.applyOptions(opts); else liveLine = candles.createPriceLine(opts);
      },
      state: function () {
        var r = chart.timeScale().getVisibleLogicalRange();
        return { bars: S.bars.length, tf: S.tf, symbol: S.symbol, from: r && r.from, to: r && r.to,
          livePrice: liveLine ? liveLine.options().price : null, liveTitle: liveLine ? liveLine.options().title : null,
          autoScale: chart.priceScale('right').options().autoScale, levelsShown: S.priceLines.length,
          pinned: S.pinned, tool: S.tool, drawings: draw.lines.length + S.hlines.length,
          profile: { rows: profile.rows.length, style: profile.style, selected: profile.sel },
          heatCells: heat.h ? heat.h.cells.length : 0, zones: zones.zones.length, volumeProfileBins: vprofile.rows.length,
          levels: S.priceLines.map(function (l) { return l.options().title; }),
          markers: S.markersShown || [], markerSelected: S.markerSel || null, callouts: callouts.centers,
          priceTop: candles.coordinateToPrice(0), priceBottom: candles.coordinateToPrice(Math.max(1, plot.clientHeight - 30)) };
      },
      // where a price's profile row is drawn, in page coordinates (tests click it as a user would):
      // the middle of the profile's band, clear of the pane edge the price axis moves as it settles
      profilePoint: function (price) {
        var y = candles.priceToCoordinate(price), r = plot.getBoundingClientRect();
        return y == null ? null : { x: r.left + chart.timeScale().width() * (1 - profile.frac / 2), y: r.top + y };
      },
      // the rows and the served scale (largest |value|) of each profile
      setProfile: function (rows, scale, style) { profile.set(rows, scale, style); },
      // the volume profile's rows, and optionally one marked price {price, label, color} (its POC)
      setVolumeProfile: function (rows, scale, mark) { vprofile.set(rows, scale, 'bars', mark); },
      // the default view starts at this served time (e.g. the session's open); null: the newest bars
      setViewFrom: function (ts) { S.viewFrom = ts == null ? null : Number(ts); showRecent(); },
      setZones: function (list) { zones.set(list); },
      // the book heatmap ({cells, since_ts, bucket_sec, n_buckets, max_size, display_lo, display_hi}
      // as served) or null: its buckets become the time axis
      setHeatmap: function (h) {
        heat.set(h, P.up, P.down, P.ink3);
        // the axes need series values to exist: the first bucket carries the served window's low,
        // the last its high, on an invisible line (sizing only; never drawn, labelled or read)
        var pts = [];
        if (h) for (var i = 0; i < h.n_buckets; i++) {
          var pt = { time: h.since_ts + i * h.bucket_sec };
          if (i === 0) pt.value = h.display_lo; else if (i === h.n_buckets - 1) pt.value = h.display_hi;
          pts.push(pt);
        }
        timeline.setData(pts);
        chart.priceScale('right').applyOptions({ autoScale: true });
        chart.timeScale().fitContent();
      },
      selectProfile: function (price) { profile.select(price); }
    };
    return api;
  }

  // The timeframes every chart offers, and the 1-minute bars each asks /api/bars1m for (the server
  // rolls them up to the timeframe).
  var TFS = [{ id: '1', lbl: '1m' }, { id: '3', lbl: '3m' }, { id: '5', lbl: '5m' }, { id: '15', lbl: '15m' },
    { id: '30', lbl: '30m' }, { id: '60', lbl: '1h' }, { id: 'D', lbl: 'D' }];
  var BARS_LIMIT = { '1': 1200, '3': 2000, '5': 3000, '15': 6000, '30': 9000, '60': 12000, 'D': 12000 };

  function lsGet(k, d) { try { var v = window.localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* per-viewer only */ } }

  // The one chart toolbar, TradingView's: the timeframes (when the page passes onTf), candles or
  // line, the crosshair / horizontal-line / trend-line tools, undo, clear, reset, screenshot and
  // full screen. o: {tf, onTf(tf), styleKey (the viewer's candles/line choice, kept per chart)}.
  // Returns {setTf(tf), slot}: `slot` is where a page adds its own controls.
  function toolbar(el, api, o) {
    o = o || {};
    var style = o.styleKey ? lsGet(o.styleKey, 'candles') : 'candles';
    var btn = function (attr, title, html, cls) {
      return '<button type="button" class="tvc-tb' + (cls ? ' ' + cls : '') + '" ' + attr + ' title="' + title + '">' + html + '</button>'; };
    el.classList.add('tvc-toolbar');
    el.innerHTML = (o.onTf ? '<div class="tvc-tfs">' + TFS.map(function (t) {
        return btn('data-tf="' + t.id + '"', t.lbl, t.lbl); }).join('') + '</div><span class="tvc-sep"></span>' : '') +
      btn('data-act="style"', 'Candles or line', 'Line') + '<span class="tvc-sep"></span>' +
      btn('data-tool="cursor"', 'Crosshair (Esc)', '&#10010;', 'tvc-tool') +
      btn('data-tool="hline"', 'Horizontal line (Alt+H)', '&#8212;', 'tvc-tool') +
      btn('data-tool="trend"', 'Trend line (Alt+T)', '&#8725;', 'tvc-tool') +
      btn('data-act="undo"', 'Undo drawing (Ctrl+Z)', '&#8630;') + btn('data-act="clear"', 'Remove all drawings', '&#10005;') +
      '<span class="tvc-slot"></span><span class="tvc-grow"></span>' +
      btn('data-act="reset"', 'Reset chart (Alt+R)', '&#10227;') + btn('data-act="shot"', 'Save a PNG of the chart', '&#128247;') +
      btn('data-act="full"', 'Full screen', '&#9974;');
    function setTf(tf) { el.querySelectorAll('[data-tf]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-tf') === tf); }); }
    function paintStyle() { api.setStyle(style); el.querySelector('[data-act="style"]').classList.toggle('on', style === 'line'); }
    el.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      if (b.hasAttribute('data-tf')) { setTf(b.getAttribute('data-tf')); o.onTf(b.getAttribute('data-tf')); return; }
      if (b.hasAttribute('data-tool')) { api.setTool(b.getAttribute('data-tool')); return; }
      var a = b.getAttribute('data-act');
      if (a === 'style') { style = style === 'line' ? 'candles' : 'line'; if (o.styleKey) lsSet(o.styleKey, style); paintStyle(); }
      else if (a === 'undo') api.undo();
      else if (a === 'clear') api.clearDrawings();
      else if (a === 'reset') api.resetAll();
      else if (a === 'shot') api.screenshot();
      else if (a === 'full') api.fullscreen();
    });
    api.onTool(function (t) { el.querySelectorAll('[data-tool]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-tool') === t); }); });
    if (o.onTf) setTf(o.tf);
    paintStyle();
    return { setTf: setTf, slot: el.querySelector('.tvc-slot') };
  }

  window.EdTvChart = { create: create, toolbar: toolbar, TFS: TFS, BARS_LIMIT: BARS_LIMIT, alpha: alpha };
})();
