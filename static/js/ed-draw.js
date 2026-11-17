/* The page's drawing math, its one home: where a served value is placed on the screen, how long
   or how dark it is drawn, how many columns fit the window. It makes no number the operator reads:
   every number, total and label is served (AGENTS.md rule 4). The chart (ed-tv-chart.js) draws
   its own; ESLint refuses Math, .sort and .reduce in every other page script. */
(function () {
  "use strict";

  // how strong a value draws against its served scale, the straight proportion in [0, 1]; null
  // when the value is unknown or the scale has no size, which each panel draws as it draws unknown
  function strength(value, scale) {
    if (value == null || isNaN(value) || !(scale > 0)) return null;
    return Math.min(1, Math.abs(value) / scale);
  }
  // a heat cell's colour: the theme's zero colour toward its positive or negative one by
  // strength; null when strength is
  function heatFill(value, scale, colors) {
    var t = strength(value, scale);
    if (t == null) return null;
    var a = colors.zero,
      b = value < 0 ? colors.neg : colors.pos;
    return [0, 1, 2].map(function (i) {
      return Math.round(a[i] + (b[i] - a[i]) * t);
    });
  }
  // the whole rows a drag of `dy` pixels moved, rows `rowPx` tall
  function rowsMoved(dy, rowPx) {
    return Math.round(dy / rowPx);
  }
  // one step from index `i` toward `dir` (+1 or -1), held within 0..n-1
  function stepWithin(i, dir, n) {
    return Math.max(0, Math.min(n - 1, i + dir));
  }
  // how many columns `minPx` wide fit in `width` pixels, from `lo` to `hi`
  function fitCount(width, minPx, lo, hi) {
    return Math.max(lo, Math.min(hi, Math.floor(width / minPx)));
  }
  // whether two drawn positions are apart (more than a tenth of a pixel)
  function apart(a, b) {
    return Math.abs(a - b) > 0.1;
  }
  // where `price` falls down a column of rows `rowPx` tall, highest strike first: between the
  // middles of the two rows whose strikes hold it, in proportion; past either end, at that end's
  // middle; 0 with no rows
  function rowAnchorY(price, strikes, rowPx) {
    var n = strikes.length,
      half = rowPx / 2;
    if (!n) return 0;
    for (var i = 0; i < n - 1; i++) {
      var hi = strikes[i],
        lo = strikes[i + 1];
      if (price <= hi && price >= lo) {
        var span = hi - lo;
        return half + i * rowPx + (span === 0 ? 0 : (hi - price) / span) * rowPx;
      }
    }
    return price >= strikes[0] ? half : n * rowPx - half;
  }
  // labels at anchors `ys`, in order, set at least `gap` apart and within `margin` of a column
  // `height` tall: each pushed down past the one above, the last held at the bottom and those
  // above pushed up from it, none above the top
  function stackLabels(ys, height, gap, margin) {
    var pos = ys.map(function (y) {
      return Math.min(height - margin, Math.max(margin, y));
    });
    var i;
    for (i = 1; i < pos.length; i++) pos[i] = Math.max(pos[i], pos[i - 1] + gap);
    if (pos.length && pos[pos.length - 1] > height - margin) {
      pos[pos.length - 1] = height - margin;
      for (i = pos.length - 2; i >= 0; i--) pos[i] = Math.min(pos[i], pos[i + 1] - gap);
    }
    return pos.map(function (y) {
      return Math.max(margin, y);
    });
  }
  // a card's small chart, as the reference draws it (line, area or bars), of served series in a
  // W x H box: sets [{ys, xs (served x values; else evenly spaced), color, kind: 'line'|'area'|
  // 'bars', colors (bars: one per y)}]; a null y is a gap. The SVG's inner markup, or null when no
  // series has a point. No axis numbers: a number derived from the series is not printed.
  function sparkline(sets, W, H) {
    var pts = [];
    sets.forEach(function (s) {
      s.ys.forEach(function (y, i) {
        if (y != null && isFinite(y)) pts.push([s.xs ? s.xs[i] : i, y]);
      });
    });
    if (!pts.length) return null;
    var xs = pts.map(function (p) {
        return p[0];
      }),
      ys = pts.map(function (p) {
        return p[1];
      });
    var x0 = Math.min.apply(null, xs),
      x1 = Math.max.apply(null, xs),
      y0 = Math.min.apply(null, ys),
      y1 = Math.max.apply(null, ys);
    if (
      sets.some(function (s) {
        return s.kind !== "line";
      })
    ) {
      y0 = Math.min(0, y0);
      y1 = Math.max(0, y1);
    }
    if (x1 === x0) x1 = x0 + 1;
    if (y1 === y0) y1 = y0 + 1;
    function X(x) {
      return ((x - x0) / (x1 - x0)) * W;
    }
    function Y(y) {
      return H - ((y - y0) / (y1 - y0)) * H;
    }
    var svg = "";
    sets.forEach(function (s) {
      var n = s.ys.length;
      if (s.kind === "bars") {
        var bw = Math.max(1, (W / Math.max(1, n)) * 0.7);
        s.ys.forEach(function (y, i) {
          if (y == null) return;
          var x = X(s.xs ? s.xs[i] : i) - bw / 2,
            top = Math.min(Y(y), Y(0));
          svg +=
            '<rect x="' +
            x.toFixed(1) +
            '" y="' +
            top.toFixed(1) +
            '" width="' +
            bw.toFixed(1) +
            '" height="' +
            Math.max(0.5, Math.abs(Y(y) - Y(0))).toFixed(1) +
            '" fill="' +
            (s.colors ? s.colors[i] : s.color) +
            '"/>';
        });
        return;
      }
      var runs = [[]]; // a null breaks the line
      s.ys.forEach(function (y, i) {
        if (y == null || !isFinite(y)) {
          if (runs[runs.length - 1].length) runs.push([]);
          return;
        }
        runs[runs.length - 1].push([X(s.xs ? s.xs[i] : i), Y(y)]);
      });
      runs.forEach(function (r) {
        if (!r.length) return;
        var d = r
          .map(function (p, k) {
            return (k ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1);
          })
          .join("");
        if (s.kind === "area")
          svg +=
            '<path d="' +
            d +
            "L" +
            r[r.length - 1][0].toFixed(1) +
            " " +
            H +
            "L" +
            r[0][0].toFixed(1) +
            " " +
            H +
            'Z" fill="' +
            s.color +
            '" opacity=".18"/>';
        svg +=
          '<path d="' +
          d +
          '" fill="none" stroke="' +
          s.color +
          '" stroke-width="1.6" vector-effect="non-scaling-stroke"/>';
        if (r.length === 1)
          svg +=
            '<circle cx="' +
            r[0][0].toFixed(1) +
            '" cy="' +
            r[0][1].toFixed(1) +
            '" r="2" fill="' +
            s.color +
            '"/>';
      });
    });
    return svg;
  }

  window.EdDraw = {
    strength: strength,
    heatFill: heatFill,
    rowsMoved: rowsMoved,
    stepWithin: stepWithin,
    fitCount: fitCount,
    apart: apart,
    rowAnchorY: rowAnchorY,
    stackLabels: stackLabels,
    sparkline: sparkline,
  };
})();
