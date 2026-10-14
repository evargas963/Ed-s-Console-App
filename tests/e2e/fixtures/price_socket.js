// The capture daemon's Schwab socket (app/market_data/schwab/streaming/live_ui.py), stood in for.
// The console serves the page port 1 under e2e (playwright.config ED_LIVE_UI_PORT), so the page
// never reaches a real daemon. Like the daemon, it answers a subscribe with what each asked-for
// symbol is ({type:'symbols'}: requested, key, display), sends each LEVELONE_EQUITIES message 300 ms
// apart ({type:'schwab'}: the fields Schwab sent, by Schwab's names), and beats every second
// ({type:'feed'}: each symbol's verdict and its last trade's time and age, as the daemon words them,
// time_et.ct_label / age_label). STAND-IN (named): instrument_identity's index roots; the verdict
// (live, unless a spec's message names an outage); the labels' words (the daemon's own are proven
// in tests/test_live_ui_daemon_to_browser_v1.py).
const INDEX_ROOTS = new Set(['SPX', 'NDX', 'VIX', 'DJI', 'COMPX', 'RUT']);
function served(s) {
  const u = String(s).toUpperCase();
  const key = u.startsWith('$') || !INDEX_ROOTS.has(u) ? u : '$' + u;
  return { requested: s, key: key, display: key.replace(/^\$/, '') };
}
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
        state[k] = { LEVELONE_EQUITIES: verdict[k] || { live: true, outage: null } };
        if (trade[k] != null) {
          trades[k] = Object.assign({ time_ct: ctLabel(trade[k]), age: ageLabel((Date.now() - trade[k]) / 1000) }, override[k]);
        }
      });
      send({ type: 'feed', feed: null, state: state, trades: trades });
    }
    const timer = setInterval(beat, 1000);
    ws.onClose(() => { closed = true; clearInterval(timer); });
    _daemons.set(page, { beat: (labels) => { Object.assign(override, labels); beat(); }, close: () => ws.close() });
    let sent = false;
    ws.onMessage((m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || req.op !== 'subscribe' || !Array.isArray(req.symbols)) return;
      const symbols = req.symbols.map(served);
      keys = symbols.map((s) => s.key);
      send({ type: 'symbols', symbols: symbols });
      beat();
      if (sent) return;                       // each spec message is Schwab's, sent once
      sent = true;
      (messages || []).forEach((q, i) => setTimeout(() => {
        if (q.content.TRADE_TIME_MILLIS != null) trade[q.key] = q.content.TRADE_TIME_MILLIS;
        if ('feed_live' in q) verdict[q.key] = { live: q.feed_live, outage: q.outage };
        send({ type: 'schwab', messages: [{ service: q.service, key: q.key, schwab_ts: q.schwab_ts, ts_recv: q.ts_recv,
          content: q.content, bar: q.bar, time_ct: q.time_ct }] });
        beat();
      }, 300 * i));
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

module.exports = { mockPriceSocket, schwabQuote, daemonBeat, daemonDown };
