> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/UNIVERSAL_TICKER_READINESS_ENFORCEMENT_V1.md`.

## 1. Universal ticker contract

Canonical statuses are emitted per ticker in `data/ticker_readiness_matrix_v1.json` under `tickers[*]`:
- `data_status`: `DATA_READY` | `INSUFFICIENT_DATA` | `DATA_INVALID`
- `training_status`: `TRAIN_READY` | `TRAINED_NATIVE` | `TRAINED_PARTIAL` | `TRAIN_BLOCKED`
- `artifact_status`: `FULL_NATIVE_COVERAGE` | `PARTIAL_COVERAGE` | `CLONED_COVERAGE_PRESENT` | `NO_COVERAGE`
- `inference_status`: `INFERENCE_READY` | `INFERENCE_PARTIAL` | `INFERENCE_BLOCKED`
- `evaluation_status`: `EVAL_READY` | `EVAL_PARTIAL` | `EVAL_BLOCKED`
- `calibration_status`: `CALIBRATION_ELIGIBLE` | `CALIBRATION_BLOCKED`
- `policy_status`: `POLICY_ELIGIBLE` | `POLICY_BLOCKED`
- `final_readiness_verdict`: `READY_GLOBAL_STANDARD` | `READY_WITH_LIMITATIONS` | `NOT_READY`

Each status has explicit reasons under `reasons` and metrics under `metrics`.

## 2. Required model inventory matrix summary

Source of truth: `data/required_model_inventory_v1.json` (ticker × horizon × head rows).

- App ticker universe audited: **30** tickers (from `logging_universe` categories `core/pinned/user_persisted`)
- Required rows: **420** (`30 * 7 horizons * 2 heads`)
- `native_model_present_y`: **305**
- `cloned_model_present_y`: **3**
- `loadable_y`: **308**
- Missing native heads: **115**
- Missing-native concentration:
  - 8 tickers have no coverage (`14/14` missing each): `$`, `$SP`, `CWV`, `IW`, `NV`, `RTY`, `SP`, `SPX`
  - clone-contaminated remaining misses: `TSL` (2), `PCG` (1)

## 3. Current app ticker readiness summary

Source: `data/ticker_readiness_matrix_v1.json`.

- Final verdict counts:
  - `READY_GLOBAL_STANDARD`: **20**
  - `READY_WITH_LIMITATIONS`: **2** (`PCG`, `TSL`)
  - `NOT_READY`: **8** (`$`, `$SP`, `CWV`, `IW`, `NV`, `RTY`, `SP`, `SPX`)
- Policy eligibility:
  - `POLICY_ELIGIBLE`: **20**
  - `POLICY_BLOCKED`: **10**
- Coverage/inference for governed-ready tickers:
  - governed population remains fully covered for ready tickers (`coverage_by_horizon` 1.0 move/dir)
  - `PCG` and `TSL` are explicitly blocked for policy due cloned dir coverage at specific horizons
- Evaluation/calibration/policy representation is explicit per ticker under `evaluation_representation`.

## 4. New ticker onboarding rules

Canonical rules file: `data/new_ticker_onboarding_rules_v1.json`.

Deterministic contract:
- Canonical timeframe: `1m`
- Trainability thresholds:
  - `train_min_rows_per_head = 80`
  - binary class diversity required (`nunique >= 2`)
- Decision flow:
  - no snapshots/governed rows -> `INSUFFICIENT_DATA`
  - train only missing native heads when trainable
  - no default cloning for onboarding
  - require full native + inference readiness before calibration/policy eligibility
- Universal future verdict: `UNIVERSAL_ONBOARDING_READY`.

## 5. Silent shortcut audit and removals/classifications

Silent shortcuts were converted into explicit statuses and reasons:
- Clone shortcut is no longer silent:
  - `artifact_status=CLONED_COVERAGE_PRESENT`
  - `policy_status=POLICY_BLOCKED`
  - explicit `reasons.policy` includes `cloned_coverage_present`
- Missing/empty coverage is no longer silent:
  - `artifact_status=NO_COVERAGE` with per-head missing inventory
- Partial behavior is no longer silent:
  - inferred from per-horizon coverage + smoke inference metrics
- App lookup normalization added:
  - `data/ticker_readiness_lookup_v1.json` for deterministic runtime lookup
  - `ticker_readiness_lookup.py` helper exposes `get_ticker_readiness(ticker)`.

## 6. Native coverage remediation performed

Remediation executed by `tools/enforce_universal_ticker_readiness_v1.py`:
- Attempted native remediation actions: **115**
- Result:
  - `TRAINED`: **0**
  - `BLOCKED`: **115**
- Block reason class:
  - overwhelmingly `insufficient_rows:<n><80`
- No feasible native retrain opportunities existed under locked threshold (`80` rows + 2 classes) for currently missing native heads.
- Cloned heads remain explicitly classified coverage-only (not policy-ready): `PCG:60c:dir`, `TSL:15c:dir`, `TSL:60c:dir`.

## 7. Inference/persistence/readiness enforcement

Enforcement outputs:
- `data/ticker_readiness_matrix_v1.json` includes per ticker:
  - inference smoke (`inference_smoke_ok`, `inference_smoke_total`)
  - persistence coverage by horizon (`coverage_by_horizon`)
  - blocked reasons when inference unavailable
- `INFERENCE_READY` is granted only when smoke checks and persisted coverage are complete for ticker horizons.
- No ticker is silently inferred as ready; non-ready tickers carry explicit blocker reasons.

## 8. App behavior contract

Deterministic app behavior (use `ticker_readiness_lookup_v1.json` / `get_ticker_readiness()`):
- Case A (`READY_GLOBAL_STANDARD`):
  - predictions/recommendations allowed
- Case B (`DATA_READY` + `TRAIN_READY` or `TRAINED_PARTIAL`):
  - surface `TRAINING_REQUIRED` / `NOT_READY_YET`
  - do not emit policy recommendations
- Case C (`INSUFFICIENT_DATA`):
  - surface `INSUFFICIENT_DATA`
  - no recommendation output
- Case D (`CLONED_COVERAGE_PRESENT`):
  - surface `COVERAGE_ONLY_NOT_POLICY`
  - block policy eligibility
- Case E (`PARTIAL_COVERAGE` / `INFERENCE_PARTIAL`):
  - surface exact horizon/head availability from `metrics.missing_native_heads` and `coverage_by_horizon`.

## 9. Final readiness verdict

- Current app ticker verdict:
  - **20** `READY_GLOBAL_STANDARD`
  - **2** `READY_WITH_LIMITATIONS`
  - **8** `NOT_READY`
- Future ticker onboarding verdict:
  - **`UNIVERSAL_ONBOARDING_READY`** (deterministic rule set and explicit blocker taxonomy implemented)
- Canonical artifacts written:
  - `data/ticker_readiness_matrix_v1.json`
  - `data/required_model_inventory_v1.json`
  - `data/new_ticker_onboarding_rules_v1.json`
  - `data/ticker_readiness_lookup_v1.json`
