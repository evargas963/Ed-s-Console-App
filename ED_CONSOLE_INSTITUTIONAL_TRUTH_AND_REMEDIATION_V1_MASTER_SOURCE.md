<!-- NOT_A_WORK_LIST: exact operator source; actionable work is the sole master checklist only -->

Classification: exact operator source of record. Not an actionable
work list.
Actionable unresolved work lives only in
ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md.

ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1 — MASTER CHECKLIST

Parent status: NOT_PROVEN

Allowed closure statuses: PASS / FAIL / NOT_PROVEN / UNAVAILABLE

Separate classification: NATIVE / DERIVED / HEURISTIC / PROXY

A checked box means the item has complete current-repo proof,
required runtime/live proof, downstream consumer proof, and any
required predictive proof. A child PASS may never close a parent
item by itself.

Parent status is NOT_PROVEN until every material money-path item is
PASS or legitimately UNAVAILABLE and mechanically prevented from
being represented as available or decision-grade
Allowed closure statuses are only PASS / FAIL / NOT_PROVEN /
UNAVAILABLE
Separate classification NATIVE / DERIVED / HEURISTIC / PROXY is
required for operator-visible and model-facing concepts
A checked box requires complete current-repo proof plus required
runtime/live proof plus downstream consumer proof plus any required
predictive proof
A child PASS may never close a parent item by itself

0. Mission identity / evidence baseline

Re-fetch origin/main before each major execution phase
Record exact HEAD_SHA
Record exact origin/main SHA
Prove clean/dirty worktree state
Prove exact branch/worktree being audited
Prove exact production process SHA
Prove exact database identity
Prove exact model-artifact identities
Prove exact runtime configuration/environment
Establish that no prior PASS or institutional claim is grandfathered
Establish single machine-readable truth matrix as the authoritative
mission board
Ensure newly discovered defects append to this same parent mission
rather than creating competing governance systems

A. RAW MARKET DATA / SOURCE TRUTH

A1. Schwab equities L1

Schwab equities L1 entitlement proven
Schwab equities L1 subscription path proven
Schwab equities L1 live RTH receipt proven
Schwab equities L1 bid/ask/last field presence proven
Schwab equities L1 bid/ask size semantics proven
Schwab equities L1 volume semantics proven
Schwab equities L1 exchange/MIC/ID semantics independently proven
where used
Schwab equities L1 quote timestamp semantics proven
Schwab equities L1 trade timestamp semantics proven
Schwab equities L1 bid/ask timestamp semantics proven
Schwab equities L1 event cadence measured during RTH
Schwab equities L1 duplicate behavior measured
Schwab equities L1 repeated-timestamp behavior measured
Schwab equities L1 out-of-order behavior measured
Schwab equities L1 missing-update behavior measured
Schwab equities L1 stale-feed behavior proven
Schwab equities L1 disconnect behavior proven
Schwab equities L1 reconnect behavior proven
Schwab equities L1 data after reconnect proven complete enough for
claimed uses
Schwab equities L1 session transition behavior proven
Schwab equities L1 extended-hours behavior proven
Schwab equities L1 ticker-switch behavior proven
Schwab equities L1 no silent source fallback proven

A2. Known L1 defect — reconstructed tape

Known L1 defect: same-TRADE_TIME_MILLIS observations are dropped
Quantify actual same-ms collision frequency during RTH
Quantify lost reported size due to collision handling
Quantify lost intra-ms price transitions
Correct misleading code comment claiming price/size refresh behavior
Determine whether retaining every L1 update improves observation
fidelity
Ensure any fix does not falsely relabel L1 reconstruction as native
time-and-sales
Preserve raw incoming update order/receive sequence for future
analysis
Explicitly classify reconstructed trade stream as incomplete
observation unless stronger evidence exists

A3. Native aggressor / true tape

Establish whether authenticated Schwab exposes native aggressor side
Establish whether authenticated Schwab exposes native true
time-and-sales
Establish whether TIMESALE is genuinely unavailable versus
subscription/configuration failure
If TIMESALE unavailable, mark UNAVAILABLE mechanically and in UI
contracts
Prevent quote/tick-rule direction from being labeled native
aggressor
Prevent reconstructed tape from being labeled complete executed flow

A4. NYSE Level 2

NYSE Level 2 entitlement proven
NYSE Level 2 live RTH receipt proven
NYSE Level 2 snapshot versus incremental-update semantics proven
NYSE Level 2 full visible depth behavior measured
NYSE Level 2 price-level ordering proven
NYSE Level 2 TOTAL_VOLUME semantics proven
NYSE Level 2 nested attribution semantics proven or withheld
NYSE Level 2 NUM_* semantics proven or neutralized
NYSE Level 2 nested sequence semantics proven or neutralized
NYSE Level 2 BOOK_TIME semantics proven
NYSE Level 2 cadence measured
NYSE Level 2 duplicate/gap behavior measured
NYSE Level 2 reconnect behavior proven
NYSE Level 2 stale-book behavior proven

