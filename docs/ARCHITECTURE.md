# Ed Console — Canonical Repository Architecture

This is the canonical target architecture for Ed Console.

The repository is being migrated incrementally toward this structure. Whenever work materially
touches an area, the affected files, responsibilities, imports, and ownership should move toward
this target when that movement is safe and cohesive.

Do not silently create a competing architecture. If this target is technically wrong, impossible,
or materially inferior for something encountered, raise the specific objection with evidence
before deviating.

---

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
│   │   │   │   └── streaming/
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
│   │   │   └── order_flow/
│   │   │
│   │   ├── liquidity/                    # Canonical liquidity/value structure
│   │   │   ├── vwap/
│   │   │   ├── volume_profile/
│   │   │   ├── liquidity_levels/
│   │   │   └── playbook/
│   │   │
│   │   ├── signals/                      # Production signal computations
│   │   │   ├── technical/
│   │   │   ├── structural/
│   │   │   ├── flow/
│   │   │   └── regime/
│   │   │
│   │   ├── models/                       # Promoted production inference only
│   │   │   ├── xgb/
│   │   │   ├── lstm/
│   │   │   ├── monte_carlo/
│   │   │   ├── fusion/
│   │   │   ├── calibration/
│   │   │   └── registry/loading
│   │   │
│   │   ├── decision/                     # DECIDE
│   │   │   ├── admission/
│   │   │   ├── policy/
│   │   │   ├── confidence/
│   │   │   ├── sizing/
│   │   │   └── trade_wait_avoid/
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
│   ├── research/                          # FIND & PROVE
│   │   ├── experiments/
│   │   ├── validation/
│   │   ├── backtests/
│   │   ├── calibration/
│   │   ├── training/
│   │   ├── ablation/
│   │   └── candidate_models/
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
│       ├── ed_console.db
│       ├── stream_capture.db
│       ├── tokens/
│       ├── logs/
│       └── state/
│
├── artifacts/
│   └── EdWebConsole/                      # GENERATED / PROMOTED ARTIFACTS
│       ├── models/
│       ├── research_outputs/
│       ├── calibration_outputs/
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

## 2. Current → target ownership

The current repository is not required to reach this structure in one rewrite. It is required to
move toward it whenever materially touched.

```text
CURRENT                                  TARGET

server.py
  routes                         →       app/api/routes/
  lifespan/startup               →       app/api/lifespan/
  business logic                 →       owning domain package
  market calculations            →       app/domain / app/market_data /
                                         app/options / app/signals
  decision logic                 →       app/decision/

db.py                            →       app/infrastructure/database/

market_state.py                  →       app/market_data/market_state/

schwab_client.py                 →       app/market_data/schwab/
                                         or infrastructure/external_clients/
                                         depending on responsibility

polling_adapter.py               →       app/market_data/

order_flow_engine.py             →       app/options/order_flow/

options chain logic              →       app/options/chains/

gamma / delta / vanna / charm    →       app/options/

liquidity_value_engine.py        →       app/liquidity/

liquidity_models.py              →       app/liquidity/

signals.py                       →       app/signals/

regime_engine.py                 →       app/domain/regimes/
                                         or app/signals/regime/
                                         based on actual responsibility

prediction_engine.py             →       app/models/

bayesian_fusion.py               →       app/models/fusion/

monte_carlo.py                   →       app/models/monte_carlo/

call_engine.py                   →       app/decision/

rules_engine.py                  →       app/decision/
                                         or owning domain package

static/index.html                →       modular static/pages/components/js/css

training scripts                 →       research/training/

ablation / experiments           →       research/ablation/
                                         research/experiments/

calibration research             →       research/calibration/

production calibration artifacts →       artifacts/EdWebConsole/

large tools population           →       delete obsolete tools;
                                         move real responsibilities to owners;
                                         retain only small active toolbox

governance sprawl                →       minimal governance/

reports/evidence/generated data  →       artifacts/EdWebConsole/
                                         or research outputs

data/ed_console.db               →       runtime/EdWebConsole/ed_console.db

stream_capture.db                →       runtime/EdWebConsole/

logs                             →       runtime/EdWebConsole/logs/

backups/db                       →       recovery/EdWebConsole/backups/

model files                      →       artifacts/EdWebConsole/models/

temporary generated files        →       artifacts/EdWebConsole/temporary_outputs/

development worktrees            →       Trading/worktrees/
```

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

---

## 10. Required agent rule

Claude, Cursor, and any future implementation agent operate under this rule:

> `docs/ARCHITECTURE.md` is the canonical target architecture for Ed Console. As you perform
> ordinary implementation work, use the schematic to move materially touched files,
> responsibilities, imports, and ownership toward their canonical target when that movement is
> safe and cohesive. Do not create new structure that moves away from the target, and do not
> preserve misplaced architecture merely because it exists today. Do not launch unrelated
> repository-wide rewrites. If you determine that the canonical architecture is technically
> wrong, impossible, or materially inferior for something encountered, raise the specific
> evidence-based objection before implementing a competing design. The operator decides
> architectural amendments; agents do not silently change the architecture.

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
