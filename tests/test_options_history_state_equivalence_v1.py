"""Persisted and live option observations share one canonical state owner.

# universal-scope-ok: the three contracts are real captured QQQ/SPY/TSLA
observations selected to reproduce the demonstrated defect, not product scope.
"""
from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.history as history
import app.options.order_flow.streaming as streaming
import app.options.order_flow.state as live_state
from app.api.routes.options_order_flow import options_history
from app.options.order_flow.live_payload import options_live_payload
from app.options.order_flow.state import MAX_BOOK_SNAPSHOTS, OrderFlowState
from stream_spine import STREAM_SCHEMA_SQL


FIXTURE = (
    Path(__file__).parent / "fixtures" / "real_options_stream_history_samples.json"
)


def _samples() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["contracts"]


def _sample(symbol: str) -> dict:
    return next(row for row in _samples() if row["symbol"] == symbol)


def _write_db(path: Path, samples: list[dict]) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(STREAM_SCHEMA_SQL)
        for sample in samples:
            symbol = sample["symbol"]
            for event in sample["events"]:
                if event["kind"] == "l1":
                    con.execute(
                        "INSERT INTO stream_options_quotes_raw"
                        "(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
                        (
                            event["ts_recv"],
                            symbol,
                            json.dumps(event["content"]),
                            event["source"],
                        ),
                    )
                else:
                    con.execute(
                        "INSERT INTO stream_book_raw"
                        "(ts_recv,symbol,service,native_json,src) VALUES(?,?,?,?,?)",
                        (
                            event["ts_recv"],
                            symbol,
                            "OPTIONS_BOOK",
                            json.dumps(event["content"]),
                            event["source"],
                        ),
                    )
        con.commit()
    finally:
        con.close()


def _apply(state: OrderFlowState, sample: dict) -> None:
    symbol = sample["symbol"]
    for event in sample["events"]:
        if event["kind"] == "l1":
            state.push_level_one(symbol, event["content"], ts_recv=event["ts_recv"])
        else:
            state.push_book(symbol, event["content"])


def _fixed_evaluation_time(sample: dict) -> float:
    return max(event["ts_recv"] for event in sample["events"]) + 60.0


def _point_history_at(monkeypatch, db: Path) -> None:
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(db.resolve()))


@pytest.mark.parametrize(
    "symbol",
    [
        "TSLA  260831C00367500",
        "QQQ   260904C00712500",
        "SPY   260904C00772000",
    ],
)
def test_real_persisted_history_equals_normal_canonical_ingestion(
    tmp_path, monkeypatch, symbol
):
    sample = _sample(symbol)
    db = tmp_path / "stream_capture.db"
    _write_db(db, [sample])
    _point_history_at(monkeypatch, db)
    evaluation_time = _fixed_evaluation_time(sample)
    monkeypatch.setattr(time, "time", lambda: evaluation_time)

    normal = OrderFlowState()
    _apply(normal, sample)
    normal_content = normal.get_content_for_symbol(symbol)
    historical_content = history.hydrate_option_content(
        symbol, since_ts=0, db_path=db
    )

    assert historical_content == normal_content
    assert options_live_payload(
        symbol, content=historical_content
    ) == options_live_payload(symbol, content=normal_content)


def test_stale_real_tsla_sizes_fail_closed_in_both_paths(tmp_path, monkeypatch):
    sample = _sample("TSLA  260831C00367500")
    db = tmp_path / "stream_capture.db"
    _write_db(db, [sample])
    _point_history_at(monkeypatch, db)
    monkeypatch.setattr(time, "time", lambda: _fixed_evaluation_time(sample))

    normal = OrderFlowState()
    _apply(normal, sample)
    historical = history.hydrate_option_content(
        sample["symbol"], since_ts=0, db_path=db
    )
    expected = options_live_payload(
        sample["symbol"], content=normal.get_content_for_symbol(sample["symbol"])
    )
    actual = options_live_payload(sample["symbol"], content=historical)

    assert actual == expected
    assert actual["top_of_book"]["bid_size"] is None
    assert actual["top_of_book"]["ask_size"] is None
    assert actual["microprice"] is None
    assert actual["flow"]["top_book_pressure"] is None


