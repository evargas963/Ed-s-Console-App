"""order_flow_engine._iter_tape_prints must preserve a missing trade size as
missing, not coerce it to zero -- the same missing-vs-zero contract as the live
tape state, proved here at the print-iteration seam specifically."""
from __future__ import annotations

import app.options.order_flow.engine as ofe




def test_cum_delta_proxy_skips_missing_print_size():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
        ]
    }

    assert ofe._compute_cum_delta_proxy(data) == 10


def test_cum_delta_proxy_returns_none_when_all_print_sizes_missing():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 499.9, "TRADE_TIME_MILLIS": 2_000},
        ]
    }

    assert ofe._compute_cum_delta_proxy(data) is None


def test_tape_pressure_skips_missing_print_size():
    data = {
        "content": [
            {"LAST_PRICE": 500.0, "TRADE_TIME_MILLIS": 1_000},
            {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000},
        ]
    }

    assert ofe._compute_tape_pressure(data, window_sec=60.0, now=2.0) == 1.0


def test_legacy_p1_absorption_is_retired_one_faucet():
    """Mission TRUTH_V1 lock: the legacy P1 `_compute_absorption` (a volume/price-range density
    mislabeled 'absorption', dead-ended with zero consumers) was RETIRED. This fails if it is
    reintroduced, and pins that the engine output no longer carries its keys — so the only
    `absorption_score` authority is institutional_behavior (P2), i.e. ONE FAUCET for the name."""
    assert not hasattr(ofe, "_compute_absorption"), "legacy P1 _compute_absorption must stay retired"
    out = ofe.OrderFlowEngine().compute({"content": [
        {"BIDS": [{"BID_PRICE": 9.9, "TOTAL_VOLUME": 100}], "ASKS": [{"ASK_PRICE": 10.1, "TOTAL_VOLUME": 100}]},
        {"LAST_PRICE": 10.0, "LAST_SIZE": 4, "TRADE_TIME_MILLIS": 1_000},
    ]})
    for k in ("absorption_score", "replenishment_score", "absorption_direction", "replenishment_score_source"):
        assert k not in out, f"engine output must not re-emit retired P1 key {k!r}"


def test_an_old_tape_has_no_current_window_pressure():
    """Audit O-08: the 30s/2m/5m windows were anchored to the LAST print, so a tape whose last
    trade was an hour ago still reported "30-second" pressure as current. Windows end at now;
    prints outside them count for nothing. Stand-in prints (named): two trades at t=1 s and 2 s."""
    data = {"content": [{"LAST_PRICE": 500.0, "LAST_SIZE": 5, "TRADE_TIME_MILLIS": 1_000},
                        {"LAST_PRICE": 500.1, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 2_000}]}
    assert ofe._compute_tape_pressure(data, window_sec=30.0, now=2.0) is not None
    assert ofe._compute_tape_pressure(data, window_sec=30.0, now=2.0 + 3600) is None
    assert ofe._compute_cum_delta_slope(data, now=2.0 + 3600, window_sec=60.0) is None
