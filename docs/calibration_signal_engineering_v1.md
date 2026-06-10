> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/calibration_signal_engineering_v1.md`.

# Calibration signal engineering (v1)

## Before vs after (population aggregates)

```json
{
  "before_canonical_effective": {
    "slice_id": "population|before|canonical_effective",
    "slice_kind": "population",
    "n": 120,
    "min_n_gate": 30,
    "gate_sufficient": true,
    "mean_outcome_5c_pts": 0.061667,
    "mean_ev_actual_final_signal": 0.058333,
    "mean_ev_always_long": 0.058333,
    "mean_ev_always_short": -0.058333,
    "mean_ev_random_long_short": 0.0,
    "delta_ev_actual_minus_long": 0.0,
    "delta_ev_actual_minus_random": 0.058333,
    "win_rate_strict_positive": 0.5,
    "mean_brier": 0.644222,
    "bootstrap_actual_minus_long": {
      "n": 120,
      "mean_delta": 0.0,
      "ci95_low": 0.0,
      "ci95_high": 0.0
    },
    "bootstrap_actual_minus_random": {
      "n": 120,
      "mean_delta": 0.058333,
      "ci95_low": 0.027917,
      "ci95_high": 0.088333
    },
    "edge_vs_always_long": false,
    "edge_vs_random": true,
    "classification": "NO_EDGE"
  },
  "after_policies": {
    "after_policy_fusion_margin_0.04_full_pop": {
      "slice_id": "population|after|fusion_margin_0.04",
      "slice_kind": "population",
      "n": 120,
      "min_n_gate": 30,
      "gate_sufficient": true,
      "mean_outcome_5c_pts": 0.061667,
      "mean_ev_actual_final_signal": null,
      "mean_ev_always_long": 0.058333,
      "mean_ev_always_short": -0.058333,
      "mean_ev_random_long_short": 0.0,
      "delta_ev_actual_minus_long": null,
      "delta_ev_actual_minus_random": null,
      "win_rate_strict_positive": null,
      "mean_brier": 0.644222,
      "bootstrap_actual_minus_long": {},
      "bootstrap_actual_minus_random": {},
      "edge_vs_always_long": false,
      "edge_vs_random": false,
      "classification": "NO_EDGE"
    },
    "after_policy_fusion_margin_0.006_full_pop": {
      "slice_id": "population|after|fusion_margin_0.006",
      "slice_kind": "population",
      "n": 120,
      "min_n_gate": 30,
      "gate_sufficient": true,
      "mean_outcome_5c_pts": 0.061667,
      "mean_ev_actual_final_signal": 0.060089,
      "mean_ev_always_long": 0.058333,
      "mean_ev_always_short": -0.058333,
      "mean_ev_random_long_short": 0.0,
      "delta_ev_actual_minus_long": 0.001756,
      "delta_ev_actual_minus_random": 0.060089,
      "win_rate_strict_positive": 0.5,
      "mean_brier": 0.644222,
      "bootstrap_actual_minus_long": {
        "n": 112,
        "mean_delta": 0.0,
        "ci95_low": 0.0,
        "ci95_high": 0.0
      },
      "bootstrap_actual_minus_random": {
        "n": 112,
        "mean_delta": 0.060089,
        "ci95_low": 0.028929,
        "ci95_high": 0.092054
      },
      "edge_vs_always_long": false,
      "edge_vs_random": true,
      "classification": "NO_EDGE"
    },
    "after_policy_fusion_argmax_full_pop": {
      "slice_id": "population|after|fusion_argmax",
      "slice_kind": "population",
      "n": 120,
      "min_n_gate": 30,
      "gate_sufficient": true,
      "mean_outcome_5c_pts": 0.061667,
      "mean_ev_actual_final_signal": 0.058333,
      "mean_ev_always_long": 0.058333,
      "mean_ev_always_short": -0.058333,
      "mean_ev_random_long_short": 0.0,
      "delta_ev_actual_minus_long": 0.0,
      "delta_ev_actual_minus_random": 0.058333,
      "win_rate_strict_positive": 0.5,
      "mean_brier": 0.644222,
      "bootstrap_actual_minus_long": {
        "n": 120,
        "mean_delta": 0.0,
        "ci95_low": 0.0,
        "ci95_high": 0.0
      },
      "bootstrap_actual_minus_random": {
        "n": 120,
        "mean_delta": 0.058333,
        "ci95_low": 0.027917,
        "ci95_high": 0.088333
      },
      "edge_vs_always_long": false,
      "edge_vs_random": true,
      "classification": "NO_EDGE"
    },
    "after_policy_fusion_dominant_outcome_full_pop": {
      "slice_id": "population|after|fusion_dominant_outcome",
      "slice_kind": "population",
      "n": 120,
      "min_n_gate": 30,
      "gate_sufficient": true,
      "mean_outcome_5c_pts": 0.061667,
      "mean_ev_actual_final_signal": 0.058333,
      "mean_ev_always_long": 0.058333,
      "mean_ev_always_short": -0.058333,
      "mean_ev_random_long_short": 0.0,
      "delta_ev_actual_minus_long": 0.0,
      "delta_ev_actual_minus_random": 0.058333,
      "win_rate_strict_positive": 0.5,
      "mean_brier": 0.644222,
      "bootstrap_actual_minus_long": {
        "n": 120,
        "mean_delta": 0.0,
        "ci95_low": 0.0,
        "ci95_high": 0.0
      },
      "bootstrap_actual_minus_random": {
        "n": 120,
        "mean_delta": 0.058333,
        "ci95_low": 0.027917,
        "ci95_high": 0.088333
      },
      "edge_vs_always_long": false,
      "edge_vs_random": true,
      "classification": "NO_EDGE"
    }
  }
}
```

## Directional diagnostics

```json
{
  "pct_final_signal": {
    "wait": 120
  },
  "pct_canonical_effective": {
    "long": 120
  },
  "pct_fusion_argmax": {
    "long": 120
  },
  "pct_fusion_margin_0.04": {
    "wait": 120
  },
  "pct_fusion_margin_0.006": {
    "long": 112,
    "wait": 8
  },
  "pct_fusion_dominant_outcome": {
    "long": 120
  },
  "ev_by_direction_canonical_effective": {
    "mean_ev_by_direction": {
      "long": 0.058333
    },
    "win_rate_by_direction": {
      "long": 0.5
    }
  },
  "ev_by_direction_fusion_argmax": {
    "mean_ev_by_direction": {
      "long": 0.058333
    },
    "win_rate_by_direction": {
      "long": 0.5
    }
  },
  "ev_by_direction_fusion_margin_0.04": {
    "mean_ev_by_direction": {},
    "win_rate_by_direction": {}
  },
  "ev_by_direction_fusion_margin_0.006": {
    "mean_ev_by_direction": {
      "long": 0.060089
    },
    "win_rate_by_direction": {
      "long": 0.5
    }
  },
  "ev_by_direction_fusion_dominant_outcome": {
    "mean_ev_by_direction": {
      "long": 0.058333
    },
    "win_rate_by_direction": {
      "long": 0.5
    }
  },
  "fusion_prob_distribution": {
    "prob_up": {
      "min": 0.359,
      "mean": 0.362133,
      "max": 0.364
    },
    "prob_down": {
      "min": 0.352,
      "mean": 0.35415,
      "max": 0.357
    },
    "prob_flat": {
      "min": 0.282,
      "mean": 0.283683,
      "max": 0.285
    },
    "top_minus_second": {
      "min": 0.002,
      "mean": 0.007983,
      "max": 0.012
    }
  },
  "model_output_prob_separation": {
    "top_minus_second_per_model_row": {
      "min": 0.01,
      "mean": 0.01,
      "max": 0.01
    },
    "note": "Flattened x3 models \u00d7 rows; stub uses identical probs \u2192 separation ~0."
  }
}
```

## Failure identification

```json
{
  "why_canonical_defaults_long": [
    "_effective_directional_signal uses canonical triplet; tie-break order is p_up >= p_dn >= p_fl \u2192 'long' when equal or up wins.",
    "Stub fusion + canonical stack produce max class 'up' with small positive spread over 'down' in logged JSON."
  ],
  "why_short_signals_absent_in_log": [
    "call.signal / final_signal from compute_signals path is 'wait' under test harness (no directional trade from decision engine).",
    "Canonical/fusion still encode direction probabilities but execution layer does not emit short without policy change."
  ],
  "model_output_separation": [
    "Fake run_unified_stack_ml_once returns identical 0.34/0.33/0.33 per model \u2192 no cross-model disagreement for stack vote."
  ],
  "sample_fusion_keys": [
    "available",
    "breakout_posterior",
    "pinning_posterior",
    "continuation_posterior",
    "reversal_posterior",
    "vol_expansion_posterior",
    "mean_reversion_posterior",
    "weight_xgboost",
    "weight_lstm",
    "weight_transformer",
    "weight_monte_carlo",
    "weight_rules",
    "weight_regime",
    "dominant_outcome",
    "dominant_probability",
    "fusion_confidence",
    "fusion_confidence_score",
    "n_sources_available",
    "n_sources_active",
    "evidence_summary",
    "contradiction_summary",
    "fusion_summary",
    "mc_available",
    "mc_containment",
    "mc_expansion"
  ],
  "sample_canonical_keys": [
    "direction",
    "probability_up",
    "probability_down",
    "probability_flat",
    "confidence",
    "provenance"
  ]
}
```

## Filtered runs (fusion_margin=0.04 + row filter)

### all_rows_control (n=120)

- **FINAL_FILTER_EDGE:** `NO_EDGE`

```json
{
  "slice_id": "population|filtered|all_rows_control|fusion_margin_0.04",
  "slice_kind": "population+filter",
  "n": 120,
  "min_n_gate": 30,
  "gate_sufficient": true,
  "mean_outcome_5c_pts": 0.061667,
  "mean_ev_actual_final_signal": null,
  "mean_ev_always_long": 0.058333,
  "mean_ev_always_short": -0.058333,
  "mean_ev_random_long_short": 0.0,
  "delta_ev_actual_minus_long": null,
  "delta_ev_actual_minus_random": null,
  "win_rate_strict_positive": null,
  "mean_brier": 0.644222,
  "bootstrap_actual_minus_long": {},
  "bootstrap_actual_minus_random": {},
  "edge_vs_always_long": false,
  "edge_vs_random": false,
  "classification": "NO_EDGE"
}
```

### utc_00_05_harness_overlap (n=104)

- **FINAL_FILTER_EDGE:** `NO_EDGE`

```json
{
  "slice_id": "population|filtered|utc_00_05_harness_overlap|fusion_margin_0.04",
  "slice_kind": "population+filter",
  "n": 104,
  "min_n_gate": 30,
  "gate_sufficient": true,
  "mean_outcome_5c_pts": 0.060865,
  "mean_ev_actual_final_signal": null,
  "mean_ev_always_long": 0.057596,
  "mean_ev_always_short": -0.057596,
  "mean_ev_random_long_short": 0.0,
  "delta_ev_actual_minus_long": null,
  "delta_ev_actual_minus_random": null,
  "win_rate_strict_positive": null,
  "mean_brier": 0.643811,
  "bootstrap_actual_minus_long": {},
  "bootstrap_actual_minus_random": {},
  "edge_vs_always_long": false,
  "edge_vs_random": false,
  "classification": "NO_EDGE"
}
```

## Best filtered marginal slices (by delta_vs_long, top from each run)

```json
[
  {
    "filter": "all_rows_control",
    "slices": [
      {
        "slice_id": "marginal|ticker=DIA",
        "slice_kind": "marginal:ticker",
        "n": 30,
        "min_n_gate": 30,
        "gate_sufficient": true,
        "mean_outcome_5c_pts": 0.061667,
        "mean_ev_actual_final_signal": null,
        "mean_ev_always_long": 0.058333,
        "mean_ev_always_short": -0.058333,
        "mean_ev_random_long_short": 0.0,
        "delta_ev_actual_minus_long": null,
        "delta_ev_actual_minus_random": null,
        "win_rate_strict_positive": null,
        "mean_brier": 0.644184,
        "bootstrap_actual_minus_long": {},
        "bootstrap_actual_minus_random": {},
        "edge_vs_always_long": false,
        "edge_vs_random": false,
        "classification": "NO_EDGE"
      },
      {
        "slice_id": "marginal|ticker=IWM",
        "slice_kind": "marginal:ticker",
        "n": 30,
        "min_n_gate": 30,
        "gate_sufficient": true,
        "mean_outcome_5c_pts": 0.061667,
        "mean_ev_actual_final_signal": null,
        "mean_ev_always_long": 0.058333,
        "mean_ev_always_short": -0.058333,
        "mean_ev_random_long_short": 0.0,
        "delta_ev_actual_minus_long": null,
        "delta_ev_actual_minus_random": null,
        "win_rate_strict_positive": null,
        "mean_brier": 0.644088,
        "bootstrap_actual_minus_long": {},
        "bootstrap_actual_minus_random": {},
        "edge_vs_always_long": false,
        "edge_vs_random": false,
        "classification": "NO_EDGE"
      },
      {
        "slice_id": "marginal|ticker=QQQ",
        "slice_kind": "marginal:ticker",
        "n": 30,
        "min_n_gate": 30,
        "gate_sufficient": true,
        "mean_outcome_5c_pts": 0.061667,
        "mean_ev_actual_final_signal": null,
        "mean_ev_always_long": 0.058333,
        "mean_ev_always_short": -0.058333,
        "mean_ev_random_long_short": 0.0,
        "delta_ev_actual_minus_long": null,
        "delta_ev_actual_minus_random": null,
        "win_rate_strict_positive": null,
        "mean_brier": 0.644428,
        "bootstrap_actual_minus_long": {},
        "bootstrap_actual_minus_random": {},
        "edge_vs_always_long": false,
        "edge_vs_random": false,
        "classification": "NO_EDGE"
      }
    ]
  },
  {
    "filter": "utc_00_05_harness_overlap",
    "slices": [
      {
        "slice_id": "marginal|ticker=IWM",
        "slice_kind": "marginal:ticker",
        "n": 30,
        "min_n_gate": 30,
        "gate_sufficient": true,
        "mean_outcome_5c_pts": 0.061667,
        "mean_ev_actual_final_signal": null,
        "mean_ev_always_long": 0.058333,
        "mean_ev_always_short": -0.058333,
        "mean_ev_random_long_short": 0.0,
        "delta_ev_actual_minus_long": null,
        "delta_ev_actual_minus_random": null,
        "win_rate_strict_positive": null,
        "mean_brier": 0.644088,
        "bootstrap_actual_minus_long": {},
        "bootstrap_actual_minus_random": {},
        "edge_vs_always_long": false,
        "edge_vs_random": false,
        "classification": "NO_EDGE"
      },
      {
        "slice_id": "marginal|ticker=QQQ",
        "slice_kind": "marginal:ticker",
        "n": 30,
        "min_n_gate": 30,
        "gate_sufficient": true,
        "mean_outcome_5c_pts": 0.061667,
        "mean_ev_actual_final_signal": null,
        "mean_ev_always_long": 0.058333,
        "mean_ev_always_short": -0.058333,
        "mean_ev_random_long_short": 0.0,
        "delta_ev_actual_minus_long": null,
        "delta_ev_actual_minus_random": null,
        "win_rate_strict_positive": null,
        "mean_brier": 0.644428,
        "bootstrap_actual_minus_long": {},
        "bootstrap_actual_minus_random": {},
        "edge_vs_always_long": false,
        "edge_vs_random": false,
        "classification": "NO_EDGE"
      },
      {
        "slice_id": "marginal|ticker=SPY",
        "slice_kind": "marginal:ticker",
        "n": 30,
        "min_n_gate": 30,
        "gate_sufficient": true,
        "mean_outcome_5c_pts": 0.061667,
        "mean_ev_actual_final_signal": null,
        "mean_ev_always_long": 0.058333,
        "mean_ev_always_short": -0.058333,
        "mean_ev_random_long_short": 0.0,
        "delta_ev_actual_minus_long": null,
        "delta_ev_actual_minus_random": null,
        "win_rate_strict_positive": null,
        "mean_brier": 0.644186,
        "bootstrap_actual_minus_long": {},
        "bootstrap_actual_minus_random": {},
        "edge_vs_always_long": false,
        "edge_vs_random": false,
        "classification": "NO_EDGE"
      }
    ]
  }
]
```

## FINAL

- **FINAL_RESULT:** `NO_EDGE`
- population EDGE (any policy in after_policies): `False`
- any filtered marginal EDGE: `False`
