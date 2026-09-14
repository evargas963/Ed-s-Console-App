/* Ed Console — Trade Desk / "Right Now" subview. PRESENTATION ONLY, computes nothing.
   The architectural home console.html has preserved verbatim since the rebuild started:
   "Detect -> Frame -> Confirm -> Execute reasoning flow." This module builds the first three
   stages from FOUR already-canonical endpoints other workspaces already own -- one page, zero
   new math, zero new producers:
     DETECT  <- /api/order-flow/microstructure  (same engine the Order Flow > Book/DOM tab reads)
     FRAME   <- /api/levels + /api/liquidity-snapshot (same contracts Liquidity > Levels/Map read)
     CONFIRM <- /api/terrain                    (same regime/walls/headline the Gamma tab reads)
   The Context Summary panel is plain-English arrangement of those SAME four responses (e.g.
   "is spot presently between these two already-fetched zone bounds") -- a classification of
   already-canonical values, never a new computed truth, and never a fabricated confluence
   score. EXECUTE is deliberately NOT rendered. THE CALL and 1m/5m/15m/60m horizons stay
   NOT_PROVEN until ticker-universal evidence earns them (the operator's own gate, preserved
   in the footer badge below) -- this page synthesizes, it does not decide. */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
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
  function fetchJson(url, signal) {
    return fetch(url, { cache: 'no-store', signal: signal })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  // ---- one stage card: numbered badge, title, one HERO stat, a short supporting-row list ----
  function stage(n, accentCls, title, hero, heroUnit, heroDir, rows, badgeText, badgeCls) {
    var dirGlyph = heroDir > 0 ? '▲' : heroDir < 0 ? '▼' : '';
    var dirCls = heroDir > 0 ? 'pos' : heroDir < 0 ? 'neg' : '';
    var h = '<div class="td-stage ' + accentCls + '">' +
      '<div class="td-stage-h"><span class="td-badge ' + accentCls + '">' + n + '</span>' +
      '<span class="td-stage-title">' + esc(title) + '</span>' +
      (badgeText ? '<span class="fl-badge ' + (badgeCls || '') + '" style="margin-left:auto;">' + esc(badgeText) + '</span>' : '') + '</div>' +
      '<div class="td-hero"><span class="' + dirCls + '">' + (dirGlyph ? dirGlyph + ' ' : '') + esc(hero) + '</span>' +
      (heroUnit ? '<span class="unit">' + esc(heroUnit) + '</span>' : '') + '</div>';
    rows.forEach(function (r) {
      h += '<div class="fl-row"><span class="k">' + esc(r[0]) + '</span><span class="v">' + esc(r[1]) + '</span>' + tag(r[2]) + '</div>';
    });
    return h + '</div>';
  }

  function detectStage(d) {
    if (!d || d.status === 'no_book') {
      return stage(1, 'td-accent-blue', 'Detect — book microstructure', 'No book yet', '', 0, [], 'NO BOOK', 'warn');
    }
    var tob = d.top_of_book || {}, depth = d.depth || {}, cls = d.classification || {};
    function dep(n, side) { var x = depth[String(n)] || {}; return x[side]; }
    var imb = dep(5, 'imbalance');
    var rows = [
      ['Bid × Ask', num(tob.bid) + ' × ' + num(tob.ask), classOf(cls, 'top_of_book.bid')],
      ['Spread (pts)', num(d.spread_pts), classOf(cls, 'spread_pts')],
      ['Depth 1 imbalance', num(dep(1, 'imbalance'), 3), classOf(cls, 'depth.*.imbalance')],
    ];
    var heroVal = imb == null ? '—' : (imb >= 0 ? '+' : '') + imb.toFixed(3);
    var heroUnit = imb == null ? '' : (imb > 0.05 ? 'bid-heavy (depth 5)' : imb < -0.05 ? 'ask-heavy (depth 5)' : 'balanced (depth 5)');
    return stage(1, 'td-accent-blue', 'Detect — book microstructure', heroVal, heroUnit, imb > 0.05 ? 1 : imb < -0.05 ? -1 : 0, rows, 'LIVE', 'live');
  }

  function frameStage(levelsD, spot) {
    var levels = (levelsD && levelsD.levels) || [];
    if (!levels.length) return stage(2, 'td-accent-green', 'Frame — liquidity levels', 'No levels', '', 0, [], null);
    var sorted = levels.slice().sort(function (a, b) {
      return Math.abs((a.price || 0) - spot) - Math.abs((b.price || 0) - spot);
    });
    var nearest = sorted[0];
    var rows = sorted.slice(1, 4).map(function (r) { return [r.label || r.id, num(r.price), r.evidence_tier]; });
    var dist = isFinite(spot) && nearest ? nearest.price - spot : null;
    var heroVal = nearest ? (nearest.label || nearest.id) + ' ' + num(nearest.price) : '—';
    var heroUnit = dist != null ? (Math.abs(dist) < 0.005 ? 'at spot' : (dist > 0 ? num(Math.abs(dist)) + ' above spot' : num(Math.abs(dist)) + ' below spot')) : '';
    return stage(2, 'td-accent-green', 'Frame — nearest liquidity level', heroVal, heroUnit, 0, rows, null);
  }

  function confirmStage(d) {
    if (!d) return stage(3, 'td-accent-amber', 'Confirm — options regime', 'No regime', '', 0, [], null);
    var rows = [
      ['Posture', esc(d.posture || '—')], ['Confidence', esc(d.confidence || '—')],
      ['Call wall', num(d.call_wall)], ['Put wall', num(d.put_wall)],
    ];
    return stage(3, 'td-accent-amber', 'Confirm — options regime', d.regime || '—', '', 0, rows, d.confidence || null,
      d.confidence === 'TRUSTED' ? 'live' : 'warn');
  }

  // ---- Context Summary: plain-English arrangement of the SAME 4 responses. Classifies
  // (inside a zone / between two zones), never invents a value. ----
  function locateSpot(spot, zones) {
    if (!isFinite(spot) || !zones || !zones.length) return null;
    for (var i = 0; i < zones.length; i++) {
      var z = zones[i];
      if (spot >= z.zone_low && spot <= z.zone_high) {
        return { inside: z };
      }
    }
    var above = null, below = null;
    zones.forEach(function (z) {
      if (z.zone_low > spot && (above == null || z.zone_low < above.zone_low)) above = z;
      if (z.zone_high < spot && (below == null || z.zone_high > below.zone_high)) below = z;
    });
    return { above: above, below: below };
  }

  function contextSummary(terrain, snap, spot) {
    var lines = [];
    if (terrain) {
      lines.push(['Regime', (terrain.regime || '—') + (terrain.posture ? ' · ' + terrain.posture : '')]);
      if (terrain.headline) lines.push(['Read', terrain.headline]);
    }
    var zones = (snap && snap.zones) || [];
    var loc = locateSpot(spot, zones);
    if (loc && loc.inside) {
      var z = loc.inside;
      lines.push(['Location', 'Inside a ' + (z.zone_type === 'support_liquidity' ? 'support' : 'resistance') +
        ' zone (' + num(z.zone_low) + '–' + num(z.zone_high) + ', confluence ' + z.confluence_score + ')']);
    } else if (loc) {
      var parts = [];
      if (loc.above) parts.push('resistance near ' + num(loc.above.zone_low) + ' (confluence ' + loc.above.confluence_score + ')');
      if (loc.below) parts.push('support near ' + num(loc.below.zone_high) + ' (confluence ' + loc.below.confluence_score + ')');
      lines.push(['Location', parts.length ? 'Between zones — ' + parts.join(', ') : 'No scored zone nearby']);
    }
    if (terrain && terrain.call_wall != null && terrain.put_wall != null && isFinite(spot)) {
      var toCall = terrain.call_wall - spot, toPut = spot - terrain.put_wall;
      lines.push(['Box', num(toPut) + ' above put wall, ' + num(toCall) + ' below call wall']);
    }
    if (!lines.length) return '';
    return '<div class="td-context"><h4>Context summary</h4>' +
      lines.map(function (l) { return '<div class="td-ctx-row"><span class="lbl">' + esc(l[0]) + '</span><span class="val">' + esc(l[1]) + '</span></div>'; }).join('') +
      '</div>';
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
      fetchJson('/api/liquidity-snapshot?ticker=' + encodeURIComponent(tk), signal),
    ]).then(function (results) {
      if (!stillRightNow(tk)) return;
      var detect = results[0], levelsD = results[1], terrain = results[2], snap = results[3];
      var spot = levelsD ? Number(levelsD.spot) : (terrain ? Number(terrain.spot) : NaN);
      h.innerHTML =
        '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Right now</span><span class="fl-sym">' + esc(tk) +
        '</span><span class="fl-meta">' + (isFinite(spot) ? 'spot ' + num(spot) : '') + '</span></div></div>' +
        '<div class="td-grid">' + detectStage(detect) + frameStage(levelsD, spot) + confirmStage(terrain) + '</div>' +
        contextSummary(terrain, snap, spot) +
        '<div class="notproven" style="margin-top:14px;">HOME PRESERVED — DECISION AUTHORITY NOT_PROVEN. ' +
        'This page assembles already-canonical Detect/Frame/Confirm signals and classifies them in plain English; it computes no new value and renders no Execute step. ' +
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
