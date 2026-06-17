> **Classification:** Operational Ledger | **Scope:** Governance register/inventory `TRADE_IMPACTING_ROUTE_INVENTORY.md`.

# Trade-Impacting Route Inventory

**Status:** COMPLETE (pre-INF lock audit)  
**Method:** Read-only scan of Python call graph + `static/index.html`, `static/governance.html`, `static/ops.html`  
**Date:** 2026-05-01  

---

## Completeness statement (production `compute_call`)

**`compute_call` is defined only in `call_engine.py` and is invoked from production decision code only via `signals.py` → `call = compute_call(...)` (~L1209).**

`compute_signals(` is invoked in this repository from:

| Caller | File | Production? |
|--------|------|---------------|
| `build_market_state` | `market_state.py` | **YES** (server + `phase2_forward_write_verify` tool) |
| Calibration / validation CLIs | `calibration/*.py`, `calibration/validate_logging_e2e.py` | **NO** (operator/CI; same stack semantics) |
| Profiler | `tools/profile_full_stack_runtime.py` | **NO** (dev) |
| Tests | `tests/test_calibration_logging_production_path.py` | **NO** |

**Conclusion:** No additional server HTTP handler invokes `compute_signals` or `compute_call` outside `_fetch_state` → `build_market_state`. No hidden parallel stack in `planes/` (L1 explicitly forbids `build_market_state`).  

**Residual scope:** New files added after this audit are out of scope; re-run grep for `compute_signals(` and `compute_call(` before lock.

---

## Route table (all decision-relevant paths)

**Legend:** TI = trade-impacting. H/D/C/E = halt / determinism / clock / env enforcement recommended per INF program.

