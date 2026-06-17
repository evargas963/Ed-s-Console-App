> **Classification:** Historical Record | **Scope:** Root point-in-time audit `MODEL_STATUS_HARDENING_AUDIT.md`; not binding unless ACTIVE_PROGRAM cites.

# Model Status Hardening — Closure Audit

## Root Cause

Model status semantics were inconsistent and not governance-aware:

1. **XGB/Transformer** used legacy `meta.approved` (unreliable; training pipelines never write it)
2. **LSTM** used only binary presence (`.pt` exists) — ignored provenance
3. **LIVE** could include non-compliant artifacts (binary present but metadata lacking provenance)
4. **Sync** logged at INFO but did not warn that promotion might have failed
5. **UI** had no way to distinguish "exists" from "approved" (governance-compliant)

## Files Changed

| File | Changes |
|------|---------|
| `server.py` | Governance-aware status; sync logging; `status_reason`; `model_sync_used` |
| `static/index.html` | Model Health card; sync warning banner; tooltips on pills and stack rows |
| `tests/test_centralization.py` | test_model_health uses LIVE/NON-COMPLIANT semantics |

---

## Exact Diffs

### server.py

**1. Sync — explicit logging + publication warning:**
```python
def _sync_missing_binaries_to_active(ticker: str, active_dir: Path) -> int:
    """Copy missing binaries from candidate dirs. Returns count of files synced."""
    synced = 0
    # ... copy logic ...
    if synced > 0:
        log.warning(
            "Model sync used for %s (%d file(s)) — promotion pipeline may not have run. "
            "Run: python ml_scheduler.py --run-now",
            ticker, synced,
        )
    return synced
# ...
_sync_count = _sync_missing_binaries_to_active(...)
```

**2. Status logic — governance-aware via check_artifact_compliance:**
- NOT TRAINED: no meta
- BINARY MISSING: meta exists, binary missing
- NON-COMPLIANT: binary + meta exist, but provenance not compliant
- LIVE: binary + meta + provenance compliant

**3. Per-model status with status_reason:**
```python
def _model_status_from_artifact(name, display_name, meta_path, edge_key, version_key):
    art = _artifacts.get(name, {})
    if not meta_exists: return {..., "status": "NOT TRAINED", "status_reason": "No metadata — model never promoted"}
    if not art.get("exists"): return {..., "status": "BINARY MISSING", "status_reason": "..."}
    if not art.get("has_provenance"): return {..., "status": "NON-COMPLIANT", "status_reason": issues}
    return {..., "status": "LIVE", "status_reason": "Binary + metadata + provenance compliant"}
```

**4. New payload fields:**
- `model_sync_used`: true when sync copied any file (publication problem)
- `status_reason`: per-model explanation for tooltips

### static/index.html

**1. Model Health card (sidebar):**
- Summary: "N/3 approved" (LIVE count)
- Per-model: name + status with tooltip from status_reason
- Sync warning banner when model_sync_used

**2. Model Stack rows:**
- `title` on each row with governance status (e.g. "LSTM: NON-COMPLIANT — metadata lacks provenance")

**3. Model pills (XGB, LSTM, TRNS):**
- `title` with status + status_reason for governance-aware tooltip

---

## Before / After Status Semantics

| Aspect | Before | After |
|--------|--------|-------|
| XGB status | LIVE if meta.approved else DISABLED | LIVE / NON-COMPLIANT / BINARY MISSING / NOT TRAINED from compliance |
| LSTM status | LIVE if .pt else BINARY MISSING / NOT TRAINED | Same taxonomy; LIVE requires provenance |
| Transformer | Same as XGB | Same as XGB |
| LIVE definition | Binary exists (LSTM) or approved flag (XGB/TF) | Binary + meta + provenance compliant |
| n_models_live | Count LIVE | Count LIVE only (governance-compliant) |
| Sync logging | INFO on copy | INFO + WARNING when sync used (publication problem) |
| UI | No governance display | Model Health card + tooltips on pills/rows |

---

## Closure Audit Result

- [x] Root cause identified (legacy approved; no provenance; sync hiding problems)
- [x] Status labels: LIVE, NON-COMPLIANT, BINARY MISSING, NOT TRAINED
- [x] Separated: binary present, metadata present, provenance compliant
- [x] Sync logs explicitly; warns when used
- [x] UI: Model Health card, tooltips, sync warning banner
- [x] Tests updated (test_model_health uses LIVE/NON-COMPLIANT)
- [x] No misleading status — LIVE is strictly governance-compliant
- [x] Dead legacy: removed meta.approved usage for status; DISABLED replaced by NON-COMPLIANT/BINARY MISSING/NOT TRAINED

---

## Validation

1. **LIVE** only when verify_active_models would report compliant for that artifact
2. **NON-COMPLIANT** when binary+meta exist but provenance fails
3. **BINARY MISSING** when meta exists, binary absent
4. **NOT TRAINED** when no meta
5. **model_sync_used** true when any file was copied; sync triggers WARNING in server log
6. **UI** shows Model Health with status colors; tooltips explain reason
