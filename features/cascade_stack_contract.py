"""
Cascade challenger stack — versioned upstream features and lineage rules.

Production default remains **parallel** (`run_unified_stack_ml_once`). This module defines the
**challenger-only** cascade contract: what may be passed between stages, and how evaluation
lineage must match shared canonical artifacts (same cache keys / contracts as parallel).

No alternate dataset generation: cascade training in `ml_scheduler.train_cascade_candidate` uses
the same `compute_feature_cache_key` / `feature_cache_dir` / `db_training_fingerprint` as parallel.
"""

from __future__ import annotations





# --- Approved upstream-derived features only (no raw L1 / SignalInput / legacy MVP dict) ---

# Stage 2 LSTM: confluence vector appended with exactly these 3 scalars from Stage 1 XGB:
#   [P(up), P(down), P(flat)] from `_predict_xgb` → `_probs_dict_to_arr` (same order as CLASS_NAMES).
LSTM_STAGE_CASCADE_INPUT_FROM_XGB = (
    "xgb_prob_up",
    "xgb_prob_down",
    "xgb_prob_flat",
)

# Stage 3 Transformer: sequence tensor appended per timestep with 6 scalars:
#   [xgb_up, xgb_down, xgb_flat, lstm_up, lstm_down, lstm_flat]
# from validated `_predict_xgb` and `_predict_lstm` outputs only.
TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM = (
    "xgb_prob_up",
    "xgb_prob_down",
    "xgb_prob_flat",
    "lstm_prob_up",
    "lstm_prob_down",
    "lstm_prob_flat",
)

# Counts must match ml_predict._CASCADE_LSTM_CONF_EXTRA (3) and _CASCADE_TRANSFORMER_SEQ_EXTRA (6).
assert len(LSTM_STAGE_CASCADE_INPUT_FROM_XGB) == 3
assert len(TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM) == 6


class CascadeChallengerError(ValueError):
    """Cascade challenger inference cannot load artifacts or complete staged pipeline."""








