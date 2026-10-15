// /api/expiries as server.get_expiries answers it, stood in for: each listed expiry with its
// dropdown label (MM/DD/YYYY; these stand-ins carry no daysToExpiration), and with none the reason.
function expiriesAnswer(exps) {
  const labels = {};
  exps.forEach((e) => { labels[e] = e.slice(5, 7) + '/' + e.slice(8, 10) + '/' + e.slice(0, 4); });
  return { expiries: exps, dte: {}, labels: labels, reason: exps.length ? null : 'no expiry listed in the published chain' };
}
module.exports = { expiriesAnswer };