A5. NASDAQ Level 2

Same complete proof battery as A4
Venue-specific differences documented
Cross-venue merging/non-merging policy proven

A6. Options L1

Options L1 entitlement proven
Options L1 live option subscription proven
Options L1 contract identity proven
Options L1 strike/expiry/DTE semantics proven
Options L1 bid/ask/last/size proven
Options L1 OI semantics/freshness proven
Options L1 totalVolume semantics/freshness proven
Options L1 IV semantics proven
Options L1 Greeks semantics proven
Options L1 stale/missing field behavior proven

A7. Options Book

Options Book entitlement proven
Options Book live receipt proven
Options Book depth shape proven
Options Book price aggregation semantics proven
Options Book attribution semantics proven or withheld
Options Book cadence/gap/reconnect behavior proven

A8. Option chain

Option chain REST acquisition proven
Option chain exact strike coverage proven
Option chain exact expiry coverage proven
Option chain freshness proven
Option chain quote/greek/OI consistency proven
Option chain malformed/poisoned contract handling proven
Option chain pagination/range limitations proven
Live narrow-chain versus wide-chain distinction eliminated or
explicitly surfaced

A9. Historical bars

Historical bars completeness proven
Historical bars gap detection proven
Historical bars repair/backfill semantics proven
Historical bars synthetic/repaired-row classification proven
Historical bars timestamp alignment proven
Historical bars corporate actions proven
Historical bars extended-hours/RTH semantics proven
Historical bars duplicates proven absent or handled
Historical bars OHLCV correctness proven

A10. Fundamentals and any other source

Inventory every REST/live external source influencing money paths
Prove source semantics and availability for each external money-path
source
Prove no undocumented fallback silently changes the semantic meaning
of any external source

B. TEMPORAL SUFFICIENCY / HISTORY

B. TEMPORAL SUFFICIENCY / HISTORY

Inventory every semantic concept requiring history
Identify exact temporal window each history-requiring concept
requires
Prove retained data spans that required window
Prove resolution/cadence is sufficient for each history-requiring
concept
Prove history survives process restart where required
Prove replay can reproduce calculations that require history

B1. Known temporal concepts requiring proof

Temporal sufficiency proven for persistence
Temporal sufficiency proven for migration
Temporal sufficiency proven for replenishment
Temporal sufficiency proven for absorption
Temporal sufficiency proven for add/pull
Temporal sufficiency proven for liquidity depletion
Temporal sufficiency proven for liquidity acceleration
Temporal sufficiency proven for rolling pressure
Temporal sufficiency proven for wall persistence
Temporal sufficiency proven for wall migration
Temporal sufficiency proven for gamma migration
Temporal sufficiency proven for OI migration
Temporal sufficiency proven for charm drift
Temporal sufficiency proven for vanna drift
Temporal sufficiency proven for regime transitions
Temporal sufficiency proven for volatility transitions
Temporal sufficiency proven for signal transitions
Temporal sufficiency proven for alert transitions
Temporal sufficiency proven for trend persistence
Temporal sufficiency proven for decay

B2. Known L2-history defect

Known L2-history defect: live book state retains only a tiny
in-memory snapshot deque
Design canonical displayed-L2 history representation
Determine snapshot vs delta representation from measured Schwab
semantics
Add local monotonically increasing receive sequence for L2 history
Preserve vendor timestamp on L2 history
Preserve server receive timestamp on L2 history
Preserve source/service on L2 history
Preserve ticker on L2 history
Preserve side/price/displayed volume on L2 history
Preserve schema/provenance version on L2 history
Build bounded live in-memory L2 history for visualization
Build durable L2 replay/research persistence
Measure expected L2 event rate
Measure expected L2 daily storage
Choose L2 storage architecture based on measurement, not convenience
Do not blindly write high-frequency L2 history into existing
oversized SQLite DB
Define L2 history retention
Define L2 history compression
Define L2 history checkpoint/delta strategy
Define L2 history crash recovery
Prove deterministic L2 history reconstruction

B3. Bookmap-style heatmap

Bookmap-style heatmap: historical displayed-liquidity time×price
data available
Heatmap generated entirely from live canonical L2 history
No static/fake heatmap
Heatmap time axis live-scrolls
Heatmap price axis correctly normalized
Liquidity intensity accurately represents displayed size
Heatmap data gaps visually exposed
Heatmap staleness visually exposed
Heatmap restart behavior proven
Historical replay reproduces live heatmap
UI explicitly says displayed L2, not MBO
No Level-3/queue/individual-order implication on heatmap

C. SEMANTIC TRUTH / NAMING

C. SEMANTIC TRUTH / NAMING

