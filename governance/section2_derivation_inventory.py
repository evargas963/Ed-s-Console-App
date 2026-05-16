"""
Section 2 Schwab-leaf derivation audit inventory (source of truth for tests).

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


SECTION2_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
    DerivationRecord(
        "server.py",
        "735-758",
        "REST quote cascade last/mark/bid/ask/time",
        "quotes.quote|extended|regular.*",
        "PASS_THROUGH",
        "Schwab quote hierarchy; spot fail-closed when last+mark missing.",
    ),
    DerivationRecord(
        "server.py",
        "768-774",
        "Fast-lane spread_frac from mark denominator",
        "quotes.quote.mark",
        "KEEP_DERIVED",
        "Spread has no Schwab leaf; mark is wire-first mid (not bid+ask/2).",
    ),
    DerivationRecord(
        "server.py",
        "3146-3162",
        "_fetch_state spread_frac denominator",
        "quotes.quote.mark",
        "REPLACED",
        "Removed bid+ask/2 mid fallback; mark-only denominator aligned with plane.",
    ),
    DerivationRecord(
        "server.py",
        "1092-1154",
        "_CandleAccumulator OHLC/volume from spot ticks + totalVolume delta",
        "quotes.quote.totalVolume, pricehistory.candles.*",
        "KEEP_DERIVED",
        "Poll-synthesized bars between Schwab seeds; volume delta not a per-bar leaf.",
    ),
    DerivationRecord(
        "server.py",
        "1175-1186",
        "Seed bars from pricehistory candles",
        "pricehistory.candles.*",
        "PASS_THROUGH",
        "schwab_candles_to_bars; datetime leaf required.",
    ),
    DerivationRecord(
        "server.py",
        "2286-2306",
        "_compute_vwap_from_bars typical price",
        "—",
        "KEEP_DERIVED",
        "No Schwab VWAP leaf in dictionary.",
    ),
    DerivationRecord(
        "server.py",
        "2247-2278",
        "_update_rest_cum_delta from last vs bid/ask",
        "quotes.quote.lastPrice, lastSize, bidPrice, askPrice",
        "KEEP_DERIVED",
        "REST tape proxy when stream unavailable.",
    ),
    DerivationRecord(
        "live_market_plane.py",
        "91-135",
        "Streaming LEVEL_ONE_EQUITY spot/spread",
        "streaming.content.*.LAST_PRICE,MARK,BID_PRICE,ASK_PRICE",
        "PASS_THROUGH",
        "Mark-denom spread_frac; spot last-or-mark fail-closed.",
    ),
    DerivationRecord(
        "live_market_plane.py",
        "215-284",
        "merge_into_state / L1 overlay",
        "live_market_plane row",
        "PASS_THROUGH",
        "Copies plane fields; no new derivations.",
    ),
    DerivationRecord(
        "live_decision_bundle.py",
        "220-228",
        "_live_session_label via market_context",
        "market_hours (indirect)",
        "KEEP_DERIVED",
        "Session refresh trigger; not a quote field.",
    ),
    DerivationRecord(
        "live_decision_bundle.py",
        "278-290",
        "derive_zone integrity gate",
        "—",
        "KEEP_DERIVED",
        "Coherence check on cached ms_dict; no Schwab ingest.",
    ),
    DerivationRecord(
        "live_decision_bundle.py",
        "390-408",
        "derive_vwap_side on stream spot vs cached vwap",
        "—",
        "KEEP_DERIVED",
        "No vwap_side Schwab leaf; uses server-computed vwap.",
    ),
    DerivationRecord(
        "live_decision_bundle.py",
        "147-192",
        "recompute_nearest_struct_at_spot",
        "—",
        "KEEP_DERIVED",
        "Geometry on cached key levels.",
    ),
    DerivationRecord(
        "order_flow_engine.py",
        "298-340",
        "_compute_spread mark denominator (repo-wide grep hit)",
        "quotes.quote.mark",
        "REPLACED",
        "Cross-section fix (§5 file); removed bid+ask/2 mid synthesis.",
    ),
    DerivationRecord(
        "live_pipeline_diag.py",
        "—",
        "ML horizon diagnostic serialization",
        "—",
        "NONE",
        "No market-data field derivations.",
    ),
    DerivationRecord(
        "live_vs_replay_validation.py",
        "97-172",
        "Replay vs live proof from DB snapshots",
        "snapshots.*",
        "PASS_THROUGH",
        "Validation reads persisted snapshots; no live Schwab ingest.",
    ),
)
