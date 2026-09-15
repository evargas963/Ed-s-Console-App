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

  // Operator-reproduced defect (2026-09-14): this file's own private "already warmed" cache
  // could not see ed-order-flow.js's identical cache moving the subscription elsewhere (or vice
  // versa) -- AMD Book -> PLTR Trade Desk -> AMD Book left the real subscription on PLTR.
  // EdStream.warmActiveTicker is the ONE shared de-dup authority now (ed-stream.js).
  function warmBook(tk) {
    if (window.EdStream && window.EdStream.warmActiveTicker) window.EdStream.warmActiveTicker(tk);
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
  var usd = function (n) {
    if (n == null || isNaN(n)) return '—';
    var a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'K';
    return s + '$' + a.toFixed(0);
  };
  function fmtVol(n) {
    if (n == null || isNaN(n)) return '—';
    var a = Math.abs(Number(n));
    if (a >= 1e6) return (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return (a / 1e3).toFixed(1) + 'K';
    return String(Math.round(a));
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
    var ages = d.ages || {};
    var rows = [
      ['Bid × Ask', num(tob.bid) + ' × ' + num(tob.ask), classOf(cls, 'top_of_book.bid')],
      ['Spread (pts)', num(d.spread_pts), classOf(cls, 'spread_pts')],
      ['Depth 1 imbalance', num(dep(1, 'imbalance'), 3), classOf(cls, 'depth.*.imbalance')],
      ['Book age', ages.book_age_sec != null ? Math.round(ages.book_age_sec) + 's' : '—', classOf(cls, 'ages.book_age_sec')],
    ];
    var heroVal = (imb == null || isNaN(imb)) ? '—' : (imb >= 0 ? '+' : '') + num(imb, 3);
    var heroUnit = imb == null ? '' : (imb > 0.05 ? 'bid-heavy (depth 5)' : imb < -0.05 ? 'ask-heavy (depth 5)' : 'balanced (depth 5)');
    // Operator-reproduced defect (2026-09-14): this badge was hardcoded 'LIVE' regardless of
    // book_age_sec -- a book observation aged to 3,600s still rendered LIVE. ages.book_stale is
    // server-computed (app.options.order_flow.engine.compute_book_microstructure), the SAME
    // freshness boundary the rest of that engine already applies to top-of-book fields; this
    // only reads the verdict, it does not invent its own threshold.
    var stale = ages.book_stale === true;
    return stage(1, 'td-accent-blue', 'Detect — book microstructure', heroVal, heroUnit, imb > 0.05 ? 1 : imb < -0.05 ? -1 : 0,
      rows, stale ? 'STALE' : 'LIVE', stale ? 'stale' : 'live');
  }

  function frameStage(levelsD, spot) {
    var levels = (levelsD && levelsD.levels) || [];
    if (!levels.length) return stage(2, 'td-accent-green', 'Frame — liquidity levels', 'No levels', '', 0, [], null);
    var sorted = levels.slice().sort(function (a, b) {
      return Math.abs((a.price || 0) - spot) - Math.abs((b.price || 0) - spot);
    });
    var nearest = sorted[0];
    var rows = sorted.slice(1, 6).map(function (r) { return [r.label || r.id, num(r.price), r.evidence_tier]; });
    var dist = isFinite(spot) && nearest ? nearest.price - spot : null;
    var heroVal = nearest ? (nearest.label || nearest.id) + ' ' + num(nearest.price) : '—';
    var heroUnit = dist != null ? (Math.abs(dist) < 0.005 ? 'at spot' : (dist > 0 ? num(Math.abs(dist)) + ' above spot' : num(Math.abs(dist)) + ' below spot')) : '';
    return stage(2, 'td-accent-green', 'Frame — nearest liquidity level', heroVal, heroUnit, 0, rows, null);
  }

  function confirmStage(d) {
    if (!d) return stage(3, 'td-accent-amber', 'Confirm — options regime', 'No regime', '', 0, [], null);
    // Raw values only -- stage() escapes every row itself (double-escaping a value here turns
    // a real "&" into the literal text "&amp;" on screen).
    var rows = [
      ['Posture', d.posture || '—'], ['Confidence', d.confidence || '—'],
      ['Call wall', num(d.call_wall)], ['Put wall', num(d.put_wall)],
      ['Gamma flip', num(d.gamma_flip)], ['Max pain', num(d.max_pain)],
      ['Net GEX @ spot', d.net_gex_at_spot != null ? (Number(d.net_gex_at_spot) / 1e6).toFixed(1) + 'M' : '—'],
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

  // ---- Positioning Migration & Volume: today's per-strike net GEX$ (solid) vs yesterday's
  // (ghost outline), plus today's per-strike option volume -- the SAME real fields
  // /api/terrain/strikes already serves to the GEX-by-Strike panel (today.{all,near,far} and
  // prior.{all,near,far}, both [strike, net_gex_1pct$, volume] rows), ported from the legacy
  // chart.html gamma panel's exact math. No new backend computation: this is a second, in-context
  // rendering of an already-canonical endpoint, same as static/chart.html's own reuse of it. ----
  var _migScope = 'all';   // 'all' | 'near' (<=7 DTE) | 'far' (monthly+) -- a DTE filter, distinct
                             // from EdShell's own auto/wider/all row-DENSITY scope used below.
  var _migGhost = true;
  var MIG_SCOPES = [['all', 'ALL'], ['near', '≤7 DTE'], ['far', 'MONTHLY+']];

  // Own badge class, deliberately NOT fl-tag/native|derived -- those hooks are this file's (and
  // ed-gamma-panels.js's) provenance classification colors; a SPOT/wall price marker is a
  // position label, not a provenance claim, and reusing them would misread as one.
  function migTag(txt, cls) { return '<span class="mig-mark ' + cls + '">' + esc(txt) + '</span>'; }

  function migrationCoach(withGhost, byVol, terrain) {
    var out = '';
    if (!withGhost.length) {
      out += '<div class="mig-coach"><b>Migration view warming up</b>The first day-over-day comparison lands after the next wide morning capture.</div>';
    } else {
      var sPos = 0, wPos = 0, sPosY = 0, wPosY = 0;
      withGhost.forEach(function (r) {
        if (r.gx > 0) { sPos += r.k * r.gx; wPos += r.gx; }
        if (r.gy > 0) { sPosY += r.k * r.gy; wPosY += r.gy; }
      });
      var wmT = wPos ? sPos / wPos : null, wmY = wPosY ? sPosY / wPosY : null;
      var dir = (wmT != null && wmY != null)
        ? (wmT - wmY > 0.15 ? 'UP the chain' : wmY - wmT > 0.15 ? 'DOWN the chain' : 'with little net drift')
        : 'with no positive-gamma mass in view';
      var sorted = withGhost.map(function (r) { return [r.k, r.gx - r.gy]; }).sort(function (a, b) { return b[1] - a[1]; });
      var grew = sorted.filter(function (d) { return d[1] > 0; }).slice(0, 2).map(function (d) { return num(d[0], 0); }).join('/');
      var shrank = sorted.filter(function (d) { return d[1] < 0; }).slice(-2).map(function (d) { return num(d[0], 0); }).join('/');
      out += '<div class="mig-coach"><b>Positive gamma mass moved ' + esc(dir) + '</b>' +
        (grew ? 'Grew most at ' + esc(grew) : 'No strike grew') +
        (shrank ? '; shrank most at ' + esc(shrank) + '. ' : '. ') +
        'Opened or closed? Tomorrow’s ΔOI confirms.</div>';
    }
    if (byVol.length) {
      var kk = byVol.map(function (r) { return r.k; });
      var cw = terrain && terrain.call_wall, pw = terrain && terrain.put_wall;
      var loc = (cw != null && Math.min.apply(null, kk) > cw) ? 'ABOVE the call wall'
        : (pw != null && Math.max.apply(null, kk) < pw) ? 'BELOW the put wall' : 'inside the wall range';
      out += '<div class="mig-coach"><b>Heaviest option trading at ' + kk.map(function (k) { return num(k, 0); }).join('–') + '</b>' +
        'That is ' + esc(loc) + '. Activity fact only — buyer/seller split stays unproven until the ΔOI test.</div>';
    }
    return out;
  }

  // ---- Repo-wide chart interaction standard, adapted for this surface's real shape ----
  // Same reasoning as GEX by Strike (ed-gamma-panels.js), which this panel reuses the exact
  // bar-list grammar of: no continuous zoomable axis, strike window governed by the ONE
  // canonical shared scope policy. The missing capability is PAN via the strike-label column;
  // wheel reuses the canonical scope levels (gated to ctrl/cmd -- .gbs-scroll here is itself
  // overflow:auto exactly like GEX by Strike's, so a plain wheel must keep scrolling it).
  var _migPanAnchor = null, _migPanTicker = null;
  var _migDragState = null, _migInteractionInstalled = false;
  function installMigInteractionOnce() {
    if (_migInteractionInstalled || typeof document === 'undefined') return;
    _migInteractionInstalled = true;
    document.addEventListener('mousemove', function (e) {
      if (!_migDragState) return;
      // Independent-review finding, REPRODUCED: #tdBody.innerHTML gets wholesale-replaced by
      // loadImpl's success path on a real ticker switch, which can complete mid-drag and calls
      // migrationSection() (and so _lastMig.tk) for the NEW ticker while this drag's closure
      // still holds the OLD ticker's ascStrikes array. Without this check the drag would keep
      // computing an index against the old strikes and paint it onto the new ticker's panel.
      if (_lastMig && _migDragState.ticker !== _lastMig.tk) { _migDragState = null; return; }
      var dy = e.clientY - _migDragState.startY;
      if (Math.abs(dy) > 3) _migDragState.moved = true;
      var rowsDelta = Math.round(dy / _migDragState.rowPx);
      if (rowsDelta === _migDragState.lastRowsDelta) return;
      _migDragState.lastRowsDelta = rowsDelta;
      var strikes = _migDragState.strikes;
      var newIdx = Math.min(strikes.length - 1, Math.max(0, _migDragState.startIdx + rowsDelta));
      _migPanAnchor = strikes[newIdx];
      _migPanTicker = _migDragState.ticker;
      rerenderMigFromCache();
    });
    document.addEventListener('mouseup', function () { _migDragState = null; });
  }
  var _lastMig = null;   // { strikesD, terrain, spot, tk } -- exactly migrationSection's own inputs
  function rerenderMigFromCache() {
    if (!_lastMig) return;
    var el = document.getElementById('tdMigration');
    if (!el) return;
    var html = migrationSection(_lastMig.strikesD, _lastMig.terrain, _lastMig.spot, _lastMig.tk);
    var tmp = document.createElement('div');
    tmp.innerHTML = html;
    var fresh = tmp.firstElementChild;
    if (fresh) {
      el.replaceWith(fresh);
      wireMigInteraction(fresh, _lastMig.ascStrikes, _lastMig.win, _lastMig.tk);
      wireMigrationChips(host(), _lastMig.tk);
    }
  }
  function wireMigInteraction(panel, ascStrikes, win, tk) {
    installMigInteractionOnce();
    if (!ascStrikes) return;   // the "no per-strike rows" placeholder branch has nothing to wire
    var centerStrike = win.length ? win[Math.floor(win.length / 2)][0] : null;
    var centerIdx = Math.max(0, ascStrikes.indexOf(centerStrike));
    var rowPx = 24;
    var firstRow = panel.querySelector('.gbs-row');
    if (firstRow) { var r = firstRow.getBoundingClientRect(); if (r.height) rowPx = r.height; }
    panel.querySelectorAll('.gbs-k').forEach(function (el) {
      el.style.cursor = 'ns-resize';
      el.setAttribute('draggable', 'false');
      el.addEventListener('dragstart', function (e) { e.preventDefault(); });
      el.addEventListener('mousedown', function (e) {
        _migDragState = { startY: e.clientY, rowPx: rowPx, strikes: ascStrikes, startIdx: centerIdx,
          lastRowsDelta: 0, moved: false, ticker: tk };
        e.preventDefault();
        e.stopPropagation();
      });
      el.addEventListener('dblclick', function (e) {
        _migPanAnchor = null; _migPanTicker = null; rerenderMigFromCache(); e.stopPropagation();
      });
    });
    var scroll = panel.querySelector('.gbs-scroll');
    if (scroll) {
      scroll.addEventListener('wheel', function (e) {
        if (!e.ctrlKey && !e.metaKey) return;
        var ES = window.EdShell;
        if (!ES || !ES.setScope || !ES.getScope) return;
        e.preventDefault();
        var order = ['auto', 'wider', 'all'];
        var cur = order.indexOf(ES.getScope()); if (cur === -1) cur = 0;
        var next = e.deltaY > 0 ? Math.min(order.length - 1, cur + 1) : Math.max(0, cur - 1);
        if (next !== cur) ES.setScope(order[next]);
      }, { passive: false });
    }
  }

  function migrationSection(strikesD, terrain, spot, tk) {
    _lastMig = { strikesD: strikesD, terrain: terrain, spot: spot, tk: tk };
    if (_migPanTicker !== tk) { _migPanAnchor = null; _migPanTicker = tk; }
    if (!strikesD) return '<div class="td-panel" id="tdMigration"><h4>Positioning migration &amp; volume</h4>' +
      '<div class="placeholder"><div class="sm">no per-strike gamma for this symbol yet</div></div></div>';
    var todayAll = (strikesD.today && strikesD.today[_migScope]) || [];
    if (!todayAll.length) {
      var why = strikesD.levels_stale_reason;
      return '<div class="td-panel" id="tdMigration"><h4>Positioning migration &amp; volume</h4>' +
        '<div class="placeholder"><div class="sm">' +
        (why ? 'no per-strike rows — ' + esc(why) : 'no per-strike gamma for this symbol yet') +
        '</div></div></div>';
    }
    var priorAll = (strikesD.prior && strikesD.prior[_migScope]) || [];
    var ghost = {}; priorAll.forEach(function (r) { ghost[r[0]] = r[1]; });
    var asc = todayAll.slice().sort(function (a, b) { return a[0] - b[0]; });
    var ascStrikes = asc.map(function (r) { return r[0]; });
    var sel = (window.EdShell && window.EdShell.scopeSelect)
      ? window.EdShell.scopeSelect(ascStrikes, _migPanAnchor != null ? _migPanAnchor : spot)
      : { idx: asc.map(function (_r, i) { return i; }), shown: asc.length, total: asc.length };
    var win = sel.idx.map(function (i) { return asc[i]; }).sort(function (a, b) { return b[0] - a[0]; });
    var note = (window.EdShell && window.EdShell.scopeNote)
      ? window.EdShell.scopeNote({ total: todayAll.length, shown: win.length }) : '';
    if (_migPanAnchor != null) note += '<div class="gbs-allexp">PANNED to ' + num(_migPanAnchor, _migPanAnchor % 1 ? 2 : 0) +
      ' — not following spot; double-click a strike label to resume</div>';
    var maxAbs = 1, maxVol = 1;
    win.forEach(function (r) {
      maxAbs = Math.max(maxAbs, Math.abs(r[1]), Math.abs(ghost[r[0]] || 0));
      maxVol = Math.max(maxVol, r[2] || 0);
    });
    var spotStrike = win.reduce(function (best, r) {
      return (best == null || Math.abs(r[0] - spot) < Math.abs(best - spot)) ? r[0] : best; }, null);
    var cw = terrain && terrain.call_wall, pw = terrain && terrain.put_wall;
    var withGhost = [], byVolRows = [];
    var rows = '';
    win.forEach(function (r) {
      var k = r[0], gx = Number(r[1]) || 0, vol = r[2], gy = ghost[k];
      var hasGy = gy != null;
      if (hasGy) withGhost.push({ k: k, gx: gx, gy: gy });
      if (vol) byVolRows.push({ k: k, vol: vol });
      var pos = gx >= 0, wToday = Math.min(100, Math.abs(gx) / maxAbs * 100);
      var ghostBar = hasGy
        ? '<i class="mig-ghost ' + (gy >= 0 ? 'pos' : 'neg') + '" style="width:' + Math.min(100, Math.abs(gy) / maxAbs * 100).toFixed(1) + '%"></i>' : '';
      var delta = hasGy ? gx - gy : null;
      var deltaHtml = delta == null ? '<span class="mig-delta"></span>'
        : '<span class="mig-delta ' + (delta >= 0 ? 'pos' : 'neg') + '">' + (delta >= 0 ? '▲' : '▼') + usd(Math.abs(delta)) + '</span>';
      var rowCls = 'gbs-row mig-row' + (k === spotStrike ? ' spot' : '') +
        (cw != null && k === cw ? ' mig-wall-call' : '') + (pw != null && k === pw ? ' mig-wall-put' : '');
      rows += '<div class="' + rowCls + '">' +
        '<span class="gbs-k">' + num(k, k % 1 ? 2 : 0) + '</span>' +
        '<span class="gbs-track mig-track"><i class="gbs-bar ' + (pos ? 'pos' : 'neg') + '" style="width:' + wToday.toFixed(1) + '%"></i>' +
        (_migGhost ? ghostBar : '') + '</span>' +
        '<span class="gbs-v ' + (pos ? 'pos' : 'neg') + '">' + usd(gx) + '</span>' +
        (_migGhost ? deltaHtml : '') +
        '<span class="gbs-vol" title="session volume">' + fmtVol(vol) + '</span>' +
        (k === spotStrike ? migTag('SPOT', 'spot') : '') +
        (cw != null && k === cw ? migTag('CALL WALL', 'call') : '') +
        (pw != null && k === pw ? migTag('PUT WALL', 'put') : '') +
        '</div>';
    });
    var byVolTop = byVolRows.slice().sort(function (a, b) { return b.vol - a.vol; }).slice(0, 2);
    var scopeChips = '<div class="mig-chips">' + MIG_SCOPES.map(function (s) {
      return '<span class="mig-chip' + (s[0] === _migScope ? ' on' : '') + '" data-mig-scope="' + s[0] + '">' + s[1] + '</span>';
    }).join('') + '<span class="mig-chip' + (_migGhost ? ' on' : '') + '" data-mig-ghost="1">GHOST</span></div>';
    // A zero here has TWO different causes and they are not the same fact: the session has
    // genuinely traded nothing yet, or the chain behind these rows was read before it started
    // trading and hasn't refreshed since (ported verbatim from static/chart.html's drawGamma,
    // same /api/terrain/strikes staleness fields GEX-by-Strike's own badge already reads).
    var totVol = win.reduce(function (a, r) { return a + (r[2] || 0); }, 0);
    var volNote = '';
    if (totVol <= 0) {
      volNote = strikesD.levels_stale
        ? '<div class="mig-vol-note stale">zero volume here is the SNAPSHOT, not the session — this chain is stale; see the source badge above</div>'
        : '<div class="mig-vol-note">no option volume yet this session — the counter resets at the new session and fills from the open</div>';
    }
    // Wiring itself must wait until this HTML is actually in the DOM (loadImpl assigns
    // h.innerHTML after this function returns) -- cached here so loadImpl can wire it right
    // after, and so a drag-triggered rerenderMigFromCache() computes the same window again.
    _lastMig.ascStrikes = ascStrikes; _lastMig.win = win;
    return '<div class="td-panel" id="tdMigration"><h4>Positioning migration &amp; volume ' +
      '<span class="mig-legend"><i class="sw" style="background:var(--ed-pos)"></i>+γ today ' +
      '<i class="sw" style="background:var(--ed-neg)"></i>-γ today ' +
      '<i class="sw ghostsw"></i>yesterday (ghost)</span></h4>' +
      scopeChips + '<div class="mig-top">' + note + volNote + '</div>' +
      '<div class="gbs-scroll"><div class="gbs">' + rows + '</div></div>' +
      '<div class="gbs-scale"><span class="neg">−' + usd(maxAbs) + '</span><span>0</span><span class="pos">+' + usd(maxAbs) + '</span></div>' +
      migrationCoach(withGhost, byVolTop, terrain) +
      '</div>';
  }

  // Chip clicks re-trigger through the SAME coalesced loader as a ticker switch or refresh tick
  // (see loadPcr()'s identical key-composition convention in ed-gamma-panels.js) -- a direct
  // loadImpl(tk) call here would run a second, uncoalesced fetch alongside whatever the loader
  // already has in flight, and whichever one resolved last would win regardless of which was
  // actually the newest request.
  function wireMigrationChips(h, tk) {
    h.querySelectorAll('[data-mig-scope]').forEach(function (b) {
      b.addEventListener('click', function () {
        var s = b.getAttribute('data-mig-scope'); if (s === _migScope) return;
        _migScope = s; retrigger();
      });
    });
    var gh = h.querySelector('[data-mig-ghost]');
    if (gh) gh.addEventListener('click', function () { _migGhost = !_migGhost; retrigger(); });
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
      // snapshot=live -- see ed-liquidity-map.js's identical comment; the endpoint's own
      // default is a frozen pre-9:30ET snapshot, wrong for an "as of right now" synthesis page.
      fetchJson('/api/liquidity-snapshot?ticker=' + encodeURIComponent(tk) + '&snapshot=live', signal),
      // same endpoint GEX-by-Strike already reads (ed-gamma-panels.js loadGbsImpl) -- reused
      // here, not recomputed, for the migration/volume section below.
      fetchJson('/api/terrain/strikes?ticker=' + encodeURIComponent(tk), signal),
    ]).then(function (results) {
      if (!stillRightNow(tk)) return;
      var detect = results[0], levelsD = results[1], terrain = results[2], snap = results[3], strikesD = results[4];
      // Independent-review finding, REPRODUCED: this used to fall back to terrain.spot when
      // levelsD was absent -- both endpoints resolve spot via the same server-side
      // resolve_spot() authority today (server.py's get_levels/_reprice_cached_terrain), so
      // it never disagreed in practice, but the shape is exactly what tools/spot_binding_lock.py
      // exists to ban (RC-225: a spot value chosen from whichever of two independent responses
      // happened to be present). /api/levels is server.py's own documented canonical serving
      // contract for spot ("every other surface carries the values out of the same snapshot");
      // a failed /api/levels now reads as honest absence (blank, see isFinite(spot) below)
      // instead of silently substituting a second source.
      var spot = levelsD ? Number(levelsD.spot) : NaN;
      h.innerHTML =
        '<div class="fl-head"><div class="fl-c"><span class="fl-lab">Right now</span><span class="fl-sym">' + esc(tk) +
        '</span><span class="fl-meta">' + (isFinite(spot) ? 'spot ' + num(spot) : '') + '</span></div></div>' +
        '<div class="td-grid">' + detectStage(detect) + frameStage(levelsD, spot) + confirmStage(terrain) + '</div>' +
        contextSummary(terrain, snap, spot) +
        migrationSection(strikesD, terrain, spot, tk) +
        '<div class="notproven" style="margin-top:14px;">HOME PRESERVED — DECISION AUTHORITY NOT_PROVEN. ' +
        'This page assembles already-canonical Detect/Frame/Confirm signals and classifies them in plain English; it computes no new value and renders no Execute step. ' +
        'THE CALL and 1m/5m/15m/60m horizons remain excluded until ticker-universal evidence earns them.</div>';
      wireMigrationChips(h, tk);
      var migEl = document.getElementById('tdMigration');
      if (migEl && _lastMig) wireMigInteraction(migEl, _lastMig.ascStrikes, _lastMig.win, tk);
    }).catch(function (e) {
      // Every sibling loader in this file (ed-order-flow.js, ed-order-flow-heatmap.js,
      // ed-liquidity-map.js) ends in a .catch() that renders an honest fallback; this one
      // didn't, so an exception while building the stage cards left the panel stuck on
      // aria-busy/stale content with no visible failure state.
      if (e && e.name === 'AbortError') return;
      if (stillRightNow(tk)) h.innerHTML = '<div class="placeholder"><div class="sm">no console serving Right Now — one of its endpoints failed to render</div></div>';
    });
  }
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); }, reset: function () {} };
  // Every dimension that makes this "a different request" must be in the key -- ticker AND the
  // migration section's own scope/ghost toggles -- or a toggle click queues behind an in-flight
  // fetch for the OLD toggle state instead of aborting it (the exact bug class this session's
  // audit found in loadStructures()/the order-flow heatmap's minute-range toggle).
  function _loadKey() { return ticker() + '|mig=' + _migScope + '|ghost=' + (_migGhost ? 1 : 0); }
  function retrigger() { if (isRightNow()) _loader.trigger(_loadKey()); }
  function load() {
    if (!isRightNow()) return;
    var tEl = document.getElementById('tdTicker'); if (tEl) tEl.textContent = ticker().replace('$', '');
    _loader.trigger(_loadKey());
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }
})();
