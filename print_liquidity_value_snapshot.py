"""
print_liquidity_value_snapshot.py
CLI to generate liquidity & value playbook snapshots.

Snapshot cutoffs (exact checkpoint times, no lookahead):
  premarket  — before 09:30 ET
  opening    — data through 09:45:00 ET
  midday     — data through 10:30:00 ET
  afternoon  — data through 14:00:00 ET

Usage:
  python print_liquidity_value_snapshot.py --ticker SPY --date 2026-03-13 --snapshot premarket
  python print_liquidity_value_snapshot.py --ticker QQQ --date 2026-03-13 --snapshot opening
  python print_liquidity_value_snapshot.py --ticker SPY --date 2026-03-13 --snapshot midday
  python print_liquidity_value_snapshot.py --ticker SPY --date 2026-03-13 --snapshot afternoon
  python print_liquidity_value_snapshot.py --ticker SPY --playbook-state
    (outputs full PlaybookState with all four snapshots)

  python print_liquidity_value_snapshot.py --snapshot premarket
    (uses default ticker from config.DEFAULT_TICKER and today's date)

Data source: Schwab price history (1-min bars). Requires schwab_token.json and config.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_DIR = str(Path(__file__).parent.resolve())
sys.path.insert(0, APP_DIR)

from config import DEFAULT_TICKER  # single authority — no shadowing local "SPY" fallback


def _fetch_bars_from_schwab(ticker: str, session_date_str: str) -> list[dict]:
    """Fetch OHLCV bars via Schwab API for the given session (uses start/end for date alignment)."""
    from datetime import date
    from config import build_config
    from schwab_client import build_client_from_token
    from polling_adapter import fetch_bars_via_schwab_for_session

    cfg = build_config(APP_DIR)
    state = build_client_from_token(
        api_key=cfg.api_key,
        app_secret=cfg.app_secret,
        token_path=cfg.token_path,
    )
    if not state.ok or state.client is None:
        raise RuntimeError(f"Schwab auth failed: {state.message}")

    session_date = date.fromisoformat(session_date_str)
    return fetch_bars_via_schwab_for_session(
        state.client,
        symbol=ticker,
        session_date=session_date,
        include_extended_hours=True,
    )


def _snapshot_to_dict(out) -> dict:
    """Convert SnapshotOutput to JSON-serializable dict."""

    d = {
        "ticker": out.ticker,
        "session_date": out.session_date,
        "snapshot_type": out.snapshot_type.value,
        "zones": [],
        "summary": None,
        "raw_levels": out.raw_levels,
    }
    for z in out.zones:
        d["zones"].append({
            "zone_type": z.zone_type.value,
            "zone_class": z.zone_class,
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "zone_mid": z.zone_mid,
            "zone_width": round(z.zone_high - z.zone_low, 4),
            "source_levels": z.source_levels,
            "source_tags": z.source_tags,
            "confluence_score": z.confluence_score,
            "interpretation_notes": z.interpretation_notes or "",
        })
    if out.summary:
        d["summary"] = {
            "value_state": out.summary.value_state,
            "vwap_relation": out.summary.vwap_relation,
            "auction_interpretation": out.summary.auction_interpretation,
            "notes": out.summary.notes,
        }
    return d


def main():
    parser = argparse.ArgumentParser(
        description="Generate liquidity & value playbook snapshot for a ticker/session.",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default=DEFAULT_TICKER,
        help=f"Ticker symbol (default from config: {DEFAULT_TICKER})",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Session date YYYY-MM-DD (default: today ET)",
    )
    parser.add_argument(
        "--snapshot",
        type=str,
        choices=["premarket", "opening", "midday", "afternoon"],
        default="premarket",
        help="Structural snapshot type. Cutoffs: premarket=before 09:30, opening=through 09:45, midday=through 10:30, afternoon=through 14:00 ET",
    )
    parser.add_argument(
        "--playbook-state",
        action="store_true",
        help="Generate full PlaybookState (all four snapshots) instead of single snapshot",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable summary",
    )
    parser.add_argument(
        "--bars-file",
        type=str,
        default=None,
        help="Optional: load bars from JSON file (for backtest); overrides Schwab fetch",
    )
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    session_date = args.date
    if not session_date:
        from time_et import now_et

        session_date = now_et().strftime("%Y-%m-%d")

    # Load bars
    if args.bars_file:
        with open(args.bars_file, "r") as f:
            bars = json.load(f)
    else:
        try:
            bars = _fetch_bars_from_schwab(ticker, session_date)
        except Exception as e:
            print(f"❌ Failed to fetch bars: {e}", file=sys.stderr)
            sys.exit(1)

    if not bars:
        print(f"⚠️  No bar data for {ticker} on {session_date}.", file=sys.stderr)
        sys.exit(1)

    from liquidity_models import SnapshotType, PlaybookConfig

    try:
        if args.playbook_state:
            from liquidity_value_engine import generate_playbook_state, playbook_state_to_dict

            state = generate_playbook_state(
                ticker=ticker,
                bars_dataframe=bars,
                session_date=session_date,
                config=PlaybookConfig(clustering_mode="percent", max_zone_width=2.0),
            )
            if args.json:
                print(json.dumps(playbook_state_to_dict(state), indent=2))
            else:
                print(f"PlaybookState: {state.ticker} {state.session_date}")
                print(f"Latest: {state.latest_snapshot_type.value if state.latest_snapshot_type else '—'}")
                print(f"Session bias: {state.session_bias or '—'}")
                print()
                print("--- Full JSON ---")
                print(json.dumps(playbook_state_to_dict(state), indent=2))
        else:
            from liquidity_value_engine import generate_liquidity_value_snapshot

            out = generate_liquidity_value_snapshot(
                ticker=ticker,
                bars_dataframe=bars,
                session_date=session_date,
                snapshot_type=SnapshotType(args.snapshot),
                config=PlaybookConfig(clustering_mode="percent", max_zone_width=2.0),
            )
            if args.json:
                print(json.dumps(_snapshot_to_dict(out), indent=2))
            else:
                from liquidity_value_engine import summarize_snapshot

                print(summarize_snapshot(out))
                print()
                print("--- Full JSON ---")
                print(json.dumps(_snapshot_to_dict(out), indent=2))
    except Exception as e:
        print(f"❌ Engine error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
