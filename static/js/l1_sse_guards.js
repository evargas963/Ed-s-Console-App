/**
 * Shared L1 SSE + Tier B light guards (single source for monotonic l1_generation and scope keys),
 * plus a generic coalesced-async-trigger guard (makeCoalescedLoader) used by every push-driven
 * view module. Loaded before inline app script in index.html; exposed as globalThis.EdL1SseGuards
 * for tests/diagnostics.
 *
 * Ordering: l1_generation is authoritative for strict ordering. When generations match (reordered delivery),
 * _server_build_ts tie-break rejects strictly older snapshots so HTTP↔SSE cannot regress UI.
 */
(function (g) {
  'use strict';

  /** Align client expiry with server _l1_scope_key / stream subscription key. */
  function normL1ExpiryKey(exp) {
    if (exp == null || exp === '') return '__auto__';
    const s = String(exp).trim();
    if (!s) return '__auto__';
    if (s === '__auto__') return '__auto__';
    return s.length >= 10 ? s.slice(0, 10) : s;
  }

  /**
   * Apply monotonic l1_generation for a scope; mutates store. Returns false if strictly stale (g < prev).
   * @deprecated Prefer l1ApplyTierBLightMonotonic for HTTP+SSE mixed delivery.
   */
  function l1ApplyGenerationMonotonic(scopeKey, g, store) {
    return l1ApplyTierBLightMonotonic(scopeKey, g, store, NaN, null);
  }

  /**
   * Monotonic l1_generation plus optional _server_build_ts tie-break when g ties (same-generation reorder).
   * Mutates genStore; updates tsStore when serverTs is finite.
   */
  function l1ApplyTierBLightMonotonic(scopeKey, g, genStore, serverTs, tsStore) {
    if (!genStore) genStore = {};
    if (g == null || typeof g !== 'number' || !Number.isFinite(g)) return true;
    const prev = genStore[scopeKey];
    const lastTs = tsStore && Number.isFinite(tsStore[scopeKey]) ? tsStore[scopeKey] : NaN;
    if (prev != null && g < prev) return false;
    if (prev != null && g === prev) {
      if (Number.isFinite(serverTs) && Number.isFinite(lastTs) && serverTs < lastTs) {
        return false;
      }
    }
    genStore[scopeKey] = Math.max(prev || 0, g);
    if (tsStore && Number.isFinite(serverTs)) {
      const base = Number.isFinite(lastTs) ? lastTs : 0;
      tsStore[scopeKey] = Math.max(base, serverTs);
    }
    return true;
  }

  /**
   * Tier B PAYLOAD vs active (ticker, expiry) — the auto-scope acceptance rule.
   *
   * L1-SSE-AUTO-ACCEPT (2026-07-22, measured live): with no explicit expiry the
   * client subscribes "__auto__" ("whatever is current"), but every L1 payload
   * that merged L2 data carries the RESOLVED selected_exp (e.g. "2026-07-22").
   * The old inline matcher required strict key equality, so in auto mode it
   * rejected 100% of delivered payloads (rejectedTierBRender=2076, accepted=0
   * on a live tab) and the Tier B light lane never painted. Auto accepts any
   * payload expiry for the active ticker; an explicitly pinned expiry stays
   * strict — same semantics as the server's __auto__ scope maintenance.
   */
  function l1PayloadMatchesActiveScope(payloadTicker, payloadSelectedExp, activeTicker, activeExpiry) {
    const pt = payloadTicker != null ? String(payloadTicker).trim().toUpperCase() : '';
    if (!pt) return false;
    const at = (activeTicker || '').trim().toUpperCase() || 'SPY';
    if (pt !== at) return false;
    const ck = normL1ExpiryKey(activeExpiry);
    if (ck === '__auto__') return true;
    return normL1ExpiryKey(payloadSelectedExp) === ck;
  }

  /**
   * Server envelope scope: { ticker, expiry } where expiry is "__auto__" or a date key.
   */
  function l1EnvelopeScopeMatches(scope, activeTicker, activeExpiry) {
    if (!scope || typeof scope !== 'object') return false;
    const st = scope.ticker != null ? String(scope.ticker).trim().toUpperCase() : '';
    const at = (activeTicker || '').trim().toUpperCase() || 'SPY';
    if (st !== at) return false;
    const se = scope.expiry != null ? String(scope.expiry).trim() : '';
    const ck = normL1ExpiryKey(activeExpiry);
    const sk = normL1ExpiryKey(se === '' ? null : se);
    return ck === sk;
  }

  /**
   * Coalesced "no overlap, nothing dropped" async trigger (RC-UI-1 round 7, 2026-09-13).
   *
   * Root cause this fixes: server.py's refresh_gamma_surface_from_stream pushes a
   * `gamma_surface_seq` SSE event on every streamed publish — unboundedly frequent, not the
   * 12s slow-poll tick it rides in on (ed-core.js dispatches it as `ed:refresh{slow:true,
   * pushed:true}`, reusing the same event the slow poll uses). Every one of the six gamma
   * view modules (heatmap, chart, levels, chain, flow, panels) responds to that event by
   * calling its own load(): bump a per-module generation counter, start a fetch, and apply
   * the response only if the counter still matches when it resolves. That guard is correct
   * for invalidating a genuinely stale context (a ticker switch mid-flight) but fails once
   * triggers arrive faster than the round trip: a new trigger bumps the counter before the
   * PREVIOUS fetch can land, so that response is discarded on arrival — and since triggers
   * never stop arriving under continuous streaming, no response's generation ever survives
   * to be applied. Controlled reproduction (2026-09-13): 500ms triggers against a 750ms
   * round trip left the display frozen at its starting value while incoming values advanced
   * far past it, updating only once the triggers stopped and one response finally landed
   * unopposed. Confirmed live-lock, not merely staleness.
   *
   * The fix is not a faster fetch or a slower trigger — it is making the trigger→fetch
   * relationship itself correct under arbitrary trigger rates: never more than one fetch in
   * flight per loader, and a trigger arriving mid-flight is coalesced into exactly one
   * trailing re-run (never dropped, never piled up). That guarantees liveness — the loader
   * always converges to the latest state as fast as the round trip allows — without giving
   * up the context-invalidation the per-call generation check still does INSIDE `run` (the
   * caller decides, at resolution time, whether the answer is still for a context anyone
   * wants; see e.g. ed-gamma.js's `stillCurrent`). Deliberately not a fixed-rate throttle:
   * throttling would reintroduce exactly the latency round 6 was built to remove.
   *
   * @param {function(): (Promise|any)} run - performs one load; may return a Promise.
   * @returns {{trigger: function(): void, reset: function(): void}}
   */
  function makeCoalescedLoader(run) {
    var inFlight = false, pending = false;
    function settle() {
      inFlight = false;
      if (pending) { pending = false; trigger(); }
    }
    function trigger() {
      if (inFlight) { pending = true; return; }
      inFlight = true;
      var r;
      try { r = run(); } catch (e) { settle(); throw e; }
      if (r && typeof r.then === 'function') r.then(settle, settle);
      else settle();
    }
    function reset() { inFlight = false; pending = false; }
    return { trigger: trigger, reset: reset };
  }

  g.EdL1SseGuards = {
    normL1ExpiryKey: normL1ExpiryKey,
    l1ApplyGenerationMonotonic: l1ApplyGenerationMonotonic,
    l1ApplyTierBLightMonotonic: l1ApplyTierBLightMonotonic,
    l1EnvelopeScopeMatches: l1EnvelopeScopeMatches,
    l1PayloadMatchesActiveScope: l1PayloadMatchesActiveScope,
    makeCoalescedLoader: makeCoalescedLoader,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
