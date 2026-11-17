// The chain panel's fields the program derives from `contracts` (terrain_engine.chain_ladder): a
// mock carries them as the real panel does. Mirrors the producer; tests/test_chain_ladder_v1.py holds
// the producer itself to real data, and tests/test_served_numbers_v1.py its texts: a strike as
// listed (numeric_contract.strike_text), the spot two decimals (price_text).
function strikeText(k) {
  return k.toFixed(2).replace(/\.?0+$/, "");
}
function served(d) {
  const byK = new Map();
  for (const c of d.contracts) {
    const k = Number(c.strikePrice);
    if (!byK.has(k)) byK.set(k, { call: [], put: [] });
    byK.get(k)[String(c.putCall).toUpperCase() === "PUT" ? "put" : "call"].push(c);
  }
  const ks = [...byK.keys()].sort((a, b) => b - a);
  const spot = d.spot == null ? null : Number(d.spot);
  const ladder = [];
  for (const k of ks) {
    const g = byK.get(k);
    for (let i = 0; i < Math.max(g.call.length, g.put.length); i++) {
      ladder.push({
        strike: k,
        strike_text: strikeText(k),
        first: i === 0,
        spot: i === 0 && k === d.spot_strike,
        call: i < g.call.length ? g.call[i] : null,
        put: i < g.put.length ? g.put[i] : null,
        call_itm: spot == null ? null : k < spot,
        put_itm: spot == null ? null : k > spot,
      });
    }
  }
  return Object.assign({}, d, {
    ladder,
    n_strikes: ks.length,
    spot_text: spot == null ? null : spot.toFixed(2),
  });
}
module.exports = { served };
