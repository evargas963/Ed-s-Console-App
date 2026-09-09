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
      { id: 'dex', label: 'Delta / DEX', state: 'na' }, { id: 'oi', label: 'Open Interest', state: 'na' },
      { id: 'flow', label: 'Flow' }, { id: 'chain', label: 'Chain' },
      { id: 'structures', label: 'Structures', state: 'na', note: 'NOT PROVEN' } ],
      views: { gamma: [
        { id: 'heatmap', label: 'Heatmap' }, { id: 'chart', label: 'Chart' },
        { id: 'levels', label: 'Levels' }, { id: 'multimap', label: 'Multi-Map' },
        { id: 'term', label: 'Term Structure', state: 'na' }, { id: 'analytics', label: 'Analytics', state: 'na' } ] } },
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
  // #3: ONE presentation-scope for the Gamma workspace. The chart/GEX-by-strike panels window the
  // canonical strikes around spot for readability; this is the SINGLE control of that window, shared
  // by every windowed panel so nothing is silently clipped. Modes: AUTO (each panel's near-money
  // base), WIDER (2x that base), ALL (every strike in the current canonical input). Presentation
  // only — the window never changes any value, only which canonical strikes are on screen.
  var SCOPE_MODES = ['auto', 'wider', 'all'];
  var SCOPE_WIDER_MULT = 2;
  function _lsScope() { var v = _ls('ed_scope', 'auto'); return SCOPE_MODES.indexOf(v) !== -1 ? v : 'auto'; }
  var state = {
    ticker: (_ls(TICKER_KEY, 'SPY')).toUpperCase(),
    workspace: _ls('ed_ws', app.getAttribute('data-workspace') || 'options'),
    subview: _ls('ed_sub', app.getAttribute('data-subview') || 'gamma'),
    view: _ls('ed_view', app.getAttribute('data-view') || 'heatmap'),
    scope: _lsScope(),
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
  // Theme resolution/first-paint/OS-change is owned by window.EdTheme (the pre-CSS bootstrap in
  // console.html). ed-core only CONSUMES it — delegates changes and reflects the control — so there
  // is one canonical resolution path shared by first paint and runtime.
  var THEME_ICON = { system: '◐', light: '☀', dark: '☾' };
  function reflectThemeIcon() {
    var t = window.EdTheme; if (!t) return;
    var pref = t.getPref(), ic = document.getElementById('themeIcon'), btn = document.getElementById('themeBtn');
    if (ic) ic.textContent = THEME_ICON[pref] || '◐';
    if (btn) btn.title = 'Theme: ' + pref + ' (resolved ' + t.resolve(pref) + ')';
  }
  function applyTheme(pref) { if (window.EdTheme) window.EdTheme.setPref(pref); }   // owner persists+applies+dispatches
  function cycleTheme() {
    var cur = (window.EdTheme && window.EdTheme.getPref()) || 'system';
    applyTheme(cur === 'system' ? 'light' : cur === 'light' ? 'dark' : 'system');
  }
  document.addEventListener('ed:theme', reflectThemeIcon);   // the control follows the owner's changes

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
      var na = v.state === 'na';
      tabHtml += '<button class="vtab' + (v.id === state.view ? ' on' : '') + (na ? ' na' : '') +
        '" data-view="' + v.id + '"' + (na ? ' title="not yet implemented"' : '') + '>' + v.label + '</button>';
    });
    // clear existing tabs
    Array.prototype.slice.call(bar.querySelectorAll('.vtab')).forEach(function (n) { n.remove(); });
    if (ctrls) ctrls.insertAdjacentHTML('beforebegin', tabHtml);
    else bar.insertAdjacentHTML('afterbegin', tabHtml);
    bar.querySelectorAll('.vtab').forEach(function (b) {
      if (b.classList.contains('na')) return;   // unavailable shell tab — part of the IA, not clickable
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
  function reflectScopeVisibility() {
    // #3: the scope control lives in the global view-controls bar. It governs the windowed Gamma
    // panels — the Chart main view AND the GEX-by-strike side panel, which is on screen for every
    // gamma view (heatmap included). So it shows for the whole gamma subview; the heatmap main view
    // itself ignores scope (it serves the server's strike_count-bounded window whole). Hidden
    // entirely outside options/gamma.
    var scp = document.getElementById('scopeCtl'); if (!scp) return;
    scp.hidden = !(state.workspace === 'options' && state.subview === 'gamma');
    if (!scp.hidden) reflectScope();
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
    reflectScopeVisibility();
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

  // #3: presentation-scope — one control, one state, one event for every windowed Gamma panel.
  var SCOPE_LABEL = { auto: 'Auto', wider: 'Wider', all: 'All available' };
  function reflectScope() {
    var ctl = document.getElementById('scopeCtl');
    if (ctl) ctl.querySelectorAll('.scbtn').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-scope') === state.scope);
    });
  }
  function setScope(mode) {
    if (SCOPE_MODES.indexOf(mode) === -1 || mode === state.scope) { reflectScope(); return; }
    state.scope = mode; _lsSet('ed_scope', mode); reflectScope();
    document.dispatchEvent(new CustomEvent('ed:scope', { detail: { scope: mode } }));
  }
  // map a panel's AUTO near-money base fraction to the effective window for the current mode.
  // ALL -> Infinity (no clip: every canonical strike). This is the ONE scope policy.
  function scopeWindow(baseFrac) {
    if (state.scope === 'all') return Infinity;
    if (state.scope === 'wider') return baseFrac * SCOPE_WIDER_MULT;
    return baseFrac;
  }
  // #3: the ONE disclosure line every windowed panel prints — states the mode, the window, and how
  // many of the canonical strikes are on screen vs clipped. A clip is NEVER silent: when strikes are
  // outside the window the count is shown with how to widen. total/shown are canonical-input counts.
  function scopeNote(opts) {
    opts = opts || {};
    var total = opts.total | 0, shown = opts.shown | 0, hidden = Math.max(0, total - shown);
    var frac = scopeWindow(opts.base || 0);
    var winTxt = isFinite(frac) ? ('±' + (frac * 100).toFixed(frac * 100 < 10 ? 1 : 0) + '% around spot')
      : 'all available strikes';
    var main = (SCOPE_LABEL[state.scope] || state.scope) + ' · ' + winTxt + ' · ' +
      shown + ' of ' + total + ' strikes';
    var clip = hidden > 0
      ? '<span class="clip">' + hidden + ' outside view — widen with Wider / All available</span>' : '';
    return '<div class="scope-note"><span>' + main + '</span>' + clip + '</div>';
  }

  // #4: format a compact per-panel source/as-of badge. This ONLY formats server-owned fields
  // (a source label + the server's own age_sec + its stale flag) - it never computes freshness and
  // never merges panels into one global "LIVE". Panels that read the same canonical generation pass
  // the same server age here, so their badges agree without a second computation.
  function _escBadge(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function fmtAge(s) {
    if (s == null || isNaN(s)) return '';
    s = Math.round(Number(s));
    return s < 90 ? (s + 's') : s < 5400 ? (Math.round(s / 60) + 'm') : (Math.round(s / 3600) + 'h');
  }
  function asOfBadge(o) {
    o = o || {};
    var age = fmtAge(o.ageSec);
    var cls = 'asof' + (o.stale ? ' stale' : (o.ref ? ' ref' : (o.live ? ' live' : '')));
    var parts = [];
    if (o.label) parts.push(_escBadge(o.label));
    if (age) parts.push(age);
    if (o.stale && o.reason) parts.push(_escBadge(o.reason));
    return '<span class="' + cls + '" title="' + _escBadge(o.title || o.label || '') + '">' +
      parts.join(' · ') + '</span>';
  }

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
    ['hSym', 'cSym', 'aiCtxSym', 'mvTicker'].forEach(function (id) { var el = document.getElementById(id); if (el) el.textContent = state.ticker.replace('$', ''); });
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
    // theme control — window.EdTheme owns resolution/first-paint/OS changes; reflect + wire the cycle
    reflectThemeIcon();
    var themeBtn = document.getElementById('themeBtn');
    if (themeBtn) themeBtn.addEventListener('click', cycleTheme);
    // workspace nav
    document.querySelectorAll('.navitem[data-ws]').forEach(function (n) {
      n.addEventListener('click', function () { setWorkspace(n.getAttribute('data-ws')); });
    });
    // #3: presentation-scope control (one control for every windowed Gamma panel)
    var scopeCtl = document.getElementById('scopeCtl');
    if (scopeCtl) scopeCtl.querySelectorAll('.scbtn').forEach(function (b) {
      b.addEventListener('click', function () { setScope(b.getAttribute('data-scope')); });
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
    setTheme: applyTheme,
    setScope: setScope, getScope: function () { return state.scope; },
    scopeWindow: scopeWindow, scopeNote: scopeNote, asOfBadge: asOfBadge };
})();
