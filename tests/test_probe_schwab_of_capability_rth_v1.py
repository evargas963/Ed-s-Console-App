"""RC-438 — unit tests for OF Schwab capability decode/matrix (no live socket)."""
from __future__ import annotations

from tools.of_schwab_capability_lib import (
    NOT_PROVEN,
    UNAVAILABLE,
    analyze_exchange_semantics,
    analyze_num_semantics,
    apply_live_results_to_matrix,
    decode_book_content_item,
    empty_capability_matrix,
    scan_keys_for_forbidden_concepts,
)


def _sample_book_content(*, num_bids: int, nested_n: int, exchange: str = "Q") -> dict:
    nested = [
        {"EXCHANGE": exchange, "BID_VOLUME": 10 * (i + 1), "SEQUENCE": i}
        for i in range(nested_n)
    ]
    return {
        "SYMBOL": "SPY",
        "BOOK_TIME": 1_700_000_000_000,
        "BIDS": [
            {
                "BID_PRICE": 500.0,
                "TOTAL_VOLUME": sum(10 * (i + 1) for i in range(nested_n)),
                "NUM_BIDS": num_bids,
                "BIDS": nested,
            }
        ],
        "ASKS": [
            {
                "ASK_PRICE": 500.1,
                "TOTAL_VOLUME": 30,
                "NUM_ASKS": 1,
                "ASKS": [{"EXCHANGE": exchange, "ASK_VOLUME": 30, "SEQUENCE": 0}],
            }
        ],
    }


def test_decode_does_not_label_exchange_as_participant():
    dec = decode_book_content_item(_sample_book_content(num_bids=2, nested_n=2))
    assert dec["n_levels"] == 2
    bid = next(lv for lv in dec["levels"] if lv["side"] == "BID")
    assert bid["num_equals_nested_count"] is True
    assert bid["agg_equals_nested_size_sum"] is True
    assert "exchange_code_raw" in bid["exchange_rows"][0]
    blob = str(dec)
    assert "per-participant" not in blob
    assert "mpid" not in blob.lower()
    assert "market_maker" not in blob.lower()


def test_num_semantics_flags_mismatch_without_calling_order_count():
    # NUM_BIDS=5 but only 2 nested rows → measurable mismatch; ruling stays NOT_PROVEN
    dec = decode_book_content_item(_sample_book_content(num_bids=5, nested_n=2))
    analysis = analyze_num_semantics([dec])
    assert analysis["num_ne_nested_count"] >= 1
    assert analysis["ruling"] == NOT_PROVEN
    assert "order-count" in analysis["ruling_note"] or "order count" in analysis["ruling_note"].lower() or "order-count" in analysis["ruling_note"]


def test_exchange_semantics_never_auto_pass():
    dec = decode_book_content_item(_sample_book_content(num_bids=1, nested_n=1, exchange="XNGS"))
    analysis = analyze_exchange_semantics([dec])
    assert analysis["ruling"] == NOT_PROVEN
    assert analysis["unique_exchange_code_raw"] >= 1
    assert "per-participant" in analysis["ruling_note"]


def test_absence_scan_marks_unavailable_when_clean():
    scan = scan_keys_for_forbidden_concepts({"BIDS": [{"BID_PRICE": 1, "TOTAL_VOLUME": 2}]})
    assert scan["noii_ruling"] == UNAVAILABLE
    assert scan["aggressor_ruling"] == UNAVAILABLE


def test_absence_scan_flags_aggressor_key_name():
    scan = scan_keys_for_forbidden_concepts({"tick": {"aggressorSide": "B"}})
    assert scan["aggressor_like_keys"]
    assert scan["aggressor_ruling"] == NOT_PROVEN


def test_empty_matrix_distinguishes_documented_from_live():
    m = empty_capability_matrix(live_ran=False)
    assert m["live_probe_ran"] is False
    assert m["corrections"]
    row = next(r for r in m["rows"] if r["concept"] == "NUM_BIDS / NUM_ASKS")
    assert row["documented_repo_visible"] == "DOCUMENTED"
    assert row["live_entitlement_proof"] == NOT_PROVEN
    assert row["semantics"] == NOT_PROVEN


def test_apply_live_results_can_pass_entitlement_but_not_num_semantics():
    m = empty_capability_matrix(live_ran=False)
    dec = decode_book_content_item(_sample_book_content(num_bids=2, nested_n=2))
    num_a = analyze_num_semantics([dec])
    ex_a = analyze_exchange_semantics([dec])
    out = apply_live_results_to_matrix(
        m,
        book_services={"NASDAQ_BOOK": {"subs_ok": True, "n_frames": 3}},
        num_analysis=num_a,
        exchange_analysis=ex_a,
        timesales={"response_code": 11},
        options_book=None,
        levelone_options=None,
        absence_scan=scan_keys_for_forbidden_concepts({}),
    )
    assert out["live_probe_ran"] is True
    nasdaq = next(r for r in out["rows"] if "NASDAQ_BOOK" in r["concept"])
    assert nasdaq["live_entitlement_proof"] == "PASS"
    num_row = next(r for r in out["rows"] if r["concept"] == "NUM_BIDS / NUM_ASKS")
    assert num_row["live_entitlement_proof"] == "PASS"  # field present
    assert num_row["semantics"] == NOT_PROVEN  # never auto semantic PASS
    ts = next(r for r in out["rows"] if "TIMESALE" in r["concept"])
    assert ts["live_entitlement_proof"] == UNAVAILABLE
