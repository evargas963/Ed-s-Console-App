# Analytics/State/Live Tier Boundaries — ownership map

**Status UPDATE (post Tier A/L1/C-route-layer extraction):** all three tiers' route layers
described below have since been extracted following exactly this document's recommended
sequencing — Tier A → `app/api/routes/live.py`, Tier L1 → `app/api/routes/analytics_light.py`,
Tier C's route layer → `app/api/routes/analytics_state.py` — completing server.py's entire
route-based decomposition (zero `@app.get`/`@app.post` decorators remain in server.py). What
follows below is kept as the historical planning record that justified that sequencing, plus
the still-current map for point 4's harder work: `_fetch_state`'s own internal phase-by-phase
decomposition, now IN PROGRESS (see the phase table's Status column) rather than merely
planned.

## Why this document exists

The Phase 3 server.py decomposition plan (the operator-approved architectural rehab plan)
explicitly scoped `/api/analytics/*`, `/api/state`, `/api/live/*`, and `/api/fast-quote` as needing
**documented ownership boundaries before any code moves** — not a mechanical route-by-route
extraction like the twelve slices that preceded it (desk, pages, ops, options, logger, terrain,
diagnostics, streaming, order_flow, exposure, status). Those twelve slices worked because each
route was a thin, mostly self-contained handler. This territory is different: it is built around
`_fetch_state`, a single ~3,400-line function (`server.py:6963`–`10360`) that is genuinely the
highest-risk piece of code in the repository, and a mechanical "just move the function" pass would
either drag half of server.py along with it or silently sever a dependency the way the terrain and
exposure/status slices' near-misses already demonstrated on much smaller functions this session.

This document is the four-part review `docs/ARCHITECTURE.md` §9 requires before a materially
touched responsibility moves: **behavior**, **ownership**, **data semantics**, **failure
boundary** — for each tier, plus a phase map of `_fetch_state`'s internals so a future extraction
pass has a real map instead of starting cold.

## The four tiers

The UI does not read one endpoint for "state" — it reads four, deliberately staggered by cost,
and conflating them is the single most consequential mistake a future refactor could make.

### Tier A — instant live quote plane

**Routes:** `GET /api/live/state`, `GET /api/live/plane`, `GET /api/fast-quote`
**Canonical functions:** `_tier_a_live_state_dict` (`server.py:6639`), `_fetch_fast_quote_payload`
(`server.py:3637`), `api_live_plane` (inline body, `server.py:15149`)

- **Behavior:** quote + session + streaming-authority diagnostics only. No chain fetch, no
  exposures, no DB read, no model stack. Every one of these three routes is explicitly documented
  in its own docstring as NOT requiring `/api/analytics/state`'s heavy pipeline.
- **Ownership:** the live-market-plane singleton `_lmp` (`live_market_plane.py`) is the sole
  producer of the quote row these all read (`_lmp.get_quote(ticker)`); streaming authority comes
  from `app.options.order_flow.streaming.get_plane_authority_for_ticker`. Nothing in Tier A writes
  `_state_cache`.
- **Data semantics:** freshness is `_lmp`'s own tri-state (`quote_ingestion` field:
  `schwab_streaming_level_one` / `rest_bootstrap_pending_stream` / REST fallback variants); no
  chain-derived field (gamma, walls, decision) exists at this tier — a consumer reading Tier A for
  a decision-bearing field would find it silently absent, not stale.
- **Failure boundary:** a Schwab REST failure here degrades to `_record_rest_fast_quote_with_auth_fallback`'s
  own fallback ladder; it cannot cascade into Tier C because it never touches Tier C's cache or
  locks.
- **Already effectively isolated.** These three routes depend on `_lmp` and
  `app.options.order_flow.*` — both already-modularized subsystems, not `_fetch_state`. **This is
  the safest candidate for a future mechanical extraction slice** (route bodies only, same pattern
  as the twelve completed slices), independent of anything below.

### Tier L1 — light context plane

**Routes:** `GET /api/analytics/light`, `GET /api/analytics/light/stream`
**Canonical functions:** delegates entirely to `planes/l1_events.py` (`notify_ticker_expiry_changed`),
`planes/l1_runtime.py`, `planes/l1_cache_lifecycle.py`, `planes/l1_thresholds.py`,
`planes/l1_operational.py` — server.py's route bodies are thin dispatchers.

