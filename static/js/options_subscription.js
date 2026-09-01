/**
 * Options contract subscription binding (PR214 merge blocker 1B/1C/1D).
 *
 * ONE CONTRACT IDENTITY must bind: operator selection -> subscription request ->
 * subscription acknowledgement -> active stream contract -> book payload -> stream
 * health -> UI rendering. Before this module, static/options.html committed the
 * selection and started polling IMMEDIATELY on click, fired the subscribe POST as
 * `.catch(function(){})` fire-and-forget, and rendered health without ever comparing
 * the plane's contract to the selected one -- so a failed, mismatched or stale
 * subscription could display a healthy state belonging to a different contract.
 *
 * Loaded before the inline app script in options.html; exposed as
 * globalThis.EdOptionsSubscription so tests/l1 diagnostics can execute the REAL
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
      /** True only for the newest outstanding attempt. */
      isCurrent: function (token) {
        return token === currentToken;
      },
      /** The contract of the newest attempt (what any commit must agree with). */
      pendingContract: function () {
        return currentContract;
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

  /**
   * Is the streaming plane's health actually ABOUT the contract on screen?
   *
   * Refuses binding when the server states a mismatch (`contract_match === false`) and,
   * independently, when the plane names a different active contract than the selected
   * one. `contract_match === undefined` on an older payload is not treated as a pass --
   * the identity comparison still runs. Absence of evidence is never binding.
   */
  function planeIsBoundToContract(plane, selectedContract) {
    const p = plane || {};
    if (p.contract_match === false) return false;
    const sel = selectedContract == null ? '' : String(selectedContract);
    if (!sel) return false;
    const active = p.option_contract == null ? '' : String(p.option_contract);
    if (active && active !== sel) return false;
    if (p.contract_match === true) return true;
    // No server verdict: bound only if the plane names this exact contract.
    return active === sel;
  }

  /**
   * Subscription state for the contract on screen, from the plane's producer truth
   * (PR214 premerge gap 1B).
   *
   * A successful POST proves only that the subscription REQUEST was accepted -- the
   * server wrote its desired-state signal file. It does NOT prove the daemon has
   * completed the LEVELONE_OPTIONS / OPTIONS_BOOK subscriptions; that happens on the
   * daemon's own poll cadence, some time later. Calling that "subscribed" would paint a
   * false green across exactly the signal-file -> daemon-subscribe transition window.
   *
   * Returns one of:
   *   'none'      no contract selected
   *   'pending'   requested, producer has not yet confirmed BOTH services
   *   'subscribed' producer confirmed this contract on both services
   */
  function subscriptionState(plane, selectedContract) {
    const sel = selectedContract == null ? '' : String(selectedContract);
    if (!sel) return 'none';
    const p = plane || {};
    if (p.contract_match === true) return 'subscribed';
    if (p.contract_match === false) return 'pending';
    // No server verdict available (older payload / plane not yet read): fall back to the
    // producer identities themselves, and require BOTH. Never infer from requested state.
    const l1 = p.producer_l1_contract == null ? '' : String(p.producer_l1_contract);
    const book = p.producer_book_contract == null ? '' : String(p.producer_book_contract);
    return (l1 === sel && book === sel) ? 'subscribed' : 'pending';
  }

  g.EdOptionsSubscription = {
    validateSubscriptionAck: validateSubscriptionAck,
    createSubscriptionGate: createSubscriptionGate,
    planeIsBoundToContract: planeIsBoundToContract,
    subscriptionState: subscriptionState,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
