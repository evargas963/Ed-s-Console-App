ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1 —
MASTER CHECKLIST

Parent status: NOT_PROVEN

Allowed closure statuses: PASS / FAIL / NOT_PROVEN /
UNAVAILABLE

Separate classification: NATIVE / DERIVED / HEURISTIC
/ PROXY

A checked box means the item has complete current-repo
proof, required runtime/live proof, downstream consumer proof, and any required
predictive proof. A child PASS may never close a parent item by itself.

0. Mission identity / evidence baseline

Re-fetch      origin/main before each major execution phase.

Record      exact HEAD_SHA.

Record      exact origin/main SHA.

Prove      clean/dirty worktree state.

Prove      exact branch/worktree being audited.

Prove      exact production process SHA.

Prove      exact database identity.

Prove      exact model-artifact identities.

Prove      exact runtime configuration/environment.

Establish      that no prior PASS or institutional claim is grandfathered.

Establish      single machine-readable truth matrix as the authoritative mission board.

Ensure      newly discovered defects append to this same parent mission rather than      creating competing governance systems.

A. RAW MARKET DATA / SOURCE TRUTH

A1. Schwab equities L1

Entitlement      proven.

Subscription      path proven.

Live      RTH receipt proven.

Bid/ask/last      field presence proven.

Bid/ask      size semantics proven.

Volume      semantics proven.

Exchange/MIC/ID      semantics independently proven where used.

Quote      timestamp semantics proven.

Trade      timestamp semantics proven.

Bid/ask      timestamp semantics proven.

Event      cadence measured during RTH.

Duplicate      behavior measured.

Repeated-timestamp      behavior measured.

Out-of-order      behavior measured.

Missing-update      behavior measured.

Stale-feed      behavior proven.

Disconnect      behavior proven.

Reconnect      behavior proven.

Data      after reconnect proven complete enough for claimed uses.

Session      transition behavior proven.

Extended-hours      behavior proven.

Ticker-switch      behavior proven.

No      silent source fallback proven.

A2. Known L1 defect — reconstructed tape

FAIL      currently: same-TRADE_TIME_MILLIS observations are dropped.

Quantify      actual same-ms collision frequency during RTH.

Quantify      lost reported size due to collision handling.

Quantify      lost intra-ms price transitions.

Correct      misleading code comment claiming price/size refresh behavior.

Determine      whether retaining every L1 update improves observation fidelity.

Ensure      any fix does not falsely relabel L1 reconstruction as native      time-and-sales.

Preserve      raw incoming update order/receive sequence for future analysis.

Explicitly      classify reconstructed trade stream as incomplete observation unless      stronger evidence exists.

A3. Native aggressor / true tape

Establish      whether authenticated Schwab exposes native aggressor side.

Establish      whether authenticated Schwab exposes native true time-and-sales.

Establish      whether TIMESALE is genuinely unavailable versus      subscription/configuration failure.

If      unavailable, mark UNAVAILABLE mechanically and in UI contracts.

Prevent      quote/tick-rule direction from being labeled native aggressor.

Prevent      reconstructed tape from being labeled complete executed flow.

A4. NYSE Level 2

Entitlement      proven.

Live      RTH receipt proven.

Snapshot      versus incremental-update semantics proven.

Full      visible depth behavior measured.

Price-level      ordering proven.

TOTAL_VOLUME      semantics proven.

nested      attribution semantics proven or withheld.

NUM_*      semantics proven or neutralized.

nested      sequence semantics proven or neutralized.

BOOK_TIME      semantics proven.

cadence      measured.

duplicate/gap      behavior measured.

reconnect      behavior proven.

stale-book      behavior proven.

A5. NASDAQ Level 2

Same      complete proof battery as A4.

Venue-specific      differences documented.

Cross-venue      merging/non-merging policy proven.

A6. Options L1

Entitlement      proven.

Live      option subscription proven.

Contract      identity proven.

strike/expiry/DTE      semantics proven.

bid/ask/last/size      proven.

OI      semantics/freshness proven.

totalVolume      semantics/freshness proven.

IV      semantics proven.