For every operator-visible or model-facing concept: exact definition
documented from code
For every operator-visible or model-facing concept: exact
formula/algorithm identified
For every operator-visible or model-facing concept: label matches
actual computation
For every operator-visible or model-facing concept: source
classification assigned (NATIVE/DERIVED/HEURISTIC/PROXY)
For every operator-visible or model-facing concept: limitations
explicitly stated
For every operator-visible or model-facing concept: missing-data
semantics proven
For every operator-visible or model-facing concept: downstream
meaning proven
For every operator-visible or model-facing concept: UI label does
not overstate evidence

C1. High-risk labels to adjudicate

High-risk label adjudicated: absorption
High-risk label adjudicated: replenishment
High-risk label adjudicated: institutional flow
High-risk label adjudicated: smart money
High-risk label adjudicated: CVD
High-risk label adjudicated: delta / signed flow
High-risk label adjudicated: tape pressure
High-risk label adjudicated: selling pressure / buying pressure
High-risk label adjudicated: liquidity
High-risk label adjudicated: liquidity wall
High-risk label adjudicated: gamma wall
High-risk label adjudicated: gamma flip
High-risk label adjudicated: gamma pin
High-risk label adjudicated: dealer regime
High-risk label adjudicated: microstructure regime
High-risk label adjudicated: support
High-risk label adjudicated: resistance
High-risk label adjudicated: breakout
High-risk label adjudicated: breakdown
High-risk label adjudicated: continuation
High-risk label adjudicated: reversal
High-risk label adjudicated: confidence
High-risk label adjudicated: confluence
High-risk label adjudicated: tradeability
High-risk label adjudicated: directional probability
High-risk label adjudicated: recommendation
High-risk label adjudicated: bias
High-risk label adjudicated: edge

D. ONE FAUCET = ONE COMPUTATION

D. ONE FAUCET = ONE COMPUTATION

Complete repo-wide producer inventory
Backend Python inspected for duplicate authorities
Frontend JS inspected for duplicate authorities
HTML inline scripts inspected for duplicate authorities
SQL inspected for duplicate authorities
Training inspected for duplicate authorities
Research inspected for duplicate authorities
Replay inspected for duplicate authorities
Caches inspected for duplicate authorities
Compatibility shims inspected for duplicate authorities
Helpers/wrappers/builders inspected for duplicate authorities
Normalization paths inspected for duplicate authorities
Persistence-derived SQL expressions inspected for duplicate
authorities
Tests inspected for shadow/reference computations that escaped into
production logic
Every material concept has one canonical computation authority
Downstream consumers import/call authority rather than recompute
Absence/fallback behavior does not create a second authority
Historical/replay computation uses same authority
Training/serve computation uses same authority
UI does not recompute semantic truth

D1. Known duplicate authority — absorption

Known duplicate authority FAIL:
order_flow_engine._compute_absorption
Known duplicate authority FAIL:
institutional_behavior.compute_liquidity_behavior_row::absorption_score
Trace all other absorption* producers
Trace all absorption DB writers/readers
Trace absorption feature contract
Trace absorption live feature adapter
Trace absorption model inputs
Trace absorption research studies
Trace absorption calibration
Trace absorption replay
Trace absorption reports
Trace absorption UI
Trace absorption decision engine
Determine historical absorption semantic eras
Determine whether persisted same-named absorption field has changed
meaning over time
Quarantine contaminated absorption artifacts/data where required
Withhold all existing absorption authorities from decision-grade use
Either replace absorption with one semantically valid authority or
retire the concept

E. ORDER FLOW / MICROSTRUCTURE

E1. Canonical point-in-time book microstructure

Re-prove raw book → canonical normalization
Re-prove bid ordering
Re-prove ask ordering
Re-prove invalid-size rejection
Re-prove crossed-book behavior
Re-prove locked-book behavior
Re-prove top-of-book
Re-prove mid
Re-prove spread
Re-prove microprice
Re-prove Top-1 depth
Re-prove Top-3 depth
Re-prove Top-5 depth
Re-prove Top-1 imbalance
Re-prove Top-3 imbalance
Re-prove Top-5 imbalance
Re-prove depth-pressure curve
Re-prove book slope
Re-prove concentration
Re-prove wall-candidate heuristic
Re-prove book age
Re-prove quote age
Re-prove book provenance
Re-prove no duplicate book-calculation authority
Re-prove live engine and API serialize same semantic book state
Re-prove fail-closed on missing book
Re-prove stale-book negative control
Re-prove book ticker switch
Re-prove book reconnect
Re-prove book RTH live proof
Re-prove book replay proof

E2. Legacy Order Flow weighted composite

Legacy Order Flow weighted composite: inventory exact current
formula
Legacy OF composite: inventory all weights
Legacy OF composite: inventory fixed thresholds
Prove whether each OF composite leg has equivalent semantic quality
Trace all OF composite consumers
Trace OF composite UI use
Trace OF composite model feature use
Trace OF composite decision influence
Trace OF composite research use
Trace OF composite calibration use
Prove independent justification for OF composite weighting
Prove predictive justification for combined OF composite
If OF composite not proven, classify NOT_ADMITTED
Safely migrate any consumers/artifacts that depend on OF composite
Remove false precision from operator UI for OF composite
Preserve separate OF legs where valid

