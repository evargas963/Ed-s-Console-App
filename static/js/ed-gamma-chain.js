/* Ed Console — Options/Gamma "Chain" subview (D). PRESENTATION ONLY.
   Renders the full vendor chain ladder the socket's chain panel sends (strike_range=ALL, one expiry) — calls left,
   puts right, strike centre. Every field is served AS-IS from the vendor; this computes nothing and
   discloses the chain scope (complete / mismatch / fallback) honestly. The expiry is the workspace
   expiry dropdown (the socket's `expiries`); the ticker is the one selected-symbol state. */
(function () {
  "use strict";

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;
  function isChain() {
    var s = window.EdShell.getState();
    return s.workspace === "options" && s.subview === "chain";
  }

  function setSrc(d) {
    var el = document.getElementById("chSrc");
    if (!el) return;
    el.innerHTML = window.EdShell.chainScopeBadge(d);
  }

  // auto-scroll to spot only the first time a ticker+expiry is rendered
  var _lastScrollContext = null;
  // the rows the drawn ladder holds (render's `shape`)
  var _shape = null;

  // a cell's text: the served value, or '-' when none is served; written only when it changed
  function write(td, c, k) {
    var v = c ? c[k] : null;
    var text = v == null ? "-" : String(v);
    if (td.textContent !== text) td.textContent = text;
  }

  function curExpiry() {
    return window.EdShell.getExpiry();
  }
  // The ladder is the `chain:ladder` panel (push.chain) the program sends on the page's socket
  // while the Chain tab is on, at the selected expiry (null: the chain's front one), at once and
  // each time a chain is priced. Nothing received yet for the ticker on screen is '-'; a frame
  // of an expiry no longer selected (sent before the page asked another) is not drawn.
  var _ladderTicker = null;
  function load() {
    var host = document.getElementById("chainBody");
    if (!isChain()) {
      window.EdShell.showPanel("chain:ladder", null);
      return;
    }
    if (_ladderTicker !== window.EdShell.getState().ticker) {
      _ladderTicker = window.EdShell.getState().ticker;
      setSrc(null);
      if (host) window.EdShell.placeholder(host, "-");
    }
    window.EdShell.showPanel("chain:ladder", { expiry: curExpiry() });
  }
  document.addEventListener("ed:panel", function (e) {
    var d = e.detail,
      host = document.getElementById("chainBody");
    if (
      d.type !== "chain:ladder" ||
      !host ||
      !isChain() ||
      (curExpiry() && d.failed == null && d.expiry !== curExpiry())
    )
      return;
    if (d.failed != null) {
      setSrc(null);
      window.EdShell.placeholder(host, d.failed);
      return;
    }
    render(host, d);
  });

  function render(host, d) {
    setSrc(d);
    var rows = d.ladder; // served: strikes high to low, one row per listed contract
    if (!rows.length) {
      host.innerHTML =
        '<div class="placeholder"><div class="sm">' +
        esc(window.EdShell.chainEmptyText(d)) +
        "</div></div>";
      return;
    }
    var dup = d.has_duplicate_contracts === true; // served
    var desired = window.EdFlow.selected();
    // B: the chain panel is a COMPLETE SINGLE-EXPIRY surface — say so, name the exact expiry returned, and
    // flag when the workspace filter was null (the server chose the default expiry).
    var filterNull = !window.EdShell.getExpiry();
    var head =
      '<div class="chn-head"><span>SINGLE EXPIRY · ' +
      esc(orDash(d.expiry)) +
      (filterNull ? ' <span class="chn-default">(server default)</span>' : "") +
      " · " +
      esc(d.n_strikes) +
      " strikes" +
      (dup ? ' · <span class="chn-dup">duplicate contracts retained</span>' : "") +
      "</span>" +
      "<span>spot " +
      orDash(d.spot_text) +
      (d.spot_time_ct ? " · last trade " + esc(d.spot_time_ct) : "") +
      "</span></div>";
    // a served text, or every digit Schwab sent (its Greeks)
    function cell(c, k) {
      var v = c ? c[k] : null;
      return v == null ? "-" : esc(String(v));
    }
    function sym(c) {
      return c && c.symbol ? String(c.symbol) : "";
    }
    function selAttr(c) {
      var s = sym(c);
      return s ? ' data-sym="' + esc(s) + '"' + (s === desired ? ' data-selc="1"' : "") : "";
    }
    // No `position:sticky`: the header table is a FROZEN (non-scrolling) sibling of a separate
    // scrollable `.chn-scroll` div holding only the body table (index.html's
    // #chainBody/.chn-scroll rules), the standard "frozen header" layout. A shared
    // fixed-percentage <colgroup> on both tables keeps every column pixel-aligned between them
    // despite being unrelated table layouts.
    var COLGROUP =
      "<colgroup>" +
      new Array(8).join('<col style="width:6.25%">') +
      '<col style="width:12.5%">' +
      new Array(8).join('<col style="width:6.25%">') +
      "</colgroup>";
    var h =
      '<table class="chn chn-headtbl">' +
      COLGROUP +
      "<thead><tr>" +
      '<th colspan="7" class="cflag" style="text-align:center">Calls</th><th class="mid">Strike</th>' +
      '<th colspan="7" class="pflag" style="text-align:center">Puts</th></tr>' +
      '<tr><th>OI</th><th>Vol</th><th>IV (%)</th><th>Δ</th><th>Γ</th><th>Bid</th><th>Ask</th><th class="mid"></th>' +
      "<th>Bid</th><th>Ask</th><th>Γ</th><th>Δ</th><th>IV (%)</th><th>Vol</th><th>OI</th></tr></thead></table>" +
      '<div class="chn-scroll" id="chainScroll">' +
      head +
      '<table class="chn chn-bodytbl">' +
      COLGROUP +
      "<tbody>";
    // open interest, volume, IV, bid and ask: the served texts; delta and gamma as Schwab sent them
    var CALL = ["oi_text", "volume_text", "iv_text", "delta", "gamma", "bid_text", "ask_text"];
    var PUT = ["bid_text", "ask_text", "gamma", "delta", "iv_text", "volume_text", "oi_text"];
    // The ladder comes again with each quote Schwab streams. While its rows are the ones drawn
    // (the same strikes, contracts, spot row, in-the-money sides and selected contract), only
    // the texts that changed are written, in place: the table, its scroll and its rows' clicks
    // stay, and a quote costs the cells it moved, not a new table.
    var shape =
      d.expiry +
      "|" +
      desired +
      "|" +
      rows
        .map(function (r) {
          return [r.strike, r.first, r.spot, sym(r.call), sym(r.put), r.call_itm, r.put_itm];
        })
        .join(";");
    var drawn = host.querySelector(".chn-bodytbl");
    if (shape === _shape && drawn) {
      host.querySelector(".chn-head").outerHTML = head;
      var trs = drawn.tBodies[0].rows;
      rows.forEach(function (r, i) {
        var tds = trs[i].cells;
        CALL.forEach(function (f, j) {
          write(tds[j], r.call, f);
        });
        PUT.forEach(function (f, j) {
          write(tds[8 + j], r.put, f);
        });
      });
      return;
    }
    _shape = shape;
    function side(c, cls, itm, cols) {
      // itm: served per row, Schwab's (its money intrinsic value positive)
      var klass =
        cls + (c && sym(c) === desired ? " chn-selc" : "") + (itm === true ? " chn-itm" : "");
      return cols
        .map(function (f, j) {
          return (
            '<td class="' + klass + '"' + (j === 0 ? selAttr(c) : "") + ">" + cell(c, f) + "</td>"
          );
        })
        .join("");
    }
    rows.forEach(function (r) {
      var c = r.call,
        p = r.put,
        k = r.strike;
      h +=
        "<tr" +
        (r.spot ? ' class="spot"' : "") +
        ' data-strike="' +
        k +
        '"' +
        (c ? ' data-csym="' + esc(sym(c)) + '"' : "") +
        (p ? ' data-psym="' + esc(sym(p)) + '"' : "") +
        ">" +
        side(c, "chn-call", r.call_itm, CALL) +
        '<td class="k">' +
        (r.first ? r.strike_text : "·") +
        "</td>" +
        side(p, "chn-put", r.put_itm, PUT) +
        "</tr>";
    });
    h += "</tbody></table></div>"; // close .chn-scroll
    // `.chn-scroll` (the actual scrolling element) is a NEW DOM node on every render, so its
    // scrollTop is captured here, before the old `.chn-scroll` is torn out by the innerHTML
    // replacement below, and restored onto the new one afterward -- a routine refresh leaves
    // the operator's own scroll position alone.
    var oldScroll = host.querySelector(".chn-scroll");
    var savedScrollTop = oldScroll ? oldScroll.scrollTop : 0;
    host.innerHTML = h;
    // C: the CALL side selects the exact CALL vendor symbol, the PUT side the exact PUT symbol; the
    // centre Strike selects ONLY the shared strike. The symbol is the vendor's own, verbatim — never
    // reconstructed. A contract click selects it for Flow (EdFlow); it asks Schwab for nothing.
    host.querySelectorAll("tr[data-strike]").forEach(function (tr) {
      tr.addEventListener("click", function (e) {
        var k = Number(tr.getAttribute("data-strike"));
        var cell = e.target.closest ? e.target.closest("td") : null;
        if (cell && cell.classList.contains("chn-call") && tr.getAttribute("data-csym"))
          return selectContract(tr.getAttribute("data-csym"), k, d.expiry);
        if (cell && cell.classList.contains("chn-put") && tr.getAttribute("data-psym"))
          return selectContract(tr.getAttribute("data-psym"), k, d.expiry);
        window.EdShell.setStrike(k, d.expiry); // centre strike -> shared strike only
      });
    });
    var context = window.EdShell.getState().ticker + "|" + d.expiry;
    var isNewContext = context !== _lastScrollContext;
    _lastScrollContext = context;
    if (isNewContext) {
      var sr = host.querySelector("tr.spot");
      if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: "center" });
    } else {
      var newScroll = host.querySelector(".chn-scroll");
      if (newScroll) newScroll.scrollTop = savedScrollTop;
    }
  }

  function selectContract(symbol, strike, expiry) {
    window.EdShell.setStrike(strike, expiry); // exact strike + expiry = shared context
    var host = document.getElementById("chainBody");
    if (host) {
      host.querySelectorAll(".chn-selc").forEach(function (n) {
        n.classList.remove("chn-selc");
      });
      host
        .querySelectorAll(
          '[data-sym="' + (window.CSS && CSS.escape ? CSS.escape(symbol) : symbol) + '"]',
        )
        .forEach(function (n) {
          n.classList.add("chn-selc");
        });
    }
    window.EdFlow.select(symbol);
  }

  document.addEventListener("ed:view", load); // fires on subview change too
  document.addEventListener("ed:ticker", load);
  document.addEventListener("ed:expiry", load);
})();
