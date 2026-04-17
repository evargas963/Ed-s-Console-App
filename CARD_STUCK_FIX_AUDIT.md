# Card Stuck Fix — Closure Audit

## Root Cause

Updates to **"What the Data Says"** and **"The Call"** cards flowed only from:

1. **Initial load** — `fetchState()` runs once on page load
2. **SSE stream** — `connectSSE()` → EventSource `/api/stream` receives server broadcasts

**No periodic polling of `/api/state` existed.** The server’s `_sse_background_loop` fetches state every CACHE_TTL (~28s) and broadcasts. If `_fetch_state` raises (e.g. auth failure), nothing is broadcast. The client still receives heartbeats but no data, so `render()` is never called and cards stay frozen.

On `es.onerror`, the SSE connection was closed and **never reconnected**. There was no fallback, so once SSE died the cards never updated again.

---

## Files Changed

| File | Changes |
|------|---------|
| `static/index.html` | Poll fallback, SSE reconnection, diagnostics, stale indicator, status updates |

**server.py** — No changes. Auth errors are already logged at line 2670.

---

## Exact Diffs

### static/index.html

**1. Poll fallback and tracking variables (before render block):**
```diff
+ let _lastRenderTs = 0;
+ let _consecutiveFailures = 0;
+ const POLL_FALLBACK_MS = 35000;  // Slightly > server CACHE_TTL (28s)
+ let _statePollTid = null;
+ const DIAG = typeof window._edDiag !== 'undefined' && window._edDiag;
```

**2. render() — guard and diagnostics:**
```diff
  function render(d) {
+   if (!d || (d.error && d.error === 'token_invalid')) return;
    window._lastData = d;
    ...
+   if (DIAG) console.log('[render] What the Data Says', { pdir: d.fusion_dominant_direction || d.dominant_dir, conf: d.confidence });
    ...
+   if (DIAG) console.log('[render] The Call', { call_signal: d.call_signal, fusion: d.fusion_dominant_direction });
    ...
+   document.querySelectorAll('[data-stale]').forEach(el => el.removeAttribute('data-stale'));
```

**3. fetchState() — auth handling, success updates, diagnostics:**
```diff
  label.textContent = 'FETCHING...';
+ if (DIAG) console.log('[fetchState] start', { force, ticker, expiry: expiry || 'null' });
  try {
    ...
+   if (data && data.error === 'token_invalid') {
+     if (DIAG) console.warn('[fetchState] auth error', data);
+     throw new Error(data.detail || data.remediation || 'Schwab auth failed');
+   }
+   _consecutiveFailures = 0;
    render(data);
+   _lastRenderTs = Date.now();
+   if (DIAG) console.log('[fetchState] success render done', { ticker: data.ticker, fusion: data.fusion_dominant });
    ...
    dot.className     = 'status-dot live';
+   label.textContent = 'LIVE';
  } catch (e) {
+   _consecutiveFailures++;
+   if (DIAG) console.warn('[fetchState] failed', { err: e.message, consecutive: _consecutiveFailures });
```

**4. pollStateFallback() — new function:**
```javascript
async function pollStateFallback() {
  if (isLoading) return;
  const ticker = $('ticker-input')?.value?.trim()?.toUpperCase() || 'SPY';
  const expiry = $('expiry-select')?.value || null;
  const sseOpen = _eventSource && _eventSource.readyState === 1;
  if (DIAG) console.log('[pollFallback] run', { ticker, sseOpen, lastRender: ... });
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      if (resp.status === 401) {
        const j = await resp.json().catch(() => ({}));
        if (j.error === 'token_invalid') {
          // show error bar, set dot/label ERROR
        }
      }
      return;
    }
    const data = await resp.json();
    if (data && data.error === 'token_invalid') return;
    _consecutiveFailures = 0;
    render(data);
    _lastRenderTs = Date.now();
    // set dot/label LIVE, hide error bar, reconnect SSE if needed
    if (!sseOpen) connectSSE();
  } catch (e) {
    if (DIAG) console.warn('[pollFallback] error', e.message);
  }
}
```

**5. startStatePollFallback() — new function:**
```javascript
function startStatePollFallback() {
  if (_statePollTid) clearInterval(_statePollTid);
  _statePollTid = setInterval(pollStateFallback, POLL_FALLBACK_MS);
}
```

