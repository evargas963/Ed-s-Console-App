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
  var _book = null;                  // the book last drawn, drawn again when the push goes down or comes back
  window.EdShell.onPanel('book', function (a) {
    var h = host(); if (!h || a.waiting) return;
    _book = null;
    if (!a.ok) { h.innerHTML = '<div class="placeholder"><div class="sm">/api/order-flow/microstructure answered HTTP ' + a.status + '</div></div>'; return; }
    _book = a.body;
    render(h, ticker(), a.body);
  });
  document.addEventListener('ed:push', function () { var h = host(); if (h && _book) render(h, ticker(), _book); });
  // the venue's book (NYSE_BOOK / NASDAQ_BOOK, Whole) and the top of book, as the daemon pushes
  // them, drawn while the Book is on screen
  function onBook() { var s = st(); return s.workspace === 'order-flow' && s.subview === 'book'; }
  window.addEventListener('ed:schwab', function (e) {
    var m = e.detail, h = host();
    if (h && onBook() && m.key === st().key && (m.service === st().bookVenue || m.service === 'LEVELONE_EQUITIES')) render(h, ticker(), _book);
  });

  function classOf(map, key) { var v = map ? map[key] : null; return (typeof v === 'string' && v) ? v : null; }

  // Real per-level DOM ladder from d.depth_pressure.{bid,ask} -- [{price,volume,cum}], best-
  // first, up to OF_BOOK_DEPTH_DEEP (5) levels. This is genuine displayed-book data the first
  // build of this view fetched but never rendered (only the aggregate depth.{1,3,5} totals
  // were shown) -- the operator's "this sucks, it's just numbers" is fixed by using the level
  // array that was already on the wire.
  // each level [price, total size] as the daemon sends it (engine.book_levels)
  function ladderHtml(bidLevels, askLevels, wallSet) {
    var maxVol = 0;
    bidLevels.concat(askLevels).forEach(function (l) { if (l[1] > maxVol) maxVol = l[1]; });
    maxVol = maxVol || 1;
    function row(l, side) {
      var isWall = wallSet[side + '@' + l[0]];
      // a size Schwab did not send as a number: no bar (an unknown is not a small size)
      var bar = l[1] == null ? '' : '<i class="dom-bar" style="width:' + Math.max(2, Math.round((l[1] / maxVol) * 100)) + '%"></i>';
      return '<div class="dom-row ' + side + (isWall ? ' wall' : '') + '">' +
        '<div class="dom-bar-track">' + bar + '</div>' +
        '<span class="dom-px">' + num(l[0]) + '</span><span class="dom-sz">' + int(l[1]) + '</span></div>';
    }
    var asksHtml = askLevels.slice().reverse().map(function (l) { return row(l, 'ask'); }).join('');
    var bidsHtml = bidLevels.map(function (l) { return row(l, 'bid'); }).join('');
    return '<div class="dom-side-label">Ask</div>' + (asksHtml || '<div class="sm" style="padding:4px 8px;">no displayed asks</div>') + bidsHtml +
      (bidsHtml ? '' : '<div class="sm" style="padding:4px 8px;">no displayed bids</div>') + '<div class="dom-side-label">Bid</div>';
  }

  function render(h, tk, d) {
    var sb = window.EdShell.book(st().bookVenue, st().key);
    // the console's reads of the book, absent until it has priced one (then each reads '—')
    var priced = d && d.status !== 'no_book' ? d : null;
    function got(k) { return priced ? priced[k] : undefined; }
    var depth = got('depth'), cls = got('classification'), asOf = got('as_of');
    var bidLevels = sb ? sb.levels.bids : [], askLevels = sb ? sb.levels.asks : [];
    var verdict = window.EdShell.feedVerdict(st().key, st().bookVenue);
    // Schwab's top of book: LEVELONE_EQUITIES as the daemon pushes it, and its verdict
    var tob = window.EdShell.priceRow(st().key);
    function dep(n, side) { var x = depth && depth[String(n)]; return x ? x[side] : undefined; }
    function bk(k) { return classOf(cls, k); }
    var walls = got('wall_candidates');
    var wallSet = {};
    if (walls) walls.forEach(function (w) { wallSet[w.side + '@' + w.price] = w; });

    // the console's reads, labelled with the top of book they were priced at (the engine's input)
    var pricedAt = got('top_of_book');
    var midHtml = '<div class="dom-mid"><span>mid ' + num(got('mid')) + '</span><span>spread ' + num(got('spread_pts')) +
      '</span><span>microprice ' + num(got('microprice')) + '</span><span class="sm">priced at ' +
      (pricedAt ? num(pricedAt.bid) + ' × ' + num(pricedAt.ask) : '-') + '</span></div>';

    // Schwab's last top of book; with its feed down, marked not live with the served reason
    var rowsTob = [
      ['Bid × size', num(tob.bid) + ' × ' + int(tob.bid_size), bk('top_of_book.bid')],
      ['Ask × size', num(tob.ask) + ' × ' + int(tob.ask_size), bk('top_of_book.ask')],
    ].concat(!tob.feed_live ? [['Top of book', window.EdShell.notLive(tob), undefined]] : []);
    var rowsImb = [
      ['Depth 1 imbalance', num(dep(1, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Depth 3 imbalance', num(dep(3, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Depth 5 imbalance', num(dep(5, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Bid total (5)', int(dep(5, 'bid_total')), bk('depth.*.bid_total')],
      ['Ask total (5)', int(dep(5, 'ask_total')), bk('depth.*.ask_total')],
    ];
    var fresh = [
      ['Book age', asOf && asOf.book != null ? { ageOf: 'book' } : '—', bk('as_of.book')],
      ['Quote age', asOf && asOf.quote != null ? { ageOf: 'quote' } : '—', bk('as_of.quote')],
    ];
    var wallsHtml = walls && walls.length
      ? walls.map(function (w) { return '<div class="fl-row"><span class="k">' + esc(w.side || '—') + ' @ ' + num(w.price) +
          '</span><span class="v">' + int(w.volume) + ' <span class="sm">(' + num(w.median_mult, 1) + '× median)</span></span></div>'; }).join('')
      : '<div class="sm" style="padding:4px 0;">no size-outlier candidates in the current displayed book</div>';
    var deferred = got('deferred') ? got('deferred').join(' · ') : '';

    // the book's verdict is the daemon's (the one live rule), on Schwab's book for this venue
    var live = !!(verdict && verdict.live);
    var badge = live ? 'LIVE' : window.EdShell.notLive(verdict);
    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' + esc(tk) + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Book</span><span class="fl-badge ' + (live ? 'live' : 'stale') + '">' + esc(badge) + '</span>' +
      '<span class="sm">' + esc(st().bookVenue) + ' · ' + (!sb || sb.time_ct == null ? '-' : esc(sb.time_ct)) + '</span></div></div>' +
      '<div class="dom-wrap">' +
        '<div class="dom-ladder">' + ladderHtml(bidLevels, askLevels, wallSet) + midHtml + '</div>' +
        '<div class="dom-stats">' +
          window.EdShell.flSection('Top of book', rowsTob, '') + window.EdShell.flSection('Imbalance', rowsImb, '') +
          window.EdShell.flSection('Freshness', fresh, '') +
        '</div>' +
      '</div>' +
      '<div class="fl-sec" style="margin-top:14px;"><div class="fl-sec-h">Wall candidates (size-outlier heuristic, displayed book only)</div>' + wallsHtml + '</div>' +
      '<div class="fl-foot">' + (deferred ? esc(deferred) + ' — ' : '') +
      'no signed buys/sells, CVD, or bull/bear verdict is canonical for the underlying; Schwab exposes no native aggressor field.</div>';
  }
})();