- **Behavior:** reads the authoritative `_l1_snapshot_cache` by default; a full L1 rebuild runs
  only on cold miss, serve-age expiry, or `force=true`, and rebuilds are materiality-gated (a quote
  move must clear a threshold before a rebuild is worth the cost — see `planes/l1_thresholds.py`).
- **Ownership:** this is **already its own subsystem** under `planes/`, not part of `_fetch_state`
  at all. `/api/diagnostics/l1` (already extracted to `app/api/routes/diagnostics.py` this session)
  reads the same `_l1_instrumentation`/`_l1_snapshot_cache` state.
- **Data semantics:** every envelope carries its own generation/sequence number
  (`_next_gamma_surface_seq` is one example of what advances it); SSE pushes only on a real
  generation advance, never on a timer.
- **Failure boundary:** isolated to the `ed_l1_light` executor; a stuck L1 rebuild cannot block
  Tier A or Tier C, which run on separate executors (see the executor table below).
- **Already fully separated from `_fetch_state`.** The only server.py-owned pieces are the two thin
  route bodies and `_l1_sse_light_diag_payload`/`_sse_event_name_for_envelope` — a clean, low-risk
  extraction candidate once Tier A is done, following the same lazy-import pattern already used for
  every prior slice.

### Tier C — full analytical pipeline

**Routes:** `GET /api/analytics/state` (canonical), `GET /api/state` (deprecated alias, same
handler path), `POST /api/analytics/warm` (non-blocking prewarm)
**Canonical functions, in call order:**

```
route (get_analytics_state / get_state)
  -> _tier_c_analytics_json_response   (server.py:10713)   READ PATH — cache-first, never blocks
       -> _schedule_analytics_recompute (server.py:2698)   SCHEDULING — dedupe + background submit
            -> _fetch_state             (server.py:6963)   COMPUTE — the actual pipeline
```

`POST /api/analytics/warm` takes a parallel path through `_schedule_analytics_warm`
(`server.py:3171`), which itself calls `_schedule_analytics_recompute` (confirmed:
`server.py:3186`) — the same scheduling function Tier C's REST read path uses — so it also bottoms
out in `_fetch_state`, one layer further removed than the REST route.

- **Behavior:** `_tier_c_analytics_json_response` is a **stale-while-refresh cache view** — it is
  the ONLY thing an HTTP request ever synchronously waits on, and it never calls `_fetch_state`
  inline. On a cache hit it merges the live quote plane in, revalidates the cached decision, and
  returns immediately (µs). On a miss or stale entry it returns a lightweight pending shell
  (`_minimal_analytics_pending_dict`) and schedules `_fetch_state` in the background via
  `_schedule_analytics_recompute`, which dedupes concurrent requests for the same
  `(ticker, expiry)` against `_analytics_inflight`. **No request path in this codebase blocks on
  `_fetch_state` except one deliberate exception**: `/api/debug/prediction` (already extracted to
  nowhere — it's still in server.py, calls `_fetch_state` directly and synchronously, by design,
  since it's an operator debug tool that wants the real, uncached number).
- **Ownership:** `_fetch_state` is the **sole producer** of the full `ms_dict` — every Tier C
  field (exposures, gamma flip, charm, PCR, expected move, vol signals, GARCH, order flow signals,
  predictive positioning, zone tracking, the full V2 decision bundle, model health dashboard,
  confluence, accuracy) is computed exactly once per cycle, inside this one function, and nowhere
  else. This is the "one faucet" the whole rehab mission has been protecting for every smaller
  domain — Tier C is where that discipline is hardest to see because it is all one function body
  rather than one function per field.
- **Data semantics:** the terminal write, `_state_cache[(ticker, expiry)] = {...ms_dict...}`
  (`server.py:10327`), is the single seam between compute and serve. `_tier_c_analytics_json_response`
  reads exactly this dict and nothing else for the "is this fresh" decision (`_analytics_generated_ts`,
  `ttl` from `_sse_viewer_cache_ttl`, `ANALYTICS_STALE_GRACE_CYCLES`). A missing entry is a genuine
  cold cache (served as a pending shell with `state_error` unset); an entry present but past its
  grace window is `stale=True` and still served (stale-while-refresh), never blocked on.
- **Failure boundary:** `_fetch_state` raising (`HTTPException`, `SchwabAuthError`, or any other
  exception) is caught entirely inside `_schedule_analytics_recompute`'s `_work()` closure and
  recorded via `_record_analytics_bg_failure` into `_analytics_bg_last_error`, which
  `_tier_c_analytics_json_response` surfaces as `state_error`/`analytics_last_error` on the NEXT
  served payload — it never raises out of an HTTP request. The one exception is
  `/api/debug/prediction`'s direct synchronous call, which is allowed to 500 (it is a debug tool,
  not a UI-facing surface).