| Route ID | File / function / endpoint | Output type | TI? | Why | Final decision point | Downstream | H | D | C | E | Bypass / alternate | Negative test |
|----------|-----------------------------|-------------|-----|-----|----------------------|------------|---|---|---|---|----------------------|---------------|
| **R-001** | `market_state.py` → `build_market_state` | Signal, forecast, **The Call** | **YES** | Full stack | `call_engine.compute_call` | Tier C, SSE, DB | Y | Y | Y | Y | Exception → error cards (no `compute_call`) | `test_calibration_logging_production_path` |
| **R-002** | `signals.py` → `_compute_signals_impl` | Same | **YES** | Orchestrates stack | `compute_call` | Via R-001 | Y | Y | Y | Y | `pred_override` if `ED_CONSOLE_ALLOW_PRED_OVERRIDE=1` | Env matrix |
| **R-003** | `features/signal_layer_v1.py` → `compute_signal_layer_v1_for_calibration` | Enrichment dict | **CONDITIONAL** | Called **inside** `_compute_signals_impl`; feeds `bayesian_fusion` / snapshot; **not** a separate HTTP route | Same tick as R-002 | Fusion inputs only | Y | Y | Y | Y | Failure → logged; stack may continue | Fusion with `signal_layer_v1` null |
| **R-004** | `server.py` → `_fetch_state` (normal path) | Full `ms_dict` | **YES** | Calls `build_market_state` | `compute_call` | UI, cache, DB | Y | Y | Y | Y | — | Golden ticker replay |
| **R-005** | `server.py` → `_fetch_state` (`no_valid_expiry` ~L2844+) | Placeholder `call_signal=wait`, `dominant_dir=flat` | **NO** for engine | **Not** `compute_call`; synthetic | Hard-coded dict | UI if shown | Y | Y | Y | N | **Bypasses stack** | Assert `state_error` + label “synthetic” |
| **R-006** | `server.py` → `_schedule_analytics_recompute` → `_fetch_state` | Cached refresh | **YES** (indirect) | Same as R-004 | `compute_call` | Cache/SSE | Y | Y | Y | Y | Inflight dedupe | Dedupe under halt |
| **R-007** | `server.py` → `_logger_fetch_and_log` → `_fetch_state(log_only=True)` | DB snapshot | **YES** | Full compute before early return | `compute_call` | DB | Y | Y | Y | Y | Returns `{}` to HTTP caller | Snapshot = REST parity |
| **R-008** | `server.py` → `_sse_background_loop` | Schedules R-006 | **YES** (indirect) | — | — | SSE viewers | Y | Y | Y | Y | No subs → no work | — |
| **R-009** | `server.py` → `_on_tick_broadcast_sync` | Schedules R-006 | **YES** (indirect) | Coherent refresh | — | SSE | Y | Y | Y | Y | `TICK_COHERENT_*` gates | Gate closed → no fetch |
| **R-010** | `GET /api/analytics/state`, `GET /api/state` | Tier C JSON | **CONDITIONAL** | Serves **cache**; refresh async | Last R-004/R-006 | UI | Y | Y | Y | Y | Stale body | `analytics_stale` contract |
| **R-011** | `GET /api/debug/prediction` | Debug JSON | **YES** | Sync `_fetch_state` | `compute_call` | Debug client | Y | Y | Y | Y | Ungated in prod | Auth / disable prod |
| **R-012** | `GET /api/live/state` | Tier A | **NO** | Doc: no `build_market_state` | — | UI | N | N | P | N | Cache merge for subset fields | No `call_signal` from Tier A only |
| **R-013** | `GET /api/analytics/light` (+ L1 SSE) | L1 plane | **NO** | Forbidden ML / no BMS | — | UI | N | N | P | N | Contract drift | Schema assert |
| **R-014** | `GET /api/stream` Tier C payload path | Cached snapshots | **CONDITIONAL** | Payload from cache after R-006 | Last `compute_call` | UI | Y | Y | Y | Y | `live_quote` events are quote-only | Distinguish event types |
| **R-015** | `GET /api/liquidity-snapshot` | Zones, scores | **CONDITIONAL** | Heuristic; not `The Call` | `liquidity_value_engine` | UI | P | P | P | N | Fusion from Tier C cache | Empty cache run |
| **R-016** | `GET /api/liquidity-playbook-state` | Playbook | **CONDITIONAL** | Narrative / zones | `generate_playbook_state` | UI | P | P | P | N | — | No `call_*` keys |
| **R-017** | `POST /api/prediction/override` (+ clear) | Memory flag | **CONDITIONAL** | Affects **next** R-004 if env allows | `signals` override branch | Next fetch | Y | Y | N | N | Default ignore | `ED_CONSOLE_ALLOW_PRED_OVERRIDE` |
| **R-018** | `GET /api/price-levels` | Levels | **NO** | Price context | `fetch_price_levels` | UI | N | N | N | N | — | — |
| **R-019** | `GET /api/fast-quote`, `GET /api/live/plane`, SSE `live_quote` | Quote | **NO** | Spot/bid/ask | `live_market_plane` / REST | UI spot | N | N | P | N | — | — |
| **R-020** | `GET /api/accuracy` | Metrics | **NO** | DB stats | `db.compute_accuracy` | UI | N | N | N | N | — | — |
| **R-021** | `GET /api/expiries` | Date list | **NO** | Chain-only light path (`_fetch_expiries_light`) | — | Dropdown / clients | N | N | N | N | Uses cache `expiries` if present | — |
| **R-022** | `GET /api/debug/charm` | Diagnostics | **NO** | Chain/charm | — | Operator | N | N | N | N | — | — |
| **R-023** | Logger / universe **GET/POST** `/api/logger/*` | Config | **NO** | Ticker list / pin | — | Operator | N | N | N | N | — | — |
| **R-024** | `GET /api/health` | Liveness | **NO** | — | — | Ops | N | N | N | N | — | — |
| **R-025** | `GET /api/diagnostics/*` | Diagnostics | **NO** | Perf / switch timing | — | Ops | N | N | N | N | — | — |
| **R-026** | `POST /api/streaming/active-ticker` | Subscription | **NO** | Stream routing | — | Transport | N | N | P | N | — | — |
| **R-027** | `GET|POST` governance + ops | Panel / promote / jobs | **NO** immediate TI | Mutates **models** / runs jobs | `manual_control` / ops runner | **Future** R-004 | P | P | P | P | Env + localhost gates | Gate tests |
| **R-028** | `static/index.html` (client) | Renders API payloads | **CONDITIONAL** | No server compute; can mis-label | Browser | User | P | P | P | P | Stale merge bugs | E2E generation guard |
| **R-029** | `static/governance.html` | Renders `/api/governance/panel` | **NO** TI | Governance JSON only | Server panel builder | Operator | P | P | P | P | — | — |
| **R-030** | `static/ops.html` | Ops runner UI | **NO** TI | Jobs | Subprocess | Training | P | P | P | P | — | — |
| **R-031** | `verify_model_outputs.py`, `verify_mc_directional.py` | State dict | **YES** | Imports `server._fetch_state` | `compute_call` | CLI output | Y | Y | Y | Y | Dev-only use | CI separate job |
| **R-032** | `tools/phase2_forward_write_verify.py` | `build_market_state` direct | **YES** | DB verify tool | `compute_call` | DB insert | Y | Y | Y | Y | Bypasses HTTP | Tool allowlist |
| **R-033** | `calibration/*.py`, `tools/profile_full_stack_runtime.py` | `SignalOutput` | **YES** stack / **NO** prod UI | Same engine | `compute_call` | Files / CI | Y | Y | Y | Y | Not HTTP | CI tag |
| **R-034** | `ml_scheduler.py` / training CLIs | Artifacts | **NO** immediate / **YES** future | Changes weights | Promotion | Future inference | P | P | P | P | Direct writes (tracked elsewhere) | G4 tests |
| **R-035** | Guides `GET /guide/*`, `GET /`, static | HTML/docs | **NO** | — | — | Reader | N | N | N | N | — | — |

**P** = partial recommended until INF scope defined.

---

## Summary / risks / next step

- **Risks:** R-005 synthetic bundle vs R-004 full stack; Tier C stale cache; debug R-011; calibration R-033 trust boundary.  
- **Next step:** Operator review + bind each Route ID to INF enforcement rows in `PHASE_PLAN_INFRASTRUCTURE.md` when locking.

---

## Audit result

**Within scanned repository:** no additional production path to `compute_call` beyond R-001–R-004 chain + listed tools/verifiers.

**RESULT:** **PASS** (route inventory complete for current tree; re-scan on major merges).
