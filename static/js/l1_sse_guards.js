/**
 * Shared L1 SSE + Tier B light guards (single source for monotonic l1_generation and scope keys).
 * Loaded before inline app script in index.html; exposed as globalThis.EdL1SseGuards for tests/diagnostics.
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

  g.EdL1SseGuards = {
    normL1ExpiryKey: normL1ExpiryKey,
    l1ApplyGenerationMonotonic: l1ApplyGenerationMonotonic,
    l1ApplyTierBLightMonotonic: l1ApplyTierBLightMonotonic,
    l1EnvelopeScopeMatches: l1EnvelopeScopeMatches,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
