"""
Section 1 Schwab-leaf derivation audit inventory (source of truth for tests).

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


SECTION1_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
    DerivationRecord(
        "schwab_client.py",
        "—",
        "OAuth client construction / token refresh",
        "—",
        "NONE",
        "No market-field derivations; transport auth only.",
    ),
    DerivationRecord(
        "reauth_schwab.py",
        "—",
        "Manual OAuth re-auth CLI",
        "—",
        "NONE",
        "No market-field derivations.",
    ),
    DerivationRecord(
        "websocket_adapter.py",
        "—",
        "Abstract WebSocket bar stream contract",
        "—",
        "NONE",
        "No implementations; no field reads.",
    ),
    DerivationRecord(
        "sse_adapter.py",
        "—",
        "Abstract SSE bar stream contract",
        "—",
        "NONE",
        "No implementations; no field reads.",
    ),
    DerivationRecord(
        "polling_adapter.py",
        "65-66",
        "Fetch Schwab pricehistory JSON → bar list",
        "pricehistory.candles.*",
        "PASS_THROUGH",
        "Delegates to schwab_candles_to_bars; no alternate OHLC source.",
    ),
    DerivationRecord(
        "polling_adapter.py",
        "102-110",
        "camelCase get_price_history fallback",
        "pricehistory.candles",
        "KEEP_DERIVED",
        "SDK transport compatibility only; same Schwab endpoint/fields.",
    ),
    DerivationRecord(
        "market_data_adapter.py",
        "67-95",
        "Read OHLCV from raw candle dict",
        "pricehistory.candles.{open,high,low,close,volume}",
        "REPLACED",
        "Canonical Schwab leaf keys only; reject bar if any OHLC missing.",
    ),
    DerivationRecord(
        "market_data_adapter.py",
        "86-89",
        "Bar timestamp from datetime",
        "pricehistory.candles.datetime",
        "REPLACED",
        "Schwab path requires datetime; internal timestamp alias only after read.",
    ),
    DerivationRecord(
        "market_data_adapter.py",
        "154-158",
        "_ts epoch seconds from datetime ms",
        "pricehistory.candles.datetime",
        "KEEP_DERIVED",
        "Unit conversion of Schwab ms leaf for engine filter; not alternate price source.",
    ),
    DerivationRecord(
        "snapshot_normalizer.py",
        "118-210",
        "resample_to_1m synthetic OHLC from sub-minute snapshot rows",
        "pricehistory.candles.* (native 1m via polling)",
        "KEEP_DERIVED",
        "Fallback when DB holds sub-minute snapshots; tagged synthetic+source; prefer pricehistory path.",
    ),
    DerivationRecord(
        "snapshot_normalizer.py",
        "120-125",
        "candle_open from spot when candle_open missing",
        "snapshots.spot / quotes",
        "KEEP_DERIVED",
        "No candle_open on row; spot proxy recorded in missing_fields.",
    ),
    DerivationRecord(
        "snapshot_normalizer.py",
        "127-151",
        "high/low from spot when candle_high/low missing",
        "snapshots.spot",
        "KEEP_DERIVED",
        "Spot proxy only when strike bar field absent; missing_fields tag.",
    ),
    DerivationRecord(
        "snapshot_normalizer.py",
        "168-175",
        "spot from close when spot missing",
        "snapshots.spot",
        "KEEP_DERIVED",
        "spot_close_proxy in missing_fields; fail-closed skip if both missing.",
    ),
    DerivationRecord(
        "snapshot_normalizer.py",
        "204-207",
        "candle_body_pts / candle_range_pts from OHLC",
        "derived from pricehistory.candles OHLC when present",
        "KEEP_DERIVED",
        "Presentation metric from Schwab-sourced OHLC; not a listed Schwab leaf.",
    ),
    DerivationRecord(
        "snapshot_normalizer.py",
        "209-211",
        "vwap_side from spot vs vwap",
        "—",
        "KEEP_DERIVED",
        "No vwap_side in schwab_field_dictionary.csv; math_snapshot_derive returns None if inputs missing.",
    ),
    DerivationRecord(
        "snapshot_access.py",
        "—",
        "timeframe enforcement for snapshot SQL",
        "—",
        "NONE",
        "No numeric field derivations.",
    ),
)