E3. Executed-flow proxies

tape_pressure_30s exact semantics
tape_pressure_2m exact semantics
tape_pressure_5m exact semantics
cum_delta_proxy exact semantics
cum_delta_slope exact semantics
institutional_flow_proxy_score exact semantics
Executed-flow proxies all marked PROXY
No native-aggressor claim on executed-flow proxies
No true-CVD claim on executed-flow proxies
No complete-volume claim on executed-flow proxies
Field names corrected where proxy nature is hidden
Executed-flow source → MarketState → API trace
Orphan executed-flow status source-proven, not inferred from null
runtime values
Executed-flow decision influence removed unless separately admitted
Executed-flow predictive usefulness tested independently if retained

E4. Absorption / replenishment

_compute_absorption marked NOT_ADMITTED
Current volume÷range absorption formula renamed or retired
Current replenishment earliest-vs-latest total-depth heuristic
renamed or retired
Misleading absorption/replenishment docstrings corrected
Actual level-specific absorption definition designed only from
available evidence
Actual replenishment definition requires time/history
Absorption/replenishment temporal windows defined
Absorption/replenishment fail-closed behavior defined
Absorption/replenishment replay reproducibility proven
Absorption/replenishment semantic validity proven before predictive
validity
Absorption/replenishment predictive validity proven before decision
admission

E5. Microstructure regime

Current microstructure regime authority inventory complete
No UI-only microstructure regime invention
Microstructure state taxonomy derived from measurable primitives
rather than invented first
Balanced auction definition
Buy-pressure definition
Sell-pressure definition
Liquidity-pull definition
Replenishment definition (regime)
Absorption definition (regime)
Exhaustion definition
Liquidity-vacuum definition
Spread-expansion definition
Microstructure regime exact temporal requirements
Microstructure regime confidence/trust definition
Microstructure regime transition logic
Microstructure regime fail-closed logic
Microstructure regime replay
Microstructure regime predictive/decision validity separately tested

F. LEVELS / LIQUIDITY / VALUE

F1. VWAP

VWAP source bars/trades proven
VWAP formula proven
VWAP session boundary proven
VWAP resets proven
VWAP extended-hours policy proven
VWAP one faucet
VWAP UI fidelity
VWAP replay
VWAP predictive status separately classified

F2. VWAP sigma bands

VWAP sigma bands variance/σ formula proven
VWAP sigma bands weighting semantics proven
VWAP sigma bands session semantics proven
VWAP sigma bands one faucet
VWAP sigma bands replay
VWAP sigma bands predictive validity separately classified

F3. Volume Profile

Volume Profile known defect: typical-price volume dump eliminated
Volume Profile price-distributed/tick-based methodology implemented
Volume Profile POC proven
Volume Profile VAH proven
Volume Profile VAL proven
Volume Profile session/window definition proven
Volume Profile reproducibility proven
Volume Profile comparison against institutional/reference
calculation
Volume Profile UI uses corrected authority only

F4. Overnight

Overnight known defect: calendar-based assumptions eliminated
Overnight prior trading session close → next open semantics
Overnight Monday includes Friday correctly
Overnight holidays handled
Overnight half-days handled
Overnight extended-session inclusion/exclusion defined
ONH proven
ONL proven

F5. Prior day / ORB

PDH proven
PDL proven
PDC proven
Prior trading day semantics proven
ORB high proven
ORB low proven
ORB mid proven
Exact opening-range window proven
ORB/prior-day holiday/half-day behavior proven

F6. Liquidity/support/resistance language

buy_side_liquidity adjudicated
sell_side_liquidity adjudicated
Stop-cluster semantics proven or label removed
Support calculation proven
Resistance calculation proven
Reaction-zone ranking proven
Structure verdict proven
Continuation/rejection/chop classifications proven
Liquidity/support/resistance predictive influence blocked until Find
& Prove PASS

G. OPTIONS / DEALER EXPOSURE

G1. Chain completeness

Chain completeness: live UI chain range
Chain completeness: wide-chain range
Chain completeness: expiry coverage
Chain completeness: strike coverage sufficient for each metric
Chain completeness: missing strikes
Chain completeness: stale chain handling
Chain completeness: contract filtering
Chain completeness: 0DTE handling
Chain completeness: cross-expiry aggregation

G2. Greeks

Greeks delta validity
Greeks gamma validity
Greeks vega validity
Greeks theta validity
Greeks IV validity
Greeks poisoned-greek rejection
Greeks fail-closed behavior
Greeks sanitization consistent research/live
Greeks exact vendor-vs-derived provenance

G3. OI

OI freshness
OI update cadence
OI same-day limitations
No false intraday OI migration claim

G4. GEX

