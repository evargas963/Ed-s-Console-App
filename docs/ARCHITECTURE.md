# Ed Console — Canonical Repository Architecture

This is the canonical target architecture for Ed Console.

The repository is being migrated incrementally toward this structure. Whenever work materially
touches an area, the affected files, responsibilities, imports, and ownership should move toward
this target when that movement is safe and cohesive.

Do not silently create a competing architecture. If this target is technically wrong, impossible,
or materially inferior for something encountered, raise the specific objection with evidence
before deviating.

---

> **Status 2026-09-26.** The ML stack, the decision layer and the research program were deleted
> (operator decisions); their target branches are gone from §1 and §2. Later sections still
> describe them and are rewritten in the docs pass (ACTIVE_PROGRAM P2-8). How data moves is
> `docs/DATA_FLOW.md`.

## 1. Canonical target schematic

```text
Trading/
│
├── EdWebConsole/                         # SOURCE / RELEASE CODE ONLY
│   │
│   ├── app/
│   │   │
│   │   ├── api/                          # Thin application/API composition
│   │   │   ├── routes/
│   │   │   ├── dependencies/
│   │   │   └── lifespan/
│   │   │
│   │   ├── domain/                       # Canonical market/domain semantics
│   │   │   ├── instruments/
│   │   │   ├── sessions/
│   │   │   ├── prices/
│   │   │   ├── levels/
│   │   │   ├── regimes/
│   │   │   └── shared canonical types
│   │   │
│   │   ├── market_data/                  # COLLECT
│   │   │   ├── schwab/
│   │   │   │   ├── client/
│   │   │   │   ├── quotes/
│   │   │   │   ├── price_history/
│   │   │   │   └── streaming/          # the capture daemon process (DATA_FLOW §4)
│   │   │   ├── normalization/
│   │   │   ├── enrollment/
│   │   │   ├── snapshots/
│   │   │   ├── bars/
│   │   │   └── market_state/
│   │   │
│   │   ├── options/                      # Canonical options truth
│   │   │   ├── chains/
│   │   │   ├── contracts/
│   │   │   ├── greeks/
│   │   │   ├── gamma/
│   │   │   ├── delta/
│   │   │   ├── vanna/
│   │   │   ├── charm/
│   │   │   ├── exposure/
│   │   │   ├── dealer_positioning/
│   │   │   ├── order_flow/
│   │   │   └── levels_producer/          # its own process (DATA_FLOW §4)
│   │   │
│   │   ├── liquidity/                    # Canonical liquidity/value structure
│   │   │   ├── vwap/
│   │   │   ├── volume_profile/
│   │   │   ├── liquidity_levels/
│   │   │   └── playbook/
│   │   │
│   │   └── infrastructure/
│   │       ├── database/
│   │       │   ├── connection/
│   │       │   ├── schema/
│   │       │   ├── repositories/
│   │       │   └── migrations/
│   │       ├── external_clients/
│   │       ├── scheduling/
│   │       ├── observability/
│   │       └── runtime_state/
│   │
│   ├── static/                            # Modular operator UI
│   │   ├── pages/
│   │   ├── components/
│   │   ├── js/
│   │   └── css/
│   │
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── runtime/
│   │   └── e2e/
│   │
│   ├── tools/                             # SMALL active operator/dev toolbox
│   │
│   ├── config/                            # Product configuration/contracts
│   │
│   ├── governance/                        # MINIMAL dev/agent/merge governance
│   │
│   ├── docs/
│   │   └── ARCHITECTURE.md                # THIS DOCUMENT
│   │
│   ├── AGENTS.md
│   ├── OPEN_ITEMS.md
│   ├── pyproject.toml
│   └── README.md
│
├── runtime/
│   └── EdWebConsole/                      # LIVE MUTABLE STATE
│       ├── the one database                 # written only by the daemon's writer (DATA_FLOW §6)
│       ├── tokens/
│       ├── logs/
│       └── state/
│
├── artifacts/
│   └── EdWebConsole/                      # GENERATED ARTIFACTS
│       └── temporary_outputs/
│
├── recovery/
│   └── EdWebConsole/                      # VERIFIED RECOVERY ASSETS
│       └── backups/
│
└── worktrees/                             # DEVELOPMENT ONLY
    └── active worktrees/
```

---

## 2. Current → target (every product file, 2026-09-26)

Moves happen one change at a time, and this table is updated in the same change as each move.
`→ delete` rows go with the change named in `ACTIVE_PROGRAM.md`.

