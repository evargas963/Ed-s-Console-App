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
      { id: 'right-now', label: 'Right Now' }, { id: 'plan', label: 'Plan' },
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
    'desk': { title: 'DESK / RESEARCH', subs: [
      { id: 'radar', label: 'Radar' }, { id: 'brief', label: 'Brief' }, { id: 'dossier', label: 'Dossier' },
      { id: 'structures', label: 'Structures' }, { id: 'scenarios', label: 'Scenarios' },
      { id: 'evidence', label: 'Evidence' }, { id: 'replay', label: 'Replay' },
      { id: 'ai-research', label: 'AI Research', state: 'na', note: 'NOT PROVEN' } ], views: Object.create(null) },
    'portfolio': { title: 'PORTFOLIO / RISK', subs: [
      { id: 'positions', label: 'Positions', state: 'na' }, { id: 'exposure', label: 'Exposure', state: 'na' },
      { id: 'risk', label: 'Risk', state: 'na' }, { id: 'scenarios', label: 'Scenarios', state: 'na' } ], views: Object.create(null) },
    'system': { title: 'SYSTEM / TRUST', subs: [
      { id: 'data-health', label: 'Data Health' }, { id: 'feeds', label: 'Feeds' },
      { id: 'provenance', label: 'Provenance' }, { id: 'models', label: 'Models' }, { id: 'runtime', label: 'Runtime' } ], views: Object.create(null) }
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
  function _lsScope() { var v = _ls('ed_scope', 'auto'); return SCOPE_MODES.indexOf(v) !== -1 ? v : 'auto'; }
  var state = {
    ticker: (_ls(TICKER_KEY, '') || '').toUpperCase(),
    workspace: _ls('ed_ws', app.getAttribute('data-workspace') || 'options'),
    subview: _ls('ed_sub', app.getAttribute('data-subview') || 'gamma'),
    view: _ls('ed_view', app.getAttribute('data-view') || 'heatmap'),
    scope: _lsScope(),
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
  var MV_TITLE = { chart: 'Price + GEX Profile', levels: 'Levels', multimap: 'Multi-Map' };
  function showMainView() {
    // dex/oi are the SAME gamma pane (see NAV/MEASURE_BY_SUBVIEW) under a different subview
    // id -- the view-switching/title logic below applies to all three, not gamma alone.
    if (!(state.workspace === 'options' && (state.subview === 'gamma' || state.subview === 'dex' || state.subview === 'oi'))) return;
    ['heatmap', 'chart', 'levels', 'multimap'].forEach(function (v) {
      var el = document.getElementById('view-' + v);
      if (el) el.classList.toggle('on', v === state.view);
    });
    var t = document.getElementById('mvTitle');
    if (t) t.textContent = (state.view === 'heatmap')
      ? (MEASURE_TITLE[state.measure] || MEASURE_TITLE.gex) : (MV_TITLE[state.view] || '');
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
    // #3: the scope control lives in the global view-controls bar. It governs the windowed Gamma
    // panels — the Chart main view AND the GEX-by-strike side panel, which is on screen for every
    // gamma view (heatmap included). So it shows for the whole gamma subview; the heatmap main view
    // itself ignores scope (it serves the server's strike_count-bounded window whole). Hidden
    // entirely outside options/gamma-family (dex/oi share this exact pane and are windowed the
    // same way -- reuses MEASURE_BY_SUBVIEW as the one place that family is named, rather than
    // hardcoding 'gamma'/'dex'/'oi' a further time; this control stayed hidden on dex/oi before,
    // leaving no way to see or change an in-effect scope window there).
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
    emit('ed:scope', { scope: mode });
  }
  // The ONE scope policy is a COUNT of canonical strikes around spot — never a percentage.
  // MEASURED 2026-09-10 on the live SPY reference surface (116 strikes at $1 spacing, spot 764):
  // a ±4% window kept 61 strikes and the heatmap rendered all 116, collapsing the approved ~11-row
  // workstation into an unreadable dump. Auto = the approved workstation density; Wider = a larger
  // window; All available = every canonical strike (scrolled at the same row height, never shrunk).
  // This selects WHICH canonical rows are displayed; no value is computed or changed here.
  var SCOPE_ROWS = { auto: 11, wider: 23 };
  function scopeRows() { return state.scope === 'all' ? Infinity : (SCOPE_ROWS[state.scope] || SCOPE_ROWS.auto); }
  // Indices into an ASCENDING strike array: the scopeRows() strikes nearest to spot, centred on the
  // strike nearest spot and clamped to the array's ends (so a spot near the edge still shows a full
  // window). ALL -> every index. Pure presentation selection.
  function scopeSelect(strikes, spot) {
    var total = strikes.length, n = scopeRows();
    if (!total) return { idx: [], shown: 0, total: 0 };
    if (!isFinite(n) || n >= total) return { idx: strikes.map(function (_s, i) { return i; }), shown: total, total: total };
    var sp = (spot == null || spot === '') ? NaN : Number(spot), c = Math.floor(total / 2), best = Infinity;   // null is absent, not 0
    if (isFinite(sp)) strikes.forEach(function (k, i) { var d = Math.abs(Number(k) - sp); if (d < best) { best = d; c = i; } });
    var lo = c - Math.floor((n - 1) / 2), hi = lo + n - 1;
    if (lo < 0) { hi -= lo; lo = 0; }
    if (hi > total - 1) { lo -= (hi - (total - 1)); hi = total - 1; if (lo < 0) lo = 0; }
    var idx = []; for (var i = lo; i <= hi; i++) idx.push(i);
    return { idx: idx, shown: idx.length, total: total };
  }
  // #3: the ONE disclosure line every windowed panel prints — states the mode, the window, and how
  // many of the canonical strikes are on screen vs clipped. A clip is NEVER silent: when strikes are
  // outside the window the count is shown with how to widen. total/shown are canonical-input counts;
  // `extra` lets a panel add its own second dimension (the heatmap's expiration columns).
  function scopeNote(opts) {
    opts = opts || {};
    var total = opts.total | 0, shown = opts.shown | 0, hidden = Math.max(0, total - shown);
    var n = scopeRows();
    var winTxt = isFinite(n) ? (n + ' strikes around spot') : 'all available strikes';
    var main = (SCOPE_LABEL[state.scope] || state.scope) + ' · ' + winTxt + ' · ' +
      shown + ' of ' + total + ' strikes' + (opts.extra ? ' · ' + opts.extra : '');
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
      row.innerHTML = '<span class="wl-sym s">' + sym.replace('$', '') + '</span>' +
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
    pollWatchlistQuotes();   // don't make a newly-added row (or first load) wait out a full slow tick
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
    saveWL(list); renderWatchlist();
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
  }

  // ================= ticker store (ONE selected-symbol state across every surface) =================
  function setTicker(sym) {
    state.ticker = (sym || '').toUpperCase();
    try { localStorage.setItem(TICKER_KEY, state.ticker); } catch (e) {}
    ['hSym', 'aiCtxSym'].forEach(function (id) { var el = document.getElementById(id); if (el) el.textContent = state.ticker.replace('$', ''); });
    // Every panel header ticker label shares .hticker (mvTicker, chTicker, flTicker, vnTicker,
    // chmTicker, stTicker, and any future one) -- a hand-maintained id list here silently froze
    // 5 of these 6 at their HTML placeholder ("SPX") the moment a panel was added without also
    // updating this array (reproduced live: vanna-by-strike/charm-by-strike returned genuinely
    // per-ticker data, e.g. a real TSLA spot/strikes, while their header still read "SPX").
    // Selecting the whole class instead of naming ids makes this un-forgettable.
    document.querySelectorAll('.hticker').forEach(function (el) { el.textContent = state.ticker.replace('$', ''); });
    var si = document.getElementById('symInput'); if (si) { si.value = state.ticker; buildSymList(); }   // the control reflects the ONE state
    document.querySelectorAll('.wl-row').forEach(function (r) {
      var s = r.querySelector('.wl-sym'); r.classList.toggle('sel', s && s.textContent === state.ticker.replace('$', ''));
    });
    state.selStrike = null; state.selExpiry = null;   // a new ticker clears the shared selection
    loadExpiries(state.ticker);       // refresh the expiry dropdown from /api/expiries for the new ticker
    openHeaderStream(state.ticker);   // (re)subscribe the SSE push to this ticker (one subscription)
    markHeaderPushDown();             // CONNECTING until the new ticker's first push
    refreshSession();
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
  function _dteOf(iso) {
    try {
      var d = new Date(iso + 'T00:00:00Z'), now = new Date();
      var t0 = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
      return Math.max(0, Math.round((d.getTime() - t0) / 86400000));
    } catch (e) { return null; }
  }
  function _fmtExpOpt(iso) {
    var parts = String(iso).split('-'); var dte = _dteOf(iso);
    var md = parts.length === 3 ? (parts[1] + '/' + parts[2] + '/' + parts[0]) : iso;
    return md + (dte != null ? (' · ' + dte + 'DTE') : '');
  }
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
  function loadExpiries(tk) {
    var sel = document.getElementById('expSel'); if (!sel) return;
    fetch('/api/expiries?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (state.ticker !== tk) return;   // a newer ticker switch superseded this request
        var exps = (d && (d.expiries || d.expirations)) || [];
        var opts = '<option value="">All Expirations</option>';
        exps.forEach(function (e) { opts += '<option value="' + e + '">' + _fmtExpOpt(e) + '</option>'; });
        sel.innerHTML = opts;
        var cur = state.expiryFilter;   // CURRENT selection, not one captured before this fetch started
        if (cur && exps.indexOf(cur) !== -1) { sel.value = cur; }   // keep a still-valid selection
        else { sel.value = ''; if (state.expiryFilter !== null) setExpiry(''); }   // invalid current expiry -> All (honest)
        relabelExpiryDefault();
      })
      .catch(function () { /* keep the All Expirations default; a cold console just shows All */ });
  }
  function setExpiry(v) {
    var nv = v || null;
    if (nv === state.expiryFilter) return;
    state.expiryFilter = nv;
    var sel = document.getElementById('expSel'); if (sel) sel.value = nv || '';
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
  // ---- header quote: PUSH via the canonical L1 SSE stream (/api/analytics/light/stream,
  //      event l1_projection), which already carries spot/bid/ask (planes/context_light.py).
  //      Ordering is the shared EdL1SseGuards monotonic l1_generation (+ _server_build_ts tie-
  //      break). The push is the ONLY source of the header quote (operator rule 2026-09-23: no
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
      var state = q.spotState || q.spot_state || '';
      if (state === 'unavailable' || (q.spot == null && !q.spot_disp)) {
        px.textContent = 'UNAVAILABLE';
      } else {
        px.textContent = q.spot_disp || fmt(q.spot);
        if (state === 'stale') px.textContent += ' STALE';
      }
      var srcLbl = q.quoteIngestion ? (QUOTE_INGESTION_LABEL[q.quoteIngestion] || q.quoteIngestion) : '';
      if (state) srcLbl = (srcLbl ? srcLbl + ' · ' : '') + state;
      px.title = srcLbl ? ('spot source: ' + srcLbl) : '';
    }
    if (ba) ba.textContent = fmt(q.bid) + ' × ' + fmt(q.ask);
    if (chg) {  // formatting only — sign/value are canonical
      if (q.chgPct !== undefined && q.chgPct !== null) {
        chg.textContent = (q.chgPct >= 0 ? '+' : '') + fmt(q.chgPct) + '%';
        chg.className = 'chg mono ' + (q.chgPct >= 0 ? 'pos' : 'neg');
      } else chg.textContent = '';
    }
    setFeed(q.feedCls, q.feedLabel, q.ageLabel);
    // The header (#hPx/#hChg above) and the watchlist rows are DECOUPLED on purpose: the
    // header shows whatever this specific quote push/poll carried (best-effort, can be
    // momentarily incomplete — e.g. a streamed ticker's spot arrives before its percent-
    // change field does). Measured live: that left the active ticker's OWN watchlist row
    // blank far more often than pollWatchlistQuotes's REST-backed batch read, which is
    // reliably correct for it exactly as it is for every other row. Two writers racing on
    // the same cell (paintQuote's often-incomplete push vs. pollWatchlistQuotes's reliable
    // poll) would flicker the value depending on which happened to run last — so the
    // watchlist rows have exactly ONE writer now (pollWatchlistQuotes, all rows uniformly,
    // active ticker included); paintQuote owns the header display only.
  }
  // Watchlist quotes: setWlRow is the ONE writer for every wl-px/wl-chg cell, called only
  // from pollWatchlistQuotes. A null field CLEARS to "—" rather than leaving the previous
  // text: failure and recovery must not leave a stale-but-current-looking number on screen.
  function setWlRow(sym, spot, chgPct, spotState) {
    var key = (sym || '').replace('$', '');
    var pe = document.querySelector('.wl-px[data-wlpx="' + sym + '"]') || document.querySelector('.wl-px[data-wlpx="' + key + '"]');
    if (pe) {
      if (spotState === 'unavailable' || spot == null) pe.textContent = 'UNAVAILABLE';
      else pe.textContent = fmt(spot) + (spotState === 'stale' ? ' STALE' : '');
    }
    var ce = document.querySelector('.wl-chg[data-wlchg="' + sym + '"]') || document.querySelector('.wl-chg[data-wlchg="' + key + '"]');
    if (ce) {
      if (chgPct != null) { ce.textContent = (chgPct >= 0 ? '+' : '') + fmt(chgPct) + '%'; ce.className = 'wl-chg ' + (chgPct >= 0 ? 'pos' : 'neg'); }
      else { ce.textContent = '—'; ce.className = 'wl-chg'; }
    }
  }
  // Bounded batch poll: ONE /api/watchlist-quotes request per slow tick for the WHOLE
  // watchlist, active ticker included — one vendor round trip regardless of list size, not
  // N sequential single-symbol polls. Every requested symbol is explicitly resolved
  // (present -> its value, absent from the batch response -> null), so a symbol the vendor
  // dropped from the response gets cleared via setWlRow's null path above, never left
  // showing its last good number.
  //
  // _wlPollGen guards against overlapping/out-of-order responses — this fires on the slow
  // tick AND immediately after every add/remove (renderWatchlist), so a fast add/remove can
  // legitimately have two requests in flight at once. Without a generation check, an OLDER
  // request that happens to resolve AFTER a newer one would overwrite fresher data with
  // stale data for whatever symbols both requests shared. Same pattern refreshSession uses
  // (_sessGen).
  var _wlPollGen = 0;
  // A failed poll withdraws every row to UNAVAILABLE (operator rule 2026-09-23: no
  // fallbacks, not even a labelled last-known value) and marks the list degraded with the
  // reason, until a poll succeeds again.
  var _wlLastGoodTs = null;
  function markWlDegraded(reason) {
    var host = document.getElementById('watchlist');
    if (host) host.classList.add('wl-degraded');
    loadWL().forEach(function (sym) { setWlRow(sym, null, null, 'unavailable'); });
    wlNotify(reason);
  }
  function markWlHealthy() {
    var host = document.getElementById('watchlist');
    if (host) host.classList.remove('wl-degraded');
    _wlLastGoodTs = Date.now();
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
      .catch(function () { _wlDeclared = null; });   // retried on the next poll
  }
  function pollWatchlistQuotes() {
    var list = loadWL();
    declareWatchlistStream(list);
    if (!list.length) return;
    var myGen = ++_wlPollGen;
    fetch('/api/watchlist-quotes?tickers=' + encodeURIComponent(list.join(',')), { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('http_' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (myGen !== _wlPollGen) return;   // superseded by a newer poll — drop this stale response
        if (!data || data.ok === false) {
          // The WHOLE batch call failed (auth/vendor/transport) -- distinct from a symbol
          // simply having no data right now (data.quotes just omits it, handled below).
          markWlDegraded('Quotes unavailable' + (data && data.error ? ' (' + data.error + ')' : ''));
          return;
        }
        markWlHealthy();
        var quotes = data.quotes || {};
        list.forEach(function (sym) {
          var row = quotes[sym];
          setWlRow(sym, row ? row.spot : null, row ? row.chg_pct : null,
            row ? row.spot_state : 'unavailable');
        });
      })
      .catch(function () {
        if (myGen !== _wlPollGen) return;
        markWlDegraded('Connection lost — quotes unavailable');
      });
  }

  var _sse = null, _sseUp = false, _lastSseTs = 0, _sseOpenedTs = 0, _l1Gen = {}, _l1Ts = {};
  // requestAnimationFrame throttle: pushes can arrive faster than the screen repaints; only the
  // NEWEST quote is painted, once per frame, so a burst never queues stale paints.
  var _pendingQuote = null, _quoteFrame = 0;
  function paintQuoteNextFrame(q) {
    _pendingQuote = q;
    if (_quoteFrame) return;
    var onFrame = function () {
      _quoteFrame = 0;
      var next = _pendingQuote; _pendingQuote = null;
      if (next) paintQuote(next);
    };
    _quoteFrame = window.requestAnimationFrame ? window.requestAnimationFrame(onFrame)
                                               : setTimeout(onFrame, 16);
  }
  function closeHeaderStream() { if (_sse) { try { _sse.close(); } catch (e) {} } _sse = null; _sseUp = false; }
  function openHeaderStream(tk) {
    closeHeaderStream();
    _sseOpenedTs = Date.now();
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
      _sseUp = true; _lastSseTs = Date.now();
      var ageMs = bts ? Math.max(0, Math.round(Date.now() - bts * 1000)) : null;
      // TRUTHFUL LIVE: receiving an SSE event only proves the SERVER pushed a projection
      // promptly — it does not prove the underlying quote is fresh (the server can build
      // and push on schedule from an L0 row that itself stopped updating). p.l1_stale is
      // the payload's own real freshness verdict (build_l1_context: stale when the L0
      // spot is missing or unusable) — use it, not "an event arrived", to label LIVE vs
      // STALE. Same reasoning the poll-fallback path already applies via streaming_healthy.
      var stale = !!p.l1_stale || p.spot_state === 'stale';
      var unavailable = p.spot_state === 'unavailable' || p.spot == null;
      paintQuoteNextFrame({ spot_disp: p.spot_disp, spot: p.spot, bid: p.bid, ask: p.ask,
        chgPct: p.chg_pct, quoteIngestion: p.quote_ingestion || p._quote_authority,
        spotState: p.spot_state,
        feedCls: unavailable ? 'stale' : (stale ? 'stale' : ''),
        feedLabel: unavailable ? 'UNAVAILABLE' : (stale ? 'STALE' : 'LIVE'),
        ageLabel: ageMs != null ? ageMs + 'ms' : 'push' });
    });
    // Independent-review finding (2026-09-12): the heatmap only ever refetched on the 3s/12s
    // slow-tick poll (liveTick's `ed:refresh` at tick % 4 === 0) -- a Playwright test that
    // manually dispatches that event proves rendering after delivery, not TIMELY delivery.
    // This reuses the ALREADY-OPEN SSE connection (no new daemon/connection) that server.py's
    // refresh_gamma_surface_from_stream now pushes a `gamma_surface_seq` event on the instant
    // it publishes -- the browser reacts to the PUSH instead of waiting out the slow poll.
    //
    // Audit finding #3 (2026-09-16), FIXED: this used to dispatch the SAME generic `ed:refresh`
    // event the 12s poll fires -- every one of the ~11 modules that listen to `ed:refresh` for
    // their OWN, largely UNRELATED endpoint (Chain, Alerts, Trade Desk, Liquidity Map, Order
    // Flow, Flow, Levels) refetched on EVERY single streamed gamma tick, not just the ones that
    // actually consume gamma-surface-derived data. A gamma-surface change now dispatches its
    // own, narrower `ed:gamma-push` event, consumed only by the modules that actually read
    // gamma-surface/per-strike data (ed-gamma.js, ed-gamma-panels.js's GEX-by-strike panel,
    // ed-gamma-chart.js) -- the 12s poll's `ed:refresh{slow}` remains the ONLY thing that
    // drives every other module's slower, session-cadence refresh.
    _sse.addEventListener('gamma_surface_seq', function (ev) {
      var env; try { env = JSON.parse(ev.data); } catch (e) { return; }
      if (!env || !env.scope || String(env.scope.ticker || '').toUpperCase() !== String(state.ticker || '').toUpperCase()) return;
      emit('ed:gamma-push', { surfaceSeq: env.surface_seq });
    });
    _sse.onerror = function () { _sseUp = false; };   // the browser reconnects; the header shows the gap
  }

  // #6: canonical market session (RTH / Pre-Market / After-Hours / Closed) — a DIFFERENT truth
  // from feed liveness, so both are shown. session_label is the canonical carrier (/api/live/state).
  function paintSession(label) {
    var el = document.getElementById('hSession'); if (!el) return;
    var m = { 'RTH': ['RTH', 'rth'], 'Pre-Market': ['PRE', 'pre'], 'After-Hours': ['AH', 'ah'], 'Closed': ['CLOSED', 'closed'] };
    var v = m[label] || [(label || '—'), ''];
    el.textContent = v[0]; el.className = 'sess ' + v[1];
  }
  // Canonical plane identity the view modules cache against (no second clock in JS): the market
  // session state and the Tier C bundle generation (analytics_lightweight.analytics_version), both
  // carried by /api/live/state, which the shell already reads on its slow tick / fallback poll.
  // A change dispatches ONE ed:plane event; nothing here decides what a view does with it.
  // Tier C state is keyed by (ticker, expiry) and its generation is per entry, so the read carries
  // the workspace's expiry context (server: _tier_a_live_state_dict(tkr, expiry) resolves THAT
  // entry; without one, the newest entry for the ticker — the same rule /api/analytics/state uses
  // for a request without expiry). The plane record names the context it was read for.
  var _plane = { ticker: null, expiry: null, session: null, analyticsVersion: null };
  function liveStateUrl() {
    var ex = state.expiryFilter || '';
    return '/api/live/state?ticker=' + encodeURIComponent(state.ticker) + (ex ? '&expiry=' + encodeURIComponent(ex) : '');
  }
  function notePlane(d, expiry) {
    var lw = d.analytics_lightweight || {};
    var next = { ticker: state.ticker, expiry: expiry || '', session: (d.session_label != null ? d.session_label : null),
      analyticsVersion: (lw.analytics_version != null ? lw.analytics_version : null) };
    if (next.ticker === _plane.ticker && next.expiry === _plane.expiry && next.session === _plane.session &&
        next.analyticsVersion === _plane.analyticsVersion) return;
    _plane = next;
    emit('ed:plane', Object.assign({}, _plane));
  }

  var _sessGen = 0;
  function refreshSession() {   // slow, session-only read used while the SSE push carries the quote
    var g = ++_sessGen, ex = state.expiryFilter || '';
    fetch(liveStateUrl(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _sessGen) { paintSession(d.session_label); notePlane(d, ex); } })
      .catch(function () { if (g === _sessGen) paintSession(null); });
  }

  // The push is not delivering: withdraw the quote instead of leaving the last one on screen
  // (and instead of polling for it -- operator rule 2026-09-23: no fallbacks). The session
  // label is not a live quote and keeps its own slow read.
  function markHeaderPushDown() {
    _pendingQuote = null;
    var connecting = _sse && !_sseUp && (Date.now() - _sseOpenedTs <= 9000);
    paintQuote({ spot: null, spot_disp: null, bid: null, ask: null, chgPct: null,
      spotState: 'unavailable', feedCls: 'stale',
      feedLabel: connecting ? 'WAITING' : 'OFFLINE',
      ageLabel: connecting ? 'no push yet' : 'live push down' });
  }

  // ONE coordinated scheduler. The header quote comes ONLY from the SSE push above; this timer
  // checks that the push is still delivering and drives the SLOW gamma/terrain refresh -- that
  // producer changes on a 60s/5min cadence, so coordinated POLLING (not SSE) is the correct,
  // lowest-cost delivery for it. No duplicate subscriptions, no polling storm.
  var _tick = 0;
  function liveTick() {
    _tick++;
    if (!state.ticker) { paintNoTicker(); if (_tick % 4 === 0) pollWatchlistQuotes(); return; }
    var sseHealthy = _sseUp && (Date.now() - _lastSseTs <= 9000);
    if (!sseHealthy) markHeaderPushDown();            // the gap is shown, never filled
    if (!sseHealthy || _tick % 4 === 0) refreshSession();
    if (_tick % 4 === 0) pollWatchlistQuotes();       // every non-active row, same slow cadence
    emit('ed:refresh', { tick: _tick, slow: _tick % 4 === 0 });
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
    setInterval(liveTick, 3000);   // single scheduler drives header (fast) + gamma (slow)
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
    addSymbol: addSymbol, removeSymbol: removeSymbol, setWorkspace: setWorkspace, setStrike: setStrike,
    setTheme: applyTheme,
    setScope: setScope, getScope: function () { return state.scope; },
    scopeRows: scopeRows, scopeSelect: scopeSelect, scopeNote: scopeNote, asOfBadge: asOfBadge, fmtAge: fmtAge,
    setExpiry: setExpiry, getExpiry: function () { return state.expiryFilter; },
    setMeasure: setMeasure, getMeasure: function () { return state.measure; },
    getPlane: function () { return Object.assign({}, _plane); },
    setMaximize: applyMaximize, toggleMaximize: toggleMaximize };
})();
