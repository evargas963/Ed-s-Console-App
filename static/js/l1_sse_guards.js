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
   * One read of a console JSON route. Resolves the answer as sent; a failed read rejects with
   * `words` naming where it failed: no connection, an error status, a body that is not JSON. A
   * read superseded by a newer one (its signal aborted) rejects with its AbortError.
   *
   * @param {string} url
   * @param {AbortSignal=} signal
   * @returns {Promise<any>}
   */
  function readJson(url, signal) {
    var route = new URL(url, 'http://page').pathname;
    function failed(words) { var e = new Error(words); e.words = words; throw e; }
    function superseded(e) { if (e && e.name === 'AbortError') throw e; }
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) {
      if (!r.ok) failed('the console answered ' + route + ' with ' + r.status);
      return r.json().catch(function (e) {
        superseded(e);
        failed('the console answered ' + route + ' with a body that is not JSON');
      });
    }, function (e) { superseded(e); failed('no console serving ' + route); });
  }

  /**
   * A panel's answer drawn: `draw(answer)`, or `say(words)` for a read that failed or an answer
   * the page could not draw (`what` names it; that error is then raised again, for the loader to
   * report). A superseded read draws and says nothing.
   */
  function show(read, what, draw, say) {
    return read.then(function (d) {
      try { draw(d); } catch (e) { say('the page could not draw the answer of ' + what); throw e; }
    }, function (e) {
      if (!e || !e.words) throw e;
      say(e.words);
    });
  }

  /**
   * Concurrent GETs of the same URL share one request (readJson); not a cache (the next call
   * after it settles fetches again). No AbortSignal: one caller leaving must not cancel the others.
   */
  var _sharedFetchInFlight = Object.create(null);
  function sharedFetchJson(url) {
    if (_sharedFetchInFlight[url]) return _sharedFetchInFlight[url];
    var p = readJson(url);
    p.then(function () { delete _sharedFetchInFlight[url]; },
           function () { delete _sharedFetchInFlight[url]; });
    _sharedFetchInFlight[url] = p;
    return p;
  }

  g.EdL1SseGuards = {
    makeCoalescedLoader: makeCoalescedLoader,
    readJson: readJson,
    show: show,
    sharedFetchJson: sharedFetchJson,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
