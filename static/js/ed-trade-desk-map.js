/* Ed Console — Trade Desk / "Desk" subview (the operator's 2026-09-25 mockup). PRESENTATION ONLY.

   One page for the SELECTED ticker, one global timeframe:
     MARKET MAP   <- /api/bars1m (completed Schwab 1m bars, server-rolled timeframe),
                     /api/levels (value area, VWAP + bands, prior day, opening range, overnight),
                     /api/terrain (call/put wall, gamma flip, max pain -- full chain)
     ATTENTION    <- /api/desk/events (served, numbered; each marker is its queue entry, linked
                     both ways): level crosses judged by their minute's bar, wall breaches,
                     the book's size walls at the book's own time
     CARDS        <- /api/order-flow/microstructure, /api/terrain, the price row (Schwab
                     LEVELONE), /api/bars1m, /api/liquidity-snapshot (value/VWAP relation)
     HEADER TRUST <- the same responses' own state/age fields
   The browser computes nothing: it picks which served values to show, formats them, and
   places a served event on the bar that contains it. A value with no producer yet says so. */
(function () {
  'use strict';

  // the chart's timeframes (ed-tv-chart, every chart's)
  var TFS = window.EdTvChart.TFS;
  // The ONE global timeframe also sets how far back the queue and the event markers reach.
  // the event window and its words are the server's (/api/desk/events window_label), for this timeframe
  function windowLabel() { return S.events && S.events.tf === S.tf ? S.events.window_label : '—'; }
  var FAMILIES = [
    { id: 'volume_profile', lbl: 'Volume profile (RTH)' },
    { id: 'value_area', lbl: 'Value area' }, { id: 'vwap', lbl: 'VWAP' }, { id: 'gamma', lbl: 'Gamma' },
    { id: 'expected_move', lbl: '±1σ move' }, { id: 'prior_day', lbl: 'Prior day' }, { id: 'opening_range', lbl: 'Opening range' },
    { id: 'overnight', lbl: 'Overnight' }];
  var DRILL = { liquidity: ['order-flow', 'heatmap'], flow: ['order-flow', 'book'],
    options: ['options', 'gamma'], vol: ['options', 'chain'] };

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
  // an instant's age as the console's push labels it (`kind`: the answer's as_of; EdShell.ageSpan)
  function age(kind) { return window.EdShell.ageSpan(kind); }
  function st() { return (window.EdShell && window.EdShell.getState()) || {}; }
  function onDesk() { var s = st(); return s.workspace === 'trade-desk' && s.subview === 'desk'; }
  // the instrument's served display name (the daemon's answer, EdShell state.display); as typed
  // until it arrives
  function shown() { return st().display || S.ticker; }
  function $(id) { return document.getElementById(id); }
  function sget(k, d) { try { var v = window.localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function sset(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* per-viewer only */ } }

  var S = {
    tf: st().tfs.desk, nearest: Number(sget('ed.desk.nearest', '6')) || 6,
    fam: (function () { try { return JSON.parse(sget('ed.desk.fam', 'null')) || null; } catch (e) { return null; } })() ||
      { value_area: 1, vwap: 1, gamma: 1, expected_move: 1, prior_day: 1, opening_range: 1, overnight: 1 },
    ticker: null, tb: null, gen: 0, chart: null, bars: [], levels: null, terrain: null, micro: null, crosses: null,
    analytics: null, liq: null, quotes: {}, queue: [], sel: null
  };

  // ------------------------------------------------------------------ layout wiring
  function buildToolbar() {
    var fam = $('tdmFamilies'); if (!fam || fam.getAttribute('data-built')) return;
    fam.setAttribute('data-built', '1');
    fam.innerHTML = FAMILIES.map(function (f) {
      return '<button type="button" class="tdm-fam fam-' + f.id + '" data-fam="' + f.id + '"><i></i>' + f.lbl + '<b data-famv="' + f.id + '"></b></button>'; }).join('') +
      '<span class="tdm-fam-note" id="tdmProfNote"></span>';
    fam.addEventListener('click', function (e) {
      var b = e.target.closest('[data-fam]'); if (!b) return;
      var id = b.getAttribute('data-fam'); S.fam[id] = S.fam[id] === 0 ? 1 : 0;   // a family not yet saved is on
      sset('ed.desk.fam', JSON.stringify(S.fam)); paintChartLevels();
    });
    paintFamilies();
  }
  function paintFamilies() {
    document.querySelectorAll('#tdmFamilies [data-fam]').forEach(function (b) {
      b.classList.toggle('on', S.fam[b.getAttribute('data-fam')] !== 0); });
    var pd = pdValueArea(), vw = levelPrice('VWAP');
    var v = { vwap: vw == null ? '' : num(vw), prior_day: pd.val == null || pd.vah == null ? '' : 'VA ' + num(pd.val) + ' – ' + num(pd.vah) };
    document.querySelectorAll('#tdmFamilies [data-famv]').forEach(function (b) { b.textContent = v[b.getAttribute('data-famv')] || ''; });
    // the profile's basis, or why there is none (the value area's served reason)
    var vp = S.levels && S.levels.volume_profile, pn = $('tdmProfNote');
    var why = ((S.levels && S.levels.families_absent) || []).filter(function (a) { return a.family === 'value_area'; })[0];
    if (pn) pn.textContent = vp ? vp.basis + (vp.bars_without_volume ? ' · ' + vp.bars_without_volume + ' of ' + vp.bars +
      ' RTH bars sent no volume and are not in it' : '') : why ? 'Volume profile (RTH) not drawn: ' + why.reason : '';
  }
  function paintTfButtons() {
    if (S.tb) S.tb.setTf(S.tf);
    var lb = $('tdmLookback'); if (lb) lb.textContent = windowLabel();
  }
  function ensureChart() {
    if (S.chart) return S.chart;
    if (!window.EdTvChart || !window.LightweightCharts) return null;
    S.chart = window.EdTvChart.create($('tdmChart'), { nearestN: S.nearest, fullscreenEl: $('tdmMap') });
    S.tb = window.EdTvChart.toolbar($('tdmToolbar'), S.chart, { tf: S.tf, onTf: setTf, styleKey: 'ed.desk.style' });
    S.tb.slot.innerHTML = '<span class="tvc-sep"></span>' +
      '<label class="tvc-nsel" title="How many key levels to draw (nearest to price, inside the visible range)">Levels ' +
      '<select id="tdmNearest">' + [3, 4, 6, 8, 12, 99].map(function (n) {
        return '<option value="' + n + '"' + (n === S.nearest ? ' selected' : '') + '>' + (n === 99 ? 'All' : n) + '</option>'; }).join('') +
      '</select></label>';
    $('tdmNearest').addEventListener('change', function (e) {
      S.nearest = Number(e.target.value) || 6; sset('ed.desk.nearest', String(S.nearest));
      S.chart.setNearestN(S.nearest);
    });
    paintTfButtons();
    document.querySelectorAll('[data-drill]').forEach(function (el) {
      el.addEventListener('click', function () {
        var d = DRILL[el.getAttribute('data-drill')]; if (!d || !window.EdShell) return;
        window.EdShell.setWorkspace(d[0]);
        if (window.EdShell.setSubview) window.EdShell.setSubview(d[1]);
      });
    });
    return S.chart;
  }
  // A new timeframe is a new view: its bars, its levels (VWAP per bar) and its event window are
  // pushed for it. Until they arrive the chart and queue say what is loading, never the old view.
  function setTf(tf) {
    if (tf === S.tf) return;
    S.tf = tf; paintTfButtons();
    S.bars = []; S.levels = S.events = undefined;
    clearChart(); paintQueue(); paintCards();
    window.EdShell.setTf('desk', tf);
  }
  function clearChart() {
    if (!S.chart) return;
    S.chart.setBars([], S.tf, shown(), null);
    S.chart.setLevels([]); S.chart.setMarkers([]); S.chart.setVolumeProfile([]); S.chart.setVwap([]);
    S.chart.setValueArea(null, null);
    $('tdmChartEmpty').hidden = false;
    $('tdmChartEmpty').textContent = 'Loading ' + shown() + ' · ' + (TFS.filter(function (x) { return x.id === S.tf; })[0] || {}).lbl + '…';
  }

  // ------------------------------------------------------------------ data: as the console pushes it
  // (the terrain, zones, strikes and book are the same answers the Gamma, Liquidity and Order Flow
  // panels read). A failed answer is absent (null); one on its way for a new view is undefined.
  // The bars: the whole series after a new view, then each push's newest two buckets.
  window.EdShell.onPanel('desk.bars', function (a) {
    if (a.waiting) { S.barsWhole = false; return; }
    if (!S.chart) return;
    var d = a.ok ? a.body : null, bars = d ? d.bars : [];
    if (!S.barsWhole) {
      S.barsWhole = true;
      S.bars = bars; S.barsAnswered = S.gen;
      S.chart.setBars(bars, S.tf, shown(), d && d.last_bar && d.last_bar.label);
      $('tdmChartEmpty').hidden = bars.length > 0;
      $('tdmChartEmpty').textContent = bars.length ? '' : (!d ? 'The bars request answered HTTP ' + a.status + ' for ' + shown() + ' (' + TFS.filter(function (x) { return x.id === S.tf; })[0].lbl + ').'
        : 'No bars for ' + shown() + (d.error ? ' — ' + d.error : ' — nothing banked or streamed for this symbol yet.'));
      paintChartOverlays(); paintQueue(); openView();
      var src = $('tdmBarsSrc'); if (src) src.textContent = 'streamed 1m bars';
    } else if (bars.length) {
      S.chart.updateTail(bars.slice(-2), d.last_bar && d.last_bar.label);
    }
  });
  [['desk.levels', 'levels'], ['desk.events', 'events'], ['desk.terrain', 'terrain'], ['desk.zones', 'liq'],
   ['desk.strikes', 'strikes'], ['desk.forces', 'forces'], ['desk.flow_bars', 'flowBars'], ['desk.book', 'micro']].forEach(function (p) {
    window.EdShell.onPanel(p[0], function (a) {
      var d = a.waiting ? undefined : a.ok ? a.body : null;
      S[p[1]] = p[1] === 'flowBars' && d ? d.bars : d;
      paintTfButtons(); paintChartOverlays(); paintQueue(); paintCards(); paintTrust(); paintAgreement(); paintFooter();
      openView();
    });
  });
  // the chart opens on the served event window (5m/30m: the session), once per symbol and timeframe
  function openView() {
    var vk = S.ticker + '|' + S.tf;
    if (S.chart && S.bars.length && S.events && S.events.tf === S.tf && S.viewKey !== vk) {
      S.viewKey = vk; S.chart.setViewFrom(S.events.window_start_ts_utc);
    }
  }

  // ------------------------------------------------------------------ chart overlays
  function levelList() {
    var P = S.chart.palette(), out = [];
    // the reference's key: value-area levels amber, every other key level orange dashed
    var style = { value_area: [P.warn, 2, 1], prior_day: [P.stale, 2, 1], opening_range: [P.stale, 2, 1], overnight: [P.stale, 2, 1],
      expected_move: [P.stale, 3, 1], gamma: [P.stale, 2, 1] };
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
      out.push({ id: l.id, price: Number(l.price), label: l.short, color: s[0], style: s[1], width: s[2] });
    });
    return out;
  }
  function levelPrice(id) {
    var l = ((S.levels && S.levels.levels) || []).filter(function (x) { return x.id === id; })[0];
    return l && l.price != null ? Number(l.price) : null;
  }
  function pdValueArea() { return { val: levelPrice('PD_VAL'), vah: levelPrice('PD_VAH') }; }
  function paintChartLevels() {
    if (!S.chart) return;
    paintFamilies();
    S.chart.setLevels(levelList());
    // the band is yesterday's value area, as the reference draws it; today's are level lines
    var pd = pdValueArea(), on = S.fam.prior_day !== 0;
    S.chart.setValueArea(on ? pd.val : null, on ? pd.vah : null);
    // the session volume profile on the left edge: value-area bins brighter (the served flag), its
    // served POC marked across it
    var vp = S.fam.volume_profile !== 0 && S.levels && S.levels.volume_profile;
    var P = S.chart.palette(), alpha = window.EdTvChart.alpha;
    S.chart.setVolumeProfile(vp ? vp.bins.map(function (b) {
      return { price: b[0], value: b[1], color: b[2] ? alpha(P.accent, 0.38) : alpha(P.ink3, 0.2) }; }) : [],
      vp ? vp.max_volume : null,
      vp && vp.poc != null ? { price: vp.poc, label: 'POC est ' + num(vp.poc), color: P.warn } : null);
    S.chart.setVwap(S.fam.vwap && S.levels ? S.levels.vwap_series : []);
  }
  function paintChartOverlays() {
    if (!S.chart || !S.bars.length) return;
    paintChartLevels();
    var P = S.chart.palette();
    // the served few (marker flag): each at its level's price and its time, numbered, named by its
    // served direction; the queue lists every event, and a marker and its entry are one served item
    var word = { up: 'Crossed above', down: 'Crossed below' };
    S.chart.setMarkers(queueItems().filter(function (q) { return q.marker; }).map(function (q) {
      return { id: q.key, time: q.ts, price: q.price, num: q.n, text: word[q.dir] || '',
        color: q.dir === 'up' ? P.up : P.down, meta: q.key };
    }), function (key) { selectItem(key, false); });
  }

  // ------------------------------------------------------------------ attention queue
  function queueItems() { return (S.events && S.events.items) || []; }   // served, ordered, numbered
  function paintQueue() {
    var host = $('tdmQueue'); if (!host) return;
    var items = queueItems(); S.queue = items;
    $('tdmQueueCount').textContent = items.length ? String(items.length) : '';
    if (S.events === undefined) { host.innerHTML = '<div class="tdm-empty">Loading ' + esc(shown()) + ' events…</div>'; return; }
    if (!items.length) {
      host.innerHTML = '<div class="tdm-empty">Nothing in the ' + esc(windowLabel()) + '. Level crosses, wall breaches and book size walls land here.</div>';
      return;
    }
    host.innerHTML = items.map(function (q) {
      return '<button type="button" class="tdm-q ' + (q.warn ? 'warn' : q.dir === 'up' ? 'up' : q.dir === 'down' ? 'dn' : '') + (q.key === S.sel ? ' sel' : '') + '" data-q="' + esc(q.key) + '">' +
        '<span class="tdm-q-n">' + (q.n || '•') + '</span>' +
        '<span class="tdm-q-b"><span class="tdm-dom">' + esc(q.dom) + '</span><span class="tdm-q-t">' + esc(q.title) + '</span>' +
        '<span class="tdm-q-d">' + esc(q.detail) + '</span>' +
        '<span class="tdm-q-m">' + esc(q.src) + ' · ' + (q.time_ct == null ? 'time not reported' : esc(q.time_ct)) + '</span></span></button>';
    }).join('');
  }
  function selectItem(key, scroll) {
    S.sel = key; paintQueue();
    var el = document.querySelector('#tdmQueue [data-q="' + key + '"]');
    if (el) el.scrollIntoView({ block: 'nearest' });
    var q = S.queue.filter(function (x) { return x.key === key; })[0];
    if (S.chart) S.chart.selectMarker(key);        // the entry's own marker, drawn larger
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
  // a card's facts: one compact line of served values
  function row(k, v, cls) { return '<span class="tdm-r">' + esc(k) + ' <b class="' + (cls || '') + '">' + v + '</b></span>'; }
  function state(el, txt, cls) { var s = el.querySelector('.tdm-state'); s.textContent = txt; s.className = 'tdm-state ' + (cls || ''); }
  function src(el, html) { el.querySelector('.tdm-src').innerHTML = html; }
  // Each card's chart, as the reference draws them (line, area or bars), of one served series.
  // sets: [{ys, xs (optional: served x values; else evenly spaced), color, kind: 'line'|'area'|'bars',
  // colors (bars: one per y)}]. Scaling to the box and the axis ticks are drawing; a null y is a gap.
  function spark(card, sets, caption, reason) {
    var box = card.querySelector('.tdm-chartbox');
    box.querySelector('figcaption').textContent = caption;
    var plot = box.querySelector('.tdm-plot');
    var pts = [];
    sets.forEach(function (s) { s.ys.forEach(function (y, i) { if (y != null && isFinite(y)) pts.push([s.xs ? s.xs[i] : i, y]); }); });
    if (!pts.length) { plot.innerHTML = '<div class="tdm-plot-none">' + esc(reason) + '</div>'; return; }
    var W = 260, H = 64, xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (sets.some(function (s) { return s.kind !== 'line'; })) { y0 = Math.min(0, y0); y1 = Math.max(0, y1); }
    if (x1 === x0) x1 = x0 + 1; if (y1 === y0) y1 = y0 + 1;
    function X(x) { return (x - x0) / (x1 - x0) * W; }
    function Y(y) { return H - (y - y0) / (y1 - y0) * H; }
    var svg = '';
    sets.forEach(function (s) {
      var n = s.ys.length;
      if (s.kind === 'bars') {
        var bw = Math.max(1, W / Math.max(1, n) * 0.7);
        s.ys.forEach(function (y, i) {
          if (y == null) return;
          var x = X(s.xs ? s.xs[i] : i) - bw / 2, top = Math.min(Y(y), Y(0));
          svg += '<rect x="' + x.toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0.5, Math.abs(Y(y) - Y(0))).toFixed(1) + '" fill="' + (s.colors ? s.colors[i] : s.color) + '"/>';
        });
        return;
      }
      var runs = [[]];   // a null breaks the line
      s.ys.forEach(function (y, i) {
        if (y == null || !isFinite(y)) { if (runs[runs.length - 1].length) runs.push([]); return; }
        runs[runs.length - 1].push([X(s.xs ? s.xs[i] : i), Y(y)]);
      });
      runs.forEach(function (r) {
        if (!r.length) return;
        var d = r.map(function (p, k) { return (k ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join('');
        if (s.kind === 'area') svg += '<path d="' + d + 'L' + r[r.length - 1][0].toFixed(1) + ' ' + H + 'L' + r[0][0].toFixed(1) + ' ' + H + 'Z" fill="' + s.color + '" opacity=".18"/>';
        svg += '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="1.6" vector-effect="non-scaling-stroke"/>';
        if (r.length === 1) svg += '<circle cx="' + r[0][0].toFixed(1) + '" cy="' + r[0][1].toFixed(1) + '" r="2" fill="' + s.color + '"/>';
      });
    });
    // no axis numbers: a number the page derives from the series is not printed (register P-11)
    plot.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + svg + '</svg>';
  }
  function paintCards() {
    var m = S.micro, t = S.terrain;
    // LIQUIDITY — displayed book depth
    var c = $('tdmCardLiq');
    if (c) {
      var d5 = m && m.depth && m.depth['5'];
      if (!m || m.status === 'no_book' || !d5) {
        state(c, m && m.status === 'no_book' ? 'NO BOOK' : 'UNAVAILABLE', 'warn');
        c.querySelector('.tdm-hero').innerHTML = '';
        src(c, 'Schwab ' + esc(st().bookVenue) + ' · ' + (m && m.status === 'no_book' ? 'no book for this symbol right now' : m === undefined ? 'loading…' : 'microstructure request failed'));
        c.querySelector('.tdm-rows').innerHTML = '';
      } else {
        var bs = m.ages ? m.ages.book_stale : null;   // true, false, or unknown (null)
        var sd = d5.side;   // served: BID / ASK / EVEN
        state(c, bs === true ? 'STALE BOOK' : bs !== false ? 'BOOK AGE UNKNOWN' : (sd === 'BID' ? 'BID HEAVY' : sd === 'ASK' ? 'OFFER HEAVY' : sd === 'EVEN' ? 'BALANCED' : 'ONE-SIDED'),
          bs !== false ? 'warn' : (sd === 'BID' ? 'up' : sd === 'ASK' ? 'dn' : ''));
        // the imbalance when both sides carry levels; the depth Schwab sent is shown either way
        var imb = d5.imbalance == null ? null : Number(d5.imbalance);
        c.querySelector('.tdm-hero').innerHTML = imb == null ? '' : '<span class="' + (imb >= 0 ? 'up' : 'dn') + '">' + (imb >= 0 ? '+' : '') + num(imb, 3) + '</span> <small>depth imbalance, 5 levels</small>';
        src(c, 'Schwab ' + esc(m.venue) + ' · book ' + (bs === false ? age('book') + ' old' : bs ? 'not live' : 'age unknown'));
        c.querySelector('.tdm-rows').innerHTML = row('Bid / ask depth (5)', (d5.bid_total != null ? fmtVol(d5.bid_total) : '—') + ' / ' + (d5.ask_total != null ? fmtVol(d5.ask_total) : '—')) +
          row('Spread', m.spread_pts != null ? num(m.spread_pts, 2) : '—');
      }
    }
    // ORDER FLOW — what Schwab reports of the trading: session volume, the last trade, the top of
    // book and the level crosses. Schwab sends no trade side, so none is claimed.
    c = $('tdmCardFlow');
    if (c) {
      var q = S.quotes[st().key], tob = m && m.top_of_book;
      var cc = (S.events && S.events.cross_counts) || null;   // served for the window
      // Schwab's last values with Schwab's trade time; with the feed down, marked not live with
      // the served reason; the feed state beside them
      state(c, !q ? 'WAITING' : q.feed_live ? 'SESSION VOLUME' : 'OFFLINE', q && q.feed_live ? '' : 'warn');
      c.querySelector('.tdm-hero').innerHTML = q && q.total_volume != null ? fmtVol(q.total_volume) + ' <small>shares, Schwab TOTAL_VOLUME</small>' : '';
      src(c, 'Schwab LEVELONE · ' + (!q ? 'no price row yet' : (q.trade_time_ct != null ? 'last trade ' + esc(window.EdShell.tradeLabel(q)) : 'no trade sent')
        + (q.outage ? ' · NOT LIVE · ' + esc(q.outage) : '')));
      c.querySelector('.tdm-rows').innerHTML =
        row('Last trade size', q && q.last_size != null ? fmtVol(q.last_size) : '—') +
        row('Top of book', (tob ? (tob.bid_size != null ? fmtVol(tob.bid_size) : '—') + ' × ' + (tob.ask_size != null ? fmtVol(tob.ask_size) : '—') : '—')
          + (m && m.top_outage ? ' · NOT LIVE' : '')) +
        row('Crosses (' + esc(windowLabel()) + ')', cc ? cc.up + ' up · ' + cc.down + ' down' : '—');
    }
    // OPTIONS POSITIONING — full-chain terrain
    c = $('tdmCardOpt');
    if (c) {
      if (!t || t.error) {
        state(c, t === undefined ? 'LOADING' : 'UNAVAILABLE', t === undefined ? '' : 'warn'); c.querySelector('.tdm-hero').innerHTML = '';
        src(c, 'Schwab option chain · ' + (t === undefined ? 'loading…' : esc((t && t.error) || 'terrain request failed')));
        c.querySelector('.tdm-rows').innerHTML = '';
      } else {
        var reg = window.EdGamma.regime(t.regime).t;
        state(c, reg, t.levels_stale ? 'warn' : (/LONG/.test(String(t.regime)) ? 'up' : /SHORT/.test(String(t.regime)) ? 'dn' : ''));
        var ng = t.net_gex_at_spot;   // absent is uncoloured, never read as 0
        c.querySelector('.tdm-hero').innerHTML = '<span class="' + (ng == null ? '' : ng >= 0 ? 'up' : 'dn') + '">' + (ng == null ? '—' : window.EdGamma.formatUsd(ng)) + '</span> <small>net dealer gamma at spot, per 1%</small>';
        src(c, 'Schwab option chain · ' + (t.levels_stale ? 'stale ' + age('levels') : age('levels') + ' old'));
        c.querySelector('.tdm-rows').innerHTML = row('Call wall', num(t.call_wall), 'up') + row('Put wall', num(t.put_wall), 'dn') +
          row('Flip', num(t.gamma_flip)) + row('P/C OI', num(t.pcr_all, 2)) + row('Max pain', num(t.max_pain)) +
          row('Contracts', t.contracts_used != null ? t.contracts_used.toLocaleString() : '—') + forcesRows();
      }
    }
    // VOLATILITY
    c = $('tdmCardVol');
    if (c) {
      var vixC = window.EdShell.marketContext().filter(function (c) { return c.display === 'VIX'; })[0];
      var im = t && t.implied_1d_move, vix = vixC && S.quotes[vixC.key];
      if (!im || im.iv_pct_atm == null) {
        state(c, t === undefined ? 'LOADING' : 'UNAVAILABLE', t === undefined ? '' : 'warn'); c.querySelector('.tdm-hero').innerHTML = '';
      } else {
        state(c, 'ATM IV ' + num(im.iv_pct_atm, 1) + '%', '');
        c.querySelector('.tdm-hero').innerHTML = '±' + num(im.points, 2) + ' <small>implied 1-day move, 1σ</small>';
      }
      src(c, 'Schwab option chain · ' + (!t || t.error ? '—' : age('levels') + ' old'));
      c.querySelector('.tdm-rows').innerHTML =
        (im && im.dte_used != null ? row('Move from', 'first expiry ≥1 day out (' + num(im.dte_used, 0) + 'd)') : '') +
        row('ATR daily', t && t.atr_daily != null ? num(t.atr_daily) : esc((t && t.atr_daily_reason) || '—')) +
        row('ATR weekly', t && t.atr_weekly != null ? num(t.atr_weekly) : esc((t && t.atr_weekly_reason) || '—')) +
        row('ATR monthly', t && t.atr_monthly != null ? num(t.atr_monthly) : esc((t && t.atr_monthly_reason) || '—')) +
        row('VIX', vix && vix.spot != null ? num(vix.spot) + (vix.chg_pct != null ? ' (' + (vix.chg_pct >= 0 ? '+' : '') + num(vix.chg_pct) + '%)' : '') : 'waiting for the VIX stream');
    }
    paintCardCharts();
  }
  function paintCardCharts() {
    if (!S.chart) return;
    var P = S.chart.palette(), m = S.micro, t = S.terrain, c;
    if ((c = $('tdmCardLiq'))) {
      var dp = (m && m.depth_pressure) || {}, bid = (dp.bid || []).slice().reverse(), ask = dp.ask || [];
      spark(c, [{ xs: bid.map(function (r) { return r.price; }), ys: bid.map(function (r) { return r.cum; }), color: P.up, kind: 'area' },
        { xs: ask.map(function (r) { return r.price; }), ys: ask.map(function (r) { return r.cum; }), color: P.down, kind: 'area' }],
        'Cumulative displayed depth by price · ' + ((m && m.venue) || st().bookVenue),
        m && m.status === 'no_book' ? 'no ' + m.venue + ' for this symbol right now' : m === undefined ? 'loading…' : 'no book levels served');
    }
    if ((c = $('tdmCardFlow'))) {
      var fb = S.flowBars || [];
      spark(c, [{ ys: fb.map(function (b) { return b.v; }), kind: 'bars', color: P.ink3,
        colors: fb.map(function (b) { return b.chg == null ? P.ink3 : b.chg >= 0 ? P.up : P.down; }) }],
        'Volume per 1-minute bar, last hour · green up, red down',
        S.flowBars === undefined ? 'loading…' : 'no 1-minute bars for this symbol');
    }
    if ((c = $('tdmCardOpt'))) {
      var pcr = (t && t.pcr_by_expiry) || {};
      spark(c, [{ ys: Object.keys(pcr).map(function (k) { return pcr[k]; }), color: P.research, kind: 'line' }],
        'Put/call open interest by expiry, nearest first',
        t === undefined ? 'loading…' : (t && t.error) || 'no expiry carries open interest');
    }
    if ((c = $('tdmCardVol'))) {
      var iv = (t && t.atm_iv_pct_by_expiry) || {};
      spark(c, [{ ys: Object.keys(iv).map(function (k) { return iv[k]; }), color: P.accent, kind: 'line' }],
        'ATM implied vol by expiry, nearest first',
        t === undefined ? 'loading…' : (t && t.error) || 'no expiry has both ATM legs priced');
    }
  }

  // ------------------------------------------------------------------ agreement (server labels only)
  function paintAgreement() {
    var host = $('tdmAgree'); if (!host) return;
    var m = S.micro, t = S.terrain, l = S.liq, d5 = m && m.depth && m.depth['5'];
    var cells = [
      ['LIQUIDITY', d5 && d5.side ? (d5.side === 'BID' ? 'Bid heavy' : d5.side === 'ASK' ? 'Offer heavy' : 'Balanced') : 'No book', d5 && d5.side === 'BID' ? 'up' : d5 && d5.side === 'ASK' ? 'dn' : ''],
      ['VALUE', l && l.summary ? String(l.summary.value_state || '—').replace(/_/g, ' ') : '—', ''],
      ['VWAP', l && l.summary ? String(l.summary.vwap_relation || '—').replace(/_/g, ' ') : '—', ''],
      ['OPTIONS', t && !t.error && t.posture ? String(t.posture).replace(/_/g, ' ') : '—', ''],
      ['GAMMA', ({ ABOVE: 'Above flip', BELOW: 'Below flip' })[t && t.flip_relation] || '—', t && t.flip_relation === 'ABOVE' ? 'up' : t && t.flip_relation === 'BELOW' ? 'dn' : '']
    ];
    host.innerHTML = cells.map(function (c) {
      return '<div class="tdm-ag"><span>' + c[0] + '</span><b class="' + c[2] + '">' + esc(c[1]) + '</b></div>'; }).join('') +
      '<div class="tdm-ag tdm-ag-note">Each domain\'s own served label. No combined agreement score is produced yet.</div>';
  }

  // ------------------------------------------------------------------ header trust + footer
  // `val`: text, or {pre, ageOf} (a served age after `pre`)
  function pill(lbl, val, cls, title) {
    var v = val && val.ageOf ? esc(val.pre) + age(val.ageOf) : esc(val);
    return '<span class="tdm-pill ' + (cls || '') + '" title="' + esc(title || '') + '"><i></i>' + esc(lbl) + ' <b>' + v + '</b></span>';
  }
  function paintTrust() {
    var host = $('tdmTrust'); if (!host) return;
    var q = S.quotes[st().key], t = S.terrain, m = S.micro, L = S.levels;
    var h = '';
    h += q ? pill('PRICE', q.feed_live ? 'LIVE' : 'OFFLINE', q.feed_live ? 'ok' : 'bad', q.feed_live ? 'the console\'s price row' : 'not live' + (q.outage ? ': ' + q.outage : ''))
      : pill('PRICE', 'WAITING', 'warn', 'no price row yet for this symbol');
    h += m === undefined ? pill('BOOK', '…', '') : !m ? pill('BOOK', 'FAILED', 'bad') : m.status === 'no_book' ? pill('BOOK', 'NONE', 'warn', 'no ' + m.venue)
      : pill('BOOK', m.ages && m.ages.book_stale === false ? { pre: '', ageOf: 'book' } : m.ages && m.ages.book_stale ? 'STALE' : 'AGE UNKNOWN',
          m.ages && m.ages.book_stale === false ? 'ok' : 'bad');
    // the session levels snapshot's served age
    h += L === undefined ? pill('LEVELS', '…', '') : !L ? pill('LEVELS', 'FAILED', 'bad') : pill('LEVELS', L.as_of.snapshot == null ? '—' : { pre: '', ageOf: 'snapshot' }, (L.degraded && L.degraded.length) ? 'warn' : 'ok', 'session levels snapshot age');
    h += t === undefined ? pill('GAMMA', '…', '') : !t || t.error ? pill('GAMMA', 'DOWN', 'bad', (t && t.error) || 'terrain request failed') : pill('GAMMA', { pre: t.levels_stale ? 'STALE ' : '', ageOf: 'levels' }, t.levels_stale ? 'warn' : 'ok', t.levels_stale_reason || '');
    host.innerHTML = h;
  }
  function paintFooter() {
    var host = $('tdmFoot'); if (!host) return;
    var t = S.terrain, m = S.micro, L = S.levels;
    host.innerHTML = [
      'Bars: <b id="tdmBarsSrc">' + esc(($('tdmBarsSrc') || {}).textContent || '—') + '</b>',
      'Book: <b>' + esc((m && m.provenance && m.provenance.book_source) || '—') + '</b>',
      'Levels: <b>' + esc((L && L.bar_source) || '—') + '</b>',
      'Options: <b>' + esc(t && !t.error ? (t.chain_basis || '—') + ' chain · ' + (t.strikes_used == null ? '—' : t.strikes_used) + ' strikes · ' + (t.contracts_used != null ? t.contracts_used.toLocaleString() : '—') + ' contracts' : '—') + '</b>',
      'Clock: <b>Central</b>'
    ].map(function (x) { return '<span>' + x + '</span>'; }).join('');
  }
  // The shell header already carries the symbol, price, change and CT clock; this page adds
  // the index context and the data-trust row beside it.
  function paintHeader() {
    window.EdShell.marketContext().forEach(function (c) {   // the served context symbols
      var el = $('tdmIdx' + c.display); if (!el) return;
      var r = S.quotes[c.key];
      el.title = r ? '' : 'waiting for the ' + c.display + ' stream';
      el.innerHTML = '<span>' + c.display + '</span><b>' + (r && r.spot != null ? num(r.spot) : '—') + '</b>' +
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
      S.levels = S.terrain = S.micro = S.events = S.liq = S.strikes = S.forces = S.flowBars = undefined; S.sel = null;
      clearChart(); paintHeader(); paintQueue(); paintCards(); paintTrust(); paintAgreement(); paintFooter();
    }
  }
  function init() {
    if (!$('tdmMap')) return;
    document.addEventListener('ed:view', start);
    document.addEventListener('ed:ticker', start);
    // Every streamed price row: header + indices. The chart moves only on a completed bar.
    window.addEventListener('ed:quote_tick', function (e) {
      var q = e.detail; if (!q || !q.ticker) return;
      S.quotes[q.ticker] = q;
      if (!onDesk()) return;
      paintHeader();
      if (q.ticker === st().key) {
        paintTrust();
        if (S.chart) S.chart.setLivePrice(q.spot, window.EdShell.tradeLabel(q));
        paintCards();   // the Order Flow card's Schwab fields, on every row
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
