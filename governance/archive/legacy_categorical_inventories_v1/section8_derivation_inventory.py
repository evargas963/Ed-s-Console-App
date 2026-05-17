"""
Section 8 Schwab-leaf derivation audit inventory (MC + regime + volatility).

One row per ``def`` (module, class method, nested helper).
Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION8_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("monte_carlo.py", "91", "MonteCarloOutput.mc_feature_dict", "derived MC features", "KEEP_DERIVED", "MC feature dict for fusion; not quote fields."),
    DerivationRecord("monte_carlo.py", "103", "_blend_sigma", "iv,realized_vol,atr,spot", "KEEP_DERIVED", "Sigma blend; inputs from Schwab-first chain/candles upstream."),
    DerivationRecord("monte_carlo.py", "127", "_compute_drift", "regime, confidence", "KEEP_DERIVED", "Drift from regime + model confidence; not a Schwab leaf."),
    DerivationRecord("monte_carlo.py", "145", "simulate", "iv,realized_vol,atr,spot (upstream)", "KEEP_DERIVED", "MC paths from upstream vol/spot; no Schwab wire ingest."),
    DerivationRecord("monte_carlo.py", "377", "_fallback", "—", "NONE", "MC fallback error payload."),
    DerivationRecord("mc_fusion_adjustment.py", "18", "normalize_mc", "MC output dict", "KEEP_DERIVED", "Normalizes MC output relative to spot."),
    DerivationRecord("mc_fusion_adjustment.py", "52", "_triplet", "probability math", "NONE", "Pure probability blending helper."),
    DerivationRecord("mc_fusion_adjustment.py", "60", "_argmax_dir", "probability math", "NONE", "Pure probability blending helper."),
    DerivationRecord("mc_fusion_adjustment.py", "64", "_blend_uniform", "probability math", "NONE", "Pure probability blending helper."),
    DerivationRecord("mc_fusion_adjustment.py", "74", "_max_uniform_blend_preserving_argmax", "probability math", "NONE", "Pure probability blending helper."),
    DerivationRecord("mc_fusion_adjustment.py", "95", "_add_to_flat_from_others", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("mc_fusion_adjustment.py", "105", "_add_to_flat_from_others.pool_order", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("mc_fusion_adjustment.py", "132", "_max_tail_flat_delta", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("mc_fusion_adjustment.py", "151", "_apply_directional_bias", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("mc_fusion_adjustment.py", "184", "apply_mc_adjustment", "fusion triplets + MC features", "KEEP_DERIVED", "Blends MC path features into fusion probabilities."),
    DerivationRecord("mc_fusion_adjustment.py", "236", "fuse_payload_apply_mc_adjustment", "fusion payload", "KEEP_DERIVED", "Applies MC adjustment on fusion payload object."),
    DerivationRecord("volatility_regime.py", "56", "classify_volatility_regime", "SignalInput vol fields", "KEEP_DERIVED", "Vol policy from rv/iv/atr/vix upstream fields."),
    DerivationRecord("volatility_regime.py", "222", "_f", "—", "NONE", "Scoring/helper; no new market-field derivation."),
    DerivationRecord("regime_engine.py", "95", "_micro_regimes", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "116", "_score_pinning", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "160", "_score_acceleration", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "206", "_score_breakout", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "242", "_score_mean_reversion", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "276", "_score_vol_compression", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "313", "_score_vol_expansion", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "346", "_score_trend_continuation", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "379", "_score_reversal_prone", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
    DerivationRecord("regime_engine.py", "434", "classify_regime", "SignalInput + RulesCard", "KEEP_DERIVED", "8-family regime from upstream levels/greeks/zone."),
    DerivationRecord("regime_engine.py", "534", "_unknown_regime", "upstream SignalInput / vol leaves", "KEEP_DERIVED", "MC/regime metric from upstream Schwab-first inputs."),
)

SECTION8_FILES = frozenset({
    "monte_carlo.py",
    "mc_fusion_adjustment.py",
    "volatility_regime.py",
    "regime_engine.py",
})