```text
CURRENT (root unless shown)            TARGET

server.py (6,130)
  routes                         →     app/api/routes/  (by what they serve)
  startup / lifespan             →     app/api/lifespan/
  levels loop                    →     the levels producer process (DATA_FLOW decision 2)

db.py (3,892), db_authority.py,  →     app/infrastructure/database/  (split by what it stores)
db_safety.py, json_blob_codec.py,
snapshot_access.py, desk_store.py

ml_horizon.py, horizon_outcomes.py,    →  delete (ML stack; P2-5)
movement_target_threshold.py,
decision_record.py, execution_identity.py,
calibration/schema.py

calibration/complete_chain_capture.py, →  app/options/chains/
calibration/option_chain_morning_full.py

schwab_client.py, reauth_schwab.py,    →  app/market_data/schwab/client/
api_pressure.py

app/market_data/schwab/streaming/      →  stays (the daemon)
stream_spine.py, live_market_plane.py, →  app/market_data/schwab/streaming/
live_price_rows.py

app/options/order_flow/,              →  app/options/order_flow/
l1_trade_observation.py,
micro_structure.py

terrain_engine.py, terrain_read.py,    →  app/options/  (gamma / exposure / levels)
terrain_atr.py, math_exposure_core.py,
math_levels.py, math_probabilities.py,
math_volatility.py

liquidity_value_engine.py,            →  app/liquidity/
liquidity_models.py

time_et.py, timeframe_config.py        →  app/domain/sessions/
instrument_identity.py,               →  app/domain/instruments/
production_universe.py,
scheduler_user_tickers.py
market_context.py                      →  app/market_data/
numeric_contract.py                    →  app/domain/
config.py, runtime_layout.py           →  app/infrastructure/runtime_state/
release_object.py                      →  app/infrastructure/observability/
schwab_field_dictionary_builder.py     →  decided in P2-7 (job to be confirmed)

start_ed_console.bat,                  →  stay at the root (what the operator runs)
start_capture_daemon.bat,
runtime_preflight.py, live_schwab_env.py,
launcher_port_guard.py,
wait_for_ready_then_open.py

static/index.html, js/, css/           →  static/  (the one shell)
static/chart.html, desk.html,          →  delete after P2-4 (what is unique moves into the shell)
exposure.html, options.html
```

---

## 2b. Taking apart the large files (measured 2026-09-26)

Each step is one change: it deletes what has no job, moves what remains to its target folder with
no change in behaviour, updates §2 in the same change, passes the full test suite and the browser
suite, and is checked on the running app. Nothing is copied: a moved function exists in one place.

### db.py — 3,892 lines

Measured: the `EdDB` class is 2,563 lines with 35 methods. Product code calls 14 of them (664 lines).
Of the 12 tables it creates, the product reads or writes 6.

