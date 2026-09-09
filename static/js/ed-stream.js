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

  function setActiveContract(contract) {
    contract = String(contract || '').trim();
    if (!contract) return Promise.resolve({ accepted: false, reason: 'empty' });
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
    ticker = String(ticker || '').trim().toUpperCase();
    if (!ticker) return Promise.resolve({ ok: false });
    // The equity active-ticker slot is single-owner but NOT generation-guarded server-side (only the
    // option-contract slot is). Last-writer-wins, no corruption. If ticker last-writer safety is later
    // required, extend the SAME _option_command_seq mechanism server-side — never a client-side owner.
    return fetch('/api/streaming/active-ticker', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker: ticker }),
    }).then(function (r) { return r.json().then(function (b) { return b; }, function () { return {}; }); })
      .then(function (b) { return { ok: !!(b && b.ok), ticker: ticker }; }, function () { return { ok: false }; });
  }

  window.EdStream = { setActiveContract: setActiveContract, setActiveTicker: setActiveTicker, gate: gate };
})();
