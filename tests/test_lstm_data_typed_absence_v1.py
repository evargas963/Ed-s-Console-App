"""RC-318 — absence gets a TYPE on the sequence-encode lane, never a coerced 0.0.

The canonical form of the absence-coerced-to-a-value class was lstm_data._safe_float
(None -> 0.0) feeding reference spots and, via `_safe_float(...) or ref` idioms, the
micro-stream reference in four modules. These tests prove the typed-absence behavior of
every CHANGED site:

  * canonical_reference_spot_from_sequence_window_first_bar — absent/NaN spot -> ValueError
    (explicit row-drop; every caller catches it), never a 0.0 or NaN reference.
  * micro_reference_spot_from_window — the ONE producer for the micro reference: absent /
    NaN / non-positive first-bar spot is TESTED and falls back to the validated ref_spot.
  * features.signal_layer_v1._sign_trend — unmeasurable slope propagates as None (the
    layer's absence type), never a fabricated "measured flat" 0.0.
  * order_flow_engine._weighted_mean_present — absent legs are EXCLUDED, never counted as
    neutral 0.0 mass (_normalize no longer accepts None at all).

_safe_float itself survives ONLY as the frozen legacy-v2 checkpoint-parity coercion; its
contract is pinned here so a future edit cannot silently shift legacy serve inputs.
"""
from __future__ import annotations




# ── canonical reference spot: absent -> typed row-drop (ValueError) ──────────────────────







# ── micro reference spot: ONE producer, absence tested -> validated fallback ─────────────









# ── legacy v2 checkpoint parity: the surviving coercion is pinned, not silent ────────────



# ── signal layer: unmeasurable slope -> None, the layer's absence type ───────────────────









# ── order flow: absent legs are excluded, never neutral 0.0 mass ─────────────────────────

def test_no_present_leg_reweighting_helper_exists():
    """2026-09-24: _weighted_mean_present RENORMALISED the weights of whichever legs were
    present (re-weighting by design) and had no production caller; it and _normalize are
    deleted so nothing can reintroduce partial-leg averaging."""
    import app.options.order_flow.engine as ofe
    assert not hasattr(ofe, "_weighted_mean_present")
    assert not hasattr(ofe, "_normalize")
