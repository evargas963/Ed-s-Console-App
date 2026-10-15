// The capture daemon's Schwab socket (app/market_data/schwab/streaming/live_ui.py), stood in for.
// The console serves the page port 1 under e2e (playwright.config ED_LIVE_UI_PORT), so the page
// never reaches a real daemon. Like the daemon, it answers a subscribe with what each asked-for
// symbol is ({type:'symbols'}: requested, key, display), sends each LEVELONE_EQUITIES message 300 ms
// apart ({type:'schwab'}: the fields Schwab sent, by Schwab's names), and beats every second
// ({type:'feed'}: each symbol's verdict and its last trade's time and age, as the daemon words them,
// time_et.ct_label / age_label), and answers a subscribe's `chart` with that ticker's 1-minute
// series ({type:'series'}) before any message. STAND-IN (named): instrument_identity's index roots;
// the verdict (live once a message for the symbol and service was sent, unless the message names an
// outage); the series (the spec's own /api/bars1m stub); the labels' words (the daemon's own are
// proven in tests/test_live_ui_daemon_to_browser_v1.py).
const INDEX_ROOTS = new Set(['SPX', 'NDX', 'VIX', 'DJI', 'COMPX', 'RUT']);
function served(s) {
  const u = String(s).toUpperCase();
  const key = u.startsWith('$') || !INDEX_ROOTS.has(u) ? u : '$' + u;
  return { requested: s, key: key, display: key.replace(/^\$/, '') };
}
// the services the daemon reports each symbol's verdict on (live_ui.EQUITY_SERVICES / OPTION_SERVICES)
const SERVICES = ['LEVELONE_EQUITIES', 'NYSE_BOOK', 'NASDAQ_BOOK', 'CHART_EQUITY', 'NEWS_HEADLINE', 'LEVELONE_OPTIONS', 'OPTIONS_BOOK'];
const CT = { timeZone: 'America/Chicago' };
function ctLabel(ms) {          // as time_et.ct_label words it: "Fri 09/25 06:59 PM CT"
  const d = new Date(ms);
  return d.toLocaleDateString('en-US', Object.assign({ weekday: 'short' }, CT)) + ' ' +
    d.toLocaleDateString('en-US', Object.assign({ month: '2-digit', day: '2-digit' }, CT)) + ' ' +
    d.toLocaleTimeString('en-US', Object.assign({ hour: '2-digit', minute: '2-digit', hour12: true }, CT)) + ' CT';
}
function ageLabel(sec) {        // as time_et.age_label words it: "7s", "3m", "2h"
  const s = Math.round(sec);
  return s < 90 ? s + 's' : s < 5400 ? Math.round(s / 60) + 'm' : Math.round(s / 3600) + 'h';
}

// One LEVELONE_EQUITIES message: LAST_PRICE and its trade time, and any other fields Schwab sent
// (`fields`, by Schwab's names). A spec may give it `feed_live: false` and an `outage` (the
// daemon's verdict for its symbol, stood in for).
function schwabQuote(key, last, fields) {
  return { service: 'LEVELONE_EQUITIES', key: key, schwab_ts: Date.now(), ts_recv: Date.now() / 1000,
    content: Object.assign({ key: key, LAST_PRICE: last, TRADE_TIME_MILLIS: Date.now() - 1000 }, fields || {}) };
}

// One book message as the daemon sends it: Schwab's item as sent and its levels (STAND-IN for
// engine.book_levels, proven on real books in tests/test_live_ui_daemon_to_browser_v1.py: a real
// item's levels are each level's price and TOTAL_VOLUME, in Schwab's order)
function schwabBook(service, key, item, tsRecv, timeCt) {
  return { service: service, key: key, schwab_ts: item.BOOK_TIME, ts_recv: tsRecv, content: Object.assign({}, item, { key: key }),
    time_ct: timeCt, levels: { bids: (item.BIDS || []).map((l) => [l.BID_PRICE, l.TOTAL_VOLUME]),
      asks: (item.ASKS || []).map((l) => [l.ASK_PRICE, l.TOTAL_VOLUME]) } };
}

//: each page's daemon stand-in: its beat (send now, with trades labels overridden), its close
const _daemons = new WeakMap();
const _down = new WeakSet();

