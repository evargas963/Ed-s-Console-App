/* The page's drawing math, its one home: where a served value is placed on the screen, how long
   or how dark it is drawn, how many columns fit the window, when a notice's chime sounds. It makes
   no number the operator reads:
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
  // the tone a served value is drawn in by its sign: `positive` for 0 and above, `negative` below,
  // `unknown` when it is not known
  function bySign(v, positive, negative, unknown) {
    return v == null ? unknown : v >= 0 ? positive : negative;
  }
  // a bar's width, in percent of its track, by strength; 0 when the value is unknown
  function barWidth(value, scale) {
    var s = strength(value, scale);
    return s == null ? 0 : s * 100;
  }
  // a width in percent as a style takes it, to a tenth
  function pct(width) {
    return width.toFixed(1) + "%";
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
  // where a served percentage (-100 to 100) sits on a strip whose centre is 0 and whose ends hold
  // 5% of margin: a percent of the strip's width from its left
  function centredLeft(pct) {
    return 50 + Number(pct) * 0.45;
  }
  // an SVG path of served percentages (-100 to 100), one every `step` seconds across a window of
  // `seconds`, on a W wide box whose centre line is at `mid` (0 at the centre, 100 at the top);
  // an unknown value breaks the line
  function centredPath(values, step, seconds, W, mid) {
    var d = "";
    values.forEach(function (v, i) {
      if (v == null) return;
      d +=
        (d && values[i - 1] != null ? "L" : "M") +
        (((i * step) / seconds) * W).toFixed(1) +
        " " +
        (mid - (v / 100) * mid).toFixed(1);
    });
    return d;
  }
  // how long, in seconds, the header's line takes to run its own width (`linePx`) at the tape's
  // steady speed, so every line moves alike whatever it holds; null when it fits its window
  // (`windowPx`) and stands still
  var TAPE_PX_PER_SEC = 50;
  function tapeSeconds(linePx, windowPx) {
    return linePx <= windowPx ? null : linePx / TAPE_PX_PER_SEC;
  }
  // whether an element one line high has wrapped its words out of sight (the header's left-out
  // cell, where row 1 has no room for its sentence: index.html)
  function wrappedAway(el) {
    return el.scrollHeight > el.clientHeight;
  }
  // the text colour that reads on a heat cell's colour: light on dark, dark on light
  function heatInk(c) {
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] < 140 ? "#f4f7fb" : "#0a0e17";
  }
  // a heat cell's text weight by its strength (null: no strength): heavier on a strong cell
  function heatWeight(t) {
    return t != null && t > 0.65 ? 750 : 550;
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
  // where `price` falls among drawn rows `points` ([{price, y}], highest price first): in
  // proportion between the two that hold it; a single row only at its own price; null outside
  function priceY(price, points) {
    if (points.length === 1 && points[0].price === price) return points[0].y;
    for (var i = 0; i < points.length - 1; i++) {
      var a = points[i],
        b = points[i + 1];
      if (price <= a.price && price >= b.price) {
        var span = a.price - b.price;
        return a.y + (span === 0 ? 0 : (a.price - price) / span) * (b.y - a.y);
      }
    }
    return null;
  }
  // the middle of a drawn box `rect`, measured from the top of `within`
  function middleY(rect, within) {
    return rect.top - within.top + rect.height / 2;
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
  // a half dial, as the options lean's gauge draws it, in a 200 x 112 box: `zones` equal arcs from
  // the left end (the first zone) over the top to the right end (the last), each classed "z<i>",
  // and the needle at the served angle `deg` from upright, positive to the right (none when null).
  // The SVG's inner markup.
  function gauge(deg, zones) {
    var cx = 100,
      cy = 100,
      r = 82,
      gap = 1.2,
      step = 180 / zones;
    function at(a) {
      var t = (a * Math.PI) / 180;
      return (cx + r * Math.cos(t)).toFixed(2) + " " + (cy - r * Math.sin(t)).toFixed(2);
    }
    var svg = "";
    for (var i = 0; i < zones; i++) {
      var a0 = 180 - step * i - (i ? gap : 0),
        a1 = 180 - step * (i + 1) + (i < zones - 1 ? gap : 0);
      svg +=
        '<path class="z' + i + '" d="M' + at(a0) + " A" + r + " " + r + " 0 0 1 " + at(a1) + '"/>';
    }
    if (deg != null)
      svg +=
        '<g class="needle" transform="rotate(' +
        Number(deg).toFixed(2) +
        " " +
        cx +
        " " +
        cy +
        ')"><path d="M' +
        (cx - 3.2) +
        " " +
        cy +
        " L" +
        cx +
        " " +
        (cy - r + 10) +
        " L" +
        (cx + 3.2) +
        " " +
        cy +
        ' Z"/></g>';
    return svg + '<circle class="hub" cx="' + cx + '" cy="' + cy + '" r="6"/>';
  }

  // the toast's chime (ed-core.js toast): two soft sine notes a fifth apart, the second 0.14 s
  // after the first, each rising in 20 ms and fading out by 0.9 s: [hertz, start]. The audio
  // clock places them (`audio`, a running AudioContext): no time of day, and no value shown.
  var CHIME = [
    [880, 0],
    [1318.51, 0.14],
  ];
  function chime(audio) {
    var t0 = audio.currentTime;
    CHIME.forEach(function (note) {
      var osc = audio.createOscillator(),
        gain = audio.createGain(),
        at = t0 + note[1];
      osc.type = "sine";
      osc.frequency.value = note[0];
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.2, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.9);
      osc.connect(gain).connect(audio.destination);
      osc.start(at);
      osc.stop(at + 0.95);
    });
  }

  window.EdDraw = {
    chime: chime,
    gauge: gauge,
    strength: strength,
    barWidth: barWidth,
    pct: pct,
    bySign: bySign,
    heatFill: heatFill,
    heatInk: heatInk,
    heatWeight: heatWeight,
    centredLeft: centredLeft,
    centredPath: centredPath,
    rowsMoved: rowsMoved,
    stepWithin: stepWithin,
    fitCount: fitCount,
    apart: apart,
    priceY: priceY,
    middleY: middleY,
    sparkline: sparkline,
    tapeSeconds: tapeSeconds,
    wrappedAway: wrappedAway,
  };
})();