GEX exact formula
GEX contract multiplier
GEX sign convention
GEX dealer-side assumption
GEX expiration weighting if any
GEX strike coverage
GEX expiry coverage
GEX live/research parity
GEX replay
GEX predictive validity separately proven

G5. DEX

same proof class as GEX

G6. Vanna

Vanna exact definition
Vanna IV surface dependence
Vanna units
Vanna strike/expiry completeness
Vanna assumptions
Vanna predictive admission

G7. Charm

Charm exact definition
Charm time-to-expiry semantics
Charm trading-day/year fraction
Charm sign convention
Charm strike coverage
Charm expiry coverage
Charm predictive admission

G8. Gamma flip

Gamma flip known limitation: narrow-chain live flip eliminated or
clearly withheld
Gamma flip full relevant strike coverage
Gamma flip cumulative method proven
Gamma flip wing-IV handling proven
Gamma flip wide-chain live path wired
Gamma flip freshness
Gamma flip self-declared trust status
Gamma flip external comparison where useful
Gamma flip replay
Gamma flip predictive validity separately proven

G9. Gamma pin / walls

Gamma pin / walls definition
Gamma pin / walls full-chain dependency
Gamma pin / walls difference from size anomaly
Gamma pin / walls one faucet
Gamma pin / walls trust status
Gamma pin / walls predictive validity

G10. Dealer regime

Dealer regime long/short gamma semantics
Dealer-position assumption clearly exposed
No claim of actual dealer inventory
Dealer regime confidence gating
Stale/untrusted gamma forces withheld dealer regime
Dealer regime predictive significance separately proven

H. MODEL / FIND & PROVE

H1. Scientific pipeline itself

Labels proven
Entry timestamp proven
Exit/outcome timestamp proven
Future information excluded
Feature availability as-of decision time proven
Lookahead audit
Label-shuffle test
Feature-shuffle tests
Leakage audit
Meta-learner leakage audit
Purged K-fold where applicable
Embargo where applicable
Time-series/walk-forward split
No random temporal contamination
Ticker isolation where required
Cross-ticker universality where claimed
Trivial baselines
Persistence baseline
Class-prior baseline
Cost-aware baseline
Multiple-hypothesis correction
Holm-Bonferroni where appropriate
Sample sufficiency
Confidence intervals
Calibration
Calibration per ticker/horizon where required
Regime-conditioned performance
Cost/slippage sensitivity
Reproducibility
Exact feature version
Exact model artifact version
Training/serve parity
Replay parity (scientific pipeline)

H2. Era contamination

Inventory every study classified era-contaminated
Determine contamination boundary
Determine semantic-feature changes across eras
Determine outcome/timestamp changes across eras
Quarantine affected historical results
Rerun era-contaminated studies only after scientific pipeline PASS
Do not cite contaminated positive or negative results

H3. Existing model stack

XGB implementation correctness
LSTM implementation correctness
Transformer legacy/removal effects
Monte Carlo implementation correctness
Fusion implementation correctness
Meta-model implementation correctness
Kalman implementation correctness
HMM implementation correctness
GARCH implementation correctness
Model input semantics
Model output semantics
Artifact compatibility
Stale artifact detection
Semantic feature drift detection
Safe abstention
Retrain requirement after feature changes
No model admitted without positive OOS evidence net of costs

H4. Predictive validity

At least one candidate beats trivial baselines
Predictive validity OOS
Predictive validity net of costs
Predictive validity sufficiently sampled
Predictive validity corrected for multiple testing
Predictive validity survives regime/robustness checks
Predictive validity calibration acceptable
Predictive validity replicated
Then and only then admitted into Decide

I. DECISION ENGINE

I1. Decision inputs

Decision input: call_signal
Decision input: execution_mode
Decision input: final_tradeable
Decision input: is_no_trade
Decision input: terrain posture
Decision input: veto stack
Decision input: wait reasons
Decision input: decision-gate reasons
Decision input: recommendation side
Decision input: bias
Decision input: confidence
Decision input: confluence
Decision input: entry
Decision input: stop
Decision input: target
Decision input: target2
Decision input: invalidation
Decision input: size
Decision input: trade type

I2. Unified decision

Canonical TRADE / WAIT / AVOID authority exists
Explicit AVOID semantics
WAIT distinguished from hostile/avoid state
No arbitrary weighted averaging in unified decision
Disagreement remains visible
Deterministic reason lineage
Contradiction list canonical
No frontend decision synthesis
Fail-closed when required decision evidence absent

I3. Plan semantics

Plan trigger primitive if required
Entry populated only when meaningful
Stop semantics
Target semantics
R:R semantics
Invalidation semantics
Blank/WAIT fields explained rather than misleading
What changes my mind is canonical
Positive tradeability requires admitted evidence

J. RISK / EXECUTION

