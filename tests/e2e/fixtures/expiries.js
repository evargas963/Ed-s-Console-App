const { mockPriceSocket } = require('./price_socket');

// The expiry list as server.expiries produces it for the page's socket: each listed expiry, Schwab's
// daysToExpiration as sent (`dte`, null when not sent), each expiry's date label (MM/DD/YYYY) and
// days text ("<n>DTE", null when not sent), and a reason only when none is listed.
function expiriesAnswer(expiries, dte = {}) {
  const sent = Object.fromEntries(expiries.map((e) => [e, e in dte ? dte[e] : null]));
  return {
    expiries: expiries,
    dte: sent,
    labels: Object.fromEntries(expiries.map((e) => [e, e.slice(5, 7) + '/' + e.slice(8, 10) + '/' + e.slice(0, 4)])),
    dte_text: Object.fromEntries(expiries.map((e) => [e, sent[e] === null ? null : sent[e] + 'DTE'])),
    reason: expiries.length ? null : 'no expiry listed in the published chain',
  };
}
// The page's socket stood in for, sending that list for the selected ticker on each subscribe
function pushExpiries(page, expiries, dte) {
  return mockPriceSocket(page, [], [], expiriesAnswer(expiries, dte));
}
module.exports = { expiriesAnswer, pushExpiries };
