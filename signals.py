"""
signals.py
Full model-stack orchestrator.

REQUIRED STACK ORDER (non-negotiable, enforced in code):
  1. Market Data          — inp (SignalInput)
  1b. Canonical snapshot   — InferenceSnapshotV1 once per tick (MVP row for vol/regime/MC/prediction filters)
  2. Volatility Regime    — classify_volatility_regime(inp, mvp_features=…); policy layer
  3. Market Regime        — classify_regime(inp, rules, mvp_features=…); needs rules for micro
  4. Feature Engineering  — build_fusion_model_overlay_for_stack **once per tick**, reused per horizon
  5. ML Models            — XGB/LSTM/Transformer per horizon slug; shared tabular ingest→overlay→m5 once/tick
  6. Monte Carlo          — monte_carlo.simulate (inside _run_model_stack; horizon bars vary by slug)
  7. Bayesian Fusion      — bayesian_fusion.fuse
  8. Decision Policy       — compute_call (The Call); consumes vol_regime
  9. Risk Engine          — _validate_trade (inside compute_call, after decision)
 10. Position Sizing      — compute_position_size (inside compute_call, after risk)

Rules (Right Now) is computed before Market Regime because regime needs micro structure.
"""
from __future__ import annotations












try:
    from crash_trace import step as _dstep, step_done as _ddone, trace_crash as _dcrash, _on as _don
except ImportError:
    def _don(): return False
    def _dstep(n, t=""): pass
    def _ddone(n, t=""): pass
    def _dcrash(n, e, t=""): pass


# Live LSTM/XGB/TR inference: ml_predict.run_unified_stack_ml_once (single path per tick; Issue 13).


# ══════════════════════════════════════════════════════════════════════════════
# CANONICAL FORECAST (Issue 13 — one decision truth)
# ══════════════════════════════════════════════════════════════════════════════













# ══════════════════════════════════════════════════════════════════════════════
# MODEL STACK RUNNER
# ══════════════════════════════════════════════════════════════════════════════













# ══════════════════════════════════════════════════════════════════════════════
# STACK DECISION PATH
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT DICT (for DB — unchanged contract)
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════



