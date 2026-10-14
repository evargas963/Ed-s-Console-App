// The console's price rows (server.live_values {type:'rows'}: live_price_rows.price_row of each
// symbol the page's view names), stood in for. STAND-IN (named): each row is built here from the
// LEVELONE_EQUITIES fields a spec gives, as live_price_rows.price_row builds it -- the price and
// its two decimals, bid/ask/sizes, Schwab's two change percents, volume, last size, Schwab's trade
// time and its label -- with the feed live and no outage (the console's real row is proven in
// tests/test_header_stream_quote_and_watchlist_push_v1.py). The rows are pushed 300 ms apart once
// the console has answered what each symbol is (tests/e2e/fixtures/live_socket.js).
const { setPrices } = require('./live_socket');

const CT = { timeZone: 'America/Chicago' };
function ctLabel(ms) {          // as time_et.ct_label words it: "Fri 09/25 06:59 PM CT"
  const d = new Date(ms);
  return d.toLocaleDateString('en-US', Object.assign({ weekday: 'short' }, CT)) + ' ' +
    d.toLocaleDateString('en-US', Object.assign({ month: '2-digit', day: '2-digit' }, CT)) + ' ' +
    d.toLocaleTimeString('en-US', Object.assign({ hour: '2-digit', minute: '2-digit', hour12: true }, CT)) + ' CT';
}

// One symbol's row from its LEVELONE_EQUITIES fields: LAST_PRICE and its trade time, and any
// other fields Schwab sent (`fields`, by Schwab's names).
function schwabQuote(key, last, fields) {
  const f = Object.assign({ LAST_PRICE: last, TRADE_TIME_MILLIS: Date.now() - 1000 }, fields || {});
  const v = (name) => (name in f ? f[name] : null);
  return { ticker: key, spot: f.LAST_PRICE, spot_disp: f.LAST_PRICE.toFixed(2), spot_source: 'streaming_plane',
    feed_live: true, outage: null, bid: v('BID_PRICE'), ask: v('ASK_PRICE'), bid_size: v('BID_SIZE'),
    ask_size: v('ASK_SIZE'), mark: v('MARK'), last_size: v('LAST_SIZE'), total_volume: v('TOTAL_VOLUME'),
    chg_pct: v('NET_CHANGE_PERCENT'), chg_pct_regular: v('REGULAR_MARKET_CHANGE_PERCENT'),
    trade_ts: f.TRADE_TIME_MILLIS / 1000, trade_time_ct: ctLabel(f.TRADE_TIME_MILLIS),
    quote_ingestion: 'schwab_streaming_level_one' };
}

async function mockPriceSocket(page, rows) {
  setPrices(page, rows || []);
}

module.exports = { mockPriceSocket, schwabQuote };
