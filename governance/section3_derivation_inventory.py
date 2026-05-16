"""
Section 3 Schwab-leaf derivation audit inventory (source of truth for tests).

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


SECTION3_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("market_context.py", "15", "_positive_float_or_none", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("market_context.py", "25", "_float_or_none", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("market_context.py", "34", "configured_index_futures_symbols", "quotes.*|chains.*|pricehistory.candles.*", "KEEP_DERIVED", "Reads or composes market fields; no single Schwab leaf."),
    DerivationRecord("market_context.py", "114", "market_context_panel_symbols_excluding_core", "quotes.*|pricehistory.candles.*|chains.*", "PASS_THROUGH", "Schwab API or wire JSON ingest path."),
    DerivationRecord("market_context.py", "125", "market_context_panel_symbols_excluding_core.add", "—", "NONE", "Nested set-add helper for symbol list builder."),
    DerivationRecord("market_context.py", "251", "_vix_regime", "quotes.*|chains.*|pricehistory.candles.*", "KEEP_DERIVED", "Reads or composes market fields; no single Schwab leaf."),
    DerivationRecord("market_context.py", "262", "_dot_color", "—", "NONE", "UI presentation helper; no market derivation."),
    DerivationRecord("market_context.py", "270", "_extract_quote", "quotes.quote|extended|regular.lastPrice,netPercentChange", "PASS_THROUGH", "Schwab quote hierarchy; pct from netChange when percent leaf absent."),
    DerivationRecord("market_context.py", "301", "_build_confluence", "constituent quote chg_pct", "KEEP_DERIVED", "Cap-weighted confluence from quote-derived chg_pct inputs."),
    DerivationRecord("market_context.py", "351", "_build_iwm_confluence", "sector quote chg_pct", "KEEP_DERIVED", "IWM sector confluence composite."),
    DerivationRecord("market_context.py", "398", "iwm_blended_participation_push", "quotes.*|chains.*|pricehistory.candles.*", "KEEP_DERIVED", "Reads or composes market fields; no single Schwab leaf."),
    DerivationRecord("market_context.py", "421", "_derive_session", "—", "KEEP_DERIVED", "ET session label; no Schwab session_label leaf."),
    DerivationRecord("market_context.py", "445", "fetch_market_context", "quotes.*", "PASS_THROUGH", "Multi-symbol quote fetch via safe_get_quote wrapper."),
    DerivationRecord("market_context.py", "458", "fetch_market_context._fetch", "quotes.*", "PASS_THROUGH", "Nested per-symbol quote fetch inside fetch_market_context."),
    DerivationRecord("market_context.py", "467", "fetch_market_context._chg_for", "quotes.quote.netPercentChange", "PASS_THROUGH", "Nested pct change helper from quote JSON."),
    DerivationRecord("market_context.py", "601", "proximity_alerts", "walls/pins levels", "KEEP_DERIVED", "Distance alerts vs key levels; inputs from upstream math."),
    DerivationRecord("market_context.py", "610", "proximity_alerts._check", "level geometry", "NONE", "Nested distance check helper."),
    DerivationRecord("market_context.py", "651", "_volume_profile_poc_vah_val", "pricehistory.candles.*", "KEEP_DERIVED", "Volume profile POC/VAH/VAL; no Schwab profile leaves."),
    DerivationRecord("market_context.py", "702", "_vwap_bands", "pricehistory.candles.*", "KEEP_DERIVED", "VWAP sigma bands from OHLCV bars."),
    DerivationRecord("market_context.py", "788", "fetch_price_levels", "pricehistory.candles.datetime,OHLC,volume", "REPLACED", "Skip candles missing datetime leaf (fail-closed; no .get(datetime,0))."),
    DerivationRecord("market_state.py", "35", "is_bias_actionable", "—", "NONE", "UI presentation helper; no market derivation."),
    DerivationRecord("market_state.py", "44", "derive_zone", "—", "KEEP_DERIVED", "Regime taxonomy from bias_signal + net_delta."),
    DerivationRecord("market_state.py", "81", "bias_color", "—", "NONE", "UI presentation helper; no market derivation."),
    DerivationRecord("market_state.py", "88", "pin_color", "—", "NONE", "UI presentation helper; no market derivation."),
    DerivationRecord("market_state.py", "95", "nd_color", "quotes.*|chains.*|pricehistory.candles.*", "KEEP_DERIVED", "Reads or composes market fields; no single Schwab leaf."),
    DerivationRecord("market_state.py", "101", "zone_badge_color", "—", "NONE", "UI presentation helper; no market derivation."),
    DerivationRecord("market_state.py", "114", "dte_style", "—", "NONE", "UI presentation helper; no market derivation."),
    DerivationRecord("market_state.py", "497", "_f_ms", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("market_state.py", "503", "_oe_chain_row_snapshot", "chains.*", "PASS_THROUGH", "Snapshots Schwab chain contract row fields."),
    DerivationRecord("market_state.py", "554", "_oe_first_contract_row", "quotes.*|chains.*|pricehistory.candles.*", "KEEP_DERIVED", "Reads or composes market fields; no single Schwab leaf."),
    DerivationRecord("market_state.py", "566", "_oe_composite_strike_row", "chains.*", "PASS_THROUGH", "Aggregates call/put rows at strike from chain JSON."),
    DerivationRecord("market_state.py", "635", "recommend_option_expression", "chains.* bid,ask,gamma,delta,OI", "KEEP_DERIVED", "OE recommendation from chain fields."),
    DerivationRecord("market_state.py", "794", "_oe_bid_ask_mid", "chains.*.mark,bid,ask,last", "KEEP_DERIVED", "OP-006 mark-first mid ladder; bid/ask/2 only when mark+last absent."),
    DerivationRecord("market_state.py", "852", "_schwab_days_to_expiration_for_contract", "chains.*.daysToExpiration", "PASS_THROUGH", "Reads Schwab DTE leaf when present."),
    DerivationRecord("market_state.py", "878", "_build_contract_context_ms", "quotes.*|chains.*|pricehistory.candles.*", "KEEP_DERIVED", "Reads or composes market fields; no single Schwab leaf."),
    DerivationRecord("market_state.py", "916", "build_market_state", "ms_dict / price_levels", "PASS_THROUGH", "Assembles MarketState from server/context outputs."),
    DerivationRecord("math_snapshot_derive.py", "11", "derive_vwap_side", "—", "KEEP_DERIVED", "spot vs vwap side; no Schwab vwap_side leaf."),
    DerivationRecord("math_snapshot_derive.py", "28", "derive_pressure_trend", "—", "KEEP_DERIVED", "DPI trend label; not a Schwab wire field."),
)

SECTION3_FILES = frozenset({
    "market_context.py",
    "market_state.py",
    "math_snapshot_derive.py",
})