async function mockPriceSocket(page, messages) {
  await page.routeWebSocket(/127\.0\.0\.1:1\/$/, (ws) => {
    if (_down.has(page)) { ws.close(); return; }
    let keys = [], closed = false;
    const trade = {}, verdict = {}, override = {};
    const send = (m) => { if (!closed) { try { ws.send(JSON.stringify(m)); } catch (e) { closed = true; } } };
    function beat() {
      const state = {}, trades = {};
      keys.forEach((k) => {
        state[k] = {};
        // as the daemon judges: live once Schwab has posted to the symbol on the service, not before
        SERVICES.forEach((svc) => { state[k][svc] = verdict[k + '|' + svc] || { live: false, outage: null }; });
        if (trade[k] != null) {
          trades[k] = Object.assign({ time_ct: ctLabel(trade[k]), age: ageLabel((Date.now() - trade[k]) / 1000) }, override[k]);
        }
      });
      send({ type: 'feed', feed: null, state: state, trades: trades });
    }
    const timer = setInterval(beat, 1000);
    ws.onClose(() => { closed = true; clearInterval(timer); });
    // one Schwab message to the page, as the daemon sends it, then a beat
    const sentBars = {};                       // each key's bars sent, as the daemon's store holds them
    let chart = null;                          // the key the page's chart draws
    function deliver(q) {
      if (q.bar) (sentBars[q.key] || (sentBars[q.key] = [])).push(q.bar);
      if (q.content.TRADE_TIME_MILLIS != null) trade[q.key] = q.content.TRADE_TIME_MILLIS;
      verdict[q.key + '|' + q.service] = 'feed_live' in q ? { live: q.feed_live, outage: q.outage } : { live: true, outage: null };
      // a bar goes to the page whose chart draws its ticker, with what the daemon's series did
      // with it (a spec's bars are each a new newest minute) and the series' newest bar
      if (!q.bar || q.key === chart) {
        send({ type: 'schwab', messages: [{ service: q.service, key: q.key, schwab_ts: q.schwab_ts, ts_recv: q.ts_recv,
          content: q.content, bar: q.bar, time_ct: q.time_ct, levels: q.levels, absent: q.absent,
          series_op: q.bar ? (q.series_op ? q.series_op : 'append') : undefined,
          last_bar: q.bar ? { t: q.bar.t, label: q.time_ct } : undefined }] });
      }
      beat();
    }
    _daemons.set(page, { beat: (labels) => { Object.assign(override, labels); beat(); }, close: () => ws.close(), deliver: deliver,
      series: (key, bars, lastBar) => send({ type: 'series', key: key, bars: bars, last_bar: lastBar }) });
    // the chart ticker's 1-minute series, whole, as the daemon sends it (live_ui series_of):
    // STAND-IN, the spec's own bars (its /api/bars1m stub, read as the console stand-in reads one)
    async function sendSeries(key) {
      const a = await page.evaluate(async (u) => {
        try { const r = await fetch(u, { cache: 'no-store', headers: { 'x-ed-stand-in': 'daemon' } }); return r.ok ? await r.json() : null; }
        catch (e) { return null; }
      }, '/api/bars1m?ticker=' + encodeURIComponent(key) + '&tf=1&limit=1200').catch(() => null);
      // as the daemon's: every bar it holds, the ones it has already sent included, one per minute
      const byT = {};
      (a && Array.isArray(a.bars) ? a.bars : []).concat(sentBars[key] || []).forEach((b) => { byT[b.t] = b; });
      const bars = Object.keys(byT).map(Number).sort((x, y) => x - y).map((t) => byT[t]);
      send({ type: 'series', key: key, bars: bars, last_bar: a && a.last_bar ? a.last_bar : null });
    }
    let sent = false;
    ws.onMessage(async (m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || req.op !== 'subscribe' || !Array.isArray(req.symbols)) return;
      const symbols = req.symbols.map(served);
      keys = symbols.map((s) => s.key);
      send({ type: 'symbols', symbols: symbols });
      beat();
      // as the daemon: a new chart's series whole, by the daemon's key, before any bar after it
      const want = typeof req.chart === 'string' && req.chart ? served(req.chart).key : null;
      if (want !== chart) {
        chart = want;
        if (chart) await sendSeries(chart);
      }
      if (sent) return;                       // each spec message is Schwab's, sent once
      sent = true;
      (messages || []).forEach((q, i) => setTimeout(() => deliver(q), 300 * i));
    });
  });
}

// The daemon beats now, its trades' labels as given ({key: {time_ct, age}}).
function daemonBeat(page, labels) {
  const d = _daemons.get(page);
  if (d) d.beat(labels || {});
}

// The daemon's socket goes down and stays down: the open socket closes and every reconnect is
// closed at once, as when the daemon has stopped.
function daemonDown(page) {
  _down.add(page);
  const d = _daemons.get(page);
  if (d) d.close();
}

// Schwab messages the daemon sends now, in order (a spec's later messages)
function daemonSend(page, messages) {
  const d = _daemons.get(page);
  if (d) messages.forEach(d.deliver);
}

// The daemon sends `key`'s 1-minute series whole again (a page reconnecting, a /pricehistory answer)
function daemonSeries(page, key, bars, lastBar) {
  const d = _daemons.get(page);
  if (d) d.series(key, bars, lastBar);
}

module.exports = { mockPriceSocket, schwabQuote, schwabBook, daemonBeat, daemonDown, daemonSend, daemonSeries };
