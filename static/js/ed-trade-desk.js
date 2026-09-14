/* Ed Console — Trade Desk / "Right Now" subview. PRESENTATION ONLY, computes nothing.
   The architectural home console.html has preserved verbatim since the rebuild started:
   "Detect -> Frame -> Confirm -> Execute reasoning flow." This module builds the first three
   stages from three ALREADY-CANONICAL endpoints other workspaces already own -- one page, zero
   new math, zero new producers:
     DETECT  <- /api/order-flow/microstructure  (same engine the Order Flow > Book/DOM tab reads)
     FRAME   <- /api/levels                     (same contract the Liquidity > Levels tab reads)
     CONFIRM <- /api/terrain                    (same regime/walls/headline the Gamma tab reads)
   EXECUTE is deliberately NOT rendered here. THE CALL and 1m/5m/15m/60m horizons stay
   NOT_PROVEN until ticker-universal evidence earns them (the operator's own gate, preserved
   in the footer badge below) -- this page synthesizes, it does not decide. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function int(n) { return (n == null || isNaN(n)) ? '—' : String(Math.round(Number(n))); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isRightNow() { var s = st(); return s.workspace === 'trade-desk' && s.subview === 'right-now'; }
  function ticker() { return (st().ticker || 'SPY'); }
  function host() { return document.getElementById('tdBody'); }
  function stillRightNow(tk) { return isRightNow() && ticker() === tk; }

  var _warmedFor = null;
  function warmBook(tk) {
    if (_warmedFor === tk) return;
    _warmedFor = tk;
    if (window.EdStream && window.EdStream.setActiveTicker) window.EdStream.setActiveTicker(tk);
  }

  function classOf(map, key) { var v = map ? map[key] : null; return (typeof v === 'string' && v) ? v : null; }
  function tag(c) {
    if (c === undefined || c == null) return '';
    var hook = (String(c).toLowerCase().match(/^[a-z0-9-]+/) || ['unknown'])[0];
    return '<span class="fl-tag ' + hook + '" data-cls="' + esc(c) + '">' + esc(c) + '</span>';
  }
  function section(title, rows, badge, footNote) {
    var h = '<div class="fl-sec"><div class="fl-sec-h">' + esc(title) + (badge ? ' ' + badge : '') + '</div>';
    if (!rows.length) h += '<div class="sm" style="padding:4px 0;">not available right now</div>';
    rows.forEach(function (r) {
      h += '<div class="fl-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span>' + tag(r[2]) + '</div>';
    });
    if (footNote) h += '<div class="sm" style="padding-top:8px;color:var(--ed-ink-2);">' + esc(footNote) + '</div>';
    return h + '</div>';
  }
  function fetchJson(url, signal) {
    return fetch(url, { cache: 'no-store', signal: signal })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function detectSection(d) {
    if (!d || d.status === 'no_book') {
      return section('Detect — book / microstructure', [], '<span class="fl-tag warn">NO BOOK YET</span>');
    }
    var tob = d.top_of_book || {}, depth = d.depth || {}, cls = d.classification || {};
    function dep(n, side) { var x = depth[String(n)] || {}; return x[side]; }
    var rows = [
      ['Bid × Ask', num(tob.bid) + ' × ' + num(tob.ask), classOf(cls, 'top_of_book.bid')],
      ['Spread (pts)', num(d.spread_pts), classOf(cls, 'spread_pts')],
      ['Depth 1 imbalance', num(dep(1, 'imbalance'), 3), classOf(cls, 'depth.*.imbalance')],
      ['Depth 5 imbalance', num(dep(5, 'imbalance'), 3), classOf(cls, 'depth.*.imbalance')],
    ];
    return section('Detect — book / microstructure', rows, '<span class="fl-tag live">LIVE</span>');
  }

  function frameSection(d) {
    var levels = (d && d.levels) || [];
    if (!levels.length) return section('Frame — liquidity levels', []);
    var spot = Number(d.spot);
    var sorted = levels.slice().sort(function (a, b) {
      var da = Math.abs((a.price || 0) - spot), db = Math.abs((b.price || 0) - spot);
      return da - db;
    }).slice(0, 6);
    var rows = sorted.map(function (r) { return [r.label || r.id, num(r.price), r.evidence_tier]; });
    return section('Frame — liquidity levels (nearest ' + sorted.length + ' of ' + levels.length + ')', rows);
  }

  function confirmSection(d) {
    if (!d) return section('Confirm — options regime', []);
    var rows = [
      ['Regime', esc(d.regime || '—')], ['Posture', esc(d.posture || '—')], ['Confidence', esc(d.confidence || '—')],
      ['Gamma flip', num(d.gamma_flip)], ['Call wall', num(d.call_wall)], ['Put wall', num(d.put_wall)],
      ['Max pain', num(d.max_pain)], ['Net GEX @ spot', d.net_gex_at_spot != null ? (Number(d.net_gex_at_spot) / 1e6).toFixed(1) + 'M' : '—'],
    ];
    return section('Confirm — options regime', rows, null, d.headline);
  }

  function loadImpl(tk, signal) {
    var h = host();
    if (!h || !stillRightNow(tk)) return;
    h.setAttribute('aria-busy', 'true');
    warmBook(tk);
    return Promise.all([
      fetchJson('/api/order-flow/microstructure?ticker=' + encodeURIComponent(tk), signal),
      fetchJson('/api/levels?ticker=' + encodeURIComponent(tk), signal),
      fetchJson('/api/terrain?ticker=' + encodeURIComponent(tk), signal),
    ]).then(function (results) {
      if (!stillRightNow(tk)) return;
      var detect = results[0], frame = results[1], confirm = results[2];
      h.innerHTML =
        '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Right now</span><span class="fl-sym">' + esc(tk) + '</span></div></div>' +
        '<div class="fl-grid">' + detectSection(detect) + frameSection(frame) + confirmSection(confirm) + '</div>' +
        '<div class="notproven" style="margin-top:14px;">HOME PRESERVED — DECISION AUTHORITY NOT_PROVEN. ' +
        'This page assembles already-canonical Detect/Frame/Confirm signals; it computes nothing new and renders no Execute step. ' +
        'THE CALL and 1m/5m/15m/60m horizons remain excluded until ticker-universal evidence earns them.</div>';
    });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  function load() {
    if (!isRightNow()) return;
    var tEl = document.getElementById('tdTicker'); if (tEl) tEl.textContent = ticker().replace('$', '');
    _loader.trigger(ticker());
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
