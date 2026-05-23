> **Classification:** Policy Specification | **Scope:** Governance documentation `G2_PLAN.md`.

# G2 Plan - Cascade Alignment

> **G2 PAUSED:** Per `OPEN_ITEMS.md` § Workstream 1 / G2 pause state, this plan is **paused pending the `Framework-ED-Decision-Engine-v2.0` decision**. All file deliverables named below — including **`governance/artifact_contract.py`**, **`governance/G2_RESULT.md`**, **`tests/test_artifact_contract.py`**, and **`tests/test_cascade_meta_assembly.py`** — are **planned — pending G2 unpause** and **do not exist** in the current working tree. Do not implement them while the pause is active. Treat every internal reference below as a planned deliverable, not a present-tense file.

## Purpose

Phase G2 closes two structural gaps recorded in G1: **(a)** there is no canonical Python module that owns lifecycle artifact contracts (today the trained-candidate basename list lives in `training_cache.py` and is duplicated conceptually elsewhere), and **(b)** cascade training never writes `meta_<ticker>_<hz>.pkl` even though the trained-candidate contract and `artifacts_present` expect it for both architectures (`training_cache.py:918-919` aliases cascade basenames to the parallel list, which includes `meta_*`; `ml_scheduler.py:816-1201` has no meta writer  - see `governance/G1_DIAGNOSIS.md`).

G2 makes parallel and cascade **peer competitors** at the **TRAINED_CANDIDATE** tier: both produce the same eight on-disk artifacts under their respective candidate directories, and the contract module becomes the single authority for what those artifacts are.

## Scope (in)

