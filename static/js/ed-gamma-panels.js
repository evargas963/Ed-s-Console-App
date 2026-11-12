/* Ed Console — Options/Gamma supporting panels. PRESENTATION ONLY.
   Key Levels rail  <- the page's socket      (the `terrain:levels` panel, the published levels)
   GEX by Strike    <- the page's socket      (the `strikes:gbs` panel, per-strike net_gex_1pct$)
   Strike Detail    <- the page's socket      (the `chain:detail` panel, vendor per-contract OI/vol/greeks)
   Vanna / Charm    <- the page's socket      (the `vanna` / `charm` panels, per-strike net)
   No trading semantics are computed here. Bar scaling is visual normalisation over the
   already-computed displayed values; distances/positions are formatting only. */
(function () {
  'use strict';

  var usd = window.EdGamma.formatUsd;
  function px(n, d) { return (n == null || isNaN(n)) ? '-' : Number(n).toFixed(d == null ? 2 : d); }
  // Compact SESSION VOLUME (native totalVolume, never OI or last-trade size — see the row
  // source below) for the GEX-by-strike row. No sign/color: volume is a magnitude, not signed.
  function fmtVol(n) {
    if (n == null || isNaN(n)) return '-';
    var a = Math.abs(Number(n));
    if (a >= 1e6) return (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return (a / 1e3).toFixed(1) + 'K';
    return String(Math.round(a));
  }
  function txt(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
  var esc = window.EdShell.esc, orDash = window.EdShell.orDash;

  // Delta/DEX and Open Interest fall back to displaying the SAME gamma `.sub-pane` (they have
  // no dedicated pane of their own -- showSubPane()'s fallback rule), which is where Key
  // Levels/GEX-by-Strike/PCR/the Options Flow tape all physically live. A 'gamma'-only check
  // would freeze all four panels on Delta/DEX or OI (a ticker switch there would leave the
  // PREVIOUS ticker's spot/flip/wall values) -- every check in this file recognizes all
  // three, exactly like ed-gamma.js's _isGammaFamilySubview.
  function isGamma() {
    var s = window.EdShell.getState();
    return s.workspace === 'options' && (s.subview === 'gamma' || s.subview === 'dex' || s.subview === 'oi');
  }
  function ticker() { return window.EdShell.getState().ticker; }

  var REGIME = {
    LONG_GAMMA_CHOP: { t: 'Long γ · chop', c: 'var(--ed-pos-ink)', tone: 'up' },
    SHORT_GAMMA_TREND: { t: 'Short γ · trend', c: 'var(--ed-warn)', tone: 'dn' },
    UNAVAILABLE: { t: 'unavailable', c: 'var(--ed-ink-3)', tone: '' },
  };
  window.EdGammaRegime = REGIME;

  // ---------- Key Levels rail: the `terrain:levels` panel (server.terrain), sent on the page's
  // socket while a Gamma tab is on, at once and each time the levels change ----------
  var _levels, _levelsTicker = null;   // the panel as last sent for the ticker on screen
  function loadLevels() {
    if (!isGamma()) { window.EdShell.showPanel('terrain:levels', null); return; }
    if (_levelsTicker !== ticker()) { _levelsTicker = ticker(); _levels = undefined; }
    renderLevels(_levels);
    window.EdShell.showPanel('terrain:levels', {});
  }
  document.addEventListener('ed:panel', function (e) {
    if (e.detail.type !== 'terrain:levels') return;
    _levels = e.detail;
    if (isGamma()) renderLevels(_levels);
  });
  function renderLevels(d) {   // d: the panel as sent; undefined: none yet for this ticker
    var ids = ['klFlip', 'klCall', 'klPut', 'klAbs', 'klNetCall', 'klNetPut', 'klNet', 'klRegime',   // terrain's (Spot is the price row's)
      'kl0Flip', 'kl0Call', 'kl0Put', 'kl0Abs', 'kl0NetCall', 'kl0NetPut'];
    // nothing to draw: none sent yet ('-'), the program could not produce it, or no levels yet
    var why = d === undefined ? '-' : d.failed != null ? d.failed : d.error ? 'terrain not ready' : null;
    paintPcr(why == null ? d : null);
    if (why != null) {   // nothing current: no tooltip or colour of the last answer stays
      ids.forEach(function (id) { txt(id, '-'); var el = document.getElementById(id); if (el) el.style.color = ''; });
      txt('klSrc', why);
      var src0 = document.getElementById('klSrc'); if (src0) { src0.title = ''; src0.style.color = ''; }
      var klb0 = document.getElementById('klBody'); if (klb0) klb0.classList.add('recede');
      return;
    }
    txt('klFlip', px(d.gamma_flip));
    txt('klCall', px(d.call_wall));
    txt('klPut', px(d.put_wall));
    txt('klAbs', px(d.absolute_gamma_strike));
    txt('klNetCall', px(d.lvp));
    txt('klNetPut', px(d.hvp));
    var z = d.same_day != null ? d.same_day : null;
    txt('kl0Flip', px(z ? z.gamma_flip : null));
    txt('kl0Call', px(z ? z.call_wall : null));
    txt('kl0Put', px(z ? z.put_wall : null));
    txt('kl0Abs', px(z ? z.absolute_gamma_strike : null));
    txt('kl0NetCall', px(z ? z.lvp : null));
    txt('kl0NetPut', px(z ? z.hvp : null));
    // Net GEX / 1% move — signed $, coloured by sign (formatting only)
    var net = document.getElementById('klNet');
    if (net) {
      var v = d.net_gex_at_spot;
      net.textContent = (v == null) ? '-' : usd(v);
      net.style.color = (v == null) ? '' : (v >= 0 ? 'var(--ed-pos-ink)' : 'var(--ed-neg-ink)');
    }
    var reg = document.getElementById('klRegime');
    if (reg) {
      var rm = REGIME[d.regime] || { t: orDash(d.regime), c: 'var(--ed-ink-2)' };
      reg.textContent = rm.t; reg.style.color = rm.c;
    }
    // the levels rail recedes while the served levels are STALE
    var klb = document.getElementById('klBody');
    if (klb) klb.classList.toggle('recede', d.levels_state === 'STALE');
    // freshness / provenance line. The chain's time stands beside the mark. The mark is
    // unchanged when no chain time was sent.
    var src = document.getElementById('klSrc');
    function chainMarked(words) {
      var when = d.levels_time_ct != null ? d.levels_time_ct : null;
      if (when != null) return when + ' · ' + words;
      return words;
    }
    if (src) {
      // the served mark (levels_mark: the levels' state, or the price's while the levels are LIVE)
      // with the levels' age; the reason is disclosed in the tooltip, not as a paragraph
      src.textContent = chainMarked(d.levels_mark + (d.levels_age_text ? ' · ' + d.levels_age_text : ''));
      src.title = d.levels_mark_reason == null ? '' : d.levels_mark_reason;
      src.style.color = d.levels_mark === 'LIVE' ? '' : 'var(--ed-stale)';
      // #5: terrain levels are AGGREGATE across expiries; if the workspace filters to one expiry,
      // disclose that these levels are still all-exp (never silently relabel them as selected-expiry).
      if (window.EdShell.getExpiry()) src.textContent += ' · all-exp';
    }
  }

  // ---------- Put/Call OI and volume <- the terrain panel's pcr_by_expiry, pcr_volume_by_expiry (selected expiry, else the front one) ----------
  function expiryFilter() { return window.EdShell.getExpiry(); }
  function paintPcr(d) {
    // the selected expiry, else the whole book -- both served on every terrain answer (TerrainSnapshot
    // fields); the page picks no expiry itself. A failed read (no d) is missing: "-"
    var ex = expiryFilter();
    var v = !d ? null : ex ? d.pcr_by_expiry[ex] : d.pcr_all;
    var vv = !d ? null : ex ? d.pcr_volume_by_expiry[ex] : d.pcr_volume_all;
    var scope = ex ? 'exp ' + ex : 'all exp';
    txt('klPcr', v == null ? '-' : Number(v).toFixed(2));
    txt('klPcrScope', 'OI · ' + scope);
    txt('klPcrVol', vv == null ? '-' : Number(vv).toFixed(2));
    txt('klPcrVolScope', 'volume · ' + scope);
  }

  // ---------- GEX by Strike: the `strikes:gbs` panel (server.strikes) the program sends on the
  // page's socket while a Gamma tab is on, in the window it asks (the scope and its pan), at once
  // and each time the levels change; nothing received yet for the ticker on screen is '-' ----------
  var _gbs;   // the panel as last sent for the ticker on screen
  function loadGbs() {
    if (!isGamma()) { window.EdShell.showPanel('strikes:gbs', null); return; }
    if (_gbsPanTicker !== ticker()) {   // a new ticker: its own window, and nothing of the last one's
      _gbsPan.centre = null; _gbsPan.shift = 0; _gbsPanTicker = ticker(); _gbs = undefined;
      var host = document.getElementById('gbsBody');
      setGbsAsOf(null); if (host) window.EdShell.placeholder(host, '-');
    }
    window.EdShell.showPanel('strikes:gbs', window.EdShell.windowParams(_gbsPan));
  }
  function drawGbs() {
    var host = document.getElementById('gbsBody');
    if (host && isGamma() && _gbs !== undefined) renderGbs(host, _gbs);
  }
  document.addEventListener('ed:panel', function (e) {
    if (e.detail.type !== 'strikes:gbs') return;
    _gbs = e.detail; drawGbs();
  });
  function setGbsAsOf(d) {
    var el = document.getElementById('gbsSrc'); if (!el) return;
    if (!d) { el.innerHTML = ''; return; }
    // the levels verdict the server serves (levels_state, its time and age); the badge formats it
    el.innerHTML = window.EdShell.asOfBadge({ label: 'terrain', state: d.levels_state,
      when: d.levels_time_ct, age: d.levels_age_text, reason: d.levels_stale_reason });
  }
  // A per-strike bar list (GEX, vanna, charm by strike): the window of `rows` the server sent
  // ([strike, value, ...], ascending), drawn highest strike first, each bar's length its |value|
  // against the served scale (view.max_abs). The strike labels pan the window (wireStrikeAxis ->
  // `reload`); a pan is never silent. `opts`: `top` html above the list, `attrs(r)` and `cells(r)`
  // a row's extra attributes and cells, `value(v)` the value's text (dollars when not given).
  function drawStrikeBars(host, rows, view, pan, spotStrike, reload, opts) {
    window.EdShell.panServed(pan, view.centre);
    var maxAbs = view.max_abs;   // at least |v| for every v drawn
    var note = opts.top + (pan.centre != null ? '<div class="gbs-allexp">Panned to ' +
      px(pan.served, pan.served % 1 ? 2 : 0) + ' · double-click a strike to follow the price</div>' : '') +
      (view.note ? '<div class="gbs-allexp">' + esc(view.note) + '</div>' : '');   // why not around the price
    var bars = '';
    rows.slice().reverse().forEach(function (r) {
      // a strike with no value is unknown: no bar, '-' (never a $0 bar)
      var k = r[0], v = r[1] == null ? null : Number(r[1]);
      var s = window.EdShell.strength(v, maxAbs), w = s == null ? 0 : s * 100, pos = v != null && v >= 0;
      bars += '<div class="gbs-row' + (k === spotStrike ? ' spot' : '') + '" data-strike="' + k + '"' +
        (opts.attrs ? opts.attrs(r) : '') + '>' +
        '<span class="gbs-k">' + px(k, k % 1 ? 2 : 0) + '</span>' +
        '<span class="gbs-track"><i class="gbs-bar ' + (pos ? 'pos' : 'neg') + '" style="width:' + w.toFixed(1) + '%"></i></span>' +
        '<span class="gbs-v ' + (v == null ? '' : pos ? 'pos' : 'neg') + '">' + (v == null ? '-' : (opts.value || usd)(v)) + '</span>' +
        (opts.cells ? opts.cells(r) : '') + '</div>';
    });
    // the bars scroll in their own area; the -/0/+ axis is pinned at the foot
    host.innerHTML = '<div class="gbs-top">' + note + '</div>' +
      '<div class="gbs-scroll"><div class="gbs">' + bars + '</div></div>' +
      '<div class="gbs-scale"><span class="neg">−</span><span>0</span><span class="pos">+</span></div>';
    host.querySelectorAll('.gbs-row').forEach(function (rr) {   // click a strike: every panel follows it
      rr.addEventListener('click', function () { window.EdShell.setStrike(Number(rr.getAttribute('data-strike')), null); });   // every expiry's row: no expiry
    });
    var firstRow = host.querySelector('.gbs-row');
    window.EdShell.wireStrikeAxis(host.querySelectorAll('.gbs-k'), host.querySelector('.gbs-scroll'), pan,
      firstRow ? firstRow.getBoundingClientRect().height : 0, reload);
    var sr = host.querySelector('.gbs-row.spot');
    if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
  }

  // GEX by Strike shows the window the server sends (scope, and the operator's pan)
  var _gbsPan = window.EdShell.newPan(), _gbsPanTicker = null;

  function renderGbs(host, d) {
    if (d.failed != null || d.available === false) {   // not produced, or a window it cannot draw: why
      setGbsAsOf(null); window.EdShell.placeholder(host, d.failed != null ? d.failed : d.reason);
      return;
    }
    setGbsAsOf(d);
    var rows = d.today && d.today.all;
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        'no banked per-strike gamma for this symbol</div></div>';
      return;
    }
    // the strikes panel is aggregate across expiries; with one expiry selected, say so
    var expOn = window.EdShell.getExpiry();
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
          (chg[r[0]] == null ? '-' : usd(chg[r[0]])) + '</span>';
      },
    });
    applyGbsHighlight(host);
  }
  function applyGbsHighlight(host) {
    host = host || document.getElementById('gbsBody'); if (!host) return;
    var sel = (window.EdShell.getState()).selStrike;
    host.querySelectorAll('.gbs-row.gbs-sel').forEach(function (n) { n.classList.remove('gbs-sel'); });
    if (sel == null) return;
    host.querySelectorAll('.gbs-row[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('gbs-sel'); });
  }

  // ---------- Strike Detail ----------
  // the workspace expiry filter, else the selected strike's own expiry
  function strikeDetailExpiry() {
    var s = window.EdShell.getState();
    return expiryFilter() || s.selExpiry;
  }
  // The selected strike's contracts: the `chain:detail` panel (server.chain) the program sends on
  // the page's socket while a strike is selected, at its expiry (null: the chain's front one), at
  // once and each time a chain is priced. loadStrike() records the desired (strike, expiry); a
  // new strike at the same expiry is drawn from the chain already sent. A frame of an expiry no
  // longer desired (sent before the page asked another) is not drawn.
  var _sdDesired = { strike: null, expiry: null }, _sd;   // _sd: the panel as last sent
  function sdCurrent(d) { return !_sdDesired.expiry || d.failed != null || d.expiry === _sdDesired.expiry; }
  function drawStrike() {
    var host = document.getElementById('sdBody');
    if (!host || _sdDesired.strike == null || _sd === undefined || !sdCurrent(_sd)) return;
    if (_sd.failed != null) { setSdAsOf(null); window.EdShell.placeholder(host, _sd.failed); return; }
    renderStrike(host, _sd, _sdDesired.strike, _sdDesired.expiry);
  }
  function loadStrike(strike, expiry) {
    var was = _sdDesired.expiry;
    _sdDesired = { strike: strike, expiry: expiry };
    if (strike == null) { window.EdShell.showPanel('chain:detail', null); return; }
    if (was === expiry) drawStrike();   // the chain at this expiry is on hand
    window.EdShell.showPanel('chain:detail', { expiry: expiry });
  }
  document.addEventListener('ed:panel', function (e) {
    if (e.detail.type !== 'chain:detail') return;
    _sd = e.detail; drawStrike();
  });
  function setSdAsOf(d) {
    var el = document.getElementById('sdSrc'); if (!el) return;
    el.innerHTML = window.EdShell.chainScopeBadge(d);
  }
  function renderStrike(host, d, strike, expiry) {
    setSdAsOf(d);
    var cs = d.contracts;
    if (!cs.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' + esc(window.EdShell.chainEmptyText(d)) + '</div></div>';
      return;
    }
    function pick(side) {
      return cs.filter(function (c) {
        return c.putCall === side &&
          Math.abs(Number(c.strikePrice) - Number(strike)) < 0.01; })[0];
    }
    var call = pick('CALL'), put = pick('PUT');
    txt('sdCtx', px(strike, strike % 1 ? 2 : 0) + (expiry ? ' · ' + esc(expiry.slice(5)) : ''));
    // d2: decimals; none: every digit Schwab sent (its Greeks)
    function cell(c, k, d2) { var v = c ? c[k] : null; return (v == null) ? '-' : (typeof v === 'number' ? (d2 == null ? String(v) : v.toFixed(d2)) : esc(v)); }
    // GEX ($) column: per-side GEX$ is not served (computing it would be frontend math) -> "-"; the
    // NET row is this expiry's net GEX at this strike, served on the same chain panel --
    // the heatmap's own cell, not GEX-by-Strike's all-expiry total beside one expiry's contracts.
    var net = null;   // served null: this expiry has no surface column, so no strike has one
    if (d.net_gex_by_strike !== null) d.net_gex_by_strike.forEach(function (r) {
      if (Math.abs(Number(r[0]) - Number(strike)) < 0.01) net = Number(r[1]);
    });
    var netCls = net == null ? '' : (net >= 0 ? 'pos' : 'neg');
    host.innerHTML =
      '<table class="sd"><thead><tr><th>Type</th><th>OI</th><th>Vol</th><th>Gamma</th><th>GEX $</th><th>Delta</th><th>IV%</th></tr></thead><tbody>' +
      '<tr><td class="side c">Call</td><td>' + cell(call, 'openInterest', 0) + '</td><td>' + cell(call, 'totalVolume', 0) +
      '</td><td>' + cell(call, 'gamma') + '</td><td class="dim">-</td><td>' + cell(call, 'delta') + '</td><td>' + cell(call, 'volatility') + '</td></tr>' +
      '<tr><td class="side p">Put</td><td>' + cell(put, 'openInterest', 0) + '</td><td>' + cell(put, 'totalVolume', 0) +
      '</td><td>' + cell(put, 'gamma') + '</td><td class="dim">-</td><td>' + cell(put, 'delta') + '</td><td>' + cell(put, 'volatility') + '</td></tr>' +
      '<tr class="sd-net"><td class="side">Net</td><td>-</td><td>-</td><td>-</td><td class="' + netCls + '">' +
      (net == null ? '-' : usd(net)) + '</td><td>-</td><td>-</td></tr>' +
      '</tbody></table><div class="sd-src">vendor per-contract · net GEX$ this expiry · the chain</div>';
  }

  // A ticker switch drops Strike Detail's chain and its rendered content: ed-core.js's
  // setTicker() clears the SHARED selStrike (a fresh strike click is required before loadStrike
  // fires again), and the panel leaves the subscribe, so nothing of the old ticker is drawn
  // under the new one (AMD's values shown after a switch to NVDA); the Strike Detail
  // placeholder is cleared the instant the ticker changes.
  function resetStrikeDetailForTickerChange() {
    loadStrike(null, null);
    _sd = undefined;
    var host = document.getElementById('sdBody');
    if (host) {
      host.innerHTML = '<div class="placeholder"><div class="sm">Select a strike/expiry. '
        + 'OI · volume · gamma · delta · IV from the chain (vendor).</div></div>';
    }
  }

  // ---------- Vanna / Charm by strike: the same bar list (drawStrikeBars), each its own pan ----------
  // The program sends the panel on the page's socket (server.strike_bars)
  // while its tab is on, for the window it asks (the scope and its pan), at once and on each
  // change of the levels; nothing received yet for the ticker on screen is '-'.
  function _mkStrikeBar(kind, hostId, srcId) {
    function inSub() {
      var s = window.EdShell.getState();
      return s.workspace === 'options' && s.subview === kind;
    }
    var pan = window.EdShell.newPan(), panTicker = null;
    function renderIt(host, d) {
      var src = document.getElementById(srcId); if (src) src.textContent = '';
      if (d.failed != null || !d.available) {   // not produced, or nothing to draw: why
        window.EdShell.placeholder(host, d.failed != null ? d.failed : d.reason);
        return;
      }
      // vanna and charm are delta-shares (per vol point, per day), not dollars: no '$'
      drawStrikeBars(host, d.rows, d.view, pan, d.spot_strike, ask, { top: '', value: window.EdGamma.formatCount });
    }
    function ask() {
      if (!inSub()) { window.EdShell.showPanel(kind, null); return; }
      if (panTicker !== ticker()) {   // a new ticker: its own window, and nothing of the last one's
        pan.centre = null; pan.shift = 0; panTicker = ticker();
        var host = document.getElementById(hostId); if (host) window.EdShell.placeholder(host, '-');
      }
      window.EdShell.showPanel(kind, window.EdShell.windowParams(pan));
    }
    document.addEventListener('ed:panel', function (e) {
      var host = document.getElementById(hostId);
      if (e.detail.type === kind && host && inSub()) renderIt(host, e.detail);
    });
    return ask;
  }
  var loadVanna = _mkStrikeBar('vanna', 'vnBody', 'vnSrc');
  var loadCharm = _mkStrikeBar('charm', 'chmBody', 'chmSrc');

  // ---------- Structures — contract-safety metadata ------
  // the chain's fields (multiplier/nonStandard/deliverables/settlementType/
  // exerciseType/expirationType/lastTradingDay/pennyPilot) that the Chain ladder never
  // surfaces -- one strike per row, both sides, no new computation, no second shape
  // (the same chain panel Chain and Strike Detail are sent).
  function inStructures() {
    var s = window.EdShell.getState();
    return s.workspace === 'options' && s.subview === 'structures';
  }
  function _flag(label, on) { return '<span class="st-flag' + (on ? ' on' : '') + '">' + esc(label) + '</span>'; }
  // ADJUSTED DELIVERABLE: served per contract (Schwab's nonStandard flag, as sent)
  function renderStructures(host, d) {
    var src = document.getElementById('stSrc'); if (src) src.textContent = '';
    // served: one row per strike, high to low; an 'unavailable' chain answer carries none
    if (d.status !== 'ok') {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        esc(window.EdShell.chainEmptyText(d)) + '</div></div>';
      return;
    }
    var ladder = d.ladder.filter(function (r) { return r.first; });
    var rows = ladder.map(function (r) {
      var k = r.strike, rep = r.call || r.put;   // settlement/exercise/expiration/multiplier are contract-level, same both sides at one strike/expiry
      var lastDay = d.last_trading_day_et[rep.symbol];   // served: its date in ET
      var flags = [
        _flag('NON-STD', rep.nonStandard === true),
        _flag('PENNY', rep.pennyPilot === true),
        _flag('ADJUSTED DELIVERABLE', d.adjusted_deliverable_symbols.indexOf(rep.symbol) !== -1),
      ].join('');
      return '<tr><td class="side">' + px(k, k % 1 ? 2 : 0) + '</td>' +
        '<td>' + (rep.multiplier == null ? '-' : rep.multiplier) + '</td>' +
        '<td>' + esc(orDash(rep.settlementType)) + '</td>' +
        '<td>' + esc(orDash(rep.exerciseType)) + '</td>' +
        '<td>' + esc(orDash(rep.expirationType)) + '</td>' +
        '<td>' + (lastDay == null ? '-' : esc(lastDay)) + '</td>' +
        '<td>' + flags + '</td></tr>';
    }).join('');
    host.innerHTML = '<div class="gbs-scroll"><table class="sd st-tbl">' +
      '<thead><tr><th>Strike</th><th>Multiplier</th><th>Settlement</th><th>Exercise</th><th>Exp. Type</th><th>Last Trading Day</th><th>Flags</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>' +
      '<div class="sd-src">vendor per-contract · the chain — no field here is inferred or defaulted</div>';
  }
  // the `chain:structures` panel (server.chain) the program sends on the page's socket while the
  // Structures tab is on, at the selected expiry (null: the chain's front one); nothing received
  // yet for the ticker on screen is '-', and a frame of an expiry no longer selected is not drawn
  var _stTicker = null;
  document.addEventListener('ed:panel', function (e) {
    var d = e.detail, host = document.getElementById('stBody'), exp = window.EdShell.getExpiry();
    if (d.type !== 'chain:structures' || !host || !inStructures() || (exp && d.failed == null && d.expiry !== exp)) return;
    if (d.failed != null) { window.EdShell.placeholder(host, d.failed); return; }
    renderStructures(host, d);
  });
  function loadStructures() {
    if (!inStructures()) { window.EdShell.showPanel('chain:structures', null); return; }
    if (_stTicker !== ticker()) {
      _stTicker = ticker();
      var host = document.getElementById('stBody'); if (host) window.EdShell.placeholder(host, '-');
    }
    window.EdShell.showPanel('chain:structures', { expiry: window.EdShell.getExpiry() });
  }

  // ---------- Options Flow tape ------------
  // The embedded tape widget on the Gamma pane (#ofBody) -- real native trade prints for
  // every contract of the ticker the daemon streams (its option rule), never a fabricated
  // buy/sell side.
  var OF_CLS_LABEL = { at_bid: 'at bid', at_ask: 'at ask', inside_spread: 'inside',
    outside_spread_low: 'below bid', outside_spread_high: 'above ask', unknown: '-' };
  function fmtOfPrice(n) { return (n == null || isNaN(n)) ? '-' : Number(n).toFixed(2); }
  function fmtOfSize(n) { return (n == null || isNaN(n)) ? '-' : String(n); }
  // Schwab's own trade time (TRADE_TIME_MILLIS, as sent), in Central Time; '-' when it sent none
  function fmtOfTime(tradeTimeMs) {
    if (tradeTimeMs == null) return '-';
    return new Date(tradeTimeMs).toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/Chicago' });
  }
  function renderOf(host, d) {
    var src = document.getElementById('ofSrc'); if (src) src.textContent = '';
    if (!d.available) {   // served: available exactly when rows were found
      host.innerHTML = '<table class="of"><thead><tr><th>Time</th><th>Symbol</th><th>Exp</th><th>Type</th><th>Strike</th>' +
        '<th>Bid×Size</th><th>Ask×Size</th><th>Trade</th><th>Size</th><th>Premium</th>' +
        '<th>Vol</th><th>OI</th><th>IV%</th><th>Δ</th><th>vs Market</th></tr></thead>' +
        '<tbody><tr class="of-empty"><td colspan="14"><div class="oe-sub">' +
        esc(d.reason || 'the console sent no reason') + '</div></td></tr></tbody></table>';
      return;
    }
    var body = d.rows.map(function (r) {
      return '<tr>' +
        '<td>' + fmtOfTime(r.trade_time_ms) + '</td>' +
        '<td class="of-sym">' + esc(orDash(r.symbol)) + '</td>' +
        '<td>' + esc(r.expiry ? r.expiry.slice(5) : '-') + '</td>' +
        '<td>' + esc(orDash(r.type)) + '</td>' +
        '<td>' + (r.strike == null ? '-' : px(r.strike, r.strike % 1 ? 2 : 0)) + '</td>' +
        '<td>' + fmtOfPrice(r.bid) + '×' + fmtOfSize(r.bid_size) + '</td>' +
        '<td>' + fmtOfPrice(r.ask) + '×' + fmtOfSize(r.ask_size) + '</td>' +
        '<td>' + fmtOfPrice(r.trade) + '</td>' +
        '<td>' + fmtOfSize(r.size) + '</td>' +
        '<td>' + (r.premium == null ? '-' : usd(r.premium)) + '</td>' +
        '<td>' + fmtVol(r.volume) + '</td>' +
        '<td>' + fmtOfSize(r.oi) + '</td>' +
        '<td>' + (r.iv == null ? '-' : Number(r.iv).toFixed(1)) + '</td>' +
        '<td>' + (r.delta == null ? '-' : Number(r.delta).toFixed(3)) + '</td>' +
        '<td><span class="of-cls ' + esc(r.classification || 'unknown') + '">' +
          esc(orDash(OF_CLS_LABEL[r.classification])) + '</span></td></tr>';
    }).join('');
    host.innerHTML = '<table class="of"><thead><tr><th>Time</th><th>Symbol</th><th>Exp</th><th>Type</th><th>Strike</th>' +
      '<th>Bid×Size</th><th>Ask×Size</th><th>Trade</th><th>Size</th><th>Premium</th>' +
      '<th>Vol</th><th>OI</th><th>IV%</th><th>Δ</th><th>vs Market</th></tr></thead><tbody>' + body + '</tbody></table>';
  }
  // the `tape` panel (server.tape) on the page's socket, at once and with each streamed quote
  function loadOf() { window.EdShell.showPanel('tape', isGamma() ? {} : null); }
  document.addEventListener('ed:panel', function (e) {
    var d = e.detail, host = document.getElementById('ofBody');
    if (d.type !== 'tape' || !host || !isGamma()) return;
    renderOf(host, d.failed != null ? { available: false, reason: d.failed } : d);
  });

  // ---------- events ----------
  function loadAll() { loadLevels(); loadGbs(); loadVanna(); loadCharm(); loadStructures(); loadOf(); }
  document.addEventListener('ed:ticker', function () { resetStrikeDetailForTickerChange(); loadAll(); });
  document.addEventListener('ed:expiry', loadLevels);   // the ratio is scoped to the selected expiry
  document.addEventListener('ed:view', loadAll);
  // a new scope is a new window: every per-strike panel re-reads it from the server
  document.addEventListener('ed:scope', function () { loadGbs(); loadVanna(); loadCharm(); });
  document.addEventListener('ed:strike', function (e) {
    var det = e.detail || {};
    applyGbsHighlight();                       // A: sync the GEX-by-strike highlight
    loadStrike(det.strike == null ? null : det.strike, det.strike == null ? null : det.expiry);
  });
  document.addEventListener('ed:expiry', function () {   // #5: expiry filter -> Strike Detail uses it; Levels/GBS stay aggregate + disclose
    loadLevels(); drawGbs(); loadStructures();   // Structures is expiry-scoped, same as Chain/Strike Detail
    var sel = (window.EdShell.getState()).selStrike;
    if (sel != null) loadStrike(sel, strikeDetailExpiry());
  });
  // Initial hydration comes SOLELY from ed-core.js's deferred ed:ticker/ed:view dispatch --
  // see that file's init() comment.
})();