def test_history_inherits_partial_zero_stale_and_recovery_semantics(
    tmp_path, monkeypatch
):
    symbol = "TSLA  260831C00367500"
    base = {
        "key": symbol,
        "BID_PRICE": 0.58,
        "ASK_PRICE": 0.61,
        "BID_SIZE": 30,
        "ASK_SIZE": 37,
    }
    zero_size_delta = {"key": symbol, "BID_SIZE": 0}
    fresh = {
        "key": symbol,
        "BID_PRICE": 0.59,
        "ASK_PRICE": 0.62,
        "BID_SIZE": 12,
        "ASK_SIZE": 14,
    }
    events = [
        {
            "kind": "l1",
            "ts_recv": 1_000.0,
            "source": "schwab_options_l1",
            "content": base,
        },
        {
            "kind": "l1",
            "ts_recv": 1_005.0,
            "source": "schwab_options_l1",
            "content": zero_size_delta,
        },
    ]
    sample = {"symbol": symbol, "events": events}
    db = tmp_path / "stream_capture.db"
    _write_db(db, [sample])
    _point_history_at(monkeypatch, db)
    clock = {"now": 1_006.0}
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    normal = OrderFlowState()
    _apply(normal, sample)

    def assert_equal() -> dict:
        expected = options_live_payload(
            symbol, content=normal.get_content_for_symbol(symbol)
        )
        actual = options_live_payload(
            symbol,
            content=history.hydrate_option_content(symbol, since_ts=0, db_path=db),
        )
        assert actual == expected
        return actual

    current = assert_equal()
    assert current["top_of_book"]["bid_size"] == 0
    assert current["top_of_book"]["ask_size"] == 37

    clock["now"] = 1_031.0
    stale = assert_equal()
    assert stale["top_of_book"]["bid_size"] is None
    assert stale["top_of_book"]["ask_size"] is None
    assert stale["flow"]["top_book_pressure"] is None

    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO stream_options_quotes_raw"
            "(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
            (1_032.0, symbol, json.dumps(fresh), "schwab_options_l1"),
        )
        con.commit()
    finally:
        con.close()
    normal.push_level_one(symbol, fresh, ts_recv=1_032.0)
    clock["now"] = 1_033.0
    recovered = assert_equal()
    assert recovered["top_of_book"]["bid_size"] == 12
    assert recovered["top_of_book"]["ask_size"] == 14
    assert recovered["flow"]["top_book_pressure"] == pytest.approx(-2 / 26)


def test_history_uses_canonical_restatement_owner(tmp_path, monkeypatch):
    sample = _sample("TSLA  260831C00367500")
    source = next(
        event
        for event in sample["events"]
        if event["kind"] == "l1" and "LAST_PRICE" in event["content"]
    )
    repeated = {
        "symbol": sample["symbol"],
        "events": [
            dict(source, ts_recv=2_000.0),
            dict(source, ts_recv=2_001.0),
        ],
    }
    db = tmp_path / "stream_capture.db"
    _write_db(db, [repeated])
    _point_history_at(monkeypatch, db)
    captured = OrderFlowState()
    monkeypatch.setattr(history, "OrderFlowState", lambda: captured)

    content = history.hydrate_option_content(
        sample["symbol"], since_ts=0, db_path=db
    )
    receipts = captured.get_receive_log(sample["symbol"])
    tape = [item for item in content if "receive_seq" in item]

    assert [row["receive_seq"] for row in receipts] == [1, 2]
    assert [row["is_restatement"] for row in receipts] == [False, True]
    assert len(tape) == 1


def test_history_applies_events_in_receive_order_with_existing_tie_rule(
    tmp_path, monkeypatch
):
    sample = _sample("TSLA  260831C00367500")
    l1 = next(event for event in sample["events"] if event["kind"] == "l1")
    book = next(event for event in sample["events"] if event["kind"] == "book")
    tied = {
        "symbol": sample["symbol"],
        "events": [
            dict(book, ts_recv=3_000.0),
            dict(l1, ts_recv=3_000.0),
        ],
    }
    db = tmp_path / "stream_capture.db"
    _write_db(db, [tied])
    _point_history_at(monkeypatch, db)

    class RecordingState(OrderFlowState):
        def __init__(self):
            super().__init__()
            self.calls = []

        def push_level_one(self, symbol, content_item, ts_recv=None):
            self.calls.append(("l1", ts_recv))
            super().push_level_one(symbol, content_item, ts_recv=ts_recv)

        def push_book(self, symbol, content_item):
            self.calls.append(("book", 3_000.0))
            super().push_book(symbol, content_item)

    captured = RecordingState()
    monkeypatch.setattr(history, "OrderFlowState", lambda: captured)
    history.hydrate_option_content(sample["symbol"], since_ts=0, db_path=db)

    assert captured.calls == [("l1", 3_000.0), ("book", 3_000.0)]


