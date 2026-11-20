/* Ed Console — Trade Desk / "Desk" subview. PRESENTATION ONLY.

   One page for the SELECTED ticker, one global timeframe:
     MARKET MAP   <- the bars panel (completed Schwab bars at the timeframe),
                     the levels panel (value area, VWAP, prior day, opening range, overnight),
                     the terrain panel (call/put wall, gamma flip, max pain -- full chain)
     ATTENTION    <- the desk panel (served, numbered; each marker is its queue entry, linked
                     both ways): level crosses judged by their minute's bar, wall breaches,
                     the book's size walls at the book's own time
     CARDS        <- the book, terrain, bars and liquidity panels (value/VWAP relation) and the
                     price row (Schwab LEVELONE)
     HEADER TRUST <- the same panels' own state/age fields
   Every panel arrives on the page's one socket. The browser computes nothing: it picks which
   served values to show, formats them, and places a served event on the bar that contains it.
   A value with no producer yet says so. */
(function () {
  "use strict";

  // the chart's timeframes and bars per timeframe (ed-tv-chart, every chart's)
  var TFS = window.EdTvChart.TFS,
    FULL_LIMIT = window.EdTvChart.BARS_LIMIT;
  // the Order Flow card's bars: the newest hour of 1-minute bars
  var FLOW_BARS = 60;
  // The ONE global timeframe also sets how far back the queue and the event markers reach.
  // the event window and its words are the server's (the desk panel's window_label), for this timeframe
  function windowLabel() {
    return S.events && S.events.tf === S.tf ? S.events.window_label : "-";
  }
  var FAMILIES = [
    { id: "volume_profile", lbl: "Volume profile (RTH)" },
    { id: "value_area", lbl: "Value area" },
    { id: "vwap", lbl: "VWAP" },
    { id: "gamma", lbl: "Gamma" },
    { id: "prior_day", lbl: "Prior day" },
    { id: "opening_range", lbl: "Opening range" },
    { id: "overnight", lbl: "Overnight" },
  ];
  var DRILL = {
    liquidity: ["order-flow", "heatmap"],
    flow: ["order-flow", "book"],
    options: ["options", "book"],
    vol: ["options", "chain"],
  };

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;
  var notLive = window.EdShell.notLive;
  // Schwab's book time stands beside the age words. A book that is not live keeps that
  // time and says so. The words are unchanged when no book time was sent.
  function bookAgeLabel(m, word) {
    var when = m && m.book_time_ct != null ? m.book_time_ct : null;
    if (when != null) return when + " · " + word;
    return word;
  }
  // The chain's time stands beside its age. The age words are unchanged when no chain time was sent.
  // the gamma levels' served time, word (LIVE, CLOSE, STALE, NOT LIVE) and age, each when sent
  function chainAgeLabel(t) {
    return [t.levels_time_ct, t.levels_state, t.levels_age_text]
      .filter(function (w) {
        return w != null;
      })
      .join(" · ");
  }
  function onDesk() {
    var s = window.EdShell.getState();
    return s.workspace === "trade-desk" && s.subview === "desk";
  }
  // the instrument's served display name (the daemon's answer, EdShell state.display); as typed
  // until it arrives
  function shown() {
    return window.EdShell.getState().display || S.ticker;
  }
  function $(id) {
    return document.getElementById(id);
  }
  var sget = window.EdShell.pref,
    sset = window.EdShell.setPref; // the viewer's own settings

  var S = {
    tf: sget("ed.desk.tf", "5"),
    nearest: Number(sget("ed.desk.nearest", "6")) || 6,
    fam: JSON.parse(
      sget(
        "ed.desk.fam",
        '{"value_area":1,"vwap":1,"gamma":1,"prior_day":1,"opening_range":1,"overnight":1}',
      ),
    ),
    ticker: null,
    tb: null,
    chart: null,
    bars: [],
    levels: null,
    terrain: null,
    micro: null,
    crosses: null,
    analytics: null,
    liq: null,
    quotes: {},
    queue: [],
    sel: null,
    // the Liquidity card's venue (COMPOSITE, or BOOK: the shell's book switch) and depth view
    liqVenue: sget("ed.desk.liqvenue", "COMPOSITE"),
    liqView:
      ["weighted", "1", "3", "5"].indexOf(sget("ed.desk.liqview", "")) >= 0
        ? sget("ed.desk.liqview", "")
        : "weighted",
    liqPaints: 0,
    liqHold: null,
    liqPending: false,
    liqDetail: false,
    pushDown: null, // the header's word while the daemon's price push is down (ed:price_push_down)
  };

  // ------------------------------------------------------------------ layout wiring
  function buildToolbar() {
    var fam = $("tdmFamilies");
    if (!fam || fam.getAttribute("data-built")) return;
    fam.setAttribute("data-built", "1");
    fam.innerHTML =
      FAMILIES.map(function (f) {
        return (
          '<button type="button" class="tdm-fam fam-' +
          f.id +
          '" data-fam="' +
          f.id +
          '"><i></i>' +
          f.lbl +
          '<b data-famv="' +
          f.id +
          '"></b></button>'
        );
      }).join("") + '<span class="tdm-fam-note" id="tdmProfNote"></span>';
    fam.addEventListener("click", function (e) {
      var b = e.target.closest("[data-fam]");
      if (!b) return;
      var id = b.getAttribute("data-fam");
      S.fam[id] = S.fam[id] === 0 ? 1 : 0; // a family not yet saved is on
      sset("ed.desk.fam", JSON.stringify(S.fam));
      paintChartLevels();
    });
    paintFamilies();
  }
  function paintFamilies() {
    document.querySelectorAll("#tdmFamilies [data-fam]").forEach(function (b) {
      b.classList.toggle("on", S.fam[b.getAttribute("data-fam")] !== 0);
    });
    var pva = S.levels && S.levels.prior_value_area;
    var v = { vwap: S.levels && S.levels.vwap_text, prior_day: pva && pva.text };
    document.querySelectorAll("#tdmFamilies [data-famv]").forEach(function (b) {
      b.textContent = v[b.getAttribute("data-famv")] || "";
    });
    // the profile's basis, or why there is none (the value area's served reason)
    var vp = S.levels && S.levels.volume_profile,
      pn = $("tdmProfNote");
    var why = (S.levels ? S.levels.families_absent : []).filter(function (a) {
      return a.family === "value_area";
    })[0];
    if (pn)
      pn.textContent = vp
        ? vp.basis +
          (vp.bars_without_volume
            ? " · " +
              vp.bars_without_volume +
              " of " +
              vp.bars +
              " RTH bars sent no volume and are not in it"
            : "")
        : why
          ? "Volume profile (RTH) not drawn: " + why.reason
          : "";
  }
  function paintTfButtons() {
    if (S.tb) S.tb.setTf(S.tf);
    var lb = $("tdmLookback");
    if (lb) lb.textContent = windowLabel();
  }
  function ensureChart() {
    if (S.chart) return S.chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    S.chart = window.EdTvChart.create($("tdmChart"), {
      nearestN: S.nearest,
      fullscreenEl: $("tdmMap"),
    });
    S.tb = window.EdTvChart.toolbar($("tdmToolbar"), S.chart, {
      tf: S.tf,
      onTf: setTf,
      styleKey: "ed.desk.style",
    });
    S.tb.slot.innerHTML =
      '<span class="tvc-sep"></span>' +
      '<label class="tvc-nsel" title="How many key levels to draw (nearest to price, inside the visible range)">Levels ' +
      '<select id="tdmNearest">' +
      [3, 4, 6, 8, 12, 99]
        .map(function (n) {
          return (
            '<option value="' +
            n +
            '"' +
            (n === S.nearest ? " selected" : "") +
            ">" +
            (n === 99 ? "All" : n) +
            "</option>"
          );
        })
        .join("") +
      "</select></label>";
    $("tdmNearest").addEventListener("change", function (e) {
      S.nearest = Number(e.target.value) || 6;
      sset("ed.desk.nearest", String(S.nearest));
      S.chart.setNearestN(S.nearest);
    });
    paintTfButtons();
    document.querySelectorAll("[data-drill]").forEach(function (el) {
      el.addEventListener("click", function () {
        var d = DRILL[el.getAttribute("data-drill")];
        if (!d) return;
        window.EdShell.setWorkspace(d[0]);
        window.EdShell.setSubview(d[1]);
      });
    });
    return S.chart;
  }
  // A new timeframe asks only for what depends on it: its bars, its levels (VWAP per bar) and its
  // event window. Until they arrive the chart and queue say what is loading, never the old view.
  function setTf(tf) {
    if (tf === S.tf) return;
    S.tf = tf;
    sset("ed.desk.tf", tf);
    paintTfButtons();
    S.bars = [];
    S.levels = S.events = undefined; // answers for another timeframe are dropped (tf check)
    clearChart();
    paintQueue();
    paintCards();
    askPanels();
  }
  function clearChart() {
    if (!S.chart) return;
    S.chart.setBars([], S.tf, shown(), null);
    S.chart.setLevels([]);
    S.chart.setMarkers([]);
    S.chart.setVolumeProfile([]);
    S.chart.setVwap([]);
    S.chart.setValueArea(null, null);
    $("tdmChartEmpty").hidden = false;
    $("tdmChartEmpty").textContent =
      "Loading " +
      shown() +
      " · " +
      (
        TFS.filter(function (x) {
          return x.id === S.tf;
        })[0] || {}
      ).lbl +
      "…";
  }

  // ------------------------------------------------------------------ data
  // the chart's bars at its timeframe (the `bars:deskmap` panel), whole each time a bar completes;
  // the chart keeps the operator's zoom while the symbol and timeframe stand
  function takeBars(d) {
    var bars = d.failed == null ? d.bars : [];
    S.bars = bars;
    S.chart.setBars(bars, S.tf, shown(), d.last_bar && d.last_bar.label);
    $("tdmChartEmpty").hidden = bars.length > 0;
    $("tdmChartEmpty").textContent = bars.length
      ? ""
      : d.failed != null
        ? d.failed
        : "No bars for " +
          shown() +
          (d.error ? " — " + d.error : " — nothing banked or streamed for this symbol yet.");
    paintChartOverlays();
    paintQueue();
    openView();
    paintFooter();
  }
  // the timeframe's levels (VWAP per chart bar; the `levels:map` panel) or event window (the
  // `desk` panel), drawn as it arrives
  function takePerTf(key, d) {
    S[key] = d;
    paintTfButtons();
    paintChartOverlays();
    paintQueue();
    paintCards();
    paintTrust();
    paintAgreement();
    paintFooter();
    openView();
  }
  function paintAll() {
    paintChartOverlays();
    paintCards();
    paintTrust();
    paintAgreement();
    paintFooter();
  }
  // Everything the desk draws, the program sends on the page's socket while the desk is on, at
  // once and each time it changes. Per symbol: the option terrain (`terrain:map`), the Options
  // Book's lean at the expiry chosen (none chosen: the front one) in the Gamma scope's window
  // (`option_book:desk`), the zones (`liquidity:deskmap`), the book (`book:deskmap`) and the Order
  // Flow card's hour of bars (`bars:flow`). Per timeframe: the chart's bars (`bars:deskmap`) and
  // those forming (`forming:deskmap`), levels (`levels:map`) and event window (`desk`).
  var PANELS = { "terrain:map": "terrain" };
  // these are kept as null when the program could not produce them
  var OR_NULL = {
    "liquidity:deskmap": "liq",
    "option_book:desk": "optBook",
    "bars:flow": "flowBars",
  };
  var PER_TF = { "levels:map": "levels", desk: "events" };
  function askPanels() {
    var on = onDesk(),
      venue = window.EdShell.getState().bookVenue;
    window.EdShell.showPanel("levels:map", on ? { tf: S.tf } : null);
    window.EdShell.showPanel("terrain:map", on ? {} : null);
    window.EdShell.showPanel("option_book:desk", on ? window.EdShell.windowAtExpiry(null) : null);
    window.EdShell.showPanel("bars:deskmap", on ? { tf: S.tf, limit: FULL_LIMIT[S.tf] } : null);
    window.EdShell.showPanel("forming:deskmap", on ? { tf: S.tf } : null);
    window.EdShell.showPanel("bars:flow", on ? { tf: "1", limit: FLOW_BARS } : null);
    window.EdShell.showPanel("desk", on ? { tf: S.tf, limit: FULL_LIMIT[S.tf] } : null);
    window.EdShell.showPanel("liquidity:deskmap", on ? {} : null);
    window.EdShell.showPanel("book:deskmap", on ? { venue: venue } : null);
  }
  function takePanel(d) {
    var ok = d.failed == null;
    // an answer for a timeframe no longer on the chart is not drawn; one not produced is none
    if (PER_TF[d.type] && (!ok || d.tf === S.tf)) takePerTf(PER_TF[d.type], ok ? d : null);
    if (d.type === "bars:deskmap" && S.chart && (!ok || d.tf === S.tf)) takeBars(d);
    // the bars forming from the trades, drawn over the bars as they come (push.bars.forming)
    if (d.type === "forming:deskmap" && S.chart && S.bars.length) {
      if (ok) S.chart.forming(d);
      else $("tdmChartEmpty").textContent = d.failed;
      $("tdmChartEmpty").hidden = ok;
    }
    if (d.type === "book:deskmap") {
      S.micro = ok ? d : null;
      paintCards();
      paintTrust();
      paintQueue();
      paintAgreement();
      paintFooter();
    }
    if (PANELS[d.type]) S[PANELS[d.type]] = d;
    if (d.type === "bars:flow") S.flowBars = ok ? d.bars : null;
    else if (OR_NULL[d.type]) S[OR_NULL[d.type]] = ok ? d : null;
    if (PANELS[d.type] || OR_NULL[d.type]) paintAll();
  }
  // what an answer says with nothing to draw: the program could not produce the panel (`failed`),
  // or the answer's own error
  function why(x) {
    return x.failed != null ? x.failed : x.error;
  }
  // the chart opens on the served event window (5m/30m: the session), once per symbol and timeframe
  function openView() {
    var vk = S.ticker + "|" + S.tf;
    if (S.chart && S.bars.length && S.events && S.events.tf === S.tf && S.viewKey !== vk) {
      S.viewKey = vk;
      S.chart.setViewFrom(S.events.window_start_ts_utc);
    }
  }

  // ------------------------------------------------------------------ chart overlays
  function levelList() {
    var P = S.chart.palette(),
      out = [];
    // the reference's key: value-area levels amber, every other key level orange dashed
    var style = {
      value_area: [P.warn, 2, 1],
      prior_day: [P.stale, 2, 1],
      opening_range: [P.stale, 2, 1],
      overnight: [P.stale, 2, 1],
      gamma: [P.stale, 2, 1],
    };
    var gamma = {
      call_wall: ["Call wall", P.up, 0, 2],
      put_wall: ["Put wall", P.down, 0, 2],
      gamma_flip: ["Γ flip", P.accent, 0, 2],
      max_pain: ["Max pain", P.ink3, 3, 1],
    };
    var byId = {};
    (S.levels ? S.levels.levels : []).forEach(function (l) {
      byId[l.id] = l;
    });
    // served order: nearest the live price first (by_distance); the chart keeps the first N on screen
    (S.levels ? S.levels.by_distance : []).forEach(function (id) {
      var l = byId[id];
      if (!l || l.price == null || S.fam[l.family] === 0) return;
      var g = l.family === "gamma" && gamma[l.id];
      var lean = S.terrain && S.terrain[l.id + "_lean"]; // served: call_wall_lean / put_wall_lean
      if (g) {
        out.push({
          id: l.id,
          price: Number(l.price),
          price_text: l.price_text,
          label: g[0] + (lean ? " · " + lean + notLive(S.terrain) : ""),
          color: g[1],
          style: g[2],
          width: g[3],
        });
        return;
      }
      var s = style[l.family];
      if (!s) return;
      out.push({
        id: l.id,
        price: Number(l.price),
        price_text: l.price_text,
        label: l.short,
        color: s[0],
        style: s[1],
        width: s[2],
      });
    });
    return out;
  }
  function paintChartLevels() {
    if (!S.chart) return;
    paintFamilies();
    S.chart.setLevels(levelList());
    // the band is yesterday's value area as served, as the reference draws it; today's are lines
    var pd = S.fam.prior_day !== 0 && S.levels && S.levels.prior_value_area;
    S.chart.setValueArea(pd ? pd.low : null, pd ? pd.high : null);
    // the session volume profile on the left edge: value-area bins brighter (the served flag), its
    // served POC marked across it
    var vp = S.fam.volume_profile !== 0 && S.levels && S.levels.volume_profile;
    var P = S.chart.palette(),
      alpha = window.EdTvChart.alpha;
    S.chart.setVolumeProfile(
      vp
        ? vp.bins.map(function (b) {
            return {
              price: b[0],
              value: b[1],
              color: b[2] ? alpha(P.accent, 0.38) : alpha(P.ink3, 0.2),
            };
          })
        : [],
      vp ? vp.max_volume : null,
      vp && vp.poc != null ? { price: vp.poc, label: vp.poc_label, color: P.warn } : null,
    );
    var vwap = S.fam.vwap && S.levels && S.levels.vwap_series;
    S.chart.setVwap(vwap ? vwap : []);
  }
  function paintChartOverlays() {
    if (!S.chart || !S.bars.length) return;
    paintChartLevels();
    var P = S.chart.palette();
    // the served few (marker flag): each at its level's price and its time, numbered, named by its
    // served direction; the queue lists every event, and a marker and its entry are one served item
    var word = { up: "Crossed above", down: "Crossed below" };
    S.chart.setMarkers(
      queueItems()
        .filter(function (q) {
          return q.marker;
        })
        .map(function (q) {
          return {
            id: q.key,
            time: q.ts,
            price: q.price,
            num: q.n,
            text: word[q.dir] || "",
            color: q.dir === "up" ? P.up : P.down,
            meta: q.key,
          };
        }),
      function (key) {
        selectItem(key, false);
      },
    );
  }

  // ------------------------------------------------------------------ attention queue
  function queueItems() {
    return S.events ? S.events.items : [];
  } // served, ordered, numbered
  function paintQueue() {
    var host = $("tdmQueue");
    if (!host) return;
    var items = queueItems();
    S.queue = items;
    $("tdmQueueCount").textContent = items.length ? String(items.length) : "";
    // the chart's markers with no bar to stand on, counted and worded by the desk panel
    $("tdmQueueOff").textContent = S.events ? S.events.markers_off_chart_text : "";
    if (S.events === undefined) {
      host.innerHTML = '<div class="tdm-empty">Loading ' + esc(shown()) + " events…</div>";
      return;
    }
    if (!items.length) {
      host.innerHTML =
        '<div class="tdm-empty">Nothing in the ' +
        esc(windowLabel()) +
        ". Level crosses, wall breaches and book size walls land here.</div>";
      return;
    }
    host.innerHTML = items
      .map(function (q) {
        return (
          '<button type="button" class="tdm-q ' +
          (q.warn ? "warn" : q.dir === "up" ? "up" : q.dir === "down" ? "dn" : "") +
          (q.key === S.sel ? " sel" : "") +
          '" data-q="' +
          esc(q.key) +
          '">' +
          '<span class="tdm-q-n">' +
          (q.n || "•") +
          "</span>" +
          '<span class="tdm-q-b"><span class="tdm-dom">' +
          esc(q.dom) +
          '</span><span class="tdm-q-t">' +
          esc(q.title) +
          "</span>" +
          '<span class="tdm-q-d">' +
          esc(q.detail) +
          "</span>" +
          '<span class="tdm-q-m">' +
          esc(q.src) +
          " · " +
          (q.time_ct == null ? "time not reported" : esc(q.time_ct)) +
          "</span></span></button>"
        );
      })
      .join("");
  }
  function selectItem(key, scroll) {
    S.sel = key;
    paintQueue();
    var el = document.querySelector('#tdmQueue [data-q="' + key + '"]');
    if (el) el.scrollIntoView({ block: "nearest" });
    var q = S.queue.filter(function (x) {
      return x.key === key;
    })[0];
    if (S.chart) S.chart.selectMarker(key); // the entry's own marker, drawn larger
    if (scroll && q && q.marker && S.chart) S.chart.scrollToTime(q.ts);
  }

  // ------------------------------------------------------------------ cards
  // the options lean of the Options Book at the expiry chosen, else the front one (the
  // `option_book:desk` panel, its expiry served), its gauge drawn as the Book view draws it
  // (EdOptionLean); with nothing to draw, why
  function paintLean(card) {
    var host = card.querySelector(".tdm-lean"),
      b = S.optBook;
    if (!b || b.available === false) {
      host.innerHTML =
        '<div class="tdm-plot-none">Options lean: ' +
        esc(b ? b.reason : noneText(b, "options book", "")) +
        "</div>";
      return;
    }
    host.innerHTML =
      '<div class="tdm-lean-h"><span>Options lean</span><span>' +
      esc(b.expiry) +
      " · " +
      (b.book_state == null ? "no book" : "books " + esc(b.book_state)) +
      "</span></div>" +
      window.EdOptionLean.html(b, true);
  }
  // a card's facts: one compact line of served values
  function row(k, v, cls) {
    return '<span class="tdm-r">' + esc(k) + ' <b class="' + (cls || "") + '">' + v + "</b></span>";
  }
  function state(el, txt, cls) {
    var s = el.querySelector(".tdm-state");
    s.textContent = txt;
    s.className = "tdm-state " + (cls || "");
  }
  function src(el, html) {
    el.querySelector(".tdm-src").innerHTML = html;
  }
  // Each card's chart of served series, drawn by the drawing module (EdDraw.sparkline); with no
  // point to draw, the card's reason.
  function spark(card, sets, caption, reason) {
    var box = card.querySelector(".tdm-chartbox");
    box.querySelector("figcaption").textContent = caption;
    var plot = box.querySelector(".tdm-plot");
    var W = 260,
      H = 64,
      svg = window.EdDraw.sparkline(sets, W, H);
    plot.innerHTML =
      svg == null
        ? '<div class="tdm-plot-none">' + esc(reason) + "</div>"
        : '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none">' + svg + "</svg>";
  }
  function paintCards() {
    var m = S.micro,
      t = S.terrain,
      c;
    paintLiqSoon();
    // ORDER FLOW — what Schwab reports of the trading: session volume, the last trade, the top of
    // book and the level crosses. Schwab sends no trade side, so none is claimed.
    c = $("tdmCardFlow");
    if (c) {
      var q = S.quotes[window.EdShell.getState().key],
        tob = m && m.top_of_book;
      var cc = S.events ? S.events.cross_counts : null; // served for the window
      // Schwab's values with Schwab's trade time; the outage stays beside that time, and the feed state beside them
      state(
        c,
        S.pushDown ? S.pushDown : !q ? "WAITING" : q.feed_live ? "SESSION VOLUME" : q.feed_label,
        q && q.feed_live && !S.pushDown ? "" : "warn",
      );
      c.querySelector(".tdm-hero").innerHTML =
        q && q.total_volume_text != null
          ? esc(q.total_volume_text) + " <small>shares, Schwab TOTAL_VOLUME</small>"
          : "";
      // Schwab's trade time stands when the feed is down; OFFLINE is the card's state, and the
      // outage stays beside the time instead of replacing it.
      var tradeWhen = q && q.trade_time_ct != null ? "last trade " + esc(q.trade_time_ct) : null;
      var tradeWhy = !q
        ? "no price row yet"
        : q.outage
          ? esc(q.outage)
          : tradeWhen
            ? null
            : "no trade sent";
      src(
        c,
        "Schwab LEVELONE · " +
          (tradeWhen && tradeWhy ? tradeWhen + " · " + tradeWhy : tradeWhen || tradeWhy),
      );
      c.querySelector(".tdm-rows").innerHTML =
        row("Last trade size", orDash(q && q.last_size_text)) +
        row(
          "Top of book",
          tob ? orDash(tob.bid_size_text) + " × " + orDash(tob.ask_size_text) : "-",
        ) +
        row(
          "Crosses (" + esc(windowLabel()) + ")",
          cc ? cc.up + " up · " + cc.down + " down" : "-",
        );
    }
    // OPTIONS POSITIONING — full-chain terrain
    c = $("tdmCardOpt");
    if (c) {
      if (!t || why(t)) {
        state(c, t === undefined ? "LOADING" : "UNAVAILABLE", t === undefined ? "" : "warn");
        c.querySelector(".tdm-hero").innerHTML = "";
        src(c, "Schwab option chain · " + (t === undefined ? "loading…" : esc(why(t))));
        c.querySelector(".tdm-rows").innerHTML = "";
      } else {
        // the served regime word, and its tone from the one regime table (ed-gamma-panels.js)
        var reg = t.regime ? String(t.regime) : null;
        var rm = reg != null ? window.EdGammaRegime[reg] : null;
        state(
          c,
          reg != null ? reg.replace(/_/g, " ") : "-",
          t.levels_state !== "LIVE" ? "warn" : rm ? rm.tone : "",
        );
        var ng = t.net_gex_at_spot; // absent is uncoloured, never read as 0
        c.querySelector(".tdm-hero").innerHTML =
          '<span class="' +
          window.EdDraw.bySign(ng, "up", "dn", "") +
          '">' +
          orDash(t.net_gex_at_spot_text) +
          "</span> <small>net dealer gamma at spot, per 1%</small>";
        src(c, "Schwab option chain · " + esc(chainAgeLabel(t)));
        c.querySelector(".tdm-rows").innerHTML =
          row("Call wall", orDash(t.call_wall_text), "up") +
          row("Put wall", orDash(t.put_wall_text), "dn") +
          row("Γ flip", orDash(t.gamma_flip_text)) +
          (t.flip_note != null ? row("Γ flip note", esc(t.flip_note)) : "") +
          row("P/C OI", orDash(t.pcr_all_text)) +
          row("Max pain", orDash(t.max_pain_text)) +
          row("Contracts", orDash(t.contracts_used_text));
      }
      paintLean(c);
    }
    // VOLATILITY
    c = $("tdmCardVol");
    if (c) {
      var vixC = window.EdShell.marketContext().filter(function (c) {
        return c.volatility; // served: the index this card shows
      })[0];
      var vix = vixC && S.quotes[vixC.key];
      state(
        c,
        t === undefined ? "LOADING" : !t || why(t) ? "UNAVAILABLE" : "",
        t === undefined || (t && !why(t)) ? "" : "warn",
      );
      src(c, "Schwab option chain · " + (!t || why(t) ? "-" : esc(chainAgeLabel(t))));
      c.querySelector(".tdm-rows").innerHTML =
        row("ATR daily", orDash(t && t.atr_daily_text)) +
        row("ATR weekly", orDash(t && t.atr_weekly_text)) +
        row("ATR monthly", orDash(t && t.atr_monthly_text)) +
        row(vixC.display, vixText(vix, vixC.display));
    }
    paintCardCharts();
  }
  // ------------------------------------------------------------------ liquidity card
  // The served order-imbalance readout (the book panel's `readout`): every number,
  // word, sentence and flag is the server's; the card picks the venue and depth to show and places
  // the dots, bars and lines on its boxes.
  var LIQ_NAME = { NYSE_BOOK: "NYSE", NASDAQ_BOOK: "Nasdaq", COMPOSITE: "Composite" };
  function liqKey() {
    return S.liqVenue === "COMPOSITE" ? "COMPOSITE" : window.EdShell.getState().bookVenue;
  }
  // a served tilt's colour on the card (bids green, offers red, balanced gold) and its arrow on
  // the agreement strip, by the tilt's name as served (order_flow.TILT_WORDS)
  var TILT_TONE = { BID_HEAVY: "bid", BALANCED: "bal", OFFER_HEAVY: "ask" };
  var TILT_ARROW = { BID_HEAVY: "up", BALANCED: "", OFFER_HEAVY: "dn" };
  function liqLeft(pct) {
    return window.EdDraw.centredLeft(pct) + "%";
  }
  function liqSpark(w) {
    var d = window.EdDraw.centredPath(w.values, w.step, w.seconds, 96, 14);
    // each served lean's colour; null (no value known in the window) is the neutral one
    var col = { BID_HEAVY: "#3fb950", OFFER_HEAVY: "#f85149", MIXED: "#c9a227", null: "#8fa1c4" }[
      w.lean
    ];
    return (
      '<svg viewBox="0 0 96 28" preserveAspectRatio="none"><line x1="0" y1="14" x2="96" y2="14" stroke="#2c3d63"/>' +
      (d
        ? '<path d="' +
          d +
          '" fill="none" stroke="' +
          col +
          '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>'
        : "") +
      "</svg>"
    );
  }
  function liqBar(side, label, text, shares, total) {
    // shares not sent: no bar; a total of 0 shares: an empty track
    var fill =
      window.EdDraw.strength(shares, total) == null
        ? ""
        : '<i class="' +
          side +
          '" style="width:' +
          window.EdDraw.barWidth(shares, total) +
          '%"></i>';
    return (
      '<div class="liq-bar-h"><span>' +
      label +
      '</span><div class="liq-track">' +
      fill +
      "</div><b>" +
      esc(text == null ? "-" : text) +
      "</b></div>"
    );
  }
  function liqSpans(rd, view) {
    var s = function (k, side) {
      return esc(orDash(rd.venues[k].views[view]["span_" + side + "_text"]));
    };
    return (
      "Top-" +
      (view === "weighted" ? "5" : view) +
      " spans, bid / ask: NYSE " +
      s("NYSE_BOOK", "bid") +
      " / " +
      s("NYSE_BOOK", "ask") +
      " · Nasdaq " +
      s("NASDAQ_BOOK", "bid") +
      " / " +
      s("NASDAQ_BOOK", "ask")
    );
  }
  // the detail panel over the card, opened from the headline
  function liqDetail(rd, key) {
    var d = rd.detail,
      p = function (t) {
        return t == null ? "" : "<p>" + esc(t) + "</p>";
      };
    return (
      '<div class="liq-detail liq-keep"><div class="liq-lbl"><span>DETAIL</span><button type="button" class="scbtn" data-liqclose>Close</button></div>' +
      p(d.weights) +
      p(d.tilt) +
      (key === "COMPOSITE" ? p(d.construction) : "") +
      p(d.spans) +
      p(liqSpans(rd, S.liqView)) +
      p(d.books) +
      "</div>"
    );
  }
  function paintLiq() {
    var c = $("tdmCardLiq");
    if (!c) return;
    S.liqPaints++;
    // the next second is held: a push in it paints when it ends (paintLiqSoon), no clock read
    clearTimeout(S.liqHold);
    S.liqHold = setTimeout(function () {
      S.liqHold = null;
      if (S.liqPending) {
        S.liqPending = false;
        paintLiq();
      }
    }, 1000);
    var m = S.micro,
      rd = m && m.readout,
      key = liqKey(),
      view = S.liqView;
    c.classList.toggle("liq-composite", key === "COMPOSITE");
    // the stock's own book, never an option's: its ticker's shares (the exchange is the lit
    // venue button beside it); the title's place fits no more on the 1920×950 Desk
    $("tdmLiqTitle").textContent = orDash(m && m.ticker) + " shares";
    c.querySelector("[data-liqvenue]").classList.toggle("on", key === "COMPOSITE");
    // the depth switch, first on the card whatever it shows
    var depth =
      '<div class="liq-depth"><small>Depth: price levels per side, not timeframes</small><span>' +
      [
        ["weighted", "Weighted"],
        ["1", "Top 1"],
        ["3", "Top 3"],
        ["5", "Top 5"],
      ]
        .map(function (d) {
          return (
            '<button type="button" class="scbtn' +
            (d[0] === view ? " on" : "") +
            '" data-liqview="' +
            d[0] +
            '">' +
            d[1] +
            "</button>"
          );
        })
        .join("") +
      "</span></div>";
    var body = c.querySelector(".liq-body"),
      r = rd && rd.venues[key];
    body.classList.toggle("stale", !!(r && !r.live && r.status !== "no_book"));
    if (!r) {
      src(c, m === undefined ? "loading…" : "the program could not produce the book");
      body.innerHTML =
        depth +
        '<div class="liq-none">' +
        (m === undefined
          ? "Loading…"
          : "UNAVAILABLE<p>The program could not produce the book</p>") +
        "</div>";
      return;
    }
    src(c, esc(r.source_text));
    if (r.no_number_text) {
      body.innerHTML =
        depth +
        '<div class="liq-none">' +
        esc(r.no_number_head) +
        "<p>" +
        esc(r.no_number_text) +
        "</p></div>";
      return;
    }
    var v = r.views[view],
      one = r.status === "one_sided",
      tone = one || !v.tilt ? "" : TILT_TONE[v.tilt];
    // laid out as the other cards: the switch, the state and its number, the chart (the bars) and
    // its caption, the three gauges, then the facts
    var h =
      depth +
      '<div class="liq-now liq-keep"><div class="liq-lbl liq-keep"><span>' +
      (view === "weighted" ? "WEIGHTED TOP-5 HEADLINE" : "TOP " + view + " HEADLINE") +
      "</span>" +
      (r.touch_flag ? '<span class="liq-pill">' + esc(r.touch_flag) + "</span>" : "") +
      (r.live ? "" : '<span class="liq-pill">BOOK ' + esc(r.feed_label) + "</span>") +
      "</div>" +
      (one
        ? '<div class="liq-hl"><span class="liq-word">ONE-SIDED</span><span class="liq-pct">-</span></div>'
        : '<div class="liq-hl" data-liqdetail title="Open the detail"><span class="liq-word ' +
          tone +
          '">' +
          esc(orDash(v.side_word)) +
          "</span>" +
          '<span class="liq-pct ' +
          tone +
          '">' +
          esc(orDash(v.pct_text)) +
          "</span></div>" +
          (v.divergence ? '<div class="liq-flag">' + esc(v.divergence) + "</div>" : "")) +
      "</div>" +
      // the side Schwab sent levels for fills its track; a missing side draws no bar and "-"
      '<figure class="tdm-chartbox"><div class="liq-bars">' +
      liqBar("bid", "Bids", v.bid_text, v.bid_total, one ? v.bid_total : v.total_depth) +
      liqBar("ask", "Asks", v.ask_text, v.ask_total, one ? v.ask_total : v.total_depth) +
      "</div>" +
      '<figcaption><span class="liq-sent">' +
      esc(one ? r.one_sided_text : orDash(v.sentence)) +
      "</span>" +
      (one
        ? ""
        : ' <span class="liq-line">Difference: ' +
          esc(orDash(v.difference_text)) +
          " shares · Total depth: " +
          esc(orDash(v.total_text)) +
          " shares</span>") +
      "</figcaption></figure>" +
      (rd.auction_text ? '<div class="liq-flag liq-keep">' + esc(rd.auction_text) + "</div>" : "") +
      '<div class="liq-gr"><div><div class="liq-lbl"><span>VENUES</span></div>' +
      '<div class="liq-strip">' +
      ["NYSE_BOOK", "NASDAQ_BOOK", "COMPOSITE"]
        .map(function (k) {
          var p = rd.venues[k].views[view].pct;
          return p == null
            ? ""
            : '<i class="liq-dot ' +
                k +
                (k === key ? " sel" : "") +
                '" style="left:' +
                liqLeft(p) +
                '" title="' +
                LIQ_NAME[k] +
                " " +
                esc(rd.venues[k].views[view].pct_text) +
                '"></i>';
        })
        .join("") +
      "</div>" +
      (rd.disagree[view] ? '<span class="liq-pill">VENUES DISAGREE</span>' : "") +
      "</div>" +
      '<div><div class="liq-lbl"><span>AT THE TOUCH</span><b>' +
      esc(orDash(r.touch_text)) +
      "</b></div>" +
      '<div class="liq-gauge">' +
      (r.touch_pct == null ? "" : '<i style="left:' + liqLeft(r.touch_pct) + '"></i>') +
      "</div></div>" +
      '<div><div class="liq-lbl"><span>LEAN</span><span class="liq-pill plain">◷ ' +
      esc(v.held_text || "HELD -") +
      "</span></div>" +
      (v.lean
        ? '<div class="liq-lean"><span>2m</span>' +
          liqSpark(v.lean["2m"]) +
          "<span>5m</span>" +
          liqSpark(v.lean["5m"]) +
          "</div>"
        : "") +
      (v.flips_2m != null
        ? '<span class="liq-pill">' + v.flips_2m + " flips in 2 min</span>"
        : "") +
      "</div></div>" +
      '<div class="tdm-rows liq-facts liq-keep">' +
      (r.levels_text ? '<span class="tdm-r">' + esc(r.levels_text) + "</span>" : "") +
      (r.dedup_partial_text && !one
        ? '<span class="tdm-r">' + esc(r.dedup_partial_text) + "</span>"
        : "") +
      '<span class="tdm-r">Green NYSE · Red Nasdaq · Gold Composite · White ring marks the selected venue</span>' +
      '<span class="tdm-r">' +
      liqSpans(rd, view) +
      "</span>" +
      '<span class="tdm-r">NYSE + Nasdaq only — not the whole market · Book ' +
      esc(orDash(r.book_time_ct)) +
      "</span></div>" +
      (S.liqDetail ? liqDetail(rd, key) : "");
    body.innerHTML = h;
  }
  // paints at most once a second; the reads stay on the pushes
  function paintLiqSoon() {
    if (S.liqHold) {
      S.liqPending = true;
      return;
    }
    paintLiq();
  }

  // what a card says with nothing to draw: not sent yet (undefined), not produced by the program
  // (null), the served error, or the served answer holding nothing
  function noneText(x, what, none) {
    if (x === undefined) return "loading…";
    if (x === null) return "the program could not produce the " + what;
    return why(x) || none;
  }
  function paintCardCharts() {
    if (!S.chart) return;
    var P = S.chart.palette(),
      t = S.terrain,
      c;
    var fb = S.flowBars,
      served = t && !why(t); // a card draws only an answer
    if ((c = $("tdmCardFlow"))) {
      spark(
        c,
        fb
          ? [
              {
                ys: fb.map(function (b) {
                  return b.v;
                }),
                kind: "bars",
                color: P.ink3,
                colors: fb.map(function (b) {
                  return window.EdDraw.bySign(b.chg, P.up, P.down, P.ink3);
                }),
              },
            ]
          : [],
        "Volume per 1-minute bar, last hour · green up, red down",
        noneText(fb, "bars", "no 1-minute bars for this symbol"),
      );
    }
    if ((c = $("tdmCardOpt"))) {
      spark(
        c,
        served
          ? [
              {
                ys: Object.keys(t.pcr_by_expiry).map(function (k) {
                  return t.pcr_by_expiry[k];
                }),
                color: P.research,
                kind: "line",
              },
            ]
          : [],
        "Put/call open interest by expiry, nearest first",
        noneText(t, "terrain", "no expiry carries open interest"),
      );
    }
    if ((c = $("tdmCardVol"))) {
      spark(
        c,
        served
          ? [
              {
                ys: Object.keys(t.atm_iv_pct_by_expiry).map(function (k) {
                  return t.atm_iv_pct_by_expiry[k];
                }),
                color: P.accent,
                kind: "line",
              },
            ]
          : [],
        "ATM implied vol by expiry, nearest first",
        noneText(t, "terrain", "no expiry has both ATM legs priced"),
      );
    }
  }

  // ------------------------------------------------------------------ agreement (server labels only)
  function paintAgreement() {
    var host = $("tdmAgree");
    if (!host) return;
    var m = S.micro,
      t = S.terrain,
      l = S.liq;
    // the Liquidity card's served side word, for its venue and depth
    var lv = m && m.readout && m.readout.venues[liqKey()],
      lt = lv && lv.views[S.liqView] && lv.views[S.liqView].tilt;
    var cells = [
      [
        "LIQUIDITY",
        lt ? lv.views[S.liqView].side_word.toLowerCase() : "No book",
        lt ? TILT_ARROW[lt] : "",
      ],
      [
        "VALUE",
        l && l.summary ? String(orDash(l.summary.value_state)).replace(/_/g, " ") : "-",
        "",
      ],
      [
        "VWAP",
        l && l.summary ? String(orDash(l.summary.vwap_relation)).replace(/_/g, " ") : "-",
        "",
      ],
      ["OPTIONS", t && !why(t) && t.regime ? window.EdGammaRegime[t.regime].t : "-", ""],
      [
        "GAMMA",
        t && t.flip_relation
          ? { ABOVE: "Above Γ flip", AT: "At Γ flip", BELOW: "Below Γ flip" }[t.flip_relation] +
            notLive(t)
          : "-",
        t && t.flip_relation === "ABOVE" ? "up" : t && t.flip_relation === "BELOW" ? "dn" : "",
      ],
    ];
    host.innerHTML =
      cells
        .map(function (c) {
          return (
            '<div class="tdm-ag"><span>' +
            c[0] +
            '</span><b class="' +
            c[2] +
            '">' +
            esc(c[1]) +
            "</b></div>"
          );
        })
        .join("") +
      '<div class="tdm-ag tdm-ag-note">Each domain\'s own served label. No combined agreement score is produced yet.</div>';
  }

  // ------------------------------------------------------------------ header trust + footer
  function pill(lbl, val, cls, title) {
    return (
      '<span class="tdm-pill ' +
      (cls || "") +
      '" title="' +
      esc(title || "") +
      '"><i></i>' +
      esc(lbl) +
      " <b>" +
      esc(val) +
      "</b></span>"
    );
  }
  function paintTrust() {
    var host = $("tdmTrust");
    if (!host) return;
    var q = S.quotes[window.EdShell.getState().key],
      t = S.terrain,
      m = S.micro,
      L = S.levels;
    var h = "";
    h += S.pushDown
      ? pill("PRICE", S.pushDown, "bad", "daemon price socket")
      : q
        ? pill("PRICE", q.feed_label, q.feed_live ? "ok" : "bad", "daemon price socket")
        : pill("PRICE", "WAITING", "warn", "no price row yet for this symbol");
    h +=
      m === undefined
        ? pill("BOOK", "…", "")
        : !m
          ? pill("BOOK", "FAILED", "bad")
          : m.status === "no_book"
            ? pill("BOOK", "NONE", "warn", "no " + m.venue)
            : pill(
                "BOOK",
                bookAgeLabel(
                  m,
                  m.ages.book_stale === false
                    ? m.book_age_text
                    : m.ages.book_stale
                      ? m.book_feed_label
                      : "AGE UNKNOWN",
                ),
                m.ages.book_stale === false ? "ok" : "bad",
              );
    // the session levels snapshot's served time and age
    var levelWord = L && L.snapshot_age_text != null ? L.snapshot_age_text : "-";
    var levelWhen = L && L.snapshot_time_ct != null ? L.snapshot_time_ct : null;
    var levelShown = levelWhen != null ? levelWhen + " · " + levelWord : levelWord;
    h +=
      L === undefined
        ? pill("LEVELS", "…", "")
        : !L
          ? pill("LEVELS", "FAILED", "bad")
          : pill(
              "LEVELS",
              levelShown,
              L.degraded && L.degraded.length ? "warn" : "ok",
              "session levels snapshot age",
            );
    var gammaWhen = t ? chainAgeLabel(t) : null;
    var gammaWhy = t && t.levels_stale_reason ? t.levels_stale_reason : null;
    h +=
      t === undefined
        ? pill("GAMMA", "…", "")
        : why(t)
          ? pill("GAMMA", "DOWN", "bad", why(t))
          : pill("GAMMA", gammaWhen, t.levels_state === "LIVE" ? "ok" : "warn", gammaWhy);
    host.innerHTML = h;
  }
  function paintFooter() {
    var host = $("tdmFoot");
    if (!host) return;
    var t = S.terrain,
      m = S.micro,
      L = S.levels;
    host.innerHTML = [
      "Bars: <b>" + (S.bars.length ? "streamed 1m bars" : "-") + "</b>",
      "Book: <b>" + esc(orDash(m && m.provenance && m.provenance.book_source)) + "</b>",
      "Levels: <b>" + esc(orDash(L && L.bar_source)) + "</b>",
      "Options: <b>" +
        esc(
          t && !why(t)
            ? (t.chain_basis == null ? "-" : t.chain_basis) +
                " chain · " +
                (t.strikes_used == null ? "-" : t.strikes_used) +
                " strikes · " +
                orDash(t.contracts_used_text) +
                " contracts"
            : "-",
        ) +
        "</b>",
      "Clock: <b>Central</b>",
    ]
      .map(function (x) {
        return "<span>" + x + "</span>";
      })
      .join("");
  }
  // The shell header already carries the symbol, price, change and CT clock; this page adds
  // the index context and the data-trust row beside it.
  function vixText(vix, name) {
    if (!vix || vix.spot == null) return "waiting for the " + esc(name) + " stream";
    var txt =
      esc(vix.spot_disp) + (vix.chg_pct_text != null ? " (" + esc(vix.chg_pct_text) + ")" : ""); // served
    return vix.trade_time_ct != null ? txt + " · last trade " + esc(vix.trade_time_ct) : txt;
  }
  function paintHeader() {
    window.EdShell.marketContext().forEach(function (c) {
      // the served context symbols
      var el = $("tdmIdx" + c.display);
      if (!el) return;
      var r = S.quotes[c.key];
      if (!r) el.title = "waiting for the " + c.display + " stream";
      else if (r.trade_time_ct != null) el.title = "last trade " + r.trade_time_ct;
      else if (r.outage != null) el.title = r.outage;
      else el.title = "no trade sent";
      el.innerHTML =
        "<span>" +
        c.display +
        "</span><b>" +
        esc(orDash(r && r.spot_disp)) + // served: "7425.50"
        "</b>" +
        (r && r.chg_pct != null
          ? '<em class="' +
            window.EdDraw.bySign(r.chg_pct, "up", "dn", "") +
            '">' +
            esc(orDash(r.chg_pct_text)) + // served: "+0.57%"
            "</em>"
          : "") +
        (r && r.trade_time_ct != null
          ? "<span> · last trade " + esc(r.trade_time_ct) + "</span>"
          : "");
    });
  }

  // ------------------------------------------------------------------ lifecycle
  function start() {
    askPanels();
    if (!onDesk()) return;
    buildToolbar();
    if (!ensureChart()) return;
    var tk = window.EdShell.getState().ticker;
    if (!tk) return;
    if (tk !== S.ticker) {
      S.ticker = tk;
      S.bars = []; // undefined = not sent YET (loading); null = not produced
      S.levels = S.terrain = S.micro = S.events = S.liq = S.optBook = S.flowBars = undefined;
      S.sel = null;
      clearChart();
      paintHeader();
      paintQueue();
      paintCards();
      paintTrust();
      paintAgreement();
      paintFooter();
    }
  }
  function init() {
    if (!$("tdmMap")) return;
    document.addEventListener("ed:view", start);
    document.addEventListener("ed:ticker", start);
    document.addEventListener("ed:book_venue", askPanels); // the book is the venue's
    document.addEventListener("ed:scope", askPanels); // the Options Book's window is the scope's
    document.addEventListener("ed:expiry", askPanels); // its expiry is the one chosen
    document.addEventListener("ed:panel", function (e) {
      if (onDesk()) takePanel(e.detail);
    });
    // Every streamed price row: header + indices. The chart moves only on a completed bar.
    // the header's word while the daemon's push is down (WAITING, OFFLINE): the last row's
    // verdict is not the state now; the next row ends it
    document.addEventListener("ed:price_push_down", function (e) {
      S.pushDown = e.detail.label;
      if (onDesk()) {
        paintTrust();
        paintCards();
      }
    });
    window.addEventListener("ed:quote_tick", function (e) {
      var q = e.detail;
      if (!q || !q.ticker) return;
      if (q.ticker === window.EdShell.getState().key) S.pushDown = null; // the selected price's own row ends it, as in the header
      S.quotes[q.ticker] = q;
      if (!onDesk()) return;
      paintHeader();
      if (q.ticker === window.EdShell.getState().key) {
        paintTrust();
        if (S.chart)
          S.chart.setLivePrice(q.spot, q.trade_age_text, q.spot != null ? q.trade_time_ct : null);
        paintCards(); // the Order Flow card's Schwab fields, on every row
      }
    });
    $("tdmQueue").addEventListener("click", function (e) {
      var b = e.target.closest("[data-q]");
      if (b) selectItem(b.getAttribute("data-q"), true);
    });
    // the Liquidity card's venue and depth: NYSE and NASDAQ are the shell's book switch (its
    // ed:book_venue reads the book again), COMPOSITE is this card's
    $("tdmCardLiq").addEventListener("click", function (e) {
      var b = e.target.closest(
        "[data-liqvenue], .bookvenue [data-venue], [data-liqview], [data-liqdetail], [data-liqclose]",
      );
      if (!b) return;
      if (b.hasAttribute("data-liqdetail") || b.hasAttribute("data-liqclose"))
        S.liqDetail = b.hasAttribute("data-liqdetail");
      else if (b.hasAttribute("data-liqview")) {
        S.liqView = b.getAttribute("data-liqview");
        sset("ed.desk.liqview", S.liqView);
      } else {
        S.liqVenue = b.hasAttribute("data-liqvenue") ? "COMPOSITE" : "BOOK";
        sset("ed.desk.liqvenue", S.liqVenue);
      }
      paintLiq();
      paintAgreement();
    });
    start();
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdTradeDeskMap = {
    state: function () {
      return {
        ticker: S.ticker,
        tf: S.tf,
        bars: S.bars.length,
        queue: S.queue.map(function (q) {
          return { key: q.key, n: q.n, marker: !!q.marker, ts: q.ts };
        }),
        sel: S.sel,
        chart: S.chart ? S.chart.state() : null,
        liqPaints: S.liqPaints,
      };
    },
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
