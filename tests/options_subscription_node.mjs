/**
 * Node assertions for static/js/options_subscription.js (vm load — no bundler).
 * Executes the REAL shipped rules, never a re-implementation.
 *
 * Covers PR214 merge blocker 1E cases 3-8:
 *   3. POST network/non-2xx failure -> no polling
 *   4. POST ok:false               -> no polling
 *   5. POST returns a different contract -> no polling
 *   6. exact successful acknowledgement -> polling begins
 *   7. late A acknowledgement after successful B -> B remains active
 *   8. UI health cannot green an identity mismatch
 *
 * Run: node tests/options_subscription_node.mjs
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const code = readFileSync(join(ROOT, 'static/js/options_subscription.js'), 'utf8');
vm.runInThisContext(code, { filename: 'options_subscription.js' });

const S = globalThis.EdOptionsSubscription;
assert.ok(S, 'EdOptionsSubscription must be exposed by the shipped module');

const A = 'SPY   260820C00767000';
const B = 'QQQ   260820C00450000';

// ── 3. network error / non-2xx must NOT accept ───────────────────────────────
assert.deepStrictEqual(
  S.validateSubscriptionAck(A, { networkError: true, status: null, body: null }),
  { accepted: false, reason: 'network_error' },
);
assert.strictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 500, body: { ok: true, contract: A } }).accepted,
  false, 'a 500 must not be committed even with an ok:true body',
);
assert.strictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 404, body: null }).accepted, false,
);
// invalid / unparseable JSON
assert.deepStrictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: null }),
  { accepted: false, reason: 'invalid_json' },
);

// ── 4. ok:false must NOT accept ──────────────────────────────────────────────
assert.deepStrictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: { ok: false, contract: A } }),
  { accepted: false, reason: 'ack_not_ok' },
);
// truthy-but-not-true must not sneak through
assert.strictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: { ok: 1, contract: A } }).accepted,
  false, 'ok must be strictly true, not merely truthy',
);

// ── 5. acknowledgement for a DIFFERENT contract must NOT accept ──────────────
assert.deepStrictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: { ok: true, contract: B } }),
  { accepted: false, reason: 'contract_mismatch' },
);
assert.strictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: { ok: true } }).accepted,
  false, 'a missing contract echo is a mismatch, not a pass',
);

// ── 6. exact successful acknowledgement accepts ──────────────────────────────
assert.deepStrictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: { ok: true, contract: A } }),
  { accepted: true, reason: 'ok' },
);

// ── 7. late A acknowledgement after successful B: B remains active ───────────
// Behavioral attack: issue A, issue B, resolve B, then resolve A LATE.
const gate = S.createSubscriptionGate();
const tokenA = gate.begin(A);
const tokenB = gate.begin(B);
assert.strictEqual(gate.mayCommit(tokenB, B), true, 'B is the newest attempt and may commit');
// ...B commits here...
assert.strictEqual(gate.mayCommit(tokenA, A), false,
  'the LATE A acknowledgement must be inert: it may not re-select A, start A polling, or overwrite B');
assert.strictEqual(gate.pendingContract(), B, 'FINAL selected/poll target must remain B');
// A's ack being independently VALID changes nothing — the gate, not the ack, decides.
assert.strictEqual(
  S.validateSubscriptionAck(A, { networkError: false, status: 200, body: { ok: true, contract: A } }).accepted,
  true, 'A\'s ack is valid in isolation...');
assert.strictEqual(gate.mayCommit(tokenA, A), false, '...and still must not commit');
// A stale token cannot commit even under the CURRENT contract name.
assert.strictEqual(gate.mayCommit(tokenA, B), false);
// The newest attempt may not commit a contract it did not request.
assert.strictEqual(gate.mayCommit(tokenB, A), false);

// ── 8. UI health cannot green an identity mismatch ───────────────────────────
// Server states the mismatch explicitly.
assert.strictEqual(
  S.planeIsBoundToContract({ option_contract: B, contract_match: false, streaming_healthy: true }, A),
  false, 'contract_match:false must never render bound, however healthy the plane claims to be');
// Server field absent (older payload): identity comparison still refuses.
assert.strictEqual(
  S.planeIsBoundToContract({ option_contract: B, streaming_healthy: true }, A),
  false, 'a plane naming a different active contract is unbound even with no contract_match field');
// Correctly bound.
assert.strictEqual(
  S.planeIsBoundToContract({ option_contract: A, contract_match: true, streaming_healthy: true }, A),
  true);
assert.strictEqual(
  S.planeIsBoundToContract({ option_contract: A, streaming_healthy: true }, A),
  true, 'identity agreement alone is sufficient when the server states no verdict');
// No committed selection -> nothing is bound (the pending-subscription state).
assert.strictEqual(S.planeIsBoundToContract({ option_contract: A, contract_match: true }, null), false);
assert.strictEqual(S.planeIsBoundToContract({}, A), false,
  'an empty plane names no contract and must not be treated as bound');

console.log('options_subscription_node: ok');
