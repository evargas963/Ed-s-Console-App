from __future__ import annotations


def test_chain_fetch_gate_returns_timings_on_normal_path(monkeypatch):
    """Uncontended gate: response + non-negative gate wait + fetch duration."""
    import server as srv

    # A fresh gate: the final "immediately acquirable" assertion requires a gate no other test
    # has touched.
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    monkeypatch.setattr(
        srv, "safe_get_chain",
        lambda client, ticker, *, strike_range=None, to_date=None, from_date=None: "OK")
    resp, gate_wait_sec, fetch_sec = srv._gated_safe_get_chain(None, "ZZZ_NORM", strike_range="ALL")
    assert resp == "OK"
    assert gate_wait_sec >= 0.0
    assert fetch_sec >= 0.0
    # Gate released: immediately acquirable.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()
