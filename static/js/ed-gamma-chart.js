/* Ed Console — Options/Gamma Chart view. PRESENTATION ONLY.
   On the one TradingView-style chart every chart in the console uses (ed-tv-chart.js): the price
   (/api/bars1m, completed Schwab bars at the toolbar's timeframe), the flip and the walls (/api/terrain) as level
   lines, the live price (the header's price row), and the selected measure's per-strike rows
   (/api/terrain/strikes: GEX `today.all`, DEX and OI `measures`) as a profile on the price axis --
   bars, or dots sized by magnitude (Dot Map). The same view serves the Gamma, Delta / DEX and Open
   Interest subviews. The strikes shown are the one Gamma scope (EdShell.scopeSelect). A click on a
   strike selects it for every panel. The page computes no exposure or level. */
(function () {
  'use strict';

  var usd = (window.EdGamma && window.EdGamma.formatUsd) || function (n) {
    if (n == null || isNaN(n)) return ''; var a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'K'; return s + '$' + a.toFixed(0);
  };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function ctTime(sec) { try { return new Date(sec * 1000).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', timeZone: 'America/Chicago' }); } catch (e) { return ''; } }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function isChart() {
    var s = st();
    return s.workspace === 'options' && ['gamma', 'dex', 'oi'].indexOf(s.subview) !== -1 && s.view === 'chart';
  }
  // the served profile for the selected measure: {rows [[strike, value, ...]], spot_strike, max_abs_strike, name}
  function served(sd) {
    var m = st().measure, x = sd && sd.measures && sd.measures[m];
    if (x) return { rows: x.rows || [], spot_strike: x.spot_strike, max_abs_strike: x.max_abs_strike, name: m === 'oi' ? 'OI' : 'DEX', signed: m !== 'oi' };
    return { rows: (sd && sd.today && sd.today.all) || [], spot_strike: sd && sd.spot_strike, max_abs_strike: sd && sd.max_abs_strike, name: 'GEX', signed: true };
  }
  function ticker() { return st().ticker || ''; }

  var _mode = 'profile';          // 'profile' (bars) | 'dotmap' (dots)
  var _chart = null;
  var _liveQuote = null;          // the header's price row (ed:quote_tick), the one displayed price
  var _last = { bars: undefined, strikes: undefined, terrain: undefined };
  // the chart's timeframe (the toolbar's), kept per viewer
  var _tf = (function () { try { return window.localStorage.getItem('ed.gchart.tf') || '1'; } catch (e) { return '1'; } })();
  function tfLabel() { return (window.EdTvChart.TFS.filter(function (t) { return t.id === _tf; })[0] || {}).lbl || _tf; }

  function liveSpot() {   // the row whose served key is the selected instrument's (EdShell state.key)
    var q = _liveQuote;
    return (q && q.ticker === st().key && q.spot_state === 'live' && q.spot != null) ? Number(q.spot) : null;
  }
  function ensureChart() {
    var host = document.getElementById('chartBody');
    if (!host || !window.EdTvChart || !window.LightweightCharts) return null;
    if (_chart && host.querySelector('.gchart-plot')) return _chart;
    host.innerHTML = '<div class="gchart-head"></div><div class="gchart-tb"></div><div class="gchart-plot"></div><div class="gchart-empty" hidden></div>';
    _chart = window.EdTvChart.create(host.querySelector('.gchart-plot'), { nearestN: 99,
      onProfileClick: function (row) {
        if (!window.EdShell) return;
        var exp = window.EdShell.getExpiry ? window.EdShell.getExpiry() : null;   // the workspace's expiry filter carries through
        window.EdShell.setStrike(row.price, exp || null);
      } });
    window.EdTvChart.toolbar(host.querySelector('.gchart-tb'), _chart, { tf: _tf, styleKey: 'ed.gchart.style',
      onTf: function (tf) { _tf = tf; try { window.localStorage.setItem('ed.gchart.tf', tf); } catch (e) { /* per-viewer only */ } load(); } });
    return _chart;
  }

  function okJson(r) { if (!r.ok) throw new Error(r.status); return r.json(); }
  function nullp() { return null; }
  function loadImpl(tk, signal) {
    if (!isChart() || ticker() !== tk || !ensureChart()) return;
    return Promise.all([
      fetch('/api/bars1m?ticker=' + encodeURIComponent(tk) + '&tf=' + _tf + '&limit=' + window.EdTvChart.BARS_LIMIT[_tf],
        { cache: 'no-store', signal: signal }).then(okJson).catch(nullp),
      fetch('/api/terrain/strikes?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal }).then(okJson).catch(nullp),
      fetch('/api/terrain?ticker=' + encodeURIComponent(tk), { cache: 'no-store', signal: signal }).then(okJson).catch(nullp)
    ]).then(function (r) {
      if (!isChart() || ticker() !== tk) return;
      _last = { bars: r[0], strikes: r[1], terrain: r[2] };
      render();
    });
  }
  var _loader = (window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(ticker(), signal); })
    : { trigger: function () { loadImpl(ticker()); } };
  function load() { _loader.trigger(ticker()); }

  // the profile and the levels only (a levels push): the bars are unchanged
  function loadLevelsImpl(tk) {
    if (!isChart() || ticker() !== tk || !_chart) return;
    var get = (window.EdL1SseGuards && window.EdL1SseGuards.sharedFetchJson) || function (u) { return fetch(u, { cache: 'no-store' }).then(okJson); };
    return Promise.all([get('/api/terrain/strikes?ticker=' + encodeURIComponent(tk)).catch(nullp),
      get('/api/terrain?ticker=' + encodeURIComponent(tk)).catch(nullp)]).then(function (r) {
      if (!isChart() || ticker() !== tk || r[0] == null || r[1] == null) return;
      _last.strikes = r[0]; _last.terrain = r[1];
      render();
    });
  }
  var _levelsLoader = (window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadLevelsImpl(ticker(), signal); })
    : { trigger: function () { loadLevelsImpl(ticker()); } };

  function render() {
    var c = ensureChart(); if (!c) return;
    var host = document.getElementById('chartBody');
    var P = c.palette(), barsD = _last.bars, sd = _last.strikes, t = _last.terrain;
    var bars = (barsD && barsD.bars) || [];
    var prof = served(sd), srows = prof.rows;   // served in strike order
    // the strikes shown: the one Gamma scope (Auto / Wider / All available), shared with the heatmap
    var sel = window.EdShell && window.EdShell.scopeSelect
      ? window.EdShell.scopeSelect(srows.map(function (r) { return r[0]; }), prof.spot_strike)
      : { idx: srows.map(function (_r, i) { return i; }) };
    var win = sel.idx.map(function (i) { return srows[i]; }).filter(function (r) { return r[1] != null; });   // unknown: nothing drawn
    c.setBars(bars, (barsD && barsD.tf) || _tf, st().display || ticker(), barsD && barsD.last_bar && barsD.last_bar.label);
    c.setProfile(win.map(function (r) {
      return { price: Number(r[0]), value: Number(r[1]), color: !prof.signed ? P.accent : r[1] >= 0 ? P.up : P.down }; }),
      _mode === 'dotmap' ? 'dots' : 'bars');
    c.selectProfile(st().selStrike == null ? null : Number(st().selStrike));
    var lv = [];
    if (t && !t.error) {
      if (t.gamma_flip != null) lv.push({ id: 'gamma_flip', price: Number(t.gamma_flip), label: 'flip', color: P.accent, style: 2, width: 1 });
      if (t.call_wall != null) lv.push({ id: 'call_wall', price: Number(t.call_wall), label: 'call wall', color: P.down, style: 0, width: 1 });
      if (t.put_wall != null) lv.push({ id: 'put_wall', price: Number(t.put_wall), label: 'put wall', color: P.up, style: 0, width: 1 });
    }
    c.setLevels(lv);
    var spot = liveSpot();
    c.setLivePrice(spot, _liveQuote && spot != null ? _liveQuote.trade_age_sec : null);
    var empty = host.querySelector('.gchart-empty');
    empty.hidden = !!(bars.length || win.length);
    empty.textContent = empty.hidden ? '' : (barsD || sd ? 'no bars / per-strike ' + prof.name + ' for this symbol'
      : 'the bars and per-strike ' + prof.name + ' requests failed');
    paintHead(host.querySelector('.gchart-head'), bars, win, prof, sd, spot);
  }
  function paintHead(el, bars, win, prof, sd, spot) {
    var srows = prof.rows, n = prof.name;
    var note = window.EdShell && window.EdShell.scopeNote ? window.EdShell.scopeNote({ total: srows.length, shown: win.length }) : '';
    var ab = (window.EdShell && window.EdShell.asOfBadge) || function () { return ''; };
    var lastT = bars.length ? bars[bars.length - 1].t : null;
    var src = sd && sd.today_source;
    var asof = (lastT ? '<span class="asof">price ' + tfLabel() + ' · ' + ctTime(lastT) + ' CT</span>' : '') +
      (src ? ab({ label: n + ' ' + (src === 'terrain_live_cache' ? 'terrain live' : src), ageSec: sd.today_age_sec,
        stale: !!sd.levels_stale, reason: sd.levels_stale_reason, live: src === 'terrain_live_cache' && sd.levels_stale === false }) : '');
    var top = srows.filter(function (r) { return r[0] === prof.max_abs_strike; })[0];   // served: the largest-magnitude strike
    var shown = top ? (prof.signed ? usd(top[1]) : Number(top[1]).toLocaleString('en-US') + ' contracts') : '';
    el.innerHTML = note + (asof ? '<div class="chart-asof">' + asof + '</div>' : '') +
      '<div class="chart-legend">' + (prof.signed
        ? '<span><span class="sw" style="background:var(--ed-pos)"></span>+' + n + '</span>' +
          '<span><span class="sw" style="background:var(--ed-neg)"></span>−' + n + '</span>'
        : '<span><span class="sw" style="background:var(--ed-accent)"></span>' + n + '</span>') +
      '<span><span class="sw" style="background:var(--ed-accent)"></span>flip</span>' +
      '<span>spot ' + (spot == null ? '—' : spot.toFixed(2)) + '</span>' +
      (top ? '<span>largest |' + n + '| ' + esc(top[0]) + ' · ' + esc(shown) + '</span>' : '') + '</div>';
  }

  function bindModes() {
    var host = document.getElementById('chartModes');
    if (!host) return;
    host.querySelectorAll('.cmode').forEach(function (b) {
      b.addEventListener('click', function () {
        _mode = b.getAttribute('data-cmode');
        host.querySelectorAll('.cmode').forEach(function (x) { x.classList.toggle('on', x === b); });
        if (_chart) render();
      });
    });
  }

  window.addEventListener('ed:quote_tick', function (ev) {
    var q = (ev && ev.detail) || {};
    if (q.ticker !== st().key) return;
    _liveQuote = q;
    if (isChart() && _chart && _last.strikes !== undefined) render();
  });
  document.addEventListener('ed:view', load);
  document.addEventListener('ed:ticker', function () { _last = { bars: undefined, strikes: undefined, terrain: undefined }; load(); });
  document.addEventListener('ed:scope', function () { if (_chart && isChart()) render(); });
  document.addEventListener('ed:measure', function () { if (_chart && isChart() && _last.strikes !== undefined) render(); });
  document.addEventListener('ed:changed', function (e) {   // a new bar reloads all; new levels reload the levels
    if (e.detail.kind === 'liquidity') load(); else if (e.detail.kind === 'levels') _levelsLoader.trigger(ticker());
  });
  document.addEventListener('ed:strike', function () { if (_chart && isChart()) _chart.selectProfile(st().selStrike == null ? null : Number(st().selStrike)); });
  bindModes();
  // read-only view for tests (e2e) -- never a control surface
  window.EdGammaChart = {
    state: function () { return _chart ? _chart.state() : null; },
    profilePoint: function (price) { return _chart ? _chart.profilePoint(price) : null; }
  };
})();
