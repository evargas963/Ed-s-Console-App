"""
Section 5 Schwab-leaf derivation audit inventory (order flow).

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


SECTION5_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("order_flow_engine.py", "40", "_safe_float", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "50", "_nonnegative_float", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "57", "_safe_int", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "67", "_collect_from_nested", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("order_flow_engine.py", "83", "_get_nested", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "98", "_iter_content", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "110", "_iter_bids_levels", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "135", "_iter_asks_levels", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "159", "_iter_tape_prints", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "183", "_latest_book_snapshot", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "191", "_compute_book_imbalance", "streaming.book levels", "KEEP_DERIVED", "Depth imbalance from bid/ask level sizes."),
    DerivationRecord("order_flow_engine.py", "216", "_latest_quote_snapshot", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "224", "_compute_top_book_pressure", "streaming.book,quotes", "KEEP_DERIVED", "Top-of-book pressure composite."),
    DerivationRecord("order_flow_engine.py", "254", "_resolve_bid_ask_prices", "streaming.BID/ASK,quotes.quote.bidPrice,askPrice", "PASS_THROUGH", "Bid/ask from stream or REST quote JSON."),
    DerivationRecord("order_flow_engine.py", "298", "_resolve_quote_mark", "quotes.quote.mark,streaming.MARK", "PASS_THROUGH", "Mark leaf for spread denominator."),
    DerivationRecord("order_flow_engine.py", "319", "_compute_spread", "quotes.quote.mark,streaming.MARK", "REPLACED", "spread_frac mark-denom only; removed bid+ask/2 mid synthesis."),
    DerivationRecord("order_flow_engine.py", "356", "_compute_tape_pressure", "streaming.LAST_PRICE,SIZE", "KEEP_DERIVED", "Tape pressure from print stream."),
    DerivationRecord("order_flow_engine.py", "410", "_compute_cum_delta_proxy", "streaming prints,quotes", "KEEP_DERIVED", "Cumulative delta proxy when stream partial."),
    DerivationRecord("order_flow_engine.py", "442", "_compute_cum_delta_slope", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "501", "_earliest_book_snapshot", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "509", "_compute_absorption", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "545", "_iter_option_exp_levels", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_engine.py", "606", "_option_contract_volume", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_engine.py", "619", "_compute_options_flow", "chains.* volume,bidSize,askSize", "KEEP_DERIVED", "Options flow from chain/stream maps."),
    DerivationRecord("order_flow_engine.py", "686", "_compute_rvol", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "740", "_compute_institutional_flow_proxy", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "766", "_normalize", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "773", "_compute_order_flow_score", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "802", "_direction", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("order_flow_engine.py", "811", "_readiness", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "837", "OrderFlowEngine.compute", "aggregated OF metrics", "KEEP_DERIVED", "Public OF engine entry; composes sub-metrics."),
    DerivationRecord("order_flow_engine.py", "992", "OrderFlowEngine._empty_result", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "1046", "_mock_data", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_engine.py", "1144", "_main", "—", "NONE", "CLI/mock/diagnostic; no production derivation."),
    DerivationRecord("order_flow_live_state.py", "33", "is_rth_open", "—", "NONE", "No Schwab market-field derivation in function body."),
    DerivationRecord("order_flow_live_state.py", "46", "_get_book", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_live_state.py", "53", "_get_tape", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_live_state.py", "60", "push_book", "streaming.book bid/ask levels", "PASS_THROUGH", "Ingests book level updates into deque."),
    DerivationRecord("order_flow_live_state.py", "85", "push_level_one", "streaming.content.* LEVEL_ONE", "PASS_THROUGH", "Ingests Schwab LEVEL_ONE_EQUITY content item."),
    DerivationRecord("order_flow_live_state.py", "182", "get_content_for_symbol", "streaming content deque", "PASS_THROUGH", "Returns merged stream content for engine."),
    DerivationRecord("order_flow_live_state.py", "211", "get_l1_stream_input_probe", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_live_state.py", "236", "clear_symbol", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_live_state.py", "254", "get_stream_volume", "streaming.TOTAL_VOLUME", "PASS_THROUGH", "Latest stream totalVolume for symbol."),
    DerivationRecord("order_flow_live_state.py", "263", "get_stream_chg_pct", "streaming net change fields", "PASS_THROUGH", "Stream-derived change percent when present."),
    DerivationRecord("order_flow_live_state.py", "272", "get_top_of_book_sizes", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_live_state.py", "278", "get_top_of_book_sizes._to_int", "—", "NONE", "Nested int parse inside get_top_of_book_sizes."),
    DerivationRecord("order_flow_live_state.py", "294", "get_stats", "streaming.*|quotes.*|chains.*", "KEEP_DERIVED", "Order-flow metric from Schwab stream/quote fields."),
    DerivationRecord("order_flow_streaming.py", "60", "_log_stream", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "68", "_streaming_healthy", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "79", "is_order_flow_stream_running", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "83", "get_plane_authority_for_ticker", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "97", "_stale_bucket", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "112", "_diag_on_active_l1_tick", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "128", "_async_staleness_watch", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "160", "get_streaming_diagnostics", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "180", "_resubscribe_to_ticker", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "208", "_resubscribe_coro", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "221", "set_streaming_active_ticker", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "249", "_graceful_disconnect_stream_client", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "268", "_drain_asyncio_tasks", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "279", "_message_loop_until_shutdown", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "308", "_run_stream_loop", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "319", "_run_stream_loop._async_run", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "341", "_run_stream_loop._async_run._book_handler", "streaming book events", "PASS_THROUGH", "Async handler pushes book to live_state."),
    DerivationRecord("order_flow_streaming.py", "354", "_run_stream_loop._async_run._level_one_handler", "streaming LEVEL_ONE", "PASS_THROUGH", "Async handler pushes L1 to live_state."),
    DerivationRecord("order_flow_streaming.py", "437", "start_order_flow_stream", "Schwab stream client", "PASS_THROUGH", "Starts schwab-py stream subscription thread."),
    DerivationRecord("order_flow_streaming.py", "468", "stop_order_flow_stream", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("order_flow_streaming.py", "504", "get_stream_thread", "quotes.*|streaming.*|chains.*", "PASS_THROUGH", "Schwab stream or API wire path."),
    DerivationRecord("debug_flow_snapshot.py", "32", "_contracts_from_chain_json", "chains.*", "PASS_THROUGH", "Parses option chain JSON for debug snapshot."),
    DerivationRecord("debug_flow_snapshot.py", "63", "main", "—", "NONE", "CLI debug entry; reads persisted snapshots."),
)

SECTION5_FILES = frozenset({
    "order_flow_engine.py",
    "order_flow_live_state.py",
    "order_flow_streaming.py",
    "debug_flow_snapshot.py",
})

