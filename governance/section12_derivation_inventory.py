"""
Section 12 Schwab-leaf derivation audit inventory (liquidity playbook).

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


SECTION12_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("liquidity_models.py", "39", "zone_class_for_type", "zone taxonomy", "NONE", "Maps ZoneType enum to display class; no market-field reads."),
    DerivationRecord("liquidity_models.py", "75", "Zone.zone_class", "zone taxonomy", "NONE", "Property delegates to zone_class_for_type; no OHLC derivation."),
    DerivationRecord("liquidity_value_engine.py", "36", "_positive_float_or_none", "—", "NONE", "Numeric coercion helper."),
    DerivationRecord("liquidity_value_engine.py", "46", "_float_or_none", "—", "NONE", "Numeric coercion helper."),
    DerivationRecord("liquidity_value_engine.py", "58", "_resolve_bar_timestamp", "pricehistory.candles.datetime", "REPLACED", "Schwab pricehistory bars require datetime leaf; fail-closed when absent (§1 align)."),
    DerivationRecord("liquidity_value_engine.py", "88", "_schwab_pricehistory_bar_missing_datetime", "pricehistory.candles.datetime", "NONE", "Guard helper for missing Schwab datetime; covered by _resolve_bar_timestamp."),
    DerivationRecord("liquidity_value_engine.py", "100", "_bars_to_list", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Normalizes OHLCV bar dicts/DataFrame via _resolve_bar_timestamp."),
    DerivationRecord("liquidity_value_engine.py", "191", "_bar_dt_et", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("liquidity_value_engine.py", "203", "merge_schwab_bars_with_live_overlay", "pricehistory.candles.* + live overlay", "KEEP_DERIVED", "Merges normalized Schwab history bars with live overlay by timestamp."),
    DerivationRecord("liquidity_value_engine.py", "238", "get_previous_day_levels", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "279", "get_overnight_levels", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "317", "compute_opening_range", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "351", "compute_session_vwap", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "370", "compute_vwap_bands", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "402", "_filter_rth_bars", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Session level/zone math on normalized bars."),
    DerivationRecord("liquidity_value_engine.py", "421", "_volume_profile_poc_vah_val", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Session level/zone math on normalized bars."),
    DerivationRecord("liquidity_value_engine.py", "473", "compute_volume_profile_levels", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "490", "compute_atr_from_bars", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "547", "cluster_price_levels_into_zones", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Derives liquidity/structure levels from normalized OHLCV bars."),
    DerivationRecord("liquidity_value_engine.py", "583", "cluster_price_levels_into_zones._flush_current", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("liquidity_value_engine.py", "618", "_cutoff_for_snapshot", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Session level/zone math on normalized bars."),
    DerivationRecord("liquidity_value_engine.py", "638", "build_premarket_snapshot", "OHLCV bars", "KEEP_DERIVED", "Structural snapshot builder from normalized session bars."),
    DerivationRecord("liquidity_value_engine.py", "734", "build_opening_snapshot", "OHLCV bars", "KEEP_DERIVED", "Structural snapshot builder from normalized session bars."),
    DerivationRecord("liquidity_value_engine.py", "832", "build_midday_snapshot", "OHLCV bars", "KEEP_DERIVED", "Structural snapshot builder from normalized session bars."),
    DerivationRecord("liquidity_value_engine.py", "950", "build_afternoon_snapshot", "OHLCV bars", "KEEP_DERIVED", "Structural snapshot builder from normalized session bars."),
    DerivationRecord("liquidity_value_engine.py", "1068", "_last_rth_close_price", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Session level/zone math on normalized bars."),
    DerivationRecord("liquidity_value_engine.py", "1082", "_classify_live_cluster", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Session level/zone math on normalized bars."),
    DerivationRecord("liquidity_value_engine.py", "1111", "build_live_snapshot", "OHLCV bars", "KEEP_DERIVED", "Structural snapshot builder from normalized session bars."),
    DerivationRecord("liquidity_value_engine.py", "1295", "summarize_snapshot", "SnapshotOutput", "NONE", "Human-readable summary of snapshot output."),
    DerivationRecord("liquidity_value_engine.py", "1316", "generate_liquidity_value_snapshot", "OHLCV bars", "KEEP_DERIVED", "Public snapshot entry; structural levels from normalized bars."),
    DerivationRecord("liquidity_value_engine.py", "1368", "generate_playbook_state", "OHLCV bars", "KEEP_DERIVED", "Full-session playbook from checkpoint snapshots on bars."),
    DerivationRecord("liquidity_value_engine.py", "1438", "playbook_state_to_dict", "SnapshotOutput", "NONE", "Serializes PlaybookState dataclass; no market derivation."),
    DerivationRecord("liquidity_value_engine.py", "1441", "playbook_state_to_dict._snap_to_dict", "bars.open|high|low|close|volume", "KEEP_DERIVED", "Bar-based liquidity/value derivation."),
    DerivationRecord("print_liquidity_value_snapshot.py", "40", "_fetch_bars_from_schwab", "pricehistory.candles.*", "PASS_THROUGH", "CLI fetches session bars via polling_adapter; engine consumes normalized bars."),
    DerivationRecord("print_liquidity_value_snapshot.py", "65", "_snapshot_to_dict", "SnapshotOutput", "NONE", "JSON serialization helper for CLI output."),
    DerivationRecord("print_liquidity_value_snapshot.py", "100", "main", "—", "NONE", "CLI entrypoint; delegates bar fetch then engine."),
    DerivationRecord("run_liquidity_sample.py", "17", "main", "—", "NONE", "Sample harness CLI; delegates to print helper and engine."),
)

SECTION12_FILES = frozenset({
    "liquidity_models.py",
    "liquidity_value_engine.py",
    "print_liquidity_value_snapshot.py",
    "run_liquidity_sample.py",
})

