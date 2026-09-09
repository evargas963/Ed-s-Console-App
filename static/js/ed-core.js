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

  function _ls(k, d) { try { var v = localStorage.getItem(k); return (v == null || v === '') ? d : v; } catch (e) { return d; } }
  function _lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  // D: persist UI navigation state (client state, not market truth)
  var state = {
    ticker: (_ls(TICKER_KEY, 'SPY')).toUpperCase(),
    workspace: _ls('ed_ws', app.getAttribute('data-workspace') || 'options'),
    subview: _ls('ed_sub', app.getAttribute('data-subview') || 'gamma'),
    view: _ls('ed_view', app.getAttribute('data-view') || 'heatmap'),
    selStrike: null, selExpiry: null
  };
  function normalizeState() {   // restored state must be valid for the current NAV config
    if (!NAV[state.workspace]) state.workspace = 'options';
    var subs = NAV[state.workspace].subs.map(function (s) { return s.id; });
    if (subs.indexOf(state.subview) === -1) state.subview = subs[0];
    var v = (NAV[state.workspace].views && NAV[state.workspace].views[state.subview]) || [];
    var vids = v.map(function (x) { return x.id; });
    state.view = vids.indexOf(state.view) !== -1 ? state.view : (vids[0] || '');
  }

  // ---- theme: SYSTEM / LIGHT / DARK — one token contract, two palettes (dark primary) ----
  var THEME_ICON = { system: '◐', light: '☀', dark: '☾' };
  function _mqDark() { try { return window.matchMedia && matchMedia('(prefers-color-scheme: dark)'); } catch (e) { return null; } }
  function resolveTheme(pref) {   // SYSTEM resolves from the OS; LIGHT/DARK are literal
    if (pref === 'light' || pref === 'dark') return pref;
    var mq = _mqDark(); return (mq && mq.matches) ? 'dark' : 'light';
  }
  function applyTheme(pref, opts) {
    if (pref !== 'light' && pref !== 'dark') pref = 'system';
    _lsSet('ed_theme', pref);                                    // persist the PREFERENCE
    var eff = resolveTheme(pref);
    document.documentElement.setAttribute('data-theme', eff);   // ALWAYS a concrete theme (never unset)
    var ic = document.getElementById('themeIcon'); if (ic) ic.textContent = THEME_ICON[pref];
    var btn = document.getElementById('themeBtn'); if (btn) btn.title = 'Theme: ' + pref + ' (resolved ' + eff + ')';
    // presentation only — a theme change never alters market values or selections
    if (!(opts && opts.silent)) document.dispatchEvent(new CustomEvent('ed:theme', { detail: { pref: pref, theme: eff } }));
  }
  function cycleTheme() {
    var cur = _ls('ed_theme', 'system');
    applyTheme(cur === 'system' ? 'light' : cur === 'light' ? 'dark' : 'system');
  }
  // ONE theme owner: in SYSTEM mode an OS light<->dark change re-resolves and re-dispatches
  // ed:theme, so the shell AND the JS-computed heatmap/chart update live. Explicit choices ignore it.
  (function () {
    var mq = _mqDark(); if (!mq) return;
    var onOs = function () { if (_ls('ed_theme', 'system') === 'system') applyTheme('system'); };
    if (mq.addEventListener) mq.addEventListener('change', onOs);
    else if (mq.addListener) mq.addListener(onOs);
  })();

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

  var MV_TITLE = { heatmap: 'Gamma Exposure Heatmap', chart: 'Price + GEX Profile', levels: 'Levels', multimap: 'Multi-Map' };
  function showMainView() {
    if (!(state.workspace === 'options' && state.subview === 'gamma')) return;
    ['heatmap', 'chart', 'levels', 'multimap'].forEach(function (v) {
      var el = document.getElementById('view-' + v);
      if (el) el.classList.toggle('on', v === state.view);
    });
    var t = document.getElementById('mvTitle'); if (t && MV_TITLE[state.view]) t.textContent = MV_TITLE[state.view];
    var cm = document.getElementById('chartModes'); if (cm) cm.hidden = state.view !== 'chart';
    var sc = document.getElementById('heatScope'); if (sc) sc.style.display = state.view === 'heatmap' ? '' : 'none';
  }

  function syncAttrs() {
    app.setAttribute('data-workspace', state.workspace);
    app.setAttribute('data-subview', state.subview);
    app.setAttribute('data-view', state.view);
    _lsSet('ed_ws', state.workspace); _lsSet('ed_sub', state.subview); _lsSet('ed_view', state.view);
    document.querySelectorAll('.navitem[data-ws]').forEach(function (n) {
      n.classList.toggle('active', n.getAttribute('data-ws') === state.workspace);
    });
    var aiWs = document.getElementById('aiCtxWs');
    if (aiWs) aiWs.textContent = NAV[state.workspace].title.replace(/\s*\/\s*/g, ' / ') +
      (state.subview ? ' · ' + state.subview : '');
    showMainView();
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
    state.selStrike = null; state.selExpiry = null;   // a new ticker clears the shared selection
    openHeaderStream(state.ticker);   // (re)subscribe the SSE push to this ticker (one subscription)
    refreshHeader();                  // immediate paint while the stream connects
    document.dispatchEvent(new CustomEvent('ed:ticker', { detail: { ticker: state.ticker } }));
  }

  // A: one selected strike shared across heatmap / profile / dot map / GEX-by-strike / Strike Detail
  function setStrike(strike, expiry) {
    state.selStrike = (strike == null || isNaN(strike)) ? null : Number(strike);
    state.selExpiry = expiry || null;
    document.dispatchEvent(new CustomEvent('ed:strike', { detail: { strike: state.selStrike, expiry: state.selExpiry } }));
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
  // ---- header quote: PUSH via the canonical L1 SSE stream (/api/analytics/light/stream,
  //      event l1_projection), which already carries spot/bid/ask (planes/context_light.py).
  //      Ordering is the shared EdL1SseGuards monotonic l1_generation (+ _server_build_ts tie-
  //      break). Polling /api/live/state is a FALLBACK ONLY, so there is ONE source per truth. ----
  var _hdrGen = 0;                       // guards in-flight poll responses (latest-wins)
  function paintQuote(q) {
    var px = document.getElementById('hPx'), chg = document.getElementById('hChg'), ba = document.getElementById('hBidAsk');
    if (px) px.textContent = q.spot_disp || fmt(q.spot);
    if (ba) ba.textContent = fmt(q.bid) + ' × ' + fmt(q.ask);
    if (chg) {  // formatting only — sign/value are canonical
      if (q.chgPct !== undefined && q.chgPct !== null) {
        chg.textContent = (q.chgPct >= 0 ? '+' : '') + fmt(q.chgPct) + '%';
        chg.className = 'chg mono ' + (q.chgPct >= 0 ? 'pos' : 'neg');
      } else chg.textContent = '';
    }
    setFeed(q.feedCls, q.feedLabel, q.ageLabel);
  }
  function chgPctFor(tkey, lw) {
    if (!lw) return null;
    var k = ({ SPY: 'spy', QQQ: 'qqq', IWM: 'iwm' })[tkey];
    return k ? lw[k + '_chg_pct'] : null;
  }

  var _sse = null, _sseUp = false, _lastSseTs = 0, _l1Gen = {}, _l1Ts = {};
  function closeHeaderStream() { if (_sse) { try { _sse.close(); } catch (e) {} } _sse = null; _sseUp = false; }
  function openHeaderStream(tk) {
    closeHeaderStream();
    if (typeof EventSource === 'undefined') return;
    try { _sse = new EventSource('/api/analytics/light/stream?ticker=' + encodeURIComponent(tk)); }
    catch (e) { _sse = null; return; }
    _sse.addEventListener('l1_projection', function (ev) {
      // the server sends an ENVELOPE {l1_sse_schema, scope, l1_generation, l1_server_build_ts,
      // payload}; the quote fields live on env.payload (server.py:_l1 envelope). Parse envelope,
      // validate envelope+payload scope, guard the PAYLOAD's generation, render from the payload.
      var env; try { env = JSON.parse(ev.data); } catch (e) { return; }
      var p = env && env.payload; if (!p) return;
      var G = window.EdL1SseGuards;
      if (G && !G.l1EnvelopeScopeMatches(env.scope, state.ticker, '')) return;
      if (G && !G.l1PayloadMatchesActiveScope(p.ticker, p.selected_exp, state.ticker, '')) return;
      var gen = (p.l1_generation != null ? p.l1_generation : env.l1_generation);
      var bts = (p._server_build_ts != null ? p._server_build_ts : env.l1_server_build_ts);
      if (G && !G.l1ApplyTierBLightMonotonic(state.ticker, gen, _l1Gen, bts, _l1Ts)) return;
      _sseUp = true; _lastSseTs = Date.now(); _hdrGen++;   // supersede any in-flight fallback poll
      var ageMs = bts ? Math.max(0, Math.round(Date.now() - bts * 1000)) : null;
      paintQuote({ spot_disp: p.spot_disp, spot: p.spot, bid: p.bid, ask: p.ask,
        chgPct: chgPctFor(state.ticker, p.analytics_lightweight),
        feedCls: '', feedLabel: 'LIVE', ageLabel: ageMs != null ? ageMs + 'ms' : 'push' });
    });
    _sse.onerror = function () { _sseUp = false; };   // fall back to polling; the browser reconnects
  }

  // #6: canonical market session (RTH / Pre-Market / After-Hours / Closed) — a DIFFERENT truth
  // from feed liveness, so both are shown. session_label is the canonical carrier (/api/live/state).
  function paintSession(label) {
    var el = document.getElementById('hSession'); if (!el) return;
    var m = { 'RTH': ['RTH', 'rth'], 'Pre-Market': ['PRE', 'pre'], 'After-Hours': ['AH', 'ah'], 'Closed': ['CLOSED', 'closed'] };
    var v = m[label] || [(label || '—'), ''];
    el.textContent = v[0]; el.className = 'sess ' + v[1];
  }
  var _sessGen = 0;
  function refreshSession() {   // slow, session-only read used while the SSE push carries the quote
    var g = ++_sessGen;
    fetch('/api/live/state?ticker=' + encodeURIComponent(state.ticker), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _sessGen) paintSession(d.session_label); })
      .catch(function () { if (g === _sessGen) paintSession(null); });
  }

  function refreshHeader() {   // FALLBACK poll — only runs when the SSE push is not delivering
    var g = ++_hdrGen;
    fetch('/api/live/state?ticker=' + encodeURIComponent(state.ticker), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (g !== _hdrGen) return;
        paintSession(d.session_label);              // header poll also carries session (no extra read)
        if (d.state_error) { setFeed('stale', 'DEGRADED', d.state_error); return; }
        var age = (d.streaming_plane && d.streaming_plane.streaming_staleness_ms != null)
          ? Math.round(d.streaming_plane.streaming_staleness_ms) + 'ms' : '—';
        var healthy = d.streaming_plane && d.streaming_plane.streaming_healthy;
        paintQuote({ spot_disp: d.spot_disp, spot: d.spot, bid: d.bid, ask: d.ask,
          chgPct: chgPctFor(state.ticker, d.analytics_lightweight || {}),
          feedCls: healthy ? '' : 'warn', feedLabel: healthy ? 'LIVE' : 'DEGRADED', ageLabel: age });
      })
      .catch(function () { if (g === _hdrGen) setFeed('stale', 'OFFLINE', 'no console'); });
  }

  // ONE coordinated scheduler. The header prefers the SSE push above; this timer only polls the
  // header as a FALLBACK (SSE down/stalled) and drives the SLOW gamma/terrain refresh — that
  // producer changes on a 60s/5min cadence, so coordinated POLLING (not SSE) is the correct,
  // lowest-cost delivery for it. No duplicate subscriptions, no polling storm.
  var _tick = 0;
  function liveTick() {
    _tick++;
    var sseHealthy = _sseUp && (Date.now() - _lastSseTs <= 9000);
    if (!sseHealthy) refreshHeader();                 // fallback: paints quote + session
    else if (_tick % 4 === 0) refreshSession();       // SSE covers the quote; slow session read
    document.dispatchEvent(new CustomEvent('ed:refresh', { detail: { tick: _tick, slow: _tick % 4 === 0 } }));
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
    // theme control (first-paint script already applied the attr; this reflects it on the button)
    applyTheme(_ls('ed_theme', 'system'), { silent: true });
    var themeBtn = document.getElementById('themeBtn');
    if (themeBtn) themeBtn.addEventListener('click', cycleTheme);
    // workspace nav
    document.querySelectorAll('.navitem[data-ws]').forEach(function (n) {
      n.addEventListener('click', function () { setWorkspace(n.getAttribute('data-ws')); });
    });
    // subnav/viewbar initial — restore persisted workspace/subview/view (D), validated to NAV
    normalizeState();
    renderSubnav(); renderViewbar(); showPane(); syncAttrs();
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
    setInterval(liveTick, 3000);   // single scheduler drives header (fast) + gamma (slow)
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  // expose for view modules + tests (no trading logic here)
  window.EdShell = { getState: function () { return Object.assign({}, state); }, setTicker: setTicker,
    addSymbol: addSymbol, removeSymbol: removeSymbol, setWorkspace: setWorkspace, setStrike: setStrike,
    setTheme: applyTheme };
})();
