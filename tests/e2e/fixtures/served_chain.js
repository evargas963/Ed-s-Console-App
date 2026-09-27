// The /api/chain fields the server derives from `contracts` (terrain_engine.chain_ladder): a mock
// carries them as the real route does. Mirrors the producer; tests/test_chain_ladder_v1.py holds
// the producer itself to real data.
function served(d) {
  const byK = new Map();
  for (const c of d.contracts || []) {
    const k = Number(c.strikePrice);
    if (!byK.has(k)) byK.set(k, { call: [], put: [] });
    byK.get(k)[String(c.putCall).toUpperCase() === 'PUT' ? 'put' : 'call'].push(c);
  }
  const ks = [...byK.keys()].sort((a, b) => b - a);
  const spot = d.spot == null ? null : Number(d.spot);
  const ladder = [];
  for (const k of ks) {
    const g = byK.get(k);
    for (let i = 0; i < Math.max(g.call.length, g.put.length); i++) {
      ladder.push({ strike: k, first: i === 0, spot: i === 0 && k === d.spot_strike,
        call: g.call[i] || null, put: g.put[i] || null,
        call_itm: spot == null ? null : k < spot, put_itm: spot == null ? null : k > spot });
    }
  }
  return Object.assign({}, d, { ladder, n_strikes: ks.length });
}
module.exports = { served };