**6. SSE onerror — reconnection:**
```diff
  es.onerror = (err) => {
    ...
    if (_eventSource === es) { es.close(); _eventSource = null; }
+   setTimeout(() => {
+     if (currentTicker && _lastSseTicker === currentTicker && !_eventSource) {
+       connectSSE();  // reconnect after delay
+     }
+   }, 3000);
  };
```

**7. SSE onmessage — tracking:**
```diff
  es.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.ticker === currentTicker && ...) {
+     _consecutiveFailures = 0;
      render(data);
+     _lastRenderTs = Date.now();
+     if (DIAG) console.log('[SSE] render', { ticker: data.ticker, fusion: data.fusion_dominant });
```

**8. CSS — stale indicator:**
```diff
  .signal-card {
    ...
  }
+ .signal-card[data-stale] {
+   opacity: 0.7;
+   filter: saturate(0.6);
+ }
```

**9. updateClock() — stale check:**
```diff
  function updateClock() {
    // ... existing clock ...
+   if (_lastRenderTs > 0 && (Date.now() - _lastRenderTs) > 60000) {
+     const label = $('status-label');
+     if (label && label.textContent !== 'STALE') label.textContent = 'STALE';
+     document.querySelectorAll('.signal-card').forEach(c => c.setAttribute('data-stale', 'true'));
+   }
  }
```

**10. Init — start poll fallback:**
```diff
  fetchState();
+ startStatePollFallback();
  startLiquidityMapPoll();
```

---

## Poll Loop Behavior

| Aspect | Before | After |
|--------|--------|-------|
| Poll interval | None | `setInterval(pollStateFallback, 35000)` |
| After failed request | N/A (no poll) | Poll continues; interval unchanged |
| After 401 | N/A | Error bar + status ERROR; poll continues |
| After 500 | N/A | Poll continues; next success clears error |
| SSE disconnect | Cards freeze | Poll fallback keeps cards updating; SSE reconnects after 3s |

---

## Card Binding Behavior

| Aspect | Before | After |
|--------|--------|-------|
| "What the Data Says" | `render()` lines ~2738–2833 (wds-zone1, pred-main-headline, wds-model-pills, etc.) | Same; guarded by `if (!d \|\| d.error === 'token_invalid') return` |
| "The Call" | `render()` lines ~2555–2728 (call-header-badge, call-zone-fusion, call-signal-el, etc.) | Same; same guard |
| Stale state | None | `data-stale` attr + dimmed styling when no render > 60s |
| Auth error payload | Not checked in render | Early return prevents rendering broken payload |

---

## Closure Audit Result

- [x] Root cause identified (no poll fallback; SSE not reconnecting; auth breakage)
- [x] Poll fallback added and started on init
- [x] SSE reconnects after onerror
- [x] Auth errors surfaced (error bar, status ERROR) and do not stop future polls
- [x] Stale indicator (status label + card dimming) when no render > 60s
- [x] Diagnostics via `window._edDiag = true` (poll start, success/fail, card update logs)
- [x] Backend auth logging present (server.py line 2670)
- [x] Status label set to LIVE on success (fetchState + pollStateFallback)
- [x] Poll fallback success clears error bar and restores LIVE
- [x] No dead legacy logic introduced
- [x] Card bindings preserved; payload shape unchanged

---

## Summary

### 1. What Was Fixed

- Added `/api/state` poll fallback every 35s so cards update even when SSE fails
- SSE reconnection after onerror (3s delay)
- Auth handling: 401 surfaces in UI, poll continues; later success clears error
- Stale indicator: status label "STALE" and card dimming when no render for 60s
- Status label set to LIVE on success (fetchState and pollStateFallback)
- `render()` guard for `token_invalid` payloads
- Diagnostics when `window._edDiag = true`

### 2. What Was Intentionally Preserved

- SSE stream as primary update path
- `fetchState()` for initial load, REFRESH, and ticker/expiry changes
- Existing card render logic and DOM structure
- Backend CACHE_TTL, auth flow, and error responses
- 90s failsafe overlay hide

### 3. What Was Removed

- Nothing. No legacy code removed; only additions and adjustments.

### 4. Known Debt

None. All requested items are implemented and validated.
