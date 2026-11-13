// The Trade Desk's served answers the desk specs send on the socket (console-trade-desk.spec.js,
// console-liquidity-card.spec.js), and the page-error watch.
//
// The base panels are the server's own answers for SPY at 2026-11-12 10:30:41 ET
// (panels_spy_two_day.json, held to the server by tests/test_e2e_panels_two_day_v1.py): Schwab's
// chain of that instant with the prior day's close compared, its two books, the day's bars and
// price histories, and the day's recorded level crosses. The readouts are the route's answers
// for SPY's real books of 2026-11-02 (tests/test_liquidity_readout_v1.py).
const path = require('path');
const { routeWatchlist } = require('./watchlist');
const { mockPriceSocket } = require('./price_socket');

const REAL = require(path.join(__dirname, 'panels_spy_two_day.json'));
// the book the desk shows unless a test names the other, and the desk chart's opening timeframe
const VENUE = 'NASDAQ_BOOK';
const TF = '5';
const TERRAIN = REAL.terrain;
const SPOT = TERRAIN.spot;                 // 757.075, Schwab's last trade
const LEVELS = REAL.levels[TF];
const EVENTS = REAL.desk[VENUE][TF];
// the route's answers for SPY's real books (tests/test_liquidity_readout_v1.py): live, the daemon's
// connection ended, no book, and crossed inside the closing auction
const READOUT_LIVE = require(path.join(__dirname, 'liquidity_readout_live.json'));
const READOUT_OFFLINE = require(path.join(__dirname, 'liquidity_readout_offline.json'));
const READOUT_NO_BOOK = require(path.join(__dirname, 'liquidity_readout_no_book.json'));
// (the books when the composite was first crossed, read inside the closing auction window)
const READOUT_AUCTION = require(path.join(__dirname, 'liquidity_readout_close_auction.json'));
// (INDUCED: those books with NASDAQ_BOOK's NSDQ quote times taken out, the feed down: crossed,
// BOOK OFFLINE, the auction line, the not-live words and the dedup note at once)
const READOUT_EVERY_LINE = require(path.join(__dirname, 'liquidity_readout_every_line.json'));
const LIVE_COMP = READOUT_LIVE.readout.venues.COMPOSITE;
// Schwab's NASDAQ_BOOK for SPY as the book panel answers it, with its own readout
const MICRO = REAL.book[VENUE];
const LIQ = REAL.liquidity;
const STRIKES = REAL.strikes;
const BARS = REAL.bars[TF];
const HEAT = require(path.join(__dirname, 'book_heatmap_payload.json'));

// the panels the page's socket sends the page intercept last set up (a test changes one before
// the page opens, or sends it again with the returned socket's `changed`)
let panels;
function deskPanels() { return panels; }
// the page's socket sending those panels and the pushed price `rows` (mockPriceSocket)
function deskSocket(page, rows = [], later = []) { return mockPriceSocket(page, rows, later, undefined, panels); }

async function intercept(page) {
  await routeWatchlist(page, ['SPY']);
  // the page asks the venue MICRO is the book of, unless the test names another after this
  await page.addInitScript((venue) => localStorage.setItem('ed_book_venue', venue), MICRO.venue);
  // each reader is answered what the server answers its ask: the strikes window of its scope, the
  // levels and the bars of its timeframe (the flow card's are its own 60 one-minute bars), the
  // queue of its venue and timeframe, the book of its venue
  panels = { terrain: TERRAIN, liquidity: LIQ, forces: REAL.forces, bookmap: HEAT, tape: REAL.tape,
    strikes: (key, params) => (params.scope === 'wider' ? REAL.strikes_wider : STRIKES),
    levels: (key, params) => REAL.levels[params.tf],
    desk: (key, params) => REAL.desk[params.venue][params.tf],
    book: (key, params) => REAL.book[params.venue],
    bars: (key, params, name) => (name === 'bars:flow' ? REAL.bars_flow : REAL.bars[params.tf]) };
  return deskSocket(page);
}
// A per-timeframe panel's stand-in for `body` (the event window, the bars): the program answers
// each reader's timeframe in it (server.PAGE_PANELS)
function tfAt(body) {
  return (key, params) => Object.assign({}, body, { tf: params.tf });
}
// The levels panel's stand-in for `body`: the program answers each reader's timeframe with the
// levels in it (server.levels), a function of (key, params) or the same body for every one
function levelsAt(body) {
  return (key, params) => Object.assign({}, typeof body === 'function' ? body(key, params) : body, { tf: params.tf });
}

function watchErrors(page) {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  return errs;
}

module.exports = {
  REAL, VENUE, EVENTS, SPOT, TERRAIN, LEVELS, READOUT_LIVE, READOUT_OFFLINE, READOUT_NO_BOOK, READOUT_AUCTION, READOUT_EVERY_LINE, LIVE_COMP,
  MICRO, LIQ, STRIKES, BARS, HEAT, intercept, watchErrors, deskPanels, deskSocket, levelsAt, tfAt,
};
