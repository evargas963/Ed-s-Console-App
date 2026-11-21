/* Trade Desk / Confluence Matrix. Draws the `confluence` panel. Computes nothing financial.
   Pill positions are display geometry between the served strikes. */
(function () {
  "use strict";

  var selectedStrike = null;
  var pinned = null;
  var lastRows = [];
  var lastNames = {};
  var lastSpot = null;
  var lastSpotText = null;
  var lastBody = null;
  var bound = false;

  var HEADS = [
    ["Price / session", "exact price", "Session reference levels. POC keeps its est mark.", false],
    [
      "Options levels",
      "chain + same-day",
      "Chain levels and the same-day levels, each at its own price.",
      false,
    ],
    ["Strike", "", "Listed strike.", false],
    ["Δ spot", "points", "Strike minus the live price.", false],
    [
      "Composite",
      "size, not direction",
      "How large this strike's positions and activity are against the expiry's other strikes, up to the preset ceiling. It carries no direction.",
      true,
    ],
    ["Net GEX", "$ / 1%", "Net gamma exposure in dollars per 1% move.", false],
    ["OI", "contracts", "Open interest in contracts. Green intensity shows size.", false],
    ["P/C GEX", "ratio", "Put gamma divided by call gamma. Above 1 is put-heavy.", false],
    [
      "Gross GEX",
      "$ / 1%",
      "Call gamma plus put gamma, in dollars per 1% move. Green shows size.",
      true,
    ],
    ["ΔGEX", "$ / 1%", "No change in gamma is produced.", false],
    [
      "Opt Vol",
      "contracts",
      "Options volume this session, in contracts. Green intensity shows size.",
      false,
    ],
    ["P/C vol", "ratio", "Put volume divided by call volume. Above 1 is put-heavy.", false],
    ["Vol/OI", "ratio", "Options volume divided by open interest.", false],
    ["Flow", "signed $", "No signed flow is produced.", true],
    ["DEX", "$", "Delta exposure in dollars.", false],
    ["Vanna", "$ / vol pt", "Vanna in dollars per volatility point.", false],
    ["IV", "%", "Implied volatility for the strike.", false],
    ["Charm", "shares/day", "Charm in delta-shares per day.", false],
  ];

  function state() {
    return window.EdShell.getState();
  }

  function text(value) {
    if (value == null) return "-";
    if (value === "") return "-";
    return String(value);
  }

  function regimeWords(code) {
    var table = window.EdGammaRegime;
    if (!table || code == null) return "-";
    var row = table[code];
    if (!row || row.t == null) return "-";
    return row.t;
  }

  var esc = window.EdShell.esc;

  function isMatrix() {
    var st = state();
    return st.workspace === "trade-desk" && st.subview === "confluence";
  }

  // The matrix is the `confluence` panel (server.confluence) on the page's socket while this view
  // is on, at the page's one expiry choice (null, All Expirations: the program ranks the front
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

  // the matrix's rows are this tall; the rail is drawn against them
  var ROW_PX = 52;

  // the served rail (push.confluence._rail): each price line and each lane's levels inside the rows; the
  // page places them
  function rails(rows, lines, lanes) {
    var n = rows.length;
    var height = n * ROW_PX;
    if (!n) return "";
    var strikes = rows.map(function (r) {
      return r.strike;
    });
    var anchorY = function (price) {
      return window.EdDraw.rowAnchorY(price, strikes, ROW_PX);
    };
    var svg =
      '<svg viewBox="0 0 276 ' +
      height +
      '" width="276" height="' +
      height +
      '" aria-label="Price levels">';
    lines.forEach(function (lv) {
      var start = lv.session ? 8 : 146;
      svg +=
        '<path class="price-line" data-price="' +
        esc(lv.price_text) +
        '" d="M' +
        start +
        " " +
        anchorY(lv.price) +
        ' H290" stroke="#718198" opacity=".7"/>';
    });
    ["session", "options"].forEach(function (lane, laneIndex) {
      var group = lanes[lane];
      var pos = window.EdDraw.stackLabels(
        group.map(function (o) {
          return anchorY(o.price);
        }),
        height,
        25,
        12,
      );
      group.forEach(function (lv, index) {
        var x = laneIndex * 138 + 7;
        var anchor = anchorY(lv.price);
        var label = pos[index];
        var connector = window.EdDraw.apart(label, anchor)
          ? '<path d="M' +
            (x + 120) +
            " " +
            label +
            " L" +
            (x + 126) +
            " " +
            anchor +
            '" fill="none" stroke="#8b9db5"/>'
          : "";
        svg +=
          '<g class="level-pill" role="button" tabindex="0" data-price="' +
          esc(lv.price_text) +
          '" aria-label="' +
          esc(lv.title + " " + lv.price_text) +
          '"><title>' +
          esc(lv.title + ": " + lv.price_text) +
          "</title>" +
          connector +
          '<rect x="' +
          x +
          '" y="' +
          (label - 10) +
          '" width="120" height="20" rx="3" fill="#111b29" stroke="#56677f"/><text x="' +
          (x + 60) +
          '" y="' +
          (label + 4) +
          '" text-anchor="middle" fill="white" font-size="10" font-weight="700">' +
          esc(lv.abbrev + " " + lv.price_text) +
          "</text></g>";
      });
    });
    return svg + "</svg>";
  }

  // the served levels past the shown strikes (push.confluence._rail: levels_above / levels_below)
  function offButtons(list, side) {
    return list
      .map(function (lv) {
        var prefix = side === "above" ? "↑ " : "↓ ";
        return (
          '<button type="button" data-price="' +
          esc(lv.price_text) +
          '" title="' +
          esc(lv.title + " · outside visible strike range") +
          '">' +
          esc(prefix + lv.abbrev + " " + lv.price_text) +
          "</button>"
        );
      })
      .join("");
  }

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

  function heatCell(shown, value, peak, heat, reason, edge) {
    var missing = shown == null || shown === "";
    var cls = (edge ? "edge " : "") + (missing ? "missing" : "");
    var title = missing && reason ? ' title="' + esc(reason) + '"' : "";
    var paint = missing ? "" : shade(value, peak, heat);
    return '<td class="' + cls + '"' + title + paint + ">" + (missing ? "-" : esc(shown)) + "</td>";
  }

  function showDetail(row) {
    var detail = document.getElementById("cmDetail");
    if (!detail) return;
    if (!row) {
      detail.innerHTML =
        '<div class="eyebrow">Selected strike</div><p>Click a strike for its numbers.</p>';
      return;
    }
    var missing = Array.isArray(row.missing) ? row.missing : [];
    var parts = Array.isArray(row.contributions) ? row.contributions : [];
    var factors = Array.isArray(row.factors) ? row.factors : [];
    var ceiling = lastBody && lastBody.ceiling != null ? lastBody.ceiling : null;
    var scoreLine =
      row.score == null ? text(missing.join(", ")) : text(row.score_text) + " / " + text(ceiling);
    var facts = [
      ["Net GEX", row.net_gex_text, row.net_reason, "$ per 1% move", "M"],
      ["Open interest", row.oi_text, row.oi_reason, "contracts", ""],
      ["Options Volume", row.volume_text, row.volume_reason, "session contracts", ""],
      ["IV", row.iv_text, row.iv_reason, "implied volatility", "%"],
      ["Flow", row.flow_text, row.flow_reason, "premium dollars", "M"],
      ["Charm", row.charm_text, row.charm_reason, "delta-shares / day", "k"],
    ];
    var cards = facts
      .map(function (f) {
        var missingValue = f[1] == null || f[1] === "";
        var caption = missingValue && f[2] ? f[2] : f[3];
        var shown = missingValue ? "-" : String(f[1]) + f[4];
        return (
          '<div class="card"><label>' +
          esc(f[0]) +
          "</label><b>" +
          esc(shown) +
          "</b><span>" +
          esc(caption) +
          "</span></div>"
        );
      })
      .join("");
    var why = parts
      .map(function (p) {
        return p.label + " " + p.text;
      })
      .join(" · ");
    var lines = factors.map(function (p) {
      return (
        p.label +
        " " +
        p.text +
        "  raw " +
        text(p.raw_text) +
        "  norm " +
        text(p.normalized_text) +
        "  weight " +
        text(p.weight_text)
      );
    });
    var note = why;
    if (lines.length) note += (note ? "\n" : "") + lines.join("\n");
    if (missing.length && row.score == null) note += (note ? "\n" : "") + missing.join(", ");
    detail.innerHTML =
      '<div class="eyebrow">Selected strike</div><h2>' +
      esc(text(row.strike_text) + " · " + text(row.distance_text) + " points from spot") +
      "</h2><p>Composite " +
      esc(scoreLine) +
      '</p><div class="cards">' +
      cards +
      "</div>" +
      (note ? '<p class="note">' + esc(note) + "</p>" : "");
  }

  function highlight(priceText) {
    var box = document.getElementById("cmBody");
    if (!box) return;
    box.querySelectorAll("[data-price]").forEach(function (el) {
      var on = priceText != null && el.getAttribute("data-price") === priceText;
      el.classList.toggle("lit", on);
      el.classList.toggle("pinned", on);
    });
    var read = document.getElementById("cmRead");
    if (!read) return;
    if (priceText == null) {
      read.textContent =
        "Hover or focus a level; click to pin its line. Escape clears the selection.";
      return;
    }
    var line = lastNames[priceText] + " · " + priceText;
    if (pinned === priceText) line += " · PINNED";
    read.textContent = line;
  }

  function position() {
    var line = document.getElementById("spotline");
    var tbody = document.getElementById("cmRows");
    if (!line || !tbody) return;
    var trs = tbody.querySelectorAll("tr");
    var wrap = tbody.closest(".matrix-wrap");
    if (!trs.length || lastSpot == null || !wrap) {
      line.style.display = "none";
      return;
    }
    var wrapRect = wrap.getBoundingClientRect();
    var points = Array.prototype.map.call(trs, function (tr, i) {
      return {
        price: lastRows[i].strike,
        y: window.EdDraw.middleY(tr.getBoundingClientRect(), wrapRect),
      };
    });
    var top = window.EdDraw.priceY(lastSpot, points);
    if (top == null) {
      line.style.display = "none";
      return;
    }
    line.style.display = "";
    line.style.top = top + "px";
    line.innerHTML = "<span>SPOT " + esc(text(lastSpotText)) + "</span>";
  }

  function onClick(e) {
    var box = document.getElementById("cmBody");
    if (!box || !box.contains(e.target)) return;
    var level = e.target.closest("[data-price]");
    if (level) {
      var priceText = level.getAttribute("data-price");
      pinned = pinned === priceText ? null : priceText;
      highlight(pinned);
      return;
    }
    var row = e.target.closest("tr[data-i]");
    if (!row || e.target.closest(".rail")) return;
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
    box.addEventListener("mouseover", function (e) {
      var level = e.target.closest("[data-price]");
      if (level && box.contains(level)) highlight(level.getAttribute("data-price"));
    });
    box.addEventListener("mouseout", function (e) {
      var level = e.target.closest("[data-price]");
      if (!level || !box.contains(level)) return;
      if (e.relatedTarget && level.contains(e.relatedTarget)) return;
      highlight(pinned);
    });
    box.addEventListener("focusin", function (e) {
      var level = e.target.closest("[data-price]");
      if (level) highlight(level.getAttribute("data-price"));
    });
    box.addEventListener("focusout", function () {
      highlight(pinned);
    });
    box.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        pinned = null;
        highlight(null);
        return;
      }
      var pill = e.target.closest(".level-pill");
      var row = e.target.closest("tr[data-i]");
      if ((e.key === "Enter" || e.key === " ") && (pill || row)) {
        e.preventDefault();
        onClick(e);
      }
    });
    window.addEventListener("resize", function () {
      position();
    });
  }

  function draw(body) {
    var box = document.getElementById("cmBody");
    if (!box) return;
    bind();
    lastBody = body;
    // the expiry the program ranked, as served (the one chosen, else the front one still open)
    var pick = body.expiry ? '<span class="cm-exp">Expiry ' + esc(body.expiry) + "</span>" : "";
    var rows = Array.isArray(body.rows) ? body.rows : [];
    var peaks = body.peaks,
      heat = window.EdShell.heatColors(); // each column's served scale
    lastRows = rows;
    lastNames = body.level_names;
    lastSpot = typeof body.spot === "number" ? body.spot : null;
    lastSpotText = body.spot_text;
    if (
      !rows.some(function (r) {
        return r.strike === selectedStrike;
      })
    ) {
      var fallback = null;
      rows.forEach(function (r) {
        if (r.spot_line && fallback == null) fallback = r;
      });
      if (fallback == null && rows.length) fallback = rows[0];
      selectedStrike = fallback == null ? null : fallback.strike;
    }
    var summary = [
      // a price that has stopped: the served mark (time and age) stands for every value from it
      [
        "SPOT",
        body.spot_text,
        body.spot_not_live_text
          ? body.spot_not_live_text
          : body.spot_time_ct
            ? "last trade " + body.spot_time_ct
            : "",
      ],
      ["GAMMA REGIME · CHAIN", regimeWords(body.regime), ""],
      ["MODELED FLIP · CHAIN", body.flip_text, body.expiry ? body.expiry : ""],
      ["PIN · CHAIN", body.pin_text, body.pin_text ? "expiry closing today" : "", body.pin_note],
    ]
      .map(function (cell) {
        var small = cell[2] ? "<small>" + esc(cell[2]) + "</small>" : "";
        var hover = cell[3] ? ' title="' + esc(cell[3]) + '"' : ""; // the served note
        return (
          '<div class="stat"' +
          hover +
          "><label>" +
          esc(cell[0]) +
          "</label><strong>" +
          esc(text(cell[1])) +
          "</strong>" +
          small +
          "</div>"
        );
      })
      .join("");
    var status = body.available ? text(body.status_text) : text(body.reason);
    var heads =
      '<tr><th class="group edge" colspan="5">Price context</th><th class="group edge" colspan="4">Positioning</th><th class="group edge" colspan="5">Activity</th><th class="group" colspan="4">Sensitivity</th></tr><tr>';
    HEADS.forEach(function (col, index) {
      var secondary = "<small>" + esc(col[1]) + "</small>";
      if (index === 4) {
        secondary += "<small>" + esc(text(body.scale_text)) + "</small>";
        if (body.preset) secondary += "<small>" + esc(body.preset) + "</small>";
      }
      heads +=
        '<th tabindex="0" title="' +
        esc(col[2]) +
        '"' +
        (col[3] ? ' class="edge"' : "") +
        ">" +
        esc(col[0]) +
        secondary +
        "</th>";
    });
    heads += "</tr>";
    var bodyRows = "";
    rows.forEach(function (row, i) {
      var scoreShown =
        row.score_text == null
          ? ""
          : '<button type="button" class="score" aria-label="Inspect strike ' +
            esc(text(row.strike_text)) +
            '">' +
            esc(row.score_text) +
            " ›</button>";
      var scoreReason = Array.isArray(row.missing) ? row.missing.join(", ") : "";
      bodyRows +=
        '<tr tabindex="0" class="data-row' +
        (row.strike === selectedStrike ? " selected" : "") +
        '" data-i="' +
        i +
        '">';
      if (i === 0) {
        bodyRows +=
          '<td class="rail edge" colspan="2" rowspan="' +
          rows.length +
          '">' +
          rails(rows, body.rail_lines, body.rail_lanes) +
          "</td>";
      }
      bodyRows += '<td class="strike">' + esc(text(row.strike_text)) + "</td>";
      bodyRows += "<td>" + esc(text(row.distance_text)) + "</td>";
      if (row.score_text == null) {
        bodyRows += '<td class="edge missing" title="' + esc(scoreReason) + '">-</td>';
      } else {
        bodyRows +=
          '<td class="edge"' + shade(row.score, body.ceiling, heat) + ">" + scoreShown + "</td>";
      }
      bodyRows += heatCell(
        row.net_gex_text,
        row.net_gex,
        peaks.net_gex,
        heat,
        row.net_reason,
        false,
      );
      bodyRows += heatCell(row.oi_text, row.oi, peaks.oi, heat, row.oi_reason, false);
      bodyRows += heatCell(
        row.pc_gex_text,
        row.pc_gex_lean,
        peaks.pc_gex_lean,
        heat,
        row.pc_gex_reason,
        false,
      );
      bodyRows += heatCell(row.gross_text, row.gross, peaks.gross, heat, row.gross_reason, true);
      bodyRows += heatCell(row.dgex_text, null, null, heat, row.dgex_reason, false);
      bodyRows += heatCell(
        row.volume_text,
        row.volume,
        peaks.volume,
        heat,
        row.volume_reason,
        false,
      );
      bodyRows += heatCell(
        row.pc_vol_text,
        row.pc_vol_lean,
        peaks.pc_vol_lean,
        heat,
        row.pc_vol_reason,
        false,
      );
      bodyRows += heatCell(
        row.vol_oi_text,
        row.vol_oi,
        peaks.vol_oi,
        heat,
        row.vol_oi_reason,
        false,
      );
      bodyRows += heatCell(row.flow_text, null, null, heat, row.flow_reason, true);
      bodyRows += heatCell(row.dex_text, row.dex, peaks.dex, heat, row.dex_reason, false);
      bodyRows += heatCell(row.vanna_text, row.vanna, peaks.vanna, heat, row.vanna_reason, false);
      bodyRows += heatCell(row.iv_text, row.iv, peaks.iv, heat, row.iv_reason, false);
      bodyRows += heatCell(row.charm_text, row.charm, peaks.charm, heat, row.charm_reason, false);
      bodyRows += "</tr>";
    });
    var notes = Array.isArray(body.notes) ? body.notes : [];
    var table = rows.length
      ? '<div class="frame" id="cmFrame"><div class="matrix-wrap"><table><colgroup><col style="width:138px"><col style="width:138px"><col style="width:74px"><col style="width:58px"><col style="width:75px"><col span="13"></colgroup><thead>' +
        heads +
        '</thead><tbody id="cmRows">' +
        bodyRows +
        '</tbody></table><div id="spotline"></div></div></div>'
      : '<div class="status">' + esc(text(body.reason)) + "</div>";
    var kept = null;
    rows.forEach(function (row) {
      if (row.strike === selectedStrike) kept = row;
    });
    box.innerHTML =
      '<div class="cm-page"><div class="summary">' +
      summary +
      '</div><div class="status"><span>' +
      esc(status) +
      "</span>" +
      pick +
      '</div><div class="offscreen" id="cmAbove">' +
      offButtons(body.levels_above, "above") +
      "</div>" +
      table +
      '<div class="offscreen" id="cmBelow">' +
      offButtons(body.levels_below, "below") +
      '</div><div class="levelread" id="cmRead">Hover or focus a level; click to pin its line. Escape clears the selection.</div><div class="legend"><span><i class="scale"></i> Red − / green + · brighter = larger magnitude within each column.</span><span>OI, Opt Vol, Gross GEX, IV and composite: green intensity = size only. P/C: red put-heavy / green call-heavy.</span></div><div class="detail" id="cmDetail"></div>' +
      (notes.length ? '<p class="foot">' + esc(notes.join(" ")) + "</p>" : "") +
      "</div>";
    showDetail(kept);
    highlight(pinned);
    requestAnimationFrame(position);
  }

  document.addEventListener("ed:view", function () {
    selectedStrike = null;
    load();
  });
  // a new expiry chosen is a new ranking: its own strikes
  document.addEventListener("ed:expiry", function () {
    selectedStrike = null;
    pinned = null;
    load();
  });
  document.addEventListener("ed:ticker", function () {
    selectedStrike = null;
    pinned = null;
    load();
  });
})();
