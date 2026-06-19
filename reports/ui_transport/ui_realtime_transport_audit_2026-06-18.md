> **Classification:** Audit Report | **Scope:** UI real-time transport fidelity

**Branch:** `audit/ui-realtime-transport-fidelity`
**Date/session audited:** 2026-06-18 (offline_static)

## Transport mechanisms found

**Classification:** hybrid

### What drives cards

- GET /api/analytics/state (REST, primary on switch + poll fallback)
- GET /api/state (legacy alias)
- SSE GET /api/stream onmessage → render(data,'sse')

### What drives price/header

- window._fastLaneSpot/_fastLaneSpotDisp (fast lane)
- refreshUtilityBar() reads owned plane + _lastData when ticker matches
- GET /api/live/plane diagnostics for streaming authority

### What drives FEED LIVE

- **feed_pill:** computeFeedState → paintUtilityFeedPill (FEED LIVE/SYNCED/DELAY/STALE/DOWN)
- **ui_active:** ub-ui-detail shows analytics_version from last accepted Tier C payload
- **status_dot:** status-dot + status-label (LIVE / ANALYTICS… / ERROR)
- **sse_badge:** _setSseUi phases CONNECTING/CONN/LIVE/RETRY/OFFLINE

### What drives STALE

- **lane_stale_chip:** laneStaleOperatorLabel — quote ahead, gen behind cards, pending analytics, syncing within trust window
- **feed_stale:** computeFeedState age_sec > ED_FEED_STALE_SEC (30s)
- **card_stale_css:** data-direction-withhold + data-lane-stale on horizon cards
- **analytics_stale_flag:** payload.analytics_stale + analytics_refresh_in_progress

### What drives LOADING

- **refresh_btn:** ↻ LOADING while fetchState in flight (Tier C force path)
- **status_label:** ANALYTICS… on ticker switch
- **analytics_freshness_el:** Analytics: loading… when analytics_pending_shell
- **loading_overlay:** hidden on switch intentionally — not a blocking spinner
- **tier_c_backoff:** _tierCBackoffUntilMs 800ms after pending shell

## Startup critical path

1. `static/index.html` shell load
2. Initial `fetchState` → Tier A `/api/live/state` concurrent with async Tier C
3. `runTickerLiveAcquisition` → SSE `/api/stream` + L1 `/api/analytics/light/stream` + `/api/fast-quote`
4. First card paint when Tier C payload with `mhap_rows` passes `_renderCoherenceGuards`

## Ticker-switch critical path

1. `setActiveTicker` → `requestGeneration++`, optional cache restore
2. `runTickerLiveAcquisition` (SSE force reconnect + fast quote)
3. Tier A/B concurrent REST; Tier C `_fetchTierCRestAndApply` **not awaited** on switch
4. Guards discard superseded generation / wrong ticker

## Measured startup latency

- startup_time_to_shell_ms: None
- startup_time_to_first_payload_ms: None
- startup_time_to_first_card_render_ms: None

## Measured ticker-switch latency

- click_to_loading p50: None ms
- click_to_card_render p50: None ms
- switch_diag samples: 0

## Backend bottleneck

Tier C `_fetch_state` (Schwab chain + DB + seven-layer stack). Non-blocking on switch but poll/SSE still compete with snapshot writes.

## Frontend bottleneck

Full `render()` DOM work on Tier C; lane stale chip when quote lane leads analytical bundle.

## SQLite contention evidence

{
  "paths": [
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\ablation_confirm_post_primary.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\ablation_confirm_v2.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\ablation_confirm_v2_resume.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\arch_competition_ablated_20260609.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-10.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-11.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-12.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-15.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-16.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-17.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\daily_scoreboard_2026-06-18.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\expand_leaf_manifest.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\qqq_iwm_bundle_retrain.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\scheduler_monitor_2026-06-02_190032.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\scheduler_monitor_2026-06-02_190344.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\scheduler_monitor_2026-06-02_191927.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\server_diag_20260609.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\server_diag_20260609b.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\server_diag_20260609c.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\survivor_edge_probe.log",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\logs\\survivor_retrain_gate_2026-06-02_190630.err",
    "C:\\Users\\evarg\\Documents\\Trading\\EdWebConsole\\enforce_all_out.txt"
  ],
  "sqlite_lock_wait_count": 0,
  "sqlite_busy_retry_count": 0,
  "sqlite_database_locked_count": 0,
  "sqlite_tier1_fail_count": 0
}

## Stale/out-of-order risk

- Quote lane can lead bundle → LANE STALE — QUOTE AHEAD (expected during refresh)
- Superseded REST responses discarded by `requestGeneration` guard

## Old ticker overwrite risk

Low for accepted renders — guards discard wrong ticker and superseded generation; residual risk: stale-while-revalidate cache paints old ticker cards until refresh completes

