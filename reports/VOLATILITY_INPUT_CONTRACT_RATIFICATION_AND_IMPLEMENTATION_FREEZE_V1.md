# VOLATILITY_INPUT_CONTRACT_RATIFICATION_AND_IMPLEMENTATION_FREEZE_V1

**Mission:** VOLATILITY_INPUT_CONTRACT_RATIFICATION_AND_IMPLEMENTATION_FREEZE_V1
**Mode:** READ_ONLY
**HEAD at start and end:** `86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b`
**Machine-readable counterpart:** `reports/VOLATILITY_INPUT_CONTRACT_RATIFICATION_AND_IMPLEMENTATION_FREEZE_V1.json` (embeds full Phase 0 start/end baselines with SHA-256 hashes of every modified/untracked path, and the complete 12 matrices).

Proof-label for this packet: `REPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED`. All code citations were Read this mission at the HEAD SHA above.

---

## Phase 0 — Worktree baseline

Captured at start and repeated at completion (full outputs + hash tables in JSON `phase0_baseline_start` / `phase0_baseline_end`). HEAD unchanged; no pre-existing file hash changed; the only new paths are the two authorized report files. `SCOPE_VIOLATION = NOT_DETECTED`.

Note: at mission start the index contained staged pre-existing changes (same set as the prior two missions' baselines). This mission staged nothing and modified none of them — proven by hash equality.

---

## Matrix 1 — Source-report completeness (Phase 1)

Programmatic validation of both source artifacts (script output embedded in JSON):

| Check | Result |
|---|---|
| JSON parses | PASS |
| 11 concepts present, exact expected set, in order | PASS |
| All 11 concept names present in MD | PASS |
| Producer–consumer rows | 9 (all present in MD Matrix 2) |
| Four ticker classes consistent across formats | PASS |
| Every concept has units/timestamp/fallback/missing-rule/source/meaning | PASS (zero field gaps) |
| Fix-design lanes + dependency order present | PASS (`lane_V1_msd001`, `lane_V2_msd002`, `dependency_order`) |
| MD/JSON final determinations identical | PASS |
| No placeholder marked APPROVED | PASS (`IMPLEMENTATION_READY` and `REAL_MONEY_APPROVAL` both `NOT_APPROVED` in source) |

```
SOURCE_MARKDOWN_COMPLETE        = PROVEN
SOURCE_JSON_COMPLETE            = PROVEN
SOURCE_CROSS_FORMAT_CONSISTENCY = PROVEN
```

---

## Matrix 2 — Canonical unit matrix (Phase 2)

Full 9-row matrix in JSON (`2_canonical_unit_matrix`). The binding decisions:

| Field | Internal unit | Serialized unit | Conversion point |
|---|---|---|---|
| `market_iv_level` (vix_level) | vol points | vol points | none — one unit everywhere |
| `market_iv_change` (vix_vs_prev) | signed vol points | signed vol points | none |
| `native_iv_level` (VXN/RVX) | vol points | vol points | none |
| `ticker_atm_iv` (iv_level) | **decimal** (0.185) | **percent** in DB/API | `vol_percent_to_decimal` in the canonical builder ONLY |
| `realized_vol` | **decimal** | **percent** in DB | same single boundary |
| `forecast_vol_bars` | per-bar sigma decimal | not persisted | none |
| `atr` | price points | price points | none; `atr/spot` at consumer |
| ratios / iv_rank | dimensionless | dimensionless | operands must share unit before ratio |

Every field carries a mechanical unit assertion (valid range + impossible range) in the JSON matrix.

### REPLAY_IV_REALIZED_VOL_UNIT_PARITY = CONFIRMED_DEFECT (new register entry VOL-UNIT-001)

The risk flagged in the source report is now a proven defect by static evidence chain:

1. **DB stores percent.** `server.py:6843` stamps snapshot `iv_level` with in-code comment "percent for DB / iv_rank history"; `db.py:599` comments `realized_vol` as "annualized realized vol %".
2. **SignalInput contract is decimal.** `signal_types.py:86-88`; live builder converts at `market_state.py:1219-1224` via `vol_percent_to_decimal`.
3. **Replay copies verbatim.** `features/replay_signal_input_v1.py:40-46` copies every matching DB column into SignalInput with no conversion — `iv_level` and `realized_vol` both match by name.
4. **Consumers do not re-normalize.** `volatility_regime.py:189-194` ("no re-normalize"; `_f` at `volatility_regime.py:84-86` is plain finite-float). `signals.py:458` feeds `inp.iv_level` to the Monte Carlo path through `float_finite_or_none` with no scaling.
5. **The guard exists but is dead.** `normalize_vol_decimal` (`volatility_regime.py:89-105`, the >5.0 percent heuristic) has **zero production call sites** — only a test and governance inventories reference it.
6. **Replay routes execute the real money path.** `tools/replay_money_path_probe.py:251-252` (`compute_signals` full path), `arch_competition/stack_bundle_eval_v1.py:482`, `arch_competition/ablation_bundle_inference.py:591`, `tools/backfill_fusion_policy_*.py`.

Consequence: any replayed/evaluated row with percent-form `iv_level` (e.g. 18.5) enters MC sigma blending and vol-regime level checks two orders of magnitude off contract. The rv/iv **ratio** survives (same-unit operands) but level thresholds do not. Downstream numeric magnitudes were not executed (read-only mission) — the contract violation itself is proven statically at the field boundary. Designed read-only reproduction: select one `snapshots` row with `iv_level > 5`, call `signal_input_from_snapshot_row_dict`, assert `inp.iv_level > VOL_DECIMAL_PERCENT_HEURISTIC` — violates the frozen decimal contract.

**Contract consequence:** replay construction must route through the same conversion boundary as live. This is folded into V1 scope (below) rather than left as a separate lane, because V1's golden-parity acceptance is unprovable while the replay builder violates the unit contract.

---

## Matrix 3 — Volatility concept registry ratification (Phase 3)

**Verdict: APPROVED with four amendments** (full registry with math meaning / source / unit / availability / consumers / prohibited consumers / observational-vs-derived / training-live permissions / absence semantics in JSON):

- **A1** — every concept gains explicit `canonical_internal_unit`, `serialization_unit`, and a mechanical unit assertion (Matrix 2 is now part of the contract).
- **A2** — the dual-unit boundary for `ticker_atm_iv` / `realized_vol` is frozen: decimal at SignalInput, percent at DB/API, conversion in exactly one place (the canonical builder), replay included.
- **A3** — `vol_input_quality` expands to the Phase 7 enumerated envelope; free-text statuses prohibited.
- **A4** — `forecast_vol_bars` keeps its documented fail-open to MC flat blend, but must stamp `fallback_used=true`, `fallback_reason=GARCH_UNAVAILABLE`.

Name-overload check: PASS — no ratified name carries two meanings; the legacy `vix_*` / `iv_level` overloads are resolved by the alias table (Matrix 6).

---

## Matrix 4 — Ticker-class mapping ratification (Phase 4)

**Verdict: APPROVED with three amendments.** Registry owner: versioned instrument-class registry in `instrument_identity.py` (already owns the `VIX/VXN/RVX` broker-root normalization at `instrument_identity.py:22`).

| Class | Rule | Market IV | Native IV | Fallback |
|---|---|---|---|---|
| `spx_cone` | SPX-tracking index products / broad S&P ETFs (SPY, $SPX + aliases) | VIX | VIX (`NATIVE_EQUALS_MARKET`) | market always present or fail-closed |
| `ndx_cone` | NDX-tracking (QQQ) | VIX (macro) | VXN | native `UNAVAILABLE` → macro overlay remains; never substituted into native field |
| `rut_cone` | RUT-tracking (IWM) | VIX (macro) | RVX | as ndx_cone |
| `single_equity_guest` | **DEFAULT class** — any symbol not matching an index-cone rule | VIX (macro overlay only) | `ticker_atm_iv` with status `CHAIN_DERIVED` | no chain → `UNAVAILABLE`; RV never copied into native field |

- **A5** — `single_equity_guest` is the governed default: classification is **total by construction**. Sector/thematic/leveraged/inverse ETFs and no-chain symbols fall here (no-chain → `chain_required` handling emits `UNAVAILABLE`); no ad hoc symbol exceptions exist anywhere.
- **A6** — SPX aliases and bare roots resolve through `instrument_identity` normalization **before** classification; the registry keys on normalized roots.
- **A7** — insufficient-liquidity chains classify normally but emit `native_iv_status=INSUFFICIENT_LIQUIDITY` (a quality gate, not a class change).

```
TICKER_CLASSIFICATION = APPROVED
BASE_TICKER_MAPPING   = APPROVED
GUEST_TICKER_MAPPING  = APPROVED
```

---

## Matrix 5 — CHAIN_DERIVED policy (Phase 5)

**Verdict: APPROVED.** Frozen parameters (complete table in JSON):

- Target maturity: nearest listed expiry with DTE in **[7, 45]**, prefer closest to 30 DTE; **no interpolation in v1** (single-expiry ATM read, matching existing `atm_iv` usage); variance-interpolated 30d is a versioned future upgrade.
- ATM = strike nearest spot (tie → lower strike); ATM call+put pair; IV basis = **bid/ask midpoint** (theoretical/last prohibited).
- Quality gates: both legs present with positive bid; crossed/locked quotes discard the pair (`PARTIAL`/`UNAVAILABLE`); relative spread `(ask−bid)/mid ≤ 0.25` else `INSUFFICIENT_LIQUIDITY`; no OI/volume floor in v1 (spread gate is the liquidity gate — revisit with data).
- Timestamps: chain snapshot within one refresh cycle of spot else `STALE`. Premarket/after-hours: previous RTH chain marked `STALE`, display-only. Corporate events: adjusted chain post-event, no smoothing across the boundary.
- Replay: reconstruct from the persisted percent `iv_level` column **through the builder conversion**, provenance `route=replay`.
- **Macro substitution: PROHIBITED. RV substitution into the native field: PROHIBITED.** Any permitted fallback changes provenance status — never silently.

```
CHAIN_DERIVED_POLICY = APPROVED
```

---

## Matrix 6 — Legacy alias migration (Phase 6)

**Verdict: APPROVED.** Disposition for every legacy field: **retained temporarily as a read-only compatibility alias, prohibited in new money-path code, translated only at the canonical-builder boundary, mechanically blocked for new consumers, sunset at contract 1.1.0.**

| Legacy | Canonical | Producers | New consumers | Removal condition |
|---|---|---|---|---|
| `vix_level` | `market_iv_level` | canonical builder only | blocked (allowlist frozen at ratification) | all consumers migrated + one full retrain on canonical columns |
| `vix_direction` | `market_iv_direction` | canonical builder only | blocked | same |
| `vix_vs_prev` | `market_iv_change` | canonical builder only | blocked | same |
| `iv_level` (SignalInput) | `ticker_atm_iv` | canonical builder only | blocked; dual-unit boundary frozen | schema migration + retrain |
| `vix_bucket` | `market_iv_bucket` (rename-only) | `math_volatility.vix_bucket` | blocked | categorical retrain |

Binding rules: no alias written outside the canonical builder; aliases are one boundary adapter, never an alternate input path; DB/API column names unchanged during the alias window; model artifacts trained during the window record consumed names in artifact metadata.

```
LEGACY_ALIAS_MIGRATION = APPROVED
```

---

## Matrix 7 — Quality and provenance envelope (Phase 7)

**Verdict: APPROVED.** Envelope carries all 20 required fields (JSON `7_quality_provenance_state_matrix.envelope_fields`), enumerated states only:

| State | Model inference | Monte Carlo | Vol regime | Card | Fail-closed | Operator warning |
|---|---|---|---|---|---|---|
| `VALID` | yes | yes | yes | yes | no | no |
| `STALE` | no | no | degraded (unknown-with-reason) | badge | for trading decisions | yes |
| `UNAVAILABLE` | no | only documented GARCH/blend fallback with stamp | unknown-with-reason | explicit state | yes | yes |
| `INSUFFICIENT_LIQUIDITY` | no | no | unknown-with-reason | badge | yes | yes |
| `PARTIAL` | no | no | VALID sub-fields only | badge | per-field | yes |
| `FALLBACK` | only if same fallback active in training rows | yes | yes | badge | no | yes |
| `UNIT_INVALID` | no | no | no | no | yes | yes |
| `TIMESTAMP_INVALID` | no | no | no | no | yes | yes |
| `SEMANTIC_VERSION_MISMATCH` | no | no | no | no | yes | yes |

```
QUALITY_PROVENANCE_ENVELOPE = APPROVED
```

---

## Matrix 8 — Route-parity contract (Phase 8)

**Verdict: APPROVED.** For one immutable as-of input, across training / validation / backtest / replay / live / API / DB / card:

- **Byte-identical:** enums (quality, direction), `contract_version`, class-map resolution.
- **Numerically identical:** all vol levels/changes/spreads in canonical internal units.
- **Semantically equivalent:** serialized percent forms (deterministic ×100/÷100, tolerance 0), card text rendered from the same enum.

Rules: conversion exclusively in the canonical builder and **replay uses the same builder**; `as_of_ts` from source cycle, never read-time wall clock; a route may never invent presence; identical `UNAVAILABLE`/`STALE` classification for the same as-of input; alias translation at one adapter; consumer views are projections, never re-derivations; semantic-version equality asserted train-vs-live at scheduler preflight.

Golden-record assertions **GR-1 … GR-6** (JSON `8_route_parity_matrix.golden_record_assertions`), including GR-2 which kills VOL-UNIT-001 (percent row 18.5 → 0.185 from both builders) and GR-6 (version-mismatch fixture fails preflight).

```
TRAIN_BACKTEST_REPLAY_LIVE_CONTRACT = APPROVED
```

---

## Matrix 9 — Final ratified field-level contract (Phase 9)

**`VOL_INPUT_CONTRACT` semver `1.0.0` — RATIFIED.** Eleven fields, each frozen with type / internal unit / valid range / nullability / required-status / producer / consumer allowlist / class applicability / fallback / timestamp policy / quality requirements / parity class / legacy alias / semver — complete table in JSON `9_final_field_level_contract`. `vol_input_quality` is the only never-null field.

## Matrix 10 — Implementation dependency order (frozen, not implemented)

1. canonical types + contract module → 2. canonical builder (single conversion boundary) → 3. source adapters (VIX tracker, VXN/RVX, chain ATM) → 4. route migration (live + replay through same builder) → 5. legacy boundary adapters → 6. DB/API compatibility (additive, percent frozen) → 7. unit guards → 8. golden replay parity (GR-1…GR-6) → 9. consumer migration → 10. mechanical governance enforcement.

---

## Matrix 11 — V1 implementation authorization (Phase 10)

**V1 (MSD-001 SignalInput parity): APPROVED.** All preconditions frozen (fields, units, missing-state, aliases, allowlists, builder contract, golden parity); no unresolved contract decision affects V1.

**V1_IMPLEMENTATION_SCOPE:**

- **Authorized files:** `server.py` (per-cycle vol context computed once — tracker direction + pre-publish change, around `server.py:6739-6878` and `7245-7252`); `market_state.py` (`build_market_state` accepts the vol context, stamps `vix_direction`/`vix_vs_prev` at the `market_state.py:1290-1312` block); `features/replay_signal_input_v1.py` (route `iv_level`/`realized_vol` through `vol_percent_to_decimal`, stamp `route_identity=replay` — closes VOL-UNIT-001); test extensions in `tests/test_volatility_regime_fail_closed.py`, `tests/test_replay_signal_input_v1.py`, plus the existing market_state stamp-parity test owner.
- **Forbidden files:** `ml_predict.py`, `ml_train.py`, `models/**`, `calibration/**`, `bayesian_fusion.py`, `static/**`, `templates/**`, `db.py` schema, `.github/**`.
- **Intended changes:** compute `market_iv_change`/`direction` once per cycle; stamp identical values on SignalInput, snapshot row, and `ms_dict`; replay builder unit conversion. No new fields, no DB schema change, no ML feature change.
- **Tests:** route-parity unit (three surfaces equal per fake cycle); vol-regime rapid-branch reachability with stamped `vix_vs_prev`; replay golden percent→decimal (GR-2); live-vs-replay field identity (GR-1); missing-prev → `None` never 0 (GR-3).
- **Golden records:** checked-in fixture dicts (no DB dependency) for GR-1/GR-2/GR-3.
- **Coverage:** ticker-universal by construction (zero ticker literals in changed paths); routes live/replay/DB/API.
- **Acceptance:** all listed tests green; Tier A `--objective-audit` exit 0; empty training-schema diff; rapid branch reachable (test-proven); VOL-UNIT-001 closed with regression test.
- **Rollback:** vol-context parameter defaults `None` (current behavior); single-commit revert.

**V2 (MSD-002 native semantics): NOT_APPROVED (sequencing, not substance).** V1 must land and prove golden parity first; the native-IV DB migration must not land while the replay route still violates the unit contract; live VXN/RVX RTH wire proof is part of V2 acceptance and unavailable to a read-only mission. Unblock: V1 merged + golden parity green + operator confirms chain-policy defaults (spread gate 0.25, DTE [7,45]).

---

## Matrix 12 — Final binary determinations

```
SOURCE_MARKDOWN_COMPLETE            = PROVEN
SOURCE_JSON_COMPLETE                = PROVEN
SOURCE_CROSS_FORMAT_CONSISTENCY     = PROVEN
REPLAY_IV_REALIZED_VOL_UNIT_PARITY  = CONFIRMED_DEFECT
VOLATILITY_CONCEPT_REGISTRY         = APPROVED
TICKER_CLASSIFICATION               = APPROVED
BASE_TICKER_MAPPING                 = APPROVED
GUEST_TICKER_MAPPING                = APPROVED
CHAIN_DERIVED_POLICY                = APPROVED
LEGACY_ALIAS_MIGRATION              = APPROVED
QUALITY_PROVENANCE_ENVELOPE         = APPROVED
TRAIN_BACKTEST_REPLAY_LIVE_CONTRACT = APPROVED
CANONICAL_VOLATILITY_INPUT_CONTRACT = APPROVED
V1_IMPLEMENTATION_READY             = APPROVED
V2_IMPLEMENTATION_READY             = NOT_APPROVED
MODEL_STACK_REAL_MONEY_APPROVAL     = NOT_APPROVED
MISSION_CLOSURE                     = NOT_CLOSED
```

`MISSION_CLOSURE` is reported `NOT_CLOSED` at the proof-label-ladder level only: the `CLOSED_WITH_EVIDENCE` label is retroactive-only under FULL_FIXES_ONLY_V2 (it requires a concrete commit SHA plus CI run ids, which an uncommitted read-only mission cannot possess). All mission deliverables are complete; the packet label is `REPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED`.

---

## End-of-mission proof

JSON `phase0_baseline_end`: HEAD unchanged at `86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b`; every pre-existing modified/untracked file hash identical to the start baseline; the only new paths:

```
reports/VOLATILITY_INPUT_CONTRACT_RATIFICATION_AND_IMPLEMENTATION_FREEZE_V1.md
reports/VOLATILITY_INPUT_CONTRACT_RATIFICATION_AND_IMPLEMENTATION_FREEZE_V1.json
```

Nothing was committed, pushed, merged, retrained, recalibrated, or altered at runtime.