Greeks      semantics proven.

stale/missing      field behavior proven.

A7. Options Book

Entitlement      proven.

Live      receipt proven.

Depth      shape proven.

Price      aggregation semantics proven.

Attribution      semantics proven or withheld.

cadence/gap/reconnect      behavior proven.

A8. Option chain

REST      acquisition proven.

exact      strike coverage proven.

exact      expiry coverage proven.

freshness      proven.

quote/greek/OI      consistency proven.

malformed/poisoned      contract handling proven.

pagination/range      limitations proven.

live      narrow-chain versus wide-chain distinction eliminated or explicitly      surfaced.

A9. Historical bars

completeness      proven.

gap      detection proven.

repair/backfill      semantics proven.

synthetic/repaired-row      classification proven.

timestamp      alignment proven.

corporate      actions proven.

extended-hours/RTH      semantics proven.

duplicates      proven absent or handled.

OHLCV      correctness proven.

A10. Fundamentals and any other source

Inventory      every REST/live external source influencing money paths.

Prove      source semantics and availability for each.

Prove      no undocumented fallback silently changes the semantic meaning.

B. TEMPORAL SUFFICIENCY / HISTORY

Inventory      every semantic concept requiring history.

Identify      exact temporal window each concept requires.

Prove      retained data spans that window.

Prove      resolution/cadence is sufficient.

Prove      history survives process restart where required.

Prove      replay can reproduce calculations.

B1. Known temporal concepts requiring proof

persistence.

migration.

replenishment.

absorption.

add/pull.

liquidity      depletion.

liquidity      acceleration.

rolling      pressure.

wall      persistence.

wall      migration.

gamma      migration.

OI      migration.

charm      drift.

vanna      drift.

regime      transitions.

volatility      transitions.

signal      transitions.

alert      transitions.

trend      persistence.

decay.

B2. Known L2-history defect

FAIL      currently: live book state retains only a tiny in-memory snapshot      deque.

Design      canonical displayed-L2 history representation.

Determine      snapshot vs delta representation from measured Schwab semantics.

Add      local monotonically increasing receive sequence.

Preserve      vendor timestamp.

Preserve      server receive timestamp.

Preserve      source/service.

Preserve      ticker.

Preserve      side/price/displayed volume.

Preserve      schema/provenance version.

Build      bounded live in-memory history for visualization.

Build      durable replay/research persistence.

Measure      expected event rate.

Measure      expected daily storage.

Choose      storage architecture based on measurement, not convenience.

Do      not blindly write high-frequency L2 history into existing oversized SQLite      DB.

Define      retention.

Define      compression.

Define      checkpoint/delta strategy.

Define      crash recovery.

Prove      deterministic reconstruction.

B3. Bookmap-style heatmap

Historical      displayed-liquidity time×price data available.

Heatmap      generated entirely from live canonical L2 history.

No      static/fake heatmap.

Time      axis live-scrolls.

Price      axis correctly normalized.

Liquidity      intensity accurately represents displayed size.

Data      gaps visually exposed.

Staleness      visually exposed.

Restart      behavior proven.

Historical      replay reproduces live heatmap.

UI      explicitly says displayed L2, not MBO.

No      Level-3/queue/individual-order implication.

C. SEMANTIC TRUTH / NAMING

For every operator-visible or model-facing concept:

exact      definition documented from code.

exact      formula/algorithm identified.

label      matches actual computation.

source      classification assigned.

limitations      explicitly stated.

missing-data      semantics proven.

downstream      meaning proven.

UI      label does not overstate evidence.

C1. High-risk labels to adjudicate

absorption.

replenishment.

institutional      flow.

smart      money.

CVD.

delta      / signed flow.

tape      pressure.

selling      pressure / buying pressure.

liquidity.

liquidity      wall.

gamma      wall.

gamma      flip.

gamma      pin.

dealer      regime.

microstructure      regime.

support.

resistance.

breakout.

breakdown.

continuation.

reversal.

confidence.

confluence.

tradeability.

directional      probability.

recommendation.

bias.

edge.

D. ONE FAUCET = ONE COMPUTATION

