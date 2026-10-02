/* Ed Console — Options/Gamma supporting panels (RC-UI-1). PRESENTATION ONLY.
   Key Levels rail  <- GET /api/terrain      (canonical levels SSOT)
   GEX by Strike    <- GET /api/terrain/strikes  (per-strike net_gex_1pct$)
   Strike Detail    <- GET /api/chain         (vendor per-contract OI/vol/greeks)
   No trading semantics are computed here. Bar scaling is visual normalisation over the
   already-computed displayed values; distances/positions are formatting only. */
(function () {
  'use strict';

  var usd = window.EdGamma.formatUsd;
  function px(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  // Compact SESSION VOLUME (native totalVolume, never OI or last-trade size — see the row
  // source below) for the GEX-by-strike row. No sign/color: volume is a magnitude, not signed.
  function fmtVol(n) {
    if (n == null || isNaN(n)) return '—';
    var a = Math.abs(Number(n));
    if (a >= 1e6) return (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return (a / 1e3).toFixed(1) + 'K';
    return String(Math.round(a));
  }
  function txt(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  // Delta/DEX and Open Interest fall back to displaying the SAME gamma `.sub-pane` (they have
  // no dedicated pane of their own -- showSubPane()'s fallback rule), which is where Key
  // Levels/GEX-by-Strike/PCR/the Options Flow tape all physically live. This check used to be
  // 'gamma' only, from before dex/oi existed as real subviews; ed-gamma.js's own
  // _isGammaFamilySubview was correctly generalized when they were added, but this sibling
  // file's gate was not, leaving all four panels frozen (reproduced live, 2026-09-13: switching
  // ticker while on Delta/DEX left Key Levels showing the PREVIOUS ticker's spot/flip/wall
  // values) -- every check in this file must recognize all three, exactly like ed-gamma.js's.
  function isGamma() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && (s.subview === 'gamma' || s.subview === 'dex' || s.subview === 'oi');
  }
  function ticker() { return ((window.EdShell && window.EdShell.getState()) || {}).ticker || ''; }

  var REGIME = {
    LONG_GAMMA_CHOP: { t: 'Long γ · chop', c: 'var(--ed-pos-ink)' },
    SHORT_GAMMA_TREND: { t: 'Short γ · trend', c: 'var(--ed-warn)' },
    UNAVAILABLE: { t: 'unavailable', c: 'var(--ed-ink-3)' },
  };

  // ---------- Key Levels rail ----------
  function stillLevelsCtx(tk) { return isGamma() && !!document.getElementById('klSpot') && ticker() === tk; }
  // ROUND 8 (2026-09-13): keyed on ticker so a held/slow fetch for an ABANDONED ticker is
  // aborted immediately once a different ticker is selected, instead of blocking it.
  function loadLevelsImpl(tk, _signal) {
    if (!stillLevelsCtx(tk)) return;
    // shared with ed-gamma-chart.js's read of the same /api/terrain: one network call
    return window.EdL1SseGuards.sharedFetchJson('/api/terrain?ticker=' + encodeURIComponent(tk))
      .then(function (d) { if (stillLevelsCtx(tk)) renderLevels(d); })
      .catch(function () {
        if (stillLevelsCtx(tk)) renderLevels(null);
      });
  }
  var _levelsLoader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadLevelsImpl(ticker(), signal); });
  function loadLevels() { _levelsLoader.trigger(ticker()); }
  function renderLevels(d) {
    var ids = ['klSpot', 'klFlip', 'klCall', 'klPut', 'klAbs', 'klPeak', 'klNet', 'klRegime'];
    paintPcr(d && !d.error ? d : null);
    if (!d || d.error) {
      ids.forEach(function (id) { txt(id, '—'); });
      txt('klSrc', d && d.error ? 'terrain not ready' : 'offline');
      return;
    }
    txt('klFlip', px(d.gamma_flip));
    txt('klCall', px(d.call_wall));
    txt('klPut', px(d.put_wall));
    txt('klAbs', px(d.absolute_gamma_strike));
    txt('klPeak', px(d.net_gex_peak));
    // Net GEX / 1% move — signed $, coloured by sign (formatting only)
    var net = document.getElementById('klNet');
    if (net) {
      var v = d.net_gex_at_spot;
      net.textContent = (v == null) ? '—' : usd(v);
      net.style.color = (v == null) ? '' : (v >= 0 ? 'var(--ed-pos-ink)' : 'var(--ed-neg-ink)');
    }
    var reg = document.getElementById('klRegime');
    if (reg) {
      var rm = REGIME[d.regime] || { t: (d.regime || '—'), c: 'var(--ed-ink-2)' };
      reg.textContent = rm.t; reg.style.color = rm.c;
    }
    // B: the levels rail recedes when terrain reports stale
    var klb = document.getElementById('klBody');
    if (klb) klb.classList.toggle('recede', !!d.levels_stale);
    // freshness / provenance line
    var src = document.getElementById('klSrc');
    if (src) {
      if (d.levels_stale) {
        // compact status grammar: state + age on the panel; the full reason is disclosed in the
        // tooltip (title) rather than as a paragraph that consumes the Key Levels rail
        var age = (window.EdShell && window.EdShell.fmtAge) ? window.EdShell.fmtAge(d.levels_age_sec)
          : (d.levels_age_sec != null ? Math.round(d.levels_age_sec) + 's' : '');
        src.textContent = 'STALE' + (age ? ' · ' + age : '');
        src.title = d.levels_stale_reason || 'terrain levels are stale';
        src.style.color = 'var(--ed-stale)';
      } else if (d.levels_stale === false) {
        src.textContent = 'terrain · live';
        src.title = '';
        src.style.color = '';
      } else {
        // no freshness verdict served: never read as live
        src.textContent = 'freshness not reported';
        src.title = '';
        src.style.color = 'var(--ed-stale)';
      }
      // #5: terrain levels are AGGREGATE across expiries; if the workspace filters to one expiry,
      // disclose that these levels are still all-exp (never silently relabel them as selected-expiry).
      if (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) src.textContent += ' · all-exp';
    }
  }

  // ---------- Put/Call OI and volume <- /api/terrain pcr_by_expiry, pcr_volume_by_expiry (selected expiry, else the front one) ----------
  function expiryFilter() { return (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) || ''; }
  function paintPcr(d) {
    var byExp = (d && d.pcr_by_expiry) || {};
    var byExpVol = (d && d.pcr_volume_by_expiry) || {};
    // the selected expiry, else the whole book -- both served; the page picks no expiry itself
    var ex = expiryFilter() || '';
    var v = ex ? byExp[ex] : (d && d.pcr_all);
    var vv = ex ? byExpVol[ex] : (d && d.pcr_volume_all);
    var scope = ex ? 'exp ' + ex : 'all exp';
    txt('klPcr', v == null ? '—' : Number(v).toFixed(2));
    txt('klPcrScope', 'OI · ' + scope);
    txt('klPcrVol', vv == null ? '—' : Number(vv).toFixed(2));
    txt('klPcrVolScope', 'volume · ' + scope);
  }

  // ---------- GEX by Strike ----------
  function stillGbsCtx(tk) { var host = document.getElementById('gbsBody'); return isGamma() && !!host && ticker() === tk; }
  // ROUND 8 (2026-09-13): keyed on ticker so a held/slow fetch for an ABANDONED ticker is
  // aborted immediately once a different ticker is selected, instead of blocking it.
  function loadGbsImpl(tk, _signal) {
    var host = document.getElementById('gbsBody');
    if (!stillGbsCtx(tk)) return;
    if (_gbsPanTicker !== tk) { _gbsPan.centre = null; _gbsPan.shift = 0; _gbsPanTicker = tk; }
    // shared with ed-gamma-chart.js's read of the same window: one network call
    return window.EdL1SseGuards.sharedFetchJson('/api/terrain/strikes?ticker=' + encodeURIComponent(tk) +
        window.EdShell.windowQuery(_gbsPan))
      .then(function (d) { if (stillGbsCtx(tk)) renderGbs(host, d, tk); })
      .catch(function () {
        if (stillGbsCtx(tk)) renderGbs(host, null, tk);
      });
  }
  var _gbsLoader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadGbsImpl(ticker(), signal); });
  function loadGbs() { _gbsLoader.trigger(ticker()); }
  var SRC_LABEL = { terrain_live_cache: 'terrain live' };
  function srcLabel(s) {
    if (!s) return '';
    if (SRC_LABEL[s]) return SRC_LABEL[s];
    return s;
  }
  function setGbsAsOf(d) {
    var el = document.getElementById('gbsSrc'); if (!el) return;
    if (!d || d.today_source == null) { el.innerHTML = ''; return; }
    // reuse the terrain authority the server already merged (today_age_sec / levels_stale) - no
    // client-side freshness computation; the badge only formats those server-owned fields.
    el.innerHTML = (window.EdShell && window.EdShell.asOfBadge)
      ? window.EdShell.asOfBadge({ label: srcLabel(d.today_source), ageSec: d.today_age_sec,
          stale: !!d.levels_stale, reason: d.levels_stale_reason,
          live: (d.today_source === 'terrain_live_cache' && d.levels_stale === false) })
      : '';
  }
  // A per-strike bar list (GEX, vanna, charm by strike): the window of `rows` the server sent
  // ([strike, value, ...], ascending), drawn highest strike first, each bar's length its |value|
  // against the served scale (view.max_abs). The strike labels pan the window (wireStrikeAxis ->
  // `reload`); a pan is never silent. `opts`: `top` html above the list, `attrs(r)` and `cells(r)`
  // a row's extra attributes and cells.
  function drawStrikeBars(host, rows, view, pan, spotStrike, reload, opts) {
    opts = opts || {};
    window.EdShell.panServed(pan, view.centre);
    var maxAbs = view.max_abs;   // at least |v| for every v drawn
    var note = (opts.top || '') + (pan.centre != null ? '<div class="gbs-allexp">Panned to ' +
      px(pan.served, pan.served % 1 ? 2 : 0) + ' · double-click a strike to follow the price</div>' : '') +
      (view.note ? '<div class="gbs-allexp">' + esc(view.note) + '</div>' : '');   // why not around the price
    var bars = '';
    rows.slice().reverse().forEach(function (r) {
      // a strike with no value is unknown: no bar, '—' (never a $0 bar)
      var k = r[0], v = r[1] == null ? null : Number(r[1]);
      var w = v == null || v === 0 ? 0 : Math.abs(v) / maxAbs * 100, pos = v != null && v >= 0;
      bars += '<div class="gbs-row' + (k === spotStrike ? ' spot' : '') + '" data-strike="' + k + '"' +
        (opts.attrs ? opts.attrs(r) : '') + '>' +
        '<span class="gbs-k">' + px(k, k % 1 ? 2 : 0) + '</span>' +
        '<span class="gbs-track"><i class="gbs-bar ' + (pos ? 'pos' : 'neg') + '" style="width:' + w.toFixed(1) + '%"></i></span>' +
        '<span class="gbs-v ' + (v == null ? '' : pos ? 'pos' : 'neg') + '">' + (v == null ? '—' : usd(v)) + '</span>' +
        (opts.cells ? opts.cells(r) : '') + '</div>';
    });
    // the bars scroll in their own area; the -/0/+ axis is pinned at the foot
    host.innerHTML = '<div class="gbs-top">' + note + '</div>' +
      '<div class="gbs-scroll"><div class="gbs">' + bars + '</div></div>' +
      '<div class="gbs-scale"><span class="neg">−</span><span>0</span><span class="pos">+</span></div>';
    host.querySelectorAll('.gbs-row').forEach(function (rr) {   // click a strike: every panel follows it
      rr.addEventListener('click', function () { if (window.EdShell) window.EdShell.setStrike(Number(rr.getAttribute('data-strike'))); });
    });
    var firstRow = host.querySelector('.gbs-row');
    window.EdShell.wireStrikeAxis(host.querySelectorAll('.gbs-k'), host.querySelector('.gbs-scroll'), pan,
      firstRow ? firstRow.getBoundingClientRect().height : 0, reload);
    var sr = host.querySelector('.gbs-row.spot');
    if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
  }

  // GEX by Strike shows the window the server sends (scope, and the operator's pan)
  var _gbsPan = window.EdShell.newPan(), _gbsPanTicker = null;

  function renderGbs(host, d, tk) {
    setGbsAsOf(d);
    var rows = d && d.today && d.today.all;
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        (d ? 'no banked per-strike gamma for this symbol' : 'no console serving /api/terrain/strikes') + '</div></div>';
      return;
    }
    // /api/terrain/strikes is aggregate across expiries; with one expiry selected, say so
    var expOn = window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry();
    // yesterday's change per strike, served (migration.all.rows: [strike, today, prior, change])
    var chg = {}, mig = d.migration && d.migration.all;
    ((mig && mig.compared && mig.rows) || []).forEach(function (m) { chg[m[0]] = m[3]; });
    // rows: [strike, net_gex_1pct$, session volume]; the volume is a count, never coloured
    drawStrikeBars(host, rows, d.views.all, _gbsPan, d.spot_strike, loadGbs, {
      top: expOn ? '<div class="gbs-allexp">all expiries</div>' : '',
      attrs: function (r) { return ' data-volume="' + (r[2] == null ? '' : r[2]) + '"'; },
      cells: function (r) {
        return '<span class="gbs-vol" title="session volume">' + fmtVol(r[2]) + '</span>' +
          '<span class="gbs-chg" title="net GEX change vs the previous session">' +
          (chg[r[0]] == null ? '—' : usd(chg[r[0]])) + '</span>';
      },
    });
    applyGbsHighlight(host);
  }
  function applyGbsHighlight(host) {
    host = host || document.getElementById('gbsBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.gbs-row.gbs-sel').forEach(function (n) { n.classList.remove('gbs-sel'); });
    if (sel == null) return;
    host.querySelectorAll('.gbs-row[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('gbs-sel'); });
  }

  // ---------- Strike Detail ----------
  // the workspace expiry filter, else the selected strike's own expiry
  function strikeDetailExpiry() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return expiryFilter() || s.selExpiry || null;
  }
  // loadStrike() records the desired (strike, expiry); the loader always fetches the current one
  var _sdDesired = { strike: null, expiry: null };
  function stillStrikeCtx(tk, strike, expiry) {
    return ticker() === tk && _sdDesired.strike === strike && _sdDesired.expiry === expiry;
  }
  // ROUND 8 (2026-09-13): keyed on ticker+strike+expiry so a held/slow fetch for an
  // ABANDONED strike is aborted immediately once a different one is selected, instead of
  // blocking it. Independent-review finding, REPRODUCED ("retain previous contract demand
  // after a failed chain read"): a network-level failure (this catch) bypassed renderStrike
  // entirely and never cleared additional-contract demand, unlike a successful-but-empty
  // chain (renderStrike's own "no chain for this expiry" path already clears it) -- the
  // PREVIOUS strike's contracts stayed subscribed forever after a genuine fetch failure.
  function loadStrikeImpl(strike, expiry, signal) {
    var host = document.getElementById('sdBody');
    if (!host || !stillStrikeCtx(ticker(), strike, expiry)) return;
    var tk = ticker();
    var q = '/api/chain?ticker=' + encodeURIComponent(tk) + (expiry ? '&expiry=' + encodeURIComponent(expiry) : '');
    return fetch(q, { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillStrikeCtx(tk, strike, expiry)) renderStrike(host, d, strike, expiry); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;   // superseded by a newer strike -- that load renders instead
        if (stillStrikeCtx(tk, strike, expiry)) {
          host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/chain</div></div>';
          _setAdditionalContractsDemand([]);
        }
      });
  }
  var _sdLoader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadStrikeImpl(_sdDesired.strike, _sdDesired.expiry, signal); });
  function loadStrike(strike, expiry) {
    _sdDesired = { strike: strike, expiry: expiry };
    _sdLoader.trigger(ticker() + '|' + strike + '|' + (expiry || ''));
  }
  var SCOPE_LABEL = {
    complete_single_expiry: { t: 'vendor · complete (ALL)', live: true },
    unavailable: { t: 'vendor · unavailable', stale: true },
  };
  function setSdAsOf(d) {
    var el = document.getElementById('sdSrc'); if (!el) return;
    var sc = d && d.scope, kind = sc && sc.kind;
    if (!kind) { el.innerHTML = ''; return; }
    var m = SCOPE_LABEL[kind] || { t: kind };
    el.innerHTML = (window.EdShell && window.EdShell.asOfBadge)
      ? window.EdShell.asOfBadge({ label: m.t, live: !!m.live, stale: !!m.stale,
          title: 'chain scope: ' + kind + (sc.reason ? ' — ' + sc.reason : '') })
      : '';
  }
  // Independent-review finding (2026-09-12): an empty/failed chain result left Strike
  // Detail showing "no chain" while the PREVIOUS strike's additional-contract
  // subscription stayed active forever -- nothing ever told the plural endpoint that
  // demand had ended. Every path out of renderStrike must state the additional-contract
  // demand for the current render, including "none".
  // ownerKey is 'strike:<ticker>' (2026-09-21, universal-ticker-scope fix, same class of
  // defect and same fix pattern as the heatmap's _heatmapOwnerKey): a single shared
  // 'default' owner meant switching tickers here silently clobbered whatever the PREVIOUS
  // ticker's Strike Detail selection had demanded, exactly like the heatmap's shared
  // 'heatmap' key did. The ticker just left is explicitly released so demand does not grow
  // unbounded across every ticker ever selected in one session.
  var _lastStrikeOwnerTicker = null;
  function _setAdditionalContractsDemand(symbols) {
    var tk = ticker();
    if (_lastStrikeOwnerTicker && _lastStrikeOwnerTicker !== tk) {
      window.EdStream.setAdditionalContracts([], 'strike:' + _lastStrikeOwnerTicker);
    }
    _lastStrikeOwnerTicker = tk;
    return window.EdStream.setAdditionalContracts(symbols || [], 'strike:' + tk);
  }
  function renderStrike(host, d, strike, expiry) {
    setSdAsOf(d);
    var cs = (d && d.contracts) || [];
    if (!cs.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' + esc(window.EdShell.chainEmptyText(d)) + '</div></div>';
      _setAdditionalContractsDemand([]);
      return;
    }
    function pick(side) {
      return cs.filter(function (c) {
        return (c.putCall || '').toUpperCase() === side &&
          Math.abs(Number(c.strikePrice) - Number(strike)) < 0.01; })[0];
    }
    var call = pick('CALL'), put = pick('PUT');
    txt('sdCtx', px(strike, strike % 1 ? 2 : 0) + (expiry ? ' · ' + esc(expiry.slice(5)) : ''));
    // d2: decimals; none: every digit Schwab sent (its Greeks)
    function cell(c, k, d2) { var v = c ? c[k] : null; return (v == null) ? '—' : (typeof v === 'number' ? (d2 == null ? String(v) : v.toFixed(d2)) : esc(v)); }
    // GEX ($) column: per-side GEX$ is not served (computing it would be frontend math) -> "—"; the
    // NET row is this expiry's net GEX at this strike, served on the same /api/chain response --
    // the heatmap's own cell (2026-09-27: it was GEX-by-Strike's all-expiry total, beside one
    // expiry's contracts).
    var net = null;
    ((d && d.net_gex_by_strike) || []).forEach(function (r) {
      if (Math.abs(Number(r[0]) - Number(strike)) < 0.01) net = Number(r[1]);
    });
    var netCls = net == null ? '' : (net >= 0 ? 'pos' : 'neg');
    host.innerHTML =
      '<table class="sd"><thead><tr><th>Type</th><th>OI</th><th>Vol</th><th>Gamma</th><th>GEX $</th><th>Delta</th><th>IV%</th></tr></thead><tbody>' +
      '<tr><td class="side c">Call</td><td>' + cell(call, 'openInterest', 0) + '</td><td>' + cell(call, 'totalVolume', 0) +
      '</td><td>' + cell(call, 'gamma') + '</td><td class="dim">—</td><td>' + cell(call, 'delta') + '</td><td>' + cell(call, 'volatility') + '</td></tr>' +
      '<tr><td class="side p">Put</td><td>' + cell(put, 'openInterest', 0) + '</td><td>' + cell(put, 'totalVolume', 0) +
      '</td><td>' + cell(put, 'gamma') + '</td><td class="dim">—</td><td>' + cell(put, 'delta') + '</td><td>' + cell(put, 'volatility') + '</td></tr>' +
      '<tr class="sd-net"><td class="side">Net</td><td>—</td><td>—</td><td>—</td><td class="' + netCls + '">' +
      (net == null ? '—' : usd(net)) + '</td><td>—</td><td>—</td></tr>' +
      '</tbody></table><div class="sd-src">vendor per-contract · net GEX$ this expiry · /api/chain</div>';
    // stream the displayed strike's two contracts (always stated, even empty); the tape reads
    // the streamed contracts, so it loads once the server has accepted a changed demand
    var p = _setAdditionalContractsDemand([call && call.symbol, put && put.symbol].filter(Boolean));
    if (p) p.then(function (r) { if (r && r.accepted && !r.unchanged) loadOf(); });
  }

  // Independent-review finding (2026-09-12), REPRODUCED: switching the active ticker did
  // not invalidate Strike Detail's in-flight /api/chain fetch or reset its rendered content
  // -- ed-core.js's setTicker() already clears the SHARED selStrike (a fresh strike click is
  // required before loadStrike fires again), but a chain fetch for the OLD ticker that was
  // already in flight when the switch happened still landed under the NEW ticker's context.
  // Reproduced: request AMD's chain, switch to NVDA, deliver the delayed AMD response --
  // Strike Detail rendered AMD's values and requested AMD's contracts. Fixed by clearing the
  // desired (strike, expiry) so `stillStrikeCtx`'s ticker check discards any in-flight
  // response for the OLD ticker (2026-09-13: this now doubles as the fix's context-identity
  // check, replacing the old `_sgen` generation counter) and no pending strike is left to
  // fetch under the new ticker without a fresh click, plus clearing all Strike Detail state
  // (DOM placeholder + additional-contracts demand) the instant the ticker changes, same
  // discipline `_setAdditionalContractsDemand([])` already gives an empty/failed chain.
  function resetStrikeDetailForTickerChange() {
    _sdDesired = { strike: null, expiry: null };
    var host = document.getElementById('sdBody');
    if (host) {
      host.innerHTML = '<div class="placeholder"><div class="sm">Select a strike/expiry. '
        + 'OI · volume · gamma · delta · IV from /api/chain (vendor).</div></div>';
    }
    _setAdditionalContractsDemand([]);
  }

  // ---------- Vanna / Charm by strike: the same bar list (drawStrikeBars), each its own pan ----------
  function _mkStrikeBar(kind, endpoint, hostId, srcId) {
    function inSub() {
      var s = (window.EdShell && window.EdShell.getState()) || {};
      return s.workspace === 'options' && s.subview === kind;
    }
    function stillCtx(tk) { var host = document.getElementById(hostId); return inSub() && !!host && ticker() === tk; }
    var pan = window.EdShell.newPan(), panTicker = null;
    function renderIt(host, d) {
      var src = document.getElementById(srcId); if (src) src.textContent = '';
      if (!d || !d.available || !d.rows || !d.rows.length) {
        host.innerHTML = '<div class="placeholder"><div class="sm">' +
          (d && d.reason ? esc(d.reason) : ('no console serving ' + endpoint)) + '</div></div>';
        return;
      }
      drawStrikeBars(host, d.rows, d.view, pan, d.spot_strike, load);
    }
    function impl(tk, signal) {
      var host = document.getElementById(hostId);
      if (!stillCtx(tk)) return;
      if (panTicker !== tk) { pan.centre = null; pan.shift = 0; panTicker = tk; }
      return fetch(endpoint + '?ticker=' + encodeURIComponent(tk) + window.EdShell.windowQuery(pan), { cache: 'no-store', signal: signal })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) { if (stillCtx(tk)) renderIt(host, d); })
        .catch(function (e) {
          if (e && e.name === 'AbortError') return;
          if (stillCtx(tk)) renderIt(host, null);
        });
    }
    var loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return impl(ticker(), signal); });
    function load() { if (inSub()) loader.trigger(ticker()); }
    return load;
  }
  var loadVanna = _mkStrikeBar('vanna', '/api/options/vanna-by-strike', 'vnBody', 'vnSrc');
  var loadCharm = _mkStrikeBar('charm', '/api/options/charm-by-strike', 'chmBody', 'chmSrc');

  // ---------- Structures — contract-safety metadata (operator field-inventory audit) ------
  // Already-flowing /api/chain fields (multiplier/nonStandard/deliverables/settlementType/
  // exerciseType/expirationType/lastTradingDay/pennyPilot) that the Chain ladder never
  // surfaces -- one strike per row, both sides, no new computation, no second fetch shape
  // (same /api/chain response Chain and Strike Detail already read).
  function inStructures() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && s.subview === 'structures';
  }
  function stillStructuresCtx(tk, exp) {
    var host = document.getElementById('stBody');
    return inStructures() && !!host && ticker() === tk &&
      (exp == null || (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) === exp);
  }
  function _flag(label, on) { return '<span class="st-flag' + (on ? ' on' : '') + '">' + esc(label) + '</span>'; }
  // lastTradingDay is native epoch MILLISECONDS (the same convention as quoteTimeInLong/
  // tradeTimeInLong), not an ISO date string -- reproduced live: String(...).slice(0,10) on
  // 1789430400000 printed the meaningless digit-string "1789430400", not a date.
  function fmtEpochMs(ms) {
    if (ms == null || isNaN(ms)) return '—';
    var d = new Date(Number(ms));
    if (isNaN(d.getTime())) return '—';
    return d.toISOString().slice(0, 10);
  }
  // ADJUSTED DELIVERABLE: served per contract (Schwab's nonStandard flag, as sent)
  function renderStructures(host, d, tk) {
    var src = document.getElementById('stSrc'); if (src) src.textContent = '';
    var ladder = ((d && d.ladder) || []).filter(function (r) { return r.first; });   // served: one row per strike, high to low
    if (!ladder.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        (d ? esc(window.EdShell.chainEmptyText(d)) : 'no console serving /api/chain') + '</div></div>';
      return;
    }
    var rows = ladder.map(function (r) {
      var k = r.strike, rep = r.call || r.put;   // settlement/exercise/expiration/multiplier are contract-level, same both sides at one strike/expiry
      var flags = [
        _flag('NON-STD', rep.nonStandard === true),
        _flag('PENNY', rep.pennyPilot === true),
        _flag('ADJUSTED DELIVERABLE', (d.adjusted_deliverable_symbols || []).indexOf(rep.symbol) !== -1),
      ].join('');
      return '<tr><td class="side">' + px(k, k % 1 ? 2 : 0) + '</td>' +
        '<td>' + (rep.multiplier == null ? '—' : rep.multiplier) + '</td>' +
        '<td>' + esc(rep.settlementType || '—') + '</td>' +
        '<td>' + esc(rep.exerciseType || '—') + '</td>' +
        '<td>' + esc(rep.expirationType || '—') + '</td>' +
        '<td>' + fmtEpochMs(rep.lastTradingDay) + '</td>' +
        '<td>' + flags + '</td></tr>';
    }).join('');
    host.innerHTML = '<div class="gbs-scroll"><table class="sd st-tbl">' +
      '<thead><tr><th>Strike</th><th>Multiplier</th><th>Settlement</th><th>Exercise</th><th>Exp. Type</th><th>Last Trading Day</th><th>Flags</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>' +
      '<div class="sd-src">vendor per-contract · /api/chain — no field here is inferred or defaulted</div>';
  }
  function loadStructuresImpl(tk, exp, signal) {
    var host = document.getElementById('stBody');
    if (!stillStructuresCtx(tk, exp)) return;
    var url = '/api/chain?ticker=' + encodeURIComponent(tk) + (exp ? '&expiry=' + encodeURIComponent(exp) : '');
    return fetch(url, { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillStructuresCtx(tk, exp)) renderStructures(host, d, tk); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillStructuresCtx(tk, exp)) renderStructures(host, null, tk);
      });
  }
  var _structuresLoader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) {
    return loadStructuresImpl(ticker(), (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()), signal); });
  // Keyed on ticker+expiry (ROUND 8 pattern, same as every other loader in this file) so a
  // context change while a fetch is still in flight ABORTS it immediately instead of merely
  // marking a trailing re-run pending -- an unkeyed trigger() left Structures frozen on the
  // old ticker/expiry's placeholder until the abandoned request finally settled.
  function loadStructures() {
    if (!inStructures()) return;
    var exp = (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) || '';
    _structuresLoader.trigger(ticker() + '|' + exp);
  }

  // ---------- Options Flow tape (operator field-inventory audit, 2026-09-13) ------------
  // The embedded tape widget on the Gamma pane (#ofBody) -- real native trade prints for
  // whichever contract(s) are currently desired (the same identity Strike Detail's own
  // _setAdditionalContractsDemand already established), never a fabricated buy/sell side.
  var OF_CLS_LABEL = { at_bid: 'at bid', at_ask: 'at ask', inside_spread: 'inside',
    outside_spread_low: 'below bid', outside_spread_high: 'above ask', unknown: '—' };
  function fmtOfPrice(n) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(2); }
  function fmtOfSize(n) { return (n == null || isNaN(n)) ? '—' : String(n); }
  function fmtOfTime(tsRecv) {
    if (tsRecv == null) return '—';
    var d = new Date(tsRecv * 1000);
    return d.toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/Chicago' });
  }
  function stillOfCtx(tk) { var host = document.getElementById('ofBody'); return isGamma() && !!host && ticker() === tk; }
  function renderOf(host, d) {
    var src = document.getElementById('ofSrc'); if (src) src.textContent = '';
    var rows = (d && d.rows) || [];
    if (!rows.length) {
      host.innerHTML = '<table class="of"><thead><tr><th>Time</th><th>Symbol</th><th>Exp</th><th>Type</th><th>Strike</th>' +
        '<th>Bid×Size</th><th>Ask×Size</th><th>Trade</th><th>Size</th><th>Premium</th>' +
        '<th>Vol</th><th>OI</th><th>IV%</th><th>Δ</th><th>vs Market</th></tr></thead>' +
        '<tbody><tr class="of-empty"><td colspan="14"><div class="oe-sub">' +
        esc((d && d.reason) || 'no console serving /api/options/tape') + '</div></td></tr></tbody></table>';
      return;
    }
    var body = rows.map(function (r) {
      return '<tr>' +
        '<td>' + fmtOfTime(r.ts_recv) + '</td>' +
        '<td class="of-sym">' + esc(r.symbol || '—') + '</td>' +
        '<td>' + esc(r.expiry ? r.expiry.slice(5) : '—') + '</td>' +
        '<td>' + esc(r.type || '—') + '</td>' +
        '<td>' + (r.strike == null ? '—' : px(r.strike, r.strike % 1 ? 2 : 0)) + '</td>' +
        '<td>' + fmtOfPrice(r.bid) + '×' + fmtOfSize(r.bid_size) + '</td>' +
        '<td>' + fmtOfPrice(r.ask) + '×' + fmtOfSize(r.ask_size) + '</td>' +
        '<td>' + fmtOfPrice(r.trade) + '</td>' +
        '<td>' + fmtOfSize(r.size) + '</td>' +
        '<td>' + (r.premium == null ? '—' : usd(r.premium)) + '</td>' +
        '<td>' + fmtVol(r.volume) + '</td>' +
        '<td>' + fmtOfSize(r.oi) + '</td>' +
        '<td>' + (r.iv == null ? '—' : Number(r.iv).toFixed(1)) + '</td>' +
        '<td>' + (r.delta == null ? '—' : Number(r.delta).toFixed(3)) + '</td>' +
        '<td><span class="of-cls ' + esc(r.classification || 'unknown') + '">' +
          esc(OF_CLS_LABEL[r.classification] || '—') + '</span></td></tr>';
    }).join('');
    host.innerHTML = '<table class="of"><thead><tr><th>Time</th><th>Symbol</th><th>Exp</th><th>Type</th><th>Strike</th>' +
      '<th>Bid×Size</th><th>Ask×Size</th><th>Trade</th><th>Size</th><th>Premium</th>' +
      '<th>Vol</th><th>OI</th><th>IV%</th><th>Δ</th><th>vs Market</th></tr></thead><tbody>' + body + '</tbody></table>';
  }
  function loadOfImpl(tk, signal) {
    var host = document.getElementById('ofBody');
    if (!stillOfCtx(tk)) return;
    return fetch('/api/options/tape?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillOfCtx(tk)) renderOf(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;
        if (stillOfCtx(tk)) renderOf(host, null);
      });
  }
  var _ofLoader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadOfImpl(ticker(), signal); });
  function loadOf() { if (isGamma()) _ofLoader.trigger(ticker()); }

  // ---------- events ----------
  function loadAll() { loadLevels(); loadGbs(); loadVanna(); loadCharm(); loadStructures(); loadOf(); }
  document.addEventListener('ed:ticker', function () { resetStrikeDetailForTickerChange(); loadAll(); });
  document.addEventListener('ed:expiry', loadLevels);   // the ratio is scoped to the selected expiry
  // Key Levels' Spot is the header's price row, painted on every push (the daemon's
  // live_price_rows.price_row), never the levels fetch's copy
  window.addEventListener('ed:quote_tick', function (e) {
    var q = e.detail;
    if (!q || q.ticker !== ((window.EdShell && window.EdShell.getState()) || {}).key) return;   // the served key
    txt('klSpot', q.spot_disp != null ? q.spot_disp : '—');
  });
  document.addEventListener('ed:view', loadAll);
  // a new scope is a new window: every per-strike panel re-reads it from the server
  document.addEventListener('ed:scope', function () { loadGbs(); loadVanna(); loadCharm(); });
  document.addEventListener('ed:changed', function (e) {
    if (e.detail.kind === 'flow') { loadOf(); return; }
    if (e.detail.kind !== 'levels') return;
    loadLevels(); loadGbs(); loadVanna(); loadCharm(); loadStructures();
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    if (sel != null) loadStrike(sel, strikeDetailExpiry());
  });
  document.addEventListener('ed:strike', function (e) {
    var det = e.detail || {};
    applyGbsHighlight();                       // A: sync the GEX-by-strike highlight
    if (det.strike != null) loadStrike(det.strike, det.expiry);
  });
  document.addEventListener('ed:expiry', function () {   // #5: expiry filter -> Strike Detail uses it; Levels/GBS stay aggregate + disclose
    loadLevels(); loadGbs(); loadStructures();   // Structures is expiry-scoped, same as Chain/Strike Detail
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    if (sel != null) loadStrike(sel, strikeDetailExpiry());
  });
  // Audit finding #4 (2026-09-16): initial hydration now comes SOLELY from ed-core.js's
  // deferred ed:ticker/ed:view dispatch -- see that file's init() comment and ed-gamma.js's
  // identical removal.
})();
