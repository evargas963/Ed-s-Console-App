# PR #238 — LIVE RTH EVIDENCE (preserved, exact-head)

## Provenance / metadata (operator-required)
- **Capture window (UTC):** T0 batch 2026-09-09T15:10:07Z; live/state + cadence samples through ~2026-09-09T15:33Z. All during RTH.
- **Production runtime SHA (console probed, :8000):** `a360416a` (origin/main). This is the ONLY console running with real Schwab data; it was probed READ-ONLY. Production topology was NOT altered.
- **Local candidate SHA (PR #238 branch HEAD, evidence-bearing code):** `1c35efb2` (pushed to origin/claude/ed-console-ui-rebuild; PR head now matches).
- **NOT_PROVEN (explicit):** PR #238 `/api/options/gamma-surface` live-terrain transition, browser==gamma-surface==canonical equality, and PR-head live projection timing / first-view warming→live are **NOT_PROVEN**. Reason: production main `a360416a` does **not contain** that endpoint (`GET /api/options/gamma-surface` → **404** on :8000). These must NOT be converted to PASS from production-main evidence. They belong at the next controlled RTH cutover when the #238 candidate runs as the SOLE console owner.

---

# PR #238 � LIVE RTH PROOF (exact-head evidence)

Captured 2026-09-09T15:33:08.455589Z during RTH against the RUNNING console at http://127.0.0.1:8000.

## Runtime identity

- Console :8000 git_sha = `a360416a3081b65ec088b3320be61f1a6c004344` (origin/main), process_id=12228, dirty=True.
- This is PRODUCTION MAIN, **not** the PR #238 branch (HEAD `1c35efb2`).
- `GET /api/options/gamma-surface` returns **404 Not Found** on :8000 � that endpoint is NEW in the branch, so its live transition CANNOT be observed on production. Every other endpoint below is canonical and branch-independent (the branch frontend renders these verbatim).

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

### Representative near-spot GEX-by-strike (net_gex_1pct$) � $SPX

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

## Real expiration columns ($SPX): 2026-09-09, 2026-09-10, 2026-09-11, 2026-09-14, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24 ...

## Strike Detail chain ($SPX 2026-09-09 0DTE): status=ok, 484 real contracts.

## 4+5. Live cadence & the refresh transition (old gen -> new gen -> API)

Two terrain reads ~47s apart, same console:

**$SPX** — terrain generation ADVANCED mid-window:
- t0: spot 7634.80, computed_ts 1788967091.53, age 103.1s, refresh_active True, stale False, src terrain_live_cache
- t1: spot 7634.35, computed_ts 1788967206.61, age **36.3s (reset)**, refresh_active True, stale False
- => new terrain generation (~115s cycle); age reset on the new gen; the SSE quote moved 7634.54 -> 7634.39 independently (fast quote clock vs slower levels clock — both fresh, both disclosed).

**SPY** — between refreshes in this window (honest monotonic aging, no false refresh):
- t0: computed_ts 1788967172.60, age 72.1s ; t1: SAME computed_ts, age **119.1s (climbing)**, refresh_active True, stale False
- => no new generation yet (SPY on the slower roster sweep); age climbs monotonically; quote still live via SSE (761.99 -> 761.80). No stale flip while under threshold.

This is the two-clock model the branch's gamma-surface relies on: it borrows freshness from THIS terrain authority (terrain_staleness / terrain_cache_get) and prefers the live surface projected in the same _terrain_refresh_one cycle.

## What is PROVEN now vs what needs a branch-HEAD console

PROVEN on real RTH data (canonical, branch-independent — the branch renders these verbatim):
- header quote identity/session/spot/bid/ask/streaming freshness ($SPX/SPY/NVDA), SPXW = no fabricated quote;
- canonical levels (spot/flip/call_wall/put_wall/net_gex) + regime gating + confidence + chain_basis=full;
- GEX-by-strike per-strike net_gex_1pct$ (real, near-spot), source terrain_live_cache;
- real expiries + real 0DTE chain (484 contracts) for Strike Detail;
- live refresh cadence + the old->new terrain generation transition + two-clock freshness.

NOT obtainable from production (endpoint is 404 on main — NEW in the branch):
- /api/options/gamma-surface transition to source=terrain_live_cache + LIVE.window + on_board/warming;
- browser-rendered equality of the NEW shell against these canonical values;
- gamma projection timing at the real producer branch; first-view -> live-surface latency.

These require a console running the PR #238 branch HEAD (1c35efb2) with REAL Schwab creds. The agent cannot start uvicorn (harness-blocked), and a second live-streaming console during RTH risks violating single-stream ownership. Recommended: capture this leg at the owed production-pull step (deploy the merged branch, next RTH) OR the operator starts a branch console on a spare port if their runtime allows a REST-only terrain instance without double-owning the L1 stream.