| Part | Lines | Used by the product | Plan |
|---|---|---|---|
| `SnapshotRow` + snapshot writer (`insert_snapshot`, `_tier1_snapshot_write`, `count_snapshots`) | ~700 | no — only the deleted ML pipeline wrote snapshots; only tests call them | delete, with their tests |
| Outcome labels (`fill_outcomes`, `refresh_all_governed_bar_anchor_outcomes_v1`, `_apply_bar_based_outcome_updates`, `_refresh_governed_outcomes_after_bar_mutation`, `_snapshot_rows_affected_by_bar_mutations`) | ~470 | no — ML training labels | delete, and the call from `upsert_1m_bars` |
| Migrations (`_migrate_schema` 555, horizon/outcome/drop migrations) | ~720 | run once at startup; most migrate tables that are gone | keep only what creates the live tables; delete the rest |
| Table creation (`_init_schema` 457) | 457 | yes | keep only the live tables: `price_bars_1m`, `level_crosses`, `oi_daily`, `iv_daily`, `logging_universe`, `ed_schema_flags`; stop creating `snapshots`, `model_accuracy`, `gamma_surface_last_valid`, `confluence_quote_ticks`, `logging_universe_eviction_log`, `logging_universe_migration_log` (existing tables are not dropped — that is the operator's database decision) |
| `market_session` | 28 | no — labelled snapshot rows; `time_et.session_label` is the one session producer | delete |
| `get_db_stats` | 46 | no | delete |
| `logging_universe_migrate_legacy_json_file` | 130 | called at startup; a one-time migration from a JSON file | delete if the migration has run (check its flag in `ed_schema_flags`) |
| Bars (`upsert_1m_bars`) | 198 | yes | `app/infrastructure/database/bars.py` |
| Levels history (`detect_and_log_level_crosses`, `log_level_cross`, `get_recent_crosses`, `count_level_tests`, `bank_daily_strike_oi`, `prev_session_strike_oi`, `bank_daily_atm_iv`) | ~170 | yes | `app/infrastructure/database/levels_history.py` |
| Enrollment (`logging_universe_*`) | ~180 | yes | `app/infrastructure/database/enrollment.py` |
| Connection, SQLite settings, contention log, `get_db` | ~120 | yes | `app/infrastructure/database/connection.py` |

The five modules only the ML stack used go in the same step: `ml_horizon.py`, `horizon_outcomes.py`,
`movement_target_threshold.py`, `decision_record.py`, `execution_identity.py`, and
`calibration/schema.py`. Expected result: about 3,900 lines become about 900, in four files.

Data flow (DATA_FLOW.md decision 5): one database, written only by the daemon's writer; the
console reads read-only. Today the console writes bars, level crosses, daily OI/IV and the ticker
board to its own database; those writes move to the daemon's writer (ACTIVE_PROGRAM P2-DB4/DB5),
and what remains of this file is the read side.

### server.py — 6,130 lines

Measured: 40 routes (1,463 lines), 112 other functions (2,986 lines), 6 classes, 129 module-level
statements.

| Part | What is in it | Plan |
|---|---|---|
| Page routes | `/`, `/favicon.ico`, and `/chart`, `/desk`, `/exposure`, `/options` | `/` stays; the four standalone pages go with P2-4 |
| Options routes | `/api/terrain`, `/api/terrain/strikes` (174 lines), `/api/options/gamma-surface` (119), `/api/chain`, vanna, charm, tape, `/api/expiries`, `/api/level_crosses`, `/api/alerts`, `/api/forces` (101), `/api/exposure/flow` | `app/api/routes/options.py`; P2 collapses the terrain / per-strike / surface / vanna / charm slices into one read of the published record |
| Liquidity route | `/api/liquidity-snapshot` (150), `/api/levels` | `app/api/routes/liquidity.py` |
| Market routes | `/api/bars1m`, `/api/spot`, `/api/watchlist-quotes`, `/api/session` | `app/api/routes/market.py` |
| Order-flow routes | `/api/order-flow/*` (3) | `app/api/routes/order_flow.py` |
| Stream-control routes | `/api/streaming/*` (4) | `app/api/routes/streaming.py` |
| Desk routes | `/api/desk/*` (5) | decided with P2-4 (check who calls them) |
| Ops routes | `/api/health`, `/api/build`, `/api/release/current` | `app/api/routes/ops.py` |
| Push | `/api/analytics/light/stream` and the `_l1_light_sse_*` queue | `app/api/routes/push.py`; replaced by the daemon push in P2-3 |
| Chain fetch | `fetch_full_chain` (78), `_gated_safe_get_chain` (105), `_ChainGateV2`, universal/complete-chain capture | moves to the daemon (P2-1) |
| Levels producer | `_terrain_loop` (110), `_terrain_refresh_one` (112), `_publish_levels` (56), `_reprice_cached_terrain` (64), `terrain_cycle_tickers`, `terrain_staleness` (99), failure/skip notes | `app/options/levels_producer.py`, then its own process (P2-2) |
| Gamma surface projection | `project_gamma_surface` (92), `_stamp_gamma_surface_cell_stream_state` (124), coverage summary (79), stream overlay, contract admission summary (72), desired greeks | `app/options/gamma_surface.py`, with the producer |
| Bars | `aggregate_bars`, `_bar_writer` | `app/market_data/bars.py` |
| Startup | `_app_lifespan` (202), signal handlers, log sink, Schwab startup diagnostics | `app/api/lifespan.py` |
| Process identity | `_capture_process_identity` (100), `ProcessIdentityV1` | `app/infrastructure/observability/` |

Order: routes first (pure moves), then the producer and surface code, then startup. What remains
of `server.py` is the app assembly: create the app, include the route modules, attach the lifespan.

### The other large files — inventory owed before each is touched

`liquidity_value_engine.py` (1,947), `app/options/order_flow/streaming.py` (1,124) and
`engine.py` (1,093), `math_exposure_core.py` (1,018), `static/js/ed-core.js` (1,063),
`static/js/ed-gamma.js` (1,039). Their internals have not been measured yet; each gets the same
table (part, lines, used or not, plan) here before its step starts.

---

## 3. Architectural direction of flow

The production system has one directional flow:

```text
                    ┌────────────────────┐
                    │   EXTERNAL MARKET  │
                    │       DATA         │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │      COLLECT       │
                    │                    │
                    │ market_data        │
                    │ options            │
                    │ normalization      │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │ CANONICAL TRUTHS   │
                    │                    │
                    │ domain             │
                    │ market state       │
                    │ options truth      │
                    │ liquidity truth    │
                    └─────────┬──────────┘
                              │
                 ┌────────────┴────────────┐
                 │                         │
                 ▼                         ▼
      ┌────────────────────┐    ┌────────────────────┐
      │   FIND & PROVE     │    │ PRODUCTION SIGNALS │
      │                    │    │ + PROMOTED MODELS  │
      │ research           │    │                    │
      │ experiments        │    │ signals            │
      │ validation         │    │ models             │
      │ training           │    └─────────┬──────────┘
      └─────────┬──────────┘              │
                │                         │
                │ PROMOTION ONLY          │
                └────────────┬────────────┘
                             ▼
                    ┌────────────────────┐
                    │       DECIDE       │
                    │                    │
                    │ TRADE              │
                    │ WAIT               │
                    │ AVOID              │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │      API / UI      │
                    │ operator surfaces  │
                    └────────────────────┘
```

Research may consume production computations.
Production must not depend on experimental research implementations.

---

## 4. Failure-domain architecture

Application availability and capability availability are separate.

```text
                        ED CONSOLE
                            │
             ┌──────────────┴──────────────┐
             │                             │
             ▼                             ▼
      APPLICATION SHELL              CAPABILITIES
      API / UI / health              │
      observability                  ├─ Schwab market data
                                     ├─ streaming
                                     ├─ options
                                     ├─ models
                                     ├─ signals
                                     └─ decision inputs
```

A subsystem failure does not unnecessarily kill the application. Examples:

```text
Schwab unavailable
    → app stays alive
    → Schwab capability unavailable/degraded
    → Schwab-dependent decision influence fails closed

Options stream unavailable
    → app stays alive
    → options capability unavailable/degraded
    → options-dependent decision influence fails closed

Model unavailable
    → app stays alive
    → model cannot participate

Decision inputs incomplete/untrusted
    → app stays alive
    → exposure cannot be authorized

Governance broken/missing
    → app stays alive
    → no runtime effect

Git/GitHub unavailable
    → app stays alive
    → no runtime effect
```

Whole-application startup refusal is reserved for cases where the application genuinely cannot
execute coherently, such as a broken Python runtime or inability to load required core
application code.

---

## 5. One faucet = one computation

A material semantic truth has one canonical computation authority.

Not one writer. Not one serializer. **One computation.**

Therefore the following are not allowed to independently reproduce production truth:

- duplicate helpers
- alternate builders
- fallback calculators
- adapters that recompute
- SQL-derived replacements
- frontend reconstruction
- training-only reimplementations
- research copies
- compatibility shims
- cached/replayed alternate formulas
- convenience wrappers containing their own computation
- inline calculations that recreate canonical semantics

Consumers import and use the canonical computation.

---

## 6. Product architecture

The system has exactly three primary responsibilities:

```text
COLLECT
    ↓
FIND & PROVE
    ↓
DECIDE
```

### COLLECT

Capture high-fidelity, causally honest market information. Includes:

- price
- quotes
- NBBO
- bars
- streaming
- options chains
- Greeks
- open interest
- volume
- order flow
- market state
- canonical normalization

### FIND & PROVE

Discover potential predictive edge and test it honestly. Includes:

- experiments
- ablation
- training
- walk-forward validation
- purging/embargo
- leakage controls
- baseline comparisons
- calibration
- cost-aware evaluation
- candidate model evaluation

Failed candidates are removed. Research is not automatically production.

### DECIDE

Only proven and admitted information may influence exposure. Output:

```text
TRADE
WAIT
AVOID
```

Abstention/fail-closed behavior is the default when necessary truth is unavailable or unproven.

---

## 7. Governance boundary

Governance exists only to control development behavior.

**It may govern:**

- Claude
- Cursor
- other development agents
- commits
- CI
- merges
- destructive repository operations
- proof/closure requirements

**It must not govern:**

- application startup
- API availability
- UI availability
- market-data collection
- production calculations
- database availability
- Schwab connectivity
- runtime scheduling
- model inference
- decision execution

The production application must not require:

```text
governance/
.claude/
.cursor/
git
GitHub
branch state
worktree state
CI state
agent state
```

in order to operate.

---

## 8. Source / runtime / artifact / recovery separation

These are separate concerns.

```text
SOURCE
Trading/EdWebConsole/

RUNTIME
Trading/runtime/EdWebConsole/

GENERATED ARTIFACTS
Trading/artifacts/EdWebConsole/

RECOVERY
Trading/recovery/EdWebConsole/

DEVELOPMENT WORKTREES
Trading/worktrees/
```

Source updates must not endanger runtime databases, logs, tokens, generated model artifacts, or
recovery backups. Runtime state must not pollute the source checkout.

**Mechanism (RC-523 / RC-534):** `runtime_layout.py` is the ONE owner of these roots.
`ED_RUNTIME_ROOT` moves the live database, logs, the Schwab token and diagnostics;
`ED_ARTIFACTS_ROOT` (default: the runtime root) moves runtime-written reports and scorecards.
Unset, a standalone checkout uses itself; a linked Git worktree reads Git's native
``commondir`` metadata and converges on the primary worktree, so a feature worktree cannot
silently become another production data root. An explicit runtime root may be a dedicated
directory, never another linked source worktree. Converging is for reading: a live console or capture daemon starts only
from the checkout that owns its runtime (`runtime_layout.live_binding_error`); a worktree that
needs to run one sets `ED_RUNTIME_ROOT` to a separate sandbox directory. `db_authority`, `db`, `config`, `server` and
the report-writing tools read their paths from it; the module imports nothing from `tools/` or
`governance/`. Model artifacts under `models/` are still read from the source tree (a later
move, with its own row).

---

## 9. Incremental rehabilitation rule

This architecture is not permission for an unrelated flag-day rewrite. It is also not permission
to leave everything where it is.

When a mission materially touches an area:

```text
1. Fix the actual root problem.

2. Identify the cohesive responsibility being touched.

3. Compare its current ownership/location to this schematic.

4. If the responsibility can safely and cohesively move toward its canonical owner,
   move it as part of the mission.

5. Rewire consumers.

6. Delete superseded implementations.

7. Do not create another temporary architecture between CURRENT and TARGET.

8. Do not preserve bad placement solely because tests currently import it there.

9. Do not broaden into unrelated repository migration.

10. If this architecture is wrong for the encountered responsibility,
    stop the competing design and raise the evidence-based objection.
```

The goal is meaningful architectural movement as ordinary work proceeds.

**What a touched responsibility must expose for review.** Whatever module or boundary a change
materially touches — regardless of whether it moves toward its target location this session —
review needs four things made explicit, not inferred: its **behavior** (what it does, stated as
observable input/output, not as its own implementation restated); its **ownership** (which module
is the one canonical producer of the fact it computes or the state it holds — §5, "One faucet =
one computation"); its **data semantics** (identity, freshness, provenance, and what a missing or
stale value means, versus a genuine zero); and its **failure boundary** (what breaks when this
responsibility fails, and — per §4 — what must NOT break: a capability failure degrades that
capability, never the application shell around it). A responsibility can be given focused,
passing tests and still be wrong at the boundary: proof that one module works is not proof that
the modules it depends on, or that depend on it, work TOGETHER — a change that touches more than
one responsibility needs both kinds of proof, module and connection. The full review structure
this operationalizes is `governance/AGENT_OPERATING_PROCESS_V1.md` §8, requirement 8
("Architecture judgment").

---

## 10. Required agent rule

Claude, Cursor, and any future implementation agent operate under this rule:

> `docs/ARCHITECTURE.md` is the canonical target architecture for Ed Console. As you perform
> ordinary implementation work, use the schematic to move materially touched files,
> responsibilities, imports, and ownership toward their canonical target when that movement is
> safe and cohesive. Do not create new structure that moves away from the target, and do not
> preserve misplaced architecture merely because it exists today. Do not launch unrelated
> repository-wide rewrites. If you determine that the canonical architecture is technically
> wrong, impossible, or materially inferior for something encountered, say so with the evidence
> and fix it — reversing a demonstrably bad target is expected engineering, not an amendment
> that waits on permission (this restates AGENTS.md's Placement rule, the governing statement,
> for a reader who starts here). What still needs the operator is a genuine product or business
> tradeoff with no answer available in engineering evidence — not a disagreement the code and
> its own behavior can settle.

---

## 11. End state

The rehabilitation is complete when the repository itself communicates its architecture without
requiring historical knowledge:

```text
api                 → application surface
domain              → canonical semantics
market_data         → collected market truth
options             → canonical options truth
liquidity           → canonical liquidity/value truth
signals             → production signals
models              → promoted inference
decision            → TRADE / WAIT / AVOID
infrastructure      → technical implementation services
research            → Find & Prove
static              → operator UI
config              → product configuration
governance          → minimal development controls

runtime             → live mutable state
artifacts           → generated/promoted outputs
recovery            → backups
worktrees           → development
```

No giant root modules.
No duplicate semantic owners.
No runtime/governance coupling.
No source/runtime-state mixing.
No research/production ambiguity.
No hidden alternate computation paths.

**One intentional system.**
