"""VOL_OBSERVABILITY_V1 — read-only native-vol surface locks (V2 prerequisite).

Money-path isolation is the load-bearing contract here: the surface observes
the already-fetched $VIX/$VXN/$RVX values and must never route them into
models, regime, fusion, or decisions (native consumption = NOT_APPROVED).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import vol_observability as vo

_REPO = Path(__file__).resolve().parent.parent

# Money-path modules that must never import the observability surface.
_MONEY_PATH_FORBIDDEN_IMPORTERS = (
    "signals.py",
    "market_state.py",
    "volatility_regime.py",
    "monte_carlo.py",
    "call_engine.py",
    "bayesian_fusion.py",
    "ml_predict.py",
    "ml_train.py",
    "regime_engine.py",
    "prediction_engine.py",
)


def _reset():
    with vo._lock:
        vo._observations.clear()


def _ctx(vix=None, vxn=None, rvx=None):
    return SimpleNamespace(vix=vix, vxn=vxn, rvx=rvx)


def _vol_ctx(as_of=123.0):
    return SimpleNamespace(as_of_ts=as_of)












def test_ticker_class_mapping_candidates():
    cases = {
        "SPY": ("spx_cone", "$VIX", "NATIVE_EQUALS_MARKET"),
        "$SPX": ("spx_cone", "$VIX", "NATIVE_EQUALS_MARKET"),
        "QQQ": ("ndx_cone", "$VXN", "NATIVE_INDEX"),
        "IWM": ("rut_cone", "$RVX", "NATIVE_INDEX"),
        "NVDA": ("single_equity_guest", "ticker_atm_iv", "CHAIN_DERIVED"),
        "ZZGUEST": ("single_equity_guest", "ticker_atm_iv", "CHAIN_DERIVED"),
    }
    for sym, (cls, native, rel) in cases.items():
        c = vo.vol_observability_payload(sym)["ticker_class_candidate"]
        assert (c["class_candidate"], c["native_source_candidate"], c["native_relation_candidate"]) == (cls, native, rel), sym








def test_v1_no_consumer_wiring_lock_still_holds():
    """The pre-existing V1 lock stays intact: server.py itself carries no
    native-index attribute wiring (the observability module owns the reads)."""
    src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    for ref in ("ctx.vxn", "ctx.rvx", "mkt_ctx.vxn", "mkt_ctx.rvx", "native_vol_"):
        assert ref not in src
