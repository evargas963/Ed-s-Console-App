/**
 * The page's two load guards: makeCoalescedLoader (one fetch in flight per panel) and
 * sharedFetchJson (one network call for concurrent identical GETs). globalThis.EdL1SseGuards.
 */
(function (g) {
  'use strict';

  /**
   * At most one load in flight. A trigger for the same context key while one is in flight
   * runs once more after it (never dropped, never piled up); a trigger for a different key
   * aborts the in-flight load and starts at once. `run` receives the AbortSignal; an
   * AbortError means superseded, not failed.
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
      // a load that fails (other than an abort by a newer context) is reported, never swallowed
      if (r && typeof r.then === 'function') r.then(settle, function (e) {
        settle();
        if (!(e && e.name === 'AbortError') && typeof console !== 'undefined') console.error(e);
      });
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
   * Concurrent GETs of the same URL share one request; not a cache (the next call after it
   * settles fetches again). No AbortSignal: one caller leaving must not cancel the others.
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
    makeCoalescedLoader: makeCoalescedLoader,
    sharedFetchJson: sharedFetchJson,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
