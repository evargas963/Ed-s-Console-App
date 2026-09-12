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
  var _accepted = false; // whether the POST for the CURRENT _desired was accepted (control-request state)
  var _ctl = 'none';     // control-request lifecycle for the CURRENT desired: none|requested|accepted|failed

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
  // control-request state (belongs to the ONE owner, not to Flow/Chain/ed-core/localStorage):
  // whether the current desired contract's POST was ACCEPTED. Not the same as ACTIVE (that needs
  // producer binding via status()). A view must not poll a contract that was never accepted.
  function acceptedForDesired() { return _accepted === true && _desired != null; }
  // control-request lifecycle for the current desired contract (Flow uses it to fail closed: only
  // 'accepted' begins microstructure observation; 'requested' shows pending; 'failed' never polls).
  function controlState() { return _desired == null ? 'none' : _ctl; }
  // clear THIS tab's local intent (ticker/expiry context change). LOCAL ONLY — never POSTs, never
  // fights the global slot; a fresh explicit selection is required to request a contract again.
  function clearDesired() { _desired = null; _accepted = false; _ctl = 'none'; }

  function setActiveContract(contract) {
    contract = String(contract || '').trim();
    if (!contract) return Promise.resolve({ accepted: false, reason: 'empty' });
    _desired = contract;                              // this tab's intent (used by status())
    _accepted = false; _ctl = 'requested';            // POST in flight — not accepted until a validated ACK
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
        if (_desired === contract) _ctl = 'failed';
        return { accepted: false, reason: 'superseded_server', command_generation: result.body && result.body.command_generation };
      }
      var verdict = OS ? OS.validateSubscriptionAck(contract, result)
        : { accepted: !!(result.body && result.body.ok === true && String(result.body.contract) === contract) };
      if (!verdict.accepted) { if (_desired === contract) _ctl = 'failed'; return { accepted: false, reason: verdict.reason || 'ack_not_ok' }; }
      if (_desired === contract) { _accepted = true; _ctl = 'accepted'; }   // accepted ONLY for the still-current desired
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

  // RC-UI-3 (2026-09-12): the ADDITIONAL-contracts slot, beside the ONE primary contract
  // above -- POST /api/streaming/active-option-contracts, mirrored server-side on its own
  // independent generation counter (server.py:post_streaming_active_option_contracts /
  // app.options.order_flow.streaming.set_active_option_contracts). Deliberately simpler
  // than setActiveContract: there is no per-view "is THIS additional contract active"
  // status the shell renders today (unlike Flow's subscribe-state badge), so this is a
  // fire-and-forget request-acceptance report, deduplicated against this tab's own last
  // request so a caller may call it on every render without spamming the endpoint.
  function _sortedEqual(a, b) {
    if (a.length !== b.length) return false;
    var as = a.slice().sort(), bs = b.slice().sort();
    for (var i = 0; i < as.length; i++) { if (as[i] !== bs[i]) return false; }
    return true;
  }
  var _desiredAdditional = [];    // last set a response actually CONFIRMED accepted
  var _pendingAdditional = null;  // set currently in flight, or null
  var _additionalGen = 0;         // monotonic token: only the LATEST request may commit
  function setAdditionalContracts(symbols) {
    var next = (symbols || []).map(function (s) { return String(s || '').trim().toUpperCase(); })
      .filter(function (s) { return s; });
    var dedup = []; next.forEach(function (s) { if (dedup.indexOf(s) < 0) dedup.push(s); });
    // Independent-review finding (2026-09-12), REPRODUCED: _desiredAdditional used to be
    // set to `dedup` HERE, unconditionally, before the fetch even started -- so a request
    // that received a real HTTP 503 still left _desiredAdditional pointing at the set that
    // was NEVER actually accepted. A second call for the identical (still-unaccepted) set
    // then matched the "unchanged" short-circuit below and reported accepted:true,
    // unchanged:true WITHOUT issuing any new HTTP request at all -- false acceptance with
    // zero retry. Fixed by only ever committing _desiredAdditional on an ACTUALLY
    // confirmed-accepted response (see the .then() below), never optimistically.
    if (_sortedEqual(dedup, _desiredAdditional)) {
      return Promise.resolve({ accepted: true, unchanged: true, contracts: _desiredAdditional });
    }
    // A second call for the exact set ALREADY in flight must not fire a duplicate
    // concurrent request (Strike Detail can call this on every render) -- report it as
    // still pending rather than fabricating either an accepted or a fresh-request result.
    if (_pendingAdditional && _sortedEqual(dedup, _pendingAdditional)) {
      return Promise.resolve({ accepted: false, unchanged: false, pending: true, contracts: dedup });
    }
    var token = ++_additionalGen;   // supersedes any earlier in-flight request's ability to commit
    _pendingAdditional = dedup;
    return fetch('/api/streaming/active-option-contracts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contracts: dedup }),
    }).then(function (r) {
      return r.json().then(function (b) { return { status: r.status, body: b }; },
                           function () { return { status: r.status, body: null }; });
    }, function () { return { status: null, body: null }; })
      .then(function (res) {
        var isCurrent = token === _additionalGen;
        var ok2xx = typeof res.status === 'number' && res.status >= 200 && res.status < 300;
        var b = (res.body && typeof res.body === 'object') ? res.body : null;
        // Identity check (independent-review finding: "a successful response acknowledging
        // the wrong contract set" must not be treated as acceptance of THIS request's set)
        // -- the server echoes `contracts` in its response; it must match what was sent,
        // exactly like setActiveContract's own ack-identity check above.
        var acked = (b && Array.isArray(b.contracts))
          ? b.contracts.map(function (s) { return String(s || '').toUpperCase(); }) : null;
        var identityOk = acked !== null && _sortedEqual(acked, dedup);
        var accepted = ok2xx && !!b && b.ok === true && identityOk;
        if (isCurrent) {
          if (accepted) _desiredAdditional = dedup;   // commit ONLY on a confirmed accept
          _pendingAdditional = null;
        }
        return { accepted: accepted, unchanged: false, contracts: dedup, status: res.status,
                 superseded: !isCurrent };
      });
  }
  function getDesiredAdditional() { return _desiredAdditional.slice(); }

  window.EdStream = { setActiveContract: setActiveContract, setActiveTicker: setActiveTicker,
    setAdditionalContracts: setAdditionalContracts, getDesiredAdditional: getDesiredAdditional,
    status: status, getDesired: getDesired, acceptedForDesired: acceptedForDesired,
    controlState: controlState, clearDesired: clearDesired, gate: gate };
})();
