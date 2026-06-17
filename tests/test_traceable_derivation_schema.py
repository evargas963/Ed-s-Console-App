"""TraceableDerivation schema — rejects categorical schwab_leaf strings by construction."""

from __future__ import annotations

import pytest

from governance.traceable_derivation import (
    FieldInputRef,
    SchwabLeafRef,
    TraceableDerivation,
    assert_inventory_is_traceable,
    is_valid_schwab_leaf_path,
    reject_categorical_schwab_leaf,
)


def test_valid_schwab_leaf_paths():
    assert is_valid_schwab_leaf_path("quotes.quote.lastPrice")
    assert is_valid_schwab_leaf_path("chains.strikeMap.*.gamma")
    assert is_valid_schwab_leaf_path("pricehistory.candles.datetime")


def test_categorical_schwab_leaf_rejected():
    assert not is_valid_schwab_leaf_path("upstream ms_dict / SignalInput")
    with pytest.raises(ValueError, match="categorical"):
        reject_categorical_schwab_leaf("upstream ms_dict / chains.*")


def test_pass_through_requires_schwab_leaves():
    row = TraceableDerivation(
        file="market_data_adapter.py",
        line=62,
        derivation="normalize_bar",
        disposition="PASS_THROUGH",
        inputs=(),
        schwab_leaves=(SchwabLeafRef("pricehistory.candles.datetime"),),
        allowlist_id=None,
        outputs=("bars.datetime",),
        justification="Schwab candle normalized to bar dict.",
    )
    assert_inventory_is_traceable((row,))


def test_keep_derived_requires_structured_inputs():
    row = TraceableDerivation(
        file="market_state.py",
        line=916,
        derivation="build_market_state",
        disposition="KEEP_DERIVED",
        inputs=(
            FieldInputRef(
                carrier="param",
                field="spot",
                producer_file="server.py",
                producer_fn="_build_rest_fast_quote_payload",
            ),
        ),
        schwab_leaves=(),
        allowlist_id=None,
        outputs=("ms_dict.spot", "signal_input.spot"),
        justification="Composes MarketState from Schwab-first quote path.",
    )
    assert_inventory_is_traceable((row,))


def test_none_requires_allowlist_id():
    with pytest.raises(ValueError, match="allowlist_id"):
        TraceableDerivation(
            file="config.py",
            line=1,
            derivation="build_config",
            disposition="NONE",
            inputs=(),
            schwab_leaves=(),
            allowlist_id=None,
            outputs=(),
            justification="Config only.",
        )
