"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, fourteenth extracted phase.

_order_flow_data_for_state (server.py) is the Order Flow Engine input
assembly phase, extracted verbatim from _fetch_state's body: builds the
full Claude proxy field set (quote/extended/regular/fundamental/reference
+ chain expDateMaps + underlying + 1m candles + optional live streaming
content) and updates the REST Cum Delta accumulator.

Any exception while building the field set is caught and logged (never
raised), leaving order_flow_data at whatever partial state it reached; a
missing app.options.order_flow.state module (ImportError) silently skips
the live-content merge.
"""
from __future__ import annotations

from unittest import mock

import server as srv
from time_et import now_et as _eastern_now


def test_full_pipeline_matches_expected_field_set():
    ticker = "ZZZ_OFD_MATCH"
    now_et = _eastern_now()
    q_json = {
        ticker: {
            "quote": {"bidPrice": 100.0, "askPrice": 100.5},
            "extended": {"lastPrice": 100.2},
            "regular": {"regularMarketLastPrice": 100.1},
            "fundamental": {"peRatio": 20.0},
            "reference": {"exchange": "NYSE"},
        }
    }
    c_json = {
        "callExpDateMap": {"2026-10-16:5": {}},
        "putExpDateMap": {"2026-10-16:5": {}},
        "underlying": {"last": 100.2},
    }

    result = srv._order_flow_data_for_state(ticker, q_json, c_json, now_et)

    assert result["quote"] == {"bidPrice": 100.0, "askPrice": 100.5}
    assert result["extended"] == {"lastPrice": 100.2}
    assert result["regular"] == {"regularMarketLastPrice": 100.1}
    assert result["fundamental"] == {"peRatio": 20.0}
    assert result["reference"] == {"exchange": "NYSE"}
    assert result["callExpDateMap"] == {"2026-10-16:5": {}}
    assert result["putExpDateMap"] == {"2026-10-16:5": {}}
    assert result["underlying"] == {"last": 100.2}
    assert "candles" in result


def test_ticker_not_present_falls_back_to_whole_q_json_node():
    """q_node = q_json.get(TICKER) or q_json.get(ticker) or q_json -- when neither key
    exists, the whole q_json dict is used as the node (this is the original inline
    fallback chain, preserved verbatim)."""
    ticker = "ZZZ_OFD_FALLBACK"
    now_et = _eastern_now()
    q_json = {"quote": {"bidPrice": 55.0}}
    c_json = {"callExpDateMap": {}, "putExpDateMap": {}, "underlying": {}}

    result = srv._order_flow_data_for_state(ticker, q_json, c_json, now_et)
    assert result["quote"] == {"bidPrice": 55.0}


def test_exception_building_field_set_is_swallowed_leaving_partial_state():
    """A non-dict q_json raises AttributeError on .get() -- caught by the outer
    try/except, never propagating out of the phase."""
    ticker = "ZZZ_OFD_BOOM"
    now_et = _eastern_now()
    c_json = {"callExpDateMap": {}, "putExpDateMap": {}, "underlying": {}}

    result = srv._order_flow_data_for_state(ticker, None, c_json, now_et)
    assert result == {}


def test_live_content_merged_when_available():
    ticker = "ZZZ_OFD_LIVE"
    now_et = _eastern_now()
    q_json = {ticker: {"quote": {}, "extended": {}, "regular": {}, "fundamental": {}, "reference": {}}}
    c_json = {"callExpDateMap": {}, "putExpDateMap": {}, "underlying": {}}

    with mock.patch(
        "app.options.order_flow.state.get_content_for_symbol",
        return_value={"book": {"bids": [], "asks": []}},
    ):
        result = srv._order_flow_data_for_state(ticker, q_json, c_json, now_et)
    assert result.get("content") == {"book": {"bids": [], "asks": []}}


def test_missing_live_content_module_is_silently_skipped():
    ticker = "ZZZ_OFD_NOMODULE"
    now_et = _eastern_now()
    q_json = {ticker: {"quote": {}, "extended": {}, "regular": {}, "fundamental": {}, "reference": {}}}
    c_json = {"callExpDateMap": {}, "putExpDateMap": {}, "underlying": {}}

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _raise_on_order_flow_state(name, *a, **k):
        if name == "app.options.order_flow.state":
            raise ImportError("simulated missing module")
        return real_import(name, *a, **k)

    with mock.patch("builtins.__import__", side_effect=_raise_on_order_flow_state):
        result = srv._order_flow_data_for_state(ticker, q_json, c_json, now_et)
    assert "content" not in result


def test_rest_cum_delta_is_updated_from_merged_quote_and_extended():
    ticker = "ZZZ_OFD_CUMDELTA"
    now_et = _eastern_now()
    q_json = {ticker: {"quote": {"bidPrice": 1.0}, "extended": {"lastPrice": 2.0}, "regular": {}, "fundamental": {}, "reference": {}}}
    c_json = {"callExpDateMap": {}, "putExpDateMap": {}, "underlying": {}}

    with mock.patch.object(srv, "_update_rest_cum_delta") as mock_update:
        srv._order_flow_data_for_state(ticker, q_json, c_json, now_et)
    assert mock_update.call_count == 1
    called_ticker, called_quote, called_now = mock_update.call_args[0]
    assert called_ticker == ticker
    assert called_quote == {"bidPrice": 1.0, "lastPrice": 2.0}
    assert called_now == now_et


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _order_flow_data_for_state exactly once, and
    must not directly call _update_rest_cum_delta itself."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_order_flow_data_for_state") == 1
    assert "_update_rest_cum_delta" not in calls_in_fetch_state, (
        "_fetch_state still calls _update_rest_cum_delta directly -- the order-flow-data "
        "phase was not fully extracted, a second inline call site survived"
    )
