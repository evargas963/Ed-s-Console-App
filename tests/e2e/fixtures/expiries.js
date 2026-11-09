const { mockPriceSocket } = require('./price_socket');

// The expiry list as server.expiries produces it for the page's socket: each listed expiry, Schwab's
// daysToExpiration as sent (`dte`), each expiry's dropdown label (MM/DD/YYYY, then " · <n>DTE"
// when its days are sent), and a reason only when none is listed.
function expiriesAnswer(expiries, dte) {
  const labels = {};
  expiries.forEach((e) => {
    const date = e.slice(5, 7) + '/' + e.slice(8, 10) + '/' + e.slice(0, 4);
    labels[e] = e in dte ? date + ' · ' + dte[e] + 'DTE' : date;
  });
  return {
    expiries: expiries,
    dte: dte,
    labels: labels,
    reason: expiries.length ? null : 'no expiry listed in the published chain',
  };
}
// The page's socket stood in for, sending that list for the selected ticker on each subscribe
function pushExpiries(page, expiries, dte = {}) {
  return mockPriceSocket(page, [], [], expiriesAnswer(expiries, dte));
}
module.exports = { expiriesAnswer, pushExpiries };
