/* Ed Console — Options/Gamma Chart view. PRESENTATION ONLY.
   On the one TradingView-style chart every chart in the console uses (ed-tv-chart.js): the price
   (the `bars:chart` panel, completed Schwab bars at the toolbar's timeframe, and the `forming:chart`
   panel over them), the flip and the walls (the `terrain:chart` panel on the page's socket) as level
   lines, the live price (the header's price row), and the selected measure's per-strike rows
   (the socket's `strikes:chart` panel at the expiry chosen: GEX `today`, DEX and OI `measures`) as a profile on the price axis --
   bars, or dots sized by magnitude (Dot Map). The same view serves the Gamma, Delta / DEX and Open
   Interest subviews. The strikes shown are the window the server sends for the Gamma scope. A click
   on a strike selects it for every panel. The page computes no exposure or level. */
(function () {
  "use strict";

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;
  function isChart() {
    var s = window.EdShell.getState();
    return (
      s.workspace === "options" &&
      ["gamma", "dex", "oi"].indexOf(s.subview) !== -1 &&
      s.view === "chart"
    );
  }
  // the served profile for the selected measure: {rows (the window, each {strike, value, text}),
  // its scale (the window's largest |value|), max_abs_row, name}
  function served(sd) {
    if (sd === undefined || sd.failed != null || sd.available === false)
      return { rows: [], name: "GEX", signed: true }; // not sent, not produced, or no window: no rows
    var m = window.EdShell.getState().measure,
      x = sd.measures[m]; // DEX and OI; GEX is the rows' own
    if (x)
      return {
        rows: x.rows,
        scale: x.view.max_abs,
        max_abs_row: x.max_abs_row,
        name: m === "oi" ? "OI" : "DEX",
        signed: m !== "oi",
      };
    return {
      rows: sd.today,
      scale: sd.view.max_abs,
      max_abs_row: sd.max_abs_row,
      name: "GEX",
      signed: true,
    };
  }
  var ticker = window.EdShell.ticker;

  var _mode = "profile"; // 'profile' (bars) | 'dotmap' (dots)
  var _chart = null;
  var _liveQuote = null; // the header's price row (ed:quote_tick), the one displayed price
  var _last = { bars: undefined, forming: undefined, strikes: undefined, terrain: undefined };
  // the chart's timeframe (the toolbar's), kept per viewer
  var _tf = window.EdShell.pref("ed.gchart.tf", "1");
  function tfLabel() {
    return (
      (
        window.EdTvChart.TFS.filter(function (t) {
          return t.id === _tf;
        })[0] || {}
      ).lbl || _tf
    );
  }

  function liveSpot() {
    // the row whose served key is the selected instrument's (EdShell state.key)
    var q = _liveQuote;
    return q && q.ticker === window.EdShell.getState().key && q.spot != null
      ? Number(q.spot)
      : null;
  }
  function ensureChart() {
    var host = document.getElementById("chartBody");
    if (!host || !window.EdTvChart || !window.LightweightCharts) return null;
    if (_chart && host.querySelector(".gchart-plot")) return _chart;
    host.innerHTML =
      '<div class="gchart-head"></div><div class="gchart-tb"></div><div class="gchart-plot"></div><div class="gchart-empty" hidden></div>';
    _chart = window.EdTvChart.create(host.querySelector(".gchart-plot"), {
      nearestN: 99,
      onProfileClick: function (row) {
        window.EdShell.setStrike(row.price, window.EdShell.getExpiry()); // the workspace's expiry filter carries through
      },
    });
    window.EdTvChart.toolbar(host.querySelector(".gchart-tb"), _chart, {
      tf: _tf,
      styleKey: "ed.gchart.style",
      onTf: function (tf) {
        _tf = tf;
        window.EdShell.setPref("ed.gchart.tf", tf);
        load();
      },
    });
    return _chart;
  }

  // The bars at the toolbar's timeframe, the profile (the Gamma scope's window, unpanned) and the
  // flip and walls: the `bars:chart`, `forming:chart`, `strikes:chart` and `terrain:chart` panels
  // (push.bars, push.strikes, push.terrain) the program sends on the page's socket while the chart
  // is on, at once and each time the bars, the trades or the levels change.
  var PANELS = {
    "bars:chart": "bars",
    "forming:chart": "forming",
    "strikes:chart": "strikes",
    "terrain:chart": "terrain",
  };
  function askPanels() {
    window.EdShell.showPanel(
      "strikes:chart",
      isChart() ? window.EdShell.windowAtExpiry(null) : null,
    );
    window.EdShell.showPanel("terrain:chart", isChart() ? {} : null);
  }
  function load() {
    askPanels();
    var on = isChart() && ensureChart();
    window.EdShell.showPanel(
      "bars:chart",
      on ? { tf: _tf, limit: window.EdTvChart.BARS_LIMIT[_tf] } : null,
    );
    window.EdShell.showPanel("forming:chart", on ? { tf: _tf } : null);
  }
  document.addEventListener("ed:panel", function (e) {
    var key = PANELS[e.detail.type];
    if (!key) return;
    _last[key] = e.detail;
    if (!isChart() || _last.bars === undefined) return;
    // the bars forming from the trades, drawn over the bars as they come (push.bars.forming)
    if (key === "forming" && e.detail.failed == null) ensureChart().forming(e.detail);
    else render();
  });

  function render() {
    var c = ensureChart();
    if (!c) return;
    var host = document.getElementById("chartBody");
    var P = c.palette(),
      barsD = _last.bars,
      sd = _last.strikes,
      t = _last.terrain;
    var prof = served(sd);
    // each panel as served; one not sent yet (undefined) draws nothing, and the program's words
    // when it could not produce one (`failed`), and the strikes' reason for holding no rows (an
    // expiry the chain does not list), are said, never drawn as empty
    var words = "";
    [barsD, _last.forming, sd, t].forEach(function (p) {
      if (p && p.failed != null) words = (words ? words + " · " : "") + p.failed;
    });
    if (sd && sd.failed == null && sd.available === false)
      words = (words ? words + " · " : "") + sd.reason;
    var okBars = barsD && barsD.failed == null;
    var bars = okBars ? barsD.bars : [];
    var win = prof.rows.filter(function (r) {
      return r.value != null;
    }); // the served window; unknown: nothing drawn
    c.setBars(
      bars,
      okBars ? barsD.tf : _tf,
      window.EdShell.getState().display || ticker(),
      okBars && barsD.last_bar && barsD.last_bar.label,
    );
    c.setProfile(
      win.map(function (r) {
        return {
          price: r.strike,
          value: r.value,
          color: !prof.signed ? P.accent : window.EdDraw.bySign(r.value, P.up, P.down, P.accent),
        };
      }),
      prof.scale,
      _mode === "dotmap" ? "dots" : "bars",
    );
    c.selectProfile(
      window.EdShell.getState().selStrike == null
        ? null
        : Number(window.EdShell.getState().selStrike),
    );
    var lv = [];
    if (t && !t.error && t.failed == null) {
      if (t.gamma_flip != null)
        lv.push({
          id: "gamma_flip",
          price: Number(t.gamma_flip),
          price_text: t.gamma_flip_text,
          label: "Gamma flip",
          color: P.accent,
          style: 2,
          width: 1,
        });
      if (t.call_wall != null)
        lv.push({
          id: "call_wall",
          price: Number(t.call_wall),
          price_text: t.call_wall_text,
          label: "Call wall",
          color: P.down,
          style: 0,
          width: 1,
        });
      if (t.put_wall != null)
        lv.push({
          id: "put_wall",
          price: Number(t.put_wall),
          price_text: t.put_wall_text,
          label: "Put wall",
          color: P.up,
          style: 0,
          width: 1,
        });
    }
    c.setLevels(lv);
    var spot = liveSpot();
    var tradeTime = _liveQuote && spot != null ? _liveQuote.trade_time_ct : null;
    c.setLivePrice(spot, _liveQuote && spot != null ? _liveQuote.trade_age_text : null, tradeTime);
    var empty = host.querySelector(".gchart-empty");
    empty.hidden = !words && !!(bars.length || win.length);
    empty.textContent =
      words || (empty.hidden ? "" : "no bars / per-strike " + prof.name + " for this symbol");
    paintHead(
      host.querySelector(".gchart-head"),
      okBars ? barsD.last_bar : null,
      win,
      prof,
      sd,
      spot == null ? null : _liveQuote.spot_disp,
      tradeTime,
    );
  }
  function paintHead(el, lastBar, win, prof, sd, spotText, tradeTime) {
    var n = prof.name;
    var asof =
      (lastBar
        ? '<span class="asof">price ' + tfLabel() + " · " + esc(lastBar.label) + "</span>"
        : "") + window.EdShell.verdictBadge(window.EdShell.served(sd), n + " terrain");
    var top = prof.max_abs_row; // served: the largest-magnitude row
    var shown = top ? orDash(top.text) + (prof.signed ? "" : " contracts") : "";
    el.innerHTML =
      (asof ? '<div class="chart-asof">' + asof + "</div>" : "") +
      '<div class="chart-legend">' +
      (prof.signed
        ? '<span><span class="sw" style="background:var(--ed-pos)"></span>+' +
          n +
          "</span>" +
          '<span><span class="sw" style="background:var(--ed-neg)"></span>−' +
          n +
          "</span>"
        : '<span><span class="sw" style="background:var(--ed-accent)"></span>' + n + "</span>") +
      '<span><span class="sw" style="background:var(--ed-accent)"></span>flip</span>' +
      "<span>spot " +
      orDash(spotText) +
      (tradeTime ? " · last trade " + esc(tradeTime) : "") +
      "</span>" +
      (top
        ? "<span>largest |" + n + "| " + esc(top.strike_text) + " · " + esc(shown) + "</span>"
        : "") +
      "</div>";
  }

  function bindModes() {
    var host = document.getElementById("chartModes");
    if (!host) return;
    host.querySelectorAll(".cmode").forEach(function (b) {
      b.addEventListener("click", function () {
        _mode = b.getAttribute("data-cmode");
        host.querySelectorAll(".cmode").forEach(function (x) {
          x.classList.toggle("on", x === b);
        });
        if (_chart) render();
      });
    });
  }

  window.addEventListener("ed:quote_tick", function (ev) {
    var q = (ev && ev.detail) || {};
    if (q.ticker !== window.EdShell.getState().key) return;
    _liveQuote = q;
    if (isChart() && _chart && _last.bars !== undefined) render();
  });
  document.addEventListener("ed:view", load);
  document.addEventListener("ed:ticker", function () {
    _last = { bars: undefined, forming: undefined, strikes: undefined, terrain: undefined };
    load();
  });
  document.addEventListener("ed:scope", askPanels); // a new window: the profile's panel asks it
  document.addEventListener("ed:expiry", askPanels); // a new expiry: its rows are asked
  document.addEventListener("ed:measure", function () {
    if (_chart && isChart() && _last.bars !== undefined) render();
  });
  document.addEventListener("ed:strike", function () {
    if (_chart && isChart())
      _chart.selectProfile(
        window.EdShell.getState().selStrike == null
          ? null
          : Number(window.EdShell.getState().selStrike),
      );
  });
  bindModes();
  // read-only view for tests (e2e) -- never a control surface
  window.EdGammaChart = {
    state: function () {
      return _chart ? _chart.state() : null;
    },
    profilePoint: function (price) {
      return _chart ? _chart.profilePoint(price) : null;
    },
  };
})();
