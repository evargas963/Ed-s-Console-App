/* Trade Desk / Confluence Matrix. Draws the `confluence` panel. Computes nothing: every number,
   word, colour tone, level placement and the price row's place is served. */
(function () {
  "use strict";

  var selectedStrike = null;
  var lastRows = [];
  var bound = false;

  // the groups, read left to right by importance (decision 62), each with its columns and class,
  // and each column: its head, unit, what it is (hover), the served row keys of its text, shading
  // number, reason and hover, the served peak it shades against ("one": the Composite's own
  // scale, 1), and its cell's and head's classes (a group's last column has the edge)
  var GROUPS = [
    ["Composite", 1, "group edge"],
    ["Price and levels", 4, "group edge"],
    ["Gamma profile and levels", 2, "group edge"],
    ["Positioning (open interest)", 4, "group edge"],
    ["Second-order Greeks (charm, vanna, IV)", 4, "group edge"],
    ["Volume and flow", 5, "group edge"],
    ["Hedging flow (est.)", 1, "group"],
  ];
  var COLS = [
    {
      head: "Read · strength",
      unit: "model · untested",
      title:
        "The sign of the expiry's gamma if the price were here (negative: the hedging accelerates moves; positive: it dampens them) and its strength, 0 to 100: the equal vote of the families measured here.",
      text: "composite_text",
      value: "composite",
      peak: "one",
      reason: "composite_reason",
      hover: "composite_hover",
      cls: "comp edge",
      th: "edge",
    },
    { head: "Strike", unit: "", title: "Listed strike.", text: "strike_text", cls: "plain strike" },
    {
      head: "Δ pts",
      unit: "points",
      title: "Strike minus the live price.",
      text: "distance_text",
      cls: "plain",
    },
    {
      head: "σ",
      unit: "implied moves",
      title:
        "The distance in the expiry's implied moves: ln(strike / price) over its at-the-money volatility times the square root of the time left.",
      text: "sigma_text",
      cls: "plain",
    },
    {
      head: "Key levels here",
      unit: "",
      title: "The key levels nearest this strike, each at its own price; its hold rate on hover.",
      tags: true,
      cls: "plain tags edge",
      th: "edge",
    },
    {
      head: "Gamma if here",
      unit: "model",
      title:
        "The expiry's net gamma if the price were at this strike, on the convention: dealers long calls, short puts.",
      text: "gamma_here_text",
      value: "gamma_here",
      peak: "gamma_here",
      reason: "gamma_here_reason",
      hover: "gamma_here_hover",
    },
    {
      head: "Visits",
      unit: "bounced of hits",
      title: "Today's hits at the strike, and how many bounced 15 minutes later.",
      text: "visits_text",
      value: "visits",
      peak: "visits",
      reason: "visits_reason",
      hover: "visits_hover",
      cls: "edge",
      th: "edge",
    },
    {
      head: "Net GEX",
      unit: "$ / 1%",
      title: "Net gamma exposure in dollars per 1% move.",
      text: "net_gex_text",
      value: "net_gex",
      peak: "net_gex",
      reason: "net_reason",
    },
    {
      head: "OI",
      unit: "contracts",
      title: "Open interest, calls and puts, as Schwab sent it.",
      text: "oi_text",
      value: "oi",
      peak: "oi",
      reason: "oi_reason",
      hover: "oi_hover",
    },
    {
      head: "ΔOI 1d",
      unit: "contracts",
      title: "Open interest less the prior day's capture of this expiry.",
      text: "oi_change_text",
      value: "oi_change",
      peak: "oi_change",
      reason: "oi_change_reason",
      hover: "oi_change_hover",
    },
    {
      head: "DEX",
      unit: "$",
      title: "Delta exposure in dollars.",
      text: "dex_text",
      value: "dex",
      peak: "dex",
      reason: "dex_reason",
      cls: "edge",
      th: "edge",
    },
    {
      head: "Charm",
      unit: "shares/day · model",
      title: "The open interest's delta drift per day, in shares.",
      text: "charm_text",
      value: "charm",
      peak: "charm",
      reason: "charm_reason",
    },
    {
      head: "Vanna",
      unit: "$ / vol pt",
      title: "Vanna in dollars per volatility point.",
      text: "vanna_text",
      value: "vanna",
      peak: "vanna",
      reason: "vanna_reason",
    },
    {
      head: "IV",
      unit: "%",
      title: "The strike's implied volatility, Schwab's, blended over calls and puts.",
      text: "iv_text",
      value: "iv",
      peak: "iv",
      reason: "iv_reason",
    },
    {
      head: "IV chg",
      unit: "vol pts · look-back",
      title: "The strike's implied volatility now less at the look-back's start.",
      text: "iv_change_text",
      value: "iv_change",
      peak: "iv_change",
      reason: "iv_change_reason",
      hover: "iv_change_hover",
      cls: "edge",
      th: "edge",
    },
    {
      head: "Volume",
      unit: "contracts",
      title: "Contracts traded at the strike, calls and puts.",
      text: "volume_text",
      value: "volume",
      peak: "volume",
      reason: "volume_reason",
      hover: "volume_hover",
    },
    {
      head: "Vol/OI",
      unit: "ratio",
      title: "Volume divided by open interest.",
      text: "vol_oi_text",
      value: "vol_oi",
      peak: "vol_oi",
      reason: "vol_oi_reason",
    },
    {
      head: "P/C vol",
      unit: "ratio",
      title: "Put volume divided by call volume. Above 1 is put-heavy.",
      text: "pc_vol_text",
      value: "pc_vol_lean",
      peak: "pc_vol_lean",
      reason: "pc_vol_reason",
    },
    {
      head: "Pace",
      unit: "vs 20 sessions",
      title: "The strike's volume in the look-back against the same time of day over 20 sessions.",
      text: "pace_text",
      value: "pace",
      peak: "pace",
      reason: "pace_reason",
      hover: "pace_hover",
    },
    {
      head: "Bought−sold",
      unit: "contracts · est.",
      title: "Contracts traded above the middle of the quote less below it, in the look-back.",
      text: "bought_sold_text",
      value: "bought_sold",
      peak: "bought_sold",
      reason: "bought_sold_reason",
      hover: "bought_sold_hover",
      cls: "edge",
      th: "edge",
    },
    {
      head: "Flow",
      unit: "$ of stock · est.",
      title:
        "The stock the look-back's option trades would have the hedgers trade, on the convention.",
      text: "flow_text",
      value: "flow",
      peak: "flow",
      reason: "flow_reason",
      hover: "flow_hover",
    },
  ];

  // each column's width in pixels, the approved design's (mock-up version 4, decision 63)
  var WIDTHS = [
    96, 62, 54, 46, 190, 88, 58, 82, 62, 66, 82, 74, 70, 50, 58, 72, 54, 50, 54, 64, 72,
  ];

  function state() {
    return window.EdShell.getState();
  }

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;

  function isMatrix() {
    var st = state();
    return st.workspace === "trade-desk" && st.subview === "confluence";
  }

  // The matrix is the `confluence` panel (server.confluence) on the page's socket while this view
  // is on, at the page's one expiry choice (null, All Expirations: the program reads the front
  // expiry still open), at once and each time the chain or the levels change.
  function load() {
    window.EdShell.showPanel(
      "confluence",
      isMatrix() ? { expiry: window.EdShell.getExpiry() } : null,
    );
  }

  document.addEventListener("ed:panel", function (e) {
    var d = e.detail;
    var box = document.getElementById("cmBody");
    if (d.type !== "confluence" || !box || !isMatrix()) return;
    if (d.failed != null) {
      box.innerHTML = '<div class="placeholder"><div class="sm">' + esc(d.failed) + "</div></div>";
    } else {
      draw(d);
    }
  });

  // a cell's shade: its served number against its column's served peak, by the shell's one
  // strength rule in the theme's colours; a peak with no size shades as zero
  function shade(value, peak, heat) {
    if (value == null) return "";
    var t = window.EdDraw.strength(value, peak);
    var c = t == null ? heat.zero : window.EdDraw.heatFill(value, peak, heat);
    return (
      ' style="background:rgb(' +
      c.join(",") +
      ");color:" +
      window.EdDraw.heatInk(c) +
      ";font-weight:" +
      window.EdDraw.heatWeight(t) +
      '"'
    );
  }

  function tagsCell(col, row) {
    var tags = Array.isArray(row.tags) ? row.tags : [];
    return (
      '<td class="' +
      col.cls +
      '">' +
      tags
        .map(function (t) {
          return (
            '<span class="cm-tag ' +
            esc(t.lane) +
            '" title="' +
            esc(t.hover) +
            '">' +
            esc(t.text) +
            "</span>"
          );
        })
        .join("") +
      "</td>"
    );
  }

  function cell(col, row, peaks, heat) {
    if (col.tags) return tagsCell(col, row);
    var shown = row[col.text];
    var missing = shown == null || shown === "";
    var cls = [col.cls, missing ? "missing" : null].filter(Boolean).join(" ");
    var title = missing ? row[col.reason] : col.hover ? row[col.hover] : null;
    var peak = col.peak === "one" ? 1 : col.peak ? peaks[col.peak] : null;
    var paint = missing || !col.value ? "" : shade(row[col.value], peak, heat);
    return (
      '<td class="' +
      cls +
      '"' +
      (title ? ' title="' + esc(title) + '"' : "") +
      paint +
      ">" +
      (missing ? "-" : esc(shown)) +
      "</td>"
    );
  }

  // the price row, where the program placed it (price_row_index): the price, the two strikes it
  // falls between and Schwab's last trade, or its not-live mark
  function priceRow(body) {
    var when = body.spot_not_live_text
      ? body.spot_not_live_text
      : body.spot_time_ct
        ? "Schwab last trade " + body.spot_time_ct
        : "";
    var between = body.price_between_text ? body.price_between_text : "";
    return (
      '<tr class="price-row"><td colspan="' +
      COLS.length +
      '"><b>▸ Price ' +
      esc(orDash(body.spot_text)) +
      "</b> <span>" +
      esc([between, when].filter(Boolean).join(" · ")) +
      "</span></td></tr>"
    );
  }

  // the selected strike's served readings, each with its served hover words
  function showDetail(row) {
    var detail = document.getElementById("cmDetail");
    if (!detail) return;
    if (!row) {
      detail.innerHTML =
        '<div class="eyebrow">Selected strike</div><p>Click a strike for its readings.</p>';
      return;
    }
    var lines = [
      ["Composite", row.composite_text, row.composite_hover || row.composite_reason],
      ["Gamma if here", row.gamma_here_text, row.gamma_here_hover || row.gamma_here_reason],
      ["Visits", row.visits_text, row.visits_hover || row.visits_reason],
      ["Open interest", row.oi_text, row.oi_hover || row.oi_reason],
      ["ΔOI 1d", row.oi_change_text, row.oi_change_hover || row.oi_change_reason],
      ["Volume", row.volume_text, row.volume_hover || row.volume_reason],
      ["IV chg", row.iv_change_text, row.iv_change_hover || row.iv_change_reason],
      ["Bought−sold", row.bought_sold_text, row.bought_sold_hover || row.bought_sold_reason],
      ["Flow", row.flow_text, row.flow_hover || row.flow_reason],
    ];
    var tags = (Array.isArray(row.tags) ? row.tags : []).map(function (t) {
      return "<li>" + esc(t.hover) + "</li>";
    });
    detail.innerHTML =
      '<div class="eyebrow">Selected strike</div><h2>' +
      esc(orDash(row.strike_text) + " · " + orDash(row.distance_text) + " points from the price") +
      '</h2><dl class="cm-lines">' +
      lines
        .map(function (l) {
          return (
            "<dt>" +
            esc(l[0]) +
            "</dt><dd><b>" +
            esc(orDash(l[1])) +
            "</b>" +
            (l[2] ? " <span>" + esc(l[2]) + "</span>" : "") +
            "</dd>"
          );
        })
        .join("") +
      "</dl>" +
      (tags.length ? '<ul class="cm-taglist">' + tags.join("") + "</ul>" : "");
  }

  function onClick(e) {
    var box = document.getElementById("cmBody");
    if (!box || !box.contains(e.target)) return;
    var row = e.target.closest("tr[data-i]");
    if (!row) return;
    var picked = lastRows[Number(row.getAttribute("data-i"))];
    if (!picked) return;
    selectedStrike = picked.strike;
    box.querySelectorAll("tr[data-i]").forEach(function (other) {
      other.classList.toggle("selected", other === row);
    });
    showDetail(picked);
  }

  function bind() {
    if (bound) return;
    var box = document.getElementById("cmBody");
    if (!box) return;
    bound = true;
    box.addEventListener("click", onClick);
    box.addEventListener("keydown", function (e) {
      if ((e.key === "Enter" || e.key === " ") && e.target.closest("tr[data-i]")) {
        e.preventDefault();
        onClick(e);
      }
    });
  }

  // the served levels past the shown strikes (levels_above / levels_below), each after `arrow`
  function pastLevels(list, arrow) {
    return list
      .map(function (lv) {
        var words = [arrow, lv.text, "·", orDash(lv.distance_text), "·", orDash(lv.sigma_text)];
        return (
          '<span class="cm-past" title="' + esc(lv.hover) + '">' + esc(words.join(" ")) + "</span>"
        );
      })
      .join("");
  }

  function headline(h) {
    if (!h) return "";
    return (
      '<section class="cm-headline"><div class="eyebrow">COMPOSITE · THE KIND OF MOVE</div>' +
      '<div class="cm-kind ' +
      esc(h.tone || "") +
      '">' +
      esc(orDash(h.text)) +
      (h.text ? " <small>est.</small>" : "") +
      "</div><p>" +
      esc(orDash(h.note)) +
      "</p>" +
      (h.record ? '<p class="cm-record">Record: ' + esc(h.record) + "</p>" : "") +
      "</section>"
    );
  }

  function cards(list) {
    return (Array.isArray(list) ? list : [])
      .map(function (c) {
        return (
          '<div class="stat"' +
          (c.hover ? ' title="' + esc(c.hover) + '"' : "") +
          "><label>" +
          esc(c.label) +
          '</label><strong class="' +
          esc(c.tone || "") +
          '">' +
          esc(orDash(c.value)) +
          "</strong>" +
          (c.sub ? "<small>" + esc(c.sub) + "</small>" : "") +
          "</div>"
        );
      })
      .join("");
  }

  function draw(body) {
    var box = document.getElementById("cmBody");
    if (!box) return;
    bind();
    // the expiry the program read, as served (the one chosen, else the front one still open)
    var pick = body.expiry ? '<span class="cm-exp">Expiry ' + esc(body.expiry) + "</span>" : "";
    var rows = Array.isArray(body.rows) ? body.rows : [];
    var peaks = body.peaks || {},
      heat = window.EdShell.heatColors();
    lastRows = rows;
    var kept = null;
    rows.forEach(function (r) {
      if (r.strike === selectedStrike) kept = r;
    });
    if (kept == null) {
      rows.forEach(function (r) {
        if (r.spot_line && kept == null) kept = r;
      });
      if (kept == null && rows.length) kept = rows[0];
      selectedStrike = kept == null ? null : kept.strike;
    }
    var status = body.available ? orDash(body.status_text) : orDash(body.reason);
    var heads =
      "<tr>" +
      GROUPS.map(function (g) {
        return '<th class="' + g[2] + '" colspan="' + g[1] + '">' + esc(g[0]) + "</th>";
      }).join("") +
      "</tr><tr>" +
      COLS.map(function (col) {
        return (
          '<th tabindex="0"' +
          (col.title ? ' title="' + esc(col.title) + '"' : "") +
          (col.th ? ' class="' + col.th + '"' : "") +
          ">" +
          esc(col.head) +
          (col.unit ? "<small>" + esc(col.unit) + "</small>" : "") +
          "</th>"
        );
      }).join("") +
      "</tr>";
    var bodyRows = "";
    rows.forEach(function (row, i) {
      if (i === body.price_row_index) bodyRows += priceRow(body);
      bodyRows +=
        '<tr tabindex="0" class="data-row' +
        (row.strike === selectedStrike ? " selected" : "") +
        '" data-i="' +
        i +
        '">' +
        COLS.map(function (col) {
          return cell(col, row, peaks, heat);
        }).join("") +
        "</tr>";
    });
    if (body.price_row_index === rows.length && rows.length) bodyRows += priceRow(body);
    var notes = Array.isArray(body.notes) ? body.notes : [];
    var cols = WIDTHS.map(function (w) {
      return '<col style="width:' + w + 'px">';
    }).join("");
    var table = rows.length
      ? '<div class="frame" id="cmFrame"><div class="matrix-wrap"><table><colgroup>' +
        cols +
        "</colgroup><thead>" +
        heads +
        '</thead><tbody id="cmRows">' +
        bodyRows +
        "</tbody></table></div></div>"
      : '<div class="status">' + esc(orDash(body.reason)) + "</div>";
    box.innerHTML =
      '<div class="cm-page">' +
      headline(body.headline) +
      '<div class="summary">' +
      cards(body.cards) +
      '</div><div class="status"><span>' +
      esc(status) +
      "</span>" +
      pick +
      '</div><div class="offscreen" id="cmAbove">' +
      pastLevels(body.levels_above || [], "↑") +
      "</div>" +
      table +
      '<div class="offscreen" id="cmBelow">' +
      pastLevels(body.levels_below || [], "↓") +
      '</div><div class="legend"><span>Read first, left to right by importance: the Composite, where the strike is, what the hedging does there, the positions behind it, how time and volatility move them, the trading, and last the hedging-flow estimate.</span><span>Heat: each cell from the zero colour toward green (+) or red (−) by its value against its column\'s largest on the expiry; open interest, volume, Vol/OI, IV and Visits are size only (green); P/C red put-heavy, green call-heavy. est. and model rest on the convention: dealers long calls, short puts.</span></div><div class="detail" id="cmDetail"></div>' +
      (notes.length ? '<p class="foot">' + esc(notes.join(" ")) + "</p>" : "") +
      "</div>";
    showDetail(kept);
  }

  document.addEventListener("ed:view", function () {
    selectedStrike = null;
    load();
  });
  // a new expiry chosen is a new matrix: its own strikes
  document.addEventListener("ed:expiry", function () {
    selectedStrike = null;
    load();
  });
  document.addEventListener("ed:ticker", function () {
    selectedStrike = null;
    load();
  });
})();
