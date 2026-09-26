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
    const at = (activeTicker || '').trim().toUpperCase();
    if (!at || pt !== at) return false;   // no active ticker accepts nothing (was: treated as SPY)
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
    const at = (activeTicker || '').trim().toUpperCase();
    if (!at || st !== at) return false;   // no active ticker accepts nothing (was: treated as SPY)
    const se = scope.expiry != null ? String(scope.expiry).trim() : '';
    const ck = normL1ExpiryKey(activeExpiry);
    const sk = normL1ExpiryKey(se === '' ? null : se);
    return ck === sk;
  }

  /**
   * Coalesced "no overlap, nothing dropped" async trigger (RC-UI-1 round 7, 2026-09-13).
   *
   * Root cause this fixes: server.py's _publish_levels pushes a
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
   * always converges to the latest state as fast as the round trip allows. Deliberately not
   * a fixed-rate throttle: throttling would reintroduce exactly the latency round 6 was
   * built to remove.
   *
   * ROUND 8 EXTENSION (2026-09-13): the round-7 version coalesced EVERY trigger into the
   * SAME in-flight slot regardless of what it was for — correct for repeated same-context
   * triggers (the push-storm above) but wrong for a genuine CONTEXT CHANGE. Independent-
   * review finding, REPRODUCED: switch ticker while the previous ticker's fetch is
   * artificially delayed (or merely slow) — the new ticker's panel never loads until the
   * OLD ticker's request finally settles, because a same-loader trigger for the new
   * context was silently merged into "run once more when the old one finishes" instead of
   * starting immediately. A held request for a context nobody wants anymore must never
   * block the context the operator is actually asking for now.
   *
   * Fixed with the platform's own cancellation primitive (AbortController) rather than
   * more bespoke flags: `trigger(key)` takes an opaque, comparable context key (e.g. a
   * ticker string, or `ticker+'|'+expiry`). A trigger for the SAME key as the request
   * already in flight still coalesces (unchanged round-7 behavior — needed so a push storm
   * on an UNCHANGED context converges instead of live-locking). A trigger for a DIFFERENT
   * key aborts the in-flight request for the old context and starts the new context's
   * request immediately — it never waits for the old one. `run` receives the AbortSignal
   * so it can pass it straight to `fetch`; callers must treat an AbortError in their
   * `.catch` as "superseded, say nothing" rather than a real failure (rendering a false
   * DEGRADED/unavailable state for a request the loader itself cancelled would be its own
   * new defect). A caller with only one context can omit `key` — every call then compares
   * `undefined === undefined` and the original single-context coalescing is unchanged.
   *
   * An in-flight request's own settle callback is generation-stamped (`myGen`) so an
   * abort's asynchronous rejection — which can arrive AFTER a newer `start()` has already
   * reassigned `inFlight`/`controller`/`currentKey` to the new context — never clobbers
   * that newer request's state; a stale settle is a no-op.
   *
   * @param {function(AbortSignal=): (Promise|any)} run - performs one load for the current
   *   context; receives an AbortSignal (undefined if AbortController is unavailable).
   * @returns {{trigger: function(*=): void, reset: function(): void}}
   *   trigger(key) requests a load for context `key`. reset() aborts any in-flight
   *   request, drops any pending follow-up, and forgets in-flight state.
   */
  function makeCoalescedLoader(run) {
    var inFlight = false, pending = false, currentKey, pendingKey, controller = null, gen = 0;
    var hasAbort = typeof AbortController !== 'undefined';
    function start(key) {
      var myGen = ++gen;
      inFlight = true; currentKey = key;
      controller = hasAbort ? new AbortController() : null;
      function settle() {
        if (myGen !== gen) return;   // superseded by a later start() (context change) -- ignore
        inFlight = false; controller = null;
        if (pending) { pending = false; var k = pendingKey; pendingKey = undefined; start(k); }
      }
      var r;
      try { r = run(controller && controller.signal); } catch (e) { settle(); throw e; }
      if (r && typeof r.then === 'function') r.then(settle, settle);
      else settle();
    }
    function trigger(key) {
      if (!inFlight) { start(key); return; }
      if (key === currentKey) { pending = true; pendingKey = key; return; }
      // A different context wants to load while the OLD context's request is still
      // outstanding: abort it (never just wait for it) and start the new one now.
      if (controller) controller.abort();
      pending = false; pendingKey = undefined;
      start(key);   // bumps gen; the old in-flight's eventual settle() sees myGen !== gen and no-ops
    }
    function reset() {
      if (controller) controller.abort();
      gen++;   // invalidate any in-flight settle callback
      inFlight = false; pending = false; pendingKey = undefined; controller = null;
    }
    return { trigger: trigger, reset: reset };
  }

  /**
   * Dedup concurrent identical-URL GETs into ONE real network request (2026-09-16 audit
   * follow-up, finding #3: a single `ed:gamma-push` SSE event still fanned out to multiple
   * independent REST GETs -- e.g. ed-gamma-chart.js and ed-gamma-panels.js both fetching
   * `/api/terrain/strikes?ticker=X` for the SAME ticker on the SAME push, each with its own
   * `fetch()` call the browser has no reason to know are redundant).
   *
   * Every caller for the identical URL while a request is already in flight gets the SAME
   * promise -- the browser sees exactly one request, not one per caller. This is deliberately
   * NOT a cache: the URL is removed from the in-flight map the instant it settles (success or
   * failure), so the NEXT call for that URL always starts a fresh request rather than serving
   * a stale response -- correctness (freshness) is unaffected, only the redundant CONCURRENT
   * call is eliminated. Each caller's own staleness guard (stillChart/stillCurrent/etc., all
   * already checked before applying a response) is untouched -- this only changes how many
   * times the network is actually asked, never who gets to apply what.
   *
   * No AbortSignal is accepted deliberately: a shared in-flight request must not be cancelled
   * because ONE of several callers waiting on it navigated away -- every caller's own
   * "am I still relevant" check at resolution time already absorbs a response that arrives
   * for a context nobody wants any more.
   *
   * @param {string} url
   * @returns {Promise<any>} parsed JSON; rejects on a non-2xx status or a network error.
   */
  var _sharedFetchInFlight = Object.create(null);
  function sharedFetchJson(url) {
    if (_sharedFetchInFlight[url]) return _sharedFetchInFlight[url];
    var p = fetch(url, { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); });
    p.then(function () { delete _sharedFetchInFlight[url]; },
           function () { delete _sharedFetchInFlight[url]; });
    _sharedFetchInFlight[url] = p;
    return p;
  }

  g.EdL1SseGuards = {
    normL1ExpiryKey: normL1ExpiryKey,
    l1ApplyGenerationMonotonic: l1ApplyGenerationMonotonic,
    l1ApplyTierBLightMonotonic: l1ApplyTierBLightMonotonic,
    l1EnvelopeScopeMatches: l1EnvelopeScopeMatches,
    l1PayloadMatchesActiveScope: l1PayloadMatchesActiveScope,
    makeCoalescedLoader: makeCoalescedLoader,
    sharedFetchJson: sharedFetchJson,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
