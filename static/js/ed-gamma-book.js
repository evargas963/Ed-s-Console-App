/* Ed Console — Options "Book" subview and the options lean's gauge. PRESENTATION ONLY.
   Options Book  <- the page's socket  (the `option_book:book` panel, push.option_book)
   Each strike's call and put: resting bid and ask (Schwab's newest OPTIONS_BOOK, every level
   summed) and volume today, then the summary and the options lean -- every number, word, share,
   scale and angle served; the page places the bars and the needle. Sent while the tab is on, at
   the selected expiry (null: the chain's front one) and the scope's window, at once and on each
   book or quote; a frame of an expiry no longer selected is not drawn. The gauge is the Trade
   Desk card's too (window.EdOptionLean). */
(function () {
  "use strict";

  var esc = window.EdShell.esc,
    orDash = window.EdShell.orDash,
    ticker = window.EdShell.ticker;

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
      (v == null ? "" : '<i style="width:' + window.EdDraw.pct(w) + '"></i>') +
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
          window.EdDraw.pct(lw) +
          '"></i><i class="r" style="width:' +
          window.EdDraw.pct(rw) +
          '"></i>') +
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
    // the books' own state, then the chain's: the rows' volumes and their listing are the chain's,
    // served with the levels verdict (its state word, its time and age, why)
    if (src)
      src.innerHTML = [
        window.EdShell.asOfBadge({
          label: "books",
          state: d.book_state,
          when: d.book_oldest_text,
          reason: d.book_outage,
        }),
        window.EdShell.asOfBadge({
          label: "chain",
          state: d.levels_state,
          when: d.levels_time_ct,
          age: d.levels_age_text,
          reason: d.levels_stale_reason,
        }),
      ].join("");
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
      '<div class="ob">' +
      (d.view.note ? '<div class="gbs-allexp">' + esc(d.view.note) + "</div>" : "") + // why not around the price
      '<div class="ob-scroll"><table class="ob-t"><thead><tr>' +
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

  // the panel is asked again for a new ticker, a new tab, a new scope (a new window) and a new
  // expiry; the first asking comes from ed-core.js's deferred ed:ticker and ed:view (its init())
  document.addEventListener("ed:ticker", loadBook);
  document.addEventListener("ed:view", loadBook); // fires on a subview change too
  document.addEventListener("ed:scope", loadBook);
  document.addEventListener("ed:expiry", loadBook);
})();
