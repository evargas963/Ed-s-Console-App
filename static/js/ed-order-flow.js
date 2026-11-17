/* Ed Console — Order Flow / "Book · DOM" subview. PRESENTATION ONLY.
   Real L2 book microstructure for the UNDERLYING ticker itself (NASDAQ_BOOK/NYSE_BOOK): the
   `book` panel on the page's socket, from the SAME calc.order_flow.
   compute_book_microstructure the options Flow tab reads. Reuses that view's .fl-* CSS grammar
   so a book reads the same whether it's an option contract's or the ticker's own.

   The console streams the books of the ticker a page has selected; a book not yet arrived reads
   "No <venue> for <ticker>". */
(function () {
  "use strict";

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash;
  var ticker = window.EdShell.ticker,
    classOf = window.EdShell.classOf;
  function isBook() {
    var s = window.EdShell.getState();
    return s.workspace === "order-flow" && s.subview === "book";
  }
  function host() {
    return document.getElementById("obBody");
  }

  // The book is the `book:dom` panel (push.book) the program sends on the page's socket while
  // this view is on, for the selected venue, at once and with each streamed quote or book.
  // Nothing received yet for the ticker on screen is '-'.
  var _bookTicker = null;
  function load() {
    var h = host();
    if (!isBook()) {
      window.EdShell.showPanel("book:dom", null);
      return;
    }
    if (_bookTicker !== ticker()) {
      _bookTicker = ticker();
      if (h) window.EdShell.placeholder(h, "-");
    }
    window.EdShell.showPanel("book:dom", { venue: window.EdShell.getState().bookVenue });
  }
  document.addEventListener("ed:panel", function (e) {
    var d = e.detail,
      h = host();
    if (d.type !== "book:dom" || !h || !isBook()) return;
    if (d.failed != null) window.EdShell.placeholder(h, d.failed);
    else render(h, ticker(), d);
  });

  var tag = window.EdShell.classTag;
  function section(title, rows) {
    var h = '<div class="fl-sec"><div class="fl-sec-h">' + esc(title) + "</div>";
    rows.forEach(function (r) {
      h +=
        '<div class="fl-row"><span class="k">' +
        esc(r[0]) +
        '</span><span class="v">' +
        esc(r[1]) +
        "</span>" +
        tag(r[2]) +
        "</div>";
    });
    return h + "</div>";
  }

  // Per-level DOM ladder from d.depth_pressure.{bid,ask} -- [{price,volume,cum}], best-first,
  // up to OF_BOOK_DEPTH_DEEP (5) levels of the displayed book, as served, each bar against the
  // served largest size (depth_pressure.max_volume).
  function ladderHtml(bidLevels, askLevels, maxVol, wallSet) {
    function row(l, side) {
      var w = window.EdDraw.barWidth(l.volume, maxVol);
      var isWall = wallSet[side + "@" + l.price];
      return (
        '<div class="dom-row ' +
        side +
        (isWall ? " wall" : "") +
        '">' +
        '<div class="dom-bar-track"><i class="dom-bar" style="width:' +
        w +
        '%"></i></div>' +
        '<span class="dom-px">' +
        l.price_text +
        '</span><span class="dom-sz">' +
        esc(orDash(l.volume_text)) +
        "</span></div>"
      );
    }
    var asksHtml = askLevels
      .slice()
      .reverse()
      .map(function (l) {
        return row(l, "ask");
      })
      .join("");
    var bidsHtml = bidLevels
      .map(function (l) {
        return row(l, "bid");
      })
      .join("");
    return (
      '<div class="dom-side-label">Ask</div>' +
      (asksHtml || '<div class="sm" style="padding:4px 8px;">no displayed asks</div>') +
      bidsHtml +
      (bidsHtml ? "" : '<div class="sm" style="padding:4px 8px;">no displayed bids</div>') +
      '<div class="dom-side-label">Bid</div>'
    );
  }

  function render(h, tk, d) {
    if (d.status === "no_book") {
      h.innerHTML =
        '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' +
        esc(tk) +
        "</span></div>" +
        '<div class="fl-sub"><span class="fl-lab">Book</span><span class="fl-badge warn">NO BOOK YET</span></div></div>' +
        '<div class="placeholder"><div class="sm">No ' +
        esc(window.EdShell.getState().bookVenue) +
        " for " +
        esc(tk) +
        " — Schwab has sent no book from this venue for this symbol.</div></div>";
      return;
    }
    // always served (engine.compute_book_microstructure)
    var tob = d.top_of_book,
      depth = d.depth,
      ages = d.ages,
      cls = d.classification;
    var bidLevels = d.depth_pressure.bid,
      askLevels = d.depth_pressure.ask;
    function bk(k) {
      return classOf(cls, k);
    }
    var walls = d.wall_candidates;
    var wallSet = {};
    walls.forEach(function (w) {
      wallSet[w.side + "@" + w.price] = w;
    });

    var midHtml =
      '<div class="dom-mid"><span>mark ' +
      orDash(d.mark_text) +
      "</span><span>spread " +
      orDash(d.spread_pts_text) +
      "</span><span>microprice " +
      orDash(d.microprice_text) +
      "</span></div>";

    var rowsTob = [
      [
        "Bid × size",
        orDash(tob.bid_text) + " × " + orDash(tob.bid_size_text),
        bk("top_of_book.bid"),
      ],
      [
        "Ask × size",
        orDash(tob.ask_text) + " × " + orDash(tob.ask_size_text),
        bk("top_of_book.ask"),
      ],
    ];
    var rowsImb = [
      ["Depth 1 imbalance", orDash(depth["1"].imbalance_text), bk("depth.*.imbalance")],
      ["Depth 3 imbalance", orDash(depth["3"].imbalance_text), bk("depth.*.imbalance")],
      ["Depth 5 imbalance", orDash(depth["5"].imbalance_text), bk("depth.*.imbalance")],
      ["Bid total (5)", orDash(depth["5"].bid_total_text), bk("depth.*.bid_total")],
      ["Ask total (5)", orDash(depth["5"].ask_total_text), bk("depth.*.ask_total")],
    ];
    var fresh = [
      [
        "Book age",
        d.book_when_age_text == null ? "-" : d.book_when_age_text,
        bk("ages.book_age_sec"),
      ],
      [
        "Quote age",
        d.quote_when_age_text == null ? "-" : d.quote_when_age_text,
        bk("ages.quote_age_sec"),
      ],
    ];
    var wallsHtml = walls.length
      ? walls
          .map(function (w) {
            return (
              '<div class="fl-row"><span class="k">' +
              esc(orDash(w.side)) +
              " @ " +
              w.price_text +
              '</span><span class="v">' +
              esc(orDash(w.volume_text)) +
              ' <span class="sm">(' +
              w.median_mult_text +
              "× median)</span></span></div>"
            );
          })
          .join("")
      : '<div class="sm" style="padding:4px 0;">no size-outlier candidates in the current displayed book</div>';
    var deferred = d.deferred.join(" · ");

    // the book's served word (book_feed_label: LIVE, OFFLINE, NOT LIVE); no book age served reads
    // AGE UNKNOWN, never live
    var bs = ages.book_stale,
      badge = bs == null ? "AGE UNKNOWN" : d.book_feed_label;
    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' +
      esc(tk) +
      "</span></div>" +
      '<div class="fl-sub"><span class="fl-lab">Book</span><span class="fl-badge ' +
      (bs === false ? "live" : "stale") +
      '">' +
      badge +
      "</span></div></div>" +
      '<div class="dom-wrap">' +
      '<div class="dom-ladder">' +
      ladderHtml(bidLevels, askLevels, d.depth_pressure.max_volume, wallSet) +
      midHtml +
      "</div>" +
      '<div class="dom-stats">' +
      section("Top of book" + (d.top_outage ? " · " + d.top_feed_label : ""), rowsTob) +
      section("Imbalance", rowsImb) +
      section("Freshness", fresh) +
      "</div>" +
      "</div>" +
      '<div class="fl-sec" style="margin-top:14px;"><div class="fl-sec-h">Wall candidates (size-outlier heuristic, displayed book only)</div>' +
      wallsHtml +
      "</div>" +
      '<div class="fl-foot">' +
      (deferred ? esc(deferred) + " — " : "") +
      "no signed buys/sells, CVD, or bull/bear verdict is canonical for the underlying; Schwab exposes no native aggressor field.</div>";
  }

  document.addEventListener("ed:view", load);
  document.addEventListener("ed:ticker", load);
  document.addEventListener("ed:book_venue", load);
  // initial hydration comes only from ed-core.js's deferred ed:ticker/ed:view dispatch
  // (that file's init() comment)
})();
