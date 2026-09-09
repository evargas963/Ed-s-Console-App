/* Ed Console — the shell's ONE streaming-control writer (RC-UI-1, gates Flow/Chain).
   All shared streaming control (active option contract, active ticker) routes through here,
   REUSING the canonical command-generation endpoints and the shipped EdOptionsSubscription
   gate/validator — no new lifecycle owner, no parallel counter.

   Two-tab safety has two layers, both already canonical:
     - SERVER: POST /api/streaming/active-option-contract admits a monotonic command_generation
       (begin_option_contract_command) and refuses a stale one with 409 {superseded:true}
       (StaleOptionCommandError) BEFORE it can write the signal file / global — so a second tab's
       older command can never overwrite newer desired state (proven server-side).
     - CLIENT: EdOptionsSubscription.createSubscriptionGate() — a newer begin() supersedes an older
       token, so a stale RESPONSE can never commit or repaint.
   This module simply funnels the shell through both; it invents neither. */
(function () {
  'use strict';
  var OS = window.EdOptionsSubscription;
  var gate = (OS && OS.createSubscriptionGate) ? OS.createSubscriptionGate() : null;
  var _desired = null;   // the contract THIS tab last requested (its intent), for binding observation

  // ONE global slot: a POST is REQUEST ACCEPTED only. A view must call status() against the live
  // plane's producer identity to decide ACTIVE vs PENDING vs MOVED, and — critically — must NOT
  // re-POST when it discovers it lost the slot to a newer legitimate selection (no oscillation).
  function status(plane, contract) {
    contract = contract || _desired;
    plane = plane || {};
    var state = (OS && OS.subscriptionState) ? OS.subscriptionState(plane, contract) : 'none';
    var bound = (OS && OS.planeIsBoundToContract) ? OS.planeIsBoundToContract(plane, contract) : false;
    // ACTIVE only when the canonical producer confirms THIS contract on both services; if the slot
    // has moved to another contract, bound=false and active=false -> the view fails visibly inactive.
    return { desired: contract, state: state, bound: bound, active: state === 'subscribed' && bound === true };
  }
  function getDesired() { return _desired; }

  function setActiveContract(contract) {
    contract = String(contract || '').trim();
    if (!contract) return Promise.resolve({ accepted: false, reason: 'empty' });
    _desired = contract;                              // this tab's intent (used by status())
    var token = gate ? gate.begin(contract) : null;   // client generation: a later begin supersedes this
    var status = null;
    return fetch('/api/streaming/active-option-contract', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contract: contract }),
    }).then(function (r) {
      status = r.status;
      return r.json().then(function (b) { return { networkError: false, status: status, body: b }; },
                           function () { return { networkError: false, status: status, body: null }; });
    }, function () {
      return { networkError: true, status: null, body: null };
    }).then(function (result) {
      // a superseded click (a newer begin() happened) is inert — never commits (client layer)
      if (gate && !gate.mayCommit(token, contract)) return { accepted: false, reason: 'superseded_client' };
      // the server's 409/superseded verdict never commits either (server layer)
      if (result.status === 409 || (result.body && result.body.superseded)) {
        return { accepted: false, reason: 'superseded_server', command_generation: result.body && result.body.command_generation };
      }
      var verdict = OS ? OS.validateSubscriptionAck(contract, result)
        : { accepted: !!(result.body && result.body.ok === true && String(result.body.contract) === contract) };
      if (!verdict.accepted) return { accepted: false, reason: verdict.reason || 'ack_not_ok' };
      return { accepted: true, contract: contract, command_generation: result.body && result.body.command_generation };
    });
  }

  function setActiveTicker(ticker) {
    // Only a view that genuinely needs the single-symbol equity BOOK/DOM should call this — NOT on
    // every shell ticker change (equity L1 is captured roster-wide). The endpoint is single-owner,
    // last-writer-wins, NOT generation-guarded (only the option-contract slot is). It returns
    // REQUEST ACCEPTED (ok + echoed ticker) but exposes NO canonical active-book-producer identity,
    // so book binding is NOT_PROVEN here — Order Flow Book must confirm from producer truth (or mark
    // NOT_PROVEN) before rendering the book as this ticker. We never manufacture success from ok alone.
    ticker = String(ticker || '').trim().toUpperCase();
    if (!ticker) return Promise.resolve({ requestAccepted: false, requested: ticker, bookBound: null });
    return fetch('/api/streaming/active-ticker', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker: ticker }),
    }).then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }, function () { return { status: r.status, body: null }; }); })
      .then(function (res) {
        // FAIL-CLOSED. The endpoint canonically echoes `ticker` (server.py:post_streaming_active_ticker,
        // both the 200 and the 500 body), so request-acceptance REQUIRES all of: HTTP 2xx, a parsed
        // JSON object, ok===true, an echoed ticker PRESENT, and that ticker exactly equal to the
        // requested canonical ticker. ok:true alone is never identity proof.
        var ok2xx = !!res && typeof res.status === 'number' && res.status >= 200 && res.status < 300;
        var b = (res && res.body && typeof res.body === 'object') ? res.body : null;
        var acked = (b && b.ticker != null) ? String(b.ticker).toUpperCase() : null;
        var accepted = ok2xx && !!b && b.ok === true && acked !== null && acked === ticker;
        return {
          requestAccepted: accepted, acknowledgedTicker: acked, requested: ticker,
          status: (res && res.status) || null,
          bookBound: null,   // NOT_PROVEN: this endpoint exposes no active-book-producer identity
        };
      }, function () { return { requestAccepted: false, acknowledgedTicker: null, requested: ticker, bookBound: null }; });
  }

  window.EdStream = { setActiveContract: setActiveContract, setActiveTicker: setActiveTicker,
    status: status, getDesired: getDesired, gate: gate };
})();
