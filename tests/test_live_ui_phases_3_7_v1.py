"""Instant-UI Phases 3–7 seams. Each expected value is independently derived."""
from __future__ import annotations


def test_token_write_is_atomic_temp_replace(tmp_path):
    from schwab_client import write_token_file_atomically

    dest = tmp_path / "schwab_token.json"
    payload = {"access_token": "aaa", "refresh_token": "bbb"}
    write_token_file_atomically(str(dest), payload)
    text = dest.read_text(encoding="utf-8")
    assert '"access_token": "aaa"' in text
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], leftovers


def test_forming_bar_overlay_uses_plane_last(monkeypatch):
    """The overlay's forming minute is live_price_rows.forming_bar -- the streamed LAST_PRICE
    folded in by the plane's row listener -- merged onto that minute's bar."""
    import live_price_rows as lpr
    import server as srv

    tk = "ZZFORM"
    monkeypatch.setattr(lpr, "_forming", {})
    monkeypatch.setattr(lpr, "_forming_seen", {})
    ts = 1_700_000_070.0  # 1_700_000_070 - (70 % 60) = 1_700_000_040
    row = {
        "ticker": tk,
        "spot": 101.5,
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {"spot": "LAST_PRICE"},
        "spot_received_ts": ts,
        "server_received_ts": ts,
        "exchange_quote_ts": ts,
        "trade_ts": ts,                 # TRADE_TIME in epoch SECONDS (the plane converts the ms)
    }
    monkeypatch.setattr(lpr.lmp, "get_quote", lambda t: row if t == tk else None)
    lpr._note_trade(tk)             # the plane's row listener, as a streamed LAST_PRICE fires it
    bars = [{"t": 1_700_000_040.0, "o": 100.0, "h": 100.5, "l": 99.5, "c": 100.2, "v": 10}]
    out = srv.overlay_forming_bar_from_plane(bars, tk)
    assert len(out) == 1
    assert out[0]["c"] == 101.5
    assert out[0]["h"] == 101.5  # 100.5 vs 101.5
    assert out[0]["l"] == 99.5
    assert out[0]["forming"] is True


def test_viewed_watchlist_quote_fires_gamma_tick_callback(monkeypatch):
    import app.options.order_flow.streaming as ofs

    hits: list[str] = []
    monkeypatch.setattr(ofs, "_on_tick_callback", lambda s: hits.append(s))
    monkeypatch.setattr(ofs, "_active_ticker", "AAA")
    monkeypatch.setattr(ofs, "_equity_demand", {"watchlist": ["BBB"], "board": []})
    monkeypatch.setattr(ofs, "push_level_one", lambda *a, **k: None)
    monkeypatch.setattr(ofs._lmp, "record_from_level_one_equity", lambda *a, **k: None)

    msg = {"symbol": "BBB", "ts_recv": 1_700_000_000.0, "native": {"LAST_PRICE": 10.0}}
    ofs._ingest_pushed("quote.BBB", msg)
    assert hits == ["BBB"]

    # every equity tick reaches the callback; WHICH surfaces reprice is decided by the heatmap
    # demand registry inside server._on_stream_tick (one "viewed" signal, audit
    # of #280) -- tests/test_instant_ui_blockers_a_v1.py pins that gate
    hits.clear()
    msg2 = {"symbol": "CCC", "ts_recv": 1_700_000_001.0, "native": {"LAST_PRICE": 11.0}}
    ofs._ingest_pushed("quote.CCC", msg2)
    assert hits == ["CCC"]
