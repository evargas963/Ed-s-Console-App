"""
compare_clustering_modes.py — Compare percent, fixed, and ATR clustering modes
==============================================================================
Runs the Liquidity & Value Playbook Engine for a real Friday session and
generates outputs for all three clustering modes for side-by-side comparison.

Usage:
  python compare_clustering_modes.py
  python compare_clustering_modes.py --date 2025-03-07
  python compare_clustering_modes.py --bars-file path/to/bars.json

Requires: Schwab auth (schwab_token.json) for live data fetch, or --bars-file for historical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from time_et import ET, RTH_END_MINS, RTH_SESSION_MINUTES, RTH_START_MINS, now_et

APP_DIR = str(Path(__file__).parent.resolve())

# OBS-CLUSTER-RANK-1: clustering-rank floor for the "no zones produced" outcome.
# This is an integer rank sentinel (lower score = worse ranking) used by
# _recommend_default_clustering to sort modes against each other. NOT the same
# semantic as MISSING_GREEK_SENTINEL (which is a float Schwab-missing-greek
# placeholder) — kept distinct so the two never alias.
CLUSTERING_RANK_NO_ZONES_FLOOR: int = -999
sys.path.insert(0, APP_DIR)


def _synthetic_bars_for_session(session_date) -> list[dict]:
    """Generate synthetic bars for a Friday session (Thu prev + Fri today + overnight)."""
    from datetime import timedelta
    bars = []
    base = 580.0
    prev_date = session_date - timedelta(days=1)
    # Skip back to get a weekday
    while prev_date.weekday() >= 5:
        prev_date -= timedelta(days=1)

    def _mk(dt, o, h, l, c, v=1000):
        return {"timestamp": int(dt.timestamp() * 1000), "_ts": dt.timestamp(),
                "open": o, "high": h, "low": l, "close": c, "volume": v}

    # Prev day cash RTH [open, close)
    for i in range(int(RTH_SESSION_MINUTES)):
        m = int(RTH_START_MINS) + i
        dt = __import__("datetime").datetime(prev_date.year, prev_date.month, prev_date.day,
                                             m // 60, m % 60, tzinfo=ET)
        p = base + (i % 40) - 20
        bars.append(_mk(dt, p, p + 0.4, p - 0.4, p))
    # Overnight: prev RTH close–24:00, today 00:00–RTH open
    for h in range(int(RTH_END_MINS) // 60, 24):
        for m in range(0, 60, 5):
            dt = __import__("datetime").datetime(prev_date.year, prev_date.month, prev_date.day, h, m, tzinfo=ET)
            p = base - 2 + (h + m) % 10
            bars.append(_mk(dt, p, p + 0.2, p - 0.2, p, 200))
    for h in range(0, 10):
        for m in range(0, 60, 5):
            dt = __import__("datetime").datetime(session_date.year, session_date.month, session_date.day, h, m, tzinfo=ET)
            p = base - 1 + (h + m) % 8
            bars.append(_mk(dt, p, p + 0.2, p - 0.2, p, 200))
    # Today RTH open onward (through 14:30 for afternoon snapshot — not full session)
    for i in range(360):
        m = int(RTH_START_MINS) + i
        dt = __import__("datetime").datetime(session_date.year, session_date.month, session_date.day,
                                             m // 60, m % 60, tzinfo=ET)
        p = base + (i % 35) - 17
        bars.append(_mk(dt, p, p + 0.35, p - 0.35, p, 800))
    return bars


def _fetch_bars(ticker: str, session_date_str: str, session_date_obj) -> list[dict]:
    """Fetch OHLCV bars via Schwab API for the given session (uses start/end for date alignment)."""
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
    return fetch_bars_via_schwab_for_session(
        state.client, symbol=ticker, session_date=session_date_obj, include_extended_hours=True
    )


def _format_raw_levels_by_source(rl: dict, snapshot_type: str) -> dict:
    """Group raw levels by source category for display."""
    out = {}
    prev = rl.get("prev_day") or rl.get("prev") or {}
    if prev:
        out["previous_day"] = {k: v for k, v in prev.items() if v is not None and isinstance(v, (int, float))}
    overnight = rl.get("overnight") or {}
    if overnight:
        out["overnight"] = dict(overnight)
    orb = rl.get("orb") or {}
    if orb:
        out["opening_range"] = dict(orb)
    vwap = rl.get("vwap")
    vwap_bands = rl.get("vwap_bands") or {}
    if vwap is not None or vwap_bands:
        out["vwap_and_bands"] = {"vwap": vwap}
        if vwap_bands:
            out["vwap_and_bands"].update(vwap_bands)
    poc = rl.get("poc")
    vah = rl.get("vah")
    val = rl.get("val")
    if poc is not None or vah is not None or val is not None:
        out["current_day_profile"] = {}
        if vah is not None:
            out["current_day_profile"]["TODAY_VAH"] = vah
        if vwap is not None and snapshot_type in ("opening", "midday", "afternoon"):
            out["current_day_profile"]["VWAP"] = vwap
        if poc is not None:
            out["current_day_profile"]["TODAY_POC"] = poc
        if val is not None:
            out["current_day_profile"]["TODAY_VAL"] = val
    return out


def _run_snapshot(ticker: str, bars: list, session_date, snapshot_type: str, config) -> dict:
    """Run a single snapshot and return full result with raw levels, clustering settings, zones."""
    from liquidity_value_engine import (
        build_premarket_snapshot,
        build_opening_snapshot,
        build_midday_snapshot,
        build_afternoon_snapshot,
        _cutoff_for_snapshot,
        compute_atr_from_bars,
    )
    from liquidity_models import SnapshotType

    st = SnapshotType(snapshot_type)
    if st == SnapshotType.PREMARKET:
        out = build_premarket_snapshot(ticker, bars, session_date, config)
    elif st == SnapshotType.OPENING:
        out = build_opening_snapshot(ticker, bars, session_date, config)
    elif st == SnapshotType.MIDDAY:
        out = build_midday_snapshot(ticker, bars, session_date, config)
    else:
        out = build_afternoon_snapshot(ticker, bars, session_date, config)

    cutoff = _cutoff_for_snapshot(st, session_date)
    atr_val = (
        compute_atr_from_bars(bars, session_date, cutoff, config.atr_period)
        if config.clustering_mode == "atr"
        else None
    )
    ref = 500.0
    rl = out.raw_levels
    prev = rl.get("prev_day") or rl.get("prev") or {}
    ref = prev.get("pd_poc") or prev.get("pdc") or 500.0
    if rl.get("poc") is not None:
        ref = rl["poc"]
    elif rl.get("orb"):
        ref = rl["orb"].get("orb_mid") or ref

    # Compute effective threshold
    if config.clustering_mode == "percent":
        thresh = ref * config.clustering_threshold_pct
    elif config.clustering_mode == "fixed" and config.clustering_threshold > 0:
        thresh = config.clustering_threshold
    elif config.clustering_mode == "atr" and atr_val:
        thresh = atr_val * config.clustering_threshold_atr_mult
    else:
        thresh = ref * config.clustering_threshold_pct

    clustering_settings = {
        "clustering_mode": config.clustering_mode,
        "effective_threshold": round(thresh, 4),
        "reference_price": round(ref, 4),
        "atr_value": round(atr_val, 4) if atr_val is not None else None,
        "atr_multiplier": config.clustering_threshold_atr_mult if config.clustering_mode == "atr" else None,
        "fixed_threshold": config.clustering_threshold if config.clustering_mode == "fixed" else None,
        "percent_threshold": config.clustering_threshold_pct if config.clustering_mode == "percent" else None,
    }

    zones = []
    for z in out.zones:
        w = z.zone_high - z.zone_low
        zones.append({
            "zone_type": z.zone_type.value,
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "zone_mid": z.zone_mid,
            "zone_width": round(w, 4),
            "source_tags": z.source_tags,
            "confluence_score": z.confluence_score,
            "merged_levels_count": len(z.source_tags),
            "interpretation_notes": z.interpretation_notes or "",
        })

    summary = None
    if out.summary:
        summary = {
            "value_state": out.summary.value_state,
            "vwap_relation": out.summary.vwap_relation,
            "auction_interpretation": out.summary.auction_interpretation,
        }

    return {
        "snapshot_type": snapshot_type,
        "raw_levels": out.raw_levels,
        "raw_levels_grouped": _format_raw_levels_by_source(out.raw_levels, snapshot_type),
        "clustering_settings": clustering_settings,
        "zones": zones,
        "summary": summary,
        "total_zones": len(zones),
    }


def _zone_diagnostics(zones: list) -> dict:
    """Compute zone diagnostics including overly broad detection."""
    if not zones:
        return {
            "total_zones": 0,
            "avg_width": 0.0,
            "widest_zone": 0.0,
            "tightest_zone": 0.0,
            "merged_per_zone": [],
            "overly_broad_zones": [],
        }
    widths = [z["zone_width"] for z in zones]
    avg_w = sum(widths) / len(widths)
    overly_broad = []
    for i, z in enumerate(zones):
        if avg_w > 0 and z["zone_width"] > 2.0 * avg_w:
            overly_broad.append({
                "index": i + 1,
                "zone_low": z["zone_low"],
                "zone_high": z["zone_high"],
                "zone_width": z["zone_width"],
                "merged_count": z["merged_levels_count"],
            })
    return {
        "total_zones": len(zones),
        "avg_width": round(sum(widths) / len(widths), 4),
        "widest_zone": round(max(widths), 4),
        "tightest_zone": round(min(widths), 4),
        "merged_per_zone": [z["merged_levels_count"] for z in zones],
        "overly_broad_zones": overly_broad,
    }


def _recommend_default_clustering(results: dict, snapshot_types: list) -> str:
    """Recommend default clustering mode from real-data comparison."""
    modes = ["percent", "fixed", "atr"]
    scores = {}
    for mode in modes:
        all_zones = []
        for st in snapshot_types:
            all_zones.extend(results[mode][st]["zones"])
        if not all_zones:
            scores[mode] = CLUSTERING_RANK_NO_ZONES_FLOOR
            continue
        diag = _zone_diagnostics(all_zones)
        # Prefer: moderate zone count (not too fragmented), tight widths, few overly broad
        zone_count = len(all_zones)
        avg_width = diag["avg_width"]
        over_broad = len(diag["overly_broad_zones"])
        # Penalize fragmentation (>15 zones), penalize wide zones, penalize over-merge
        score = 0
        if 8 <= zone_count <= 14:
            score += 2
        elif zone_count < 8:
            score += 1
        if avg_width < 0.5:
            score += 2
        elif avg_width < 1.0:
            score += 1
        score -= over_broad
        scores[mode] = score
    best = max(modes, key=lambda m: scores[m])
    return best


def _final_assessment(results: dict, snapshot_types: list) -> str:
    """Generate final comparative assessment."""
    lines = []
    modes = ["percent", "fixed", "atr"]

    # Cleanest institutional map
    zone_counts = {}
    for mode in modes:
        zone_counts[mode] = sum(
            len(results[mode][st]["zones"]) for st in snapshot_types
        )
    min_zones = min(zone_counts.values())
    max_zones = max(zone_counts.values())
    cleanest = [m for m in modes if zone_counts[m] == min_zones][0] if min_zones != max_zones else modes[0]
    lines.append(f"* Cleanest institutional map: {cleanest} ({zone_counts[cleanest]} total zones across snapshots)")

    # Most tradeable zones
    avg_widths = {}
    for mode in modes:
        all_zones = []
        for st in snapshot_types:
            all_zones.extend(results[mode][st]["zones"])
        if all_zones:
            avg_widths[mode] = sum(z["zone_width"] for z in all_zones) / len(all_zones)
        else:
            avg_widths[mode] = float("inf")
    most_tradeable = min(avg_widths, key=lambda m: avg_widths[m])
    lines.append(f"* Most tradeable zones (tightest avg): {most_tradeable} (avg width {avg_widths[most_tradeable]:.4f})")

    # Too wide
    widest_avg = max(avg_widths.values())
    too_wide = [m for m in modes if avg_widths[m] == widest_avg and widest_avg > 0][0]
    lines.append(f"* Zones too wide: {too_wide} (avg width {avg_widths[too_wide]:.4f})")

    # Best separation
    separation_scores = {}
    for mode in modes:
        over_merged = 0
        for st in snapshot_types:
            diag = _zone_diagnostics(results[mode][st]["zones"])
            over_merged += len(diag["overly_broad_zones"])
        separation_scores[mode] = -over_merged  # fewer over-merged = better
    best_sep = max(separation_scores, key=separation_scores.get)
    lines.append(f"* Best separation (resistance/fair value/support/sweep): {best_sep}")

    return "\n".join(lines)


def main():
    from datetime import date, timedelta
    from liquidity_models import PlaybookConfig

    # Default: most recent Friday (ensure within Schwab's date range)
    now_et_date = now_et().date()
    days_back = 0
    while (now_et_date - timedelta(days=days_back)).weekday() != 4:  # 4 = Friday
        days_back += 1
    session_date_str = (now_et_date - timedelta(days=days_back)).isoformat()
    bars_file = None
    use_synthetic = "--synthetic" in sys.argv
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            session_date_str = sys.argv[idx + 1]
    if "--bars-file" in sys.argv:
        idx = sys.argv.index("--bars-file")
        if idx + 1 < len(sys.argv):
            bars_file = sys.argv[idx + 1]

    session_date = date.fromisoformat(session_date_str)
    prev_date = session_date - timedelta(days=1)
    while prev_date.weekday() >= 5:
        prev_date -= timedelta(days=1)
    prev_date_str = prev_date.isoformat()

    ticker = "SPY"

    if use_synthetic:
        print("Using synthetic bars for session...")
        bars = _synthetic_bars_for_session(session_date)
    elif bars_file:
        print(f"Loading bars from {bars_file}...")
        with open(bars_file, "r") as f:
            bars = json.load(f)
    else:
        print("Fetching bars from Schwab...")
        try:
            bars = _fetch_bars(ticker, session_date_str, session_date)
        except Exception as e:
            print(f"Failed to fetch bars: {e}")
            print("Tip: Use --synthetic for demo data, or --bars-file path/to/bars.json")
            sys.exit(1)

    if not bars:
        print("No bar data returned.")
        sys.exit(1)

    print(f"Loaded {len(bars)} bars for {ticker}")
    print(f"Session date: {session_date_str} (Friday)")
    print(f"Previous trading day: {prev_date_str}")
    print()

    # Configs
    cfg_percent = PlaybookConfig(clustering_mode="percent", clustering_threshold_pct=0.002)
    cfg_fixed = PlaybookConfig(clustering_mode="fixed", clustering_threshold=2.0)
    cfg_atr = PlaybookConfig(clustering_mode="atr", clustering_threshold_atr_mult=1.0)

    snapshot_types = ["premarket", "opening", "midday", "afternoon"]
    results = {
        "percent": {st: _run_snapshot(ticker, bars, session_date, st, cfg_percent) for st in snapshot_types},
        "fixed": {st: _run_snapshot(ticker, bars, session_date, st, cfg_fixed) for st in snapshot_types},
        "atr": {st: _run_snapshot(ticker, bars, session_date, st, cfg_atr) for st in snapshot_types},
    }

    cutoffs = {
        "premarket": "before 09:30 ET",
        "opening": "through 09:45:00 ET",
        "midday": "through 10:30:00 ET",
        "afternoon": "through 14:00:00 ET",
    }

    for st in snapshot_types:
        print("=" * 110)
        print(f"  SNAPSHOT: {st.upper()} - cutoff: {cutoffs[st]}")
        print("=" * 110)

        r_pct = results["percent"][st]
        r_fix = results["fixed"][st]
        r_atr = results["atr"][st]

        # 1. Raw levels grouped by source
        rl = r_pct["raw_levels_grouped"]
        print("\n  -- 1. RAW LEVELS (same for all modes) --")
        for group, vals in rl.items():
            if isinstance(vals, dict):
                print(f"    [{group}]")
                for k, v in vals.items():
                    if v is not None:
                        print(f"      {k}: {v:.4f}" if isinstance(v, (int, float)) else f"      {k}: {v!s}")
            else:
                print(f"    [{group}]: {vals}")

        # 2. Clustering settings
        print("\n  -- 2. CLUSTERING SETTINGS --")
        print("-" * 90)
        print(f"{'Setting':<30} {'PERCENT':<22} {'FIXED':<22} {'ATR':<22}")
        print("-" * 90)
        for key in ["clustering_mode", "effective_threshold", "reference_price", "atr_value",
                    "atr_multiplier", "fixed_threshold", "percent_threshold"]:
            vp = r_pct["clustering_settings"].get(key)
            vf = r_fix["clustering_settings"].get(key)
            va = r_atr["clustering_settings"].get(key)
            sp = str(vp) if vp is not None else "-"
            sf = str(vf) if vf is not None else "-"
            sa = str(va) if va is not None else "-"
            print(f"{key:<30} {sp:<22} {sf:<22} {sa:<22}")

        # 3. Resulting zones per mode
        print("\n  -- 3. RESULTING ZONES --")
        for mode_name, r in [("PERCENT", r_pct), ("FIXED", r_fix), ("ATR", r_atr)]:
            print(f"\n    --- {mode_name} ({len(r['zones'])} zones) ---")
            for i, z in enumerate(r["zones"], 1):
                print(f"      Zone {i}: [{z['zone_type']}]")
                print(f"        zone_low={z['zone_low']:.4f}  zone_high={z['zone_high']:.4f}  zone_mid={z['zone_mid']:.4f}")
                print(f"        zone_width={z['zone_width']:.4f}  confluence={z['confluence_score']}  merged={z['merged_levels_count']}")
                print(f"        source_tags: {z['source_tags']}")
                print(f"        interpretation_notes: {z['interpretation_notes'] or '-'}")

        # 4. Snapshot summary
        print("\n  -- 4. SNAPSHOT SUMMARY --")
        summ = r_pct.get("summary") or r_atr.get("summary") or r_fix.get("summary")
        if summ:
            print(f"    value_state: {summ.get('value_state', '-')}")
            print(f"    vwap_relation: {summ.get('vwap_relation', '-')}")
            print(f"    auction_interpretation: {summ.get('auction_interpretation', '-')}")
        print(f"    total_zones (pct/fix/atr): {r_pct['total_zones']} / {r_fix['total_zones']} / {r_atr['total_zones']}")

        # Side-by-side comparison
        print("\n  -- SIDE-BY-SIDE COMPARISON --")
        print("-" * 90)
        print(f"{'Metric':<35} {'PERCENT':<18} {'FIXED':<18} {'ATR':<18}")
        print("-" * 90)
        print(f"{'Total zones':<35} {r_pct['total_zones']:<18} {r_fix['total_zones']:<18} {r_atr['total_zones']:<18}")
        def _zs(zones):
            if not zones:
                return 0.0, 0.0, 0.0
            w = [z["zone_width"] for z in zones]
            return sum(w) / len(w), max(w), min(w)
        ap, wp, tp = _zs(r_pct["zones"])
        af, wf, tf = _zs(r_fix["zones"])
        aa, wa, ta = _zs(r_atr["zones"])
        print(f"{'Avg zone width':<35} {ap:<18.4f} {af:<18.4f} {aa:<18.4f}")
        print(f"{'Widest zone':<35} {wp:<18.4f} {wf:<18.4f} {wa:<18.4f}")
        print(f"{'Tightest zone':<35} {tp:<18.4f} {tf:<18.4f} {ta:<18.4f}")
        print()

    # Diagnostics per mode
    print("\n" + "=" * 110)
    print("  DIAGNOSTICS BY CLUSTERING MODE")
    print("=" * 110)
    for mode_name, mode_key in [("PERCENT", "percent"), ("FIXED", "fixed"), ("ATR", "atr")]:
        all_zones = []
        for st in snapshot_types:
            all_zones.extend(results[mode_key][st]["zones"])
        diag = _zone_diagnostics(all_zones)
        print(f"\n  {mode_name}:")
        print(f"    Total zones: {diag['total_zones']}")
        print(f"    Avg zone width: {diag['avg_width']}")
        print(f"    Widest zone: {diag['widest_zone']}")
        print(f"    Tightest zone: {diag['tightest_zone']}")
        print(f"    Merged levels per zone: {diag['merged_per_zone'][:20]}{'...' if len(diag['merged_per_zone']) > 20 else ''}")
        if diag["overly_broad_zones"]:
            print(f"    Overly broad zones (>2x avg): {len(diag['overly_broad_zones'])}")
            for ob in diag["overly_broad_zones"][:5]:
                print(f"      Zone {ob['index']}: {ob['zone_low']:.2f}-{ob['zone_high']:.2f} width={ob['zone_width']:.4f} merged={ob['merged_count']}")

    # Final comparative assessment
    print("\n" + "=" * 110)
    print("  FINAL COMPARATIVE ASSESSMENT")
    print("=" * 110)
    print(_final_assessment(results, snapshot_types))

    # Default clustering mode recommendation (real data only)
    if not use_synthetic and not bars_file:
        print("\n  --- DEFAULT CLUSTERING MODE RECOMMENDATION (real Schwab data) ---")
        rec = _recommend_default_clustering(results, snapshot_types)
        print(f"  Recommended default: {rec}")

    # Metadata
    print("\n" + "=" * 110)
    print("  METADATA")
    print("=" * 110)
    print(f"  Session date: {session_date_str}")
    print(f"  Previous trading day: {prev_date_str}")
    print("  Snapshot cutoffs:")
    for k, v in cutoffs.items():
        print(f"    {k}: {v}")
    print("  Files/functions: compare_clustering_modes.py (main, _run_snapshot, _zone_diagnostics)")
    print("  Engine: liquidity_value_engine.py (build_*_snapshot, cluster_price_levels_into_zones)")
    print("  Data source:", "synthetic (--synthetic)" if use_synthetic else "Schwab API" + (" / " + bars_file if bars_file else ""))
    print("  Limitations: Schwab API returns last 5 days; session_date must fall within that window.")
    print("  Assumptions: RTH 09:30-16:00 ET; ORB = first 15 min; ATR period = 14 bars.")
    print()


if __name__ == "__main__":
    main()
