/* Ed Console shell core (RC-UI-1) — navigation, watchlist foundation, ticker store,
   header live-data, CT clock, AI drawer. NO trading semantics are computed here: this
   file only fetches canonical endpoints and formats/arranges the results (ONE FAUCET).
   View-specific rendering (heatmap, levels, order flow) is wired in per-view modules. */
(function () {
  'use strict';

  // ---- shared ticker key (compatible with the legacy shell) ----
  var TICKER_KEY = 'ed_ticker';
  var RAIL_KEY = 'ed_rail_open';

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
  // each panel's drawers (onPanel), by the panel's name in the console's push
  var _panelFns = {};
  var state = {
    ticker: (_ls(TICKER_KEY, '') || '').toUpperCase(),
    // the selected instrument's identity as the console serves it (/api/live symbols, ingestIdentity):
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
    // the option contract Flow observes (a Chain click; cleared by a new ticker or expiry)
    contract: null,
    // each chart's timeframe (its toolbar's), kept per viewer
    tfs: { chart: _ls('ed.gchart.tf', '1'), liquidity: _ls('ed.liqm.tf', '5'), desk: _ls('ed.desk.tf', '5') },
    // the expiry columns the heatmap fits (a measurement of the page) and the book heatmap's minutes
    cols: null, bookMinutes: 60,
    // each strike panel's pan: {centre, shift, served}; none: follow the price
    pans: { heatmap: newPan(), gbs: newPan(), vanna: newPan(), charm: newPan(), migration: newPan() },
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
  // The strikes a per-strike panel shows are the server's choice (terrain_engine.strike_window),
  // for the scope and the panel's pan (the view carries both). A pan: {centre, shift, served}.
  // `served` is the centre of the window on screen (the answer the server sent); `centre`/`shift`
  // are what the view asks for (none: follow the price).
  function newPan() { return { centre: null, shift: 0, served: null }; }
  // The strike axis of a per-strike panel: dragging the strike labels pans (rows of movement
  // become `shift` from the centre the drag began on), a double-click follows the price again,
  // ctrl/cmd+wheel over `wheelEl` steps the scope (Auto -> Wider -> All). Each is a new view.
  var _axisDrag = null;
  if (typeof document !== 'undefined') {
    document.addEventListener('mousemove', function (e) {
      var d = _axisDrag; if (!d) return;
      var rows = Math.round((e.clientY - d.startY) / d.rowPx);
      if (rows === d.pan.shift && d.pan.centre === d.base) return;
      d.pan.centre = d.base; d.pan.shift = rows;
      sendView();
    });
    document.addEventListener('mouseup', function () { _axisDrag = null; });
  }
  // An answer's window arrived: its centre is the window on screen (the next drag starts from it).
  // The pan the operator asked for (`centre`, `shift`) is kept as asked.
  function panServed(pan, centre) { pan.served = centre; }
  function wireStrikeAxis(axisEls, wheelEl, pan, rowPx) {
    Array.prototype.forEach.call(axisEls, function (el) {
      el.style.cursor = 'ns-resize';
      el.setAttribute('draggable', 'false');
      el.addEventListener('dragstart', function (e) { e.preventDefault(); });
      el.addEventListener('mousedown', function (e) {
        _axisDrag = { startY: e.clientY, rowPx: rowPx, pan: pan, base: pan.served };
        e.preventDefault(); e.stopPropagation();
      });
      el.addEventListener('dblclick', function (e) {
        pan.centre = null; pan.shift = 0; sendView(); e.stopPropagation();
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
  // (a source label + the served age of its instant + its stale flag) - it never computes freshness and
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
  // The age of an instant an answer names (its `as_of` kind), as the console's push labels it
  // (time_et.age_label, on each panel answer and every beat): the page computes no age. Each
  // drawer places ageSpan(kind); the push fills every span of the kind. While the push is down
  // no age is known.
  var _ageLabels = {};
  var AGE_NOT_KNOWN = 'age not known';
  function ageText(kind) { var l = _ageLabels[kind]; return l == null ? AGE_NOT_KNOWN : l; }
  function ageSpan(kind) { return '<span data-age-of="' + _escBadge(kind) + '">' + _escBadge(ageText(kind)) + '</span>'; }
  function fillAges(labels) {
    Object.keys(labels).forEach(function (k) { _ageLabels[k] = labels[k]; });
    document.querySelectorAll('[data-age-of]').forEach(function (el) {
      el.textContent = ageText(el.getAttribute('data-age-of'));
    });
  }
  // a price row's last trade as every screen words it: Schwab's trade time and its served age
  // (time_et.age_label; while the console's push is down the age is not known)
  function tradeLabel(q) {
    if (q.trade_time_ct == null) return null;
    return q.trade_time_ct + (q.trade_age == null ? ' · age not known' : ' · ' + q.trade_age + ' ago');
  }
  function asOfBadge(o) {
    o = o || {};
    var cls = 'asof' + (o.stale ? ' stale' : (o.ref ? ' ref' : (o.live ? ' live' : '')));
    var parts = [];
    if (o.label) parts.push(_escBadge(o.label));
    if (o.ageOf) parts.push(ageSpan(o.ageOf));
    if (o.stale) parts.push('STALE');
    // the detailed reason is DISCLOSED in the tooltip — never as a paragraph inside an analytical panel
    var title = (o.stale && o.reason) ? o.reason : (o.title || o.label || '');
    return '<span class="' + cls + '" title="' + _escBadge(title) + '">' + parts.join(' · ') + '</span>';
  }

  // ================= watchlist: the one list, kept by the capture daemon =================
  // The page holds the list as the console last served it (/api/watchlist); an add or a removal
  // is the daemon's (POST / DELETE /api/watchlist), and its answer carries the new list.
  var _wl = [];
  function loadWL() { return _wl.slice(); }
  function wlFetch(url, opts) {
    return fetch(url, opts).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  // the list as the console pushes it
  onPanel('watchlist', function (a) {
    if (a.waiting) return;
    if (!a.ok) { wlNotify(a.body ? a.body.error : 'The watchlist could not be read: HTTP ' + a.status); return; }
    // the daemon not reporting: its list is unknown now; the last one stands, marked, with the reason
    if (a.body.tickers === null) { markWlDegraded(a.body.error); return; }
    _wl = a.body.tickers; renderWatchlist();
  });
  // the daemon's answer to an add or a removal: the new list, or what happened instead
  function wlAnswer(a) {
    if (a.j.tickers) { _wl = a.j.tickers; renderWatchlist(); }
    if (a.j.ok) return true;
    if (a.j.op === 'invalid') wlNotify(a.j.ticker + ' is not added: Schwab does not quote it (' + JSON.stringify(a.j.answer) + ')');
    else wlNotify(a.j.error || (a.j.ticker + ': ' + a.j.op));
    return false;
  }

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
      // its values as the daemon last sent them: Schwab sends a field again only when it changes
      if (_served[sym] && _l1[_served[sym].key]) setWlRow(sym, priceRow(_served[sym].key));
    });
    host.querySelectorAll('[data-rm]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); removeSymbol(b.getAttribute('data-rm')); });
    });
    buildSymList();   // the watchlist is only a SUGGESTION list for the instrument control
    // the console is told the new set with the view; nothing reconnects, nothing blanks
    sendView();
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
    if (loadWL().indexOf(sym) !== -1) { wlNotify(sym + ' is already on the watchlist'); setTicker(sym); return; }
    wlNotify('Checking ' + sym + ' with Schwab…');
    wlFetch('/api/watchlist', { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker: sym }) })
      .then(function (a) { if (wlAnswer(a)) setTicker(sym); })
      .catch(function (e) { wlNotify(sym + ' is not added: ' + e); });
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
    wlFetch('/api/watchlist/' + encodeURIComponent(sym), { method: 'DELETE', cache: 'no-store' })
      .then(wlAnswer)
      .catch(function (e) { wlNotify(sym + ' is not removed: ' + e); });
  }

  // Every selection goes through emit(): its event, then the view to the console (once, after
  // every listener has set what the event changes). With no ticker chosen, nothing is shown.
  function emit(name, detail) {
    if (!state.ticker) return;
    document.dispatchEvent(new CustomEvent(name, { detail: detail }));
    sendView();
  }
  function paintNoTicker() {
    var px = document.getElementById('hPx'); if (px) px.textContent = 'CHOOSE A SYMBOL';
    setFeed('stale', 'NO SYMBOL', '—');
    paintIdentity('—');
  }

  // ================= ticker store (ONE selected-symbol state across every surface) =================
  // The instrument's name on every header: as typed until the console serves its display name
  // (/api/live symbols, ingestIdentity).
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
    Object.keys(state.pans).forEach(function (k) { state.pans[k].centre = null; state.pans[k].shift = 0; });   // and follows the price
    openPush();                          // the console's push (the view goes with ed:ticker)
    openDaemon();                        // the daemon's socket: Schwab's messages (the subscribe goes with the view)
    _priceSubTs = Date.now();            // the daemon answers the subscribe with this ticker's record at once
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
  // each option's label is served (MM/DD/YYYY and Schwab's daysToExpiration); pushed again on
  // each new chain for the ticker
  onPanel('expiries', function (a) {
    var sel = document.getElementById('expSel'); if (!sel || a.waiting) return;
    if (!a.ok) {
      sel.innerHTML = '<option value="">All Expirations</option><option value="" disabled>expiries unavailable: HTTP ' + a.status + '</option>';
      return;
    }
    var d = a.body, exps = d.expiries, labels = d.labels;
    var opts = '<option value="">All Expirations</option>';
    exps.forEach(function (e) { opts += '<option value="' + e + '">' + _escBadge(labels[e]) + '</option>'; });
    if (!exps.length && d.reason) opts += '<option value="" disabled>' + _escBadge(d.reason) + '</option>';
    sel.innerHTML = opts;
    var cur = state.expiryFilter;
    if (cur && exps.indexOf(cur) !== -1) { sel.value = cur; }   // keep a still-valid selection
    else { sel.value = ''; if (state.expiryFilter !== null) setExpiry(''); }   // invalid current expiry -> All (honest)
    relabelExpiryDefault();
  });
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
  // ---- header quote + watchlist: the console's price rows on its push (/api/live) -- the
  //      ONLY source of the header quote and the watchlist rows: when it is not delivering,
  //      the header says so -- nothing polls a quote. ----
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
  // Watchlist quotes: setWlRow is the ONE writer for every wl-px/wl-chg cell, from the symbol's
  // price row. A field never sent reads "—"; a price whose feed is down stands, marked not live
  // with the row's reason.
  function setWlRow(sym, q) {
    var spot = q.spot, chgPct = q.chg_pct;
    var pe = document.querySelector('.wl-px[data-wlpx="' + sym + '"]');
    if (pe) {
      pe.textContent = spot == null ? 'UNAVAILABLE' : fmt(spot);
      pe.classList.toggle('not-live-px', !q.feed_live);
      pe.title = q.feed_live ? '' : 'not live' + (q.outage ? ': ' + q.outage : '');
    }
    var ce = document.querySelector('.wl-chg[data-wlchg="' + sym + '"]');
    if (ce) {
      if (chgPct != null) { ce.textContent = (chgPct >= 0 ? '+' : '') + fmt(chgPct) + '%'; ce.className = 'wl-chg ' + (chgPct >= 0 ? 'pos' : 'neg'); }
      else { ce.textContent = '—'; ce.className = 'wl-chg'; }
    }
  }
  // A silent price push marks the list not live with the reason; each row's last pushed values
  // stand until a row arrives again (AGENTS.md rule 5).
  function markWlDegraded(reason) {
    var host = document.getElementById('watchlist');
    if (host) host.classList.add('wl-degraded');
    wlNotify(reason);
  }
  function markWlHealthy() {
    var host = document.getElementById('watchlist');
    if (host) host.classList.remove('wl-degraded');
  }
  // ---- Schwab's messages, straight from the capture daemon (app/market_data/schwab/streaming/
  //      live_ui.py), each by its delivery type: LEVELONE_EQUITIES / LEVELONE_OPTIONS Change (the
  //      fields that changed), the books Whole, CHART_EQUITY and NEWS_HEADLINE every one in order ----
  var PRICE_SILENCE_MS = 3000;   // the daemon beats every 1 s; 3 s of nothing = its socket is down
  var _priceUp = false, _lastPriceTs = 0, _priceSubTs = 0, _daemon = null, _daemonRetry = 0;
  // The market context the server always streams, served in the page (meta ed-market-context,
  // from live_push.MARKET_CONTEXT): [{key, display}]. The daemon sends only what a page asks for,
  // so every page asks for it.
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
  // The daemon's database writer, as each heartbeat carries it: the line and its class are the
  // daemon's (stream_spine.WriterStatus line / cls). No writer status served: '—'.
  function paintRecord(w) {
    var el = document.getElementById('hRecord'); if (!el) return;
    el.textContent = w ? w.line : '—';
    el.className = w ? 'v ' + w.cls : 'v';
  }
  // the daemon's socket: the port the console serves in the page (meta ed-live-ui-port, the
  // daemon's ED_LIVE_UI_PORT); an unfilled page opens none and its prices read absent
  function daemonUrl() {
    var m = document.querySelector('meta[name="ed-live-ui-port"]');
    var port = m ? String(m.getAttribute('content')) : '';
    return /^\d+$/.test(port) ? 'ws://127.0.0.1:' + port + '/' : null;
  }
  function subscribePrices() {
    if (!_daemon || _daemon.readyState !== 1) return;   // sent on open
    _daemon.send(JSON.stringify({ op: 'subscribe', symbols: priceSymbols().concat(state.contract ? [state.contract] : []),
      since: _seqSeen }));
  }
  // the daemon's receive time of the last bar and headline received of each symbol, so a
  // reconnect is sent only those after them, each once ({service: {key: ts_recv}})
  var _seqSeen = {};
  // every CHART_EQUITY bar the daemon has sent this page, per symbol, in order: what each chart at
  // 1 minute draws on the console's history when it is drawn (EdTvChart setBars)
  var _live1m = {};
  // Each symbol's LEVELONE_EQUITIES fields as Schwab sent them (Change: each the last one sent),
  // each symbol's verdict per service and its last trade's time and age, as the daemon's beat
  // serves them ({service: {live, outage}}, {time_ct, age})
  var _l1 = {}, _feedState = {}, _trades = {};
  function openDaemon() {
    var url = daemonUrl();
    if (_daemon || typeof WebSocket === 'undefined' || !url) return;
    var ws = new WebSocket(url);
    _daemon = ws;
    ws.onopen = function () { _daemonRetry = 0; subscribePrices(); };
    ws.onmessage = function (ev) {
      var msg = JSON.parse(ev.data);
      _priceUp = true; _lastPriceTs = Date.now();     // the daemon beats every second
      if (msg.type === 'symbols') { ingestIdentity(msg.symbols); return; }
      if (msg.type === 'feed') {
        paintRecord(msg.feed ? msg.feed.writer : null);
        _feedState = msg.state; _trades = msg.trades;
        Object.keys(_feedState).forEach(function (k) { ingestPriceRow(priceRow(k)); });
        return;
      }
      if (msg.type !== 'schwab') return;
      msg.messages.forEach(function (m) {
        if (m.service === 'LEVELONE_EQUITIES' || m.service === 'LEVELONE_OPTIONS') {   // Change: the fields Schwab changed
          // each field Schwab sent, cleared where the daemon marks it not a number (AGENTS.md rule 2)
          var f = _l1[m.key] || (_l1[m.key] = {}), absent = m.absent;
          Object.keys(m.content).forEach(function (k) {
            if (absent && absent.indexOf(k) !== -1) delete f[k]; else f[k] = m.content[k];
          });
          if (m.service === 'LEVELONE_EQUITIES') ingestPriceRow(priceRow(m.key));
        }
        if (m.service === 'CHART_EQUITY' || m.service === 'NEWS_HEADLINE') {   // All Sequence: each once, in order
          var seen = _seqSeen[m.service] || (_seqSeen[m.service] = {});
          if (typeof m.ts_recv === 'number') seen[m.key] = m.ts_recv;
        }
        if (m.service === 'CHART_EQUITY' && m.bar) (_live1m[m.key] || (_live1m[m.key] = [])).push(m);
        // every Schwab message, by its service, to the screens that draw it (books, bars,
        // headlines, option quotes)
        try { window.dispatchEvent(new CustomEvent('ed:schwab', { detail: m })); } catch (e) { console.error(e); }
      });
    };
    ws.onclose = function () {
      if (_daemon !== ws) return;
      _daemon = null; _priceUp = false;
      setTimeout(openDaemon, Math.min(2000, 250 * Math.pow(2, _daemonRetry++)));   // the daemon restarting is seen at once
    };
    ws.onerror = function () { ws.close(); };
  }
  // One symbol's row as the screen paints it: Schwab's LEVELONE_EQUITIES fields, each the last one
  // sent, named for the painters; its verdict, and its trade time and age, as the daemon serves
  // them. Not live, the values stand, marked (AGENTS.md rule 5).
  var DAEMON_DOWN = "the daemon's socket is down";
  function priceRow(key) {
    // each absent until the daemon has sent it: Schwab's fields, the verdict, the trade's labels
    var f = _l1[key], s = feedVerdict(key, 'LEVELONE_EQUITIES'), t = _trades[key];
    function v(name) { return f && f[name] !== undefined ? f[name] : null; }
    var spot = v('LAST_PRICE'), trade = v('TRADE_TIME_MILLIS');
    return { ticker: key, spot: spot, spot_disp: spot == null ? null : spot.toFixed(2),
      bid: v('BID_PRICE'), ask: v('ASK_PRICE'), bid_size: v('BID_SIZE'), ask_size: v('ASK_SIZE'), mark: v('MARK'),
      last_size: v('LAST_SIZE'), total_volume: v('TOTAL_VOLUME'), net_change: v('NET_CHANGE'),
      chg_pct: v('NET_CHANGE_PERCENT'), chg_pct_regular: v('REGULAR_MARKET_CHANGE_PERCENT'),
      open_price: v('OPEN_PRICE'), high_price: v('HIGH_PRICE'), low_price: v('LOW_PRICE'), prior_close: v('CLOSE_PRICE'),
      trade_ts: trade == null ? null : trade / 1000, trade_time_ct: t && t.time_ct != null ? t.time_ct : null,
      trade_age: t && t.age != null ? t.age : null,
      feed_live: !!s && s.live === true, outage: s && s.outage != null ? s.outage : null, quote_ingestion: 'schwab_streaming_level_one' };
  }
  // What each symbol the page asked for is, as the daemon answers the subscribe: the key its
  // messages carry ("$SPX") and its display name ("SPX").
  function ingestIdentity(list) {
    list.forEach(function (s) {
      _served[s.requested] = s;
      if (s.requested === state.ticker && state.key !== s.key) {
        state.key = s.key; state.display = s.display;
        paintIdentity(s.display);
        if (_l1[s.key]) ingestPriceRow(priceRow(s.key));   // its row as last sent, until it changes
      }
    });
  }
  // ONE row in (the console's price_row), every surface painted from it. Every number and
  // verdict is the server's; the browser only picks the words.
  function ingestPriceRow(q) {
    if (!q || !q.ticker) return;
    if (q.ticker === state.key) {
      // painted NOW, not on requestAnimationFrame: the browser slows or pauses rAF for a
      // window it considers covered (measured 2026-09-24: row in at 6 ms, rAF paint at 773 ms).
      // Only the fields that changed arrive, so there is no burst to throttle -- a few text
      // writes per second. The price is Schwab's last trade with Schwab's
      // trade time, or absent with the served outage reason; the feed state is stated beside it.
      paintQuote({ spot_disp: q.spot_disp, spot: q.spot, bid: q.bid, ask: q.ask,
        chgPct: q.chg_pct, chgPctRegular: q.chg_pct_regular, quoteIngestion: q.quote_ingestion,
        feedCls: q.feed_live ? '' : 'stale',
        feedLabel: q.feed_live ? 'LIVE' : 'OFFLINE',
        ageLabel: (q.outage ? q.outage + ' · ' : '') + (q.trade_time_ct != null ? ('last trade ' + tradeLabel(q)) : 'no trade sent') });
    }
    loadWL().forEach(function (wlSym) {
      if (!_served[wlSym] || _served[wlSym].key !== q.ticker) return;
      setWlRow(wlSym, q);
      markWlHealthy();
    });
    try { window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: q })); } catch (e) {}
  }
  // the daemon's verdict for `key` on Schwab's `service` ({live, outage}); with the daemon's socket
  // down, not live with that reason; null when the daemon has not reported the symbol
  function feedVerdict(key, service) {
    if (!pricePushHealthy()) return { live: false, outage: DAEMON_DOWN };
    var held = _feedState && _feedState[key];
    return held && held[service] ? held[service] : null;
  }
  function pricePushHealthy() { return _priceUp && (Date.now() - _lastPriceTs <= PRICE_SILENCE_MS); }
  // 1 s watchdog: a silent daemon withdraws every price within PRICE_SILENCE_MS + 1 s
  function checkPriceSilence() {
    if (!state.ticker) return;
    if (Date.now() - _liveTs > PRICE_SILENCE_MS) setPushDown(true);   // the console's push: its panels
    if (pricePushHealthy()) return;                                 // the daemon's socket: the prices
    markHeaderPushDown();
    var wlHost = document.getElementById('watchlist');
    if (!(wlHost && wlHost.classList.contains('wl-degraded'))) markWlDegraded('live push down');
  }

  // ---- the console's push (/api/live, one WebSocket). The page sends its view, the operator's
  // selections (viewOf), whenever one changes; it names no route. The console decides the panels
  // on screen for it and pushes each one's answer by name, at once and again on every change that
  // moves it, and the session label. A panel draws what is pushed under its name (onPanel). ----
  var _live = null, _liveRetry = 0, _liveTs = 0;
  // the newest view sent (its number), and the answers that came under an older one, each held
  // until the console has taken the newer view: dropped if the view moved that panel, else drawn
  var _viewSeq = 0, _viewQueued = false, _held = {};
  function viewOf() {
    var pans = {};
    Object.keys(state.pans).forEach(function (k) { pans[k] = { centre: state.pans[k].centre, shift: state.pans[k].shift }; });
    return { seq: _viewSeq, ticker: state.ticker, workspace: state.workspace, subview: state.subview, view: state.view,
      expiry: state.expiryFilter, strike: state.selStrike, strike_expiry: state.selExpiry, contract: state.contract,
      scope: state.scope, venue: state.bookVenue, cols: state.cols, book_minutes: state.bookMinutes,
      tfs: state.tfs, pans: pans, symbols: priceSymbols() };
  }
  // once per turn of the page, after every listener of the event has set its part
  function sendView() {
    if (_viewQueued) return;
    _viewQueued = true;
    Promise.resolve().then(function () {
      _viewQueued = false;
      subscribePrices();                              // the daemon: the symbols this view shows
      if (!_live || _live.readyState !== 1) return;   // sent on open
      _viewSeq += 1;
      _live.send(JSON.stringify({ op: 'view', view: viewOf() }));
    });
  }
  // `fn(answer)` draws panel `name`: {ok, status, body} as pushed, or {waiting: true} while the
  // console computes its value for a new view
  function onPanel(name, fn) {
    if (!_panelFns[name]) _panelFns[name] = [];
    _panelFns[name].push(fn);
  }
  // the elements each panel's values are drawn in, for the panels whose values are read from a
  // Schwab feed: the console says when one is not live (`not_live`, the feed's outage). An element
  // drawn from several panels is marked with every one of them that is not live, whichever
  // arrived last.
  var PANEL_HOSTS = {
    'book.heatmap': ['ofhBody'], flow: ['flowBody'],
    'gamma.surface': ['heatBody'], 'gamma.terrain': ['klBody'], 'gamma.strikes': ['gbsBody'], 'gamma.strike': ['sdBody'],
    'gamma.tape': ['ofBody'], 'gamma.chart.bars': ['chartBody'], 'gamma.chart.strikes': ['chartBody'],
    'gamma.chart.terrain': ['chartBody'], 'gamma.levels': ['levelsBody'],
    vanna: ['vnBody'], charm: ['chmBody'], chain: ['chainBody'], structures: ['stBody'],
    'liquidity.map.zones': ['liqmBody'], 'liquidity.map.levels': ['liqmBody'], 'liquidity.map.bars': ['liqmBody'],
    'liquidity.levels': ['lvlBody'], book: ['obBody'],
    'rightnow.book': ['tdDetect'], 'rightnow.levels': ['tdFrame'], 'rightnow.terrain': ['tdConfirm', 'tdContext', 'tdMigration'],
    'rightnow.zones': ['tdContext'], 'rightnow.strikes': ['tdMigration'],
    'desk.bars': ['tdmChart'], 'desk.levels': ['tdmChart'], 'desk.events': ['tdmChart', 'tdmCardFlow'],
    'desk.zones': ['tdmChart'], 'desk.strikes': ['tdmChart'], 'desk.terrain': ['tdmCardOpt', 'tdmCardVol'],
    'desk.forces': ['tdmCardOpt'], 'desk.book': ['tdmCardLiq', 'tdmCardFlow'] };
  var _notLive = {};                 // each shown panel's not-live reasons (none: live)
  var _shown = [];                   // the panels of the view the console last took
  // the reason every value is not live while the page's own connection to the console is down
  var PUSH_DOWN = 'the console push is down';
  var NO_HOSTS = [];                 // a panel drawn in no marked element
  function hostsOf(n) { return Object.prototype.hasOwnProperty.call(PANEL_HOSTS, n) ? PANEL_HOSTS[n] : NO_HOSTS; }
  function markLive(name, notLive) {           // notLive: the served reasons, or none
    if (notLive) _notLive[name] = notLive; else delete _notLive[name];
    paintMarks();
  }
  // every shown panel's elements, marked again: a drawer may have drawn its element anew
  function paintMarks() { _shown.forEach(function (n) { hostsOf(n).forEach(paintMark); }); }
  function drawnIn(n, id) { return hostsOf(n).indexOf(id) !== -1; }
  function paintMark(id) {
    var host = document.getElementById(id); if (!host) return;
    var why = _pushDown && _shown.some(function (n) { return drawnIn(n, id); }) ? [PUSH_DOWN] : [];
    // each panel drawn in it, in PANEL_HOSTS's order, its served reasons as served, each said once
    Object.keys(PANEL_HOSTS).forEach(function (n) {
      if (_notLive[n] && drawnIn(n, id)) _notLive[n].forEach(function (r) { if (why.indexOf(r) === -1) why.push(r); });
    });
    if (why.length) { host.classList.add('not-live'); host.setAttribute('data-not-live', why.join('; ')); }
    else { host.classList.remove('not-live'); host.removeAttribute('data-not-live'); }
  }
  // the page's connection to the console is down (closed, or no beat): every panel shown stands,
  // not live, until the push beats again
  var _pushDown = false;
  function setPushDown(down) {
    if (down === _pushDown) return;
    _pushDown = down;
    if (down) {                                    // no beat comes: no panel's age is known any more
      var unknown = {};
      Object.keys(_ageLabels).forEach(function (k) { unknown[k] = null; });
      fillAges(unknown);
    }
    document.dispatchEvent(new CustomEvent('ed:push', { detail: { down: down } }));   // the screens that say LIVE redraw
    paintMarks();                                  // then every shown element is marked, the redrawn included
  }
  // each panel drawn on its own: one drawer's error is reported and never stops the others
  function deliver(name, a) {
    if (!_panelFns[name]) return;
    if (a.ages) Object.keys(a.ages).forEach(function (k) { _ageLabels[k] = a.ages[k]; });   // drawn with its ages
    _panelFns[name].forEach(function (fn) {
      try { fn(a); } catch (e) { console.error('panel ' + name + ': ' + (e && e.stack ? e.stack : e)); }
    });
    if ('notLive' in a) markLive(name, a.notLive); else paintMarks();
    if (a.ages) fillAges(a.ages);
  }
  function answerOf(msg) {
    return { ok: msg.status >= 200 && msg.status < 300, status: msg.status, body: msg.body, notLive: msg.not_live,
             ages: msg.ages };
  }
  function openPush() {
    if (_live || typeof WebSocket === 'undefined') return;
    var ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/live');
    _live = ws;
    ws.onopen = function () { _liveRetry = 0; _held = {}; sendView(); };
    ws.onmessage = function (ev) {
      var msg = JSON.parse(ev.data);
      _liveTs = Date.now();                          // the console's push is alive (it beats every second)
      if (msg.type === 'feed') {
        paintSession(msg.session);
        fillAges(msg.as_of_ages);                     // each shown panel's instants, at one instant
        setPushDown(false);                           // the push beats: the console's own marks stand
        return;
      }
      if (msg.type === 'view') {                   // the console took view `msg.seq`; `moved`: its new panels
        Object.keys(_held).forEach(function (n) { if (msg.shown.indexOf(n) === -1) delete _held[n]; });   // off screen
        _shown = msg.shown;
        Object.keys(_notLive).forEach(function (n) { if (msg.shown.indexOf(n) === -1) markLive(n, null); });
        msg.moved.forEach(function (n) { delete _held[n]; deliver(n, { waiting: true }); });
        if (msg.seq !== _viewSeq) return;          // a newer view is on its way: it decides the rest
        var held = _held; _held = {};
        Object.keys(held).forEach(function (n) { deliver(n, held[n]); });
        return;
      }
      if (msg.type !== 'panels') return;              // one change's answers, drawn together
      msg.panels.forEach(function (p) {
        if (msg.seq < _viewSeq) _held[p.panel] = answerOf(p);   // under a view the page has left
        else deliver(p.panel, answerOf(p));
      });
    };
    ws.onclose = function () {
      if (_live !== ws) return;
      _live = null;
      setPushDown(true);
      paintSession('Unknown', 'session unknown: the console push is down');
      setTimeout(openPush, Math.min(2000, 250 * Math.pow(2, _liveRetry++)));
    };
    ws.onerror = function () { ws.close(); };
  }

  // market session (RTH / Pre-Market / After-Hours / Closed, or Unknown while Schwab's /markets
  // answer for today is not held), pushed with the changes
  function paintSession(label, why) {
    var el = document.getElementById('hSession'); if (!el) return;
    var m = { 'RTH': ['RTH', 'rth'], 'Pre-Market': ['PRE', 'pre'], 'After-Hours': ['AH', 'ah'], 'Closed': ['CLOSED', 'closed'],
              'Unknown': ['UNKNOWN', 'unknown'] };
    var v = m[label] || [(label || '—'), ''];
    el.textContent = v[0]; el.className = 'sess ' + v[1]; el.title = why || '';
  }

  // The push is not delivering: the last row pushed stands, marked not live with its trade
  // time (AGENTS.md rule 5); a row never pushed reads absent. Nothing polls for it.
  function markHeaderPushDown() {
    // just asked for this ticker (page load or a ticker change): the row is on its way
    // (WAITING); otherwise the push itself is down (OFFLINE)
    var connecting = Date.now() - _priceSubTs <= PRICE_SILENCE_MS;
    var feedLabel = connecting ? 'WAITING' : 'OFFLINE';
    // no beat comes: no row's age is known any more (every screen that words a trade is told);
    // the trade's time, Schwab's, stands
    Object.keys(_trades).forEach(function (k) { _trades[k] = { time_ct: _trades[k].time_ct, age: null }; });
    Object.keys(_l1).forEach(function (k) {
      try { window.dispatchEvent(new CustomEvent('ed:quote_tick', { detail: priceRow(k) })); } catch (e) { console.error(e); }
    });
    var q = _l1[state.key] ? priceRow(state.key) : undefined;
    if (q === undefined) {             // never sent: absent
      paintQuote({ spot: null, spot_disp: null, bid: null, ask: null, chgPct: null, chgPctRegular: null,
        feedCls: 'stale', feedLabel: feedLabel, ageLabel: connecting ? 'no push yet' : 'live push down' });
    } else {
      paintQuote({ spot: q.spot, spot_disp: q.spot_disp, bid: q.bid, ask: q.ask, chgPct: q.chg_pct,
        chgPctRegular: q.chg_pct_regular, quoteIngestion: q.quote_ingestion, feedCls: 'stale', feedLabel: feedLabel,
        ageLabel: q.trade_time_ct == null ? 'no trade sent' : 'last trade ' + tradeLabel(q) });
    }
    paintRecord(null);
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
    openPush();                          // the console's push: the watchlist, and the ticker's panels once chosen
    openDaemon();                        // the daemon's socket: Schwab's messages, straight to the screen
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
  // the page's own inputs of a panel's view: the Flow contract, the heatmap's columns, the book
  // heatmap's minutes; and each chart's timeframe (kept per viewer)
  function setInput(key, v) {
    if (state[key] === v) return;
    state[key] = v; sendView();
  }
  var TF_KEY = { chart: 'ed.gchart.tf', liquidity: 'ed.liqm.tf', desk: 'ed.desk.tf' };
  function setTf(chart, tf) {
    if (state.tfs[chart] === tf) return;
    state.tfs[chart] = tf; _lsSet(TF_KEY[chart], tf); sendView();
  }
  window.EdShell = { getState: function () { return Object.assign({}, state); }, setTicker: setTicker,
    onPanel: onPanel, setInput: setInput, setTf: setTf, pan: function (name) { return state.pans[name]; },
    pushDown: function () { return _pushDown; }, PUSH_DOWN: PUSH_DOWN,
    addSymbol: addSymbol, setWorkspace: setWorkspace, setStrike: setStrike,
    setTheme: applyTheme,
    marketContext: function () { return MARKET_CONTEXT.slice(); },   // served [{key, display}]
    setScope: setScope, getScope: function () { return state.scope; },
    panServed: panServed, wireStrikeAxis: wireStrikeAxis, asOfBadge: asOfBadge, ageSpan: ageSpan, tradeLabel: tradeLabel, chainEmptyText: chainEmptyText,
    setExpiry: setExpiry, getExpiry: function () { return state.expiryFilter; },
    getMeasure: function () { return state.measure; },
    feedVerdict: feedVerdict,
    liveBars: function (key) { return _live1m[key] ? _live1m[key].slice() : []; },
    priceRow: priceRow,                                    // an equity's row, from the daemon's fields
    // a LEVELONE_EQUITIES / LEVELONE_OPTIONS field as Schwab last sent it, null where it is not a number
    schwabNumber: function (key, name) { return _l1[key] && _l1[key][name] !== undefined ? _l1[key][name] : null; },
    setSubview: setSubview };
})();