Complete      repo-wide producer inventory.

Backend      Python inspected.

frontend      JS inspected.

HTML      inline scripts inspected.

SQL      inspected.

training      inspected.

research      inspected.

replay      inspected.

caches      inspected.

compatibility      shims inspected.

helpers/wrappers/builders      inspected.

normalization      paths inspected.

persistence-derived      SQL expressions inspected.

tests      inspected for shadow/reference computations that escaped into production      logic.

every      material concept has one canonical computation authority.

downstream      consumers import/call authority rather than recompute.

absence/fallback      behavior does not create a second authority.

historical/replay      computation uses same authority.

training/serve      computation uses same authority.

UI      does not recompute semantic truth.

D1. Known duplicate authority — absorption

FAIL:      order_flow_engine._compute_absorption.

FAIL:      institutional_behavior.compute_liquidity_behavior_row::absorption_score.

Trace      all other absorption* producers.

Trace      all DB writers/readers.

Trace      feature contract.

Trace      live feature adapter.

Trace      model inputs.

Trace      research studies.

Trace      calibration.

Trace      replay.

Trace      reports.

Trace      UI.

Trace      decision engine.

Determine      historical semantic eras.

Determine      whether persisted same-named field has changed meaning over time.

Quarantine      contaminated artifacts/data where required.

Withhold      all existing absorption authorities from decision-grade use.

Either      replace with one semantically valid authority or retire concept.

E. ORDER FLOW / MICROSTRUCTURE

E1. Canonical point-in-time book microstructure

Re-prove rather than assume:

raw      book → canonical normalization.

bid      ordering.

ask      ordering.

invalid-size      rejection.

crossed-book      behavior.

locked-book      behavior.

top-of-book.

mid.

spread.

microprice.

Top-1      depth.

Top-3      depth.

Top-5      depth.

Top-1      imbalance.

Top-3      imbalance.

Top-5      imbalance.

depth-pressure      curve.

book      slope.

concentration.

wall-candidate      heuristic.

book      age.

quote      age.

provenance.

no      duplicate calculation authority.

live      engine and API serialize same semantic state.

fail-closed      on missing book.

stale-book      negative control.

ticker      switch.

reconnect.

RTH      live proof.

replay      proof.

E2. Legacy Order Flow weighted composite

Inventory      exact current formula.

Inventory      all weights.

Inventory      fixed thresholds.

Prove      whether each leg has equivalent semantic quality.

Trace      all consumers.

Trace      UI use.

Trace      model feature use.

Trace      decision influence.

Trace      research use.

Trace      calibration use.

Prove      independent justification for weighting.

Prove      predictive justification for combined composite.

If      not proven, classify NOT_ADMITTED.

Safely      migrate any consumers/artifacts that depend on it.

Remove      false precision from operator UI.

Preserve      separate legs where valid.

E3. Executed-flow proxies

tape_pressure_30s      exact semantics.

tape_pressure_2m      exact semantics.

tape_pressure_5m      exact semantics.

cum_delta_proxy      exact semantics.

cum_delta_slope      exact semantics.

institutional_flow_proxy_score      exact semantics.

all      marked PROXY.

no      native-aggressor claim.

no      true-CVD claim.

no      complete-volume claim.

field      names corrected where proxy nature is hidden.

source      → MarketState → API trace.

orphan      status source-proven, not inferred from null runtime values.

decision      influence removed unless separately admitted.

predictive      usefulness tested independently if retained.

E4. Absorption / replenishment

_compute_absorption      marked NOT_ADMITTED.

current      volume÷range formula renamed or retired.

current      “replenishment” earliest-vs-latest total-depth heuristic renamed or      retired.

misleading      docstrings corrected.

actual      level-specific absorption definition designed only from available      evidence.

actual      replenishment definition requires time/history.

temporal      windows defined.

fail-closed      behavior defined.

replay      reproducibility proven.

semantic      validity proven before predictive validity.

predictive      validity proven before decision admission.

E5. Microstructure regime

Current      regime authority inventory complete.

No      UI-only regime invention.

State      taxonomy derived from measurable primitives rather than invented first.