Transaction-cost model
Spread model
Slippage model
Market/limit fill assumptions
Partial fills
Order latency
Signal latency
Data latency
Stop execution
Gaps through stop
Overnight gap risk if relevant
Position sizing
Max position risk
Max portfolio risk
Correlation risk
Sector concentration
Ticker concentration
Daily loss limit
Drawdown limit
Stale-data kill
Model-unavailable kill
Broker disconnect kill if applicable
Emergency kill switch
Execution reconciliation
Order-state reconciliation
No real-money approval until all material items PASS

K. UI / OPERATOR TRUTH

K1. Architecture

Dashboard role proven
Levels role proven
Order Flow role proven
Options role proven
Plan role proven
Chart role proven
Desk role proven
Terrain consolidation decision proven
Exposure consolidation decision proven
Console content migration proven
Dead hidden legacy UI removed
Duplicate surfaces removed
Ops/Governance/Diagnostics separated from trading workflow

K2. Every decision-facing visual

Every decision-facing visual: exact backend source
Every decision-facing visual: exact canonical producer
Every decision-facing visual: no JS recomputation
Every decision-facing visual: freshness visible
Every decision-facing visual: stale state visible
Every decision-facing visual: unavailable state visible
Every decision-facing visual: proxy status visible
Every decision-facing visual: heuristic status visible
Every decision-facing visual: low-confidence status visible
Every decision-facing visual: source classification where materially
useful
Every decision-facing visual: no misleading color
Every decision-facing visual: no misleading precision
Every decision-facing visual: no hidden fallback
Every decision-facing visual: no static market-state data
masquerading as live

K3. Storytelling

Edge shown only where evidence supports edge
Bias has exact definition
Signal has exact definition
Contradiction visible
Uncertainty visible
No opaque score hiding disagreement
Decision reason visible
Invalidation visible
What changes the view grounded in canonical states

L. REPLAY / AUDITABILITY

Raw input retained where required
Canonical normalized input retained
Code SHA retained
Model-artifact SHA retained
Policy version retained
Feature schema/version retained
Thresholds retained
Calibration retained
Source timestamps retained
Receive timestamps retained
Event ordering retained
Decision inputs retained
Decision result retained
Explanation/lineage retained
Historical replay reproduces live computation
Replay does not call alternate formulas
Replay survives schema/version changes
Live/replay mismatch mechanically fails

M. OPERATIONS / PRODUCTION RELIABILITY

M1. Production isolation

Primary checkout production-only
Clean origin/main for production
Agent mutation of primary blocked
Claude isolated worktree policy reconciled with
one-canonical-worktree law
Cursor isolated workspace/branch policy reconciled with
one-canonical-worktree law
Proof server isolated from production
Proof port separate
Proof DB cannot silently mutate canonical production DB
Production port only serves clean approved SHA

M2. Known worktree-policy conflict

Shared-root policy retired or corrected
RC-129 assumptions reconciled with RC-350
RC-125 live proof works against proof runtime
Negative control: agent cannot mutate prod tree
Negative control: dirty prod cannot launch
Positive control: clean main launches
Proof and production runtimes can coexist

M3. Stream reliability

Automatic reconnect fully proven or implemented
Disconnect detection
Retry/backoff
Resubscribe
State invalidation during reconnect
Stale UI state blocked during reconnect
Recovery proof
No silent REST semantic substitution

M4. Single-ticker L2 scope

Active-ticker-only L2 behavior explicitly documented
Desk does not imply multi-ticker L2 if unavailable
Ticker-switch clearing/carry behavior proven
History store identity correct across ticker switches

M5. Known Schwab worker leak

Reproduce Schwab orphan process leak
Schwab worker leak root cause proven
Explicit client/process cleanup implemented
Scheduled-job lifecycle fixed for Schwab workers
Week-long/no-orphan observation if required
No lingering worker CPU/memory leakage

M6. Resource / performance

CPU budget
Memory budget
DB growth
L2-history storage growth
UI latency
API latency
Stream-to-state latency
State-to-UI latency
High-load behavior
Backpressure
Resource exhaustion behavior

M7. Backup / restore / crash

Canonical DB backup
Restore tested
Schema migration rollback
Crash recovery
Abrupt stream loss
Abrupt process termination
Corrupted cache/history handling
Backup identity/provenance

M8. Scheduled jobs

Scheduled jobs inventory complete
Scheduled jobs schedule correct
Scheduled jobs commands correct
Scheduled jobs environment correct
Scheduled jobs logs
Scheduled jobs exit codes
Stale/failed task visibility
No hidden host-only jobs outside repo inventory

N. MAINTAINABILITY / ARCHITECTURAL PROOFABILITY

N1. Existing debt

Function-complexity findings classified
Function-length findings classified
File-length findings classified
Ruff-quality findings classified
Fake-default findings classified
Type-safety gaps classified

N2. Promote debt to correctness defect where it

