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

  g.EdL1SseGuards = {
    normL1ExpiryKey: normL1ExpiryKey,
    l1ApplyGenerationMonotonic: l1ApplyGenerationMonotonic,
    l1ApplyTierBLightMonotonic: l1ApplyTierBLightMonotonic,
    l1EnvelopeScopeMatches: l1EnvelopeScopeMatches,
    l1PayloadMatchesActiveScope: l1PayloadMatchesActiveScope,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
