"""The number moves: the heatmap serves each new publication's open interest, Schwab's openInterest as
sent, as a new publication (surface_seq) the page redraws. Real data: the last chain sweep of
2026-10-01 and of 2026-10-02, one expiry (2027-03-19), SPY and TSLA
(tests/fixtures/real_chain_captures_spy_tsla_2027_03_19_2026_10_0{1,2}_close.json); open interest
changed overnight. Each capture is written by the chain sweep's writer and published by the levels
producer from the stored captures (server._price_chain STORED)."""
from __future__ import annotations

import json

import pytest

import server
from tests.feed_live_helper import fixture_rows, forget_chain_captures, store_chain_capture

EXPIRY = "2027-03-19"
_DAYS = [fixture_rows(f"real_chain_captures_spy_tsla_2027_03_19_2026_10_0{d}_close.json") for d in (1, 2)]


def _served(tk: str) -> tuple[int, dict]:
    d = json.loads(server.get_options_gamma_surface(tk, scope="all", centre=None, shift=0, cols=None,
                                                    expiry=EXPIRY).body)
    assert [e["expiry"] for e in d["expirations"]] == [EXPIRY]
    return d["surface_seq"], {c["strike"]: (c["oi"][0]["call"], c["oi"][0]["put"]) for c in d["cells"]}


def _schwab_oi(row: dict) -> dict:
    """Per strike, (call, put): the sum of Schwab's openInterest of the contracts listed there."""
    out: dict = {}
    for c in row["chain"]:
        call, put = out.get(c["strikePrice"], (0.0, 0.0))
        oi = float(c["openInterest"])
        out[c["strikePrice"]] = (call + oi, put) if c["putCall"] == "CALL" else (call, put + oi)
    return out


@pytest.mark.parametrize("tk", ["SPY", "TSLA"])
def test_a_new_publication_serves_the_new_number(tk):
    first, second = (next(r for r in day if r["ticker"] == tk) for day in _DAYS)
    assert {k for k, v in _schwab_oi(second).items() if _schwab_oi(first).get(k) != v}, "open interest unchanged"
    forget_chain_captures([first, second])
    try:
        seqs = []
        for row in (first, second):
            store_chain_capture(row)
            server._price_chain(tk, server.STORED, None, None)
            seq, served = _served(tk)
            assert served == _schwab_oi(row)
            seqs.append(seq)
        assert seqs[1] == seqs[0] + 1
    finally:
        forget_chain_captures([first, second])
