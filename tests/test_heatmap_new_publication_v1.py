"""The number moves: the heatmap serves each new publication's open interest, Schwab's openInterest as
sent, as a new publication (surface_seq) the page redraws. Real data: the last chain capture of
2026-10-01 and of 2026-10-02 of one expiry (2027-03-19), SPY and TSLA
(tests/fixtures/real_chain_captures_spy_tsla_2027_03_19_on_2026_10_01_02.json); open interest
changed overnight. Each capture is written by the chain sweep's writer
(persist_complete_chain_capture) and published by the levels producer from the stored captures
(server._price_chain STORED: priced at Schwab's underlying price and time in the capture)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import server
from calibration.complete_chain_capture import ensure_schema, persist_complete_chain_capture
from db import get_db

_FX = json.loads((Path(__file__).resolve().parent / "fixtures"
                  / "real_chain_captures_spy_tsla_2027_03_19_on_2026_10_01_02.json").read_text(encoding="utf-8"))
EXPIRY = "2027-03-19"


def _captures(tk: str) -> list[dict]:
    return sorted((r for r in _FX["rows"] if r["ticker"] == tk), key=lambda r: r["ts_utc"])


def _store(row: dict) -> None:
    assert persist_complete_chain_capture(
        get_db().db_path, ticker=row["ticker"], expiry=row["expiry"], contracts=row["chain"],
        spot=row["spot"], completeness_basis=row["completeness_basis"], ts_utc=row["ts_utc"],
        source=row["source"])["status"] == "written"


def _forget(tk: str) -> None:
    with sqlite3.connect(str(get_db().db_path)) as con:
        ensure_schema(con)
        con.executemany("DELETE FROM complete_chain_captures WHERE ticker=? AND ts_utc=?",
                        [(tk, r["ts_utc"]) for r in _captures(tk)])
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)


def _served_oi(tk: str) -> dict:
    d = json.loads(server.get_options_gamma_surface(tk, scope="all", centre=None, shift=0, cols=None,
                                                    expiry=EXPIRY).body)
    assert [e["expiry"] for e in d["expirations"]] == [EXPIRY]
    return d["surface_seq"], {c["strike"]: (c["oi"][0]["call"], c["oi"][0]["put"]) for c in d["cells"]}


def _schwab_oi(row: dict) -> dict:
    out: dict = {}
    for c in row["chain"]:
        call, put = out.get(c["strikePrice"], (0.0, 0.0))
        oi = float(c["openInterest"])
        out[c["strikePrice"]] = (call + oi, put) if c["putCall"] == "CALL" else (call, put + oi)
    return out


@pytest.mark.parametrize("tk", ["SPY", "TSLA"])
def test_a_new_publication_serves_the_new_number(tk):
    first, second = _captures(tk)
    changed = {k for k, v in _schwab_oi(second).items() if _schwab_oi(first).get(k) != v}
    assert changed, "the two captures' open interest is the same"
    _forget(tk)
    try:
        published = []
        for row in (first, second):
            _store(row)
            server._price_chain(tk, server.STORED, None, None)
            assert server.terrain_cache_get(tk)["computed_ts_utc"] == row["ts_utc"]
            seq, served = _served_oi(tk)
            assert served == _schwab_oi(row)
            published.append(seq)
        assert published[1] == published[0] + 1
    finally:
        _forget(tk)