Balanced      auction definition.

buy-pressure      definition.

sell-pressure      definition.

liquidity-pull      definition.

replenishment      definition.

absorption      definition.

exhaustion      definition.

liquidity-vacuum      definition.

spread-expansion      definition.

exact      temporal requirements.

confidence/trust      definition.

transition      logic.

fail-closed      logic.

replay.

predictive/decision      validity separately tested.

F. LEVELS / LIQUIDITY / VALUE

F1. VWAP

source      bars/trades proven.

formula      proven.

session      boundary proven.

resets      proven.

extended-hours      policy proven.

one      faucet.

UI      fidelity.

replay.

predictive      status separately classified.

F2. VWAP sigma bands

variance/σ      formula proven.

weighting      semantics proven.

session      semantics proven.

one      faucet.

replay.

predictive      validity separately classified.

F3. Volume Profile

Known      defect: typical-price volume dump eliminated.

price-distributed/tick-based      methodology implemented.

POC      proven.

VAH      proven.

VAL      proven.

session/window      definition proven.

reproducibility      proven.

comparison      against institutional/reference calculation.

UI      uses corrected authority only.

F4. Overnight

Known      defect: calendar-based assumptions eliminated.

prior      trading session close → next open semantics.

Monday      includes Friday correctly.

holidays      handled.

half-days      handled.

extended-session      inclusion/exclusion defined.

ONH      proven.

ONL      proven.

F5. Prior day / ORB

PDH.

PDL.

PDC.

prior      trading day semantics.

ORB      high.

ORB      low.

ORB      mid.

exact      opening-range window.

holiday/half-day      behavior.

F6. Liquidity/support/resistance language

buy_side_liquidity      adjudicated.

sell_side_liquidity      adjudicated.

stop-cluster      semantics proven or label removed.

support      calculation proven.

resistance      calculation proven.

reaction-zone      ranking proven.

structure      verdict proven.

continuation/rejection/chop      classifications proven.

predictive      influence blocked until Find & Prove PASS.

G. OPTIONS / DEALER EXPOSURE

G1. Chain completeness

live      UI chain range.

wide-chain      range.

expiry      coverage.

strike      coverage sufficient for each metric.

missing      strikes.

stale      chain handling.

contract      filtering.

0DTE      handling.

cross-expiry      aggregation.

G2. Greeks

delta      validity.

gamma      validity.

vega      validity.

theta      validity.

IV      validity.

poisoned-greek      rejection.

fail-closed      behavior.

sanitization      consistent research/live.

exact      vendor-vs-derived provenance.

G3. OI

OI      freshness.

update      cadence.

same-day      limitations.

no      false intraday OI migration claim.

G4. GEX

exact      formula.

contract      multiplier.

sign      convention.

dealer-side      assumption.

expiration      weighting if any.

strike      coverage.

expiry      coverage.

live/research      parity.

replay.

predictive      validity separately proven.

G5. DEX

same      proof class as GEX.

G6. Vanna

exact      definition.

IV      surface dependence.

units.

strike/expiry      completeness.

assumptions.

predictive      admission.

G7. Charm

exact      definition.

time-to-expiry      semantics.

trading-day/year      fraction.

sign      convention.

strike      coverage.

expiry      coverage.

predictive      admission.

G8. Gamma flip

Known      limitation: narrow-chain live flip eliminated or clearly withheld.

full      relevant strike coverage.

cumulative      method proven.

wing-IV      handling proven.

wide-chain      live path wired.

freshness.

self-declared      trust status.

external      comparison where useful.

replay.

predictive      validity separately proven.

G9. Gamma pin / walls

definition.

full-chain      dependency.

difference      from size anomaly.

one      faucet.

trust      status.

predictive      validity.

G10. Dealer regime

long/short      gamma regime semantics.

dealer-position      assumption clearly exposed.

no      claim of actual dealer inventory.

confidence      gating.

stale/untrusted      gamma forces withheld regime.

predictive      significance separately proven.

H. MODEL / FIND & PROVE

H1. Scientific pipeline itself

labels      proven.

entry      timestamp proven.