Promote debt to correctness defect where it obscures semantic
authority
Promote debt to correctness defect where it prevents exhaustive
testing
Promote debt to correctness defect where it permits hidden fallback
Promote debt to correctness defect where it permits duplicate
computation
Promote debt to correctness defect where it couples unrelated money
paths
Promote debt to correctness defect where it prevents review
Promote debt to correctness defect where it prevents replay
Promote debt to correctness defect where it prevents runtime
isolation
Promote debt to correctness defect where it prevents deterministic
behavior

N3. server.py

Determine which server.py size/complexity is merely maintainability
debt
Determine which server.py areas prevent money-path proof
Refactor server.py only where required for correctness/provability
No functional semantic changes hidden inside server.py cleanup

O. SEMANTIC-ERA / HISTORICAL CONTAMINATION

For every material persisted or trained feature: identify semantic
definition by code era
Identify first/last SHA using each feature definition
Identify DB rows produced under each definition
Identify normalized feature tables affected
Identify training datasets affected
Identify trained artifacts affected
Identify calibration artifacts affected
Identify research reports affected
Identify replay results affected
Identify decision records affected
Quarantine mixed-era data when semantics changed materially
Retrain/revalidate artifacts when input semantics changed
No same column name allowed to conceal materially different
historical meaning

O1. Absorption era contamination

Absorption era: complete producer-era graph
Absorption era: exact DB population query
Absorption era: exact NULL-rate calculation with date
range/denominator
Absorption era: identify model-facing definition
Absorption era: identify order-flow-composite definition
Absorption era: determine overlap
Absorption era: determine mixed-era training
Absorption era: invalidate/rebuild affected artifacts

P. DATA QUALITY / DATABASE TRUTH

Schema inventory
Writer inventory
Reader inventory
Duplicated semantic columns
Stale columns
Orphan columns
Silent default values
Sentinel values
NULL semantics
Timestamps (DB truth)
Ticker identity (DB)
Option contract identity (DB)
Timeframe identity (DB)
Duplicate primary semantic keys
Missing rows
Repair provenance (DB)
Synthetic-row provenance (DB)
Corporate actions (DB)
Retention (DB)
DB bloat sources
Indexes
Integrity checks
Reproducible snapshot extraction
Write/read parity
No SQL-side semantic recomputation violating ONE FAUCET

Q. SOURCE → DISPLAY CARD FIDELITY

Card fidelity: observation value correct
Card fidelity: observation unit correct
Card fidelity: observation timestamp correct
Card fidelity: API value identical
Card fidelity: frontend receives identical value
Card fidelity: frontend does not transform semantics
Card fidelity: frontend label correct
Card fidelity: frontend unit correct
Card fidelity: frontend direction/color correct
Card fidelity: frontend missing-state correct
Card fidelity: frontend stale-state correct
Card fidelity: multi-ticker proof
Card fidelity: multi-horizon proof where applicable
Card fidelity: live RTH proof where applicable
Overall card fidelity remains unchecked until every money-path card
satisfies this

R. UNIVERSE / TICKER / HORIZON UNIVERSALITY

Universe proof includes SPY
Universe proof includes QQQ
Universe proof includes IWM
Universe proof includes representative high-price equity
Universe proof includes representative low-price equity
Universe proof includes representative high-volatility equity
Universe proof includes symbol with punctuation such as BRK.B where
supported
Universe proof includes index symbols where supported
Horizon proof includes 1m
Horizon proof includes 5m
Horizon proof includes 15m
Horizon proof includes 60m
Ticker-agnostic semantics
Horizon-specific semantics where intentional
No SPY-only proof closes universal parent claim

S. FAILURE MODES / FAIL-CLOSED BEHAVIOR

Fail-closed: missing quote
Fail-closed: missing book
Fail-closed: one-sided book
Fail-closed: crossed book
Fail-closed: stale book
Fail-closed: stale quote
Fail-closed: stream disconnect
Fail-closed: REST failure
Fail-closed: option chain failure
Fail-closed: partial option chain
Fail-closed: invalid Greek
Fail-closed: zero/negative price
Fail-closed: zero/negative size
Fail-closed: NaN
Fail-closed: infinity
Fail-closed: missing model artifact
Fail-closed: stale model artifact
Fail-closed: semantic-version mismatch
Fail-closed: missing calibration
Fail-closed: DB lock/failure
Fail-closed: API exception
Fail-closed: frontend fetch failure
Fail-closed: process restart
Fail-closed: overnight→RTH transition
Fail-closed: RTH→after-hours transition
Fail-closed: ticker change
Fail-closed: clock/daylight-saving transition
Fail-closed: holiday/half-day
Every failure defaults to truthful abstention rather than fabricated
normality

T. SECURITY / SECRETS / AUTHORIZATION

Schwab credentials storage
Tokens
Refresh-token handling
Log redaction
Environment secrets
No secrets in repo
Local file permissions where relevant
Debug endpoints
Destructive DB operations
Authorization for resets/cleanups
Production/proof environment separation (security)
External-facing endpoints reviewed

