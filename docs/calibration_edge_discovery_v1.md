> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/calibration_edge_discovery_v1.md`.

# Calibration edge discovery (v1)

## A. Dataset description

- **db:** `data\calibration_accumulation_validation.db`
- **labeled+trusted raw:** 120
- **after anchor filter:** 120
- **excluded (no anchor):** 0
- **per-row feature rows written:** 120 (see JSON `per_row_feature_extract`)

## B. Full slice table (all slices)

| slice_id | kind | n | mean_ev_actual | mean_ev_long | mean_ev_random | delta_vs_long | delta_vs_random | Brier | class |
|---|---|--:|---:|---:|---:|---:|---:|---|---|
| marginal\|ticker=DIA | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| marginal\|ticker=IWM | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| marginal\|ticker=QQQ | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |
| marginal\|ticker=SPY | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644186 | NO_EDGE |
| marginal\|regime_primary=pinning | marginal:regime_primary | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|vol_regime=unknown | marginal:vol_regime | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|vix_bucket=unknown | marginal:vix_bucket | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|session_bucket=unknown | marginal:session_bucket | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|session_rth_derived=unknown_session | marginal:session_rth_der | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|utc_hour_bucket_6h=utc_00_05 | marginal:utc_hour_bucket | 104 | 0.057596 | 0.057596 | 0.0 | 0.0 | 0.057596 | 0.643811 | NO_EDGE |
| marginal\|utc_hour_bucket_6h=utc_06_11 | marginal:utc_hour_bucket | 16 | 0.063125 | 0.063125 | 0.0 | 0.0 | 0.063125 | 0.646889 | NO_EDGE |
| marginal\|zone=pin_bull | marginal:zone | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|vwap_side=above | marginal:vwap_side | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|final_signal=wait | marginal:final_signal | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|call_conviction=low | marginal:call_conviction | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|canonical_confidence_bucket=medium | marginal:canonical_confi | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|alignment_state=UNUSABLE | marginal:alignment_state | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| 2d\|ticker=DIA\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| 2d\|ticker=IWM\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| 2d\|ticker=QQQ\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |
| 2d\|ticker=SPY\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644186 | NO_EDGE |
| 2d\|ticker=DIA\|final_signal=wait | 2d:ticker×final_signal | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| 2d\|ticker=IWM\|final_signal=wait | 2d:ticker×final_signal | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| 2d\|ticker=QQQ\|final_signal=wait | 2d:ticker×final_signal | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |
| 2d\|ticker=SPY\|final_signal=wait | 2d:ticker×final_signal | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644186 | NO_EDGE |
| 2d\|ticker=DIA\|alignment_state=UNUSABLE | 2d:ticker×alignment_stat | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| 2d\|ticker=IWM\|alignment_state=UNUSABLE | 2d:ticker×alignment_stat | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| 2d\|ticker=QQQ\|alignment_state=UNUSABLE | 2d:ticker×alignment_stat | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |
| 2d\|ticker=SPY\|alignment_state=UNUSABLE | 2d:ticker×alignment_stat | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644186 | NO_EDGE |
| 2d\|call_conviction=low\|alignment_state=UNUSABLE | 2d:call_conviction×align | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| 2d\|vol_regime=unknown\|vwap_side=above | 2d:vol_regime×vwap_side | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| 2d\|session_rth_derived=unknown_session\|utc_hour_bucket_6h=utc_00_05 | 2d:session_rth_derived×u | 104 | 0.057596 | 0.057596 | 0.0 | 0.0 | 0.057596 | 0.643811 | NO_EDGE |
| 2d\|session_rth_derived=unknown_session\|utc_hour_bucket_6h=utc_06_11 | 2d:session_rth_derived×u | 16 | 0.063125 | 0.063125 | 0.0 | 0.0 | 0.063125 | 0.646889 | NO_EDGE |

## C. Top EDGE slices (ranked by delta_vs_long; may be empty)

| slice_id | kind | n | mean_ev_actual | mean_ev_long | mean_ev_random | delta_vs_long | delta_vs_random | Brier | class |
|---|---|--:|---:|---:|---:|---:|---:|---|---|

## D. Bottom slices (lowest delta_vs_long, full set)

| slice_id | kind | n | mean_ev_actual | mean_ev_long | mean_ev_random | delta_vs_long | delta_vs_random | Brier | class |
|---|---|--:|---:|---:|---:|---:|---:|---|---|
| marginal\|ticker=DIA | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| marginal\|ticker=IWM | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| marginal\|ticker=QQQ | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |
| marginal\|ticker=SPY | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644186 | NO_EDGE |
| marginal\|regime_primary=pinning | marginal:regime_primary | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |

## E. All slices classified EDGE (full ranked list)

| slice_id | kind | n | mean_ev_actual | mean_ev_long | mean_ev_random | delta_vs_long | delta_vs_random | Brier | class |
|---|---|--:|---:|---:|---:|---:|---:|---|---|

## F. Worst NO_EDGE sample (low delta_vs_long)

| slice_id | kind | n | mean_ev_actual | mean_ev_long | mean_ev_random | delta_vs_long | delta_vs_random | Brier | class |
|---|---|--:|---:|---:|---:|---:|---:|---|---|
| marginal\|ticker=DIA | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| marginal\|ticker=IWM | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| marginal\|ticker=QQQ | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |
| marginal\|ticker=SPY | marginal:ticker | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644186 | NO_EDGE |
| marginal\|regime_primary=pinning | marginal:regime_primary | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|vol_regime=unknown | marginal:vol_regime | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|vix_bucket=unknown | marginal:vix_bucket | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|session_bucket=unknown | marginal:session_bucket | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|session_rth_derived=unknown_session | marginal:session_rth_der | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|utc_hour_bucket_6h=utc_00_05 | marginal:utc_hour_bucket | 104 | 0.057596 | 0.057596 | 0.0 | 0.0 | 0.057596 | 0.643811 | NO_EDGE |
| marginal\|utc_hour_bucket_6h=utc_06_11 | marginal:utc_hour_bucket | 16 | 0.063125 | 0.063125 | 0.0 | 0.0 | 0.063125 | 0.646889 | NO_EDGE |
| marginal\|zone=pin_bull | marginal:zone | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|vwap_side=above | marginal:vwap_side | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|final_signal=wait | marginal:final_signal | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|call_conviction=low | marginal:call_conviction | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|canonical_confidence_bucket=medium | marginal:canonical_confi | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| marginal\|alignment_state=UNUSABLE | marginal:alignment_state | 120 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644222 | NO_EDGE |
| 2d\|ticker=DIA\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644184 | NO_EDGE |
| 2d\|ticker=IWM\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644088 | NO_EDGE |
| 2d\|ticker=QQQ\|regime_primary=pinning | 2d:ticker×regime_primary | 30 | 0.058333 | 0.058333 | 0.0 | 0.0 | 0.058333 | 0.644428 | NO_EDGE |

## G. Feature importance (naive)

```json
{
  "pearson_fusion_prob_up_vs_outcome_5c_pts": 0.039516,
  "mean_outcome_pts_by_final_signal": {
    "wait": 0.061667
  },
  "note": "Descriptive only; not causal. MHAP/fusion from logged JSON."
}
```

## H. Failure modes

- **Effective EV** uses `effective_signal_for_ev` (canonical dominant class when `final_signal=wait`).
- **Dominant class is always `up` in this build** (fusion probs ~0.36/0.35/0.28) → effective policy matches **always-long** on every row → `delta_vs_long=0` for all slices.
- **EDGE classification** additionally requires bootstrap CI of (actual−long) > 0 — never satisfied when means are identical.
- **Random baseline** mean is 0 while outcome mix varies → positive `delta_vs_random` without incremental alpha vs long.

## I. FINAL (system-level)

- **FINAL:** `NO_EDGE`
- **marginal EDGE slices found:** False
