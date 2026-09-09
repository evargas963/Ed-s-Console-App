/* Ed Console shell core (RC-UI-1) — navigation, watchlist foundation, ticker store,
   header live-data, CT clock, AI drawer. NO trading semantics are computed here: this
   file only fetches canonical endpoints and formats/arranges the results (ONE FAUCET).
   View-specific rendering (heatmap, levels, order flow) is wired in per-view modules. */
(function () {
  'use strict';

  // ---- shared ticker key (compatible with the legacy shell) ----
  var TICKER_KEY = 'ed_ticker';
  var WL_KEY = 'ed_watchlist_v1';
  var RAIL_KEY = 'ed_rail_open';
  var DEFAULT_WL = ['SPY', 'QQQ', 'IWM', 'NVDA', 'TSLA'];

  var app = document.getElementById('app');

  // ---- 3-tier navigation config (workspace -> subnav -> views).
  //      `state:'na'` marks a tab whose canonical capability is absent/partial. ----
  var NAV = {
    'trade-desk': { title: 'TRADE DESK', subs: [
      { id: 'right-now', label: 'Right Now' }, { id: 'plan', label: 'Plan' },
      { id: 'expression', label: 'Expression', state: 'na' } ], views: [] },
    'order-flow': { title: 'ORDER FLOW', subs: [
      { id: 'overview', label: 'Overview' }, { id: 'book', label: 'Book / DOM' },
      { id: 'heatmap', label: 'Heatmap', state: 'na' }, { id: 'tape', label: 'Tape' },
      { id: 'options-book', label: 'Options Book' }, { id: 'history', label: 'History' } ], views: [] },
    'options': { title: 'OPTIONS', subs: [
      { id: 'gamma', label: 'Gamma' }, { id: 'vanna', label: 'Vanna', state: 'na', note: 'AGG ONLY' },
      { id: 'charm', label: 'Charm', state: 'na', note: 'WALLS ONLY' },
      { id: 'dex', label: 'Delta / DEX', state: 'na' }, { id: 'oi', label: 'OI', state: 'na' },
      { id: 'flow', label: 'Flow' }, { id: 'chain', label: 'Chain' },
      { id: 'structures', label: 'Structures', state: 'na', note: 'NOT PROVEN' } ],
      views: { gamma: [
        { id: 'heatmap', label: 'Heatmap' }, { id: 'chart', label: 'Chart' },
        { id: 'levels', label: 'Levels' }, { id: 'multimap', label: 'Multi-Map' } ] } },
    'liquidity': { title: 'LIQUIDITY', subs: [
      { id: 'map', label: 'Map' }, { id: 'profile', label: 'Profile' }, { id: 'levels', label: 'Levels' },
      { id: 'vwap', label: 'VWAP / Value' }, { id: 'session', label: 'Session' }, { id: 'history', label: 'History' } ], views: [] },
    'desk': { title: 'DESK / RESEARCH', subs: [
      { id: 'radar', label: 'Radar' }, { id: 'brief', label: 'Brief' }, { id: 'dossier', label: 'Dossier' },
      { id: 'structures', label: 'Structures' }, { id: 'scenarios', label: 'Scenarios' },
      { id: 'evidence', label: 'Evidence' }, { id: 'replay', label: 'Replay' },
      { id: 'ai-research', label: 'AI Research', state: 'na', note: 'NOT PROVEN' } ], views: [] },
    'portfolio': { title: 'PORTFOLIO / RISK', subs: [
      { id: 'positions', label: 'Positions', state: 'na' }, { id: 'exposure', label: 'Exposure', state: 'na' },
      { id: 'risk', label: 'Risk', state: 'na' }, { id: 'scenarios', label: 'Scenarios', state: 'na' } ], views: [] },
    'system': { title: 'SYSTEM / TRUST', subs: [
      { id: 'data-health', label: 'Data Health' }, { id: 'feeds', label: 'Feeds' },
      { id: 'provenance', label: 'Provenance' }, { id: 'models', label: 'Models' }, { id: 'runtime', label: 'Runtime' } ], views: [] }
  };

  var state = {
    ticker: (localStorage.getItem(TICKER_KEY) || 'SPY').toUpperCase(),
    workspace: app.getAttribute('data-workspace') || 'options',
    subview: app.getAttribute('data-subview') || 'gamma',
    view: app.getAttribute('data-view') || 'heatmap'
  };

  // ================= navigation =================
  function renderSubnav() {
    var cfg = NAV[state.workspace];
    var sub = document.getElementById('subnav');
    var html = '<span class="wtitle">' + cfg.title + '</span>';
    cfg.subs.forEach(function (s) {
      var cls = 'tab' + (s.state === 'na' ? ' na' : '') + (s.id === state.subview ? ' on' : '');
      html += '<button class="' + cls + '" data-sub="' + s.id + '">' + s.label +
        (s.note ? '<span class="np">' + s.note + '</span>' : '') + '</button>';
    });
    sub.innerHTML = html;
    sub.querySelectorAll('button[data-sub]').forEach(function (b) {
      if (b.classList.contains('na')) return;
      b.addEventListener('click', function () { setSubview(b.getAttribute('data-sub')); });
    });
  }

  function renderViewbar() {
    var cfg = NAV[state.workspace];
    var views = (cfg.views && cfg.views[state.subview]) || [];
    var bar = document.getElementById('viewbar');
    var ctrls = bar.querySelector('.ctrls');
    // rebuild only the tab region, preserve the controls block
    var tabHtml = '';
    views.forEach(function (v) {
      tabHtml += '<button class="vtab' + (v.id === state.view ? ' on' : '') + '" data-view="' + v.id + '">' + v.label + '</button>';
    });
    // clear existing tabs
    Array.prototype.slice.call(bar.querySelectorAll('.vtab')).forEach(function (n) { n.remove(); });
    if (ctrls) ctrls.insertAdjacentHTML('beforebegin', tabHtml);
    else bar.insertAdjacentHTML('afterbegin', tabHtml);
    bar.querySelectorAll('.vtab').forEach(function (b) {
      b.addEventListener('click', function () { setView(b.getAttribute('data-view')); });
    });
    bar.style.display = views.length ? '' : 'none';
  }

  function showPane() {
    document.querySelectorAll('.workspace').forEach(function (w) {
      w.classList.toggle('on', w.getAttribute('data-ws-pane') === state.workspace);
    });
  }

  function syncAttrs() {
    app.setAttribute('data-workspace', state.workspace);
    app.setAttribute('data-subview', state.subview);
    app.setAttribute('data-view', state.view);
    document.querySelectorAll('.navitem[data-ws]').forEach(function (n) {
      n.classList.toggle('active', n.getAttribute('data-ws') === state.workspace);
    });
    var aiWs = document.getElementById('aiCtxWs');
    if (aiWs) aiWs.textContent = NAV[state.workspace].title.replace(/\s*\/\s*/g, ' / ') +
      (state.subview ? ' · ' + state.subview : '');
    document.dispatchEvent(new CustomEvent('ed:view', { detail: Object.assign({}, state) }));
  }

  function setWorkspace(ws) {
    if (!NAV[ws]) return;
    state.workspace = ws;
    state.subview = (NAV[ws].subs[0] || {}).id || '';
    var v = (NAV[ws].views && NAV[ws].views[state.subview]) || [];
    state.view = (v[0] || {}).id || '';
    renderSubnav(); renderViewbar(); showPane(); syncAttrs();
  }
  function setSubview(sv) {
    state.subview = sv;
    var v = (NAV[state.workspace].views && NAV[state.workspace].views[sv]) || [];
    state.view = (v[0] || {}).id || '';
    renderSubnav(); renderViewbar(); syncAttrs();
  }
  function setView(v) { state.view = v; renderViewbar(); syncAttrs(); }

  // ================= watchlist (editable foundation, localStorage) =================
  function loadWL() {
    try { var v = JSON.parse(localStorage.getItem(WL_KEY)); if (Array.isArray(v) && v.length) return v; }
    catch (e) {}
    return DEFAULT_WL.slice();
  }
  function saveWL(list) { try { localStorage.setItem(WL_KEY, JSON.stringify(list)); } catch (e) {} }

  function renderWatchlist() {
    var list = loadWL();
    var host = document.getElementById('watchlist');
    var add = document.getElementById('wlAdd');
    host.querySelectorAll('.wl-row').forEach(function (n) { n.remove(); });
    list.forEach(function (sym) {
      var row = document.createElement('div');
      row.className = 'wl-row' + (sym === state.ticker ? ' sel' : '');
      row.innerHTML = '<span class="tk">' + sym.replace('$', '') + '</span>' +
        '<span class="info"><span class="s">' + sym + '</span><span class="p mono" data-wlpx="' + sym + '">—</span></span>' +
        '<span class="st" title="event state not yet canonical"></span>' +
        '<button class="st-x" data-rm="' + sym + '" aria-label="Remove ' + sym + '" ' +
        'style="background:none;border:none;color:var(--ed-ink-4);font-size:13px;padding:0 2px;display:none">×</button>';
      row.addEventListener('click', function (e) {
        if (e.target.getAttribute('data-rm')) return;
        setTicker(sym);
      });
      row.addEventListener('mouseenter', function () { var x = row.querySelector('[data-rm]'); if (x && app.classList.contains('rail-open')) x.style.display = ''; });
      row.addEventListener('mouseleave', function () { var x = row.querySelector('[data-rm]'); if (x) x.style.display = 'none'; });
      host.insertBefore(row, add);
    });
    host.querySelectorAll('[data-rm]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); removeSymbol(b.getAttribute('data-rm')); });
    });
  }
  function addSymbol(sym) {
    sym = (sym || '').trim().toUpperCase();
    if (!sym) return;
    var list = loadWL();
    if (list.indexOf(sym) === -1) { list.push(sym); saveWL(list); }
    renderWatchlist(); setTicker(sym);
  }
  function removeSymbol(sym) {
    var list = loadWL().filter(function (s) { return s !== sym; });
    saveWL(list); renderWatchlist();
  }

  // ================= ticker store =================
  function setTicker(sym) {
    state.ticker = (sym || '').toUpperCase();
    try { localStorage.setItem(TICKER_KEY, state.ticker); } catch (e) {}
    ['hSym', 'cSym', 'aiCtxSym'].forEach(function (id) { var el = document.getElementById(id); if (el) el.textContent = state.ticker; });
    document.querySelectorAll('.wl-row').forEach(function (r) {
      var s = r.querySelector('.info .s'); r.classList.toggle('sel', s && s.textContent === state.ticker);
    });
    refreshHeader();
    document.dispatchEvent(new CustomEvent('ed:ticker', { detail: { ticker: state.ticker } }));
  }

  // ================= header live data (single coordinated poll; degrades honestly) =================
  function fmt(n, d) { return (n === null || n === undefined || isNaN(n)) ? '—' : Number(n).toFixed(d === undefined ? 2 : d); }
  function setFeed(cls, label, age) {
    var dot = document.getElementById('hFeedDot'), f = document.getElementById('hFeed'), a = document.getElementById('hAge');
    if (dot) dot.className = 'dot' + (cls ? ' ' + cls : '');
    if (f) f.textContent = label;
    if (a) a.textContent = age;
    var fresh = document.getElementById('aiCtxFresh'); if (fresh) fresh.textContent = label + (age && age !== '—' ? ' · ' + age : '');
  }
  function refreshHeader() {
    fetch('/api/live/state?ticker=' + encodeURIComponent(state.ticker), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (d.state_error) { setFeed('stale', 'DEGRADED', d.state_error); return; }
        var px = document.getElementById('hPx'), chg = document.getElementById('hChg'), ba = document.getElementById('hBidAsk');
        if (px) px.textContent = d.spot_disp || fmt(d.spot);
        if (ba) ba.textContent = fmt(d.bid) + ' × ' + fmt(d.ask);
        var lw = d.analytics_lightweight || {};
        if (chg) {
          // formatting only — sign/value are canonical
          var s = lw[({SPY:'spy',QQQ:'qqq',IWM:'iwm'})[state.ticker] + '_chg_pct'];
          if (s !== undefined && s !== null) { chg.textContent = (s >= 0 ? '+' : '') + fmt(s) + '%'; chg.className = 'chg mono ' + (s >= 0 ? 'pos' : 'neg'); }
          else chg.textContent = '';
        }
        var age = (d.streaming_plane && d.streaming_plane.streaming_staleness_ms != null)
          ? Math.round(d.streaming_plane.streaming_staleness_ms) + 'ms' : '—';
        var healthy = d.streaming_plane && d.streaming_plane.streaming_healthy;
        setFeed(healthy ? '' : 'warn', healthy ? 'LIVE' : 'DEGRADED', age);
      })
      .catch(function () { setFeed('stale', 'OFFLINE', 'no console'); });
  }

  // ================= CT clock =================
  function tickClock() {
    var now = new Date();
    var t = now.toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/Chicago' });
    var dt = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: '2-digit', timeZone: 'America/Chicago' });
    var c = document.getElementById('hClock'), cd = document.getElementById('hClockDate');
    if (c) c.textContent = t + ' CT';
    if (cd) cd.textContent = dt;
  }

  // ================= wire up =================
  function init() {
    // rail collapse/expand (persisted)
    if (localStorage.getItem(RAIL_KEY) === '0') app.classList.remove('rail-open');
    document.getElementById('railToggle').addEventListener('click', function () {
      app.classList.toggle('rail-open');
      try { localStorage.setItem(RAIL_KEY, app.classList.contains('rail-open') ? '1' : '0'); } catch (e) {}
    });
    // workspace nav
    document.querySelectorAll('.navitem[data-ws]').forEach(function (n) {
      n.addEventListener('click', function () { setWorkspace(n.getAttribute('data-ws')); });
    });
    // subnav/viewbar initial (Options/Gamma hardcoded in HTML; re-render to bind + data-drive)
    renderSubnav(); renderViewbar(); syncAttrs();
    // subnav/view tabs already in HTML are re-bound by renderSubnav/renderViewbar
    // watchlist
    renderWatchlist();
    document.getElementById('wlAdd').addEventListener('click', function () {
      var s = window.prompt('Add symbol to watchlist'); if (s) addSymbol(s);
    });
    // search
    var search = document.getElementById('symSearch');
    if (search) search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && search.value.trim()) { addSymbol(search.value); search.value = ''; }
    });
    // AI drawer
    document.getElementById('aiOpen').addEventListener('click', function () {
      var d = document.getElementById('aidrawer'); d.classList.add('open'); d.setAttribute('aria-hidden', 'false');
    });
    document.getElementById('aiClose').addEventListener('click', function () {
      var d = document.getElementById('aidrawer'); d.classList.remove('open'); d.setAttribute('aria-hidden', 'true');
    });
    // initial ticker + header
    setTicker(state.ticker);
    tickClock(); setInterval(tickClock, 1000);
    setInterval(refreshHeader, 2500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  // expose for view modules + tests (no trading logic here)
  window.EdShell = { getState: function () { return Object.assign({}, state); }, setTicker: setTicker,
    addSymbol: addSymbol, removeSymbol: removeSymbol, setWorkspace: setWorkspace };
})();