def test_canonical_book_state_is_bounded_and_contract_isolated():
    samples = _samples()
    first, second = samples[0], samples[1]
    first_book = next(e for e in first["events"] if e["kind"] == "book")["content"]
    second_book = next(e for e in second["events"] if e["kind"] == "book")["content"]
    state = OrderFlowState()

    base_time = int(first_book["BOOK_TIME"])
    for i in range(MAX_BOOK_SNAPSHOTS + 5):
        state.push_book(first["symbol"], dict(first_book, BOOK_TIME=base_time + i))
    state.push_book(second["symbol"], second_book)

    first_content = state.get_content_for_symbol(first["symbol"])
    second_content = state.get_content_for_symbol(second["symbol"])
    first_books = [row for row in first_content if "BIDS" in row]
    assert len(first_books) == MAX_BOOK_SNAPSHOTS
    assert first_books[0]["BOOK_TIME"] == base_time + 5
    assert first_books[-1]["BOOK_TIME"] == base_time + MAX_BOOK_SNAPSHOTS + 4
    assert all(row.get("BOOK_TIME") != second_book["BOOK_TIME"] for row in first_books)
    assert len([row for row in second_content if "BIDS" in row]) == 1
    assert options_live_payload("MISSING", content=[])["status"] == "no_book"


def test_history_requests_are_isolated_from_live_and_each_other(
    tmp_path, monkeypatch
):
    samples = _samples()
    db = tmp_path / "stream_capture.db"
    _write_db(db, samples)
    _point_history_at(monkeypatch, db)
    live_state.clear_all_live_state()
    sentinel = samples[0]
    first_l1 = next(e for e in sentinel["events"] if e["kind"] == "l1")
    live_state.push_level_one(
        sentinel["symbol"], first_l1["content"], ts_recv=first_l1["ts_recv"]
    )
    before_content = live_state.get_content_for_symbol(sentinel["symbol"])
    before_stats = live_state.get_stats()
    before_receipts = live_state.get_receive_log(sentinel["symbol"])
    monkeypatch.setattr(
        time, "time", lambda: max(_fixed_evaluation_time(s) for s in samples)
    )

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(
                history.hydrate_option_content,
                sample["symbol"],
                since_ts=0,
                db_path=db,
            )
            for sample in samples
        ]
        results = [future.result(timeout=10) for future in futures]

    assert all(results)
    assert live_state.get_content_for_symbol(sentinel["symbol"]) == before_content
    assert live_state.get_stats() == before_stats
    assert live_state.get_receive_log(sentinel["symbol"]) == before_receipts
    assert len({result[-1].get("BID_PRICE") for result in results}) > 1
    live_state.clear_all_live_state()


def test_live_replay_cursor_preserves_later_rows_with_equal_receive_time(
    tmp_path, monkeypatch
):
    sample = _sample("TSLA  260831C00367500")
    l1_rows = [
        event
        for event in sample["events"]
        if event["kind"] == "l1" and "LAST_PRICE" in event["content"]
    ][:2]
    book_rows = [event for event in sample["events"] if event["kind"] == "book"][:2]
    first = {
        "symbol": sample["symbol"],
        "events": [
            dict(l1_rows[0], ts_recv=5_000.0),
            dict(book_rows[0], ts_recv=5_000.0),
        ],
    }
    db = tmp_path / "stream_capture.db"
    _write_db(db, [first])
    _point_history_at(monkeypatch, db)
    monkeypatch.setattr(time, "time", lambda: 5_001.0)
    live_state.clear_all_live_state()
    streaming._option_l1_cursor = {}
    streaming._option_book_cursor = {}

    con = streaming._open_capture_db_readonly(db)
    assert con is not None
    streaming._replay_option_contract_rows(con, sample["symbol"])
    con.close()

    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO stream_options_quotes_raw"
            "(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
            (
                5_000.0,
                sample["symbol"],
                json.dumps(l1_rows[1]["content"]),
                l1_rows[1]["source"],
            ),
        )
        con.execute(
            "INSERT INTO stream_book_raw"
            "(ts_recv,symbol,service,native_json,src) VALUES(?,?,?,?,?)",
            (
                5_000.0,
                sample["symbol"],
                "OPTIONS_BOOK",
                json.dumps(book_rows[1]["content"]),
                book_rows[1]["source"],
            ),
        )
        con.commit()
    finally:
        con.close()

    con = streaming._open_capture_db_readonly(db)
    assert con is not None
    streaming._replay_option_contract_rows(con, sample["symbol"])
    con.close()

    expected = live_state.get_content_for_symbol(sample["symbol"])
    actual = history.hydrate_option_content(
        sample["symbol"], since_ts=0, db_path=db
    )
    assert actual == expected
    assert len(live_state.get_receive_log(sample["symbol"])) == 2
    assert len([row for row in expected if "BIDS" in row]) == 2
    assert streaming._option_l1_cursor[sample["symbol"]][0] == 5_000.0
    assert streaming._option_l1_cursor[sample["symbol"]][1] > 1
    assert streaming._option_book_cursor[sample["symbol"]][0] == 5_000.0
    assert streaming._option_book_cursor[sample["symbol"]][1] > 1
    live_state.clear_all_live_state()


