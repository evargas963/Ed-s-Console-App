"""Order flow computes nothing in the page (P1-3, PR C): the book heatmap's default window, each
cell's dominant side and the colour scale's top are served; so are an option contract's put/call
(Schwab's CONTRACT_TYPE) and its subscription state. Book rows are real TSLA NASDAQ_BOOK messages
(tests/fixtures/real_tsla_book_rows.json)."""
import json
import sqlite3
from pathlib import Path

import pytest

from app.options.order_flow import streaming as S
from app.options.order_flow.history import DISPLAY_TAIL_SHARE, book_heatmap_for_ticker, put_call_side
from stream_spine import STREAM_SCHEMA_SQL

_FX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_tsla_book_rows.json").read_text(encoding="utf-8"))


@pytest.fixture
def heat(tmp_path):
    db = tmp_path / "stream_capture.db"
    con = sqlite3.connect(db)
    con.executescript(STREAM_SCHEMA_SQL)
    con.executemany("INSERT INTO stream_book_raw(ts_recv,service,symbol,native_json,src) VALUES(?,?,?,?,?)",
                    [(ts, svc, "TSLA", json.dumps(nat), "schwab_book") for ts, svc, nat in _FX["rows"]])
    con.commit(); con.close()
    d = book_heatmap_for_ticker("TSLA", "NASDAQ_BOOK", minutes=240, db_path=db)
    assert d["available"] is True and len(d["cells"]) > 50
    return d


def _sizes(c):
    return [v for v in (c["bid"], c["ask"]) if v is not None]


def test_each_cell_carries_its_dominant_side_and_the_scale_top(heat):
    """A side Schwab sent no level for at a price is absent (None), never 0; the cell's side is
    the one Schwab sent, or the larger of the two."""
    one_sided = 0
    for c in heat["cells"]:
        b, a = c["bid"], c["ask"]
        assert _sizes(c), c
        one_sided += b is None or a is None
        want = "BID" if a is None else "ASK" if b is None else "BID" if b > a else "ASK" if a > b else "EVEN"
        assert c["side"] == want
    assert one_sided, "real TSLA books: a price carries a bid or an ask, rarely both"
    assert heat["max_size"] == max(v for c in heat["cells"] for v in _sizes(c))


def test_the_default_window_drops_the_thin_tails(heat):
    totals = {}
    for c in heat["cells"]:
        totals[c["price"]] = totals.get(c["price"], 0.0) + sum(_sizes(c))
    whole, cum, inside = sum(totals.values()), 0.0, []
    for px in sorted(totals):
        cum += totals[px]
        if DISPLAY_TAIL_SHARE <= cum / whole <= 1 - DISPLAY_TAIL_SHARE:
            inside.append(px)
    assert heat["display_lo"] == inside[0] and heat["display_hi"] == inside[-1]
    assert heat["price_min"] <= heat["display_lo"] < heat["display_hi"] <= heat["price_max"]


def test_put_call_is_schwabs_contract_type():
    assert [put_call_side(v) for v in ("C", "P", None, "X")] == ["CALL", "PUT", None, None]


@pytest.mark.parametrize("l1, book, want", [
    ({"Q"}, {"Q"}, "SUBSCRIBED"),          # the producer holds the queried contract on both services
    ({"Z"}, {"Z"}, "MOVED"),               # both services hold one other contract
    ({"Q"}, set(), "PENDING"),             # only one service has it yet
])
def test_the_subscription_state_is_served(monkeypatch, l1, book, want):
    monkeypatch.setattr(S, "_active_option_contract", "Q")
    monkeypatch.setattr(S, "_read_producer_option_contracts", lambda: {"LEVELONE_OPTIONS": l1, "OPTIONS_BOOK": book})
    monkeypatch.setattr(S, "_pick_producer_contract", lambda held, q: q if q in held else next(iter(held), None))
    assert S.get_option_contract_streaming_diagnostics(for_contract="Q")["subscription_state"] == want


def test_the_window_ends_at_the_newest_book_with_levels_not_the_empty_after_close_snapshots(tmp_path):
    """After the close Schwab keeps sending empty book snapshots (measured 2026-09-27: SPY's latest
    NASDAQ_BOOK message is {"key": "SPY", "BOOK_TIME": ..., "BIDS": [], "ASKS": []}); anchoring the
    window on those left the heatmap blank all weekend."""
    db = tmp_path / "stream_capture.db"
    last = _FX["rows"][-1][0]
    empties = [(last + 3600 * h, "NASDAQ_BOOK", {"key": "TSLA", "BOOK_TIME": int((last + 3600 * h) * 1000), "BIDS": [], "ASKS": []})
               for h in range(1, 40)]
    con = sqlite3.connect(db)
    con.executescript(STREAM_SCHEMA_SQL)
    con.executemany("INSERT INTO stream_book_raw(ts_recv,service,symbol,native_json,src) VALUES(?,?,?,?,?)",
                    [(ts, svc, "TSLA", json.dumps(nat), "schwab_book") for ts, svc, nat in _FX["rows"] + empties])
    con.commit(); con.close()
    d = book_heatmap_for_ticker("TSLA", "NASDAQ_BOOK", minutes=60, db_path=db)
    assert d["available"] is True and d["cells"]
    assert d["until_ts"] == last
