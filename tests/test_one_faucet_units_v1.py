"""One meaning per name (2026-09-27): DEX is dealer-signed (+call/-put) in every bucket and in the
terrain total; vanna is per 1 volatility point in every bucket and in the aggregate; a contract with
no readable expiry is in no expiry's book; yesterday's chain is priced at its own capture time."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import time_et
from math_exposure_core import compute_exposures_by_strike, compute_net_dex_dollars, compute_net_vanna
from terrain_engine import compute_terrain

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))
_CAPTURED = (2026, 9, 22, 12, 46)


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """real_spy_0dte_chain.json was captured 2026-09-22 12:46 ET."""
    return pin_clock(*_CAPTURED)


def _book():
    per, _ = compute_exposures_by_strike(_FX["chain"], spot=float(_FX["spot"]), require_oi=True)
    return per


def test_dex_is_dealer_signed_in_every_bucket_and_in_the_total():
    per = _book()
    for b in per.values():
        assert b["net_dex_dollars"] == pytest.approx(b["call_dex_dollars"] - b["put_dex_dollars"])
    total = compute_net_dex_dollars(per)["net_dex"]
    assert total == pytest.approx(sum(b["net_dex_dollars"] for b in per.values()), abs=1.0)


def test_vanna_is_per_vol_point_in_every_bucket_and_in_the_aggregate():
    per = _book()
    shares = sum(b["call_vanna"] - b["put_vanna"] for b in per.values())
    agg = compute_net_vanna(per, float(_FX["spot"]))
    assert agg["net_vanna_shares_per_volpt"] == pytest.approx(shares, abs=0.01)


def test_a_contract_with_no_expiry_is_not_counted_as_same_day(pin_clock):
    """On a chain with no same-day expiry (CRWD, 16 days out), a contract that does not state its
    expiry must not create a same-day share (it was pooled into the 0DTE book)."""
    pin_clock(2026, 9, 2, 10, 5)                   # the CRWD chain's capture
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                    .read_text(encoding="utf-8"))
    chain, spot = fx["chain"], float(fx["spot"])
    base = compute_terrain("CRWD", chain, spot).zero_dte_gamma_share_pct
    top = max(chain, key=lambda c: c.get("gamma") or 0.0)          # a contract that carries gamma
    orphan = {k: v for k, v in top.items() if k not in ("expirationDate", "daysToExpiration")}
    orphan["openInterest"] = 100_000
    assert base == 0.0
    assert compute_terrain("CRWD", chain + [orphan], spot).zero_dte_gamma_share_pct == base


def test_forces_prices_yesterdays_chain_at_its_capture_time(tmp_path, monkeypatch, pin_clock):
    import server
    from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
    db = tmp_path / "ed_console.db"
    for day, hour in ((22, 12), (21, 15)):
        ts = datetime(2026, 9, day, hour, 0, tzinfo=time_et.ET).timestamp()
        by_exp: dict = {}
        for ct in _FX["chain"]:
            by_exp.setdefault(ct["expirationDate"][:10], []).append(ct)
        for exp, cts in by_exp.items():
            persist_complete_chain_capture(db, ticker="SPY", expiry=exp, contracts=cts,
                                           spot=float(_FX["spot"]), completeness_basis=CAPTURE_BASIS,
                                           ts_utc=ts)
    monkeypatch.setattr(server, "get_db", lambda: type("Db", (), {"db_path": db})())
    pin_clock(2026, 10, 30, 12, 0)                  # the chain's expiry is long past
    body = json.loads(bytes(server.get_forces(ticker="SPY").body))
    assert body["available"] is True
    assert body["charm_below"] is not None and body.get("charm_error") is None, body


def test_the_put_call_volume_ratio_is_todays_trading_and_says_so_when_volume_is_missing():
    """Both ratios are served (operator 2026-09-27): OI (positions held) and volume (today's
    trading, Cboe's convention). A strike with no call listed has no call volume, not a zero."""
    from math_exposure_core import put_call_volume_ratio
    book = {100.0: {"call_volume": 400.0, "put_volume": 300.0, "volume_unreported": 0},
            105.0: {"call_volume": 100.0, "put_volume": 200.0, "volume_unreported": 0}}
    assert put_call_volume_ratio(book) == pytest.approx(500.0 / 500.0)
    book[105.0]["volume_unreported"] = 1
    assert put_call_volume_ratio(book) is None, "a contract with no volume is not zero volume"
    book[105.0]["volume_unreported"] = 0
    book[110.0] = {"call_volume": None, "put_volume": 50.0, "volume_unreported": 0}
    assert put_call_volume_ratio(book) == pytest.approx(550.0 / 500.0)
