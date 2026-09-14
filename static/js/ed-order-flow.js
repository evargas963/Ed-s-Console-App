/* Ed Console — Order Flow / "Book · DOM" subview. PRESENTATION ONLY.
   Real L2 book microstructure for the UNDERLYING ticker itself (NASDAQ_BOOK/NYSE_BOOK), via
   /api/order-flow/microstructure -- the SAME canonical app.options.order_flow.engine.
   compute_book_microstructure the options Flow tab already reads (server.py:15093 delegates
   to the identical function server.py:15124 does for one option contract's book). Reuses that
   view's exact .fl-* CSS grammar so a book reads the same whether it's an option contract's
   or the ticker's own -- one visual language, not a second one invented here.

   EdStream.setActiveTicker (ed-stream.js) is the ONE owner of "please subscribe this ticker's
   NASDAQ/NYSE book" -- built this mission but never called from anywhere in the new console
   (confirmed: every ticker's book returned {"status":"no_book"} even for an actively-viewed
   symbol). This view calls it once per ticker on entry, per that function's own doc comment
   ("only a view that genuinely needs the single-symbol equity BOOK/DOM should call this").
   The POST is REQUEST-ACCEPTED only, no producer-binding identity -- so a book that has not
   arrived yet renders as an honest "no book yet" state, never a fabricated ladder. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function int(n) { return (n == null || isNaN(n)) ? '—' : String(Math.round(Number(n))); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isBook() { var s = st(); return s.workspace === 'order-flow' && s.subview === 'book'; }
  function ticker() { return (st().ticker || 'SPY'); }
  function host() { return document.getElementById('obBody'); }
  function stillBook(tk) { return isBook() && ticker() === tk; }

  // Operator-reproduced defect (2026-09-14): a PRIVATE "already warmed AMD" cache here could
  // not see that Trade Desk moved the real subscription to PLTR in between -- AMD Book -> PLTR
  // Trade Desk -> AMD Book left the live subscription stuck on PLTR while this screen still
  // showed AMD. EdStream.warmActiveTicker is the ONE shared de-dup authority now (ed-stream.js);
  // no view keeps its own copy of "did I already ask for this ticker".
  function warm(tk) {
    if (window.EdStream && window.EdStream.warmActiveTicker) window.EdStream.warmActiveTicker(tk);
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillBook(tk)) return;
    h.setAttribute('aria-busy', 'true');
    return fetch('/api/order-flow/microstructure?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillBook(tk)) render(h, tk, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillBook(tk)) h.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/order-flow/microstructure</div></div>';
      });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() {
    if (!isBook()) return;
    var tk = ticker();
    var tEl = document.getElementById('obTicker'); if (tEl) tEl.textContent = tk.replace('$', '');
    warm(tk);
    _loader.trigger(tk);
  }

  function classOf(map, key) { var v = map ? map[key] : null; return (typeof v === 'string' && v) ? v : null; }
  function tag(c) {
    if (c === undefined || c == null) return '';
    var hook = (String(c).toLowerCase().match(/^[a-z0-9-]+/) || ['unknown'])[0];
    return '<span class="fl-tag ' + hook + '" data-cls="' + esc(c) + '">' + esc(c) + '</span>';
  }
  function section(title, rows) {
    var h = '<div class="fl-sec"><div class="fl-sec-h">' + esc(title) + '</div>';
    rows.forEach(function (r) {
      h += '<div class="fl-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span>' + tag(r[2]) + '</div>';
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
        '<div class="placeholder"><div class="sm">Subscription just requested for ' + esc(tk) +
        ' — the ladder populates once Schwab confirms the NASDAQ/NYSE book (this view never fabricates a book).</div></div>';
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

    var rowsTob = [
      ['Bid × size', num(tob.bid) + ' × ' + int(tob.bid_size), bk('top_of_book.bid')],
      ['Ask × size', num(tob.ask) + ' × ' + int(tob.ask_size), bk('top_of_book.ask')],
    ];
    var rowsImb = [
      ['Depth 1 imbalance', num(dep(1, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Depth 3 imbalance', num(dep(3, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Depth 5 imbalance', num(dep(5, 'imbalance'), 3), bk('depth.*.imbalance')],
      ['Bid total (5)', int(dep(5, 'bid_total')), bk('depth.*.bid_total')],
      ['Ask total (5)', int(dep(5, 'ask_total')), bk('depth.*.ask_total')],
    ];
    var fresh = [
      ['Book age', ages.book_age_sec != null ? Math.round(ages.book_age_sec) + 's' : '—', bk('ages.book_age_sec')],
      ['Quote age', ages.quote_age_sec != null ? Math.round(ages.quote_age_sec) + 's' : '—', bk('ages.quote_age_sec')],
    ];
    var wallsHtml = walls.length
      ? walls.map(function (w) { return '<div class="fl-row"><span class="k">' + esc(w.side || '—') + ' @ ' + num(w.price) +
          '</span><span class="v">' + int(w.size) + ' <span class="sm">(' + num(w.median_mult, 1) + '× median)</span></span></div>'; }).join('')
      : '<div class="sm" style="padding:4px 0;">no size-outlier candidates in the current displayed book</div>';
    var deferred = (d.deferred || []).join(' · ');

    // Operator-reproduced defect (2026-09-14): this badge was a hardcoded literal, never gated
    // on ages.book_age_sec even though the exact same number is displayed two lines below it in
    // the Freshness section -- a book observation aged to 3,600s still rendered LIVE. book_stale
    // is server-computed (app.options.order_flow.engine.compute_book_microstructure); this only
    // reads the verdict.
    var stale = ages.book_stale === true;
    h.innerHTML =
      '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Ticker</span><span class="fl-sym">' + esc(tk) + '</span></div>' +
      '<div class="fl-sub"><span class="fl-lab">Book</span><span class="fl-badge ' + (stale ? 'stale' : 'live') + '">' + (stale ? 'STALE' : 'LIVE') + '</span></div></div>' +
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

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
