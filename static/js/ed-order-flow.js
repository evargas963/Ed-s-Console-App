/* Ed Console — Order Flow / "Book · DOM" subview. PRESENTATION ONLY.
   Real L2 book microstructure for the UNDERLYING ticker itself (NASDAQ_BOOK/NYSE_BOOK), via
   /api/order-flow/microstructure -- the SAME canonical app.options.order_flow.engine.
   compute_book_microstructure the options Flow tab already reads (server.py:15093 delegates
   to the identical function server.py:15124 does for one option contract's book). Reuses that
   view's exact .fl-* CSS grammar so a book reads the same whether it's an option contract's
   or the ticker's own -- one visual language, not a second one invented here.

   The console streams the books of the ticker whose /api/live connection is open (the page
   opens it for its ticker); a book not yet arrived reads "No <venue> for <ticker>". */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function int(n) { return (n == null || isNaN(n)) ? '—' : String(Math.round(Number(n))); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function ticker() { return (st().ticker || ''); }
  function host() { return document.getElementById('obBody'); }

  // the book as the console pushes it for the view's ticker and venue (the same answer Right Now
  // and the Desk read)
  window.EdShell.onPanel('book', function (a) {
    var h = host(); if (!h || a.waiting) return;
    if (!a.ok) { h.innerHTML = '<div class="placeholder"><div class="sm">/api/order-flow/microstructure answered HTTP ' + a.status + '</div></div>'; return; }
    render(h, ticker(), a.body);
  });

  function classOf(map, key) { var v = map ? map[key] : null; return (typeof v === 'string' && v) ? v : null; }
  function tag(c) {
    if (c === undefined || c == null) return '';
    var hook = (String(c).toLowerCase().match(/^[a-z0-9-]+/) || ['unknown'])[0];
    return '<span class="fl-tag ' + hook + '" data-cls="' + esc(c) + '">' + esc(c) + '</span>';
  }
  function section(title, rows) {
    var h = '<div class="fl-sec"><div class="fl-sec-h">' + esc(title) + '</div>';
    rows.forEach(function (r) {
      var v = r[1] && r[1].ageOf ? window.EdShell.ageSpan(r[1].ageOf) : esc(r[1]);   // a served age
      h += '<div class="fl-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + v + '</span>' + tag(r[2]) + '</div>';
    });
    return h + '</div>';
  }

  // Real per-level DOM ladder from d.depth_pressure.{bid,ask} -- [{price,volume,cum}], best-
  // first, up to OF_BOOK_DEPTH_DEEP (5) levels. This is genuine displayed-book data the first
  // build of this view fetched but never rendered (only the aggregate depth.{1,3,5} totals
  // were shown) -- the operator's "this sucks, it's just numbers" is fixed by using the level
  // array that was already on the wire.
  function ladderHtml(bidLevels, askLevels, wallSet) {
    var maxVol = 0;
    bidLevels.concat(askLevels).forEach(function (l) { if (l.volume > maxVol) maxVol = l.volume; });
    maxVol = maxVol || 1;
    function row(l, side) {
      var w = Math.max(2, Math.round((l.volume / maxVol) * 100));
      var isWall = wallSet[side + '@' + l.price];
      return '<div class="dom-row ' + side + (isWall ? ' wall' : '') + '">' +
        '<div class="dom-bar-track"><i class="dom-bar" style="width:' + w + '%"></i></div>' +
        '<span class="dom-px">' + num(l.price) + '</span><span class="dom-sz">' + int(l.volume) + '</span></div>';
    }
    var asksHtml = askLevels.slice().reverse().map(function (l) { return row(l, 'ask'); }).join('');
    var bidsHtml = bidLevels.map(function (l) { return row(l, 'bid'); }).join('');
    return '<div class="dom-side-label">Ask</div>' + (asksHtml || '<div class="sm" style="padding:4px 8px;">no displayed asks</div>') + bidsHtml +
      (bidsHtml ? '' : '<div class="sm" style="padding:4px 8px;">no displayed bids</div>') + '<div class="dom-side-label">Bid</div>';
  }

  function render(h, tk, d) {
    if (!d || d.status === 'no_book') {
      h.innerHTML = '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' + esc(tk) + '</span></div>' +
        '<div class="fl-sub"><span class="fl-lab">Book</span><span class="fl-badge warn">NO BOOK YET</span></div></div>' +
        '<div class="placeholder"><div class="sm">No ' + esc(st().bookVenue) + ' for ' + esc(tk) +
        ' — Schwab has sent no book from this venue for this symbol.</div></div>';
      return;
    }
    var tob = d.top_of_book || {}, depth = d.depth || {}, ages = d.ages || {}, cls = d.classification || {};
    var dp = d.depth_pressure || {}, bidLevels = dp.bid || [], askLevels = dp.ask || [];
    function dep(n, side) { var x = depth[String(n)] || {}; return x[side]; }
    function bk(k) { return classOf(cls, k); }
    var walls = d.wall_candidates || [];
    var wallSet = {};
    walls.forEach(function (w) { wallSet[w.side + '@' + w.price] = w; });

    var midHtml = '<div class="dom-mid"><span>mid ' + num(d.mid) + '</span><span>spread ' + num(d.spread_pts) +
      '</span><span>microprice ' + num(d.microprice) + '</span></div>';

    // Schwab's last top of book; with its feed down, marked not live with the served reason
    var rowsTob = [
      ['Bid × size', num(tob.bid) + ' × ' + int(tob.bid_size), bk('top_of_book.bid')],
      ['Ask × size', num(tob.ask) + ' × ' + int(tob.ask_size), bk('top_of_book.ask')],
    ].concat(d.top_outage ? [['Top of book', 'NOT LIVE · ' + d.top_outage, null]] : []);
    var rowsImb = [
      ['Depth 1 imbalance', num(dep(1, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Depth 3 imbalance', num(dep(3, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Depth 5 imbalance', num(dep(5, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Bid total (5)', int(dep(5, 'bid_total')), bk('depth.*.bid_total')],
      ['Ask total (5)', int(dep(5, 'ask_total')), bk('depth.*.ask_total')],
    ];
    var fresh = [
      ['Book age', d.as_of.book != null ? { ageOf: 'book' } : '—', bk('as_of.book')],
      ['Quote age', d.as_of.quote != null ? { ageOf: 'quote' } : '—', bk('as_of.quote')],
    ];
    var wallsHtml = walls.length
      ? walls.map(function (w) { return '<div class="fl-row"><span class="k">' + esc(w.side || '—') + ' @ ' + num(w.price) +
          '</span><span class="v">' + int(w.volume) + ' <span class="sm">(' + num(w.median_mult, 1) + '× median)</span></span></div>'; }).join('')
      : '<div class="sm" style="padding:4px 0;">no size-outlier candidates in the current displayed book</div>';
    var deferred = (d.deferred || []).join(' · ');

    // book_stale is the server's verdict (app.options.order_flow.engine); LIVE only on its
    // explicit "not stale", an unknown book age is not live
    var bs = ages.book_stale, badge = bs === false ? 'LIVE' : bs === true ? 'STALE' : 'AGE UNKNOWN';
    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' + esc(tk) + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Book</span><span class="fl-badge ' + (bs === false ? 'live' : 'stale') + '">' + badge + '</span></div></div>' +
      '<div class="dom-wrap">' +
        '<div class="dom-ladder">' + ladderHtml(bidLevels, askLevels, wallSet) + midHtml + '</div>' +
        '<div class="dom-stats">' +
          section('Top of book', rowsTob) + section('Imbalance', rowsImb) + section('Freshness', fresh) +
        '</div>' +
      '</div>' +
      '<div class="fl-sec" style="margin-top:14px;"><div class="fl-sec-h">Wall candidates (size-outlier heuristic, displayed book only)</div>' + wallsHtml + '</div>' +
      '<div class="fl-foot">' + (deferred ? esc(deferred) + ' — ' : '') +
      'no signed buys/sells, CVD, or bull/bear verdict is canonical for the underlying; Schwab exposes no native aggressor field.</div>';
  }
})();