exit/outcome      timestamp proven.

future      information excluded.

feature      availability as-of decision time proven.

lookahead      audit.

label-shuffle      test.

feature-shuffle      tests.

leakage      audit.

meta-learner      leakage audit.

purged      K-fold where applicable.

embargo      where applicable.

time-series/walk-forward      split.

no      random temporal contamination.

ticker      isolation where required.

cross-ticker      universality where claimed.

trivial      baselines.

persistence      baseline.

class-prior      baseline.

cost-aware      baseline.

multiple-hypothesis      correction.

Holm-Bonferroni      where appropriate.

sample      sufficiency.

confidence      intervals.

calibration.

calibration      per ticker/horizon where required.

regime-conditioned      performance.

cost/slippage      sensitivity.

reproducibility.

exact      feature version.

exact      model artifact version.

training/serve      parity.

replay      parity.

H2. Era contamination

Inventory      every study classified era-contaminated.

Determine      contamination boundary.

Determine      semantic-feature changes across eras.

Determine      outcome/timestamp changes across eras.

Quarantine      affected historical results.

Rerun      only after scientific pipeline PASS.

Do      not cite contaminated positive or negative results.

H3. Existing model stack

For every current/legacy model:

XGB      implementation correctness.

LSTM      implementation correctness.

Transformer      legacy/removal effects.

Monte      Carlo implementation correctness.

fusion      implementation correctness.

meta-model      implementation correctness.

Kalman      implementation correctness.

HMM      implementation correctness.

GARCH      implementation correctness.

model      input semantics.

model      output semantics.

artifact      compatibility.

stale      artifact detection.

semantic      feature drift detection.

safe      abstention.

retrain      requirement after feature changes.

no      model admitted without positive OOS evidence net of costs.

H4. Predictive validity

At      least one candidate beats trivial baselines.

OOS.

net      of costs.

sufficiently      sampled.

corrected      for multiple testing.

survives      regime/robustness checks.

calibration      acceptable.

replicated.

then      and only then admitted into Decide.

I. DECISION ENGINE

I1. Decision inputs

call_signal.

execution_mode.

final_tradeable.

is_no_trade.

terrain      posture.

veto      stack.

wait      reasons.

decision-gate      reasons.

recommendation      side.

bias.

confidence.

confluence.

entry.

stop.

target.

target2.

invalidation.

size.

trade      type.

I2. Unified decision

canonical      TRADE / WAIT / AVOID authority exists.

explicit      AVOID semantics.

WAIT      distinguished from hostile/avoid state.

no      arbitrary weighted averaging.

disagreement      remains visible.

deterministic      reason lineage.

contradiction      list canonical.

no      frontend synthesis.

fail-closed      when required evidence absent.

I3. Plan semantics

trigger      primitive if required.

entry      populated only when meaningful.

stop      semantics.

target      semantics.

R:R      semantics.

invalidation      semantics.

blank/WAIT      fields explained rather than misleading.

“what      changes my mind” canonical.

positive      tradeability requires admitted evidence.

J. RISK / EXECUTION

transaction-cost      model.

spread      model.

slippage      model.

market/limit      fill assumptions.

partial      fills.

order      latency.

signal      latency.

data      latency.

stop      execution.

gaps      through stop.

overnight      gap risk if relevant.

position      sizing.

max      position risk.

max      portfolio risk.

correlation      risk.

sector      concentration.

ticker      concentration.

daily      loss limit.

drawdown      limit.

stale-data      kill.

model-unavailable      kill.

broker      disconnect kill if applicable.

emergency      kill switch.

execution      reconciliation.

order-state      reconciliation.

no      real-money approval until all material items PASS.

K. UI / OPERATOR TRUTH

K1. Architecture

Dashboard      role proven.

Levels      role proven.

Order      Flow role proven.

Options      role proven.

Plan      role proven.

Chart      role proven.

Desk      role proven.

Terrain      consolidation decision proven.

Exposure      consolidation decision proven.

Console      content migration proven.

dead      hidden legacy UI removed.

duplicate      surfaces removed.

Ops/Governance/Diagnostics      separated from trading workflow.