- **Create** `governance/artifact_contract.py` defining **TRAINED_CANDIDATE** contracts for architectures `parallel` and `cascade` (basename templates + manifest name), with public helpers to resolve canonical paths and validate a candidate directory.
- **Modify** `ml_scheduler.py` only inside `train_cascade_candidate` to add a **cascade meta-learner** write path that mirrors the parallel path in `train_parallel_candidate` (`ml_scheduler.py:718-775`), writing `meta_<T>_<hz>.pkl` under `out_dir` (the cascade candidate directory).
- **Add tests**: new `tests/test_artifact_contract.py` and `tests/test_cascade_meta_assembly.py` as specified under [Test Plan](#test-plan); existing `tests/test_centralization.py` must still report **224 passed, 0 failed** (current baseline as of G2 planning).
- **Update** `OPEN_ITEMS.md` to mark G2 complete and G3 next (documentation only; phase banner in `OPEN_ITEMS.md:8` area).
- **After implementation**, create `governance/G2_RESULT.md` (G2.8)  - not part of this plan file's creation, listed in [Implementation Order](#implementation-order).

## Scope (out)

- **No** `EVALUATABLE_CANDIDATE`, `PROMOTABLE_CANDIDATE`, or `ACTIVE_SERVING_CANDIDATE` contract logic beyond explicit `NotImplementedError` placeholders in `artifact_contract.py`  - **G3**.
- **No** fix for governed evaluation **lineage / horizon mismatch** errors seen in benchmark logs  - **G3** (`arch_competition/lineage.py:29-87`, `arch_competition/eval_runner.py:229-236`).
- **No** Option **(b)** strict-mode refactor (`OPEN_ITEMS.md:63`)  - deferred post G2-G4; Option **(d)** wrapper remains as today (`ml_scheduler.py:92-104`, `ml_scheduler.py:725`, `ml_scheduler.py:422`).
- **No** changes to direct-active writers, server active sync, scheduler fail-open, or dormant auto-copy  - **G4** items (`OPEN_ITEMS.md:36-57`, `governance/REBUILD_CONTEXT.md:53-58`).
- **No** change to the **semantic** list of basenames in `parallel_artifact_basenames` / `cascade_artifact_basenames` at `training_cache.py:904-919` beyond **re-sourcing** that list from `governance/artifact_contract.py` (G2.3) so the module is the authority; do not add/remove artifact types in G2.

## Architectural Reference

**G1 decision:** Parallel and cascade are **PEER COMPETITORS**; both must expose a full stack for governance comparison. Full evidence table: `governance/G1_DIAGNOSIS.md:9-97`.

**Four supporting code paths (re-verified):**

1. Side-by-side evaluation entry: `arch_competition/eval_runner.py:208-266`  - `run_architecture_pair_evaluation` loads both dirs and calls `_evaluate_parallel_on_full_rth` and `_evaluate_cascade_on_full_rth` (`arch_competition/eval_runner.py:249-266`).
2. Promotion constants / decision entry: `arch_competition/promotion_engine.py:17-18` (`INCUMBENT_ARCHITECTURE`, `CHALLENGER_ARCHITECTURE`); `decide_promotion` starts at `arch_competition/promotion_engine.py:60`.
3. Manual promotion accepts architecture: `arch_competition/manual_control.py:136-144`  - `manual_promote_to_active_explicit(..., target_architecture: Literal["cascade", "parallel"], ...)`.
4. Scheduler trains both per ticker/horizon slice: parallel train+eval `ml_scheduler.py:1586-1608`; cascade train+eval `ml_scheduler.py:1631-1654` (within `run_once` loop; `cascade_out = CASCADE_DIR / ticker` at `ml_scheduler.py:1385-1386`).

**Deferred G4 alignment:** `OPEN_ITEMS.md:36-51` lists G4-1-G4-4; **not in G2 scope** per `governance/REBUILD_CONTEXT.md:51-58`.

## Canonical Artifact Contract Module Design

### Module location

`governance/artifact_contract.py` (new file; **not** created during this planning-only task).

### Module contents

Below is the **proposed complete initial module** for G2.1. Higher tiers raise `NotImplementedError` until G3.

```python
"""
Canonical artifact contract for EdWebConsole ML lifecycle tiers.

This module is the canonical artifact contract. All producers (ml_scheduler.py
training functions), validators (training_cache.py, future arch_competition
validators), and tests must import contract definitions from this module.
Do not duplicate contract definitions elsewhere.

Authority: established in G1; see governance/REBUILD_CONTEXT.md (contract
authority section) and governance/G1_DIAGNOSIS.md (TRAINED_CANDIDATE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

# --- Constants ----------------------------------------------------------------

class ModelTier(str, Enum):
    TRAINED = "trained_candidate"
    EVALUATABLE = "evaluatable_candidate"
    PROMOTABLE_CANDIDATE = "promotable_candidate"
    ACTIVE_SERVING = "active_serving_candidate"


class Architecture(str, Enum):
    PARALLEL = "parallel"
    CASCADE = "cascade"


MANIFEST_BASENAME = "scheduler_run_manifest.json"


# --- Data structures ------------------------------------------------------------

@dataclass(frozen=True)
class ArtifactSpec:
    """One required on-disk artifact under a candidate or active bundle root."""

    basename_template: str  # e.g. "xgb_{ticker}_{horizon}.pkl"
    required: bool = True
    conditional: bool = False
    conditional_predicate: Callable[..., bool] | None = None


@dataclass(frozen=True)
class TierContract:
    """Per-(architecture, tier) contract; G2 fills TRAINED only."""

    architecture: Architecture
    tier: ModelTier
    artifacts: tuple[ArtifactSpec, ...]
    path_resolver: Callable[[str, str], Path]  # (ticker, horizon) -> root dir for checks


@dataclass
class ValidationResult:
    ok: bool
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)  # optional policy; default ignore
    reason: str = ""


# --- Root helpers ---------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _models_dir() -> Path:
    return _repo_root() / "models"


def canonical_candidate_dir(architecture: str, ticker: str) -> Path:
    """Candidate leaf dir; ticker segment casing matches scheduler (ml_scheduler.py:1385-1386)."""
    arch = architecture if isinstance(architecture, Architecture) else str(architecture)
    t = ticker.strip()
    if arch == Architecture.PARALLEL.value:
        return _models_dir() / "parallel" / t
    if arch == Architecture.CASCADE.value:
        return _models_dir() / "cascade" / t
    raise ValueError(f"unknown architecture: {architecture!r}")


def canonical_active_dir(horizon: str, ticker: str) -> Path:
    """Mirror verify_active_models._active_bundle_dir (hz-specific active roots)."""
    from ml_horizon import normalize_ml_horizon_slug

    su = normalize_ml_horizon_slug(horizon)
    t = ticker.strip()
    if su == "1c":
        return _models_dir() / "active" / t
    return _models_dir() / f"active_{su}" / t


def _trained_basename_templates() -> tuple[str, ...]:
    """Basenames only; manifest separate. Order matches training_cache historical list."""
    return (
        "xgb_{ticker}_{horizon}.pkl",
        "xgb_{ticker}_{horizon}_meta.json",
        "lstm_{ticker}_{horizon}.pt",
        "lstm_{ticker}_{horizon}_meta.json",
        "transformer_{ticker}_{horizon}.pt",
        "transformer_{ticker}_{horizon}_meta.json",
        "meta_{ticker}_{horizon}.pkl",
    )


def trained_candidate_basenames(ticker: str, horizon: str) -> list[str]:
    """Return concrete basenames for TRAINED_CANDIDATE (parallel == cascade set)."""
    t = ticker.strip().upper()
    hz = horizon.strip().lower()
    return [pat.format(ticker=t, horizon=hz) for pat in _trained_basename_templates()]


def get_required_artifacts(architecture: str, horizon: str, ticker: str) -> list[Path]:
    """
    Absolute paths for required TRAINED artifacts under canonical_candidate_dir,
    plus scheduler_run_manifest.json. G3 may add a ``tier`` parameter for other tiers.
    """
    root = canonical_candidate_dir(architecture, ticker)
    names = trained_candidate_basenames(ticker, horizon)
    paths = [root / n for n in names]
    paths.append(root / MANIFEST_BASENAME)
    return paths


def validate_trained_candidate(
    architecture: str,
    horizon: str,
    ticker: str,
    dir_path: Path,
) -> ValidationResult:
    """Check presence of trained-candidate artifacts (and manifest) under dir_path."""
    missing: list[str] = []
    for rel in [p.name for p in get_required_artifacts(architecture, horizon, ticker)]:
        if not (dir_path / rel).is_file():
            missing.append(rel)
    ok = len(missing) == 0
    return ValidationResult(
        ok=ok,
        missing=missing,
        extra=[],
        reason="" if ok else "missing required trained-candidate artifacts",
    )


def tier_contract(architecture: str, tier: ModelTier) -> TierContract:
    """G3 will return real TierContract for EVALUATABLE+; G2 raises."""
    if tier == ModelTier.TRAINED:
        arch_e = Architecture(architecture)
        return TierContract(
            architecture=arch_e,
            tier=tier,
            artifacts=tuple(ArtifactSpec(p) for p in _trained_basename_templates()),
            path_resolver=lambda tk, hz: canonical_candidate_dir(arch_e.value, tk),
        )
    raise NotImplementedError(f"G3 scope: tier {tier!r} not defined in G2")


def validate_evaluatable_candidate(*args, **kwargs) -> ValidationResult:  # noqa: ANN001
    raise NotImplementedError("G3: EVALUATABLE_CANDIDATE contract")


def validate_promotable_candidate(*args, **kwargs) -> ValidationResult:  # noqa: ANN001
    raise NotImplementedError("G3: PROMOTABLE_CANDIDATE contract")


def validate_active_serving_candidate(*args, **kwargs) -> ValidationResult:  # noqa: ANN001
    raise NotImplementedError("G3: ACTIVE_SERVING_CANDIDATE contract")


__all__ = [
    "Architecture",
    "ModelTier",
    "ArtifactSpec",
    "TierContract",
    "ValidationResult",
    "MANIFEST_BASENAME",
    "trained_candidate_basenames",
    "get_required_artifacts",
    "validate_trained_candidate",
    "canonical_candidate_dir",
    "canonical_active_dir",
    "tier_contract",
]
```

**Note on `parallel_artifact_basenames` vs manifest:** `training_cache.py:904-915` returns **six** model/meta basenames; manifest filename is separate (`training_cache.py:33` `MANIFEST_FILENAME`, `training_cache.py:869` `candidate_manifest_path`). G2 contract helpers **append** `scheduler_run_manifest.json` in `get_required_artifacts` so the **eight** trained-candidate files match the G1 success-criteria list in this plan.

### Authority statement

Included in the module docstring above (verbatim requirement).

### What this module replaces

- **Primary duplicate today:** `training_cache.py:904-919`  - `parallel_artifact_basenames`, `cascade_artifact_basenames` (cascade aliases parallel).

**Recommendation (G2.3):** Replace the ** bodies** of `parallel_artifact_basenames` and `cascade_artifact_basenames` with thin wrappers that call `governance.artifact_contract.trained_candidate_basenames` (or `get_required_artifacts` for path-oriented callers), so **no second list** is maintained. Call sites to audit before refactor (grep re-verified):

- `training_cache.py:665-667`, `922-928`  - validators use basenames.
- `ml_scheduler.py:1236-1239`, `1352-1353`, `1783`, `2037-2041`  - manifest / SHA / dormant path.
- `train_compare.py:122-123`, `235-236`  - compare tooling.

**UNKNOWN until implementation:** whether any non-Python tooling assumes literal duplicate strings in `training_cache.py`; mitigation is repo-wide search after G2.2.

## Cascade Meta Writer Design

### Current state

- **Cascade training function:** `train_cascade_candidate` spans **`ml_scheduler.py:816-1201`**. The function returns immediately after `train_transformer(...)` (`ml_scheduler.py:1179-1191`) with **no** meta-assembly block before `warm_resume` / `return` (`ml_scheduler.py:1192-1201`).
- **Parallel meta writer (template):** `ml_scheduler.py:718-775`  - builds `X_meta`/`y_meta` via `_predict_xgb` / `_predict_lstm` / `_predict_transformer` under `with _strict_off_for_candidate_inference():` (`ml_scheduler.py:725`), fits `LogisticRegression` when `len(X_meta) >= 10` (`ml_scheduler.py:771-775`), writes `meta_{ticker}_{hz}.pkl` to `out_dir`.
- **Strict-mode helper:** `_strict_off_for_candidate_inference` at **`ml_scheduler.py:92-104`**.
- **Cascade eval already wrapped:** `_evaluate_cascade_on_full_rth` uses the same context manager at **`ml_scheduler.py:422`** (inside `try` starting `ml_scheduler.py:410`).

### What needs to be added

1. Same stacked feature construction as parallel: for each historical tabular row, `vector = [xgb_probs, lstm_probs, transformer_probs]` (each three-class), with LSTM/Transformer optional per-row degradation as in parallel (`ml_scheduler.py:741-763`).
2. Labels from the horizon outcome column: cascade already uses `label_col = outcome_column(hz)` at **`ml_scheduler.py:832-833`**; parallel uses `target_column = outcome_column(hz)` at **`ml_scheduler.py:521-522`** and `row.get(target_column)` at **`ml_scheduler.py:765`**  - cascade block should use **`label_col`** for `y_meta`.
3. Fit `sklearn.linear_model.LogisticRegression` on `(X_meta, y_meta)` (same hyperparameters as parallel: `C=1.0, max_iter=1000, random_state=42` per **`ml_scheduler.py:772`**).
4. Write `out_dir / f"meta_{ticker.upper()}_{hz}.pkl"` (**`ml_scheduler.py:774` pattern**).
5. Gate: `if len(X_meta) >= 10:` only then fit/write (**`ml_scheduler.py:771`**).
6. Wrap the inference loop with `with _strict_off_for_candidate_inference():` (**`ml_scheduler.py:725` pattern**).

### Where it goes in `train_cascade_candidate`

Insert **after** `tr = train_transformer(...)` completes (`ml_scheduler.py:1179-1191`) and **before** assembling `warm_resume` (`ml_scheduler.py:1192-1196`). That insertion point is **between lines 1191 and 1192** in the current file.

### Code shape (proposed insert  - single contiguous block)

This block is intended to be pasted **once**, reusing in-scope names `ticker`, `db_path`, `out_dir`, `df`, `label_col`, `hz`, `train_transformer` result `tr` is unused by meta but confirms training finished  - parallel meta does not use `tr` either.

```python
    # Meta-learner (cascade)  - mirror train_parallel_candidate meta assembly
    # (ml_scheduler.py:718-775): stack XGB/LSTM/Transformer probs per row; optional
    # LSTM/TR rows; same len(X_meta) >= 10 gate; write meta_<T>_<hz>.pkl into cascade out_dir.
    from sklearn.linear_model import LogisticRegression
    from ml_predict import _predict_xgb, _predict_lstm, _predict_transformer, CLASS_NAMES
    from train_all import preload_historical_db_for_eval
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    import ml_predict as mp
    import pickle

    orig_mp_dir = mp.MODEL_DIR
    htok_meta = mp.set_ml_infer_horizon_slug(hz)
    X_meta, y_meta = [], []
    try:
        with _strict_off_for_candidate_inference():
            mp.MODEL_DIR = out_dir
            mp.reset_caches()

            rows = df.to_dict("records")
            _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
            hist_db = (
                preload_historical_db_for_eval(db_path, ticker, max(_tss)) if _tss else None
            )
            for row in rows:
                inf_v1 = build_inference_snapshot_v1_from_db_row(
                    ticker=ticker,
                    expiry=None,
                    as_of_ts=row.get("ts_utc"),
                    db_row=row,
                )
                xgb_p = _predict_xgb(inf_v1, ticker, fusion_feature_overlay=row)
                lstm_p = tr_p = None
                ts_utc = row.get("ts_utc")
                if ts_utc and hist_db is not None:
                    try:
                        lstm_p = _predict_lstm(ticker, hist_db, inference_snapshot_v1=inf_v1)
                    except Exception as _lstm_e:
                        log.debug("%s cascade meta row: LSTM unavailable at ts=%s (%s)", ticker, ts_utc, _lstm_e)
                        lstm_p = None
                    try:
                        tr_p = _predict_transformer(ticker, hist_db, inference_snapshot_v1=inf_v1)
                    except Exception as _tr_e:
                        log.debug("%s cascade meta row: Transformer unavailable at ts=%s (%s)", ticker, ts_utc, _tr_e)
                        tr_p = None
                if xgb_p is None:
                    continue
                vec = (
                    [xgb_p.get(c, 0.333) for c in CLASS_NAMES] +
                    ([lstm_p.get(c, 0.333) for c in CLASS_NAMES] if lstm_p else [0.333, 0.333, 0.334]) +
                    ([tr_p.get(c, 0.333) for c in CLASS_NAMES] if tr_p else [0.333, 0.333, 0.334])
                )
                X_meta.append(vec)
                y_meta.append({"up": 0, "down": 1, "flat": 2}.get(row.get(label_col), 2))
    finally:
        mp.MODEL_DIR = orig_mp_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok_meta)

    if len(X_meta) >= 10:
        meta_mdl = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        meta_mdl.fit(np.array(X_meta), np.array(y_meta))
        with open(out_dir / f"meta_{ticker.upper()}_{hz}.pkl", "wb") as f:
            pickle.dump(meta_mdl, f)
```

**Import hygiene note for implementers:** `train_cascade_candidate` already imports `pickle` and `numpy as np` at **`ml_scheduler.py:867-869`**; the block above uses `np` and `pickle`  - either rely on outer imports or avoid redundant inner `import pickle` (implementation prompt should dedupe to match file style).

### Differences vs parallel

| Topic | Parallel (`train_parallel_candidate`) | Cascade (`train_cascade_candidate`) |
|--------|----------------------------------------|-------------------------------------|
| **Output path** | `out_dir` = parallel candidate leaf | `out_dir` = cascade candidate leaf (`ml_scheduler.py:819`) |
| **Label column variable** | `target_column` (`ml_scheduler.py:522`) | `label_col` (`ml_scheduler.py:833`)  - meta block must use **`label_col`** |
| **Training stack** | Independent XGB, LSTM, Transformer (`architecture="parallel"` in training calls, e.g. `ml_scheduler.py:680-711`) | XGB-fed LSTM / XGB+LSTM-fed Transformer (`architecture="cascade"`, e.g. `ml_scheduler.py:1021-1037`, `ml_scheduler.py:1179-1190`) |
| **Inference for meta** | `mp.MODEL_DIR = out_dir` under strict-off (`ml_scheduler.py:725-727`) | Same pattern; `out_dir` points at `models/cascade/<ticker>/` |

**Feature / model-input parity for meta:** Meta assembly does **not** re-feed engineered cascade tensors; it calls the same `_predict_*` entry points as parallel meta (`ml_scheduler.py:741-753`). With `mp.MODEL_DIR` set to the **cascade candidate leaf**, `_model_dir_for_ticker` resolves back to that directory under non-strict mode via the flat-artifact fallback (`ml_predict.py:302-307`). **UNKNOWN without a full trace in implementation:** whether any `_predict_lstm` / `_predict_transformer` path assumes `_INFER_ARCHITECTURE == "cascade"` for checkpoint layout; if integration tests fail, inspect `_load_lstm` / `_load_transformer` for cascade-specific branches before changing this block.

**Strict-off scope:** New cascade meta loop must use `_strict_off_for_candidate_inference()` the same way parallel meta does (`ml_scheduler.py:725`); cascade evaluation already uses it at `ml_scheduler.py:422`.

## Test Plan

### New tests required

**`tests/test_artifact_contract.py` (new)**

- `test_trained_candidate_required_artifacts_parallel`  - `get_required_artifacts("parallel", hz, ticker)` returns eight paths ending with expected basenames + manifest.
- `test_trained_candidate_required_artifacts_cascade`  - same for `"cascade"`.
- `test_canonical_candidate_dir_parallel` / `_cascade`  - paths equal `Path("models")/...` resolution from repo root (use `_repo_root()` pattern or chdir-safe fixture).
- `test_canonical_active_dir_default`  - `hz="1c"` resolves to `models/active/<ticker>` per `verify_active_models.py:62-75`.
- `test_canonical_active_dir_horizon_specific`  - e.g. `5c` maps to `models/active_5c/<ticker>`.
- `test_validate_trained_candidate_complete`  - temp dir populated with eight empty files (touch) yields `ValidationResult.ok`.
- `test_validate_trained_candidate_missing_meta`  - delete `meta_*`; expect `ok` is False, `missing` contains basename.

**`tests/test_cascade_meta_assembly.py` (new)**

- `test_cascade_meta_pickle_produced`  - integration: after training fixture or monkeypatched short path, assert `meta_<T>_<hz>.pkl` exists (may require DB + time budget; **UNKNOWN** minimal fixture size until tried).
- `test_cascade_meta_pickle_path_canonical`  - path under `canonical_candidate_dir("cascade", ticker)`.
- `test_cascade_meta_skipped_when_insufficient_data`  - force `<10` meta rows; expect no pickle (mirror parallel gating).

**`tests/test_centralization.py` (existing)**

- Must remain **224 passed, 0 failed** after G2.6 (baseline per project discipline).

### Existing tests to verify (must still pass)

By citation of import / patch surface:

- `tests/test_training_canonical_input.py:128`  - imports `train_parallel_candidate`; cascade meta must not break canonical input tests.
- `tests/test_arch_competition_eval_promotion.py:255-298`  - patches `_evaluate_*`; unchanged if eval signatures unchanged.
- `tests/test_scheduler_arch_competition_integration.py:211`  - source scan for governed pass; no change expected.
- `tests/test_cascade_challenger_stack.py:136-139`  - asserts `train_cascade_candidate` string presence; still true after edit.
- `tests/test_issue15_ml_horizon_5c.py`, `tests/test_issue17_ml_horizon_60c.py`  - `training_cache.build_manifest` / keys; G2.3 must preserve manifest behavior.
- `tests/test_manual_governance.py:22`  - `_scheduler_auto_promote_to_active`; untouched.

### Test data fixtures

- **Synthetic candidate dirs:** create `tmp_path` with eight zero-byte files named per `trained_candidate_basenames`  - **no existing fixture required** for contract unit tests.
- **Cascade meta integration:** likely needs small SQLite snapshot + `allowed_et_dates` narrowing OR heavy monkeypatch of `load_data` / `train_transformer`  - **UNKNOWN** which is cheaper until spike; if full train is too slow, prefer monkeypatching lower layers to emit `meta` path only for path/canonical tests.

## Implementation Order

| Sub-phase | Deliverable |
|-----------|-------------|
| **G2.1** | Add `governance/artifact_contract.py` (new); no consumer imports yet beyond self-test in REPL optional. |
| **G2.2** | Add `tests/test_artifact_contract.py`; green in isolation. |
| **G2.3** | Refactor `training_cache.py:904-919` to delegate basename lists to `artifact_contract.trained_candidate_basenames`; run grep for all call sites (`training_cache.py:665-667`, `922-928`, `ml_scheduler.py:1236-1239`, `1352-1353`, `1783`, `2037-2041`, `train_compare.py:122-123`, `235-236`). |
| **G2.4** | Insert cascade meta block in `ml_scheduler.py` between **`1191-1192`**. |
| **G2.5** | Add `tests/test_cascade_meta_assembly.py`. |
| **G2.6** | Run `python tests/test_centralization.py` + `pytest` (or project default) for new tests; all green. |
| **G2.7** | Update `OPEN_ITEMS.md` GOVERNANCE REBUILD STATUS (`OPEN_ITEMS.md:8+`)  - G2 complete, G3 next. |
| **G2.8** | Add `governance/G2_RESULT.md` with evidence (paths, command outputs, commit hash). |

Each sub-phase = one strict Cursor prompt.

## Success Criteria

G2 is complete when **all** hold:

- `governance/artifact_contract.py` exists with **TRAINED** contract for **both** `parallel` and `cascade` (same basename set).
- `training_cache.py` no longer embeds a second copy of the six basename strings for TRAINED tier  - it imports from `governance/artifact_contract.py` (per G2.3 recommendation).
- `train_cascade_candidate` produces `meta_<ticker>_<hz>.pkl` under `models/cascade/<ticker>/` on successful runs (same gate as parallel).
- Single-pair benchmark (e.g. AAPL / 5c) produces **eight** artifacts in **each** of `models/parallel/AAPL/` and `models/cascade/AAPL/` (six models + meta + manifest)  - manifest still written by existing `save_run_manifest` path (`ml_scheduler.py:2044+` region; parallel/cascade manifests built in same loop).
- `tests/test_centralization.py`: **224/0** minimum (higher only if that file gains checks).
- New test modules pass.
- Clean working tree after commits (per project rules).
- `OPEN_ITEMS.md` shows G2 complete, G3 next.
- `governance/G2_RESULT.md` exists.

## Validation Beyond "Tests Pass"

- **Directory inspection** after a real AAPL/5c train: list `models/parallel/AAPL/` and `models/cascade/AAPL/`  - same eight filenames modulo identical names (diff should be empty for required-name set).
- **Set equality:** `set(trained_candidate_basenames("AAPL","5c")).union({MANIFEST_BASENAME})` equals on-disk required names (use `MANIFEST_BASENAME` from `artifact_contract.py`).
- **Single-source proof:** `rg` for `xgb_.*\.pkl` string builders **outside** `artifact_contract.py` / thin wrappers should not reintroduce duplicate six-tuple lists (allow `ml_train` filenames, `lstm_model`, etc., as producers).

## Risks

1. **Cascade vs parallel checkpoint layout at `_predict_*` time:** If meta assembly loads wrong graph, meta probabilities skew or load fails  - mitigate with focused integration test and, if needed, `_cascade_challenger_inference_scope` investigation (`ml_predict.py:90-91`, `ml_predict.py:256-264`).
2. **`training_cache` refactor blast radius:** Many imports  - mitigate with full `rg "parallel_artifact_basenames"` before/after.
3. **Hardcoded lists in tests:** `rg "meta_.*pkl"` / `xgb_.*pkl` under `tests/`  - update to import contract helpers.
4. **Strict-off scope drift:** Ensure new meta loop is fully inside `with _strict_off_for_candidate_inference():` matching **`ml_scheduler.py:725-763`** structure.

## What G2 Does NOT Fix (preview of G3+)

After G2, the following **remain** as today unless later phases land:

- Governed competition / evaluation may still fail lineage or horizon parity checks (`arch_competition/lineage.py:29-87`).
- `models/arch_competition/` may still be absent if no successful governed write occurred (`governance/REBUILD_CONTEXT.md:10` observation; governed writers create parents before write: `arch_competition/eval_runner.py:365-367`, `arch_competition/promotion_engine.py:275-277`, `arch_competition/scheduler_integration.py:110-113` plus summary merge dir prep `arch_competition/scheduler_integration.py:122-124`).
- Direct-active mutation surface (`OPEN_ITEMS.md:39`, `governance/REBUILD_CONTEXT.md:55-56`).
- Scheduler fail-open / exit code semantics (`OPEN_ITEMS.md:48`, `ml_scheduler.py:1701-1707`, `ml_scheduler.py:2133-2135`  - line refs per G1; re-verify in G4 work).
- Option **(b)** strict threading (`OPEN_ITEMS.md:63`).
- Dormant auto-copy (`OPEN_ITEMS.md:51`, `ml_scheduler.py` near `parallel_artifact_basenames` use at **`ml_scheduler.py:1783`**  - verify exact block in G4).

---

**File creation:** This task adds **only** `governance/G2_PLAN.md`.

**Citations re-verified** against repository state used for this document: `ml_scheduler.py` (41-43, 92-104, 388-430, 505-522, 718-775, 816-833, 1179-1201, 1385-1386, 1586-1608, 1631-1654, 2037-2042), `training_cache.py` (33, 869, 904-919), `ml_predict.py` (203-307), `arch_competition/eval_runner.py` (208-266), `arch_competition/promotion_engine.py` (17-18, 60), `arch_competition/manual_control.py` (136-144), `verify_active_models.py` (62-75), `OPEN_ITEMS.md` (8, 36-63), `governance/REBUILD_CONTEXT.md` (12-22, 51-58), `governance/G1_DIAGNOSIS.md` (9-30, 41-97).
