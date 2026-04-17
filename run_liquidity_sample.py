"""
Run Liquidity Map payload for all four snapshots (SPY 2026-03-13).
Uses real Schwab data. Run from terminal: python run_liquidity_sample.py
"""
import json
import sys
from pathlib import Path

APP_DIR = str(Path(__file__).parent.resolve())
sys.path.insert(0, APP_DIR)

from print_liquidity_value_snapshot import _fetch_bars_from_schwab
from liquidity_value_engine import generate_liquidity_value_snapshot
from liquidity_models import SnapshotType, PlaybookConfig
from server import _build_raw_levels_used

def main():
    print("Fetching SPY bars for 2026-03-13 from Schwab...")
    bars = _fetch_bars_from_schwab("SPY", "2026-03-13")
    cfg = PlaybookConfig(clustering_mode="percent", max_zone_width=2.0)

    for st in ["premarket", "opening", "midday", "afternoon"]:
        out = generate_liquidity_value_snapshot(
            "SPY", bars, "2026-03-13", SnapshotType(st), cfg
        )
        payload = {
            "snapshot_type": out.snapshot_type.value,
            "ticker": out.ticker,
            "session_date": out.session_date,
            "zones": [],
            "summary": None,
            "raw_levels_used": _build_raw_levels_used(
                out.raw_levels, out.snapshot_type.value
            ),
        }
        for z in out.zones:
            payload["zones"].append({
                "zone_type": z.zone_type.value,
                "zone_class": z.zone_class,
                "zone_low": z.zone_low,
                "zone_high": z.zone_high,
                "zone_mid": z.zone_mid,
                "zone_width": round(z.zone_high - z.zone_low, 4),
                "confluence_score": z.confluence_score,
                "source_tags": z.source_tags,
                "source_levels": z.source_levels,
                "interpretation_notes": z.interpretation_notes or "",
            })
        if out.summary:
            payload["summary"] = {
                "value_state": out.summary.value_state,
                "vwap_relation": out.summary.vwap_relation,
                "auction_interpretation": out.summary.auction_interpretation,
                "notes": out.summary.notes,
            }
        print("\n" + "=" * 70)
        print(f"SNAPSHOT: {st.upper()}")
        print("=" * 70)
        print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
