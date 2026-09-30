/**
 * Options contract subscription binding (PR214 merge blocker 1B/1C/1D).
 *
 * ONE CONTRACT IDENTITY must bind: operator selection -> subscription request ->
 * subscription acknowledgement -> active stream contract -> book payload -> stream
 * health -> UI rendering. Used by the console's stream control (ed-stream.js); exposed as
 * globalThis.EdOptionsSubscription so tests can execute the REAL
 * shipped rules rather than a re-implementation (see tests/options_subscription_node.mjs).
 */
(function (g) {
  'use strict';

  /**
   * Is a subscription acknowledgement good enough to COMMIT the selection?
   *
   * `result` is the caller's observation of the POST:
   *   { networkError: bool, status: number|null, body: object|null }
   * A commit requires ALL of: no transport error, a 2xx status, a parsed JSON object,
   * `ok === true`, and the acknowledgement echoing the EXACT contract requested.
   * Anything else returns accepted=false with a specific reason -- never a silent
   * swallow, and never a default-accept.
   */
  function validateSubscriptionAck(requestedContract, result) {
    const want = requestedContract == null ? '' : String(requestedContract);
    if (!want) return { accepted: false, reason: 'no_requested_contract' };
    const r = result || {};
    if (r.networkError) return { accepted: false, reason: 'network_error' };
    const status = Number(r.status);
    if (!Number.isFinite(status) || status < 200 || status > 299) {
      return { accepted: false, reason: 'http_status' };
    }
    const body = r.body;
    if (!body || typeof body !== 'object') return { accepted: false, reason: 'invalid_json' };
    if (body.ok !== true) return { accepted: false, reason: 'ack_not_ok' };
    if (String(body.contract) !== want) {
      return { accepted: false, reason: 'contract_mismatch' };
    }
    return { accepted: true, reason: 'ok' };
  }

  /**
   * Smallest request-generation mechanism that closes the A->B selection race:
   * every click takes a monotonically increasing token, and only the token from the
   * MOST RECENT click may commit. A late acknowledgement for an earlier contract is
   * therefore inert -- it cannot re-select, cannot start polling, and cannot overwrite
   * the newer contract's state. No framework, no cancellation plumbing.
   */
  function createSubscriptionGate() {
    let seq = 0;
    let currentToken = 0;
    let currentContract = null;
    return {
      /** Begin a selection attempt; returns the token that attempt must present later. */
      begin: function (contract) {
        seq += 1;
        currentToken = seq;
        currentContract = contract == null ? null : String(contract);
        return seq;
      },
      /**
       * A late/superseded acknowledgement must never be committed. Returns true only
       * when this token is still the newest AND its contract is still the pending one.
       */
      mayCommit: function (token, contract) {
        if (token !== currentToken) return false;
        return String(contract) === String(currentContract);
      },
    };
  }

  g.EdOptionsSubscription = {
    validateSubscriptionAck: validateSubscriptionAck,
    createSubscriptionGate: createSubscriptionGate,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
