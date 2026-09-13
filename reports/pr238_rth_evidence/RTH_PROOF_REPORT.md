# PR #238 - PRESERVED LIVE RTH OBSERVATIONS

These are real observations captured from the RUNNING production console during RTH.
They are OBSERVATIONAL evidence, NOT exact-head runtime proof: the production working
tree reported dirty=True, so the exact code identity behind the observed endpoints is
not established. See the classification section below.

## Provenance / metadata
- **Capture window (UTC):** T0 batch 2026-09-09T15:10:07Z; live/state + cadence samples through ~2026-09-09T15:33Z. All during RTH.
- **Production runtime observed (console probed, :8000):** git_sha `a360416a` (origin/main), process_id 12228, **dirty=True**. This was the ONLY console running with real Schwab data; it was probed READ-ONLY. Production topology was NOT altered. (reproduce identity fields: `curl -s http://127.0.0.1:8000/api/build`; raw capture at reports/pr238_rth_evidence/raw/build_t0.json)
- **Code candidate (PR #238):** `1c35efb2` (the evidence-bearing branch code).
- **Current PR #238 head:** `5708f31e` - an evidence-only commit layered over `1c35efb2` (adds this report + raw captures; no code change).

## Classification

### PASS - real live RTH observations captured from the running production console
- real streaming quote behavior (identity / session / spot / bid / ask / freshness);
- real terrain generation transitions (old gen -> new gen, age reset/climb);
- real canonical endpoint outputs observed (terrain levels, per-strike GEX);
- real expiries / chain values observed;
- SPXW identity boundary (no fabricated underlying quote).

### NOT_PROVEN
- exact runtime code identity: the production working tree reported dirty=True, so it is not established which code produced the observed endpoint outputs;
- whether any uncommitted production changes were relevant to any observed endpoint;
- PR #238 `/api/options/gamma-surface` live-terrain transition (endpoint is 404 on production main - it is NEW in the branch);
- PR #238 browser == gamma-surface == canonical equality;
- PR-head live projection performance / first-view warming->live.

These NOT_PROVEN items must NOT be upgraded to PASS from production-main observations.
They belong at the next controlled RTH cutover when the #238 candidate runs as the SOLE console owner. The dirty runtime is preserved as useful observational evidence; it is not rescued with any further governance exercise.

---

## Runtime identity observed
- Console :8000 git_sha = `a360416a3081b65ec088b3320be61f1a6c004344` (origin/main), process_id=12228, dirty=True.
- This is PRODUCTION MAIN, **not** the PR #238 branch (candidate code `1c35efb2`).
- `GET /api/options/gamma-surface` returns **404 Not Found** on :8000 - that endpoint is NEW in the branch, so its live transition CANNOT be observed on production (reproduce: `curl -s "http://127.0.0.1:8000/api/options/gamma-surface?ticker=SPY"` against a production-main-only console). Every other endpoint below is canonical and branch-independent.

## 1+2+6. Header / live source / identity (real RTH quotes)

| ticker | id echoed | session | spot | bid | ask | streaming | staleness_ms | note |
|---|---|---|---|---|---|---|---|---|
| SPX | $SPX | RTH | 7633.33 | None | None | True | 396.6 | index: last-only, no bid/ask |
| SPY | SPY | RTH | 761.91 | 761.89 | 761.92 | True | 680.3 | full L1 quote |
| NVDA | NVDA | RTH | 224.31 | 224.3 | 224.32 | True | 286.8 | full L1 quote |
| SPXW | SPXW | RTH | None | None | None | None | 0 | no independent quote (SPX weekly OPTION root; underlying is $SPX) |

`SPXW` -> `state_error='no_quote'` (honest: no fabricated underlying quote).

## 3. Canonical levels + GEX (backend leg of end-to-end equality)

| ticker | spot | gamma_flip | call_wall | put_wall | net_gex_at_spot | regime | conf | chain_basis | src | age_s | refresh | stale |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPX | 7636.48 | 7722.21 | 7700.0 | 7500.0 | -67102858909.928795 | SIGN_UNPROVEN | TRUSTED | full | terrain_live_cache | 21.3 | True | False |
| SPY | 762.22 | 769.07 | 770.0 | 760.0 | -12458798416.287842 | SHORT_GAMMA_TREND | TRUSTED | full | terrain_live_cache | 69.3 | True | False |
| NVDA | 224.425 | None | 230.0 | 225.0 | 1141719563.293901 | SIGN_UNPROVEN | TRUSTED | full | terrain_live_cache | 77.2 | True | False |

### Representative near-spot GEX-by-strike (net_gex_1pct$) - $SPX

| strike | net_gex_1pct $ | volume |
|---|---|---|
| 7635.0 | -1,469,741,481.1 | 29,591 |
| 7640.0 | -934,690,967.7 | 51,190 |
| 7630.0 | -5,269,853,923.0 | 40,258 |
| 7645.0 | -1,512,603,838.3 | 53,283 |
| 7625.0 | -4,352,716,111.1 | 34,140 |
| 7650.0 | -4,930,803,930.1 | 105,666 |
| 7620.0 | -3,292,528,826.8 | 34,458 |
| 7655.0 | -1,992,603,922.9 | 69,572 |

$SPX per-strike rows: 227 total, 113 non-zero, chain_basis=full.

## Real expiration columns ($SPX)
2026-09-09, 2026-09-10, 2026-09-11, 2026-09-14, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24 ...

## Strike Detail chain ($SPX 2026-09-09 0DTE)
status=ok, 484 real contracts.

## 4+5. Live cadence & the refresh transition (old gen -> new gen -> API)

Two terrain reads ~47s apart, same console:

**$SPX** - terrain generation ADVANCED mid-window:
- t0: spot 7634.80, computed_ts 1788967091.53, age 103.1s, refresh_active True, stale False, src terrain_live_cache
- t1: spot 7634.35, computed_ts 1788967206.61, age **36.3s (reset)**, refresh_active True, stale False
- => new terrain generation (~115s cycle); age reset on the new gen; the SSE quote moved 7634.54 -> 7634.39 independently (fast quote clock vs slower levels clock - both fresh, both disclosed).

**SPY** - between refreshes in this window (honest monotonic aging, no false refresh):
- t0: computed_ts 1788967172.60, age 72.1s ; t1: SAME computed_ts, age **119.1s (climbing)**, refresh_active True, stale False
- => no new generation yet (SPY on the slower roster sweep); age climbs monotonically; quote still live via SSE (761.99 -> 761.80). No stale flip while under threshold.

This is the two-clock model the branch's gamma-surface relies on: it borrows freshness from THIS terrain authority (terrain_staleness / terrain_cache_get) and prefers the live surface projected in the same _terrain_refresh_one cycle.

## What was observed vs what needs a sole-owner branch console

Observed on real RTH data (canonical, branch-independent):
- header quote identity/session/spot/bid/ask/streaming freshness ($SPX/SPY/NVDA), SPXW = no fabricated quote;
- canonical levels (spot/flip/call_wall/put_wall/net_gex) + regime gating + confidence + chain_basis=full;
- GEX-by-strike per-strike net_gex_1pct$ (real, near-spot), source terrain_live_cache;
- real expiries + real 0DTE chain (484 contracts) for Strike Detail;
- live refresh cadence + the old->new terrain generation transition + two-clock freshness.

NOT obtainable from production (endpoint is 404 on main - NEW in the branch), and NOT_PROVEN:
- /api/options/gamma-surface transition to source=terrain_live_cache + LIVE.window + on_board/warming;
- browser-rendered equality of the NEW shell against these canonical values;
- gamma projection timing at the real producer branch; first-view -> live-surface latency.

These require a console running the PR #238 candidate as the SOLE console owner (server:app lifespan starts logger + terrain + bars producers, so a second console is not run). They belong at the next controlled RTH cutover.

## Reproduce (read-only probes of the running console, during RTH)

Every figure above is a live observation, so a re-run returns the values of THAT session, not
these; what re-runs is the method. The probes are the canonical endpoints, read-only, against the
one running console on :8000 (never a second console):

- header / live source / identity: `curl -s "http://127.0.0.1:8000/api/live/state?ticker=SPY"` (also `$SPX`, `NVDA`, `SPXW`);
- canonical levels + net GEX: `curl -s "http://127.0.0.1:8000/api/terrain?ticker=SPY"` (also `$SPX`, `NVDA`), read twice ~47s apart for the cadence / generation transition;
- per-strike net_gex_1pct$: `curl -s "http://127.0.0.1:8000/api/terrain/strikes?ticker=%24SPX"`;
- real expiration columns: `curl -s "http://127.0.0.1:8000/api/expiries?ticker=%24SPX"`;
- Strike Detail chain: `curl -s "http://127.0.0.1:8000/api/chain?ticker=%24SPX&expiry=2026-09-09"`;
- runtime identity (git_sha / dirty / process_id): `curl -s "http://127.0.0.1:8000/api/release/current"`.

---

# 2026-09-10 CONTROLLED RTH PROOF - candidate `3d3d21c2` as the SOLE console owner

Raw captures: `rth_3d3d21c2_20260910/` (per-viewport `*_record.json` + full-viewport PNGs).
Every number below is copied from those records or from the same-window API reads.

## Runtime identity (exact head, sole owner, one daemon)
- `/api/build`: git_sha `3d3d21c245dcbc6da85f115d1d9b458437e3ab6a`, process_id 25056, startup_git_dirty **false**, code_drift.repo_moved_past_process false. Port 8000 LISTEN owner = 25056 (its uvicorn parent 5632 shares the command line and owns no socket).
- Stream daemon: scheduled task "EdConsole Stream Capture" fired 08:25:00 CT from the production checkout (`EdWebConsole\.venv\Scripts\pythonw.exe -m app.market_data.schwab.streaming.capture --symbols SPY,QQQ,IWM --duration-min 405`), PID 26928 with worker child 12856; only 12856 holds the two Schwab TLS sockets. `stream_db_identity.identity_match=true`, `producer_heartbeat.daemon_pid=12856`. Exactly ONE daemon before, during and after the Flow control request.
- Console logs since launch (07:46:53 CT) through 09:05 CT: tracebacks 0, errors 0, non-200 responses 0 apart from static 304s, one favicon 204 and one probe of a non-existent `/api/tickers` (404, the auditor's own probe). Warnings 197, all pre-existing classes (sqlite_bg_write_slow fill_outcomes, sqlite_tier1_lock_wait insert_snapshot, ATR NULL early-session bar count, MANIFEST_MISSING active bundles, SATS terrain quarantine).

## Heatmap population - real RTH surface, three scopes, two viewports (SPY)
| capture (CT) | viewport | surface source | canonical | Auto shown | Wider shown | All shown | row h (Auto/All) | expired cols | body X-overflow |
|---|---|---|---|---|---|---|---|---|---|
| 08:40 | 1920x1080 | banked_morning_reference, live=false (LIVE SURFACE WARMING banner) | 116x16 | 11x11 | 23x16 | 116x16 | 43 / 31 | 0 | 0 |
| 08:48:15 | 1672x941 | terrain_live_cache, live=true, stale=false | 213x34 | 11x10 | 23x20 | 213x34 | 37 / 31 | 0 | 0 |
| 08:52:07 | 1920x1080 | terrain_live_cache, live=true, stale=false | 213x34 | 11x11 | 23x22 | 213x34 | 46 / 31 | 0 | 0 |

- The warming -> live transition of `/api/options/gamma-surface` happened between 08:40 and 08:48 CT (first live SPY surface age 41.8 s at the 08:47 API read; `chain_basis=full`, `strike_count 213`, `expiry_count 34`, contracts_used 6172/6172, provenance.producer `math_exposure_core.compute_exposures_by_strike`, classification DERIVED, spot_source schwab_quote_last).
- Scope header on the live surface: `213x34 canonical . 11x11 shown . spot 757.88 . LIVE.window 46s full`; Auto/Wider/All show 11 / 23 / 213 strikes and 11 / 22 / 34 columns; All scrolls in both axes; no column narrower than its 84 px minimum; Key Levels reads `terrain . live`; GEX by Strike 11 rows at 25 px.
- Browser == API: the DOM Auto window (11 of 213 strikes, 11 of 34 expirations) is the count-based selection of the same `strikes`/`expirations` arrays the API returned in the same capture; the strike rows API (`/api/terrain/strikes`) returned 213 rows, source terrain_live_cache, age 50.5 s.

## Ticker decoupling (item 9) - non-watchlist symbol typed, real data
- PLTR (not in the watchlist) at 08:50:14 CT: the surface served the banked prior-session reference honestly labelled `PRIOR SESSION REFERENCE . 2026-09-09 - LIVE SURFACE WARMING` (113x6, prior_session=true) while `/api/terrain/strikes` was already live (31 rows, age 99.3 s). By 08:56 CT the PLTR surface read `terrain_live_cache, live=true, stale=false, spot 167.49 (schwab_quote_last), 31 strikes x 18 expirations` - the same warming -> live path as SPY, on a typed symbol.
- Same-window API census of the other named tickers at 08:53 CT: META live (terrain_live_cache, 50x23); AAPL / AMZN / AVGO still on the prior-session reference (never selected in this session, so never enrolled in the live terrain sweep). The shell labels that state explicitly; it does not present it as live.

## D-Flow - real stream, explicitly selected contract (SPY)
- Chain rendered 165 contract rows for SPY 2026-09-10; the near-spot Call `SPY   260910C00756000` was clicked (spot 758.18); EdStream posted the ONE control request; the Flow badge reached **ACTIVE in 12 s** (08:58:44 CT capture, page errors 0).
- Producer binding from the payload's streaming_plane: producer_l1_contract == producer_book_contract == the desired contract; daemon_pid 12856.
- 21 rows rendered, every tag the backend's own string, zero UNKNOWN, zero static header chips: top_of_book.{bid,ask,bid_size,ask_size} NATIVE (1.96 / 1.97 / 120 / 56 at capture); mid, microprice, spread_pts, depth.{1,3,5}.imbalance, depth.5.{bid,ask}_total, flow.top_book_pressure DERIVED; flow.tape_pressure_{30s,2m,5m}, cum_delta_proxy, cum_delta_slope PROXY.
- Footer verbatim from the payload: `native_aggressor_available=false; tape_classification=PROXY_RECONSTRUCTED_L1_TICK` -> signed buys/sells NOT PROVEN, none shown.
- ages.book_age_sec 1.304 at the API read; header data age 5 ms; streaming healthy 930 ms.

## Tier C / PCR
- `/api/live/state?ticker=SPY` analytics_lightweight: pcr_val 2.0932, analytics_version 35, vix 17.77; the Key Levels row shows `Put/Call OI . exp 2026-09-10 . 2.09` (the bundle's selected expiry, stated beside the value).

## Classification
PASS (live, exact head, sole owner):
- exact runtime identity == PR head, dirty=false, one console owner, one daemon (before/after the control request);
- `/api/options/gamma-surface` warming -> live transition on real RTH data (SPY and a typed non-watchlist symbol);
- Auto = legible viewport (11 strikes around spot, 10-11 readable expiry columns, 37-46 px rows) at 1920x1080 and 1672x941; Wider = 23 x (<= 2x Auto columns); All = full canonical population scrolled, never compressed; no horizontal body overflow;
- browser == API population counts in every scope;
- D-Flow on a real explicitly selected contract, backend classification verbatim, no signed flow;
- zero tracebacks / errors in the candidate's own log for the whole session.

NOT_PROVEN / observed but not a proof:
- expired-column grammar under RTH: no expiration had expired at capture time (0DTE 09-10 is live), so the EXPIRED header state is [UNVERIFIED] in this live window -- it is exercised only by a separate pre-market fixture test, not reproduced here;
- AAPL / AMZN / AVGO live transition: not selected in this session, so only the honest reference state was observed;
- watchlist last-price cells for QQQ/IWM show "-" although the same analytics_lightweight payload carries `qqq_last`/`iwm_last` (the shell paints only the change column from that payload, per the design comment in ed-core.js). Legibility gap, no second faucet involved; operator decision whether to paint it.

## Reproduce (read-only, against the one running console)
- identity: `curl -s http://127.0.0.1:8000/api/build`
- surface envelope: `curl -s "http://127.0.0.1:8000/api/options/gamma-surface?ticker=SPY"`
- render capture (three scopes + PNGs): `node capture_real_console.mjs http://127.0.0.1:8000 <outDir> rth_SPY 1920 1080 SPY`
- flow proof: `node capture_flow_live.mjs http://127.0.0.1:8000 <outDir> SPY 1920 1080`
- daemon census: `powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'streaming.capture' } | Select-Object ProcessId,ParentProcessId,CreationDate"`
