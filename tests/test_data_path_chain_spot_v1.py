"""Schwab -> the levels. A chain's one spot (operator 2026-10-23): Schwab's LAST_PRICE with its
trade time, as the daemon's price row holds it when the chain is complete. The daemon's chain sweep
sends it with the chain and stores it with the capture (each expiry's underlyingPrice kept as sent
beside it); the console prices the chain at it; the stored-capture reader gives it back. A capture
written before the chain carried a spot is read at its nearest expiry's underlyingPrice, labelled.

Real data: CRWD's 2026-10-16 expiry captured 2026-10-07 10:38:40 ET (tests/real_chains.py CRWD,
underlyingPrice 269.04) and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00 ET
(tests/fixtures/real_crwd_quote_2026_10_07.json: LAST_PRICE 269.395, TRADE_TIME_MILLIS
1791383880289), taken in by the daemon's plane at its receipt time.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import calibration.complete_chain_capture as cch
import live_market_plane as lmp
import server
from app.options.order_flow import streaming as ofs
from stream_spine import CaptureWriter
from tests.real_chains import CRWD

_QUOTE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json").read_text(
        encoding="utf-8"
    )
)
TK = "CRWD"
LAST, TRADED = _QUOTE["native"]["LAST_PRICE"], _QUOTE["native"]["TRADE_TIME_MILLIS"] / 1000.0
EXPIRY = CRWD.chain[0]["expirationDate"][:10]


def _forget():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    with server._chains_waiting_lock:
        server._chains_delivered.discard(TK)
    ofs._price_rows.pop(TK, None)
    ofs._chain_parts.pop(TK, None)
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    lmp.record_feed_down()


def _drain():
    while True:
        server._chain_pricing.submit(lambda: None).result(timeout=60)
        with server._chains_waiting_lock:
            if not server._chains_waiting:
                return


def test_the_chain_carries_its_spot_from_the_daemon_to_the_levels_and_the_capture(tmp_path):
    at = CRWD.now.timestamp()
    _forget()
    published = []
    try:
        lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
        lmp.record_feed_heartbeat(
            {"ts": at, "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": [TK]}}
        )
        sweep = cch.ChainSweep(
            tmp_path / "ed_console.db",
            [TK],
            lambda topic, msg: published.append((topic, msg)),
            clock=lambda: at,
            failures=CaptureWriter(tmp_path / "stream_capture.db"),
            streamed=lambda symbol: None,
        )
        chain = cch._Chain(
            TK, at, spots={EXPIRY: CRWD.spot}, by_expiry={EXPIRY: [dict(c) for c in CRWD.chain]}
        )
        sweep.deliver(chain)
        assert published and all((m["spot"], m["spot_ts"]) == (LAST, TRADED) for _t, m in published)
        with sqlite3.connect(tmp_path / "ed_console.db") as c:
            stored = c.execute(
                "SELECT spot, chain_spot, chain_spot_ts FROM complete_chain_captures"
            ).fetchall()
        assert stored == [(CRWD.spot, LAST, TRADED)]  # underlyingPrice kept as sent beside it
        (read,) = cch.last_capture_per_day(tmp_path / "ed_console.db", TK, 1)
        assert (read["spot"], read["spot_ts"]) == (LAST, TRADED)
        for _topic, msg in published:
            for done in ofs.assemble_chain_part(json.loads(msg["frame"])["msg"]):
                server._on_chain(*done)
        _drain()
        with server._terrain_cache_lock:
            held = dict(server._terrain_cache[TK])
    finally:
        _forget()
    assert (held["spot"], held["spot_as_of_ts_utc"], held["spot_source"]) == (
        LAST,
        TRADED,
        server.SPOT_SOURCE_PLANE,
    )
    assert held["spot"] != CRWD.spot


def test_a_capture_written_before_the_chain_carried_a_spot_is_read_at_its_nearest_expiry(tmp_path):
    db = tmp_path / "ed_console.db"
    by_expiry: dict = {}
    for ct in CRWD.chain:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    for expiry, cts in by_expiry.items():
        cch.persist_complete_chain_capture(
            db,
            ticker=TK,
            expiry=expiry,
            contracts=cts,
            spot=CRWD.spot,
            completeness_basis=cch.CAPTURE_BASIS,
            ts_utc=CRWD.now.timestamp(),
        )
    (read,) = cch.last_capture_per_day(db, TK, 1)
    assert (read["spot"], read["spot_ts"], read["spot_from_chain"]) == (CRWD.spot, None, False)
    published = []
    try:
        server._publish_levels(TK, captures=[read], now=CRWD.now)
        with server._terrain_cache_lock:
            published.append(dict(server._terrain_cache[TK]))
        server._publish_levels(TK, now=CRWD.now)  # a reprice of the kept capture
        with server._terrain_cache_lock:
            published.append(dict(server._terrain_cache[TK]))
    finally:
        _forget()
    for held in published:
        assert (held["spot"], held["spot_source"], held["spot_as_of_ts_utc"]) == (
            CRWD.spot,
            server.SPOT_SOURCE_CAPTURE,
            CRWD.now.timestamp(),
        )


def test_a_stored_trade_time_without_its_price_is_no_chain_spot(tmp_path):
    db = tmp_path / "ed_console.db"
    cch.persist_complete_chain_capture(
        db,
        ticker=TK,
        expiry=EXPIRY,
        contracts=CRWD.chain,
        spot=CRWD.spot,
        completeness_basis=cch.CAPTURE_BASIS,
        ts_utc=CRWD.now.timestamp(),
        chain_spot=None,
        chain_spot_ts=TRADED,
    )
    (read,) = cch.last_capture_per_day(db, TK, 1)
    assert (read["spot"], read["spot_ts"], read["spot_from_chain"]) == (CRWD.spot, None, False)
