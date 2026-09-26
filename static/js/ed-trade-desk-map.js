/* Ed Console — Trade Desk / "Desk" subview (the operator's 2026-09-25 mockup). PRESENTATION ONLY.

   One page for the SELECTED ticker, one global timeframe:
     MARKET MAP   <- /api/bars1m (server-rolled timeframe + the server's forming bar),
                     /api/levels (value area, VWAP + bands, prior day, opening range, overnight),
                     /api/terrain (call/put wall, gamma flip, max pain -- full chain)
     ATTENTION    <- /api/level_crosses (numbered on the chart, linked both ways),
                     /api/terrain wall states, /api/order-flow/microstructure wall candidates
     CARDS        <- /api/order-flow/microstructure, /api/terrain, /api/analytics/state (pcr_val),
                     /api/liquidity-snapshot (value/VWAP relation)
     HEADER TRUST <- the same responses' own state/age fields
   The browser computes nothing: it picks which served values to show, formats them, and
   places a served event on the bar that contains it. A value with no producer yet says so. */
(function () {
  'use strict';

  var TFS = [{ id: '1', lbl: '1m' }, { id: '5', lbl: '5m' }, { id: '15', lbl: '15m' },
    { id: '30', lbl: '30m' }, { id: '60', lbl: '1h' }, { id: 'D', lbl: 'D' }];
  // 1m rows fetched per timeframe (the server rolls them up), and the tail re-read on each tick:
  // two whole buckets, so the bar before the forming one is always complete.
  var FULL_LIMIT = { '1': 1200, '5': 3000, '15': 6000, '30': 9000, '60': 12000, 'D': 12000 };
  var TAIL_LIMIT = { '1': 5, '5': 15, '15': 35, '30': 65, '60': 125, 'D': 2000 };
  // The ONE global timeframe also sets how far back the queue and the event markers reach.
  var LOOKBACK = { '1': { s: 900, lbl: 'last 15 min' }, '5': { s: 3600, lbl: 'last 1 h' },
    '15': { s: 14400, lbl: 'last 4 h' }, '30': { s: 'session', lbl: 'this session' },
    '60': { s: 172800, lbl: 'last 2 days' }, 'D': { s: 1728000, lbl: 'last 20 days' } };
  var FAMILIES = [
    { id: 'value_area', lbl: 'Value area' }, { id: 'vwap', lbl: 'VWAP' }, { id: 'gamma', lbl: 'Gamma' },
    { id: 'prior_day', lbl: 'Prior day' }, { id: 'opening_range', lbl: 'Opening range' }, { id: 'overnight', lbl: 'Overnight' }];
  var SHORT = { TODAY_VAH: 'VAH', TODAY_VAL: 'VAL', TODAY_POC: 'POC', PDH: 'PDH', PDL: 'PDL', PDC: 'PDC',
    PD_POC: 'pPOC', PD_VAH: 'pVAH', PD_VAL: 'pVAL', ORB_HIGH: 'ORH', ORB_LOW: 'ORL', ORB_MID: 'ORM',
    OVERNIGHT_HIGH: 'ONH', OVERNIGHT_LOW: 'ONL' };
  var DRILL = { liquidity: ['order-flow', 'heatmap'], flow: ['order-flow', 'book'],
    options: ['options', 'gamma'], vol: ['options', 'chain'] };
  var CT_HM = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit', hour12: false });
  var CT_DAYKEY = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Chicago' });
  var CT_MD = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', month: 'short', day: 'numeric' });

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function num(n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 2 : d); }
  function usd(n) {
    if (n == null || isNaN(n)) return '—';
    var a = Math.abs(n), s = n < 0 ? '−' : '+';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    return s + '$' + a.toFixed(0);
  }
  function fmtVol(n) {
    if (n == null || isNaN(n)) return '—';
    var a = Math.abs(Number(n));
    if (a >= 1e6) return (a / 1e6).toFixed(2) + 'M';
    if (a >= 1e3) return (a / 1e3).toFixed(1) + 'K';
    return String(Math.round(a));
  }
  function age(sec) {
    if (sec == null || isNaN(sec)) return '—';
    sec = Math.max(0, Number(sec));
    if (sec < 90) return Math.round(sec) + 's';
    if (sec < 5400) return Math.round(sec / 60) + 'm';
    if (sec < 172800) return (sec / 3600).toFixed(1) + 'h';
    return Math.round(sec / 86400) + 'd';
  }
  function whenCT(ts) {
    var d = new Date(ts * 1000);
    return (CT_DAYKEY.format(d) === CT_DAYKEY.format(new Date()) ? '' : CT_MD.format(d) + ' ') + CT_HM.format(d);
  }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function onDesk() { var s = st(); return s.workspace === 'trade-desk' && s.subview === 'desk'; }
  function bare(t) { return String(t || '').toUpperCase().replace(/^\$/, ''); }
  function $(id) { return document.getElementById(id); }
  function fetchJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  function sget(k, d) { try { var v = window.localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function sset(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* per-viewer only */ } }

  var S = {
    tf: sget('ed.desk.tf', '5'), nearest: Number(sget('ed.desk.nearest', '6')) || 6,
    fam: (function () { try { return JSON.parse(sget('ed.desk.fam', 'null')) || null; } catch (e) { return null; } })() ||
      { value_area: 1, vwap: 1, gamma: 1, prior_day: 1, opening_range: 1, overnight: 1 },
    ticker: null, gen: 0, chart: null, bars: [], levels: null, terrain: null, micro: null, crosses: null,
    analytics: null, liq: null, quotes: {}, lastTail: 0, tailBusy: false, queue: [], sel: null
  };

  // ------------------------------------------------------------------ layout wiring
  function buildToolbar() {
    var tb = $('tdmToolbar'); if (!tb || tb.getAttribute('data-built')) return;
    tb.setAttribute('data-built', '1');
    tb.innerHTML =
      '<div class="tdm-tfs">' + TFS.map(function (t) {
        return '<button type="button" class="tdm-tb" data-tf="' + t.id + '">' + t.lbl + '</button>'; }).join('') + '</div>' +
      '<span class="tdm-sep"></span>' +
      '<button type="button" class="tdm-tb tdm-tool on" data-tool="cursor" title="Crosshair (Esc)">&#10010;</button>' +
      '<button type="button" class="tdm-tb tdm-tool" data-tool="hline" title="Horizontal line (Alt+H)">&#8212;</button>' +
      '<button type="button" class="tdm-tb tdm-tool" data-tool="trend" title="Trend line (Alt+T)">&#8725;</button>' +
      '<button type="button" class="tdm-tb" data-act="undo" title="Undo drawing (Ctrl+Z)">&#8630;</button>' +
      '<button type="button" class="tdm-tb" data-act="clear" title="Remove all drawings">&#10005;</button>' +
      '<span class="tdm-sep"></span>' +
      '<label class="tdm-nsel" title="How many key levels to draw (nearest to price, inside the visible range)">Levels ' +
        '<select id="tdmNearest">' + [3, 4, 6, 8, 12, 99].map(function (n) {
          return '<option value="' + n + '"' + (n === S.nearest ? ' selected' : '') + '>' + (n === 99 ? 'All' : n) + '</option>'; }).join('') +
        '</select></label>' +
      '<span class="tdm-grow"></span>' +
      '<button type="button" class="tdm-tb" data-act="reset" title="Reset chart (Alt+R)">&#10227;</button>' +
      '<button type="button" class="tdm-tb" data-act="shot" title="Save a PNG of the chart">&#128247;</button>' +
      '<button type="button" class="tdm-tb" data-act="full" title="Full screen">&#9974;</button>';
    tb.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b || !S.chart) return;
      if (b.hasAttribute('data-tf')) { setTf(b.getAttribute('data-tf')); return; }
      if (b.hasAttribute('data-tool')) { S.chart.setTool(b.getAttribute('data-tool')); return; }
      var a = b.getAttribute('data-act');
      if (a === 'undo') S.chart.undo();
      else if (a === 'clear') S.chart.clearDrawings();
      else if (a === 'reset') S.chart.resetAll();
      else if (a === 'shot') S.chart.screenshot();
      else if (a === 'full') S.chart.fullscreen();
    });
    $('tdmNearest').addEventListener('change', function (e) {
      S.nearest = Number(e.target.value) || 6; sset('ed.desk.nearest', String(S.nearest));
      if (S.chart) S.chart.setNearestN(S.nearest);
    });
    var fam = $('tdmFamilies');
    fam.innerHTML = FAMILIES.map(function (f) {
      return '<button type="button" class="tdm-fam fam-' + f.id + '" data-fam="' + f.id + '"><i></i>' + f.lbl + '</button>'; }).join('');
    fam.addEventListener('click', function (e) {
      var b = e.target.closest('[data-fam]'); if (!b) return;
      var id = b.getAttribute('data-fam'); S.fam[id] = S.fam[id] ? 0 : 1;
      sset('ed.desk.fam', JSON.stringify(S.fam)); paintFamilies(); paintChartLevels();
    });
    paintFamilies(); paintTfButtons();
  }
  function paintFamilies() {
    document.querySelectorAll('#tdmFamilies [data-fam]').forEach(function (b) {
      b.classList.toggle('on', !!S.fam[b.getAttribute('data-fam')]); });
  }
  function paintTfButtons() {
    document.querySelectorAll('#tdmToolbar [data-tf]').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-tf') === S.tf); });
    var lb = $('tdmLookback'); if (lb) lb.textContent = LOOKBACK[S.tf].lbl;
  }
  function ensureChart() {
    if (S.chart) return S.chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    S.chart = window.EdTvChart.create($('tdmChart'), { nearestN: S.nearest, fullscreenEl: $('tdmMap'),
      onTool: function (t) { document.querySelectorAll('#tdmToolbar [data-tool]').forEach(function (b) {
        b.classList.toggle('on', b.getAttribute('data-tool') === t); }); } });
    document.querySelectorAll('[data-drill]').forEach(function (el) {
      el.addEventListener('click', function () {
        var d = DRILL[el.getAttribute('data-drill')]; if (!d || !window.EdShell) return;
        window.EdShell.setWorkspace(d[0]);
        if (window.EdShell.setSubview) window.EdShell.setSubview(d[1]);
      });
    });
    return S.chart;
  }
  function setTf(tf) {
    if (tf === S.tf) return;
    S.tf = tf; sset('ed.desk.tf', tf); paintTfButtons();
    loadBars(true); paintQueue();
  }

  // ------------------------------------------------------------------ data
  function loadBars(full) {
    var tk = S.ticker, tf = S.tf, gen = S.gen;
    var lim = full ? FULL_LIMIT[tf] : TAIL_LIMIT[tf];
    return fetchJson('/api/bars1m?ticker=' + encodeURIComponent(tk) + '&tf=' + tf + '&limit=' + lim).then(function (d) {
      if (gen !== S.gen || tf !== S.tf || !S.chart) return;
      var bars = (d && d.bars) || [];
      if (full) {
        S.bars = bars;
        S.chart.setBars(bars, tf, bare(tk));
        $('tdmChartEmpty').hidden = bars.length > 0;
        $('tdmChartEmpty').textContent = bars.length ? '' : (!d ? 'The bars request failed for ' + bare(tk) + ' (' + (TFS.filter(function (x) { return x.id === tf; })[0] || {}).lbl + ').'
          : 'No bars for ' + bare(tk) + (d.error ? ' — ' + d.error : ' — nothing banked or streamed for this symbol yet.'));
        paintChartOverlays(); paintQueue();
        var src = $('tdmBarsSrc'); if (src) src.textContent = 'streamed 1m bars';
      } else if (bars.length) {
        S.chart.updateTail(bars.slice(-2));
      }
    });
  }
  function loadSlow() {
    var tk = S.ticker, gen = S.gen, q = encodeURIComponent(tk);
    return Promise.all([
      fetchJson('/api/levels?ticker=' + q),
      fetchJson('/api/terrain?ticker=' + q),
      fetchJson('/api/level_crosses?ticker=' + q + '&n=200'),
      fetchJson('/api/analytics/state?ticker=' + q + '&_via=desk'),
      fetchJson('/api/liquidity-snapshot?ticker=' + q + '&snapshot=live')
    ]).then(function (r) {
      if (gen !== S.gen) return;
      S.levels = r[0]; S.terrain = r[1]; S.crosses = r[2]; S.analytics = r[3]; S.liq = r[4];
      paintChartOverlays(); paintQueue(); paintCards(); paintTrust(); paintAgreement(); paintFooter();
    });
  }
  function loadFast() {
    var tk = S.ticker, gen = S.gen;
    return fetchJson('/api/order-flow/microstructure?ticker=' + encodeURIComponent(tk)).then(function (d) {
      if (gen !== S.gen) return;
      S.micro = d; paintCards(); paintTrust(); paintQueue(); paintAgreement(); paintFooter();
    });
  }

  // ------------------------------------------------------------------ chart overlays
  function levelList() {
    var P = S.chart.palette(), out = [];
    var style = { value_area: [P.accent2, 2, 1], prior_day: [P.ink3, 1, 1], opening_range: [P.stale, 2, 1], overnight: [P.research, 2, 1] };
    ((S.levels && S.levels.levels) || []).forEach(function (l) {
      var s = style[l.family]; if (!s || !S.fam[l.family] || l.price == null) return;
      out.push({ id: l.id, price: Number(l.price), label: SHORT[l.id] || l.label || l.id, color: s[0], style: s[1], width: s[2] });
    });
    var t = S.terrain;
    if (t && !t.error && S.fam.gamma) {
      [['call_wall', 'Call wall', P.up, 0, 2], ['put_wall', 'Put wall', P.down, 0, 2],
        ['gamma_flip', 'γ flip', P.accent, 0, 2], ['max_pain', 'Max pain', P.ink3, 3, 1]].forEach(function (g) {
        if (t[g[0]] != null) out.push({ id: g[0], price: Number(t[g[0]]), label: g[1], color: g[2], style: g[3], width: g[4] });
      });
    }
    return out;
  }
  function paintChartLevels() {
    if (!S.chart) return;
    S.chart.setLevels(levelList());
    var L = (S.levels && S.levels.levels) || [], vah = null, val = null;
    L.forEach(function (l) { if (l.id === 'TODAY_VAH') vah = l.price; if (l.id === 'TODAY_VAL') val = l.price; });
    S.chart.setValueArea(S.fam.value_area ? val : null, S.fam.value_area ? vah : null);
    S.chart.setVwap(S.fam.vwap && S.levels ? S.levels.vwap_series : []);
  }
  function paintChartOverlays() {
    if (!S.chart || !S.bars.length) return;
    paintChartLevels();
    var P = S.chart.palette();
    // the newest 40 events are drawn (the queue lists every one); a 20-day daily chart would
    // otherwise carry hundreds of dots on thirty candles
    S.chart.setMarkers(queueItems().filter(function (q) { return q.marker; }).slice(0, 40).map(function (q) {
      return { id: q.key, time: q.ts, text: String(q.n), color: q.dir === 'up' ? P.up : q.dir === 'down' ? P.down : P.accent2,
        position: q.dir === 'down' ? 'aboveBar' : 'belowBar', shape: 'circle', meta: q.key };
    }), function (key) { selectItem(key, false); });
  }

  // ------------------------------------------------------------------ attention queue
  function windowStart() {
    var lb = LOOKBACK[S.tf].s;
    if (lb === 'session') {
      var last = S.bars.length ? S.bars[S.bars.length - 1].t : Date.now() / 1000;
      var day = CT_DAYKEY.format(new Date(last * 1000));
      for (var i = S.bars.length - 1; i >= 0; i--) if (CT_DAYKEY.format(new Date(S.bars[i].t * 1000)) !== day) return S.bars[i + 1].t;
      return S.bars.length ? S.bars[0].t : last - 86400;
    }
    return Date.now() / 1000 - lb;
  }
  function queueItems() {
    var items = [], from = windowStart();
    var cr = ((S.crosses && S.crosses.crosses) || []).filter(function (c) { return c.ts_utc >= from; })
      .sort(function (a, b) { return a.ts_utc - b.ts_utc; });
    cr.forEach(function (c, i) {
      var names = (c.level_names && c.level_names.length ? c.level_names : [c.level_name]).join(' + ');
      items.push({ key: 'x' + c.cross_id, n: i + 1, ts: c.ts_utc, dom: 'LEVELS', dir: c.direction, marker: true,
        title: 'Crossed ' + (c.direction === 'up' ? 'above ' : 'below ') + names,
        detail: num(c.level_value) + ' · spot ' + num(c.spot_at_cross) + (c.zone_after ? ' · zone ' + c.zone_after : ''),
        src: '/api/level_crosses' });
    });
    var t = S.terrain;
    if (t && !t.error) {
      var tts = t.computed_ts_utc || Date.now() / 1000;
      if (t.call_wall_state === 'breached') items.push({ key: 'cw', ts: tts, dom: 'OPTIONS', dir: 'up',
        title: 'Spot through the call wall', detail: 'call wall ' + num(t.call_wall) + ' · spot ' + num(t.spot), src: '/api/terrain' });
      if (t.put_wall_state === 'breached') items.push({ key: 'pw', ts: tts, dom: 'OPTIONS', dir: 'down',
        title: 'Spot through the put wall', detail: 'put wall ' + num(t.put_wall) + ' · spot ' + num(t.spot), src: '/api/terrain' });
      if (t.levels_stale) items.push({ key: 'ls', ts: tts, dom: 'DATA', dir: null, warn: true,
        title: 'Gamma levels are ' + age(t.levels_age_sec) + ' old', detail: t.levels_stale_reason || '', src: '/api/terrain' });
    }
    var m = S.micro;
    if (m && m.wall_candidates && m.wall_candidates.length) {
      m.wall_candidates.slice(0, 3).forEach(function (w, i) {
        items.push({ key: 'wall' + i, ts: (m.provenance && m.provenance.server_received_ts) || Date.now() / 1000, dom: 'LIQUIDITY',
          dir: w.side === 'bid' ? 'up' : 'down',
          title: 'Displayed size wall · ' + (w.side || '') + ' ' + num(w.price),
          detail: fmtVol(w.volume) + ' shown · ' + (w.median_mult != null ? num(w.median_mult, 1) + '× the median level' : 'size outlier'),
          src: '/api/order-flow/microstructure' });
      });
    }
    ((S.analytics && S.analytics.rules_alerts) || []).forEach(function (a, i) {
      items.push({ key: 'ra' + i, ts: Date.now() / 1000, dom: 'RULES', dir: null, title: String(a), detail: '', src: '/api/analytics/state' });
    });
    return items.sort(function (a, b) { return b.ts - a.ts; });
  }
  function paintQueue() {
    var host = $('tdmQueue'); if (!host) return;
    var items = queueItems(); S.queue = items;
    $('tdmQueueCount').textContent = items.length ? String(items.length) : '';
    if (!items.length) {
      host.innerHTML = '<div class="tdm-empty">Nothing in the ' + esc(LOOKBACK[S.tf].lbl) + '. Level crosses, wall breaches, book size walls and rule alerts land here.</div>';
      return;
    }
    host.innerHTML = items.map(function (q) {
      return '<button type="button" class="tdm-q' + (q.key === S.sel ? ' sel' : '') + (q.warn ? ' warn' : '') + '" data-q="' + esc(q.key) + '">' +
        '<span class="tdm-q-n ' + (q.dir === 'up' ? 'up' : q.dir === 'down' ? 'dn' : '') + '">' + (q.n || '•') + '</span>' +
        '<span class="tdm-q-b"><span class="tdm-q-t">' + esc(q.title) + '</span>' +
        '<span class="tdm-q-d">' + esc(q.detail) + '</span>' +
        '<span class="tdm-q-m"><span class="tdm-dom">' + esc(q.dom) + '</span>' + esc(whenCT(q.ts)) + ' CT · ' + esc(q.src) + '</span></span></button>';
    }).join('');
  }
  function selectItem(key, scroll) {
    S.sel = key; paintQueue();
    var el = document.querySelector('#tdmQueue [data-q="' + key + '"]');
    if (el) el.scrollIntoView({ block: 'nearest' });
    var q = S.queue.filter(function (x) { return x.key === key; })[0];
    if (scroll && q && q.marker && S.chart) S.chart.scrollToTime(q.ts);
  }

  // ------------------------------------------------------------------ cards
  function row(k, v, cls) { return '<div class="tdm-r"><span>' + esc(k) + '</span><b class="' + (cls || '') + '">' + v + '</b></div>'; }
  function state(el, txt, cls) { var s = el.querySelector('.tdm-state'); s.textContent = txt; s.className = 'tdm-state ' + (cls || ''); }
  function seriesNote() { return '<div class="tdm-series">1h change · sparkline: not produced yet</div>'; }
  function paintCards() {
    var m = S.micro, t = S.terrain, a = S.analytics;
    // LIQUIDITY — displayed book depth
    var c = $('tdmCardLiq');
    if (c) {
      var d5 = m && m.depth && m.depth['5'];
      if (!m || m.status === 'no_book' || !d5 || d5.imbalance == null) {
        state(c, m && m.status === 'no_book' ? 'NO BOOK' : 'UNAVAILABLE', 'warn');
        c.querySelector('.tdm-hero').innerHTML = '—';
        c.querySelector('.tdm-rows').innerHTML = row('Book source', esc((m && m.provenance && m.provenance.book_source) || 'unavailable')) +
          row('Reason', m && m.status === 'no_book' ? 'no NASDAQ/NYSE book rows for this symbol right now' : m === undefined ? 'loading…' : 'microstructure request failed');
      } else {
        var imb = Number(d5.imbalance);
        state(c, m.ages && m.ages.book_stale ? 'STALE BOOK' : (imb > 0 ? 'BID HEAVY' : imb < 0 ? 'OFFER HEAVY' : 'BALANCED'), m.ages && m.ages.book_stale ? 'warn' : (imb > 0 ? 'up' : imb < 0 ? 'dn' : ''));
        c.querySelector('.tdm-hero').innerHTML = '<span class="' + (imb >= 0 ? 'up' : 'dn') + '">' + (imb >= 0 ? '+' : '') + num(imb * 100, 1) + '%</span><small>depth imbalance · 5 levels</small>';
        c.querySelector('.tdm-rows').innerHTML = row('Bid depth (5)', fmtVol(d5.bid_total)) + row('Ask depth (5)', fmtVol(d5.ask_total)) +
          row('Spread', num(m.spread_pts, 2) + ' pts') + row('Size walls shown', String((m.wall_candidates || []).length)) +
          row('Book age', age(m.ages && m.ages.book_age_sec));
      }
    }
    // ORDER FLOW — trade side by the tick rule (PROXY: Schwab sends no buy/sell flag, so a
    // trade above the previous price counts as bought, below as sold -- the server's
    // OrderFlowEngine), plus where price is being crossed
    c = $('tdmCardFlow');
    if (c) {
      var fl = m && m.flow, tob = m && m.top_of_book;
      var from = windowStart(), cr = ((S.crosses && S.crosses.crosses) || []).filter(function (x) { return x.ts_utc >= from; });
      var up = cr.filter(function (x) { return x.direction === 'up'; }).length, dn = cr.length - up;
      function pct(v) { return v == null ? '—' : '<span class="' + (v > 0 ? 'up' : v < 0 ? 'dn' : '') + '">' + (v > 0 ? '+' : '') + num(v * 100, 0) + '%</span>'; }
      var p5 = fl ? fl.tape_pressure_5m : null;
      state(c, p5 == null ? (m === undefined ? 'LOADING' : 'NO TRADES SEEN') : (p5 > 0 ? 'NET BUYING' : p5 < 0 ? 'NET SELLING' : 'BALANCED'),
        p5 == null ? 'warn' : (p5 > 0 ? 'up' : p5 < 0 ? 'dn' : ''));
      c.querySelector('.tdm-hero').innerHTML = p5 == null ? '—<small>no trades in the tape buffer yet</small>'
        : pct(p5) + '<small>net traded volume, last 5 min (tick rule, PROXY)</small>';
      c.querySelector('.tdm-rows').innerHTML =
        row('Last 30 s · 2 min', (fl ? pct(fl.tape_pressure_30s) : '—') + ' · ' + (fl ? pct(fl.tape_pressure_2m) : '—')) +
        row('Cum. delta (tape buffer)', fl && fl.cum_delta_proxy != null ? (fl.cum_delta_proxy >= 0 ? '+' : '−') + fmtVol(Math.abs(fl.cum_delta_proxy)) + ' sh' : '—') +
        row('Top of book', tob && tob.bid_size != null ? fmtVol(tob.bid_size) + ' × ' + fmtVol(tob.ask_size) : '—') +
        row('Level crosses (' + LOOKBACK[S.tf].lbl + ')', cr.length ? up + ' up · ' + dn + ' down' : '0');
    }
    // OPTIONS POSITIONING — full-chain terrain
    c = $('tdmCardOpt');
    if (c) {
      if (!t || t.error) {
        state(c, t === undefined ? 'LOADING' : 'UNAVAILABLE', t === undefined ? '' : 'warn'); c.querySelector('.tdm-hero').innerHTML = '—';
        c.querySelector('.tdm-rows').innerHTML = row('Reason', t === undefined ? 'loading the full-chain terrain…' : esc((t && t.error) || 'terrain request failed'));
      } else {
        var reg = String(t.regime || '').replace(/_/g, ' ');
        state(c, t.levels_market_closed ? 'AS OF ' + t.levels_as_of : t.levels_stale ? 'STALE ' + age(t.levels_age_sec) : (reg || '—'), t.levels_stale ? 'warn' : (/LONG/.test(t.regime || '') ? 'up' : /SHORT/.test(t.regime || '') ? 'dn' : ''));
        c.querySelector('.tdm-hero').innerHTML = '<span class="' + ((t.net_gex_at_spot || 0) >= 0 ? 'up' : 'dn') + '">' + usd(t.net_gex_at_spot) + '</span><small>net dealer gamma at spot (per 1% move)</small>';
        c.querySelector('.tdm-rows').innerHTML = row('Call wall', num(t.call_wall) + (t.call_wall_state ? ' · ' + esc(t.call_wall_state) : ''), 'up') +
          row('Put wall', num(t.put_wall) + (t.put_wall_state ? ' · ' + esc(t.put_wall_state) : ''), 'dn') +
          row('Gamma flip', num(t.gamma_flip)) + row('Max pain', num(t.max_pain)) +
          row('Put/Call ratio', num(a && a.pcr_val, 2)) +
          row('Chain', esc(t.chain_basis || '—') + ' · ' + (t.contracts_used != null ? t.contracts_used.toLocaleString() : '—') + ' contracts');
      }
    }
    // VOLATILITY
    c = $('tdmCardVol');
    if (c) {
      var im = t && t.implied_1d_move, vix = S.quotes.VIX;
      if (!im || im.iv_pct_atm == null) {
        state(c, t === undefined ? 'LOADING' : 'UNAVAILABLE', t === undefined ? '' : 'warn'); c.querySelector('.tdm-hero').innerHTML = '—';
      } else {
        state(c, 'ATM IV ' + num(im.iv_pct_atm, 1) + '%', '');
        c.querySelector('.tdm-hero').innerHTML = '<span>±' + num(im.points, 2) + '</span><small>implied 1-day move (1σ, pts)</small>';
      }
      c.querySelector('.tdm-rows').innerHTML = row('ATM IV (nearest expiry)', im && im.iv_pct_atm != null ? num(im.iv_pct_atm, 2) + '%' : '—') +
        row('ATR daily', num(t && t.atr_daily)) + row('ATR 15m', num(t && t.atr_15m)) +
        row('VIX', vix && vix.spot != null ? num(vix.spot) + (vix.chg_pct != null ? ' (' + (vix.chg_pct >= 0 ? '+' : '') + num(vix.chg_pct) + '%)' : '') : 'waiting for the VIX stream');
    }
    document.querySelectorAll('#tdmCards .tdm-card').forEach(function (el) {
      if (!el.querySelector('.tdm-series')) el.insertAdjacentHTML('beforeend', seriesNote());
    });
  }

  // ------------------------------------------------------------------ agreement (server labels only)
  function paintAgreement() {
    var host = $('tdmAgree'); if (!host) return;
    var m = S.micro, t = S.terrain, l = S.liq, d5 = m && m.depth && m.depth['5'];
    var cells = [
      ['LIQUIDITY', d5 && d5.imbalance != null ? (d5.imbalance > 0 ? 'Bid heavy' : d5.imbalance < 0 ? 'Offer heavy' : 'Balanced') : 'No book', d5 && d5.imbalance != null ? (d5.imbalance > 0 ? 'up' : 'dn') : ''],
      ['VALUE', l && l.summary ? String(l.summary.value_state || '—').replace(/_/g, ' ') : '—', ''],
      ['VWAP', l && l.summary ? String(l.summary.vwap_relation || '—').replace(/_/g, ' ') : '—', ''],
      ['OPTIONS', t && !t.error ? String(t.posture || t.regime || '—').replace(/_/g, ' ') : '—', ''],
      ['GAMMA', t && !t.error && t.gamma_flip != null && t.spot != null ? (t.spot >= t.gamma_flip ? 'Above flip' : 'Below flip') : '—', t && t.spot >= t.gamma_flip ? 'up' : 'dn']
    ];
    host.innerHTML = cells.map(function (c) {
      return '<div class="tdm-ag"><span>' + c[0] + '</span><b class="' + c[2] + '">' + esc(c[1]) + '</b></div>'; }).join('') +
      '<div class="tdm-ag tdm-ag-note">Each domain\'s own served label. No combined agreement score is produced yet.</div>';
  }

  // ------------------------------------------------------------------ header trust + footer
  function pill(lbl, val, cls, title) { return '<span class="tdm-pill ' + (cls || '') + '" title="' + esc(title || '') + '"><i></i>' + esc(lbl) + ' <b>' + esc(val) + '</b></span>'; }
  function paintTrust() {
    var host = $('tdmTrust'); if (!host) return;
    var q = S.quotes[bare(S.ticker)], t = S.terrain, m = S.micro, L = S.levels;
    var h = '';
    h += q ? pill('PRICE', q.spot_state === 'live' ? 'LIVE' : String(q.spot_state || '—').toUpperCase(), q.spot_state === 'live' ? 'ok' : 'bad', 'daemon price socket')
      : pill('PRICE', 'WAITING', 'warn', 'no price row yet for this symbol');
    h += m === undefined ? pill('BOOK', '…', '') : !m ? pill('BOOK', 'FAILED', 'bad') : m.status === 'no_book' ? pill('BOOK', 'NONE', 'warn', 'no NASDAQ/NYSE book rows')
      : pill('BOOK', m.ages && m.ages.book_stale ? 'STALE' : age(m.ages && m.ages.book_age_sec), m.ages && m.ages.book_stale ? 'bad' : 'ok');
    var la = L && L.snapshot_as_of_ts_utc ? Date.now() / 1000 - L.snapshot_as_of_ts_utc : null;
    h += L === undefined ? pill('LEVELS', '…', '') : !L ? pill('LEVELS', 'FAILED', 'bad') : pill('LEVELS', age(la), (L.degraded && L.degraded.length) ? 'warn' : 'ok', 'session levels snapshot age');
    h += t === undefined ? pill('GAMMA', '…', '') : !t || t.error ? pill('GAMMA', 'DOWN', 'bad', (t && t.error) || 'terrain request failed') : pill('GAMMA', t.levels_stale ? 'STALE ' + age(t.levels_age_sec) : age(t.levels_age_sec), t.levels_stale ? 'warn' : 'ok', t.levels_stale_reason || '');
    host.innerHTML = h;
  }
  function paintFooter() {
    var host = $('tdmFoot'); if (!host) return;
    var t = S.terrain, m = S.micro, L = S.levels;
    host.innerHTML = [
      'Bars: <b id="tdmBarsSrc">' + esc(($('tdmBarsSrc') || {}).textContent || 'banked 1m bars') + '</b>',
      'Book: <b>' + esc((m && m.provenance && m.provenance.book_source) || '—') + '</b>',
      'Levels: <b>' + esc((L && L.bar_source) || '—') + '</b>',
      'Options: <b>' + esc(t && !t.error ? (t.chain_basis || '—') + ' chain · ' + (t.strikes_used || '—') + ' strikes · ' + (t.contracts_used != null ? t.contracts_used.toLocaleString() : '—') + ' contracts' : '—') + '</b>',
      'Clock: <b>Central</b>'
    ].map(function (x) { return '<span>' + x + '</span>'; }).join('');
  }
  // The shell header already carries the symbol, price, change and CT clock; this page adds
  // the index context and the data-trust row beside it.
  function paintHeader() {
    ['SPX', 'NDX', 'VIX'].forEach(function (s) {
      var el = $('tdmIdx' + s); if (!el) return;
      var r = S.quotes[s];
      el.title = r ? '' : 'waiting for the ' + s + ' stream';
      el.innerHTML = '<span>' + s + '</span><b>' + (r && r.spot != null ? num(r.spot) : '—') + '</b>' +
        (r && r.chg_pct != null ? '<em class="' + (r.chg_pct >= 0 ? 'up' : 'dn') + '">' + (r.chg_pct >= 0 ? '+' : '') + num(r.chg_pct) + '%</em>' : '');
    });
  }

  // ------------------------------------------------------------------ lifecycle
  function start() {
    if (!onDesk()) return;
    buildToolbar();
    if (!ensureChart()) return;
    var tk = st().ticker || '';
    if (!tk) return;
    if (tk !== S.ticker) {
      S.ticker = tk; S.gen++; S.bars = []; // undefined = not answered YET (loading); null = the request failed
      S.levels = S.terrain = S.micro = S.crosses = S.analytics = S.liq = undefined; S.sel = null;
      paintHeader(); paintQueue(); paintCards(); paintTrust(); paintAgreement(); paintFooter();
      loadBars(true); loadSlow(); loadFast();
    } else if (!S.bars.length) { loadBars(true); loadSlow(); loadFast(); }
  }
  function init() {
    if (!$('tdmMap')) return;
    document.addEventListener('ed:view', start);
    document.addEventListener('ed:ticker', start);
    document.addEventListener('ed:refresh', function (e) {
      if (!onDesk() || !S.ticker) return;
      loadFast();
      if (e.detail && e.detail.slow) loadSlow();
      if (Date.now() - S.lastTail > 2500) { S.lastTail = Date.now(); loadBars(false); }
    });
    // Every streamed price row: header + indices; the active symbol also re-reads the chart's
    // tail (the server's forming bar) at most once a second.
    window.addEventListener('ed:quote_tick', function (e) {
      var q = e.detail; if (!q || !q.ticker) return;
      S.quotes[bare(q.ticker)] = q;
      if (!onDesk()) return;
      paintHeader();
      if (bare(q.ticker) === bare(S.ticker)) {
        paintTrust();
        if (!S.tailBusy && Date.now() - S.lastTail > 1000 && S.bars.length) {
          S.tailBusy = true; S.lastTail = Date.now();
          loadBars(false).then(function () { S.tailBusy = false; }, function () { S.tailBusy = false; });
        }
      }
    });
    $('tdmQueue').addEventListener('click', function (e) {
      var b = e.target.closest('[data-q]'); if (b) selectItem(b.getAttribute('data-q'), true);
    });
    start();
  }
  // read-only view for tests (e2e) -- never a control surface
  window.EdTradeDeskMap = { state: function () {
    return { ticker: S.ticker, tf: S.tf, bars: S.bars.length, queue: S.queue.map(function (q) { return { key: q.key, n: q.n, marker: !!q.marker, ts: q.ts }; }),
      sel: S.sel, chart: S.chart ? S.chart.state() : null };
  } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
