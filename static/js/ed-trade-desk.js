/* Ed Console — Trade Desk / "Right Now" subview. PRESENTATION ONLY, computes nothing.
   The page's reasoning flow is Detect -> Frame -> Confirm -> Execute; this module builds the
   first three stages from panels other workspaces already own, all on the page's socket -- one
   page, zero new math, zero new producers:
     DETECT  <- the `book:desk` panel (same engine the Order Flow > Book/DOM tab reads)
     FRAME   <- the `levels:desk` and `liquidity:desk` panels (same contracts Liquidity > Levels/Map read)
     CONFIRM <- the `terrain:desk` panel (the levels the Gamma tab is sent)
   The Context Summary panel is plain-English arrangement of those SAME four responses (e.g.
   "is spot presently between these two already-fetched zone bounds") -- a classification of
   already-canonical values, never a new computed truth, and never a fabricated confluence
   score. EXECUTE is deliberately NOT rendered. THE CALL and 1m/5m/15m/60m horizons stay
   NOT_PROVEN until ticker-universal evidence earns them (the operator's own gate, preserved
   in the footer badge below) -- this page synthesizes, it does not decide. */
(function () {
  "use strict";

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;
  var ticker = window.EdShell.ticker,
    classOf = window.EdShell.classOf,
    served = window.EdShell.served,
    notLive = window.EdShell.notLive;
  function isRightNow() {
    var s = window.EdShell.getState();
    return s.workspace === "trade-desk" && s.subview === "right-now";
  }
  function host() {
    return document.getElementById("tdBody");
  }

  // ---- one stage card: numbered badge, title, one HERO stat, a short supporting-row list ----
  // a served tilt's arrow and colour on a hero (bids up and green, offers down and red), by the
  // tilt's name as served (order_flow.TILT_WORDS); a hero with no tilt has neither
  var TILT_GLYPH = { BID_HEAVY: "▲", BALANCED: "", OFFER_HEAVY: "▼" };
  var TILT_CLS = { BID_HEAVY: "pos", BALANCED: "", OFFER_HEAVY: "neg" };
  function stage(n, accentCls, title, hero, heroUnit, heroTilt, rows, badgeText, badgeCls) {
    var dirGlyph = heroTilt ? TILT_GLYPH[heroTilt] : "";
    var dirCls = heroTilt ? TILT_CLS[heroTilt] : "";
    var h =
      '<div class="td-stage ' +
      accentCls +
      '">' +
      '<div class="td-stage-h"><span class="td-badge ' +
      accentCls +
      '">' +
      n +
      "</span>" +
      '<span class="td-stage-title">' +
      esc(title) +
      "</span>" +
      (badgeText
        ? '<span class="fl-badge ' +
          (badgeCls || "") +
          '" style="margin-left:auto;">' +
          esc(badgeText) +
          "</span>"
        : "") +
      "</div>" +
      '<div class="td-hero"><span class="' +
      dirCls +
      '">' +
      (dirGlyph ? dirGlyph + " " : "") +
      esc(hero) +
      "</span>" +
      (heroUnit ? '<span class="unit">' + esc(heroUnit) + "</span>" : "") +
      "</div>";
    return h + window.EdShell.rowsHtml(rows) + "</div>";
  }

  function detectStage(d) {
    // the book panel as sent: undefined (none yet), failed, or the book
    if (d === undefined)
      return stage(1, "td-accent-blue", "Detect — book microstructure", "-", "", null, [], null);
    if (d.failed != null) {
      // said so, never told as a book Schwab did not send
      return stage(
        1,
        "td-accent-blue",
        "Detect — book microstructure",
        d.failed,
        "",
        null,
        [],
        "FAILED",
        "warn",
      );
    }
    if (d.status === "no_book") {
      return stage(
        1,
        "td-accent-blue",
        "Detect — book microstructure",
        "No book yet",
        "",
        null,
        [],
        "NO BOOK",
        "warn",
      );
    }
    var tob = d.top_of_book,
      depth = d.depth,
      cls = d.classification; // always served (engine.compute_book_microstructure)
    // Schwab's book time and its age, as served; neither sent shows "-"
    var bookAge = d.book_when_age_text == null ? "-" : d.book_when_age_text;
    var rows = [
      [
        "Bid × Ask",
        orDash(tob.bid_text) + " × " + orDash(tob.ask_text),
        classOf(cls, "top_of_book.bid"),
      ],
      ["Spread (pts)", orDash(d.spread_pts_text), classOf(cls, "spread_pts")],
      ["Depth 1 imbalance", orDash(depth["1"].imbalance_text), classOf(cls, "depth.*.imbalance")],
      ["Book age", bookAge, classOf(cls, "ages.book_age_sec")],
    ];
    // the Liquidity readout's served headline and side word for this book at depth 5: the one
    // producer of a book's lean (the Desk card shows the same)
    var r5 = d.readout && d.readout.venues[d.venue] && d.readout.venues[d.venue].views["5"];
    var tilt = r5 ? r5.tilt : null;
    var heroVal = r5 && r5.pct_text != null ? r5.pct_text : "-";
    var heroUnit =
      tilt == null ? "" : r5.side_word.toLowerCase() + " (" + esc(d.venue) + ", depth 5)";
    // the served words: the top of book's while it is not live, else the book's (book_feed_label);
    // no book age served reads AGE UNKNOWN, never live
    var bs = d.ages.book_stale;
    var badge = d.top_outage ? d.top_feed_label : bs == null ? "AGE UNKNOWN" : d.book_feed_label;
    return stage(
      1,
      "td-accent-blue",
      "Detect — book microstructure",
      heroVal,
      heroUnit,
      tilt,
      rows,
      badge,
      d.top_outage || bs !== false ? "stale" : "live",
    );
  }

  function frameStage(sent) {
    // the levels panel as sent: undefined (none yet), failed, or the levels
    if (sent === undefined)
      return stage(2, "td-accent-green", "Frame — liquidity levels", "-", "", null, [], null);
    if (sent.failed != null)
      return stage(
        2,
        "td-accent-green",
        "Frame — liquidity levels",
        sent.failed,
        "",
        null,
        [],
        null,
      );
    var levelsD = sent;
    var levels = levelsD.levels; // always served (levels_payload)
    if (!levels.length)
      return stage(
        2,
        "td-accent-green",
        "Frame — liquidity levels",
        "No levels",
        "",
        null,
        [],
        null,
      );
    // served: levels ordered by distance to the live price (by_distance), each with its distance and side
    var byId = {};
    levels.forEach(function (r) {
      byId[r.id] = r;
    });
    var sorted = levelsD.by_distance
      .map(function (id) {
        return byId[id];
      })
      .filter(Boolean);
    if (!sorted.length)
      return stage(
        2,
        "td-accent-green",
        "Frame — liquidity levels",
        "No priced levels",
        "",
        null,
        [],
        null,
      );
    var nearest = sorted[0];
    var rows = sorted.slice(1, 6).map(function (r) {
      return [r.label, r.price_text, r.evidence_tier];
    });
    var heroVal = nearest.label + " " + nearest.price_text; // served: every level has its name
    return stage(
      2,
      "td-accent-green",
      "Frame — nearest liquidity level",
      heroVal,
      nearest.from_spot_text + notLive(levelsD),
      null,
      rows,
      null,
    );
  }

  function confirmStage(d) {
    // d: the terrain panel as sent; undefined: none yet ('-')
    if (d === undefined)
      return stage(3, "td-accent-amber", "Confirm — options regime", "-", "", null, [], null);
    if (d.failed != null)
      return stage(
        3,
        "td-accent-amber",
        "Confirm — options regime",
        "No regime",
        d.failed,
        null,
        [],
        null,
      );
    // Raw values only -- stage() escapes every row itself (double-escaping a value here turns
    // a real "&" into the literal text "&amp;" on screen).
    var rows = [
      ["Call wall", orDash(d.call_wall_text)],
      ["Put wall", orDash(d.put_wall_text)],
      ["Γ flip", orDash(d.gamma_flip_text)],
      // max pain is per expiry: label it with the expiry the server computed it on (front)
      [
        "Max pain" + (d.max_pain_dte != null ? " (" + d.max_pain_dte + "DTE)" : ""),
        orDash(d.max_pain_text),
      ],
      ["Net GEX @ spot", orDash(d.net_gex_at_spot_text)],
    ];
    if (d.flip_note != null) rows.push(["Γ flip note", d.flip_note]); // served: the flip's note
    return stage(
      3,
      "td-accent-amber",
      "Confirm — options regime",
      orDash(d.regime),
      "",
      null,
      rows,
    );
  }

  // ---- Context Summary: plain-English arrangement of the SAME 4 responses. Classifies
  // (inside a zone / between two zones), never invents a value. ----
  function contextSummary(terrain, snap, levelsD) {
    var lines = [];
    if (terrain) {
      lines.push(["Regime", orDash(terrain.regime)]);
      // the served headline, its served sources on hover
      if (terrain.headline) lines.push(["Read", terrain.headline, terrain.headline_source]);
    }
    var sl = snap && snap.spot_location,
      zones = sl && snap.zones; // served
    var loc = sl
      ? {
          inside: sl.inside != null ? zones[sl.inside] : null,
          above: sl.above != null ? zones[sl.above] : null,
          below: sl.below != null ? zones[sl.below] : null,
        }
      : null;
    if (loc && loc.inside) {
      var z = loc.inside;
      lines.push([
        "Location",
        "Inside a " +
          esc(z.zone_label) +
          " zone (" +
          z.zone_low_text +
          "–" +
          z.zone_high_text +
          ", confluence " +
          z.confluence_score +
          ")",
      ]);
    } else if (loc) {
      var parts = [];
      if (loc.above)
        parts.push(
          esc(loc.above.zone_label) +
            " zone above at " +
            loc.above.zone_low_text +
            " (confluence " +
            loc.above.confluence_score +
            ")",
        );
      if (loc.below)
        parts.push(
          esc(loc.below.zone_label) +
            " zone below at " +
            loc.below.zone_high_text +
            " (confluence " +
            loc.below.confluence_score +
            ")",
        );
      lines.push([
        "Location",
        parts.length ? "Between zones — " + parts.join(", ") : "No scored zone nearby",
      ]);
    }
    var walls = {}; // served: the levels panel's own rows
    if (levelsD && levelsD.levels)
      levelsD.levels.forEach(function (r) {
        walls[r.id] = r;
      });
    if (
      walls.put_wall &&
      walls.call_wall &&
      walls.put_wall.from_spot_text &&
      walls.call_wall.from_spot_text
    ) {
      lines.push([
        "Walls",
        "Put wall " +
          walls.put_wall.from_spot_text +
          ", call wall " +
          walls.call_wall.from_spot_text +
          notLive(levelsD),
      ]);
    }
    if (!lines.length) return "";
    return (
      '<div class="td-context"><h4>Context summary</h4>' +
      lines
        .map(function (l) {
          return (
            '<div class="td-ctx-row"><span class="lbl">' +
            esc(l[0]) +
            '</span><span class="val"' +
            (l[2] ? ' title="' + esc(l[2]) + '"' : "") + // a line's sources, on hover
            ">" +
            esc(l[1]) +
            "</span></div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  // ---- Positioning Migration & Volume: today's per-strike net GEX$ (solid) vs yesterday's
  // (ghost outline), plus today's per-strike option volume -- the SAME real fields
  // the strikes panel already sends to GEX by Strike (today.{all,near,far} rows, each
  // {strike, value, volume} with their texts, and migration.{all,near,far}). ----
  var _migScope = "all"; // 'all' | 'near' (<=7 DTE) | 'far' (monthly+) -- a DTE filter, distinct
  // from EdShell's own auto/wider/all row-DENSITY scope used below.
  var _migGhost = true;
  var MIG_SCOPES = [
    ["all", "ALL"],
    ["near", "≤7 DTE"],
    ["far", "MONTHLY+"],
  ];

  // Own badge class, deliberately NOT fl-tag/native|derived -- those hooks are this file's (and
  // ed-gamma-panels.js's) provenance classification colors; a SPOT/wall price marker is a
  // position label, not a provenance claim, and reusing them would misread as one.
  function migTag(txt, cls) {
    return '<span class="mig-mark ' + cls + '">' + esc(txt) + "</span>";
  }

  var LEVEL_WORDS = { call_wall: "Call wall", put_wall: "Put wall", gamma_flip: "Γ flip" };
  // one served level move with its texts: 'Call wall 755 → 760 (+5)'; a side not known is '-',
  // and a change is said only when both days are known
  function levelMove(v) {
    return (
      LEVEL_WORDS[v.level] +
      " " +
      orDash(v.prior_text) +
      " → " +
      orDash(v.today_text) +
      (v.change_text == null ? "" : " (" + v.change_text + ")")
    );
  }
  var WALL_WORDS = {
    ABOVE_CALL_WALL: "ABOVE the call wall",
    BELOW_PUT_WALL: "BELOW the put wall",
    INSIDE_WALLS: "inside the wall range",
  };
  // m: the served positioning_migration for this DTE scope; moves: the served level_moves
  function migrationCoach(m, moves) {
    var out = "";
    if (!m || !m.compared) {
      out +=
        '<div class="mig-coach"><b>Migration view warming up</b>The first day-over-day comparison lands after the next wide morning capture.</div>';
    } else {
      var grew = m.grew_text,
        shrank = m.shrank_text;
      out +=
        '<div class="mig-coach"><b>Levels since the prior close: ' +
        esc(moves.map(levelMove).join(" · ")) +
        "</b>" +
        (grew ? "Gamma grew most at " + esc(grew) : "No strike grew") +
        (shrank ? "; shrank most at " + esc(shrank) + "." : ".") +
        "</div>";
    }
    if (m && m.busiest && m.busiest.length) {
      out +=
        '<div class="mig-coach"><b>Heaviest option trading at ' +
        m.busiest_text +
        "</b>" +
        "That is " +
        esc(orDash(WALL_WORDS[m.busiest_vs_walls])) +
        ".</div>";
    }
    return out;
  }

  // The migration panel's strikes are the window the program sends (the Gamma scope, and the
  // operator's pan on its strike labels: EdShell.wireStrikeAxis). A pan or a new scope asks the
  // new window of its panel, and the program sends that window from then on.
  var _migPan = window.EdShell.newPan(),
    _migPanTicker = null;
  function migPan(tk) {
    // the pan is the ticker's: a new ticker follows the price
    if (_migPanTicker !== tk) {
      _migPan.centre = null;
      _migPan.shift = 0;
      _migPanTicker = tk;
    }
    return _migPan;
  }
  function wireMigration(panel) {
    wireMigrationChips(panel);
    var firstRow = panel.querySelector(".gbs-row");
    window.EdShell.wireStrikeAxis(
      panel.querySelectorAll(".gbs-k"),
      panel.querySelector(".gbs-scroll"),
      _migPan,
      firstRow ? firstRow.getBoundingClientRect().height : 0,
      askPanels,
    );
  }

  function migrationSection(strikesD) {
    // none sent yet for this ticker ('-'), or the program's words for why it is not drawn
    var why =
      strikesD === undefined
        ? "-"
        : strikesD.failed != null
          ? strikesD.failed
          : strikesD.available === false
            ? strikesD.reason
            : null;
    if (why != null)
      return (
        '<div class="td-panel" id="tdMigration"><h4>Positioning migration &amp; volume</h4>' +
        '<div class="placeholder"><div class="sm">' +
        esc(why) +
        "</div></div></div>"
      );
    var todayAll = strikesD.today[_migScope]; // always served: every scope's rows, none when there are no levels
    if (!todayAll.length) {
      var stale = strikesD.levels_stale_reason;
      return (
        '<div class="td-panel" id="tdMigration"><h4>Positioning migration &amp; volume</h4>' +
        '<div class="placeholder"><div class="sm">' +
        (stale ? "no per-strike rows — " + esc(stale) : "no per-strike gamma for this symbol yet") +
        "</div></div></div>"
      );
    }
    // served: day-over-day rows {strike, value, prior, change, change_text} and the verdicts
    var mig = strikesD.migration[_migScope];
    var migRow = {};
    mig.rows.forEach(function (r) {
      migRow[r.strike] = r;
    });
    var view = strikesD.views[_migScope];
    window.EdShell.panServed(_migPan, view.centre);
    var win = todayAll.slice().reverse(); // the served window, high strikes on top
    // a pan is never silent: the strikes stop following the price until a double-click
    var note =
      (_migPan.centre != null
        ? '<div class="gbs-allexp">Panned to ' +
          view.centre_text +
          " · double-click a strike to follow the price</div>"
        : "") + (view.note ? '<div class="gbs-allexp">' + esc(view.note) + "</div>" : ""); // why not around the price
    var maxAbs = view.max_abs_with_prior; // served: today's and the prior day's bars, one scale
    var rows = "";
    win.forEach(function (r) {
      // a strike with no GEX value is unknown, not a zero bar
      var m = migRow[r.strike],
        gx = r.value,
        gy = m ? m.prior : null;
      var hasGy = gy != null && gx != null;
      var tone = window.EdDraw.bySign(gx, "pos", "neg", ""),
        wToday = window.EdDraw.barWidth(gx, maxAbs);
      var ghostBar = hasGy
        ? '<i class="mig-ghost ' +
          window.EdDraw.bySign(gy, "pos", "neg", "") +
          '" style="width:' +
          window.EdDraw.barWidth(gy, maxAbs).toFixed(1) +
          '%"></i>'
        : "";
      var delta = m ? m.change : null; // served change
      var deltaHtml =
        delta == null
          ? '<span class="mig-delta">-</span>'
          : '<span class="mig-delta ' +
            window.EdDraw.bySign(delta, "pos", "neg", "") +
            '">' +
            esc(m.change_text) + // served: "▲$1.23M" / "▼$1.23M"
            "</span>";
      rows +=
        '<div class="gbs-row mig-row' +
        r.marks
          .map(function (mk) {
            return " mark-" + mk.kind; // served: the strike at the price, the call and put walls
          })
          .join("") +
        '">' +
        '<span class="gbs-k">' +
        r.strike_text +
        "</span>" +
        '<span class="gbs-track mig-track"><i class="gbs-bar ' +
        tone +
        '" style="width:' +
        wToday.toFixed(1) +
        '%"></i>' +
        (_migGhost ? ghostBar : "") +
        "</span>" +
        '<span class="gbs-v ' +
        tone +
        '">' +
        esc(orDash(r.text)) + // served: net GEX $ as the screen shows it
        "</span>" +
        (_migGhost ? deltaHtml : "") +
        '<span class="gbs-vol" title="session volume">' +
        esc(orDash(r.volume_text)) +
        "</span>" +
        r.marks
          .map(function (mk) {
            return migTag(mk.label, mk.kind);
          })
          .join("") +
        "</div>";
    });
    var scopeChips =
      '<div class="mig-chips">' +
      MIG_SCOPES.map(function (s) {
        return (
          '<span class="mig-chip' +
          (s[0] === _migScope ? " on" : "") +
          '" data-mig-scope="' +
          s[0] +
          '">' +
          s[1] +
          "</span>"
        );
      }).join("") +
      '<span class="mig-chip' +
      (_migGhost ? " on" : "") +
      '" data-mig-ghost="1">GHOST</span></div>';
    // what a session volume of 0 means, served (push.strikes._shown_scope)
    var volZero = mig ? mig.volume_zero_text : null;
    var volNote = volZero
      ? '<div class="mig-vol-note' +
        (strikesD.levels_state === "STALE" ? " stale" : "") +
        '">' +
        esc(volZero) +
        "</div>"
      : "";
    return (
      '<div class="td-panel" id="tdMigration"><h4>Positioning migration &amp; volume ' +
      '<span class="mig-legend"><i class="sw" style="background:var(--ed-pos)"></i>+Γ today ' +
      '<i class="sw" style="background:var(--ed-neg)"></i>-Γ today ' +
      '<i class="sw ghostsw"></i>yesterday (ghost)</span></h4>' +
      scopeChips +
      '<div class="mig-top">' +
      note +
      volNote +
      "</div>" +
      '<div class="gbs-scroll"><div class="gbs">' +
      rows +
      "</div></div>" +
      '<div class="gbs-scale"><span class="neg">−</span><span>0</span><span class="pos">+</span></div>' +
      migrationCoach(mig, strikesD.level_moves) +
      "</div>"
    );
  }

  // a chip picks which of the served rows are drawn: the page draws again, asking nothing
  function wireMigrationChips(h) {
    h.querySelectorAll("[data-mig-scope]").forEach(function (b) {
      b.addEventListener("click", function () {
        var s = b.getAttribute("data-mig-scope");
        if (s === _migScope) return;
        _migScope = s;
        draw();
      });
    });
    var gh = h.querySelector("[data-mig-ghost]");
    if (gh)
      gh.addEventListener("click", function () {
        _migGhost = !_migGhost;
        draw();
      });
  }

  // DETECT's book, FRAME's levels and zones, CONFIRM's levels and the migration's rows: the
  // `book:desk`, `levels:desk`, `liquidity:desk`, `terrain:desk` and `strikes:migration` panels
  // (push.book, server.levels, server.liquidity, push.terrain, push.strikes) the program
  // sends on the page's socket while Right Now is on, at once and each time one changes; a panel
  // not in `_panels` has not been sent yet for the ticker on screen
  var NAMES = ["book:desk", "levels:desk", "liquidity:desk", "terrain:desk", "strikes:migration"];
  var _panels = {},
    _panelsTicker = null;
  document.addEventListener("ed:panel", function (e) {
    if (NAMES.indexOf(e.detail.type) < 0) return;
    _panels[e.detail.type] = e.detail;
    if (!isRightNow()) return;
    try {
      draw();
    } catch (err) {
      // said, then reported
      window.EdShell.placeholder(host(), "the page could not draw the answer of Right Now");
      throw err;
    }
  });
  function draw() {
    var h = host();
    if (!h) return;
    var tk = ticker(),
      snap = served(_panels["liquidity:desk"]);
    var strikesD = _panels["strikes:migration"],
      sent = _panels["terrain:desk"],
      levelsSent = _panels["levels:desk"];
    var terrain = served(sent),
      levelsD = served(levelsSent);
    // the spot is the levels panel's alone, as served; none yet, or none sent, is absent, never 0
    var spotText = levelsD ? levelsD.spot_text : null;
    var when = levelsD && levelsD.spot_time_ct ? " · last trade " + esc(levelsD.spot_time_ct) : "";
    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Right now</span><span class="fl-sym">' +
      esc(tk) +
      '</span><span class="fl-meta">' +
      (spotText != null ? "spot " + esc(spotText) + when : "") +
      "</span></div></div>" +
      '<div class="td-grid">' +
      detectStage(_panels["book:desk"]) +
      frameStage(levelsSent) +
      confirmStage(sent) +
      "</div>" +
      contextSummary(terrain, snap, levelsD) +
      migrationSection(strikesD) +
      '<div class="notproven" style="margin-top:14px;">HOME PRESERVED — DECISION AUTHORITY NOT_PROVEN. ' +
      "This page assembles already-canonical Detect/Frame/Confirm signals and classifies them in plain English; it computes no new value and renders no Execute step. " +
      "THE CALL and 1m/5m/15m/60m horizons remain excluded until ticker-universal evidence earns them.</div>";
    var migEl = document.getElementById("tdMigration");
    if (migEl) wireMigration(migEl);
  }
  // the panels Right Now shows: the book of the selected venue, the migration's in its window
  // (the Gamma scope and the pan)
  function askPanels() {
    var on = isRightNow();
    window.EdShell.showPanel(
      "book:desk",
      on ? { venue: window.EdShell.getState().bookVenue } : null,
    );
    window.EdShell.showPanel("levels:desk", on ? { tf: "1" } : null);
    window.EdShell.showPanel("liquidity:desk", on ? {} : null);
    window.EdShell.showPanel("terrain:desk", on ? {} : null);
    window.EdShell.showPanel(
      "strikes:migration",
      on ? window.EdShell.windowParams(migPan(ticker())) : null,
    );
  }
  function load() {
    if (isRightNow() && _panelsTicker !== ticker()) {
      // a new ticker: nothing of the last one's
      _panelsTicker = ticker();
      _panels = {};
      draw();
    }
    askPanels();
  }

  document.addEventListener("ed:view", load);
  document.addEventListener("ed:ticker", load);
  document.addEventListener("ed:book_venue", load);
  document.addEventListener("ed:scope", askPanels); // a new scope is a new window
  // the first read comes from ed-core.js's ed:ticker/ed:view dispatch at init
})();

/* Trade Desk / "Experimental": the `experimental` panel of the selected ticker as served, every
   value and word from the server (server.experimental); draws, computes nothing. */
(function () {
  "use strict";

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash,
    ticker = window.EdShell.ticker;
  function isExperimental() {
    var s = window.EdShell.getState();
    return s.workspace === "trade-desk" && s.subview === "experimental";
  }
  // the served direction as its color: up, down, or none (a value not sent)
  function dir(up) {
    return up === true ? "xp-up" : up === false ? "xp-down" : "";
  }
  function edge(up) {
    return up === true ? "up" : up === false ? "down" : "";
  }
  function todayCard(t) {
    return (
      '<div class="xp-card ' +
      edge(t.gap_up) +
      '"><div class="xp-lab">' +
      esc(t.label) +
      '</div><div class="xp-big ' +
      dir(t.gap_up) +
      '">' +
      esc(orDash(t.gap_text)) +
      '</div><div class="xp-sub">' +
      esc(t.when_text) +
      "</div></div>"
    );
  }
  function followedCard(m, others) {
    return (
      '<div class="xp-card accent"><div class="xp-lab">' +
      esc(m.title) +
      '</div><div><span class="xp-big">' +
      esc(m.share_text) +
      '</span><span class="xp-count">' +
      esc(m.count_text) +
      '</span></div><div class="xp-bar"><div class="xp-band" style="left:' +
      m.band_left +
      "%;width:" +
      m.band_width +
      '%"></div><div class="xp-half"></div><div class="xp-mark" style="left:' +
      m.mark +
      '%"></div></div><div class="xp-scale"><span>' +
      esc(m.range_text) +
      "</span><span>coin flip at 50%</span></div>" +
      others
        .map(function (o) {
          return '<div class="xp-sub" style="margin-top:8px">' + esc(o.line) + "</div>";
        })
        .join("") +
      "</div>"
    );
  }
  function resultRow(r) {
    return (
      '<div class="xp-card ' +
      edge(r.called) +
      ' xp-result"><span class="xp-lab">' +
      esc(r.label) +
      '</span><span class="xp-big ' +
      dir(r.five_up) +
      '">' +
      esc(r.five_text) +
      '</span><span class="' +
      dir(r.called) +
      '">' +
      esc(r.called_text) +
      "</span></div>"
    );
  }
  function lastTable(rec) {
    return (
      '<div style="margin-top:14px"><div class="xp-lab">' +
      esc(rec.last_title) +
      '</div><table class="xp-last"><tr><th>Day</th><th>Gap</th><th>First 5 min</th>' +
      '<th class="r">Called</th></tr>' +
      rec.last
        .map(function (o) {
          return (
            "<tr><td>" +
            esc(o.day_text) +
            '</td><td class="' +
            dir(o.gap_up) +
            '">' +
            esc(o.gap_text) +
            '</td><td class="' +
            dir(o.five_up) +
            '">' +
            esc(o.five_text) +
            '</td><td class="r ' +
            dir(o.called) +
            '">' +
            (o.called ? "✓" : "✗") +
            "</td></tr>"
          );
        })
        .join("") +
      '</table></div><div class="xp-foot">' +
      esc(rec.footer) +
      "</div>"
    );
  }
  function draw(d) {
    var h = document.getElementById("xpBody");
    if (!h) return;
    if (d.failed != null) {
      window.EdShell.placeholder(h, "the Experimental panel was not produced: " + d.failed);
      return;
    }
    // the approved mock-up: today's gap, how that direction was followed, today's result, the
    // last 10 opens
    h.innerHTML =
      '<div class="xp-view"><div class="xp-head"><span class="xp-sym">' +
      esc(d.ticker) +
      '</span><span class="xp-lab">Open gap</span></div><div class="xp-top">' +
      todayCard(d.today) +
      d.records
        .map(function (rec) {
          return followedCard(rec.main, rec.others);
        })
        .join("") +
      "</div>" +
      d.today.results.map(resultRow).join("") +
      d.records.map(lastTable).join("") +
      "</div>";
  }
  document.addEventListener("ed:panel", function (e) {
    // the selected ticker's only: one asked before a switch is not drawn
    if (e.detail.type === "experimental" && isExperimental() && e.detail.ticker === ticker()) {
      draw(e.detail);
    }
  });
  function ask() {
    window.EdShell.showPanel("experimental", isExperimental() ? {} : null);
  }
  document.addEventListener("ed:view", ask);
  document.addEventListener("ed:ticker", ask);
})();
