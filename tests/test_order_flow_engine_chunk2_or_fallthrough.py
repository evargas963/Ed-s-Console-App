"""order_flow_engine chunk-2: FIND-OF1/OF2 — preserve 0.0 through book/tape score selection."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

from order_flow_engine import OrderFlowEngine, _compute_order_flow_score


def _book_side_effect(values: dict[int, float | None]):
    def _fn(_data: dict, depth: int) -> float | None:
        return values.get(depth)

    return _fn


def _tape_side_effect(values: dict[float, float | None]):
    def _fn(_data: dict, window_sec: float) -> float | None:
        return values.get(window_sec)

    return _fn


def _run_compute_capture_score_inputs(
    *,
    book: dict[int, float | None] | None = None,
    tape: dict[float, float | None] | None = None,
) -> tuple[float | None, float | None]:
    with ExitStack() as stack:
        if book is not None:
            stack.enter_context(
                patch(
                    "order_flow_engine._compute_book_imbalance",
                    side_effect=_book_side_effect(book),
                )
            )
        if tape is not None:
            stack.enter_context(
                patch(
                    "order_flow_engine._compute_tape_pressure",
                    side_effect=_tape_side_effect(tape),
                )
            )
        score_fn = stack.enter_context(
            patch(
                "order_flow_engine._compute_order_flow_score",
                wraps=_compute_order_flow_score,
            )
        )
        OrderFlowEngine().compute({"quote": {}})
    args = score_fn.call_args[0]
    return args[0], args[1]


def test_book_for_score_preserves_zero_at_depth_5():
    book, _tape = _run_compute_capture_score_inputs(
        book={5: 0.0, 3: 0.5, 1: None},
        tape={120.0: None, 30.0: None, 300.0: None},
    )
    assert book == 0.0


def test_book_for_score_falls_through_to_depth_3_when_depth_5_missing():
    book, _tape = _run_compute_capture_score_inputs(
        book={5: None, 3: 0.5, 1: -0.2},
        tape={120.0: None, 30.0: None, 300.0: None},
    )
    assert book == 0.5


def test_book_for_score_falls_through_to_depth_1():
    book, _tape = _run_compute_capture_score_inputs(
        book={5: None, 3: None, 1: -0.3},
        tape={120.0: None, 30.0: None, 300.0: None},
    )
    assert book == -0.3


def test_book_for_score_none_when_all_depths_missing():
    book, _tape = _run_compute_capture_score_inputs(
        book={5: None, 3: None, 1: None},
        tape={120.0: None, 30.0: None, 300.0: None},
    )
    assert book is None


def test_tape_for_score_preserves_zero_at_2m_window():
    _book, tape = _run_compute_capture_score_inputs(
        book={5: None, 3: None, 1: None},
        tape={120.0: 0.0, 30.0: 0.5, 300.0: None},
    )
    assert tape == 0.0


def _balanced_five_level_book_content() -> dict:
    """Depth-5 balanced book; depth-3 imbalanced (OF1 regression fixture)."""
    bid_vols_l13 = [125.0, 125.0, 125.0]
    ask_vols_l13 = [42.0, 42.0, 42.0]
    bid_vols_l45 = [13.0, 13.0]
    ask_vols_l45 = [137.5, 137.5]
    bids = [
        {"BID_PRICE": 100.0 - i * 0.01, "TOTAL_VOLUME": v}
        for i, v in enumerate(bid_vols_l13 + bid_vols_l45)
    ]
    asks = [
        {"ASK_PRICE": 100.05 + i * 0.01, "TOTAL_VOLUME": v}
        for i, v in enumerate(ask_vols_l13 + ask_vols_l45)
    ]
    return {"content": [{"BIDS": bids, "ASKS": asks}]}


def test_compute_score_uses_depth_5_zero_not_depth_3_fallback():
    data = _balanced_five_level_book_content()
    from order_flow_engine import _compute_book_imbalance

    assert _compute_book_imbalance(data, 5) == 0.0
    depth3 = _compute_book_imbalance(data, 3)
    assert depth3 is not None
    assert abs(depth3 - 0.5) < 0.02

    # Chunk-3 requires ≥2 present legs for a composite; neutral tape pairs with depth-5 zero book.
    with patch("order_flow_engine._compute_tape_pressure", return_value=0.0):
        out = OrderFlowEngine().compute(data)
    score_with_depth5_zero = out["order_flow_score"]
    score_if_depth3_substituted = _compute_order_flow_score(
        _compute_book_imbalance(data, 3),
        0.0,
        None,
        None,
        None,
        None,
    )
    assert score_with_depth5_zero is not None
    assert abs(score_with_depth5_zero) < 0.01
    assert score_if_depth3_substituted is not None
    assert score_if_depth3_substituted > 0.1
    assert out["book_imbalance_5"] == 0.0