**Tier C's shared module-level state** (must stay in server.py if/when route bodies eventually
move, exactly like every prior slice's caches/locks):
`_state_cache`, `_analytics_bg_lock`, `_analytics_inflight`, `_analytics_bg_shutdown`,
`_analytics_bg_last_error`, `_analytics_recompute_last_duration_sec`, `_sse_subscribers`,
`_sse_clients`, `CACHE_TTL`, `ANALYTICS_STALE_GRACE_CYCLES` — every one of these has call sites
well outside `_fetch_state` itself (the SSE broadcast loop, the background logger, the terrain
loop's own freshness checks), so none of them can move with any extracted route body.

## `_fetch_state`'s internal phase map

**Line numbers below are as originally mapped (server.py:6963–10360, ~3,400 lines) and drift
with every unrelated edit elsewhere in the file — treat them as approximate/historical, not a
live reference.** Re-locate `_fetch_state` (`grep -n "^def _fetch_state"`) before trusting any
line number here. This is the coarse structural map, built from the function's own
section-banner comments (its existing convention — every phase is already marked). **This is
not a byte-level dependency graph.** Verify each phase's real inputs/outputs before extracting.

| # | Phase (line, approx. at first mapping) | What it does | Delegates to (already modular) or inline | Status |
|---|---|---|---|---|
| 1 | Preamble, ticker canonicalization (6963) | `ticker_storage_key`, `_touch_tracked_ticker_view`, diag emit | inline (cheap) | not extracted |
| 2 | Chain + quote fetch in parallel (7009) | Schwab REST via gated executor pool | delegates: `_gated_safe_get_chain`, `_memoized_quote_response` | not extracted |
| 3 | Expiry selection (7196) | picks the working expiry from the chain | inline | not extracted |
| 4 | Exposures (7284) | GEX/DEX/vanna by strike | delegates: `math_exposure_core.compute_exposures_by_strike` | not extracted |
| 5 | Gamma flip + void zones (7387) | wall/flip selection | delegates: `math_levels.py` | not extracted |
| 6 | Charm (7406) | dealer charm by strike | delegates: `math_levels.compute_charm_by_strike` | not extracted |
| 7 | PCR (7469) | put/call ratio | inline (small) | **EXTRACTED** — `_pcr_val_for_state(totals) -> pcr_val \| None`, a pure read-through of `totals[0].pcr_oi` (no computation of its own). Second slice; see `tests/test_fetch_state_pcr_phase_v1.py`. |
| 8 | Market context, candle (7509–7544) | session label; candle direction/body/OHLC/range from the last COMPLETED 1m bar | delegates: `market_context.py`; candle classification delegates to `math_probabilities.classify_direction` | Candle direction sub-phase **EXTRACTED** — `_candle_direction_for_state(ticker) -> _CandleDirectionForState` (7-field `NamedTuple`). Fifth slice; see `tests/test_fetch_state_candle_direction_phase_v1.py`. The session-label "Market context" sub-phase is a separate, not-yet-extracted piece of this same original banner. |
| 9 | Price levels (7548) | VWAP/PDH/PDL/PDC/ORB | delegates: `liquidity_value_engine.py` | **EXTRACTED** — `_price_levels_for_state(ticker, client, q_json, now_et_dt, cache_key) -> PriceLevels`. First slice with a real shared-state side effect (reads/writes `_state_cache[cache_key]` directly, referenced as a server.py module global exactly as `_fetch_state` itself does — not passed as a parameter). Sixth slice; see `tests/test_fetch_state_price_levels_phase_v1.py` for all four preserved control-flow paths (cache hit, successful fetch + cache write, `LevelCarrierConflict` re-raise, generic-failure fallback with NO cache write per Python's try/except/else semantics). |
| 10 | Expected move (7616) | straddle + IV-based | delegates: `math_volatility.py` (`compute_expected_move_straddle`/`compute_expected_move_iv`/`compute_em_progress`/`resolve_kl_em_anchor`/`resolve_mc_iv_for_kl_em_anchor`) | **EXTRACTED** — `_expected_move_for_state(now_et_dt, price_levels, contracts_use, spot_f, atm_iv) -> _ExpectedMoveForState` (9-field `NamedTuple`). Seventh slice; see `tests/test_fetch_state_expected_move_phase_v1.py` for the STRADDLE_IMPLIED-priority-over-IV_MODEL fallback chain and the exception-swallow contract. |
| 11 | Volatility signals (7702) | IV skew, realized vol, ATR, rank/pctile | delegates: `volatility_regime.py` family | **EXTRACTED** — `_volatility_signals_for_state(ticker, contracts_use, spot_f, atm_iv, ed_db, tick_ts) -> _VolatilitySignalsForState` (6-field `NamedTuple`, including `closes` for the downstream GARCH phase). Fourth slice; **also fixed a live regression the first slice (GARCH) had introduced** — see `tests/test_fetch_state_volatility_signals_phase_v1.py`'s module docstring for the full causal chain. |
| 12 | GARCH forecast (7769) | vol forecast | delegates: `compute_garch_forecast`/`blend_garch_sigma` | **EXTRACTED** — `_garch_sigma_bars_for_state(closes, atm_iv, realized_vol, spot_f) -> sigma_bars \| None`, defined immediately above `_fetch_state`; `_fetch_state` now calls it in one line. Verified byte-identical to the original inline chain, including the pre-existing swallowed-RuntimeError quirk (deliberately NOT fixed as part of this decomposition — see `tests/test_fetch_state_garch_phase_v1.py`). First slice of this phase-by-phase decomposition. |
| 13 | Order flow signals (7803) | from option volume + bid/ask size | delegates: `compute_volume_oi_ratio`/`flow_imbalance_normalized_with_fallback`/`compute_smart_money_signal`/`compute_iv_model_spread` | **EXTRACTED** — `_order_flow_signals_for_state(exposures, spot_f, contracts_use) -> _OrderFlowSignalsForState` (a `NamedTuple` with 5 fields), preserving the ORIGINAL per-call try/except isolation exactly (one signal's failure never affects a sibling's). Third slice; see `tests/test_fetch_state_order_flow_signals_phase_v1.py`. |
| 14 | Predictive positioning §8 (7832) | signal layer | delegates: `signals.py`/`bayesian_fusion.py` | **EXTRACTED** — `_predictive_positioning_for_state(ticker, exposures, cons_strikes, spot_f, charm_net, gamma_voids, iv_direction) -> _PredictivePositioningForState` (9-field `NamedTuple`: DPI, hedging flow, gamma gradient, breakout score, pin score, vol expansion, void factor, terrain-SSOT pin/regime). Required promoting the nested closure `_bucket_total_oi` to a module-level function first (a second call site in the not-yet-extracted Level Density sub-phase, phase 15, needed it visible outside the closure's original enclosing scope). `_sweep_score` is deliberately NOT part of the return contract — its real computation happens after `build_market_state` (phase 18), gated on `ms.nearest_above_dist`/`ms.nearest_below_dist`; `_fetch_state` still pre-initializes `_sweep_score = {}` itself, unmoved. Eighth slice; see `tests/test_fetch_state_predictive_positioning_phase_v1.py`. |
| 15 | Vol envelope, level density, sector strength (7980) | breadth/regime context | delegates: several `*_engine.py` modules | not extracted |
| 16 | Zone tracking (8120) | price zone state machine | inline + `market_state.py` | not extracted |
| 17 | DB counts + crosses (8154) | snapshot counters | delegates: `db.py` | not extracted |
| 18 | Build `MarketState` dataclass (8328) | assembles the typed observation | delegates: `market_state.build_market_state` | not extracted |
| 19 | V2 decision build, identity anchor (8484–8624) | the actual model stack + fusion + decision bundle | delegates: `v2_decision/*`, `ml_predict.py`, `bayesian_fusion.py`, `call_engine.py` | not extracted |
| 20 | Publish + persistence tail (8624) | writes decision, stamps generation | delegates: `decision_record.py`, `db.py` | not extracted |
| 21 | `log_only` early return (9475) | background-logger path stops here — no full API dict assembled | inline branch | not extracted |
| 22 | Full API response dict assembly (9502–10293) | ~35 more sub-sections re-reading/re-shaping the SAME already-computed values above for the JSON wire shape (key levels, terrain read, top drivers, synthetic forward, trade validation gate, call/put readiness, position sizing, model health dashboard, confluence, accuracy, fusion-calibration provenance) | inline shaping only — **no new computation**, this whole block reads fields already produced by phases 3–20 | not extracted |
| 23 | Level-cross detection (10293) | debounced level-touch logging | delegates: `db.detect_and_log_level_crosses` | not extracted |
| 24 | Terminal cache write (10327) | `_state_cache[key] = {...}` | inline (the seam) | not extracted |

**Extraction pattern established by phase 12, to reuse for the rest:** (1) identify the phase's
real inputs (values read from outer scope, unmodified since their own assignment) and real
outputs (values the phase defines that are read afterward) by grepping the phase's variable
names across the whole `_fetch_state` body, not just visually; (2) write a standalone function
with those as explicit parameters/return value, placed immediately above `_fetch_state` so it
can use every already-imported module-level name server.py already has; (3) preserve behavior
byte-for-byte, including any pre-existing quirks — a decomposition is not the place to also fix
something noticed along the way, no matter how tempting; (4) replace the inline block with a
one-line call; (5) write a direct unit test proving the extracted function's output matches the
original inline computation chain exactly (not just "returns something"), plus edge cases and
an AST lock proving `_fetch_state` calls the new function exactly once and no longer contains a
second, independent copy of the same computation; (6) run the full directly-relevant test batch
plus ruff plus the institutional-correctness gate before committing, exactly like every route
slice this session.

**The single most important fact this map surfaces:** phases 1–20 are the real computation, almost
entirely delegated to already-separate modules — `_fetch_state` itself is closer to an
**orchestrator** than a monolith of business logic. Phase 22 (the largest block by line count,
~800 lines) is **pure re-shaping of already-computed values into the wire response**, not new
computation. This means the eventual extraction shape is very different from every prior slice:
there is no clean "route handler body" to peel off, because `_fetch_state` is not behind a thin
route — it IS the compute, called by three different schedulers (SSE loop, REST scheduler,
background logger) that each need the same `ms_dict`, not an HTTP request/response shape.

## What this means for a future extraction (not attempted here)

1. **Tier A first.** `/api/live/state`, `/api/live/plane`, `/api/fast-quote` can follow the exact
   mechanical pattern used for the twelve completed slices — they own no shared computation, only
   read `_lmp`. Lowest risk, highest confidence.
2. **Tier L1 second.** `/api/analytics/light` + `/api/analytics/light/stream` are thin dispatchers
   into an already-separate `planes/` subsystem. Same mechanical pattern, slightly more care around
   the SSE generator closure (mirror the pattern already used for `/api/logger`'s and terrain's SSE
   equivalents if any exist, or the existing `/api/stream` extraction precedent once that lands).
3. **Tier C's route layer (`_tier_c_analytics_json_response`, `get_analytics_state`, `get_state`,
   `post_analytics_warm`) can plausibly move as a unit** — it never calls `_fetch_state` inline, so
   it does not drag the 3,400-line function with it. `_schedule_analytics_recompute`,
   `_schedule_analytics_warm`, and `_fetch_state` itself are the scheduling/compute core and should
   **stay in server.py, imported back lazily**, exactly like every prior slice's shared
   infrastructure — this route layer would be a genuinely clean, low-risk fourth extraction once
   Tier A and Tier L1 are done and the pattern is proven again on this file.
4. **`_fetch_state` itself was never a route-extraction candidate** — it has no route decorator of
   its own. Its decomposition is a *phase-by-phase refactor* of one giant function into named,
   independently testable steps (using the phase table above as the outline), never a file-move,
   and is now IN PROGRESS: phase 12 (GARCH forecast) is extracted as the first slice, proving the
   pattern documented above the phase table. This is real, careful, one-reviewed-section-at-a-time
   work — plausibly where genuine speed gains live (parallelizing independent phases, caching
   phase 22's re-shaping separately from phases 1–20's real compute, etc.) — continue it the same
   way: one phase per slice, behavior-preserving, with a direct test proving the match before
   moving to the next.
5. **Do not move `_schedule_analytics_recompute`/`_schedule_analytics_warm`/`_fetch_state` anywhere
   until phase 4 above is a deliberately planned, separately reviewed mission.** They are called
   from at least three places outside any HTTP route (the SSE background loop, the background
   ticker logger, `/api/debug/prediction`) — moving them prematurely risks exactly the kind of
   "swallowed the thing sitting between two routes" mistake this session already made twice on far
   smaller functions (the exposure and status slices), at ~50x the blast radius.