U. OBSERVABILITY

Feed health visible
Source authority visible
Freshness visible (observability)
Event lag visible
Dropped messages visible where detectable
Reconnect count visible
Calculation failures visible
Fail-closed reasons visible
Decision vetoes visible
Model artifact identity visible
DB write failures visible
Scheduled-job failures visible
Process leaks visible
Memory/CPU/storage visible
UI fetch failures visible
Operator sees data-quality state before trusting a value

V. PREDICTIVE VS DESCRIPTIVE SEPARATION

For every field/panel: classify as descriptive market state or
predictive signal
Descriptive state does not imply edge
Contextual level does not imply predictive edge
Heuristic does not imply predictive edge
Proxy does not imply predictive edge
Predictive language appears only after Find & Prove admission
EDGE UI label only appears when positive evidence exists
Confidence cannot be a synonym for mathematical certainty unless
calibrated
Bias cannot be silently interpreted as a trade recommendation
SELLING PRESSURE cannot automatically imply SHORT
ABSORPTION cannot automatically imply LONG
Decision engine enforces descriptive/predictive separation
mechanically

W. REAL-MONEY READINESS

Real-money parent remains unchecked until everything material above
passes
Real-money requires data truth
Real-money requires semantic truth
Real-money requires one computation
Real-money requires live completeness
Real-money requires temporal sufficiency
Real-money requires replay
Real-money requires predictive validity
Real-money requires calibration
Real-money requires decision engine
Real-money requires risk
Real-money requires execution realism
Real-money requires UI fidelity
Real-money requires failure handling
Real-money requires operations
Real-money requires security
Real-money requires observability
Real-money requires reproducibility
Real-money requires universal runtime proof
Real-money requires independent falsification
Real-money requires final RTH end-to-end proof
Real-money requires final operator approval
Until then REAL_MONEY_READINESS = NOT_APPROVED

X. CLOSURE / PROOF REQUIREMENTS

No checkbox may be checked based on narrative
Every checked item must have exact SHA
Every checked item must have exact file/function producer
Every checked item must have exact consumer graph
Every checked item must have exact test(s)
Every checked item must have mutation or negative control where
meaningful
Every checked item must have exact command
Every checked item must have exit code
Every checked item must have runtime proof where applicable
Every checked item must have RTH proof where applicable
Every checked item must have multi-ticker proof where applicable
Every checked item must have replay proof where applicable
Every checked item must have before/after evidence if a defect was
fixed
Every checked item must have no downstream regression
Every checked item must have no alternate authority
Every checked item must have truth matrix updated
Parent remains open if any material connected requirement is
unresolved
ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1 = PASS cannot be
checked until every material money-path item is PASS or legitimately
UNAVAILABLE and mechanically prevented from being represented as
available or decision-grade
A FAIL or material NOT_PROVEN anywhere keeps the parent open

Known confirmed defects that must not get lost

These sit at the top of the active remediation queue on the sole
P0.1→P4 spine. They are not a second queue.

Known L1 defect: same-TRADE_TIME_MILLIS observations are dropped
Explicitly classify reconstructed trade stream as incomplete
observation unless stronger evidence exists
Establish whether authenticated Schwab exposes native aggressor side
Executed-flow proxies all marked PROXY
Current volume÷range absorption formula renamed or retired
Current replenishment earliest-vs-latest total-depth heuristic
renamed or retired
Known duplicate authority FAIL:
order_flow_engine._compute_absorption
Determine whether persisted same-named absorption field has changed
meaning over time
Legacy Order Flow weighted composite: inventory exact current
formula
Known L2-history defect: live book state retains only a tiny
in-memory snapshot deque
Bookmap-style heatmap: historical displayed-liquidity time×price
data available
Current microstructure regime authority inventory complete
Automatic reconnect fully proven or implemented
Active-ticker-only L2 behavior explicitly documented
Gamma flip known limitation: narrow-chain live flip eliminated or
clearly withheld
Gamma flip wing-IV handling proven
Volume Profile known defect: typical-price volume dump eliminated
Overnight known defect: calendar-based assumptions eliminated
Stop-cluster semantics proven or label removed
At least one candidate beats trivial baselines
Until then REAL_MONEY_READINESS = NOT_APPROVED
Then and only then admitted into Decide
Overall card fidelity remains unchecked until every money-path card
satisfies this
Do not cite contaminated positive or negative results
Shared-root policy retired or corrected
Reproduce Schwab orphan process leak
Determine which server.py areas prevent money-path proof
Dead hidden legacy UI removed
Canonical TRADE / WAIT / AVOID authority exists
Contradiction list canonical

The parent closure rule

The final box is: ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1
= PASS
That box cannot be checked until every material money-path item
above is either PASS, or legitimately UNAVAILABLE and mechanically
prevented from being represented as available or decision-grade.
A FAIL or material NOT_PROVEN anywhere keeps the parent open.
