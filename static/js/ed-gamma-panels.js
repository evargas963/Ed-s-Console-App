/* Ed Console — Options/Gamma supporting panels (RC-UI-1). PRESENTATION ONLY.
   Key Levels rail  <- GET /api/terrain      (canonical levels SSOT)
   GEX by Strike    <- GET /api/terrain/strikes  (per-strike net_gex_1pct$)
   Strike Detail    <- GET /api/chain         (vendor per-contract OI/vol/greeks)
   No trading semantics are computed here. Bar scaling is visual normalisation over the
   already-computed displayed values; distances/positions are formatting only. */
(function () {
  'use strict';

  var usd = (window.EdGamma && window.EdGamma.formatUsd) || function (n) {
    if (n == null || isNaN(n)) return '';
    var a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'K';
    return s + '$' + a.toFixed(0);
  };
  function px(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function txt(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  function isGamma() {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && s.subview === 'gamma';
  }
  function ticker() { return ((window.EdShell && window.EdShell.getState()) || {}).ticker || 'SPY'; }

  var REGIME = {
    LONG_GAMMA_CHOP: { t: 'Long γ · chop', c: 'var(--ed-pos-ink)' },
    SHORT_GAMMA_TREND: { t: 'Short γ · trend', c: 'var(--ed-warn)' },
    SIGN_UNPROVEN: { t: 'sign unproven', c: 'var(--ed-ink-3)' },
    UNAVAILABLE: { t: 'unavailable', c: 'var(--ed-ink-3)' },
  };

  // ---------- Key Levels rail ----------
  var _lgen = 0;
  function loadLevels() {
    if (!isGamma() || !document.getElementById('klSpot')) return;
    var g = ++_lgen, tk = ticker();
    fetch('/api/terrain?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _lgen) renderLevels(d); })
      .catch(function () { if (g === _lgen) renderLevels(null); });
  }
  function renderLevels(d) {
    var ids = ['klSpot', 'klFlip', 'klCall', 'klPut', 'klAbs', 'klPeak', 'klNet', 'klRegime'];   // klPcr: analytics plane, own reader below
    if (!d || d.error) {
      ids.forEach(function (id) { txt(id, '—'); });
      txt('klSrc', d && d.error ? 'terrain not ready' : 'offline');
      return;
    }
    txt('klSpot', px(d.spot));
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
        src.textContent = 'STALE ' + (d.levels_age_sec != null ? Math.round(d.levels_age_sec) + 's' : '') +
          (d.levels_stale_reason ? ' · ' + d.levels_stale_reason : '');
        src.style.color = 'var(--ed-stale)';
      } else {
        src.textContent = 'terrain · live';
        src.style.color = '';
      }
      // #5: terrain levels are AGGREGATE across expiries; if the workspace filters to one expiry,
      // disclose that these levels are still all-exp (never silently relabel them as selected-expiry).
      if (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) src.textContent += ' · all-exp';
    }
  }

  // ---------- Put/Call OI ratio (Key Levels · Exposure) <- GET /api/analytics/state ----------
  // Canonical producer: server._fetch_state -> build_totals_rows(...)[0].pcr_oi, the CONSENSUS window
  // = put OI / call OI over EVERY strike of the SELECTED-EXPIRY chain (contracts_use), served as
  // `pcr_val` beside `selected_exp`. That pair is read here so the expiry the ratio is scoped to is
  // always disclosed; the lightweight plane's bare pcr_val carries no expiry and is not used.
  // CACHE IDENTITY = ticker + expiry-filter + the bundle's CANONICAL generation, never wall-clock:
  //   * `analytics_version` — the Tier C bundle's own generation, which the shell already receives
  //     on its slow /api/live/state read (analytics_lightweight.analytics_version; EdShell.getPlane).
  //     Tier C state is keyed by (ticker, expiry) and the generation is PER ENTRY, so the plane read
  //     carries the same expiry context as the PCR read (/api/live/state?ticker=X&expiry=E resolves
  //     entry (X,E); no expiry -> the newest entry for X, the same rule /api/analytics/state uses
  //     without expiry) and a generation is compared ONLY when the plane record names this exact
  //     context. Same generation -> no re-read. New generation -> one re-read. This is what actually
  //     moves the value (a recompute over a re-fetched chain carrying the day's OI publication).
  //   * `session_label` — the canonical market-session state on the same read. A session
  //     transition (e.g. Closed -> Pre-Market on the next trading day) re-reads once, which also
  //     schedules the Tier C recompute when no other viewer has kept it warm; the generation
  //     advance that follows lands the fresh value through the rule above.
  //   * ticker / expiry change -> re-read (new context).
  // While the analytics plane is warming (pending shell) the bounded re-read rides the slow tick.
  // /api/analytics/state is cache-first (stale-while-refresh); this never polls it per tick.
  var _pcrGen = 0, _pcrKey = null, _pcrPending = false, _pcrTries = 0, PCR_MAX_TRIES = 10;
  var _pcrVer = null, _pcrSession = null;        // identity of the value currently displayed
  function expiryFilter() { return (window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry()) || ''; }
  function plane() { return (window.EdShell && window.EdShell.getPlane && window.EdShell.getPlane()) || {}; }
  function paintPcr(v, scope) {
    txt('klPcr', v == null ? '—' : Number(v).toFixed(2));   // formatting only
    txt('klPcrScope', scope || '');
  }
  function loadPcr() {
    if (!isGamma() || !document.getElementById('klPcr')) return;
    var tk = ticker(), ex = expiryFilter(), key = tk + '|' + ex, pl = plane();
    var newContext = key !== _pcrKey;
    // the plane's generation counts only when its record was read for THIS (ticker, expiry) context
    var sameCtx = pl.ticker === tk && (pl.expiry || '') === ex;
    var newGen = sameCtx && pl.analyticsVersion != null && _pcrVer != null && pl.analyticsVersion !== _pcrVer;
    var newSession = pl.session != null && _pcrSession != null && pl.session !== _pcrSession;
    var retry = _pcrPending && _pcrTries < PCR_MAX_TRIES;
    if (!newContext && !newGen && !newSession && !retry) return;   // same identity: no redundant re-read
    if (newContext) { _pcrKey = key; _pcrTries = 0; _pcrPending = false; _pcrVer = null; _pcrSession = null; paintPcr(null, 'warming'); }
    if (newGen || newSession) { _pcrTries = 0; }
    _pcrTries++;
    var g = ++_pcrGen;
    fetch('/api/analytics/state?ticker=' + encodeURIComponent(tk) + (ex ? '&expiry=' + encodeURIComponent(ex) : ''), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (g !== _pcrGen) return;
        // the identity this response answers for: its own generation (falls back to the plane's
        // when the response carries none) and the session it was read under
        var pn = plane(), pnSame = pn.ticker === tk && (pn.expiry || '') === ex;
        _pcrVer = (d.analytics_version != null) ? d.analytics_version : (pnSame && pn.analyticsVersion != null ? pn.analyticsVersion : null);
        _pcrSession = pn.session != null ? pn.session : null;
        if (d.state_error) { _pcrPending = false; paintPcr(null, 'analytics error'); return; }
        if (d.analytics_pending_shell) { _pcrPending = true; paintPcr(null, 'warming'); return; }
        _pcrPending = false;
        if (d.pcr_val == null) { paintPcr(null, 'unavailable'); return; }
        paintPcr(d.pcr_val, 'OI · exp ' + (d.selected_exp || '—'));
      })
      .catch(function () { if (g === _pcrGen) { _pcrPending = true; paintPcr(null, 'offline'); } });
  }

  // ---------- GEX by Strike ----------
  var _ggen = 0;
  function loadGbs() {
    var host = document.getElementById('gbsBody');
    if (!isGamma() || !host) return;
    var g = ++_ggen, tk = ticker();
    fetch('/api/terrain/strikes?ticker=' + encodeURIComponent(tk), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _ggen) renderGbs(host, d); })
      .catch(function () { if (g === _ggen) renderGbs(host, null); });
  }
  var SRC_LABEL = { terrain_live_cache: 'terrain live' };
  function srcLabel(s) {
    if (!s) return '';
    if (SRC_LABEL[s]) return SRC_LABEL[s];
    if (s.indexOf('accrual_bank') === 0) return 'accrual bank';
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
          live: (d.today_source === 'terrain_live_cache' && !d.levels_stale) })
      : '';
  }
  var _lastGbs = { rows: [], spot: null };
  function gbsNetAt(strike) {   // canonical per-strike net GEX$ (from /api/terrain/strikes), for reuse
    for (var i = 0; i < _lastGbs.rows.length; i++) {
      if (Math.abs(Number(_lastGbs.rows[i][0]) - Number(strike)) < 0.01) return Number(_lastGbs.rows[i][1]);
    }
    return null;
  }
  function renderGbs(host, d) {
    setGbsAsOf(d);
    _lastGbs = { rows: (d && d.today && d.today.all) || [], spot: Number(d && d.spot) };
    var rows = d && d.today && d.today.all;
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        (d ? 'no banked per-strike gamma for this symbol' : 'no console serving /api/terrain/strikes') + '</div></div>';
      return;
    }
    var spot = Number(d.spot);
    // #3: window around spot for readability (presentation), high strikes on top. The window is the
    // ONE shared Gamma scope (Auto ±6% / Wider / All available); `rows` is the current canonical
    // input, so the disclosure below states exactly how many of them are on screen vs clipped.
    var GBS_BASE = 0.06;
    var frac = (window.EdShell && window.EdShell.scopeWindow) ? window.EdShell.scopeWindow(GBS_BASE) : GBS_BASE;
    var win = rows.filter(function (r) { return (isFinite(spot) && isFinite(frac)) ? Math.abs(r[0] - spot) <= spot * frac : true; })
      .sort(function (a, b) { return b[0] - a[0]; });
    var note = (window.EdShell && window.EdShell.scopeNote)
      ? window.EdShell.scopeNote({ base: GBS_BASE, total: rows.length, shown: win.length, spot: spot }) : '';
    // #5: /api/terrain/strikes is aggregate across expiries; if the workspace filters to one expiry,
    // disclose that this ladder is still all-exp (per-expiry GEX-by-strike is not canonical here).
    var expOn = window.EdShell && window.EdShell.getExpiry && window.EdShell.getExpiry();
    if (expOn) note += '<div class="gbs-allexp">ALL-EXP terrain · per-expiry GEX-by-strike not canonical here</div>';
    var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
    var spotStrike = win.reduce(function (best, r) {
      return (best == null || Math.abs(r[0] - spot) < Math.abs(best - spot)) ? r[0] : best; }, null);
    var bars = '';
    win.forEach(function (r) {
      var k = r[0], v = Number(r[1]) || 0, w = Math.min(100, Math.abs(v) / maxAbs * 100);
      var pos = v >= 0;
      bars += '<div class="gbs-row' + (k === spotStrike ? ' spot' : '') + '" data-strike="' + k + '">' +
        '<span class="gbs-k">' + px(k, k % 1 ? 2 : 0) + '</span>' +
        '<span class="gbs-track"><i class="gbs-bar ' + (pos ? 'pos' : 'neg') + '" style="width:' + w.toFixed(1) + '%"></i></span>' +
        '<span class="gbs-v ' + (pos ? 'pos' : 'neg') + '">' + usd(v) + '</span></div>';
    });
    // the bars scroll in their own area; the -/0/+ magnitude axis is PINNED at the foot so it is
    // always visible without scrolling (reference behaviour).
    host.innerHTML = '<div class="gbs-top">' + note + '</div>' +
      '<div class="gbs-scroll"><div class="gbs">' + bars + '</div></div>' +
      '<div class="gbs-scale"><span class="neg">−' + usd(maxAbs) + '</span><span>0</span><span class="pos">+' + usd(maxAbs) + '</span></div>';
    host.querySelectorAll('.gbs-row').forEach(function (rr) {   // A: click a strike -> sync all panels
      rr.addEventListener('click', function () { if (window.EdShell) window.EdShell.setStrike(Number(rr.getAttribute('data-strike'))); });
    });
    applyGbsHighlight(host);
    var sr = host.querySelector('.gbs-row.spot');
    if (sr && sr.scrollIntoView) sr.scrollIntoView({ block: 'center' });
  }
  function applyGbsHighlight(host) {
    host = host || document.getElementById('gbsBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.gbs-row.gbs-sel').forEach(function (n) { n.classList.remove('gbs-sel'); });
    if (sel == null) return;
    host.querySelectorAll('.gbs-row[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('gbs-sel'); });
  }

  // ---------- Strike Detail ----------
  var _sgen = 0, _lastExpiry = null;
  function loadStrike(strike, expiry) {
    var host = document.getElementById('sdBody');
    if (!host) return;
    var g = ++_sgen, tk = ticker();
    var q = '/api/chain?ticker=' + encodeURIComponent(tk) + (expiry ? '&expiry=' + encodeURIComponent(expiry) : '');
    fetch(q, { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (g === _sgen) renderStrike(host, d, strike, expiry); })
      .catch(function () { if (g === _sgen) host.innerHTML = '<div class="placeholder"><div class="sm">no console serving /api/chain</div></div>'; });
  }
  var SCOPE_LABEL = {
    complete_single_expiry: { t: 'vendor · complete (ALL)', live: true },
    expiry_scope_mismatch: { t: 'vendor · expiry mismatch', ref: true },
    persisted_complete_capture_fallback: { t: 'vendor · captured', ref: true },
    stored_analytical_snapshot_fallback: { t: 'vendor · analytical (not complete)', ref: true },
  };
  function setSdAsOf(d) {
    var el = document.getElementById('sdSrc'); if (!el) return;
    var sc = d && d.scope, kind = sc && sc.kind;
    if (!kind) { el.innerHTML = ''; return; }
    var m = SCOPE_LABEL[kind] || { t: kind };
    // captured_age_sec is the server's own age for the fallback tiers; a live fetch has no age.
    el.innerHTML = (window.EdShell && window.EdShell.asOfBadge)
      ? window.EdShell.asOfBadge({ label: m.t, ageSec: (sc.captured_age_sec != null ? sc.captured_age_sec : null),
          live: !!m.live, ref: !!m.ref, title: 'chain scope: ' + kind })
      : '';
  }
  function renderStrike(host, d, strike, expiry) {
    setSdAsOf(d);
    var cs = (d && d.contracts) || [];
    if (!cs.length) { host.innerHTML = '<div class="placeholder"><div class="sm">no chain for this expiry</div></div>'; return; }
    function pick(side) {
      return cs.filter(function (c) {
        return (c.putCall || '').toUpperCase() === side &&
          Math.abs(Number(c.strikePrice) - Number(strike)) < 0.01; })[0];
    }
    var call = pick('CALL'), put = pick('PUT');
    txt('sdCtx', px(strike, strike % 1 ? 2 : 0) + (expiry ? ' · ' + esc(expiry.slice(5)) : ''));
    function cell(c, k, d2) { var v = c ? c[k] : null; return (v == null) ? '—' : (typeof v === 'number' ? v.toFixed(d2 == null ? 2 : d2) : esc(v)); }
    // GEX ($) column: per-side GEX$ is NOT canonical from /api/chain (computing it would be frontend
    // math) -> "—"; the NET row's GEX is the canonical per-strike net_gex_1pct$ from /api/terrain/strikes.
    var net = gbsNetAt(strike);
    var netCls = net == null ? '' : (net >= 0 ? 'pos' : 'neg');
    host.innerHTML =
      '<table class="sd"><thead><tr><th>Type</th><th>OI</th><th>Vol</th><th>Gamma</th><th>GEX $</th><th>Delta</th><th>IV%</th></tr></thead><tbody>' +
      '<tr><td class="side c">Call</td><td>' + cell(call, 'openInterest', 0) + '</td><td>' + cell(call, 'totalVolume', 0) +
      '</td><td>' + cell(call, 'gamma', 4) + '</td><td class="dim">—</td><td>' + cell(call, 'delta', 3) + '</td><td>' + cell(call, 'volatility', 1) + '</td></tr>' +
      '<tr><td class="side p">Put</td><td>' + cell(put, 'openInterest', 0) + '</td><td>' + cell(put, 'totalVolume', 0) +
      '</td><td>' + cell(put, 'gamma', 4) + '</td><td class="dim">—</td><td>' + cell(put, 'delta', 3) + '</td><td>' + cell(put, 'volatility', 1) + '</td></tr>' +
      '<tr class="sd-net"><td class="side">Net</td><td>—</td><td>—</td><td>—</td><td class="' + netCls + '">' +
      (net == null ? '—' : usd(net)) + '</td><td>—</td><td>—</td></tr>' +
      '</tbody></table><div class="sd-src">vendor per-contract · /api/chain · net GEX$ · /api/terrain/strikes</div>';
  }

  // ---------- events ----------
  function loadAll() { loadLevels(); loadGbs(); loadPcr(); }   // loadPcr is a no-op unless its context changed or it is still warming
  document.addEventListener('ed:ticker', loadAll);
  document.addEventListener('ed:expiry', loadPcr);   // the ratio is scoped to the selected expiry -> re-read for the new context
  document.addEventListener('ed:plane', loadPcr);    // the bundle generation or the market session changed -> identity check
  document.addEventListener('ed:view', loadAll);
  document.addEventListener('ed:scope', loadGbs);   // #3: re-window the GEX-by-strike panel only
  document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) loadAll(); });
  document.addEventListener('ed:strike', function (e) {
    var det = e.detail || {}; _lastExpiry = det.expiry || _lastExpiry;
    applyGbsHighlight();                       // A: sync the GEX-by-strike highlight
    if (det.strike != null) loadStrike(det.strike, det.expiry);
  });
  document.addEventListener('ed:expiry', function (e) {   // #5: expiry filter -> Strike Detail uses it; Levels/GBS stay aggregate + disclose
    var exp = (e.detail && e.detail.expiry) || null;
    loadLevels(); loadGbs();
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    if (sel != null) loadStrike(sel, exp || _lastExpiry);
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadAll);
  else loadAll();
})();
