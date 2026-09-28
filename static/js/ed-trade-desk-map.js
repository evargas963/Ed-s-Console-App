/* Ed Console — Trade Desk / "Desk" subview (the operator's 2026-09-25 mockup). PRESENTATION ONLY.

   One page for the SELECTED ticker, one global timeframe:
     MARKET MAP   <- /api/bars1m (completed Schwab 1m bars, server-rolled timeframe),
                     /api/levels (value area, VWAP + bands, prior day, opening range, overnight),
                     /api/terrain (call/put wall, gamma flip, max pain -- full chain)
     ATTENTION    <- /api/desk/events (served, numbered; on the chart, linked both ways),
                     /api/terrain wall states, /api/order-flow/microstructure wall candidates
     CARDS        <- /api/order-flow/microstructure, /api/terrain (pcr_by_expiry), /api/alerts,
                     /api/liquidity-snapshot (value/VWAP relation)
     HEADER TRUST <- the same responses' own state/age fields
   The browser computes nothing: it picks which served values to show, formats them, and
   places a served event on the bar that contains it. A value with no producer yet says so. */
(function () {
  'use strict';

  var TFS = [{ id: '1', lbl: '1m' }, { id: '3', lbl: '3m' }, { id: '5', lbl: '5m' }, { id: '15', lbl: '15m' },
    { id: '30', lbl: '30m' }, { id: '60', lbl: '1h' }, { id: 'D', lbl: 'D' }];
  // 1m rows fetched per timeframe (the server rolls them up), and the tail re-read on each new
  // completed bar: two whole buckets.
  var FULL_LIMIT = { '1': 1200, '3': 2000, '5': 3000, '15': 6000, '30': 9000, '60': 12000, 'D': 12000 };
  var TAIL_LIMIT = { '1': 5, '3': 9, '5': 15, '15': 35, '30': 65, '60': 125, 'D': 2000 };
  // The ONE global timeframe also sets how far back the queue and the event markers reach.
  // the event window per timeframe is the server's (DESK_LOOKBACK_SEC); these are its words only
  var LOOKBACK = { '1': { lbl: 'last 15 min' }, '3': { lbl: 'last 30 min' }, '5': { lbl: 'last 1 h' }, '15': { lbl: 'last 4 h' },
    '30': { lbl: 'this session' }, '60': { lbl: 'last 2 days' }, 'D': { lbl: 'last 20 days' } };
  var FAMILIES = [
    { id: 'value_area', lbl: 'Value area' }, { id: 'vwap', lbl: 'VWAP' }, { id: 'gamma', lbl: 'Gamma' },
    { id: 'expected_move', lbl: '±1σ move' }, { id: 'prior_day', lbl: 'Prior day' }, { id: 'opening_range', lbl: 'Opening range' },
    { id: 'overnight', lbl: 'Overnight' }];
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
      { value_area: 1, vwap: 1, gamma: 1, expected_move: 1, prior_day: 1, opening_range: 1, overnight: 1 },
    style: sget('ed.desk.style', 'candles'),
    ticker: null, gen: 0, chart: null, bars: [], levels: null, terrain: null, micro: null, crosses: null,
    analytics: null, liq: null, quotes: {}, queue: [], sel: null
  };

  // ------------------------------------------------------------------ layout wiring
  function buildToolbar() {
    var tb = $('tdmToolbar'); if (!tb || tb.getAttribute('data-built')) return;
    tb.setAttribute('data-built', '1');
    tb.innerHTML =
      '<div class="tdm-tfs">' + TFS.map(function (t) {
        return '<button type="button" class="tdm-tb" data-tf="' + t.id + '">' + t.lbl + '</button>'; }).join('') + '</div>' +
      '<span class="tdm-sep"></span>' +
      '<button type="button" class="tdm-tb" data-act="style" id="tdmStyle" title="Candles or line">Line</button>' +
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
      else if (a === 'style') { S.style = S.style === 'line' ? 'candles' : 'line'; sset('ed.desk.style', S.style); paintStyle(); }
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
      var id = b.getAttribute('data-fam'); S.fam[id] = S.fam[id] === 0 ? 1 : 0;   // a family not yet saved is on
      sset('ed.desk.fam', JSON.stringify(S.fam)); paintFamilies(); paintChartLevels();
    });
    paintFamilies(); paintTfButtons(); paintStyle();
  }
  function paintFamilies() {
    document.querySelectorAll('#tdmFamilies [data-fam]').forEach(function (b) {
      b.classList.toggle('on', S.fam[b.getAttribute('data-fam')] !== 0); });
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
    paintStyle();
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
    loadBars(true); loadSlow();   // levels (VWAP per bar) and events are per timeframe
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
        S.chart.setBars(bars, tf, bare(tk), d.last_bar && d.last_bar.label);
        $('tdmChartEmpty').hidden = bars.length > 0;
        $('tdmChartEmpty').textContent = bars.length ? '' : (!d ? 'The bars request failed for ' + bare(tk) + ' (' + (TFS.filter(function (x) { return x.id === tf; })[0] || {}).lbl + ').'
          : 'No bars for ' + bare(tk) + (d.error ? ' — ' + d.error : ' — nothing banked or streamed for this symbol yet.'));
        paintChartOverlays(); paintQueue();
        var src = $('tdmBarsSrc'); if (src) src.textContent = 'streamed 1m bars';
      } else if (bars.length) {
        S.chart.updateTail(bars.slice(-2), d.last_bar && d.last_bar.label);
      }
    });
  }
  function loadSlow() {
    var tk = S.ticker, gen = S.gen, q = encodeURIComponent(tk);
    return Promise.all([
      fetchJson('/api/levels?ticker=' + q + '&tf=' + encodeURIComponent(S.tf)),
      fetchJson('/api/terrain?ticker=' + q),
      fetchJson('/api/desk/events?ticker=' + q + '&venue=' + st().bookVenue + '&tf=' + encodeURIComponent(S.tf)),
      fetchJson('/api/liquidity-snapshot?ticker=' + q + '&snapshot=live'),
      fetchJson('/api/terrain/strikes?ticker=' + q),
      fetchJson('/api/forces?ticker=' + q)
    ]).then(function (r) {
      if (gen !== S.gen) return;
      S.levels = r[0]; S.terrain = r[1]; S.events = r[2]; S.liq = r[3]; S.strikes = r[4]; S.forces = r[5];
      paintChartOverlays(); paintQueue(); paintCards(); paintTrust(); paintAgreement(); paintFooter();
    });
  }
  function loadFast() {
    var tk = S.ticker, gen = S.gen;
    return fetchJson('/api/order-flow/microstructure?ticker=' + encodeURIComponent(tk) + '&venue=' + st().bookVenue).then(function (d) {
      if (gen !== S.gen) return;
      S.micro = d; paintCards(); paintTrust(); paintQueue(); paintAgreement(); paintFooter();
    });
  }

  // ------------------------------------------------------------------ chart overlays
  function levelList() {
    var P = S.chart.palette(), out = [];
    var style = { value_area: [P.accent2, 2, 1], prior_day: [P.ink3, 1, 1], opening_range: [P.stale, 2, 1], overnight: [P.research, 2, 1],
      expected_move: [P.accent2, 3, 1], gamma: [P.research, 2, 1] };
    var gamma = { call_wall: ['Call wall', P.up, 0, 2], put_wall: ['Put wall', P.down, 0, 2],
      gamma_flip: ['γ flip', P.accent, 0, 2], max_pain: ['Max pain', P.ink3, 3, 1] };
    var byId = {}; ((S.levels && S.levels.levels) || []).forEach(function (l) { byId[l.id] = l; });
    // served order: nearest the live price first (by_distance); the chart keeps the first N on screen
    ((S.levels && S.levels.by_distance) || []).forEach(function (id) {
      var l = byId[id]; if (!l || l.price == null || S.fam[l.family] === 0) return;
      var g = l.family === 'gamma' && gamma[l.id];
      var lean = S.terrain && S.terrain[l.id + '_lean'];   // served: call_wall_lean / put_wall_lean
      if (g) { out.push({ id: l.id, price: Number(l.price), label: g[0] + (lean ? ' · ' + lean : ''), color: g[1], style: g[2], width: g[3] }); return; }
      var s = style[l.family]; if (!s) return;
      out.push({ id: l.id, price: Number(l.price), label: l.short || l.label || l.id, color: s[0], style: s[1], width: s[2] });
    });
    return out;
  }
  function paintStyle() {
    if (S.chart) S.chart.setStyle(S.style);
    var b = $('tdmStyle'); if (b) { b.classList.toggle('on', S.style === 'line'); }
  }
  function paintChartLevels() {
    if (!S.chart) return;
    S.chart.setLevels(levelList());
    var L = (S.levels && S.levels.levels) || [], vah = null, val = null;
    L.forEach(function (l) { if (l.id === 'TODAY_VAH') vah = l.price; if (l.id === 'TODAY_VAL') val = l.price; });
    S.chart.setValueArea(S.fam.value_area ? val : null, S.fam.value_area ? vah : null);
    S.chart.setVwap(S.fam.vwap && S.levels ? S.levels.vwap_series : []);
    var T = S.fam.gamma !== 0 && S.terrain;
    S.chart.setWallBands(T ? T.call_wall_range : null, T ? T.put_wall_range : null);
  }
  function paintChartOverlays() {
    if (!S.chart || !S.bars.length) return;
    paintChartLevels();
    var P = S.chart.palette();
    // the newest 40 events are drawn (the queue lists every one); a 20-day daily chart would
    // otherwise carry hundreds of dots on thirty candles
    S.chart.setMarkers(queueItems().filter(function (q) { return q.marker; }).map(function (q) {   // served flag: the newest 40
      return { id: q.key, time: q.ts, text: String(q.n), color: q.dir === 'up' ? P.up : q.dir === 'down' ? P.down : P.accent2,
        position: q.dir === 'down' ? 'aboveBar' : 'belowBar', shape: 'circle', meta: q.key };
    }), function (key) { selectItem(key, false); });
  }

  // ------------------------------------------------------------------ attention queue
  function queueItems() { return (S.events && S.events.items) || []; }   // served, ordered, numbered
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
        '<span class="tdm-q-m"><span class="tdm-dom">' + esc(q.dom) + '</span>' + (q.ts == null ? 'time not reported' : esc(whenCT(q.ts)) + ' CT') + ' · ' + esc(q.src) + '</span></span></button>';
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
  // the FORCES split, served: GEX below/above spot (/api/terrain/strikes today_side_sums), and
  // OI change, DEX and charm below/above from the last two market days' captures (/api/forces)
  function forcesRows() {
    var ss = S.strikes && S.strikes.today_side_sums, f = S.forces || {};
    var out = row('GEX below / above', ss ? usd(ss.gex_below) + ' / ' + usd(ss.gex_above) : '—');
    if (f.available !== true) return out + row('ΔOI · DEX · charm', esc(f.reason || '—'));
    return out + row('ΔOI below / above', num(f.doi_below, 0) + ' / ' + num(f.doi_above, 0)) +
      row('DEX below / above', usd(f.dex_below_dollars) + ' / ' + usd(f.dex_above_dollars)) +
      row('Charm below / above', num(f.charm_below, 4) + ' / ' + num(f.charm_above, 4));
  }
  function row(k, v, cls) { return '<div class="tdm-r"><span>' + esc(k) + '</span><b class="' + (cls || '') + '">' + v + '</b></div>'; }
  function state(el, txt, cls) { var s = el.querySelector('.tdm-state'); s.textContent = txt; s.className = 'tdm-state ' + (cls || ''); }
  function seriesNote() { return '<div class="tdm-series">1h change · sparkline: not produced yet</div>'; }
  function paintCards() {
    var m = S.micro, t = S.terrain;
    // LIQUIDITY — displayed book depth
    var c = $('tdmCardLiq');
    if (c) {
      var d5 = m && m.depth && m.depth['5'];
      if (!m || m.status === 'no_book' || !d5 || d5.imbalance == null) {
        state(c, m && m.status === 'no_book' ? 'NO BOOK' : 'UNAVAILABLE', 'warn');
        c.querySelector('.tdm-hero').innerHTML = '—';
        c.querySelector('.tdm-rows').innerHTML = row('Book source', esc((m && m.provenance && m.provenance.book_source) || 'unavailable')) +
          row('Reason', m && m.status === 'no_book' ? 'no ' + esc(m.venue) + ' for this symbol right now' : m === undefined ? 'loading…' : 'microstructure request failed');
      } else {
        var imb = Number(d5.imbalance);
        var bs = m.ages ? m.ages.book_stale : null;   // true, false, or unknown (null)
        var sd = d5.side;   // served: BID / ASK / EVEN
        state(c, bs === true ? 'STALE BOOK' : bs !== false ? 'BOOK AGE UNKNOWN' : (sd === 'BID' ? 'BID HEAVY' : sd === 'ASK' ? 'OFFER HEAVY' : 'BALANCED'),
          bs !== false ? 'warn' : (sd === 'BID' ? 'up' : sd === 'ASK' ? 'dn' : ''));
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
      var cc = (S.events && S.events.cross_counts) || null;   // served for the window
      function pct(v) { return v == null ? '—' : '<span class="' + (v > 0 ? 'up' : v < 0 ? 'dn' : '') + '">' + (v > 0 ? '+' : '') + num(v * 100, 0) + '%</span>'; }
      var p5 = fl ? fl.tape_pressure_5m : null, ts5 = fl ? fl.tape_side_5m : null;   // served side
      state(c, ts5 == null ? (m === undefined ? 'LOADING' : 'NO TRADES SEEN') : (ts5 === 'BUY' ? 'NET BUYING' : ts5 === 'SELL' ? 'NET SELLING' : 'BALANCED'),
        ts5 == null ? 'warn' : (ts5 === 'BUY' ? 'up' : ts5 === 'SELL' ? 'dn' : ''));
      c.querySelector('.tdm-hero').innerHTML = p5 == null ? '—<small>no trades in the tape buffer yet</small>'
        : pct(p5) + '<small>net traded volume, last 5 min (tick rule, PROXY)</small>';
      c.querySelector('.tdm-rows').innerHTML =
        row('Last 30 s · 2 min', (fl ? pct(fl.tape_pressure_30s) : '—') + ' · ' + (fl ? pct(fl.tape_pressure_2m) : '—')) +
        row('Cum. delta (tape buffer)', fl && fl.cum_delta_proxy != null ? (fl.cum_delta_proxy >= 0 ? '+' : '−') + fmtVol(Math.abs(fl.cum_delta_proxy)) + ' sh' : '—') +
        row('Top of book', tob && tob.bid_size != null ? fmtVol(tob.bid_size) + ' × ' + fmtVol(tob.ask_size) : '—') +
        row('Level crosses (' + LOOKBACK[S.tf].lbl + ')', cc ? cc.up + ' up · ' + cc.down + ' down' : '—');
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
        var ng = t.net_gex_at_spot;   // absent is uncoloured, never read as 0
        var up = (t.flip_diag || {}).unpriced;   // contracts with open interest the flip could not price, by reason
        c.querySelector('.tdm-hero').innerHTML = '<span class="' + (ng == null ? '' : ng >= 0 ? 'up' : 'dn') + '">' + usd(ng) + '</span><small>net dealer gamma at spot (per 1% move)</small>';
        c.querySelector('.tdm-rows').innerHTML = row('Call wall', num(t.call_wall) + (t.call_wall_state ? ' · ' + esc(t.call_wall_state) : ''), 'up') +
          row('Put wall', num(t.put_wall) + (t.put_wall_state ? ' · ' + esc(t.put_wall_state) : ''), 'dn') +
          row('Gamma flip', num(t.gamma_flip)) + row('Max pain', num(t.max_pain)) +
          row('Not priced', !up ? '—' : Object.keys(up).map(function (k) { return up[k] + ' ' + esc(k.replace(/_/g, ' ')); }).join(' · ') || 'none') +
          row('Put/Call OI (all exp)', num(t.pcr_all, 2)) +
          forcesRows() +
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
      ['LIQUIDITY', d5 && d5.side ? (d5.side === 'BID' ? 'Bid heavy' : d5.side === 'ASK' ? 'Offer heavy' : 'Balanced') : 'No book', d5 && d5.side === 'BID' ? 'up' : d5 && d5.side === 'ASK' ? 'dn' : ''],
      ['VALUE', l && l.summary ? String(l.summary.value_state || '—').replace(/_/g, ' ') : '—', ''],
      ['VWAP', l && l.summary ? String(l.summary.vwap_relation || '—').replace(/_/g, ' ') : '—', ''],
      ['OPTIONS', t && !t.error ? String(t.posture || t.regime || '—').replace(/_/g, ' ') : '—', ''],
      ['GAMMA', t && t.flip_relation ? (t.flip_relation === 'ABOVE' ? 'Above flip' : 'Below flip') : '—', t && t.flip_relation === 'ABOVE' ? 'up' : t && t.flip_relation === 'BELOW' ? 'dn' : '']
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
    h += m === undefined ? pill('BOOK', '…', '') : !m ? pill('BOOK', 'FAILED', 'bad') : m.status === 'no_book' ? pill('BOOK', 'NONE', 'warn', 'no ' + m.venue)
      : pill('BOOK', m.ages && m.ages.book_stale === false ? age(m.ages.book_age_sec) : m.ages && m.ages.book_stale ? 'STALE' : 'AGE UNKNOWN',
          m.ages && m.ages.book_stale === false ? 'ok' : 'bad');
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
      S.levels = S.terrain = S.micro = S.events = S.liq = S.strikes = S.forces = undefined; S.sel = null;
      paintHeader(); paintQueue(); paintCards(); paintTrust(); paintAgreement(); paintFooter();
      loadBars(true); loadSlow(); loadFast();
    } else if (!S.bars.length) { loadBars(true); loadSlow(); loadFast(); }
  }
  function init() {
    if (!$('tdmMap')) return;
    document.addEventListener('ed:view', start);
    document.addEventListener('ed:ticker', start);
    document.addEventListener('ed:book_venue', function () { if (onDesk() && S.ticker) { loadFast(); loadSlow(); } });
    document.addEventListener('ed:changed', function (e) {
      if (!onDesk() || !S.ticker) return;
      var k = e.detail.kind;
      if (k === 'flow') loadFast();
      if (k === 'levels' || k === 'liquidity') loadSlow();
      if (k === 'liquidity') loadBars(false);   // a completed Schwab bar was written
    });
    // Every streamed price row: header + indices. The chart moves only on a completed bar.
    window.addEventListener('ed:quote_tick', function (e) {
      var q = e.detail; if (!q || !q.ticker) return;
      S.quotes[bare(q.ticker)] = q;
      if (!onDesk()) return;
      paintHeader();
      if (bare(q.ticker) === bare(S.ticker)) paintTrust();
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
