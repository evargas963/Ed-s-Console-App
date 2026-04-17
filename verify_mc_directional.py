#!/usr/bin/env python3
"""
Verification: Monte Carlo directional responsiveness to pre-fusion model blend.

Runs one live cycle for SPY, QQQ, MSFT. Captures pre-fusion blend passed into MC
and compares MC output (containment, expansion, bands) to model direction.

Answers:
  - Is MC now directionally responsive (drift/bands reflect model direction)?
  - Does MC still look miscalibrated?
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Global capture: last MC simulate call's model inputs (set per ticker by patch)
_mc_capture = {"model_prob_up": None, "model_prob_down": None, "model_confidence": None}


def _fmt(v):
    if v is None:
        return "None"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}" if abs(v) < 1 else f"{v:.2f}"
    return str(v)


def _report_ticker(ticker: str, state: dict, mc_cap: dict):
    """One clean per-ticker report."""
    d = state
    spot = d.get("spot") or d.get("spot_f") or 0
    prob_up = mc_cap.get("model_prob_up")
    prob_down = mc_cap.get("model_prob_down")
    mc_conf = mc_cap.get("model_confidence")
    mc_exp = d.get("mc_expansion")
    mc_cont = d.get("mc_containment")
    mc_u50 = d.get("mc_upper_50")
    mc_l50 = d.get("mc_lower_50")

    print(f"\n{'='*70}")
    print(f"  {ticker}")
    print(f"{'='*70}")
    print("  Models (from fusion/predictive stack):")
    print(f"    xgb_dominant={_fmt(d.get('xgb_dominant'))}  xgb_confidence={_fmt(d.get('xgb_confidence'))}")
    print(f"    lstm_dominant={_fmt(d.get('lstm_dominant'))}  lstm_confidence={_fmt(d.get('lstm_confidence'))}")
    print(f"    transformer_dominant={_fmt(d.get('transformer_dominant'))}  transformer_confidence={_fmt(d.get('transformer_confidence'))}")
    print("  Pre-fusion blend (passed into MC):")
    print(f"    model_prob_up={_fmt(prob_up)}  model_prob_down={_fmt(prob_down)}  model_confidence={_fmt(mc_conf)}")
    print("  Monte Carlo output:")
    print(f"    mc_expansion={_fmt(mc_exp)}  mc_containment={_fmt(mc_cont)}")
    print(f"    mc_upper_50={_fmt(mc_u50)}  mc_lower_50={_fmt(mc_l50)}")

    # Directional consistency check
    if spot and mc_u50 is not None and mc_l50 is not None and prob_up is not None and prob_down is not None:
        up_range = mc_u50 - spot
        down_range = spot - mc_l50
        net_model = prob_up - prob_down
        # Model says up > down → expect upper band farther (or containment lower if breakout regime)
        print("  Directional check:")
        print(f"    model net (up-down) = {net_model:+.3f}")
        print(f"    MC upper range = {up_range:.2f}  MC lower range = {down_range:.2f}")
        if net_model > 0.05 and up_range > down_range * 1.1:
            print(f"    => MC bands lean UP (consistent with model)")
        elif net_model < -0.05 and down_range > up_range * 1.1:
            print(f"    => MC bands lean DOWN (consistent with model)")
        elif abs(net_model) < 0.05:
            print(f"    => Model neutral; MC asymmetry reflects vol/regime")
        else:
            print(f"    => MC asymmetry not clearly aligned with model direction")

    print()


def main():
    try:
        import monte_carlo
        _real_simulate = monte_carlo.simulate

        def _capturing_simulate(*args, **kwargs):
            _mc_capture["model_prob_up"] = kwargs.get("model_prob_up")
            _mc_capture["model_prob_down"] = kwargs.get("model_prob_down")
            _mc_capture["model_confidence"] = kwargs.get("model_confidence")
            return _real_simulate(*args, **kwargs)
    except ImportError as e:
        print(f"ERROR: Cannot import monte_carlo: {e}")
        sys.exit(1)

    try:
        from server import _fetch_state
    except ImportError as e:
        print(f"ERROR: Cannot import server: {e}")
        print("Run from project root: python verify_mc_directional.py")
        sys.exit(1)

    from unittest.mock import patch

    tickers = ["SPY", "QQQ", "MSFT"]
    results = []

    with patch("monte_carlo.simulate", side_effect=_capturing_simulate):
        for ticker in tickers:
            try:
                _mc_capture["model_prob_up"] = _mc_capture["model_prob_down"] = _mc_capture["model_confidence"] = None
                print(f"Fetching {ticker}...", flush=True)
                state = _fetch_state(ticker, expiry=None)
                cap = dict(_mc_capture)
                results.append((ticker, state, cap))
            except Exception as e:
                print(f"ERROR for {ticker}: {e}")
                import traceback
                traceback.print_exc()
                results.append((ticker, {}, dict(_mc_capture)))

    # Per-ticker reports
    for ticker, state, cap in results:
        _report_ticker(ticker, state, cap)

    # Summary
    print("=" * 70)
    print("  SUMMARY: MC DIRECTIONAL RESPONSIVENESS")
    print("=" * 70)

    n_with_blend = sum(1 for _, _, cap in results if cap.get("model_prob_up") is not None)
    n_mc_ok = sum(1 for _, s, _ in results if s.get("mc_upper_50") is not None)
    print(f"  Pre-fusion blend reaching MC: {n_with_blend}/{len(tickers)} tickers")
    print(f"  MC producing bands: {n_mc_ok}/{len(tickers)} tickers")

    if n_with_blend == len(tickers):
        print("  => MC is NOW wired to live model blend (pre-fusion XGB+LSTM+Transformer)")
    else:
        print("  => Some tickers lacked model blend (models unavailable?)")

    # Miscalibration signal
    all_symmetric = True
    for ticker, state, cap in results:
        spot = state.get("spot") or state.get("spot_f")
        u50, l50 = state.get("mc_upper_50"), state.get("mc_lower_50")
        if spot and u50 and l50:
            up_r, down_r = u50 - spot, spot - l50
            if abs(up_r - down_r) > 0.5:
                all_symmetric = False
                break

    print()
    if n_with_blend > 0:
        print("  DIRECTIONAL RESPONSIVENESS:")
        print("  - If model_prob_up > model_prob_down and MC upper band range > lower,")
        print("    MC is directionally responsive.")
        print("  - Drift scaling: high conf=1.0, medium=0.6, low=0.2.")
    print()
    print("  MISCALIBRATION:")
    print("  - Compare mc_containment vs realized price action over time.")
    print("  - If containment/expansion often wrong, MC may need calibration.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
