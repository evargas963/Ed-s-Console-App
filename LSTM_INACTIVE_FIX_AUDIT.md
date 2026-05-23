> **Classification:** Historical Record | **Scope:** Root point-in-time audit `LSTM_INACTIVE_FIX_AUDIT.md`; not binding unless ACTIVE_PROGRAM cites.

# LSTM Inactive Fix — Closure Audit

## Root Cause

**Primary**: LSTM shows inactive when `lstm_{ticker}_1c.pt` is missing from `models/active/{ticker}/`, or when `_model_dir_for_ticker()` does not resolve to the directory containing the binary.

**Flow**:
1. UI shows "INACTIVE" when `lstm_available` is false (from fusion/ml_predict output)
2. `lstm_available = lstm_p is not None` where `lstm_p = _predict_lstm(ticker, db)`
3. `_predict_lstm` returns `None` if `_load_lstm(ticker)` fails
4. `_load_lstm` fails when `lstm_{ticker}_1c.pt` does not exist at the path returned by `_model_dir_for_ticker(ticker)`
5. `_model_dir_for_ticker` previously required `xgb_{ticker}_1c.pkl` to exist in active/ — if XGB was missing but LSTM existed, it would fall through to parallel/flat and might not find the LSTM
6. Model binaries in `active/` could be missing when training wrote to `models/` (flat) or `models/parallel/{ticker}/` but promotion did not run or did not complete

## Affected Tickers

All tickers in `arch_state.json` that have meta in `active/` but lack the corresponding `.pt`/`.pkl` binary. The dashboard ticker defaults to SPY (or first of SPY/QQQ/IWM in arch_state).

## Files Changed

| File | Changes |
|------|---------|
| `server.py` | Sync missing binaries to active; LSTM status "BINARY MISSING" when meta exists but .pt absent |
| `ml_predict.py` | `_model_dir_for_ticker` uses active when any of xgb/lstm/transformer exists; fallback to flat `models/` |

---

## Exact Diffs

### server.py

**1. Sync missing binaries (before model health block):**
```python
# Sync missing binaries: if active has meta but not .pt/.pkl, copy from parallel/cascade/flat
def _sync_missing_binaries_to_active(ticker: str, active_dir: Path):
    t = ticker
    for model_file, meta_file in [
        (f"lstm_{t}_1c.pt", f"lstm_{t}_1c_meta.json"),
        (f"transformer_{t}_1c.pt", f"transformer_{t}_1c_meta.json"),
        (f"xgb_{t}_1c.pkl", f"xgb_{t}_1c_meta.json"),
    ]:
        dest = active_dir / model_file
        meta = active_dir / meta_file
        if meta.exists() and not dest.exists():
            for src_dir in [
                _models_dir / "parallel" / t,
                _models_dir / "cascade" / t,
                _models_dir,  # flat train_all output
            ]:
                src = src_dir / model_file
                if src.exists():
                    try:
                        import shutil
                        shutil.copy2(src, dest)
                        log.info("Synced %s to active/%s/%s", model_file, t, model_file)
                        break
                    except Exception as e:
                        log.warning("Sync %s failed: %s", model_file, e)
try:
    _sync_missing_binaries_to_active(_dashboard_ticker, _active_dir)
except Exception as e:
    log.debug("sync_missing_binaries: %s", e)
```

**2. LSTM status — add BINARY MISSING:**
```python
# LSTM: LIVE if .pt exists; BINARY MISSING if meta exists but .pt absent; NOT TRAINED if no meta
_lstm_status = "LIVE" if _lstm_path.exists() else ("BINARY MISSING" if _lstm_meta.exists() else "NOT TRAINED")
_model_health.append({
    "model": "LSTM",
    "status": _lstm_status,
    ...
})
```

### ml_predict.py

**`_model_dir_for_ticker` — use active when any model exists; add flat fallback:**
```python
# Before: required (active / f"xgb_{ticker}_1c.pkl").exists()
# After: use active if any of xgb/lstm/transformer binary exists
if active.exists():
    has_any = (
        (active / f"xgb_{ticker}_1c.pkl").exists()
        or (active / f"lstm_{ticker}_1c.pt").exists()
        or (active / f"transformer_{ticker}_1c.pt").exists()
    )
    if has_any:
        return active

# Same for parallel - check any model
# Add flat fallback: models/lstm_SPY_1c.pt or models/xgb_SPY_1c.pkl
flat_pt = MODEL_DIR / f"lstm_{ticker}_1c.pt"
flat_pkl = MODEL_DIR / f"xgb_{ticker}_1c.pkl"
if flat_pt.exists() or flat_pkl.exists():
    return MODEL_DIR
```

---

## Before / After

### Active-model status logic

| Component | Before | After |
|-----------|--------|-------|
| LSTM status | LIVE if `lstm_*.pt` exists, else NOT TRAINED | LIVE if .pt exists; BINARY MISSING if meta exists but .pt missing; NOT TRAINED if no meta |
| Model dir selection | active only if xgb.pkl exists | active if any of xgb/lstm/transformer exists |
| Binary recovery | None | Sync from parallel/cascade/flat to active when meta exists but binary missing |
| Flat layout | Not considered | `models/lstm_{ticker}_1c.pt` and `models/xgb_{ticker}_1c.pkl` supported as fallback |

### Card binding (unchanged)

- "What the Data Says" and "The Call" use `lstm_available`, `lstm_dominant`, etc. from fusion output
- Fusion gets these from ml_predict's `_model_health_output`, which runs `_predict_lstm`
- No changes to card bindings; fix ensures `_predict_lstm` can load the model when the binary exists

---

## Closure Audit Result

- [x] Root cause identified (binary missing or model dir not resolving to active)
- [x] Sync path adds binaries from parallel/cascade/flat when meta exists
- [x] `_model_dir_for_ticker` uses active when any model binary exists
- [x] Flat `models/` layout supported for train_all output
- [x] LSTM status distinguishes BINARY MISSING (actionable) from NOT TRAINED
- [x] No dead legacy logic
- [x] verify_active_models runs (reports provenance issues separately; binaries present for existing deployment)

---

## Validation

1. **LSTM artifact in active**: Run `python verify_active_models.py` — lstm shows `exists=True` for tickers with binaries
2. **verify_active_models**: Exits 1 if non-compliant (provenance); exit 0 when all compliant. Provenance is a separate fix.
3. **UI model health**: LSTM shows LIVE when `lstm_{ticker}_1c.pt` exists in active; BINARY MISSING when meta exists but .pt missing; NOT TRAINED when no meta

**To create missing binaries**: Run `python train_all.py --ticker SPY` or `python ml_scheduler.py --run-now`. The sync will copy them to active/ on the next `/api/state` request.
