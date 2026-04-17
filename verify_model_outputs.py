#!/usr/bin/env python3
"""
Verification: Run one live MarketState cycle for SPY, QQQ, MSFT
and print model outputs to confirm approval bypass is working.
"""
import sys
import os

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fmt(v):
    if v is None:
        return "None"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}" if abs(v) < 1 else f"{v:.2f}"
    return str(v)


def print_ticker(state: dict, ticker: str):
    d = state
    print(f"\n{'='*60}")
    print(f"Ticker: {ticker}")
    print(f"{'='*60}")
    print(f"XGBoost:     available={_fmt(d.get('xgb_available'))} dominant={_fmt(d.get('xgb_dominant'))} "
          f"confidence={_fmt(d.get('xgb_confidence'))} approved={_fmt(d.get('xgb_approved'))}")
    print(f"LSTM:         available={_fmt(d.get('lstm_available'))} dominant={_fmt(d.get('lstm_dominant'))} "
          f"confidence={_fmt(d.get('lstm_confidence'))} approved={_fmt(d.get('lstm_approved'))}")
    print(f"Transformer:  available={_fmt(d.get('transformer_available'))} dominant={_fmt(d.get('transformer_dominant'))} "
          f"confidence={_fmt(d.get('transformer_confidence'))} approved={_fmt(d.get('transformer_approved'))}")
    print(f"Fusion:       dominant={_fmt(d.get('fusion_dominant'))} dominant_prob={_fmt(d.get('fusion_dominant_prob'))} "
          f"model_agreement={_fmt(d.get('fusion_model_agreement'))}")
    print(f"Fusion Dir:   up={_fmt(d.get('fusion_prob_up'))} down={_fmt(d.get('fusion_prob_down'))} "
          f"flat={_fmt(d.get('fusion_prob_flat'))} dominant_dir={_fmt(d.get('fusion_dominant_direction'))}")
    print(f"Monte Carlo:  expansion={_fmt(d.get('mc_expansion'))} containment={_fmt(d.get('mc_containment'))} "
          f"upper_50={_fmt(d.get('mc_upper_50'))} lower_50={_fmt(d.get('mc_lower_50'))}")


def main():
    try:
        from server import _fetch_state
    except ImportError as e:
        print(f"ERROR: Cannot import server: {e}")
        print("Run from project root with: python verify_model_outputs.py")
        sys.exit(1)

    tickers = ["SPY", "QQQ", "MSFT"]
    for ticker in tickers:
        try:
            print(f"\nFetching {ticker}...", flush=True)
            state = _fetch_state(ticker, expiry=None)
            print_ticker(state, ticker)
        except Exception as e:
            print(f"\nERROR for {ticker}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    print("If xgb_available, lstm_available, transformer_available are True")
    print("with real dominant/confidence values, the WHAT THE DATA SAYS card")
    print("will render real values instead of INACTIVE.")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
