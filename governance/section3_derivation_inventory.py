"""
Section 3 Schwab-leaf derivation audit inventory (source of truth for tests).

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
    DerivationRecord(
        "market_context.py",
        "270-296",
        "_extract_quote last + chg_pct cascade",
        "quotes.quote|extended|regular.lastPrice,netPercentChange",
        "PASS_THROUGH",
        "Schwab quote hierarchy; pct from netChange only when leaf present.",
    ),
    DerivationRecord(
        "market_context.py",
        "421-442",
        "_derive_session from ET clock",
        "—",
        "KEEP_DERIVED",
        "No Schwab session_label leaf; calendar boundaries only.",
    ),
    DerivationRecord(
        "market_context.py",
        "651-726",
        "POC/VAH/VAL and VWAP bands from OHLCV bars",
        "pricehistory.candles.*",
        "KEEP_DERIVED",
        "Volume profile / VWAP stats; no Schwab POC/VWAP leaves.",
    ),
    DerivationRecord(
        "market_context.py",
        "813-826",
        "Tier-1 today OHLC/PDC from quote{}",
        "quotes.quote.openPrice,highPrice,lowPrice,closePrice",
        "PASS_THROUGH",
        "Direct Schwab quote leaves when present.",
    ),
    DerivationRecord(
        "market_context.py",
        "869-941",
        "Price-history candle datetime + VWAP/ORB",
        "pricehistory.candles.datetime",
        "REPLACED",
        "Skip candles missing datetime leaf (was .get(datetime,0)); fail-closed.",
    ),
    DerivationRecord(
        "market_state.py",
        "44-72",
        "derive_zone from bias_signal + net_delta",
        "—",
        "KEEP_DERIVED",
        "Regime taxonomy; not a Schwab wire field.",
    ),
    DerivationRecord(
        "market_state.py",
        "794-848",
        "_oe_bid_ask_mid mark→last→bid/ask ladder",
        "chains.*.mark,bid,ask,last",
        "KEEP_DERIVED",
        "OP-006 option mid ladder; mark-first; bid/ask/2 only when mark+last absent.",
    ),
    DerivationRecord(
        "market_state.py",
        "916-985",
        "build_market_state assembly",
        "ms_dict / price_levels inputs",
        "PASS_THROUGH",
        "Consumes server/context outputs; no new Schwab ingest.",
    ),
    DerivationRecord(
        "math_snapshot_derive.py",
        "11-25",
        "derive_vwap_side spot vs vwap",
        "—",
        "KEEP_DERIVED",
        "No vwap_side Schwab leaf; returns None when inputs missing.",
    ),
    DerivationRecord(
        "math_snapshot_derive.py",
        "28-53",
        "derive_pressure_trend DPI delta",
        "—",
        "KEEP_DERIVED",
        "Dealer-pressure trend; not a Schwab field.",
    ),
    DerivationRecord(
        "math_exposure_core.py",
        "839-847",
        "returns_from_candles daily grouping",
        "pricehistory.candles.datetime",
        "REPLACED",
        "Cross-section fix (§4 file); skip missing datetime (was default 0).",
    ),
    DerivationRecord(
        "server.py",
        "1173-1183",
        "_CandleAccumulator.seed datetime",
        "pricehistory.candles.datetime",
        "REPLACED",
        "Cross-section fix (§2 file); reject bars without datetime leaf.",
    ),
)
