"""The engine's tape must preserve a missing trade size as missing, not coerce it to zero.

The same missing-vs-zero contract as the live tape state, proved at the print seam. Each trade is a
LEVELONE message as Schwab sent it, taken through the live state (state.push_level_one: the one
reader of LAST_PRICE, LAST_SIZE and TRADE_TIME_MILLIS) in receive order.

Real data: Schwab's LEVELONE_EQUITIES messages of 2026-10-05 14:00:00-14:00:03 CT as the daemon
received them (real_stream_mix_2026_10_05_1400ct.json): RKLB's three prints with no LAST_SIZE then
one with, $SPX's four prints (an index: never a size), SPY's three; and NVDA's print of
2026-10-19 04:00:01 ET that Schwab sent with LAST_SIZE 0 (real_security_status_2026_10_19.json).
Each expected number is the tick rule worked out here from the prices and sizes Schwab sent.
"""

from __future__ import annotations

import json
from pathlib import Path

import app.options.order_flow.engine as ofe
from app.options.order_flow.state import OrderFlowState
from tests.shared_helpers import sent

_FX = Path(__file__).resolve().parent / "fixtures"
_MIX = [
    m
    for m in json.loads(
        (_FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8")
    )["messages"]
    if m["service"] == "LEVELONE_EQUITIES"
]
_NVDA_ZERO = next(
    m
    for m in json.loads((_FX / "real_security_status_2026_10_19.json").read_text(encoding="utf-8"))[
        "messages"
    ]
    if m["symbol"] == "NVDA" and m["item"]["LAST_SIZE"] == 0
)


def _prints(key: str) -> list[tuple]:
    """(LAST_PRICE, LAST_SIZE or None, TRADE_TIME_MILLIS) of each message of `key` with a price."""
    return [
        (i["LAST_PRICE"], i.get("LAST_SIZE"), i["TRADE_TIME_MILLIS"])
        for i in (m["item"] for m in sent(_MIX, key))
        if "LAST_PRICE" in i
    ]


def _data(messages: list[dict]) -> dict:
    """Return the engine's input: the tape a fresh live state recorded from `messages`, in order."""
    state = OrderFlowState()
    for m in messages:
        state.push_level_one(m["item"]["key"], m["item"], ts_recv=m["ts_recv"])
    (key,) = {m["item"]["key"] for m in messages}
    return {"content": state.get_content_for_symbol(key)}


def test_cum_delta_proxy_skips_missing_print_size():
    prints = _prints("RKLB")
    assert [size for _p, size, _t in prints] == [None, None, None, 138]
    assert prints[3][0] < prints[2][0]  # a downtick: the sized print signs negative
    assert ofe._compute_cum_delta_proxy(_data(sent(_MIX, "RKLB"))) == -138


def test_cum_delta_proxy_returns_none_when_all_print_sizes_missing():
    prints = _prints("$SPX")
    assert len(prints) == 4 and all(size is None for _p, size, _t in prints)
    assert ofe._compute_cum_delta_proxy(_data(sent(_MIX, "$SPX"))) is None


def test_a_tape_of_zero_size_prints_sums_to_zero_and_serves_its_window():
    """A print Schwab sent with LAST_SIZE 0 sums to a cumulative delta of 0, not "no value".

    Operator 2026-10-01: "shouldn't be a dash should be 0". The window it sums is served beside
    it -- no clock resets it. NVDA traded 2026-10-19 at 04:00:01 ET, 03:00 AM CT.
    """
    t0 = _NVDA_ZERO["item"]["TRADE_TIME_MILLIS"]
    data = _data([_NVDA_ZERO])
    assert ofe._compute_cum_delta_proxy(data) == 0.0
    flow = ofe.OrderFlowEngine().compute(data, now=t0 / 1000 + 61)
    assert flow["cum_delta_proxy"] == 0.0
    assert flow["cum_delta_window"] == "prints Mon 10/19 03:00 AM CT to Mon 10/19 03:00 AM CT"


def test_tape_pressure_skips_missing_print_size():
    """RKLB's one sized print, a downtick, is all the pressure: -138 / 138."""
    now = _prints("RKLB")[-1][2] / 1000
    assert ofe._compute_tape_pressure(_data(sent(_MIX, "RKLB")), window_sec=60.0, now=now) == -1.0


def test_an_old_tape_has_no_current_window_pressure():
    """Audit O-08: the 30s/2m/5m windows were anchored to the LAST print.

    So a tape whose last
    trade was an hour ago still reported "30-second" pressure as current. Windows end at now;
    prints outside them count for nothing. SPY's prints, judged at its last trade and an hour on.
    """
    data = _data(sent(_MIX, "SPY"))
    last = max(t for _p, _s, t in _prints("SPY")) / 1000
    assert ofe._compute_tape_pressure(data, window_sec=30.0, now=last) is not None
    assert ofe._compute_tape_pressure(data, window_sec=30.0, now=last + 3600) is None
    assert ofe._compute_cum_delta_slope(data, now=last + 3600, window_sec=60.0) is None
