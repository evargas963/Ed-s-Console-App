"""Phase 3 D17 — Schwab adapter normalization boundary (register disposition only).

Scope: market_data_adapter.py, live_market_plane.py, schwab_client.py.
Wire-pattern rows are excluded from lexical bulk NOT_MARKET_DATA via PHASE3_ADAPTER_WIRE_DENYLIST.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

PHASE3_ADAPTER_PATHS: frozenset[str] = frozenset(
    {
        "market_data_adapter.py",
        "live_market_plane.py",
        "schwab_client.py",
    }
)

WIRE_PATTERN_KINDS: frozenset[str] = frozenset(
    {
        "DICT_GET_MARKET_NULLABLE",
        "SUBSCRIPT_MARKET_KEY",
        "ATTRIBUTE_MARKET",
        "GETATTR_MARKET_LITERAL",
        "PYTHON_GETATTR_SETATTR",
        "DICT_LITERAL_MARKET_KEY",
    }
)

PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST: frozenset[str] = frozenset(
    {
        # spread / display derived from Schwab streaming bid/ask/mark (lexical rows)
        "d09ed96468157bb8792b",
        "30bd6b2b1095672f6c6c",
        "ba019d02dd237d0c86a3",
        "306baa95ad647c4cc4a2",
        "5d3a3ad8a51e611be792",
        "1d4bfd5ed307d0c87083",
        "d8590b3a6dc081fb1c1b",
        "a4581785fa6fbeac4c75",
    }
)

_PP_FAST_QUOTE = (
    "governance/artifacts/perf_proof/replacements/"
    "pp_v4b_server_fast_quote_leaf_provenance.json"
)
_PP_PRICEHISTORY = (
    "governance/artifacts/perf_proof/replacements/"
    "pp_v4b_market_context_quote_pricehistory_leaf_provenance.json"
)
_PP_MARKET_STATE_CHAIN = (
    "governance/artifacts/perf_proof/replacements/"
    "pp_v4b_market_state_chunk6_chain_leaf_provenance.json"
)

PHASE3_NMD_NOTE: Final[str] = (
    "Phase 3 D17 adapter lexical NOT_MARKET_DATA — non-wire surface in adapter trio only"
)
PHASE3_WIRE_TRACE: Final[str] = "Phase 3 D17 adapter wire disposition slice (line-level trace)"


@dataclass(frozen=True)
class WireDisposition:
    disposition: str
    canonical_field_citation: str = ""
    governed_ref: str = ""
    notes: str = ""


# All 65 wire-pattern register_ids — frozen at Phase 3 investigation (unreviewed_count baseline 46859).
PHASE3_ADAPTER_WIRE_DENYLIST: frozenset[str] = frozenset(
    {
        "5705329be00c39ccb749",
        "3c6d9157455f5618f9b2",
        "54f28419b563197b79b6",
        "6fe4c8273e3e11c1b218",
        "fbc802d971684fc1f3d9",
        "889d508aa3c3cbe7b8e3",
        "cf25f5c53a0bb0440513",
        "361ec8c131f7a5f75421",
        "93c64ef80ce2827ea4e1",
        "a46779603022537945a5",
        "eaafb1b4674d0618b3f0",
        "31b00a55a45fb5361aed",
        "7f10a05549c4acbf0a6e",
        "61cf75d0a2cab0075e61",
        "08449478ae9f9d7a4717",
        "97dc24dd77b9bdfc1808",
        "8013bd3a50ef63d7b40e",
        "0d02975a333763dc6290",
        "47d5ae0a4e89d4dfff5e",
        "a7d28e0af9ec13cc406a",
        "e203adb4519dcbe8ec88",
        "ef1e3ce15162f9921839",
        "58536944872cd2030b53",
        "25647bb093c098d521fc",
        "6169cd689ab54eb3fb87",
        "586c234040379f8c6193",
        "7d3d6d14e997e6302909",
        "c5b8a2cc6aac6c0863cb",
        "32ae1a19d439b35ce6d4",
        "0ef6e01c4c1d7d22f33a",
        "0eef98b4e2fc7409f2f3",
        "43fc295d2c5a3be228b5",
        "cfb679227d6807310984",
        "dd6d60d0a67951b38b01",
        "986872e3a95197a8c3a1",
        "80efcad5043487fe3a6c",
        "c3e850121f304b1dab8f",
        "823c46bedc24b0b9ca38",
        "2334dc4e0a2355a8309a",
        "083e2c95d19f6d1d3157",
        "1085f69ff30591b0764e",
        "7a6274103d391e209a50",
        "862ba7fda0abddccdd92",
        "b59779b440899bb05cd5",
        "45ee1e6cf54a944c201a",
        "234bbf4c9fc56c2687c3",
        "74bd9c8d87672d2cdb4c",
        "ed845c78373176d8afff",
        "c7a190ab90018d68ee87",
        "ba39b744f099fc99ba7b",
        "e49084233173e5e5d074",
        "29b8a02808e2d98f3f25",
        "0e866290ac706cecdcee",
        "d55858c805bc13875b76",
        "1f3f1300cbcb33f1a2da",
        "db641e14d6eb1b52ccdc",
        "c4d49d94982bea534845",
        "707587b873e07d0df79b",
        "7c5df428881f49d9b5e5",
        "156ae82138d8a9cc17ac",
        "c074d1ebf74c5f61bf1b",
        "294eff14d75df99bc536",
        "bbe6040933cc6d26b06e",
        "8b652342bdf9df9730d9",
        "b7cd21eedac2c238fa2d",
    }
)

PHASE3_WIRE_DISPOSITIONS: dict[str, WireDisposition] = {
    # live_market_plane.py — Schwab streaming LEVEL_ONE_EQUITY ingest (register lags code)
    "5705329be00c39ccb749": WireDisposition(
        "REPLACED",
        "streaming.content.*.LAST_PRICE",
        _PP_FAST_QUOTE,
        "record_from_level_one_equity item.get LAST_PRICE | live_market_plane.py L95",
    ),
    "3c6d9157455f5618f9b2": WireDisposition(
        "REPLACED",
        "streaming.content.*.MARK",
        _PP_FAST_QUOTE,
        "record_from_level_one_equity item.get MARK | live_market_plane.py L96",
    ),
    "54f28419b563197b79b6": WireDisposition(
        "REPLACED",
        "streaming.content.*.BID_PRICE",
        _PP_FAST_QUOTE,
        "record_from_level_one_equity item.get BID_PRICE | live_market_plane.py L97",
    ),
    "6fe4c8273e3e11c1b218": WireDisposition(
        "REPLACED",
        "streaming.content.*.ASK_PRICE",
        _PP_FAST_QUOTE,
        "record_from_level_one_equity item.get ASK_PRICE | live_market_plane.py L98",
    ),
    "cf25f5c53a0bb0440513": WireDisposition(
        "REPLACED",
        "streaming.content.*.QUOTE_TIME_MILLIS",
        _PP_FAST_QUOTE,
        "quote timestamp millis | live_market_plane.py L115",
    ),
    "361ec8c131f7a5f75421": WireDisposition(
        "REPLACED",
        "streaming.content.*.TRADE_TIME_MILLIS",
        _PP_FAST_QUOTE,
        "trade timestamp millis | live_market_plane.py L116",
    ),
    "fbc802d971684fc1f3d9": WireDisposition(
        "KEEP_DERIVED",
        "",
        "",
        "prev plane cache bid (carried from prior Schwab ingest) | live_market_plane.py L103",
    ),
    "889d508aa3c3cbe7b8e3": WireDisposition(
        "KEEP_DERIVED",
        "",
        "",
        "prev plane cache ask (carried from prior Schwab ingest) | live_market_plane.py L104",
    ),
    "93c64ef80ce2827ea4e1": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "quote_ingestion app metadata compare | live_market_plane.py L123",
    ),
    "a46779603022537945a5": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "server_received_ts wall clock time.time() | live_market_plane.py L143",
    ),
    "eaafb1b4674d0618b3f0": WireDisposition(
        "REPLACED",
        "streaming.content.*.BID_PRICE",
        _PP_FAST_QUOTE,
        "plane out bid from BID_PRICE | live_market_plane.py L147",
    ),
    "31b00a55a45fb5361aed": WireDisposition(
        "REPLACED",
        "streaming.content.*.ASK_PRICE",
        _PP_FAST_QUOTE,
        "plane out ask from ASK_PRICE | live_market_plane.py L148",
    ),
    "7f10a05549c4acbf0a6e": WireDisposition(
        "KEEP_DERIVED",
        "",
        "",
        "bid_disp display format of Schwab bid | live_market_plane.py L150",
    ),
    "61cf75d0a2cab0075e61": WireDisposition(
        "KEEP_DERIVED",
        "",
        "",
        "ask_disp display format of Schwab ask | live_market_plane.py L151",
    ),
    "08449478ae9f9d7a4717": WireDisposition(
        "KEEP_DERIVED",
        "",
        "",
        "quote_mid derived from Schwab streaming MARK | live_market_plane.py L152",
    ),
    "97dc24dd77b9bdfc1808": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "quote_time_source app metadata | live_market_plane.py L170",
    ),
    "8013bd3a50ef63d7b40e": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "quote_ingestion app metadata | live_market_plane.py L172",
    ),
    "0d02975a333763dc6290": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "quote_source_detail container | live_market_plane.py L173",
    ),
    "47d5ae0a4e89d4dfff5e": WireDisposition(
        "REPLACED",
        "streaming.content.*.BID_PRICE",
        _PP_FAST_QUOTE,
        "quote_source_detail bid attribution BID_PRICE | live_market_plane.py L175",
    ),
    "a7d28e0af9ec13cc406a": WireDisposition(
        "REPLACED",
        "streaming.content.*.ASK_PRICE",
        _PP_FAST_QUOTE,
        "quote_source_detail ask attribution ASK_PRICE | live_market_plane.py L176",
    ),
    "e203adb4519dcbe8ec88": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "previous_bid_available app flag | live_market_plane.py L181",
    ),
    "ef1e3ce15162f9921839": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "previous_ask_available app flag | live_market_plane.py L182",
    ),
    "58536944872cd2030b53": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "_quote_authority overlay metadata | live_market_plane.py L254",
    ),
    "25647bb093c098d521fc": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "_quote_authority overlay metadata | live_market_plane.py L291",
    ),
    # market_data_adapter.py — pricehistory.candles.* normalization boundary
    "32ae1a19d439b35ce6d4": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.open",
        _PP_PRICEHISTORY,
        "SCHWAB_CANDLE_LEAF_MAP open | market_data_adapter.py L28",
    ),
    "0ef6e01c4c1d7d22f33a": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.high",
        _PP_PRICEHISTORY,
        "SCHWAB_CANDLE_LEAF_MAP high | market_data_adapter.py L29",
    ),
    "0eef98b4e2fc7409f2f3": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.low",
        _PP_PRICEHISTORY,
        "SCHWAB_CANDLE_LEAF_MAP low | market_data_adapter.py L30",
    ),
    "43fc295d2c5a3be228b5": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.close",
        _PP_PRICEHISTORY,
        "SCHWAB_CANDLE_LEAF_MAP close | market_data_adapter.py L31",
    ),
    "cfb679227d6807310984": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.volume",
        _PP_PRICEHISTORY,
        "SCHWAB_CANDLE_LEAF_MAP volume | market_data_adapter.py L32",
    ),
    "dd6d60d0a67951b38b01": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "SCHWAB_CANDLE_LEAF_MAP datetime | market_data_adapter.py L33",
    ),
    "80efcad5043487fe3a6c": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.open",
        _PP_PRICEHISTORY,
        "NormalizedBar.to_dict open | market_data_adapter.py L52",
    ),
    "c3e850121f304b1dab8f": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.high",
        _PP_PRICEHISTORY,
        "NormalizedBar.to_dict high | market_data_adapter.py L53",
    ),
    "823c46bedc24b0b9ca38": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.low",
        _PP_PRICEHISTORY,
        "NormalizedBar.to_dict low | market_data_adapter.py L54",
    ),
    "2334dc4e0a2355a8309a": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.close",
        _PP_PRICEHISTORY,
        "NormalizedBar.to_dict close | market_data_adapter.py L55",
    ),
    "083e2c95d19f6d1d3157": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.volume",
        _PP_PRICEHISTORY,
        "NormalizedBar.to_dict volume | market_data_adapter.py L56",
    ),
    "986872e3a95197a8c3a1": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "NormalizedBar.to_dict timestamp from datetime | market_data_adapter.py L51",
    ),
    "6169cd689ab54eb3fb87": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.open",
        _PP_PRICEHISTORY,
        "normalize_bar getattr open | market_data_adapter.py L78",
    ),
    "586c234040379f8c6193": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.high",
        _PP_PRICEHISTORY,
        "normalize_bar getattr high | market_data_adapter.py L78",
    ),
    "7d3d6d14e997e6302909": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.low",
        _PP_PRICEHISTORY,
        "normalize_bar getattr low | market_data_adapter.py L78",
    ),
    "c5b8a2cc6aac6c0863cb": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.close",
        _PP_PRICEHISTORY,
        "normalize_bar getattr close | market_data_adapter.py L78",
    ),
    "1085f69ff30591b0764e": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "normalize_bar attr timestamp | market_data_adapter.py L40",
    ),
    "7a6274103d391e209a50": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.open",
        _PP_PRICEHISTORY,
        "normalize_bar attr open | market_data_adapter.py L41",
    ),
    "862ba7fda0abddccdd92": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.high",
        _PP_PRICEHISTORY,
        "normalize_bar attr high | market_data_adapter.py L42",
    ),
    "b59779b440899bb05cd5": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.low",
        _PP_PRICEHISTORY,
        "normalize_bar attr low | market_data_adapter.py L43",
    ),
    "45ee1e6cf54a944c201a": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.close",
        _PP_PRICEHISTORY,
        "normalize_bar attr close | market_data_adapter.py L44",
    ),
    "234bbf4c9fc56c2687c3": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.volume",
        _PP_PRICEHISTORY,
        "normalize_bar attr volume | market_data_adapter.py L45",
    ),
    "74bd9c8d87672d2cdb4c": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.volume",
        _PP_PRICEHISTORY,
        "normalize_bar raw.get volume | market_data_adapter.py L87",
    ),
    "ed845c78373176d8afff": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.volume",
        _PP_PRICEHISTORY,
        "normalize_bar getattr volume | market_data_adapter.py L87",
    ),
    "c7a190ab90018d68ee87": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "schwab_pricehistory raw.get datetime | market_data_adapter.py L100",
    ),
    "ba39b744f099fc99ba7b": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "normalize_bar raw.get datetime | market_data_adapter.py L104",
    ),
    "e49084233173e5e5d074": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "normalize_bar raw.get datetime branch | market_data_adapter.py L104",
    ),
    "29b8a02808e2d98f3f25": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "normalize_bar raw.get timestamp fallback | market_data_adapter.py L104",
    ),
    "0e866290ac706cecdcee": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "normalize_bar getattr datetime schwab_pricehistory | market_data_adapter.py L106",
    ),
    "d55858c805bc13875b76": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "normalize_bar getattr timestamp | market_data_adapter.py L106",
    ),
    "1f3f1300cbcb33f1a2da": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.volume",
        _PP_PRICEHISTORY,
        "schwab_candles_to_bars missing volume check | market_data_adapter.py L124",
    ),
    "db641e14d6eb1b52ccdc": WireDisposition(
        "REPLACED",
        "pricehistory.candles.*.datetime",
        _PP_PRICEHISTORY,
        "schwab_candles_to_bars c.get datetime | market_data_adapter.py L169",
    ),
    # schwab_client.py — transport / API boundary
    "c4d49d94982bea534845": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "OAuth DEFAULT_BASE_URL getattr auth plumbing | schwab_client.py L51",
    ),
    "707587b873e07d0df79b": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "token expiry wall clock time.time() | schwab_client.py L152",
    ),
    "7c5df428881f49d9b5e5": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "OAuth2Client.create_authorization_url attr start | schwab_client.py L59",
    ),
    "156ae82138d8a9cc17ac": WireDisposition(
        "REPLACED",
        "pricehistory.candles",
        _PP_PRICEHISTORY,
        "safe_get_price_history Client.PriceHistory API | schwab_client.py L507 (rekeyed 2026-07-15: site shifted, content identical)",
    ),
    "c074d1ebf74c5f61bf1b": WireDisposition(
        "NOT_MARKET_DATA",
        "",
        "",
        "PriceHistory.Period.DAY API enum constant | schwab_client.py L509",
    ),
    "294eff14d75df99bc536": WireDisposition(
        "REPLACED",
        "chains.strikeCount",
        _PP_MARKET_STATE_CHAIN,
        "safe_get_chain strike_count kwarg | schwab_client.py L561 (rekeyed 2026-07-15: site shifted, content identical)",
    ),
    "bbe6040933cc6d26b06e": WireDisposition(
        "REPLACED",
        "chains.includeUnderlyingQuote",
        _PP_MARKET_STATE_CHAIN,
        "safe_get_chain include_underlying_quote | schwab_client.py L561 (rekeyed 2026-07-15: site shifted, content identical)",
    ),
    "8b652342bdf9df9730d9": WireDisposition(
        "REPLACED",
        "chains.fromDate",
        _PP_MARKET_STATE_CHAIN,
        "safe_get_chain from_date | schwab_client.py L563 (rekeyed 2026-07-15: site shifted, content identical)",
    ),
    "b7cd21eedac2c238fa2d": WireDisposition(
        "REPLACED",
        "chains.toDate",
        _PP_MARKET_STATE_CHAIN,
        "safe_get_chain to_date | schwab_client.py L565 (rekeyed 2026-07-15: site shifted, content identical)",
    ),
}

PHASE3_LEXICAL_KEEP_DERIVED_DISPOSITIONS: dict[str, WireDisposition] = {
    rid: WireDisposition(
        "KEEP_DERIVED",
        "",
        "",
        f"lexical spread/display derived from Schwab bid/ask/mark | register_id={rid}",
    )
    for rid in PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST
}