## Missing metadata

- No unified server-side transport audit ring buffer (switch diag is client-posted only)
- Tier C SSE lacks fingerprint dedup before render (L1 SSE has l1_payload_fingerprint)
- No built-in click-to-card-render histogram in production UI without ED_SWITCH_TIMING
- startup_time_to_shell requires browser Performance API capture (not persisted server-side)
- sqlite lock counts require log scrape unless ED_SQLITE_METRICS export added
- No per-tier switch SLA breakdown (core vs guest) in switch diag schema

## Bugs proven

- Hybrid transport with multiple lanes can show LANE STALE — QUOTE AHEAD while cards still show prior bundle (by coherence rules, not necessarily wrong ticker)
- Ticker switch intentionally uses stale-while-revalidate cache — can show prior-ticker cards briefly with analytics_stale flag
- Transport ownership guards are tier-agnostic in static code — core and guest share requestGeneration + ticker mismatch discard

## Bugs not proven

- SQLite contention impact on UI latency (no log samples in audit bundle)
- Guest ticker warm switch meets <2s payload SLA (guest may cold-start slower — needs RTH matrix)
- Core ticker cards cannot persist after switch to guest without visible stale marker (needs live core→guest trace)
- Old ticker payload overwriting selected ticker after guards (requires live RTH switch capture)
- LOADING overlay persistence (overlay hidden on switch; operator may mean ANALYTICS… status — needs live trace)
- Warm ticker switch SLA breach (<2s) — no switch diag samples in this audit run

## Tests added

- `tests/test_live_ui_integrity_v1.py` — transport guard + feed state + sqlite parse helpers

## Files changed

- `verification/ui_realtime_transport_audit.py`
- `tools/check_ui_realtime_transport_audit.py`
- `tests/test_live_ui_integrity_v1.py`
- `ui_realtime_transport_audit_2026-06-18.md`

## Objective audit

Run: `python tools/enforce_all_rules.py --objective-audit`

## Recommended fix branches

- `fix/ui-transport-tier-c-dedup` — Add Tier C payload fingerprint skip before render (mirror L1 SSE) to cut redundant card paints
- `fix/ui-transport-sqlite-readiness` — Surface sqlite_tier1_lock_wait counts on /api/diagnostics/transport-health when contention delays analytics cache
- `fix/card-price-conflict-explainability` — After transport trust proven — operator-facing reconciliation chips (per PR #10 plan)
- `fix/ui-transport-guest-switch-sla` — Per-tier switch diag + guest cold-start degraded UX when models/DB sparse

## Live validation still required

- Warm ticker switch latency under RTH with ED_SWITCH_TIMING=1
- STALE pill timeline correlation with feed state + lane stale chip
- SQLite lock wait impact on Tier C refresh during concurrent base capture

## Core vs guest ticker switching

**Operator requirement:** Ticker switching must be seamless, guarded, and fast for core money-path tickers (SPY/QQQ/IWM) and guest tickers (NVDA, AAPL, …) alike. Guest tickers may lack full base capture parity but must not show old cards, wrong-ticker payloads, or long unexplained loading.

- **Transport guards tier-agnostic:** True
- **activeTicker ownership guest-safe:** True
- **Wrong-ticker discarded (matrix):** True
- **Cache restore marks stale (matrix):** True
- **Guest payload metadata same contract as core:** True
- **Guest missing data visibly explained:** True
- **Core cards persist after guest switch risk:** Stale-while-revalidate restores per-ticker cache only when revisiting same symbol; switching core→guest without guest cache uses pending shell. Residual risk: guest cache hit could show prior guest cards with analytics_stale until refresh — not core ticker bleed if guards hold.

### Question 21

Static: guards are tier-agnostic (no is_base_money_path in render guards). Guest tickers use same metadata contract and wrong-ticker discard. Live: not proven for guest warm-switch SLA — see core_vs_guest_ticker_switching.

### Guest live validation still required

- core→guest and guest→core switch with ED_SWITCH_TIMING under RTH
- guest cold start (no cache) shows pending shell not prior core cards
- SPX/$VIX/$TNX switch if operator uses them in UI

## Follow-up: Tier C duplicate render skip (fix/ui-transport-tier-c-dedup)

| Item | Status |
|------|--------|
| Tier C duplicate render skip gap | **Fixed** |
| Scope | Render dedup only — no card meaning / fusion / model changes |
| Mechanism | `_tierCCardRenderFingerprint` + `_shouldSkipTierCCardRender` before full Tier C `render()` DOM path |
| Reset on switch | `_resetTierCCardRenderDedup()` on `setActiveTicker` / `requestGeneration++` |
| Tier coverage | Core and guest tickers share identical dedup rules |

**Remaining risks:** Live RTH proof that dedup reduces perceived slowness; SQLite contention; guest switch SLA; card explainability layer not yet built.
