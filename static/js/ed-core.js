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
  // No built-in watchlist or ticker (universality, operator 2026-09-23): a first run starts
  // empty and every symbol is one the operator chose.
  var DEFAULT_WL = [];

  var app = document.getElementById('app');

  // ---- 3-tier navigation config (workspace -> subnav -> views).
  //      `state:'na'` marks a tab whose canonical capability is absent/partial.
  // A workspace with no view-tab family uses `Object.create(null)`, never a plain `[]` or
  // `{}` -- reproduced live (2026-09-13): Liquidity's `views: []` made `cfg.views['map']`
  // resolve to the INHERITED Array.prototype.map function (truthy) instead of undefined,
  // the moment a sub was named 'map' -- renderViewbar's `views.forEach` then threw on every
  // switch INTO Liquidity, and because the throw happened before showPane()/syncAttrs() ran,
  // the workspace silently never became visible (state updated, DOM never did). A null-
  // prototype object has no inherited properties to collide with, for this or any future
  // sub id (map/filter/find/sort/... are all real Array.prototype methods). ----
  var NAV = {
    'trade-desk': { title: 'TRADE DESK', subs: [
      { id: 'desk', label: 'Desk' }, { id: 'right-now', label: 'Right Now' }, { id: 'plan', label: 'Plan' },
      { id: 'expression', label: 'Expression', state: 'na' } ], views: Object.create(null) },
    // Book/DOM first (real, wired 2026-09-13 to /api/order-flow/microstructure); the rest stay
    // `na` until they have their own real wiring -- Overview/Heatmap/Tape/Options Book/History
    // were never anything but a labelled placeholder div, same as Book was before this pass.
    // Book/DOM + Heatmap real (2026-09-13); the rest stay `na` until they have their own real
    // wiring -- Overview/Tape/Options Book/History were never anything but a labelled
    // placeholder div, same as Book/Heatmap were before this pass.
    'order-flow': { title: 'ORDER FLOW', subs: [
      { id: 'book', label: 'Book / DOM' }, { id: 'heatmap', label: 'Heatmap' },
      { id: 'overview', label: 'Overview', state: 'na' },
      { id: 'tape', label: 'Tape', state: 'na' }, { id: 'options-book', label: 'Options Book', state: 'na' },
      { id: 'history', label: 'History', state: 'na' } ], views: Object.create(null) },
    'options': { title: 'OPTIONS', subs: [
      { id: 'gamma', label: 'Gamma' }, { id: 'vanna', label: 'Vanna', note: 'AGG BY STRIKE' },
      { id: 'charm', label: 'Charm', note: 'AGG BY STRIKE' },
      { id: 'dex', label: 'Delta / DEX' }, { id: 'oi', label: 'Open Interest' },
      { id: 'flow', label: 'Flow' }, { id: 'chain', label: 'Chain' },
      { id: 'structures', label: 'Structures' } ],
      views: (function () {
        // dex/oi present the SAME strike x expiry grid + view family gamma does (heatmap/
        // chart/levels/multi-map), just a different `measure` (see MEASURE_BY_SUBVIEW) --
        // one shared view list, not three copies to keep in sync by hand.
        var gammaViews = [
          { id: 'heatmap', label: 'Heatmap' }, { id: 'chart', label: 'Chart' },
          { id: 'levels', label: 'Levels' }, { id: 'multimap', label: 'Multi-Map' },
          { id: 'term', label: 'Term Structure', state: 'na' }, { id: 'analytics', label: 'Analytics', state: 'na' } ];
        return { gamma: gammaViews, dex: gammaViews, oi: gammaViews };
      })() },
    // Map + Levels real (2026-09-13: Map is the "visual liquidity map, not a table" the
    // original placeholder always named -- /api/liquidity-snapshot's own confluence-scored
    // zones on a price axis; Levels reuses ed-gamma-levels.js's /api/levels renderer
    // verbatim). The rest stay `na` until they have their own real wiring.
    'liquidity': { title: 'LIQUIDITY', subs: [
      { id: 'map', label: 'Map' }, { id: 'levels', label: 'Levels' },
      { id: 'profile', label: 'Profile', state: 'na' },
      { id: 'vwap', label: 'VWAP / Value', state: 'na' }, { id: 'session', label: 'Session', state: 'na' },
      { id: 'history', label: 'History', state: 'na' } ], views: Object.create(null) },
    'portfolio': { title: 'PORTFOLIO / RISK', subs: [
      { id: 'positions', label: 'Positions', state: 'na' }, { id: 'exposure', label: 'Exposure', state: 'na' },
      { id: 'risk', label: 'Risk', state: 'na' }, { id: 'scenarios', label: 'Scenarios', state: 'na' } ], views: Object.create(null) },
    'system': { title: 'SYSTEM / TRUST', subs: [
      { id: 'data-health', label: 'Data Health' }, { id: 'feeds', label: 'Feeds' },
      { id: 'provenance', label: 'Provenance' }, { id: 'runtime', label: 'Runtime' } ], views: Object.create(null) }
  };

  function _ls(k, d) { try { var v = localStorage.getItem(k); return (v == null || v === '') ? d : v; } catch (e) { return d; } }
  function _lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  // D: persist UI navigation state (client state, not market truth)
  // The strike-window scopes, served in the page (meta ed-scopes, from terrain_engine.SCOPES):
  // [{key, label}], the first the default. The server picks each panel's strikes for the scope.
  var SCOPES = (function () {
    var m = document.querySelector('meta[name="ed-scopes"]');
    try { return JSON.parse(m ? m.getAttribute('content') : '[]') || []; } catch (e) { return []; }
  })();
  var SCOPE_MODES = SCOPES.map(function (s) { return s.key; });
  function _lsScope() { var v = _ls('ed_scope', SCOPE_MODES[0]); return SCOPE_MODES.indexOf(v) !== -1 ? v : SCOPE_MODES[0]; }
  // every asked-for symbol's served identity, {requested: {requested, key, display}} (ingestIdentity)
  var _served = {};
  var state = {
    ticker: (_ls(TICKER_KEY, '') || '').toUpperCase(),
    // the selected instrument's identity as the daemon's price socket serves it (ingestIdentity):
    // the key every price row and route uses ("$SPX") and its display name ("SPX"); null until served
    key: null, display: null,
    workspace: _ls('ed_ws', app.getAttribute('data-workspace') || 'options'),
    subview: _ls('ed_sub', app.getAttribute('data-subview') || 'gamma'),
    view: _ls('ed_view', app.getAttribute('data-view') || 'heatmap'),
    scope: _lsScope(),
    // the one Schwab book every book panel shows; the two are never combined
    bookVenue: _ls('ed_book_venue', 'NYSE_BOOK') === 'NASDAQ_BOOK' ? 'NASDAQ_BOOK' : 'NYSE_BOOK',
    expiryFilter: null,   // null = All Expirations; else a single 'YYYY-MM-DD' from /api/expiries
    selStrike: null, selExpiry: null,
    // Operator field-inventory audit (2026-09-13): the Gamma heatmap grid, Strike Detail's
    // native fields, and the strike x expiry PROJECTION (server.py project_gamma_surface)
    // already carry dex/vanna/oi/volume per cell alongside gex -- one canonical faucet, four
    // more measures the SAME grid can present, not a second computation or a second UI. This
    // is that ONE measure switch: 'gex' | 'dex' | 'oi' | 'volume'. Vanna stays aggregate-only
    // today (see the Key Levels 'AGG $ ONLY' badge) since it has no per-expiry column yet.
    measure: 'gex'
  };
  function normalizeState() {   // restored state must be valid for the current NAV config
    if (!NAV[state.workspace]) state.workspace = 'options';
    var subDefs = NAV[state.workspace].subs;
    var enabledIds = subDefs.filter(function (s) { return s.state !== 'na'; }).map(function (s) { return s.id; });
    // Membership alone isn't enough: a sub can still be a real, listed id (subDefs still
    // names it) while `state:'na'` now marks it disabled -- localStorage['ed_sub'] persists
    // across a NAV reshuffle, so a returning user whose cached subview was demoted to `na`
    // (several were, this pass) would otherwise restore onto a selected-but-disabled tab with
    // no matching .sub-pane and no fallback outside Options, rendering that workspace blank.
    if (enabledIds.indexOf(state.subview) === -1) state.subview = enabledIds[0] || subDefs[0].id;
    var v0 = NAV[state.workspace].views && NAV[state.workspace].views[state.subview];
    var v = Array.isArray(v0) ? v0 : [];
    var vids = v.map(function (x) { return x.id; });
    state.view = vids.indexOf(state.view) !== -1 ? state.view : (vids[0] || '');
    // A page reload restores `subview` from localStorage (ed_sub) but `measure` was never
    // itself persisted -- reproduced live: reloading on the Open Interest tab showed GEX's
    // own dollar values under an "Open Interest Heatmap" title, because state.measure
    // defaulted back to 'gex' while state.subview correctly restored to 'oi'. Re-derived
    // from the restored subview here, the same rule setSubview's own click path already
    // applies, so a reload and a click land on the identical measure for the same tab.
    if (MEASURE_BY_SUBVIEW[state.subview]) state.measure = MEASURE_BY_SUBVIEW[state.subview];
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
    // Array.isArray, not a truthy/`||` check: `cfg.views` being a plain object or array (both
    // truthy, both able to resolve a lookup to something other than undefined -- see this
    // block's own history, 2026-09-13) must never reach `.forEach` on anything but a real array.
    var v0 = cfg.views && cfg.views[state.subview];
    var views = Array.isArray(v0) ? v0 : [];
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
    // keep the control bar for every options subview (the ticker/expiry dropdowns drive Chain too),
    // even those with no view tabs; hide it only for workspaces that have neither views nor controls.
    bar.style.display = (views.length || state.workspace === 'options') ? '' : 'none';
  }

  function showPane() {
    document.querySelectorAll('.workspace').forEach(function (w) {
      w.classList.toggle('on', w.getAttribute('data-ws-pane') === state.workspace);
    });
  }
  // Subview panes (Gamma grid / Chain ladder / Flow, and now Liquidity / Order Flow / Trade
  // Desk's own sub-panes) swap in the one workspace canvas; scoped to the CURRENT workspace's
  // own <section data-ws-pane="..."> so two different workspaces reusing the same sub id (e.g.
  // both Liquidity and Order Flow have a "history" sub) never resolve to the wrong pane. Within
  // Options specifically, a subview with no dedicated pane still falls back to the Gamma grid
  // so that workspace is never blank -- no other workspace has (or needs) that fallback.
  function showSubPane() {
    var wsSection = document.querySelector('.workspace[data-ws-pane="' + state.workspace + '"]');
    var panes = wsSection ? wsSection.querySelectorAll('.sub-pane') : [];
    if (!panes.length) return;
    var target = state.subview;
    var hasOwn = target && wsSection.querySelector('.sub-pane[data-sub-pane="' + target + '"]');
    panes.forEach(function (p) {
      var id = p.getAttribute('data-sub-pane');
      p.classList.toggle('on', !!target &&
        (id === target || (state.workspace === 'options' && id === 'gamma' && !hasOwn)));
    });
    relabelExpiryDefault();   // the null-expiry label is subview-contextual (Chain = Default Expiry)
  }

  // Measure-adaptive panel title for the 'heatmap' view -- dex/oi (and gex itself) all share
  // this ONE grid (see state.measure's own comment), so its title must name whichever
  // measure is actually selected, not always say "Gamma Exposure Heatmap" while showing DEX.
  var MEASURE_TITLE = { gex: 'Gamma Exposure Heatmap', dex: 'Delta Exposure (DEX) Heatmap',
    oi: 'Open Interest Heatmap', volume: 'Volume Heatmap' };
  var MV_TITLE = { levels: 'Levels', multimap: 'Multi-Map' };
  // the Chart view draws the selected measure's per-strike profile (ed-gamma-chart.js); volume has none
  var CHART_TITLE = { gex: 'Price + GEX Profile', dex: 'Price + DEX Profile', oi: 'Price + Open Interest Profile',
    volume: 'Price + GEX Profile' };
  function showMainView() {
    // dex/oi are the SAME gamma pane (see NAV/MEASURE_BY_SUBVIEW) under a different subview
    // id -- the view-switching/title logic below applies to all three, not gamma alone.
    if (!(state.workspace === 'options' && (state.subview === 'gamma' || state.subview === 'dex' || state.subview === 'oi'))) return;
    ['heatmap', 'chart', 'levels', 'multimap'].forEach(function (v) {
      var el = document.getElementById('view-' + v);
      if (el) el.classList.toggle('on', v === state.view);
    });
    var t = document.getElementById('mvTitle');
    if (t) t.textContent = state.view === 'heatmap' ? (MEASURE_TITLE[state.measure] || MEASURE_TITLE.gex)
      : state.view === 'chart' ? (CHART_TITLE[state.measure] || CHART_TITLE.gex) : (MV_TITLE[state.view] || '');
    var cm = document.getElementById('chartModes'); if (cm) cm.hidden = state.view !== 'chart';
    var sc = document.getElementById('heatScope'); if (sc) sc.style.display = state.view === 'heatmap' ? '' : 'none';
  }
  // active-workspace children expanded under it in the rail (the reference Options tree). Reuses the
  // NAV subs; clicking a child sets the subview — same one nav state as the horizontal subnav.
  function renderRailChildren() {
    Array.prototype.slice.call(document.querySelectorAll('.rail-children')).forEach(function (n) { n.remove(); });
    var active = document.querySelector('.navitem[data-ws="' + state.workspace + '"]');
    var cfg = NAV[state.workspace];
    if (!active || !cfg || !cfg.subs || !cfg.subs.length) return;
    var box = document.createElement('div');
    box.className = 'rail-children';
    cfg.subs.forEach(function (s) {
      var na = s.state === 'na';
      var el = document.createElement('a');
      el.className = 'rail-child' + (s.id === state.subview ? ' on' : '') + (na ? ' na' : '');
      el.textContent = s.label;
      if (!na) el.addEventListener('click', function () { setSubview(s.id); });
      box.appendChild(el);
    });
    active.insertAdjacentElement('afterend', box);
  }

  // #8: maximize the Gamma main analytical panel (Heatmap/Chart). PRESENTATION ONLY — it toggles a
  // grid class that hides the Key Levels rail + bottom strip; the shared ticker / strike / expiry /
  // scope state is never touched, so Restore returns to the exact same context. Persisted + Esc.
  var MAX_KEY = 'ed_gamma_max';
  function applyMaximize(on) {
    var grid = document.querySelector('.gamma-grid'); if (!grid) return;
    grid.classList.toggle('maxed', !!on);
    var b = document.getElementById('maxBtn');
    if (b) { b.classList.toggle('on', !!on); b.title = on ? 'Restore panel (Esc)' : 'Maximize panel (Esc to restore)'; }
    _lsSet(MAX_KEY, on ? '1' : '0');
  }
  function toggleMaximize() {
    var grid = document.querySelector('.gamma-grid');
    applyMaximize(!(grid && grid.classList.contains('maxed')));
  }

  function reflectScopeVisibility() {
    // The scope control shows on the gamma-family subviews (MEASURE_BY_SUBVIEW), whose panels the
    // server windows by it.
    var scp = document.getElementById('scopeCtl'); if (!scp) return;
    scp.hidden = !(state.workspace === 'options' && !!MEASURE_BY_SUBVIEW[state.subview]);
    if (!scp.hidden) reflectScope();
  }

  // Audit finding #4 (2026-09-16): suppresses syncAttrs()'s ed:view dispatch during init()'s
  // own cold-boot pass -- see that dispatch's own comment for why.
  var _booting = true;

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
    showSubPane();
    showMainView();
    reflectScopeVisibility();
    renderRailChildren();
    // Audit finding #4 (2026-09-16): init() below calls syncAttrs() AND setTicker() during
    // the SAME cold-boot pass, each dispatching its own event (ed:view / ed:ticker) into
    // every view module's now-live listener (see init()'s own comment on why this dispatch
    // used to reach nobody). Every module treats ed:view and ed:ticker as equally sufficient
    // triggers for a full reload, so firing BOTH during boot -- when neither the view nor the
    // ticker has actually CHANGED from anything, there is simply no prior state yet -- causes
    // a genuine duplicate hydration this fix exists to eliminate. `_booting` suppresses this
    // dispatch only during that one initial pass; setTicker's OWN ed:ticker dispatch (below,
    // unconditional) is the single signal every module hydrates from at cold start, and
    // ed:view fires normally, exactly once per call, on every REAL subsequent view change.
    if (!_booting) emit('ed:view', Object.assign({}, state));
  }

  function setWorkspace(ws) {
    if (!NAV[ws]) return;
    state.workspace = ws;
    // First ENABLED sub, not just subs[0] -- every workspace today happens to list its real
    // tab first, but nothing enforced that; landing a workspace switch on a `state:'na'` tab
    // would hit the exact same "selected but disabled, no matching pane" gap normalizeState()
    // guards against on reload.
    var firstEnabled = NAV[ws].subs.filter(function (s) { return s.state !== 'na'; })[0] || NAV[ws].subs[0] || {};
    state.subview = firstEnabled.id || '';
    var v0 = NAV[ws].views && NAV[ws].views[state.subview];
    var v = Array.isArray(v0) ? v0 : [];
    state.view = (v[0] || {}).id || '';
    renderSubnav(); renderViewbar(); showPane(); syncAttrs();
  }
  // Which measure a given Options subview presents on the SAME strike x expiry grid the
  // Gamma tab already renders -- see `state.measure`'s own comment. A subview absent here
  // (chain/flow/structures/vanna/charm — vanna/charm have no per-expiry surface yet) leaves
  // the measure untouched, so returning to Gamma after visiting Chain still shows whichever
  // measure was last selected there, exactly like `scope` already persists across subviews.
  var MEASURE_BY_SUBVIEW = { gamma: 'gex', dex: 'dex', oi: 'oi' };
  function setSubview(sv) {
    state.subview = sv;
    var v0 = NAV[state.workspace].views && NAV[state.workspace].views[sv];
    var v = Array.isArray(v0) ? v0 : [];
    state.view = (v[0] || {}).id || '';
    if (MEASURE_BY_SUBVIEW[sv]) setMeasure(MEASURE_BY_SUBVIEW[sv], /*fromSubview*/ true);
    renderSubnav(); renderViewbar(); syncAttrs();
  }
  function setView(v) { state.view = v; renderViewbar(); syncAttrs(); }

  // #dex/#oi: ONE canonical strike x expiry projection (server.py project_gamma_surface)
  // already carries dex/oi/volume alongside gex per cell -- this switches which of those
  // the SAME heatmap grid, Key Levels, and legend present, never a second surface or a
  // second computation. `fromSubview` suppresses the redundant nav re-render setSubview is
  // already about to do for a tab-driven switch; a direct #measureSel change (fromSubview
  // falsy) still needs its own reflect + redraw.
  function reflectMeasure() {
    var sel = document.getElementById('measureSel');
    if (sel && sel.value !== state.measure) sel.value = state.measure;
  }
  function setMeasure(m, fromSubview) {
    if (m === state.measure) { reflectMeasure(); return; }
    state.measure = m;
    reflectMeasure();
    showMainView();   // the heatmap panel title names the measure (see MEASURE_TITLE)
    if (!fromSubview) {
      emit('ed:measure', { measure: m });
    }
  }

  // #3: presentation-scope — one control, one state, one event for every windowed Gamma panel.
  function reflectScope() {
    var ctl = document.getElementById('scopeCtl');
    if (ctl) ctl.querySelectorAll('.scbtn').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-scope') === state.scope);
    });
  }
  function setScope(mode) {
    if (SCOPE_MODES.indexOf(mode) === -1 || mode === state.scope) { reflectScope(); return; }
    state.scope = mode; _lsSet('ed_scope', mode); reflectScope();
    emit('ed:scope', { scope: mode });
  }
  function reflectBookVenue() {
    document.querySelectorAll('.bookvenue .scbtn').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-venue') === state.bookVenue);
    });
  }
  function setBookVenue(v) {
    if (v === state.bookVenue) return;
    state.bookVenue = v; _lsSet('ed_book_venue', v); reflectBookVenue();
    emit('ed:book_venue', { venue: v });
  }
  // The strikes a per-strike panel shows are the server's choice (terrain_engine.strike_window):
  // every panel sends this with its read -- the scope, and while the operator has panned, the
  // centre strike the drag began on and the rows it moved from there.
  function windowQuery(pan) {
    return '&scope=' + encodeURIComponent(state.scope) +
      (pan && pan.centre != null ? '&centre=' + encodeURIComponent(pan.centre) + '&shift=' + (pan.shift | 0) : '');
  }
  // A panel's pan state: {centre, shift, served}. `served` is the centre of the window on screen
  // (the view the server sent); `centre`/`shift` are what the next read asks for (none: follow
  // the price).
  function newPan() { return { centre: null, shift: 0, served: null }; }
  // The strike axis of a per-strike panel: dragging the strike labels pans (rows of movement
  // become `shift` from the centre the drag began on), a double-click follows the price again,
  // ctrl/cmd+wheel over `wheelEl` steps the scope (Auto -> Wider -> All). `reload` re-reads the
  // panel with the pan state as it now is.
  var _axisDrag = null;
  if (typeof document !== 'undefined') {
    document.addEventListener('mousemove', function (e) {
      var d = _axisDrag; if (!d) return;
      var rows = Math.round((e.clientY - d.startY) / d.rowPx);
      if (rows === d.pan.shift && d.pan.centre === d.base) return;
      d.pan.centre = d.base; d.pan.shift = rows;
      d.reload();
    });
    document.addEventListener('mouseup', function () { _axisDrag = null; });
  }
  // A read's view arrived: its centre is the window on screen (the next drag starts from it). The
  // pan the operator asked for (`centre`, `shift`) is kept as asked, so a read still held behind a
  // drag asks for where the drag ended.
  function panServed(pan, centre) { pan.served = centre; }
  function wireStrikeAxis(axisEls, wheelEl, pan, rowPx, reload) {
    Array.prototype.forEach.call(axisEls, function (el) {
      el.style.cursor = 'ns-resize';
      el.setAttribute('draggable', 'false');
      el.addEventListener('dragstart', function (e) { e.preventDefault(); });
      el.addEventListener('mousedown', function (e) {
        _axisDrag = { startY: e.clientY, rowPx: rowPx, pan: pan, base: pan.served, reload: reload };
        e.preventDefault(); e.stopPropagation();
      });
      el.addEventListener('dblclick', function (e) {
        pan.centre = null; pan.shift = 0; reload(); e.stopPropagation();
      });
    });
    if (wheelEl) wheelEl.addEventListener('wheel', function (e) {
      if (!e.ctrlKey && !e.metaKey) return;   // a plain wheel scrolls the panel
      e.preventDefault();
      var cur = SCOPE_MODES.indexOf(state.scope); if (cur === -1) cur = 0;
      var next = e.deltaY > 0 ? Math.min(SCOPE_MODES.length - 1, cur + 1) : Math.max(0, cur - 1);
      if (next !== cur) setScope(SCOPE_MODES[next]);
    }, { passive: false });
  }

  // #4: format a compact per-panel source/as-of badge. This ONLY formats server-owned fields
  // (a source label + the server's own age_sec + its stale flag) - it never computes freshness and
  // never merges panels into one global "LIVE". Panels that read the same canonical generation pass
  // the same server age here, so their badges agree without a second computation.
  function _escBadge(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  // The one empty-chain message for every /api/chain panel (Chain, Strike Detail, contract
  // specs). /api/chain answers the live chain or status 'unavailable' with a named reason --
  // no stored or captured substitute (fallback register R-01) -- so the reason IS the message.
  function chainEmptyText(d) {
    var why = d && d.status === 'unavailable' && d.scope && d.scope.reason;
    return why ? ('chain unavailable — ' + why) : 'no chain for this expiry';
  }
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
    if (o.stale) parts.push('STALE');
    // the detailed reason is DISCLOSED in the tooltip — never as a paragraph inside an analytical panel
    var title = (o.stale && o.reason) ? o.reason : (o.title || o.label || '');
    return '<span class="' + cls + '" title="' + _escBadge(title) + '">' + parts.join(' · ') + '</span>';
  }

  // ================= watchlist (editable foundation, localStorage) =================
  function loadWL() {
    // An explicitly saved EMPTY list (every ticker removed) must stay empty — only an
    // absent key (never saved before) falls back to defaults. `[].length` is falsy, so a
    // naive truthiness check on the parsed array silently resurrected the defaults here.
    try {
      var raw = localStorage.getItem(WL_KEY);
      if (raw == null) return DEFAULT_WL.slice();
      var v = JSON.parse(raw);
      if (Array.isArray(v)) return v;
    } catch (e) {}
    return DEFAULT_WL.slice();
  }
  function saveWL(list) { try { localStorage.setItem(WL_KEY, JSON.stringify(list)); } catch (e) {} }

  function renderWatchlist() {
    var list = loadWL();
    var host = document.getElementById('watchlist');
    var add = document.getElementById('wlAdd');
    host.querySelectorAll('.wl-row, .wl-empty').forEach(function (n) { n.remove(); });
    if (!list.length) {
      var empty = document.createElement('div');
      empty.className = 'wl-empty';
      empty.textContent = 'Watchlist is empty — use + Add symbol below';
      host.insertBefore(empty, add);
    }
    list.forEach(function (sym) {
      var row = document.createElement('div');
      row.className = 'wl-row' + (sym === state.ticker ? ' sel' : '');
      // Remove is a real <button> in normal flow (not display:none swapped by hover JS), so
      // Tab reaches it and Enter/Space activates it natively — CSS (:hover/:focus-within/
      // :focus) alone controls its visibility, no mouse required to discover or use it.
      row.innerHTML = '<span class="wl-sym s">' + (_served[sym] ? _served[sym].display : sym) + '</span>' +
        '<span class="wl-px" data-wlpx="' + sym + '">—</span>' +
        '<span class="wl-chg" data-wlchg="' + sym + '">—</span>' +
        '<button class="st-x" data-rm="' + sym + '" aria-label="Remove ' + sym + ' from watchlist">×</button>';
      row.addEventListener('click', function (e) {
        if (e.target.getAttribute('data-rm')) return;
        setTicker(sym);
      });
      host.insertBefore(row, add);
    });
    host.querySelectorAll('[data-rm]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); removeSymbol(b.getAttribute('data-rm')); });
    });
    buildSymList();   // the watchlist is only a SUGGESTION list for the instrument control
    declareWatchlistStream(loadWL());
    // the open price socket is told the new set; nothing reconnects, nothing blanks
    subscribePrices();
  }
  var _wlMsgTimer = null;
  function wlNotify(msg) {   // understandable feedback for invalid/duplicate add — aria-live, self-clearing
    var el = document.getElementById('wlMsg'); if (!el) return;
    el.textContent = msg;
    if (_wlMsgTimer) clearTimeout(_wlMsgTimer);
    _wlMsgTimer = setTimeout(function () { el.textContent = ''; }, 3000);
  }
  // WATCHLIST = persistent symbols the operator chose to monitor. Adding is an explicit action
  // (the rail's "+ Add symbol"); analysing an instrument never adds it.
  function addSymbol(sym) {
    var raw = sym;
    sym = normSym(sym);
    if (!sym) { wlNotify('Not a valid symbol: "' + raw + '"'); return; }
    var list = loadWL();
    if (list.indexOf(sym) !== -1) { wlNotify(sym + ' is already on the watchlist'); setTicker(sym); return; }
    list.push(sym); saveWL(list);
    renderWatchlist(); setTicker(sym);
  }
  // ACTIVE INSTRUMENT = any supported Schwab symbol the operator wants to analyse now. The client
  // only normalises the FORM (upper-case, the vendor's symbol alphabet); whether the instrument is
  // real/supported is decided by the backend, which fails closed (state_error / no chain) — nothing
  // is fabricated for an unknown symbol, and no hard-coded allowlist exists here.
  function normSym(raw) {
    var s = String(raw || '').trim().toUpperCase();
    return /^[$^]?[A-Z0-9][A-Z0-9.\-\/]{0,11}$/.test(s) ? s : null;
  }
  function removeSymbol(sym) {
    var list = loadWL().filter(function (s) { return s !== sym; });
    saveWL(list); renderWatchlist();   // renderWatchlist reopens the push for the new list
  }

  // Every view event goes through emit(): with no ticker chosen, no panel is asked to load
  // (each would otherwise fetch for an empty symbol).
  function emit(name, detail) {
    if (!state.ticker) return;
    document.dispatchEvent(new CustomEvent(name, { detail: detail }));
  }
  function paintNoTicker() {
    var px = document.getElementById('hPx'); if (px) px.textContent = 'CHOOSE A SYMBOL';
    setFeed('stale', 'NO SYMBOL', '—');
    paintIdentity('—');
  }

  // ================= ticker store (ONE selected-symbol state across every surface) =================
  // The instrument's name on every header: as typed until the daemon's price socket serves its
  // display name (ingestIdentity).
  // Every panel header ticker label shares .hticker, so a panel added later is never missed.
  function paintIdentity(name) {
    ['hSym', 'aiCtxSym'].forEach(function (id) { var el = document.getElementById(id); if (el) el.textContent = name; });
    document.querySelectorAll('.hticker').forEach(function (el) { el.textContent = name; });
    document.querySelectorAll('.wl-row').forEach(function (r) {
      var s = r.querySelector('.wl-sym'); r.classList.toggle('sel', !!s && (s.textContent === name || s.textContent === state.ticker));
    });
  }
  function setTicker(sym) {
    state.ticker = (sym || '').toUpperCase();
    state.key = null; state.display = null;
    try { localStorage.setItem(TICKER_KEY, state.ticker); } catch (e) {}
    paintIdentity(state.ticker);
    var si = document.getElementById('symInput'); if (si) { si.value = state.ticker; buildSymList(); }   // the control reflects the ONE state
    state.selStrike = null; state.selExpiry = null;   // a new ticker clears the shared selection
    loadExpiries(state.ticker);       // refresh the expiry dropdown from /api/expiries for the new ticker
    openChangeStream(state.ticker);      // levels / flow / liquidity changes and the session
    _priceSubTs = Date.now();
    subscribePrices();                   // the daemon answers with this ticker's row at once
    markHeaderPushDown();                // WAITING until that row lands (milliseconds)
    emit('ed:ticker', { ticker: state.ticker });
  }

  // ---- instrument control: a typed symbol IS the control (institutional selector: type -> Enter ->
  //      the whole workspace changes context). The watchlist only feeds the suggestion list; it is
  //      never a membership test and never changes when an instrument is analysed. ----
  function buildSymList() {
    var dl = document.getElementById('symList'); if (!dl) return;
    var list = loadWL().slice();
    if (list.indexOf(state.ticker) === -1) list.unshift(state.ticker);
    dl.innerHTML = list.map(function (s) { return '<option value="' + s + '"></option>'; }).join('');
  }
  function commitSymInput(input) {
    var v = normSym(input.value);
    if (!v) { input.value = state.ticker; input.classList.add('invalid'); setTimeout(function () { input.classList.remove('invalid'); }, 900); return; }
    input.value = v;
    if (v !== state.ticker) setTicker(v);   // analyse it; the watchlist is untouched
    input.blur();
  }

  // ---- expiry dropdown: populated ONLY from the canonical /api/expiries (never hard-coded) ----
  // each option's label is served (MM/DD/YYYY and Schwab's daysToExpiration)
  // Independent-review finding (2026-09-13), REPRODUCED ("revert the selected expiry on a
  // pushed refresh"): `prev` was captured ONCE at call time and used, unchanged, when the
  // response finally resolved -- if the operator picked a different expiry WHILE this fetch
  // was in flight, the delayed callback still judged that fresh pick against the STALE
  // `prev`, and could revert it back to All Expirations even though the new pick was
  // perfectly valid. Separately, the callback never checked whether `tk` was still the
  // active ticker, so a rapid double ticker-switch could paint an ABANDONED ticker's expiry
  // list into the dropdown under the ticker actually selected now -- the same "stale
  // response, no context check" defect class fixed everywhere else in the gamma views.
  // Fixed: check ticker identity before applying anything, and judge validity against the
  // CURRENT state.expiryFilter at resolution time, never a value captured before the fetch.
  var _expiriesPending = false;
  function loadExpiries(tk) {
    var sel = document.getElementById('expSel'); if (!sel) return;
    fetch('/api/expiries?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('expiries unavailable: HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        if (state.ticker !== tk) return;   // a newer ticker switch superseded this request
        var exps = d.expiries || [], labels = d.labels || {};
        _expiriesPending = !exps.length;   // levels not computed yet: asked again when they change
        var opts = '<option value="">All Expirations</option>';
        exps.forEach(function (e) { opts += '<option value="' + e + '">' + _escBadge(labels[e]) + '</option>'; });
        if (!exps.length && d.reason) opts += '<option value="" disabled>' + _escBadge(d.reason) + '</option>';
        sel.innerHTML = opts;
        var cur = state.expiryFilter;   // CURRENT selection, not one captured before this fetch started
        if (cur && exps.indexOf(cur) !== -1) { sel.value = cur; }   // keep a still-valid selection
        else { sel.value = ''; if (state.expiryFilter !== null) setExpiry(''); }   // invalid current expiry -> All (honest)
        relabelExpiryDefault();
      })
      .catch(function (e) {
        if (state.ticker !== tk) return;
        _expiriesPending = true;
        sel.innerHTML = '<option value="">All Expirations</option><option value="" disabled>' +
          _escBadge((e && e.message) || 'expiries unavailable') + '</option>';
      });
  }
  function setExpiry(v) {
    var nv = v || null;
    if (nv === state.expiryFilter) return;
    state.expiryFilter = nv;
    var sel = document.getElementById('expSel'); if (sel) sel.value = nv || '';
    var ctx = document.getElementById('aiCtxExp');     // the selected option's served label
    if (ctx) ctx.textContent = (sel && nv && sel.selectedIndex >= 0) ? sel.options[sel.selectedIndex].text : 'All';
    emit('ed:expiry', { expiry: nv });
  }
  // B: /api/chain is a COMPLETE SINGLE-EXPIRY surface, so the null option must NOT read
  // "All Expirations" while Chain is active — the server returns ONE (default) expiry. In every
  // other subview null legitimately means all expirations. One expiry authority; label only.
  function relabelExpiryDefault() {
    var sel = document.getElementById('expSel'); if (!sel || !sel.options.length) return;
    var first = sel.options[0];
    if (first && first.value === '') first.textContent =
      (state.workspace === 'options' && state.subview === 'chain') ? 'Default Expiry' : 'All Expirations';
  }

  // A: one selected strike shared across heatmap / profile / dot map / GEX-by-strike / Strike Detail
  function setStrike(strike, expiry) {
    state.selStrike = (strike == null || isNaN(strike)) ? null : Number(strike);
    state.selExpiry = expiry || null;
    emit('ed:strike', { strike: state.selStrike, expiry: state.selExpiry });
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
  // ---- header quote + watchlist: PUSHED BY THE CAPTURE DAEMON over WebSocket (port 8800,
  //      app/market_data/schwab/streaming/live_ui.py) -- the finished row (live_price_rows.
  //      price_row) the instant a Schwab message changes it, plus a feed verdict every second.
  //      No web server is in this path, so no analytics load can delay a price. It is the
  //      ONLY source of the header quote and the watchlist rows (operator rule 2026-09-23: no
  //      fallbacks): when it is not delivering, the header says so -- nothing polls a quote. ----
  // Operator directive (2026-09-14, spot 360 audit): the source that answered THIS number
  // was already on every payload (quote_ingestion / _quote_authority) but never surfaced —
  // a hover tooltip, not new chrome, so the next divergence (if the plane/REST hierarchy
  // ever disagrees again) is diagnosable on the spot the operator is already looking at,
  // not something that needs a screenshot comparison to notice.
  var QUOTE_INGESTION_LABEL = {
    schwab_streaming_level_one: 'streaming', rest_tier_a: 'REST (header bootstrap)',
    rest_watchlist_batch: 'REST (watchlist batch)', live_market_plane: 'streaming plane',
  };
  function paintQuote(q) {
    var px = document.getElementById('hPx'), chg = document.getElementById('hChg'), ba = document.getElementById('hBidAsk');
    if (px) {
      px.textContent = q.spot_disp == null ? 'UNAVAILABLE' : q.spot_disp;
      var srcLbl = q.quoteIngestion ? (QUOTE_INGESTION_LABEL[q.quoteIngestion] || q.quoteIngestion) : '';
      px.title = srcLbl ? ('spot source: ' + srcLbl) : '';
    }
    if (ba) ba.textContent = fmt(q.bid) + ' × ' + fmt(q.ask);
    // Schwab's two change percents, each labelled: the regular session's and the last price's
    // (extended hours included). Formatting only; absent reads "—".
    [[document.getElementById('hChgReg'), 'REG ', q.chgPctRegular], [chg, 'EXT ', q.chgPct]].forEach(function (c) {
      if (!c[0]) return;
      if (c[2] != null) {
        c[0].textContent = c[1] + (c[2] >= 0 ? '+' : '') + fmt(c[2]) + '%';
        c[0].className = 'chg mono ' + (c[2] >= 0 ? 'pos' : 'neg');
      } else { c[0].textContent = c[1] + '—'; c[0].className = 'chg mono'; }
    });
    setFeed(q.feedCls, q.feedLabel, q.ageLabel);
    // paintQuote owns the header display only; watchlist rows are written by setWlRow from
    // the same quote_tick event (one producer, two surfaces).
  }
  // Watchlist quotes: setWlRow is the ONE writer for every wl-px/wl-chg cell, called from the
  // quote_tick handler with the served row. A null field CLEARS to "—"; a row whose values are not
  // live keeps them, marked with the row's served words (`not_live`).
  function setWlRow(sym, q) {
    var pe = document.querySelector('.wl-px[data-wlpx="' + sym + '"]');
    if (pe) {
      pe.textContent = q.spot == null ? 'UNAVAILABLE' : fmt(q.spot);
      pe.classList.toggle('not-live', !!q.not_live);
      pe.title = q.not_live ? q.not_live : '';
    }
    var ce = document.querySelector('.wl-chg[data-wlchg="' + sym + '"]');
    if (ce) {
      if (q.chg_pct != null) { ce.textContent = (q.chg_pct >= 0 ? '+' : '') + fmt(q.chg_pct) + '%'; ce.className = 'wl-chg ' + (q.chg_pct >= 0 ? 'pos' : 'neg'); }
      else { ce.textContent = '—'; ce.className = 'wl-chg'; }
    }
  }
  // A silent price push keeps every row's last value and marks the list not live with the
  // reason and the age of the last push, until a row arrives again.
  function markWlDegraded(reason) {
    var host = document.getElementById('watchlist');
    if (host) host.classList.add('wl-degraded');
    wlNotify(reason);
  }
  function markWlHealthy() {
    var host = document.getElementById('watchlist');
    if (host) host.classList.remove('wl-degraded');
  }
  // The daemon streams only what is asked for: hand it the watchlist whenever it changes
  // (and once at start), so every row can be a streamed quote.
  var _wlDeclared = null;
  function declareWatchlistStream(list) {
    var key = list.join(',');
    if (key === _wlDeclared) return;
    _wlDeclared = key;
    fetch('/api/streaming/watchlist-symbols', { method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbols: list }) })
      .catch(function () { _wlDeclared = null; });   // retried when the console push reopens
  }
  // ---- the price socket (daemon -> browser) ----
  // the daemon beats every 1 s; this long with nothing = the push is down (meta ed-live-silence-ms,
  // the one liveness limit live_market_plane.FEED_HEARTBEAT_MAX_AGE_SEC, which the daemon also
  // closes a browser by)
  var PRICE_SILENCE_MS = (function () {
    var m = document.querySelector('meta[name="ed-live-silence-ms"]');
    return m ? Number(m.getAttribute('content')) : NaN;   // unfilled: the push never reads healthy
  })();
  var _priceWs = null, _priceUp = false, _lastPriceTs = 0, _priceSubTs = 0, _priceRetry = 0;
  // the last served row of the ticker on screen and the daemon's last writer status: kept on
  // screen, marked not live, while the push is down
  var _lastHeaderRow = null, _lastWriter = null;
  // the port comes from the console (meta ed-live-ui-port = the daemon's ED_LIVE_UI_PORT);
  // an unfilled page opens no socket and its prices read UNAVAILABLE
  function priceSocketUrl() {
    var m = document.querySelector('meta[name="ed-live-ui-port"]');
    var port = m ? String(m.getAttribute('content') || '') : '';
    if (!/^\d+$/.test(port)) return null;
    return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.hostname + ':' + port + '/';
  }
  // The market context the server always streams, served in the page (meta ed-market-context,
  // from streaming.MARKET_CONTEXT_SYMBOLS): [{key, display}]. The socket pushes only what a page
  // subscribes to, so every page asks for it.
  var MARKET_CONTEXT = (function () {
    var m = document.querySelector('meta[name="ed-market-context"]');
    try { return JSON.parse(m ? m.getAttribute('content') : '[]') || []; } catch (e) { return []; }
  })();
  function priceSymbols() {
    var out = [];
    if (state.ticker) out.push(String(state.ticker).toUpperCase());
    MARKET_CONTEXT.forEach(function (c) { if (out.indexOf(c.key) === -1) out.push(c.key); });
    loadWL().forEach(function (s) { s = String(s).toUpperCase(); if (out.indexOf(s) === -1) out.push(s); });
    return out;
  }
  function subscribePrices() {
    if (!_priceWs || _priceWs.readyState !== 1) return;   // sent on open
    try { _priceWs.send(JSON.stringify({ op: 'subscribe', symbols: priceSymbols() })); } catch (e) {}
  }
  // The daemon's database writer, as each heartbeat carries it: the line and its class are the
  // daemon's (stream_spine.WriterStatus line / cls). No writer status served: '—'.
  function paintRecord(w) {
    _lastWriter = w;
    var el = document.getElementById('hRecord'); if (!el) return;
    el.textContent = w ? w.line : '—';
    el.className = w ? 'v ' + w.cls : 'v';
  }
  function openPriceSocket() {
    var url = priceSocketUrl();
    if (typeof WebSocket === 'undefined' || !url) return;
    var ws;
    try { ws = new WebSocket(url); } catch (e) { schedulePriceReconnect(); return; }
    _priceWs = ws;   // (_priceSubTs is set by a ticker change only: a reconnect during an
                     //  outage keeps reading OFFLINE, not WAITING)
    ws.onopen = function () { _priceRetry = 0; subscribePrices(); };
    ws.onmessage = function (ev) {
      var msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg && msg.type === 'symbols' && Array.isArray(msg.symbols)) { ingestIdentity(msg.symbols); return; }
      if (msg && msg.type === 'feed') paintRecord(msg.feed && msg.feed.writer);
      if (!msg || !Array.isArray(msg.rows)) return;
      _priceUp = true; _lastPriceTs = Date.now();
      msg.rows.forEach(ingestPriceRow);
    };
    ws.onclose = function () {
      if (_priceWs === ws) { _priceWs = null; _priceUp = false; schedulePriceReconnect(); }
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  function schedulePriceReconnect() {
    // 0.25 s, 0.5 s, 1 s, then every 2 s: the daemon restarting is seen and recovered at once
    var ms = Math.min(2000, 250 * Math.pow(2, _priceRetry++));
    setTimeout(function () { if (!_priceWs) openPriceSocket(); }, ms);
  }
  // What each symbol the page asked for is, as the daemon answers the subscribe: the key its rows
  // carry ("$SPX") and its display name ("SPX"). Rows are matched to what was asked by that key.
  function ingestIdentity(list) {
    list.forEach(function (s) {
      if (!s || !s.key) return;
      _served[s.requested] = s;
      if (s.requested === state.ticker && state.key !== s.key) {
        state.key = s.key; state.display = s.display;
        paintIdentity(s.display);
      }
    });
  }
  // ONE row in (the daemon's price_row), every surface painted from it. Every number and
  // verdict is the server's; the browser only picks the words.
  function ingestPriceRow(q) {
    if (!q || !q.ticker) return;
    if (q.ticker === state.key) {
      // painted NOW, not on requestAnimationFrame: the browser slows or pauses rAF for a
      // window it considers covered (measured 2026-09-24: row in at 6 ms, rAF paint at 773 ms).
      // The daemon already conflates to the newest row per symbol, so there is no burst to
      // throttle -- a few text writes per second. The price is Schwab's last trade with Schwab's
      // trade time; values that are not live carry the served words saying so (`not_live`).
      _lastHeaderRow = q;
      paintHeaderRow(q, q.feed_live ? 'LIVE' : 'FEED DOWN',
        q.not_live ? q.not_live : (q.trade_time_ct != null ? ('last trade ' + q.trade_time_ct) : 'no trade sent'));
    }
    loadWL().forEach(function (wlSym) {
      if (!_served[wlSym] || _served[wlSym].key !== q.ticker) return;
      setWlRow(wlSym, q);
      markWlHealthy();
    });
    try { window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: q })); } catch (e) {}
  }
  function paintHeaderRow(q, feedLabel, ageLabel) {
    paintQuote({ spot_disp: q.spot_disp, spot: q.spot, bid: q.bid, ask: q.ask,
      chgPct: q.chg_pct, chgPctRegular: q.chg_pct_regular, quoteIngestion: q.quote_ingestion,
      feedCls: feedLabel === 'LIVE' ? '' : 'stale', feedLabel: feedLabel, ageLabel: ageLabel });
  }
  function pricePushHealthy() { return _priceUp && (Date.now() - _lastPriceTs <= PRICE_SILENCE_MS); }
  // seconds since the page last heard from the daemon (the page's own clock, both ends)
  function pushSilentSec() { return Math.round((Date.now() - _lastPriceTs) / 1000); }
  // 1 s watchdog: a silent daemon marks every price not live within PRICE_SILENCE_MS + 1 s
  function checkPriceSilence() {
    if (!state.ticker || pricePushHealthy()) return;
    markHeaderPushDown();
    markRecordPushDown();
    var words = 'OFFLINE · live push down · last push ' + pushSilentSec() + ' s ago';
    markWlDegraded(words);
    // every other surface showing a price row keeps it, marked with these words, until the next row
    emit('ed:price_push_down', { words: words });
  }

  // ---- the console's push: which of this ticker's values changed, and the session label.
  // Each panel reloads on `ed:changed` for the kinds it shows: levels, flow, liquidity. ----
  var _changes = null;
  function openChangeStream(tk) {
    if (_changes) { try { _changes.close(); } catch (e) {} }
    _changes = null;
    if (typeof EventSource === 'undefined') return;
    try { _changes = new EventSource('/api/changes?ticker=' + encodeURIComponent(tk)); }
    catch (e) { return; }
    _changes.onopen = function () { _wlDeclared = null; declareWatchlistStream(loadWL()); };
    _changes.onerror = function () { paintSession(null, 'session unknown: the console push is down'); };
    _changes.addEventListener('session', function (ev) { paintSession(ev.data); });
    ['levels', 'chain', 'flow', 'liquidity'].forEach(function (kind) {
      _changes.addEventListener(kind, function () {
        if (kind === 'levels' && _expiriesPending) loadExpiries(state.ticker);
        emit('ed:changed', { kind: kind });
      });
    });
  }

  // market session (RTH / Pre-Market / After-Hours / Closed), pushed with the changes
  function paintSession(label, why) {
    var el = document.getElementById('hSession'); if (!el) return;
    var m = { 'RTH': ['RTH', 'rth'], 'Pre-Market': ['PRE', 'pre'], 'After-Hours': ['AH', 'ah'], 'Closed': ['CLOSED', 'closed'] };
    var v = m[label] || [(label || '—'), ''];
    el.textContent = v[0]; el.className = 'sess ' + v[1]; el.title = why || '';
  }

  // The push is not delivering: the ticker's last served row stays on screen, marked OFFLINE
  // with its Schwab trade time and age; nothing polls for another (AGENTS.md rule 5). With no
  // row yet for this ticker there is nothing to keep: WAITING just after asking for it (page load
  // or a ticker change), else OFFLINE. The daemon's last writer status stays, marked the same
  // (markRecordPushDown).
  function markHeaderPushDown() {
    var q = _lastHeaderRow && _lastHeaderRow.ticker === state.key ? _lastHeaderRow : null;
    if (q) {
      paintHeaderRow(q, 'OFFLINE', 'live push down · ' + (q.trade_ts != null
        ? 'last trade ' + q.trade_time_ct + ', ' + Math.round(Date.now() / 1000 - q.trade_ts) + ' s ago'
        : 'no trade sent'));
    } else {
      var connecting = Date.now() - _priceSubTs <= PRICE_SILENCE_MS;
      paintQuote({ spot: null, spot_disp: null, bid: null, ask: null, chgPct: null, chgPctRegular: null,
        feedCls: 'stale',
        feedLabel: connecting ? 'WAITING' : 'OFFLINE',
        ageLabel: connecting ? 'no push yet' : 'live push down' });
    }
  }
  function markRecordPushDown() {
    var el = document.getElementById('hRecord'); if (!el || !_lastWriter) return;
    el.textContent = 'OFFLINE · last beat ' + pushSilentSec() + ' s ago · ' + _lastWriter.line;
    el.className = 'v stale';
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
    // the scope control: one button per served scope (one control for every per-strike panel)
    var scopeCtl = document.getElementById('scopeCtl');
    if (scopeCtl) SCOPES.forEach(function (s) {
      var b = document.createElement('button');
      b.className = 'scbtn'; b.setAttribute('data-scope', s.key); b.textContent = s.label;
      b.addEventListener('click', function () { setScope(s.key); });
      scopeCtl.appendChild(b);
    });
    reflectScope();
    document.querySelectorAll('.bookvenue .scbtn').forEach(function (b) {
      b.addEventListener('click', function () { setBookVenue(b.getAttribute('data-venue')); });
    });
    reflectBookVenue();
    // ONE canonical strike x expiry projection presents gex/dex/oi/volume -- this control
    // switches which one, on the same grid (see state.measure's own comment).
    var measureSel = document.getElementById('measureSel');
    if (measureSel) {
      reflectMeasure();
      measureSel.addEventListener('change', function () { setMeasure(measureSel.value); });
    }
    // operator dropdowns: ticker (one symbol state) + expiry (from /api/expiries)
    buildSymList();
    var symInput = document.getElementById('symInput');
    if (symInput) {
      symInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); commitSymInput(symInput); } if (e.key === 'Escape') { symInput.value = state.ticker; symInput.blur(); } });
      symInput.addEventListener('change', function () { commitSymInput(symInput); });   // datalist pick / focus-out with an edit
      symInput.addEventListener('focus', function () { symInput.select(); });
      symInput.addEventListener('blur', function () { if (!symInput.value.trim()) symInput.value = state.ticker; });
    }
    var expSel = document.getElementById('expSel');
    if (expSel) expSel.addEventListener('change', function () { setExpiry(expSel.value); });
    // #8: maximize / restore the Gamma main panel
    var maxBtn = document.getElementById('maxBtn');
    if (maxBtn) maxBtn.addEventListener('click', toggleMaximize);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { var g = document.querySelector('.gamma-grid'); if (g && g.classList.contains('maxed')) applyMaximize(false); }
    });
    try { if (localStorage.getItem(MAX_KEY) === '1') applyMaximize(true); } catch (e) {}
    // subnav/viewbar initial — restore persisted workspace/subview/view (D), validated to NAV
    normalizeState();
    // Reflect AGAIN, now that normalizeState() may have just corrected state.measure to
    // match a persisted subview (e.g. a reload landing on Open Interest) -- the earlier
    // reflectMeasure() at bind time ran before normalizeState() and would otherwise leave
    // the dropdown showing "GEX" while the grid itself correctly renders OI (reproduced
    // live: reloading on the Open Interest tab left the control reading GEX).
    reflectMeasure();
    renderSubnav(); renderViewbar(); showPane(); syncAttrs();
    // subnav/view tabs already in HTML are re-bound by renderSubnav/renderViewbar
    // watchlist
    renderWatchlist();
    document.getElementById('wlAdd').addEventListener('click', function () {   // EXPLICIT watchlist add
      var s = window.prompt('Add symbol to watchlist', state.ticker); if (s) addSymbol(s);
    });
    // header search: analyse a symbol (active-instrument change only — never a watchlist mutation)
    var search = document.getElementById('symSearch');
    if (search) search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && search.value.trim()) { var v = normSym(search.value); if (v) { setTicker(v); search.value = ''; } }
    });
    // AI drawer
    document.getElementById('aiOpen').addEventListener('click', function () {
      var d = document.getElementById('aidrawer'); d.classList.add('open'); d.setAttribute('aria-hidden', 'false');
    });
    document.getElementById('aiClose').addEventListener('click', function () {
      var d = document.getElementById('aidrawer'); d.classList.remove('open'); d.setAttribute('aria-hidden', 'true');
    });
    // initial ticker + header
    if (state.ticker) setTicker(state.ticker); else paintNoTicker();
    _booting = false;   // every REAL subsequent view/ticker change dispatches both events normally
    tickClock(); setInterval(tickClock, 1000);
    openPriceSocket();                   // prices: daemon -> browser, one socket for the page
    setInterval(checkPriceSilence, 1000);
  }

  // Audit finding #4 (2026-09-16): every view module (ed-gamma.js, ed-gamma-panels.js, etc.)
  // loads with `defer`, and per the HTML spec a deferred script executes AFTER parsing
  // finishes, while `document.readyState` is already 'interactive' -- so `init()` used to
  // ALWAYS take this file's own "not loading, run immediately" branch, firing `ed:ticker`/
  // `ed:view` (setTicker/syncAttrs, below) before any LATER script tag had even executed,
  // let alone registered its own `ed:ticker`/`ed:view` listener. Every view module's initial
  // render therefore came from its OWN separate bottom-of-file self-call
  // (`else load()`/`else loadAll()`), never from this dispatch -- two independent hydration
  // mechanisms that happened to avoid colliding only because of that ordering coincidence,
  // not because either one was designed to be the sole owner. `init()` now ALWAYS waits for
  // `DOMContentLoaded`, which the HTML spec guarantees fires strictly after every deferred
  // script has executed -- making this dispatch the one hydration trigger every module can
  // reliably listen for, and letting each module's own self-call be removed (see those
  // files) rather than duplicate it. `readyState === 'complete'` is the one case where
  // DOMContentLoaded has already fired (a very late/dynamic script insertion) and must run
  // immediately instead of waiting for an event that will never come again.
  if (document.readyState === 'complete') init();
  else document.addEventListener('DOMContentLoaded', init);

  // expose for view modules + tests (no trading logic here)
  window.EdShell = { getState: function () { return Object.assign({}, state); }, setTicker: setTicker,
    addSymbol: addSymbol, setWorkspace: setWorkspace, setStrike: setStrike,
    setTheme: applyTheme,
    marketContext: function () { return MARKET_CONTEXT.slice(); },   // served [{key, display}]
    setScope: setScope, getScope: function () { return state.scope; },
    windowQuery: windowQuery, newPan: newPan, panServed: panServed, wireStrikeAxis: wireStrikeAxis, asOfBadge: asOfBadge, fmtAge: fmtAge, chainEmptyText: chainEmptyText,
    setExpiry: setExpiry, getExpiry: function () { return state.expiryFilter; },
    getMeasure: function () { return state.measure; },
    setSubview: setSubview };
})();