K2. Every decision-facing visual

exact      backend source.

exact      canonical producer.

no      JS recomputation.

freshness      visible.

stale      state visible.

unavailable      state visible.

proxy      status visible.

heuristic      status visible.

low-confidence      status visible.

source      classification where materially useful.

no      misleading color.

no      misleading precision.

no      hidden fallback.

no      static market-state data masquerading as live.

K3. Storytelling

edge      shown only where evidence supports “edge”.

bias      has exact definition.

signal      has exact definition.

contradiction      visible.

uncertainty      visible.

no      opaque score hiding disagreement.

decision      reason visible.

invalidation      visible.

“what      changes the view” grounded in canonical states.

L. REPLAY / AUDITABILITY

raw      input retained where required.

canonical      normalized input retained.

code      SHA retained.

model-artifact      SHA retained.

policy      version retained.

feature      schema/version retained.

thresholds      retained.

calibration      retained.

source      timestamps retained.

receive      timestamps retained.

event      ordering retained.

decision      inputs retained.

decision      result retained.

explanation/lineage      retained.

historical      replay reproduces live computation.

replay      does not call alternate formulas.

replay      survives schema/version changes.

live/replay      mismatch mechanically fails.

M. OPERATIONS / PRODUCTION RELIABILITY

M1. Production isolation

primary      checkout production-only.

clean      origin/main.

agent      mutation of primary blocked.

Claude      isolated worktree.

Cursor      isolated workspace/branch.

proof      server isolated from production.

proof      port separate.

proof      DB cannot silently mutate canonical production DB.

production      port only serves clean approved SHA.

M2. Known worktree-policy conflict

shared-root      policy retired or corrected.

RC-129      assumptions reconciled with RC-350.

RC-125      live proof works against proof runtime.

negative      control: agent cannot mutate prod tree.

negative      control: dirty prod cannot launch.

positive      control: clean main launches.

proof      and production runtimes can coexist.

M3. Stream reliability

Known      issue: automatic reconnect fully proven or implemented.

disconnect      detection.

retry/backoff.

resubscribe.

state      invalidation during reconnect.

stale      UI state blocked.

recovery      proof.

no      silent REST semantic substitution.

M4. Single-ticker L2 scope

active-ticker-only      behavior explicitly documented.

Desk      does not imply multi-ticker L2 if unavailable.

ticker-switch      clearing/carry behavior proven.

history      store identity correct across ticker switches.

M5. Known Schwab worker leak

reproduce      orphan process leak.

root      cause proven.

explicit      client/process cleanup implemented.

scheduled-job      lifecycle fixed.

week-long/no-orphan      observation if required.

no      lingering worker CPU/memory leakage.

M6. Resource / performance

CPU      budget.

memory      budget.

DB      growth.

L2-history      storage growth.

UI      latency.

API      latency.

stream-to-state      latency.

state-to-UI      latency.

high-load      behavior.

backpressure.

resource      exhaustion behavior.

M7. Backup / restore / crash

canonical      DB backup.

restore      tested.

schema      migration rollback.

crash      recovery.

abrupt      stream loss.

abrupt      process termination.

corrupted      cache/history handling.

backup      identity/provenance.

M8. Scheduled jobs

inventory      complete.

schedule      correct.

commands      correct.

environment      correct.

logs.

exit      codes.

stale/failed      task visibility.

no      hidden host-only jobs outside repo inventory.

N. MAINTAINABILITY / ARCHITECTURAL PROOFABILITY

N1. Existing debt

function-complexity      findings classified.

function-length      findings classified.

file-length      findings classified.

Ruff-quality      findings classified.

fake-default      findings classified.

type-safety      gaps classified.

N2. Promote debt to correctness defect where it:

obscures      semantic authority.

prevents      exhaustive testing.

permits      hidden fallback.

permits      duplicate computation.

couples      unrelated money paths.

prevents      review.

prevents      replay.

prevents      runtime isolation.

prevents      deterministic behavior.

N3. server.py

determine      which size/complexity is merely maintainability debt.

determine      which areas prevent money-path proof.