def test_isolated_state_created_during_rth_keeps_earlier_book(
    tmp_path, monkeypatch
):
    sample = _sample("QQQ   260904C00712500")
    book = next(event for event in sample["events"] if event["kind"] == "book")
    l1 = next(event for event in sample["events"] if event["kind"] == "l1")
    ordered = {
        "symbol": sample["symbol"],
        "events": [
            dict(book, ts_recv=6_000.0),
            dict(l1, ts_recv=6_001.0),
        ],
    }
    db = tmp_path / "stream_capture.db"
    _write_db(db, [ordered])
    _point_history_at(monkeypatch, db)
    monkeypatch.setattr(live_state, "is_rth_open", lambda: True)
    monkeypatch.setattr(
        live_state, "now_et", lambda: datetime(2026, 9, 8, 10, 0)
    )

    normal = OrderFlowState()
    _apply(normal, ordered)
    historical = history.hydrate_option_content(
        sample["symbol"], since_ts=0, db_path=db
    )

    assert historical == normal.get_content_for_symbol(sample["symbol"])
    assert len([row for row in historical if "BIDS" in row]) == 1


def test_history_api_serializes_the_same_canonical_payload(tmp_path, monkeypatch):
    sample = _sample("QQQ   260904C00712500")
    db = tmp_path / "stream_capture.db"
    _write_db(db, [sample])
    evaluation_time = _fixed_evaluation_time(sample)
    monkeypatch.setattr(time, "time", lambda: evaluation_time)
    monkeypatch.setenv("STREAM_CAPTURE_DB_PATH", str(db.resolve()))

    content = history.hydrate_option_content(
        sample["symbol"], since_ts=evaluation_time - 900, db_path=db
    )
    expected = options_live_payload(sample["symbol"], content=content)
    response = options_history(contract=sample["symbol"], minutes=15)
    body = json.loads(response.body)

    for key, value in expected.items():
        assert body[key] == value
    assert body["contract"] == sample["symbol"]
    assert body["history_minutes"] == 15.0
    assert body["history_n"] == len(content)


def test_history_missing_and_malformed_inputs_fail_closed(tmp_path, monkeypatch):
    sample = _sample("QQQ   260904C00712500")
    symbol = sample["symbol"]
    _point_history_at(monkeypatch, tmp_path / "unavailable.db")
    assert history.hydrate_option_content(symbol, since_ts=0) == []

    l1_only = {
        "symbol": symbol,
        "events": [next(e for e in sample["events"] if e["kind"] == "l1")],
    }
    l1_db = tmp_path / "l1-only.db"
    _write_db(l1_db, [l1_only])
    _point_history_at(monkeypatch, l1_db)
    l1_content = history.hydrate_option_content(symbol, since_ts=0)
    assert l1_content
    assert options_live_payload(symbol, content=l1_content)["status"] == "no_book"

    book_only = {
        "symbol": symbol,
        "events": [next(e for e in sample["events"] if e["kind"] == "book")],
    }
    book_db = tmp_path / "book-only.db"
    _write_db(book_db, [book_only])
    con = sqlite3.connect(book_db)
    try:
        con.execute(
            "INSERT INTO stream_options_quotes_raw"
            "(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
            (4_000.0, symbol, "{malformed", "schwab_options_l1"),
        )
        con.commit()
    finally:
        con.close()
    _point_history_at(monkeypatch, book_db)
    book_content = history.hydrate_option_content(symbol, since_ts=0)
    payload = options_live_payload(symbol, content=book_content)
    assert len([row for row in book_content if "BIDS" in row]) == 1
    assert not any("LAST_PRICE" in row for row in book_content)
    assert payload["top_of_book"]["bid_size"] is None
    assert payload["top_of_book"]["ask_size"] is None
