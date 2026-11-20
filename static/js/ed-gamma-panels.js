/* Ed Console — Options/Gamma supporting panels. PRESENTATION ONLY.
   Key Levels rail  <- the page's socket      (the `terrain:levels` panel, the published levels)
   GEX by Strike    <- the page's socket      (the `strikes:gbs` panel, per-strike net_gex_1pct$)
   Strike Detail    <- the page's socket      (the `chain:detail` panel, vendor per-contract OI/vol/greeks)
   Vanna / Charm    <- the page's socket      (the `vanna` / `charm` panels, per-strike net)
   Options Book     <- the page's socket      (the `option_book:book` panel, books, volume, lean)
   No trading semantics are computed here. Bar scaling is visual normalisation over the
   already-computed displayed values; distances/positions are formatting only. */
(function () {
  "use strict";

  function txt(id, v) {
    var e = document.getElementById(id);
    if (e) e.textContent = v;
  }
  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;

  // Delta/DEX and Open Interest fall back to displaying the SAME gamma `.sub-pane` (they have
  // no dedicated pane of their own -- showSubPane()'s fallback rule), which is where Key
  // Levels/GEX-by-Strike/PCR/the Options Flow tape all physically live. A 'gamma'-only check
  // would freeze all four panels on Delta/DEX or OI (a ticker switch there would leave the
  // PREVIOUS ticker's spot/flip/wall values) -- every check in this file recognizes all
  // three, exactly like ed-gamma.js's _isGammaFamilySubview.
  function isGamma() {
    var s = window.EdShell.getState();
    return (
      s.workspace === "options" &&
      (s.subview === "gamma" || s.subview === "dex" || s.subview === "oi")
    );
  }
  var ticker = window.EdShell.ticker;

  var REGIME = {
    LONG_GAMMA_CHOP: { t: "Dealer Γ +", c: "var(--ed-pos-ink)", tone: "up" },
    SHORT_GAMMA_TREND: { t: "Dealer Γ −", c: "var(--ed-warn)", tone: "dn" },
    UNAVAILABLE: { t: "unavailable", c: "var(--ed-ink-3)", tone: "" },
  };
  window.EdGammaRegime = REGIME;

  // ---------- Key Levels rail: the `terrain:levels` panel (push.terrain), sent on the page's
  // socket while a Gamma tab is on, at once and each time the levels change ----------
  var _levels,
    _levelsTicker = null; // the panel as last sent for the ticker on screen
  var _price; // the `levels:kl` panel as last sent for the ticker on screen
  function loadLevels() {
    if (!isGamma()) {
      window.EdShell.showPanel("terrain:levels", null);
      window.EdShell.showPanel("levels:kl", null);
      return;
    }
    if (_levelsTicker !== ticker()) {
      _levelsTicker = ticker();
      _levels = undefined;
      _price = undefined;
    }
    renderLevels(_levels);
    renderPriceLevels(_price);
    window.EdShell.showPanel("terrain:levels", {});
    window.EdShell.showPanel("levels:kl", { tf: "1" });
  }
  document.addEventListener("ed:panel", function (e) {
    if (e.detail.type === "levels:kl") {
      _price = e.detail;
      if (isGamma()) renderPriceLevels(_price);
    }
    if (e.detail.type !== "terrain:levels") return;
    _levels = e.detail;
    if (isGamma()) renderLevels(_levels);
  });
  // the card's price levels: each is the `levels` panel's own row of that id (push.levels.levels_payload),
  // its price as served; a row not sent, or a panel not sent or failed, reads '-'
  var PRICE_LEVELS = {
    PDH: "klPdh",
    PDL: "klPdl",
    PDC: "klPdc",
    VWAP: "klVwap",
  };
  function renderPriceLevels(d) {
    // d: the panel as sent; undefined: none yet for this ticker
    var sent = {};
    if (d !== undefined && d.failed == null)
      d.levels.forEach(function (r) {
        sent[r.id] = r.price_text;
      });
    Object.keys(PRICE_LEVELS).forEach(function (id) {
      txt(PRICE_LEVELS[id], orDash(sent[id]));
    });
  }
  function renderLevels(d) {
    // d: the panel as sent; undefined: none yet for this ticker
    var ids = [
      "klFlip",
      "klCall",
      "klPut",
      "klAbs",
      "klCallDelta",
      "klPutDelta",
      "klCallCharm",
      "klPutCharm",
      "klNet",
      "klRegime", // terrain's (Spot is the price row's)
      "kl0Flip",
      "kl0Call",
      "kl0Put",
      "kl0Abs",
      "kl0CallDelta",
      "kl0PutDelta",
      "kl0CallCharm",
      "kl0PutCharm",
    ];
    // nothing to draw: none sent yet ('-'), the program could not produce it, or no levels yet
    var why =
      d === undefined ? "-" : d.failed != null ? d.failed : d.error ? "terrain not ready" : null;
    paintPcr(why == null ? d : null);
    if (why != null) {
      // nothing current: no tooltip or colour of the last answer stays
      ids.forEach(function (id) {
        txt(id, "-");
        var el = document.getElementById(id);
        if (el) el.style.color = "";
      });
      txt("klSrc", why);
      txt("klFlipNote", "");
      var src0 = document.getElementById("klSrc");
      if (src0) {
        src0.title = "";
        src0.style.color = "";
      }
      var klb0 = document.getElementById("klBody");
      if (klb0) klb0.classList.add("recede");
      return;
    }
    txt("klFlip", orDash(d.gamma_flip_text));
    txt("klFlipNote", d.flip_note != null ? d.flip_note : ""); // served: the flip's note
    txt("klCall", orDash(d.call_wall_text));
    txt("klPut", orDash(d.put_wall_text));
    txt("klAbs", orDash(d.absolute_gamma_strike_text));
    txt("klCallDelta", orDash(d.call_delta_wall_text));
    txt("klPutDelta", orDash(d.put_delta_wall_text));
    txt("klCallCharm", orDash(d.call_charm_wall_text));
    txt("klPutCharm", orDash(d.put_charm_wall_text));
    var z = d.same_day_text; // served: each 0DTE level's text, none for a level not held
    txt("kl0Flip", orDash(z.gamma_flip));
    txt("kl0Call", orDash(z.call_wall));
    txt("kl0Put", orDash(z.put_wall));
    txt("kl0Abs", orDash(z.absolute_gamma_strike));
    txt("kl0CallDelta", orDash(z.call_delta_wall));
    txt("kl0PutDelta", orDash(z.put_delta_wall));
    txt("kl0CallCharm", orDash(z.call_charm_wall));
    txt("kl0PutCharm", orDash(z.put_charm_wall));
    // Net GEX / 1% move — signed $, coloured by sign (formatting only)
    var net = document.getElementById("klNet");
    if (net) {
      var v = d.net_gex_at_spot;
      net.textContent = orDash(d.net_gex_at_spot_text);
      net.style.color = window.EdDraw.bySign(v, "var(--ed-pos-ink)", "var(--ed-neg-ink)", "");
    }
    var reg = document.getElementById("klRegime");
    if (reg) {
      var rm = REGIME[d.regime] || { t: orDash(d.regime), c: "var(--ed-ink-2)" };
      reg.textContent = rm.t;
      reg.style.color = rm.c;
    }
    // the levels rail recedes while the served levels are STALE
    var klb = document.getElementById("klBody");
    if (klb) klb.classList.toggle("recede", d.levels_state === "STALE");
    // freshness / provenance line. The chain's time stands beside the mark. The mark is
    // unchanged when no chain time was sent.
    var src = document.getElementById("klSrc");
    function chainMarked(words) {
      var when = d.levels_time_ct != null ? d.levels_time_ct : null;
      if (when != null) return when + " · " + words;
      return words;
    }
    if (src) {
      // the served mark (levels_mark: the levels' state, or the price's while the levels are LIVE)
      // with the levels' age; the reason is disclosed in the tooltip, not as a paragraph
      src.textContent = chainMarked(
        d.levels_mark + (d.levels_age_text ? " · " + d.levels_age_text : ""),
      );
      src.title = d.levels_mark_reason == null ? "" : d.levels_mark_reason;
      src.style.color = d.levels_mark === "LIVE" ? "" : "var(--ed-stale)";
      // #5: terrain levels are AGGREGATE across expiries; if the workspace filters to one expiry,
      // disclose that these levels are still all-exp (never silently relabel them as selected-expiry).
      if (window.EdShell.getExpiry()) src.textContent += " · all-exp";
    }
  }

  // ---------- Put/Call OI and volume <- the terrain panel's pcr_by_expiry, pcr_volume_by_expiry (selected expiry, else the front one) ----------
  function expiryFilter() {
    return window.EdShell.getExpiry();
  }
  function paintPcr(d) {
    // the selected expiry, else the whole book -- both served on every terrain answer (TerrainSnapshot
    // fields); the page picks no expiry itself. A failed read (no d) is missing: "-"
    var ex = expiryFilter();
    var v = !d ? null : ex ? d.pcr_by_expiry_text[ex] : d.pcr_all_text;
    var vv = !d ? null : ex ? d.pcr_volume_by_expiry_text[ex] : d.pcr_volume_all_text;
    var scope = ex ? "exp " + ex : "all exp";
    txt("klPcr", orDash(v));
    txt("klPcrScope", "OI · " + scope);
    txt("klPcrVol", orDash(vv));
    txt("klPcrVolScope", "volume · " + scope);
  }

  // ---------- GEX by Strike: the `strikes:gbs` panel (server.strikes) the program sends on the
  // page's socket while a Gamma tab is on, in the window it asks (the scope and its pan), at once
  // and each time the levels change; nothing received yet for the ticker on screen is '-' ----------
  var _gbs; // the panel as last sent for the ticker on screen
  function loadGbs() {
    if (!isGamma()) {
      window.EdShell.showPanel("strikes:gbs", null);
      return;
    }
    if (_gbsPanTicker !== ticker()) {
      // a new ticker: its own window, and nothing of the last one's
      _gbsPan.centre = null;
      _gbsPan.shift = 0;
      _gbsPanTicker = ticker();
      _gbs = undefined;
      var host = document.getElementById("gbsBody");
      setGbsAsOf(null);
      if (host) window.EdShell.placeholder(host, "-");
    }
    window.EdShell.showPanel("strikes:gbs", window.EdShell.windowAtExpiry(_gbsPan));
  }
  function drawGbs() {
    var host = document.getElementById("gbsBody");
    if (host && isGamma() && _gbs !== undefined) renderGbs(host, _gbs);
  }
  document.addEventListener("ed:panel", function (e) {
    if (e.detail.type !== "strikes:gbs") return;
    _gbs = e.detail;
    drawGbs();
  });
  function setGbsAsOf(d) {
    var el = document.getElementById("gbsSrc");
    if (!el) return;
    if (!d) {
      el.innerHTML = "";
      return;
    }
    // the levels verdict the server serves (levels_state, its time and age); the badge formats it
    el.innerHTML = window.EdShell.asOfBadge({
      label: "terrain",
      state: d.levels_state,
      when: d.levels_time_ct,
      age: d.levels_age_text,
      reason: d.levels_stale_reason,
    });
  }
  // A per-strike bar list (GEX, vanna, charm by strike): the window of `rows` the server sent
  // ({strike, value, text, ...}, ascending), drawn highest strike first, each bar's length its
  // |value| against the served scale (view.max_abs). The strike labels pan the window
  // (wireStrikeAxis -> `reload`); a pan is never silent. `opts`: `top` html above the list,
  // `attrs(r)` and `cells(r)` a row's extra attributes and cells, `expiry` the served expiry the
  // rows are (a click selects the strike in it; none: every expiry's). Each row carries its served
  // marks (the strike at the price, the walls), each drawn as its class.
  function drawStrikeBars(host, rows, view, pan, reload, opts) {
    window.EdShell.panServed(pan, view.centre);
    var maxAbs = view.max_abs; // at least |v| for every v drawn
    var note =
      opts.top +
      (pan.centre != null
        ? '<div class="gbs-allexp">Panned to ' +
          view.centre_text +
          " · double-click a strike to follow the price</div>"
        : "") +
      (view.note ? '<div class="gbs-allexp">' + esc(view.note) + "</div>" : ""); // why not around the price
    var bars = "";
    rows
      .slice()
      .reverse()
      .forEach(function (r) {
        // a strike with no value is unknown: no bar, '-' (never a $0 bar)
        var k = r.strike,
          v = r.value;
        var w = window.EdDraw.barWidth(v, maxAbs),
          tone = window.EdDraw.bySign(v, "pos", "neg", "");
        bars +=
          '<div class="gbs-row' +
          r.marks
            .map(function (mk) {
              return " mark-" + mk.kind;
            })
            .join("") +
          '" data-strike="' +
          k +
          '"' +
          (opts.attrs ? opts.attrs(r) : "") +
          ">" +
          '<span class="gbs-k">' +
          r.strike_text +
          "</span>" +
          '<span class="gbs-track"><i class="gbs-bar ' +
          tone +
          '" style="width:' +
          w.toFixed(1) +
          '%"></i></span>' +
          '<span class="gbs-v ' +
          tone +
          '">' +
          esc(orDash(r.text)) +
          "</span>" +
          (opts.cells ? opts.cells(r) : "") +
          "</div>";
      });
    // the bars scroll in their own area; the -/0/+ axis is pinned at the foot
    host.innerHTML =
      '<div class="gbs-top">' +
      note +
      "</div>" +
      '<div class="gbs-scroll"><div class="gbs">' +
      bars +
      "</div></div>" +
      '<div class="gbs-scale"><span class="neg">−</span><span>0</span><span class="pos">+</span></div>';
    host.querySelectorAll(".gbs-row").forEach(function (rr) {
      // click a strike: every panel follows it
      rr.addEventListener("click", function () {
        window.EdShell.setStrike(Number(rr.getAttribute("data-strike")), opts.expiry);
      }); // the rows' own expiry; every expiry's row: null, no expiry
    });
    var firstRow = host.querySelector(".gbs-row");
    window.EdShell.wireStrikeAxis(
      host.querySelectorAll(".gbs-k"),
      host.querySelector(".gbs-scroll"),
      pan,
      firstRow ? firstRow.getBoundingClientRect().height : 0,
      reload,
    );
    var sr = host.querySelector(".gbs-row.mark-spot");
    if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: "center" });
  }

  // GEX by Strike shows the window the server sends (scope, and the operator's pan)
  var _gbsPan = window.EdShell.newPan(),
    _gbsPanTicker = null;

  function renderGbs(host, d) {
    if (d.failed != null || d.available === false) {
      // not produced, or a window it cannot draw: why
      setGbsAsOf(null);
      window.EdShell.placeholder(host, d.failed != null ? d.failed : d.reason);
      return;
    }
    setGbsAsOf(d);
    // the chosen expiry's rows (every expiry's with none chosen), as served
    var rows = d.today;
    if (!rows.length) {
      host.innerHTML =
        '<div class="placeholder"><div class="sm">' +
        "no banked per-strike gamma for this symbol</div></div>";
      return;
    }
    // yesterday's change per strike, of the same expiry, as served (migration.rows' change_text)
    var chg = new Map(
      d.migration.rows.map(function (m) {
        return [m.strike, m.change_text];
      }),
    );
    // rows: each strike's net GEX $ (value) and session volume with their texts; the volume is a
    // count, never coloured
    drawStrikeBars(host, rows, d.view, _gbsPan, loadGbs, {
      top: "",
      // a click selects the strike in the expiry these rows are (null: every expiry's)
      expiry: d.expiry,
      attrs: function (r) {
        return ' data-volume="' + (r.volume == null ? "" : r.volume) + '"';
      },
      cells: function (r) {
        return (
          '<span class="gbs-vol" title="session volume">' +
          esc(orDash(r.volume_text)) +
          "</span>" +
          '<span class="gbs-chg" title="net GEX change vs the previous session">' +
          esc(orDash(chg.get(r.strike))) +
          "</span>"
        );
      },
    });
    applyGbsHighlight(host);
  }
  function applyGbsHighlight(host) {
    host = host || document.getElementById("gbsBody");
    if (!host) return;
    var sel = window.EdShell.getState().selStrike;
    host.querySelectorAll(".gbs-row.gbs-sel").forEach(function (n) {
      n.classList.remove("gbs-sel");
    });
    if (sel == null) return;
    host.querySelectorAll('.gbs-row[data-strike="' + sel + '"]').forEach(function (n) {
      n.classList.add("gbs-sel");
    });
  }

  // ---------- Strike Detail ----------
  // the workspace expiry filter, else the selected strike's own expiry
  function strikeDetailExpiry() {
    var s = window.EdShell.getState();
    return expiryFilter() || s.selExpiry;
  }
  // The selected strike's contracts: the `chain:detail` panel (push.chain) the program sends on
  // the page's socket while a strike is selected, at its expiry (null: the chain's front one), at
  // once and each time a chain is priced. loadStrike() records the desired (strike, expiry); a
  // new strike at the same expiry is drawn from the chain already sent. A frame of an expiry no
  // longer desired (sent before the page asked another) is not drawn.
  var _sdDesired = { strike: null, expiry: null },
    _sd; // _sd: the panel as last sent
  function sdCurrent(d) {
    return !_sdDesired.expiry || d.failed != null || d.expiry === _sdDesired.expiry;
  }
  function drawStrike() {
    var host = document.getElementById("sdBody");
    if (!host || _sdDesired.strike == null || _sd === undefined || !sdCurrent(_sd)) return;
    if (_sd.failed != null) {
      setSdAsOf(null);
      window.EdShell.placeholder(host, _sd.failed);
      return;
    }
    renderStrike(host, _sd, _sdDesired.strike, _sdDesired.expiry);
  }
  function loadStrike(strike, expiry) {
    var was = _sdDesired.expiry;
    _sdDesired = { strike: strike, expiry: expiry };
    if (strike == null) {
      window.EdShell.showPanel("chain:detail", null);
      return;
    }
    if (was === expiry) drawStrike(); // the chain at this expiry is on hand
    window.EdShell.showPanel("chain:detail", { expiry: expiry });
  }
  document.addEventListener("ed:panel", function (e) {
    if (e.detail.type !== "chain:detail") return;
    _sd = e.detail;
    drawStrike();
  });
  function setSdAsOf(d) {
    var el = document.getElementById("sdSrc");
    if (!el) return;
    el.innerHTML = window.EdShell.chainScopeBadge(d);
  }
  function renderStrike(host, d, strike, expiry) {
    setSdAsOf(d);
    if (!d.ladder.length) {
      host.innerHTML =
        '<div class="placeholder"><div class="sm">' +
        esc(window.EdShell.chainEmptyText(d)) +
        "</div></div>";
      return;
    }
    // the served ladder's row at the selected strike (a strike Schwab sent, matched as sent)
    var sd = d.ladder.filter(function (r) {
        return r.strike === strike;
      })[0],
      call = sd ? sd.call : null,
      put = sd ? sd.put : null;
    txt("sdCtx", (sd ? sd.strike_text : "-") + (expiry ? " · " + esc(expiry.slice(5)) : ""));
    // a served text, or every digit Schwab sent (its Greeks)
    function cell(c, k) {
      var v = c ? c[k] : null;
      return v == null ? "-" : esc(String(v));
    }
    // GEX ($) column: per-side GEX$ is not served (computing it would be frontend math) -> "-"; the
    // NET row is this expiry's net GEX at this strike, served on the same chain panel --
    // the heatmap's own cell, not GEX-by-Strike's all-expiry total beside one expiry's contracts.
    var net = sd ? sd.net_gex : null; // served null: no surface value at this strike
    var netCls = window.EdDraw.bySign(net, "pos", "neg", "");
    host.innerHTML =
      '<table class="sd"><thead><tr><th>Type</th><th>OI</th><th>Vol</th><th>Gamma</th><th>GEX $</th><th>Delta</th><th>IV%</th></tr></thead><tbody>' +
      '<tr><td class="side c">Call</td><td>' +
      cell(call, "oi_text") +
      "</td><td>" +
      cell(call, "volume_text") +
      "</td><td>" +
      cell(call, "gamma") +
      '</td><td class="dim">-</td><td>' +
      cell(call, "delta") +
      "</td><td>" +
      cell(call, "iv_text") +
      "</td></tr>" +
      '<tr><td class="side p">Put</td><td>' +
      cell(put, "oi_text") +
      "</td><td>" +
      cell(put, "volume_text") +
      "</td><td>" +
      cell(put, "gamma") +
      '</td><td class="dim">-</td><td>' +
      cell(put, "delta") +
      "</td><td>" +
      cell(put, "iv_text") +
      "</td></tr>" +
      '<tr class="sd-net"><td class="side">Net</td><td>-</td><td>-</td><td>-</td><td class="' +
      netCls +
      '">' +
      esc(orDash(sd ? sd.net_gex_text : null)) +
      "</td><td>-</td><td>-</td></tr>" +
      '</tbody></table><div class="sd-src">vendor per-contract · net GEX$ this expiry · the chain</div>';
  }

  // A ticker switch drops Strike Detail's chain and its rendered content: ed-core.js's
  // setTicker() clears the SHARED selStrike (a fresh strike click is required before loadStrike
  // fires again), and the panel leaves the subscribe, so nothing of the old ticker is drawn
  // under the new one (AMD's values shown after a switch to NVDA); the Strike Detail
  // placeholder is cleared the instant the ticker changes.
  function resetStrikeDetailForTickerChange() {
    loadStrike(null, null);
    _sd = undefined;
    var host = document.getElementById("sdBody");
    if (host) {
      host.innerHTML =
        '<div class="placeholder"><div class="sm">Select a strike/expiry. ' +
        "OI · volume · gamma · delta · IV from the chain (vendor).</div></div>";
    }
  }

  // ---------- Vanna / Charm by strike: the same bar list (drawStrikeBars), each its own pan ----------
  // The program sends the panel on the page's socket (server.strike_bars)
  // while its tab is on, for the window it asks (the scope and its pan), at once and on each
  // change of the levels; nothing received yet for the ticker on screen is '-'.
  function _mkStrikeBar(kind, hostId, srcId) {
    function inSub() {
      var s = window.EdShell.getState();
      return s.workspace === "options" && s.subview === kind;
    }
    var pan = window.EdShell.newPan(),
      panTicker = null;
    function renderIt(host, d) {
      var src = document.getElementById(srcId);
      if (src) src.textContent = "";
      if (d.failed != null || !d.available) {
        // not produced, or nothing to draw: why
        window.EdShell.placeholder(host, d.failed != null ? d.failed : d.reason);
        return;
      }
      // vanna and charm are delta-shares (per vol point, per day), not dollars: no '$'
      drawStrikeBars(host, d.rows, d.view, pan, ask, { top: "", expiry: null }); // every expiry's rows
    }
    function ask() {
      if (!inSub()) {
        window.EdShell.showPanel(kind, null);
        return;
      }
      if (panTicker !== ticker()) {
        // a new ticker: its own window, and nothing of the last one's
        pan.centre = null;
        pan.shift = 0;
        panTicker = ticker();
        var host = document.getElementById(hostId);
        if (host) window.EdShell.placeholder(host, "-");
      }
      window.EdShell.showPanel(kind, window.EdShell.windowParams(pan));
    }
    document.addEventListener("ed:panel", function (e) {
      var host = document.getElementById(hostId);
      if (e.detail.type === kind && host && inSub()) renderIt(host, e.detail);
    });
    return ask;
  }
  var loadVanna = _mkStrikeBar("vanna", "vnBody", "vnSrc");
  var loadCharm = _mkStrikeBar("charm", "chmBody", "chmSrc");

  // ---------- Structures — contract-safety metadata ------
  // the chain's fields (multiplier/nonStandard/deliverables/settlementType/
  // exerciseType/expirationType/lastTradingDay/pennyPilot) that the Chain ladder never
  // surfaces -- one ladder row per row, both sides, no new computation, no second shape
  // (the same chain panel Chain and Strike Detail are sent).
  function inStructures() {
    var s = window.EdShell.getState();
    return s.workspace === "options" && s.subview === "structures";
  }
  function _flag(label, on) {
    return '<span class="st-flag' + (on ? " on" : "") + '">' + esc(label) + "</span>";
  }
  // NON-STD: Schwab's nonStandard flag, as sent (a non-standard, adjusted deliverable)
  function renderStructures(host, d) {
    var src = document.getElementById("stSrc");
    if (src) src.textContent = "";
    // served: one row per strike, high to low; an 'unavailable' chain answer carries none
    if (d.status !== "ok") {
      host.innerHTML =
        '<div class="placeholder"><div class="sm">' +
        esc(window.EdShell.chainEmptyText(d)) +
        "</div></div>";
      return;
    }
    // every ladder row (a second listing at a strike has its own), its contract-level fields
    // served once on the row (push.chain._series)
    var rows = d.ladder
      .map(function (r) {
        var s = r.series;
        var flags = [
          _flag("NON-STD", s.nonStandard === true),
          _flag("PENNY", s.pennyPilot === true),
        ].join("");
        return (
          '<tr><td class="side">' +
          r.strike_text +
          "</td>" +
          "<td>" +
          (s.multiplier == null ? "-" : s.multiplier) +
          "</td>" +
          "<td>" +
          esc(orDash(s.settlementType)) +
          "</td>" +
          "<td>" +
          esc(orDash(s.exerciseType)) +
          "</td>" +
          "<td>" +
          esc(orDash(s.expirationType)) +
          "</td>" +
          "<td>" +
          esc(orDash(s.last_trading_day_et)) +
          "</td>" +
          "<td>" +
          flags +
          "</td></tr>"
        );
      })
      .join("");
    host.innerHTML =
      '<div class="gbs-scroll"><table class="sd st-tbl">' +
      "<thead><tr><th>Strike</th><th>Multiplier</th><th>Settlement</th><th>Exercise</th><th>Exp. Type</th><th>Last Trading Day</th><th>Flags</th></tr></thead>" +
      "<tbody>" +
      rows +
      "</tbody></table></div>" +
      '<div class="sd-src">vendor per-contract · the chain — no field here is inferred or defaulted</div>';
  }
  // the `chain:structures` panel (push.chain) the program sends on the page's socket while the
  // Structures tab is on, at the selected expiry (null: the chain's front one); nothing received
  // yet for the ticker on screen is '-', and a frame of an expiry no longer selected is not drawn
  var _stTicker = null;
  document.addEventListener("ed:panel", function (e) {
    var d = e.detail,
      host = document.getElementById("stBody"),
      exp = window.EdShell.getExpiry();
    if (
      d.type !== "chain:structures" ||
      !host ||
      !inStructures() ||
      (exp && d.failed == null && d.expiry !== exp)
    )
      return;
    if (d.failed != null) {
      window.EdShell.placeholder(host, d.failed);
      return;
    }
    renderStructures(host, d);
  });
  function loadStructures() {
    if (!inStructures()) {
      window.EdShell.showPanel("chain:structures", null);
      return;
    }
    if (_stTicker !== ticker()) {
      _stTicker = ticker();
      var host = document.getElementById("stBody");
      if (host) window.EdShell.placeholder(host, "-");
    }
    window.EdShell.showPanel("chain:structures", { expiry: window.EdShell.getExpiry() });
  }

  // ---------- Options Book: the `option_book:book` panel (push.option_book) ------------
  // Each strike's call and put: resting bid and ask (Schwab's newest OPTIONS_BOOK, every level
  // summed) and volume today, then the summary and the options lean -- every number, word, share,
  // scale and angle served; the page places the bars and the needle. Sent while the tab is on, at
  // the selected expiry (null: the chain's front one) and the scope's window, at once and on each
  // book or quote; a frame of an expiry no longer selected is not drawn.
  function inBook() {
    var s = window.EdShell.getState();
    return s.workspace === "options" && s.subview === "book";
  }
  // one served number in its cell, its bar against the served scale (none: '-', no bar)
  function obCell(leg, key, scale, cls) {
    var v = leg ? leg[key] : null,
      w = window.EdDraw.barWidth(v, scale);
    var stale = leg && leg.book_live === false && key !== "volume";
    return (
      '<td class="ob-n ' +
      cls +
      (stale ? " nl" : "") +
      '"' +
      (leg && leg.book_when_text && key !== "volume"
        ? ' title="Schwab book ' + esc(leg.book_when_text) + '"'
        : "") +
      ">" +
      (v == null ? "" : '<i style="width:' + w.toFixed(1) + '%"></i>') +
      "<span>" +
      esc(orDash(leg ? leg[key + "_text"] : null)) +
      "</span></td>"
    );
  }
  // one summary bar: its label, the two served totals and shares, the track split at the share
  function obSplit(label, s, left, right, cls) {
    var lw = window.EdDraw.barWidth(s.left_share, 1),
      rw = window.EdDraw.barWidth(s.right_share, 1);
    return (
      '<div class="ob-split ' +
      cls +
      '"><div class="ob-split-h"><span class="ob-split-t">' +
      label +
      "</span></div>" +
      '<div class="ob-split-n"><span><em>' +
      left +
      "</em> <b>" +
      esc(orDash(s.left_text)) +
      "</b> <small>" +
      esc(orDash(s.left_share_text)) +
      "</small></span><span><small>" +
      esc(orDash(s.right_share_text)) +
      "</small> <b>" +
      esc(orDash(s.right_text)) +
      "</b> <em>" +
      right +
      "</em></span></div>" +
      '<div class="ob-split-track">' +
      (s.left_share == null
        ? ""
        : '<i class="l" style="width:' +
          lw.toFixed(1) +
          '%"></i><i class="r" style="width:' +
          rw.toFixed(1) +
          '%"></i>') +
      "</div></div>"
    );
  }
  // the options lean's gauge, its value and zone, the three readings beneath it (`compact`: the
  // Trade Desk card's); every number and word served, the needle at the served angle
  function leanHtml(d, compact) {
    var x = d.lean,
      z = x.zone_index == null ? "" : " z" + x.zone_index;
    return (
      '<div class="olg' +
      (compact ? " compact" : "") +
      '"><svg class="olg-dial" viewBox="0 0 200 112" role="img" aria-label="Options lean ' +
      esc(orDash(x.value_text)) +
      '">' +
      window.EdDraw.gauge(x.needle_deg, d.zones.length) +
      "</svg>" +
      '<div class="olg-ends"><span>' +
      esc(d.zones[0]) +
      "</span><span>" +
      esc(d.zones[d.zones.length - 1]) +
      "</span></div>" +
      '<div class="olg-read"><b class="olg-v' +
      z +
      '">' +
      esc(orDash(x.value_text)) +
      '</b><span class="olg-z' +
      z +
      '">' +
      esc(orDash(x.zone)) +
      "</span></div>" +
      '<div class="olg-parts"><span>Calls resting <b>' +
      esc(orDash(x.calls_text)) +
      "</b></span><span>Puts resting <b>" +
      esc(orDash(x.puts_text)) +
      "</b></span><span>Volume <b>" +
      esc(orDash(x.volume_text)) +
      "</b></span></div></div>"
    );
  }
  window.EdOptionLean = { html: leanHtml };
  function renderBook(host, d) {
    var src = document.getElementById("opbSrc"),
      ctx = document.getElementById("opbCtx");
    if (d.failed != null || d.available === false) {
      if (src) src.innerHTML = "";
      if (ctx) ctx.textContent = "";
      window.EdShell.placeholder(host, d.failed != null ? d.failed : d.reason);
      return;
    }
    if (ctx) ctx.textContent = d.expiry + " · " + d.books_held_text;
    if (src)
      src.innerHTML = window.EdShell.asOfBadge({
        label: "books",
        state: d.book_state,
        when: d.book_oldest_text,
        reason: d.book_outage,
      });
    var sc = d.scales;
    var rows = d.rows
      .map(function (r) {
        return (
          '<tr class="ob-row' +
          (r.marks.length ? " mark-spot" : "") +
          (r.summed ? "" : " ob-out") +
          '" data-strike="' +
          r.strike +
          '">' +
          obCell(r.call, "bid", sc.resting, "c bid") +
          obCell(r.call, "ask", sc.resting, "c ask") +
          obCell(r.call, "volume", sc.volume, "c vol") +
          '<td class="ob-k">' +
          esc(r.strike_text) +
          r.marks
            .map(function (m) {
              return '<span class="ob-mark">' + esc(m.label) + "</span>";
            })
            .join("") +
          "</td>" +
          obCell(r.put, "bid", sc.resting, "p bid") +
          obCell(r.put, "ask", sc.resting, "p ask") +
          obCell(r.put, "volume", sc.volume, "p vol") +
          "</tr>"
        );
      })
      .join("");
    var s = d.summary;
    host.innerHTML =
      '<div class="ob"><div class="ob-scroll"><table class="ob-t"><thead><tr>' +
      '<th class="c">Call bid</th><th class="c">Call ask</th><th class="c">Call vol</th>' +
      '<th class="ob-k">Strike</th>' +
      '<th class="p">Put bid</th><th class="p">Put ask</th><th class="p">Put vol</th>' +
      "</tr></thead><tbody>" +
      rows +
      "</tbody></table></div>" +
      '<div class="ob-foot"><section class="ob-sum"><div class="ob-h">Summary of the strikes shown</div>' +
      obSplit("Calls resting", s.calls, "Bid", "Ask", "rest") +
      obSplit("Puts resting", s.puts, "Bid", "Ask", "rest") +
      obSplit("Volume today", s.volume, "Calls", "Puts", "vol") +
      '<div class="ob-note">' +
      esc(s.summed_text) +
      (s.left_out_text ? "<br>" + esc(s.left_out_text) : "") +
      "</div></section>" +
      '<section class="ob-lean"><div class="ob-h">Options lean</div>' +
      leanHtml(d, false) +
      "</section></div></div>";
    var sr = host.querySelector(".ob-row.mark-spot");
    if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: "center" });
  }
  var _obTicker = null;
  function loadBook() {
    var host = document.getElementById("opbBody");
    if (!inBook()) {
      window.EdShell.showPanel("option_book:book", null);
      return;
    }
    if (_obTicker !== ticker()) {
      _obTicker = ticker();
      if (host) window.EdShell.placeholder(host, "-");
    }
    window.EdShell.showPanel("option_book:book", window.EdShell.windowAtExpiry(null));
  }
  document.addEventListener("ed:panel", function (e) {
    var d = e.detail,
      host = document.getElementById("opbBody"),
      exp = window.EdShell.getExpiry();
    if (d.type !== "option_book:book" || !host || !inBook()) return;
    if (exp && d.failed == null && d.expiry && d.expiry !== exp) return;
    renderBook(host, d);
  });

  // ---------- Options Flow tape ------------
  // The embedded tape widget on the Gamma pane (#ofBody) -- real native trade prints for
  // every contract of the ticker the daemon streams (its option rule), never a fabricated
  // buy/sell side.
  var OF_CLS_LABEL = {
    at_bid: "at bid",
    at_ask: "at ask",
    inside_spread: "inside",
    outside_spread_low: "below bid",
    outside_spread_high: "above ask",
    unknown: "-",
  };
  function renderOf(host, d) {
    var src = document.getElementById("ofSrc");
    if (src) src.textContent = "";
    if (!d.available) {
      // served: available exactly when rows were found
      host.innerHTML =
        '<table class="of"><thead><tr><th>Time</th><th>Symbol</th><th>Exp</th><th>Type</th><th>Strike</th>' +
        "<th>Bid×Size</th><th>Ask×Size</th><th>Trade</th><th>Size</th><th>Premium</th>" +
        "<th>Vol</th><th>OI</th><th>IV%</th><th>Δ</th><th>vs Market</th></tr></thead>" +
        '<tbody><tr class="of-empty"><td colspan="14"><div class="oe-sub">' +
        esc(d.reason) +
        "</div></td></tr></tbody></table>"; // the server says why with every empty tape
      return;
    }
    var body = d.rows
      .map(function (r) {
        return (
          "<tr>" +
          "<td>" +
          esc(orDash(r.trade_time_ct)) +
          "</td>" +
          '<td class="of-sym">' +
          esc(orDash(r.symbol)) +
          "</td>" +
          "<td>" +
          esc(r.expiry ? r.expiry.slice(5) : "-") +
          "</td>" +
          "<td>" +
          esc(orDash(r.type)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.strike_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.bid_text)) +
          "×" +
          esc(orDash(r.bid_size_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.ask_text)) +
          "×" +
          esc(orDash(r.ask_size_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.trade_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.size_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.premium_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.volume_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.oi_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.iv_text)) +
          "</td>" +
          "<td>" +
          esc(orDash(r.delta_text)) +
          "</td>" +
          '<td><span class="of-cls ' +
          esc(r.classification || "unknown") +
          '">' +
          esc(orDash(OF_CLS_LABEL[r.classification])) +
          "</span></td></tr>"
        );
      })
      .join("");
    host.innerHTML =
      '<table class="of"><thead><tr><th>Time</th><th>Symbol</th><th>Exp</th><th>Type</th><th>Strike</th>' +
      "<th>Bid×Size</th><th>Ask×Size</th><th>Trade</th><th>Size</th><th>Premium</th>" +
      "<th>Vol</th><th>OI</th><th>IV%</th><th>Δ</th><th>vs Market</th></tr></thead><tbody>" +
      body +
      "</tbody></table>";
  }
  // the `tape` panel (server.tape) on the page's socket, at once and with each streamed quote
  function loadOf() {
    window.EdShell.showPanel("tape", isGamma() ? {} : null);
  }
  document.addEventListener("ed:panel", function (e) {
    var d = e.detail,
      host = document.getElementById("ofBody");
    if (d.type !== "tape" || !host || !isGamma()) return;
    renderOf(host, d.failed != null ? { available: false, reason: d.failed } : d);
  });

  // ---------- events ----------
  function loadAll() {
    loadLevels();
    loadGbs();
    loadVanna();
    loadCharm();
    loadStructures();
    loadBook();
    loadOf();
  }
  document.addEventListener("ed:ticker", function () {
    resetStrikeDetailForTickerChange();
    loadAll();
  });
  document.addEventListener("ed:expiry", loadLevels); // the ratio is scoped to the selected expiry
  document.addEventListener("ed:view", loadAll);
  // a new scope is a new window: every per-strike panel re-reads it from the server
  document.addEventListener("ed:scope", function () {
    loadGbs();
    loadVanna();
    loadCharm();
    loadBook();
  });
  document.addEventListener("ed:strike", function (e) {
    var det = e.detail || {};
    applyGbsHighlight(); // A: sync the GEX-by-strike highlight
    loadStrike(det.strike == null ? null : det.strike, det.strike == null ? null : det.expiry);
  });
  document.addEventListener("ed:expiry", function () {
    // the expiry choice: Strike Detail and GEX by Strike follow it; Levels stay aggregate + disclose
    loadLevels();
    loadGbs(); // a new expiry is a new answer: the server sends that expiry's rows
    loadStructures(); // Structures is expiry-scoped, same as Chain/Strike Detail
    loadBook(); // and so is the Options Book
    var sel = window.EdShell.getState().selStrike;
    if (sel != null) loadStrike(sel, strikeDetailExpiry());
  });
  // Initial hydration comes SOLELY from ed-core.js's deferred ed:ticker/ed:view dispatch --
  // see that file's init() comment.
})();