refactor      only where required for correctness/provability.

no      functional semantic changes hidden inside cleanup.

O. SEMANTIC-ERA / HISTORICAL CONTAMINATION

This needs to be explicit because the absorption discovery
exposed it.

For every material persisted or trained feature:

identify      semantic definition by code era.

identify      first/last SHA using each definition.

identify      DB rows produced under each definition.

identify      normalized feature tables affected.

identify      training datasets affected.

identify      trained artifacts affected.

identify      calibration artifacts affected.

identify      research reports affected.

identify      replay results affected.

identify      decision records affected.

quarantine      mixed-era data when semantics changed materially.

retrain/revalidate      artifacts when input semantics changed.

no      same column name allowed to conceal materially different historical      meaning.

O1. Absorption era contamination

complete      producer-era graph.

exact      DB population query.

exact      NULL-rate calculation with date range/denominator.

identify      model-facing definition.

identify      order-flow-composite definition.

determine      overlap.

determine      mixed-era training.

invalidate/rebuild      affected artifacts.

P. DATA QUALITY / DATABASE TRUTH

schema      inventory.

writer      inventory.

reader      inventory.

duplicated      semantic columns.

stale      columns.

orphan      columns.

silent      default values.

sentinel      values.

NULL      semantics.

timestamps.

ticker      identity.

option      contract identity.

timeframe      identity.

duplicate      primary semantic keys.

missing      rows.

repair      provenance.

synthetic-row      provenance.

corporate      actions.

retention.

DB      bloat sources.

indexes.

integrity      checks.

reproducible      snapshot extraction.

write/read      parity.

no      SQL-side semantic recomputation violating ONE FAUCET.

Q. SOURCE → DISPLAY CARD FIDELITY

For every operator-facing field:

backend      value correct.

backend      unit correct.

backend      timestamp correct.

API      value identical.

frontend      receives identical value.

frontend      does not transform semantics.

frontend      label correct.

frontend      unit correct.

frontend      direction/color correct.

frontend      missing-state correct.

frontend      stale-state correct.

multi-ticker      proof.

multi-horizon      proof where applicable.

live      RTH proof where applicable.

Overall card fidelity remains unchecked until every
money-path card satisfies this.

R. UNIVERSE / TICKER / HORIZON UNIVERSALITY

SPY.

QQQ.

IWM.

representative      high-price equity.

representative      low-price equity.

representative      high-volatility equity.

symbol      with punctuation such as BRK.B where supported.

index      symbols where supported.

1m.

5m.

15m.

60m.

ticker-agnostic      semantics.

horizon-specific      semantics where intentional.

no      SPY-only proof closes universal parent claim.

S. FAILURE MODES / FAIL-CLOSED BEHAVIOR

missing      quote.

missing      book.

one-sided      book.

crossed      book.

stale      book.

stale      quote.

stream      disconnect.

REST      failure.

option      chain failure.

partial      option chain.

invalid      Greek.

zero/negative      price.

zero/negative      size.

NaN.

infinity.

missing      model artifact.

stale      model artifact.

semantic-version      mismatch.

missing      calibration.

DB      lock/failure.

API      exception.

frontend      fetch failure.

process      restart.

overnight→RTH      transition.

RTH→after-hours      transition.

ticker      change.

clock/daylight-saving      transition.

holiday/half-day.

every      failure defaults to truthful abstention rather than fabricated normality.

T. SECURITY / SECRETS / AUTHORIZATION

Schwab      credentials storage.

tokens.

refresh-token      handling.

log      redaction.

environment      secrets.

no      secrets in repo.

local      file permissions where relevant.

debug      endpoints.

destructive      DB operations.

authorization      for resets/cleanups.

production/proof      environment separation.

external-facing      endpoints reviewed.

U. OBSERVABILITY

feed      health.

source      authority.

freshness.

event      lag.

dropped      messages where detectable.

reconnect      count.

calculation      failures.

fail-closed      reasons.

decision      vetoes.

model      artifact identity.

DB      write failures.

scheduled-job      failures.

process      leaks.

memory/CPU/storage.

UI      fetch failures.

