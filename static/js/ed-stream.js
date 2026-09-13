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
  var _desiredAdditionalGen = 0;  // the _additionalGen value AT THE MOMENT _desiredAdditional
                                   // was confirmed -- see the "unchanged" short-circuit below
  var _pendingAdditional = null;  // set currently in flight, or null
  var _additionalGen = 0;         // monotonic token: only the LATEST request may commit
  // Independent-review finding (2026-09-12, state-authority review), REPRODUCED: on a
  // FRESH page, before this module has ever dispatched a single request,
  // `_desiredAdditionalGen` (0) trivially equals `_additionalGen` (0) -- a sentinel
  // meaning "never touched", not "confirmed by the server". The shell's own
  // background auto-select-on-load calls setAdditionalContracts([]) as its first-ever
  // call in the common case (no contract auto-selected), which matched that untouched
  // pair and short-circuited with accepted:true/unchanged:true WITHOUT ever contacting
  // the server -- a LOCAL DEFAULT masquerading as CONFIRMED SERVER STATE. A real
  // server that still holds some OTHER additional-contracts selection (a prior tab, a
  // server that did not reset) would never be told to clear it. `_desiredAdditionalGen
  // === _additionalGen` alone cannot distinguish "confirmed" from "never asked" --
  // an explicit flag, set true ONLY by a genuine accepted commit, is required.
  var _desiredAdditionalConfirmed = false;
  // Live-heatmap coverage (state-authority review, 2026-09-12): this endpoint/slot is
  // SINGLE-OWNER server-side (one POST replaces the whole additional-contracts set) --
  // until now the ONLY caller was Strike Detail's one selected strike's call+put. Making
  // the visible HEATMAP GRID live (not just whatever one strike happens to be selected
  // elsewhere) means a second, independent caller needs to declare its OWN demand without
  // the two callers clobbering each other (last-caller-wins would make Strike Detail and
  // the heatmap fight over this one slot on every render). `ownerKey` is optional and
  // defaults to a fixed key so every EXISTING caller (Strike Detail, every existing test)
  // is completely unaffected -- with only ever one owner registered, the "union" below is
  // exactly that owner's own set, identical to today. A caller that wants to coexist with
  // another (the heatmap) passes its own distinct ownerKey; the ACTUAL POST always carries
  // the union of every owner's current demand, deduplicated, computed fresh on every call
  // so an owner's OWN change (including going back to empty) is reflected immediately.
  var _additionalDemandByOwner = {};
  function _unionedAdditionalDemand() {
    var seen = {}, out = [];
    Object.keys(_additionalDemandByOwner).forEach(function (owner) {
      (_additionalDemandByOwner[owner] || []).forEach(function (s) {
        if (!seen[s]) { seen[s] = true; out.push(s); }
      });
    });
    return out;
  }
  function setAdditionalContracts(symbols, ownerKey) {
    var owner = ownerKey || 'default';
    _additionalDemandByOwner[owner] = (symbols || []).map(function (s) {
      return String(s || '').trim().toUpperCase();
    }).filter(function (s) { return s; });
    return _dispatchAdditionalContracts(_unionedAdditionalDemand());
  }
  function _dispatchAdditionalContracts(symbols) {
    var next = symbols || [];
    var dedup = []; next.forEach(function (s) { if (dedup.indexOf(s) < 0) dedup.push(s); });
    // Independent-review finding (2026-09-12), REPRODUCED: _desiredAdditional used to be
    // set to `dedup` HERE, unconditionally, before the fetch even started -- so a request
    // that received a real HTTP 503 still left _desiredAdditional pointing at the set that
    // was NEVER actually accepted. A second call for the identical (still-unaccepted) set
    // then matched the "unchanged" short-circuit below and reported accepted:true,
    // unchanged:true WITHOUT issuing any new HTTP request at all -- false acceptance with
    // zero retry. Fixed by only ever committing _desiredAdditional on an ACTUALLY
    // confirmed-accepted response (see the .then() below), never optimistically.
    //
    // Independent-review finding (2026-09-12), REPRODUCED, connected: the "unchanged"
    // short-circuit below used to compare ONLY against _desiredAdditional (the last
    // CONFIRMED value), ignoring whatever was currently _pendingAdditional (in flight for
    // a DIFFERENT value). Two real sequences this let through:
    //   (a) request A (pending) -> clear ([]) before A resolves: since _desiredAdditional
    //       was still [] (A never committed yet), the clear matched "unchanged" and
    //       returned accepted:true WITHOUT sending any cancellation to the server, and
    //       without bumping the generation -- A's stale in-flight token was still
    //       "current" when it eventually resolved, so A's late acceptance silently WON
    //       over the operator's clear intent.
    //   (b) accept A -> request B (pending) -> return to A before B resolves: matched
    //       "unchanged" against the confirmed A, again with no generation bump -- B's
    //       stale in-flight token was still "current" when it resolved, so B silently
    //       WON over the operator's explicit return-to-A intent.
    // The real invariant: the LATEST call always wins. "Nothing to do" is only true when
    // the requested value matches whatever is CURRENTLY AUTHORITATIVE -- the in-flight
    // request's target if one exists, else the last confirmed value -- never the
    // confirmed value alone while something else is in flight for a different target.
    //
    // Independent-review finding (2026-09-12), REPRODUCED, connected: the currentTarget
    // check above closes the case where something is CURRENTLY pending, but not the
    // case where something WAS dispatched and is no longer pending -- because its
    // outcome was either a definitive REJECTION or a SUPERSESSION whose result this
    // module chose not to trust. Two real sequences this still let through:
    //   (a) request A (pending) -> a clear ([]) FAILS (503) -> A's late response then
    //       arrives (correctly ignored, superseded) -> retrying the SAME clear again
    //       matched _desiredAdditional (still [], the untouched initial value) and
    //       reported accepted:true/unchanged:true WITHOUT a new request -- even though
    //       the server may have already applied A (that request was never confirmed
    //       either way from this module's perspective once superseded) and the FAILED
    //       clear never actually removed it.
    //   (b) accept A -> request B (pending) -> a return to A FAILS -> B's late response
    //       then arrives (correctly ignored, superseded) -> retrying the return to A
    //       again matched the STALE _desiredAdditional=A (confirmed BEFORE B was ever
    //       dispatched) and short-circuited -- even though an intervening dispatch (B)
    //       means the server's actual current state cannot be assumed to still be A
    //       without a fresh confirmation.
    // The root fix: `_desiredAdditional`'s value is trustworthy for the "nothing to do"
    // short-circuit ONLY when NOTHING has been dispatched since the tick it was last
    // confirmed -- tracked by `_desiredAdditionalGen`, which is set to match
    // `_additionalGen` ONLY at the exact moment of a genuine accepted commit. Any
    // dispatch at all (accepted, rejected, or later superseded) advances `_additionalGen`
    // without advancing `_desiredAdditionalGen`, so the cached value stops being
    // trustworthy the instant anything else is attempted, and only becomes trustworthy
    // again once a fresh accept re-synchronizes the two counters.
    var currentTarget = (_pendingAdditional !== null) ? _pendingAdditional : _desiredAdditional;
    var cacheTrustworthy = _pendingAdditional === null && _desiredAdditionalGen === _additionalGen
      && _desiredAdditionalConfirmed;
    if (cacheTrustworthy && _sortedEqual(dedup, currentTarget)) {
      return Promise.resolve({ accepted: true, unchanged: true, contracts: _desiredAdditional });
    }
    if (_pendingAdditional !== null && _sortedEqual(dedup, currentTarget)) {
      // Identical to what is ALREADY in flight -- do not fire a duplicate concurrent
      // request (Strike Detail can call this on every render); let the one in-flight
      // fetch resolve and commit on its own (its token is still current, untouched).
      return Promise.resolve({ accepted: false, unchanged: false, pending: true, contracts: dedup });
    }
    // Either the requested value genuinely DIFFERS from whatever is authoritative right
    // now, or it coincidentally matches a STALE cached value that an intervening dispatch
    // has made untrustworthy -- either way, a real new request is required to get a fresh
    // confirmation. Bump the generation so any STALE in-flight OR previously-superseded
    // request can never retroactively be treated as still authoritative.
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
          if (accepted) {
            _desiredAdditional = dedup;      // commit ONLY on a confirmed accept
            _desiredAdditionalGen = token;   // and re-synchronize the trust generation
            _desiredAdditionalConfirmed = true;   // the cache is now backed by a real ack
          }
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
