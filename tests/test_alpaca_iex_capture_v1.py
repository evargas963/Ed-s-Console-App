"""ISOLATED Alpaca IEX research collector — the capture logic MOVED out of the canonical daemon,
plus the negative control that it can never write the canonical Schwab capture db.

Nothing here infers signing, aggressor side, or CVD — the collector stays raw, and nothing it
writes enters Decide.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import alpaca_iex_capture as ac  # noqa: E402


def test_rfc3339_nanoseconds_trim_to_ms():
    """Alpaca stamps carry 9-digit fractions; fromisoformat takes 6 — the trim must hold."""
    assert ac.alpaca_rfc3339_to_ms("2026-07-22T20:22:23.626206217Z") == 1784751743626
    assert ac.alpaca_rfc3339_to_ms("2026-07-22T20:22:23Z") == 1784751743000
    assert ac.alpaca_rfc3339_to_ms(None) is None
    assert ac.alpaca_rfc3339_to_ms("garbage") is None


def test_item_to_row_shapes_prints_and_quotes_and_skips_the_rest():
    trade = {"T": "t", "S": "SPY", "i": 52983945511779, "x": "V", "p": 748.6, "s": 40,
             "c": [" ", "T"], "t": "2026-07-22T20:22:23.626206217Z", "z": "B"}
    quote = {"T": "q", "S": "SPY", "bx": "V", "bp": 748.37, "bs": 80, "ax": "V",
             "ap": 748.99, "as": 80, "c": ["R"], "t": "2026-07-22T20:31:07.643443439Z", "z": "B"}
    kind, row = ac.alpaca_item_to_row(trade, received_ts=1.0)
    assert kind == "print"
    assert row == (1.0, "SPY", 748.6, 40, "V", " ,T", 1784751743626, "alpaca_iex")
    kind, row = ac.alpaca_item_to_row(quote, received_ts=2.0)
    assert kind == "quote"
    assert row == (2.0, "SPY", 748.37, 748.99, 80, 80, 1784752267643, "alpaca_iex")
    # control/subscription/bar/no-symbol frames are NOT captured (bars stay Schwab's authority).
    for skip in ({"T": "success", "msg": "authenticated"}, {"T": "subscription", "trades": ["SPY"]},
                 {"T": "b", "S": "SPY", "o": 1, "c": 2}, {"T": "t", "p": 1.0}):
        assert ac.alpaca_item_to_row(skip, received_ts=0.0) is None


def test_store_round_trips_to_its_own_tables(tmp_path):
    store = ac.AlpacaCaptureStore(tmp_path / "alpaca_capture.db", batch_max=1)
    store.write("print", (1.0, "SPY", 748.6, 40, "V", " ,T", 1784751743626, "alpaca_iex"))
    store.write("quote", (2.0, "SPY", 748.37, 748.99, 80, 80, 1784751267643, "alpaca_iex"))
    store.close()
    con = sqlite3.connect(tmp_path / "alpaca_capture.db")
    try:
        p = con.execute("SELECT symbol, price, size, exchange, conditions, trade_ts_ms, src "
                        "FROM alpaca_prints_raw").fetchall()
        q = con.execute("SELECT symbol, bid, ask, bid_size, ask_size, src "
                        "FROM alpaca_quotes_raw").fetchall()
    finally:
        con.close()
    assert p == [("SPY", 748.6, 40, "V", " ,T", 1784751743626, "alpaca_iex")]
    assert q == [("SPY", 748.37, 748.99, 80, 80, "alpaca_iex")]


def test_the_collector_cannot_write_the_canonical_or_operational_db(tmp_path):
    """NEGATIVE CONTROL #2: the isolated research collector must NEVER write stream_capture.db (the
    Schwab Collect db) or ed_console.db (the operational db). The store refuses them at construction,
    and its default target is its OWN alpaca_capture.db."""
    assert ac.ALPACA_DB_DEFAULT.name == "alpaca_capture.db"
    for forbidden in ("stream_capture.db", "ed_console.db"):
        with pytest.raises(ValueError):
            ac.AlpacaCaptureStore(tmp_path / forbidden)
        # and via a traversal/relative path that resolves to the forbidden name
        with pytest.raises(ValueError):
            ac.AlpacaCaptureStore(tmp_path / "sub" / ".." / forbidden)
    # a non-canonical name is fine and creates only that file.
    ok = ac.AlpacaCaptureStore(tmp_path / "alpaca_capture.db")
    ok.close()
    assert (tmp_path / "alpaca_capture.db").is_file()
    assert not (tmp_path / "stream_capture.db").exists()


def test_pump_skips_cleanly_without_keys(tmp_path, monkeypatch, capsys):
    """No keys is a clean no-op — the collector never raises into its caller."""
    monkeypatch.setattr(ac, "ALPACA_ENV_PATH", tmp_path / "missing.env")
    for var in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    store = ac.AlpacaCaptureStore(tmp_path / "alpaca_capture.db")

    async def go():
        await ac.alpaca_pump(["SPY"], store, asyncio.Event())

    asyncio.run(go())
    store.close()
    assert "collector idle" in capsys.readouterr().out


def test_session_recycles_on_a_silent_half_open_socket(tmp_path, monkeypatch):
    """A half-open socket raises NOTHING — the session must return True (recycle) once quiet passes
    the bar, instead of spinning on timeouts forever."""
    import json as _json

    monkeypatch.setattr(ac, "ALPACA_STALE_RECONNECT_SEC", 0.05)
    store = ac.AlpacaCaptureStore(tmp_path / "alpaca_capture.db")

    class FakeWS:
        def __init__(self):
            self.frames = [_json.dumps([{"T": "success", "msg": "connected"}]),
                           _json.dumps([{"T": "success", "msg": "authenticated"}])]
            self.sent: list = []

        async def recv(self):
            if self.frames:
                return self.frames.pop(0)
            await asyncio.sleep(3600)   # half-open: silent forever, no exception
            return None

        async def send(self, data):
            self.sent.append(data)

    async def _run():
        return await asyncio.wait_for(
            ac._alpaca_session(FakeWS(), ["SPY"], "k", "s", store, asyncio.Event()), timeout=10)

    assert asyncio.run(_run()) is True, "silent socket must signal recycle, not hang"
    store.close()