operator      sees data-quality state before trusting a value.

V. PREDICTIVE VS DESCRIPTIVE SEPARATION

This must be explicit across the whole product.

For every field/panel:

classify      as descriptive market state or predictive signal.

descriptive      state does not imply edge.

contextual      level does not imply predictive edge.

heuristic      does not imply predictive edge.

proxy      does not imply predictive edge.

predictive      language appears only after Find & Prove admission.

“EDGE”      UI label only appears when positive evidence exists.

“confidence”      cannot be a synonym for mathematical certainty unless calibrated.

“bias”      cannot be silently interpreted as a trade recommendation.

SELLING      PRESSURE cannot automatically imply SHORT.

ABSORPTION      cannot automatically imply LONG.

decision      engine enforces this separation mechanically.

W. REAL-MONEY READINESS

Parent remains unchecked until everything material above
passes.

data      truth.

semantic      truth.

one      computation.

live      completeness.

temporal      sufficiency.

replay.

predictive      validity.

calibration.

decision      engine.

risk.

execution      realism.

UI      fidelity.

failure      handling.

operations.

security.

observability.

reproducibility.

universal      runtime proof.

independent      falsification.

final      RTH end-to-end proof.

final      operator approval.

Until then:

REAL_MONEY_READINESS = NOT_APPROVED

X. CLOSURE / PROOF REQUIREMENTS

No checkbox above may be checked based on narrative.

Every checked item must have:

exact      SHA.

exact      file/function producer.

exact      consumer graph.

exact      test(s).

mutation      or negative control where meaningful.

exact      command.

exit      code.

runtime      proof where applicable.

RTH      proof where applicable.

multi-ticker      proof where applicable.

replay      proof where applicable.

before/after      evidence if a defect was fixed.

no      downstream regression.

no      alternate authority.

truth      matrix updated.

parent      remains open if any material connected requirement is unresolved.

Known confirmed defects that must not get lost

These should sit at the top of the active remediation queue:

Same-millisecond      L1 trade observations are dropped.

Current      reconstructed tape is not complete native time-and-sales.

No      native/quote-based aggressor side is currently proven.

CVD/tape      pressure are proxies and suffer from upstream observation loss.

Legacy      absorption math does not measure what its label claims.

Replenishment      heuristic does not constitute proven replenishment.

Absorption      has multiple computation authorities.

Absorption      may have semantic-era contamination in DB/training/model artifacts.

Legacy      Order Flow composite mixes unequal-quality legs with fixed arbitrary      weights.

No      durable historical L2 time×price store currently exists.

Bookmap-style      historical liquidity heatmap therefore is not ready.

Microstructure      regime authority is not yet proven/built.

Auto-reconnect      behavior remains unproven/defective.

L2      is currently active-ticker scoped, not universal multi-ticker live depth.

Live      gamma flip/walls have known strike-coverage trust limitations.

Wing-IV      treatment remains unresolved for trustworthy wide-chain flip.

Volume-profile      methodology has known defect.

Overnight      session semantics have known defect.

Liquidity      nomenclature overclaims unproven stop-cluster semantics.

Predictive      validity remains NOT_PROVEN.

Real-money      readiness remains NOT_APPROVED.

Decision-path      admissions remain empty/unproven.

Card      fidelity/universal runtime proof remains NOT_PROVEN.

Era-contaminated      research results cannot be cited until rerun.

Shared-root      development policy conflicted with clean-production isolation.

Schwab      worker/process leak remains a known operations defect.

Repository      complexity may hide correctness defects and must be adjudicated, not      merely counted.

UI      contains duplicate/dead/hidden legacy surfaces that require      migration/removal.

Unified      TRADE/WAIT/AVOID authority remains unproven/not complete.

Contradictions/veto      reasoning is not yet one canonical operator-facing object.

The parent closure rule

The final box is:

ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1      = PASS

That box cannot be checked until every material money-path
item above is either:

PASS, or legitimately UNAVAILABLE and
mechanically prevented from being represented as available or decision-grade.

A FAIL or material NOT_PROVEN anywhere keeps the parent
open.
