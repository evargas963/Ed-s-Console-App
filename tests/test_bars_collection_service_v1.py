"""RC-69: bar collection is a SERVICE, and price_bars_1m has exactly ONE writer.

Bars used to be persisted only inside `_fetch_state` — the render path — so a ticker's chart
decayed to whenever it was last looked at. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar lag
3.1 min vs QQQ 19.1 and IWM 19.1 (off screen), while all three had ~1.0 min SNAPSHOT lag. The
quotes were current; the bars were not. 39.8% of snapshots (122,795/308,796) carry unfilled
outcomes because fill_outcomes reads price_bars_1m for the forward price and it was never written.

These lock the architecture, not the symptom: collection independent of the viewport, and a
single faucet for the bars table. Since the bars-from-the-stream change the ONLY producer is
Schwab's streamed CHART_EQUITY 1-minute bar (capture daemon -> `bar1m.SYM` push ->
`streamed_bars` -> `_bar_writer` -> `_write_streamed_bar` -> `_persist_1m_bars`); the REST quote
poll and the price-history seeds that used to write here are deleted.
"""
from __future__ import annotations


def test_collection_covers_every_streamed_symbol_not_a_fixed_list(monkeypatch):
    """The writer persists whatever symbol the stream delivers -- no roster, sentinel or viewport
    filter. A hardcoded tuple is how bars once covered 3 of 57 tickers."""
    import server as srv

    written: list[tuple] = []
    monkeypatch.setattr(srv, "_persist_1m_bars", lambda tk, bars: written.append((tk, bars)) or 1)
    for sym in ("ZZA", "ZZB", "QQQ"):
        assert srv._write_streamed_bar({"symbol": sym, "open": 10.0, "high": 11.0, "low": 9.5,
                                        "close": 10.5, "volume": 1200.0,
                                        "bar_start_ms": 1_785_168_000_000}) is True
    assert [tk for tk, _ in written] == ["ZZA", "ZZB", "QQQ"]
    bar = written[0][1][0]
    assert (bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        1_785_168_000.0, 10.0, 11.0, 9.5, 10.5, 1200.0), "ms bar start must land as epoch seconds"


def test_a_streamed_bar_missing_a_field_is_absence_not_a_bar(monkeypatch):
    """Absence must read as absence -- a bar with no open/high/low/close/start is not written,
    never completed from anything else."""
    import server as srv

    written: list = []
    monkeypatch.setattr(srv, "_persist_1m_bars", lambda tk, bars: written.append(tk) or 1)
    full = {"symbol": "ZZG", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
            "volume": 5.0, "bar_start_ms": 1_785_168_000_000}
    for k in ("open", "high", "low", "close", "bar_start_ms"):
        msg = dict(full)
        msg[k] = None
        assert srv._write_streamed_bar(msg) is False, f"a bar without {k} was written"
    assert written == []
    # positive control: the complete bar IS written, so the guard is not refusing everything
    assert srv._write_streamed_bar(full) is True and written == ["ZZG"]
