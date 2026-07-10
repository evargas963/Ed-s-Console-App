"""VOL_OBSERVABILITY_V1 — read-only native-vol surface locks (V2 prerequisite).

Money-path isolation is the load-bearing contract here: the surface observes
the already-fetched $VIX/$VXN/$RVX values and must never route them into
models, regime, fusion, or decisions (native consumption = NOT_APPROVED).
"""

from __future__ import annotations

import ast
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


def test_payload_contract_keys_and_versions():
    _reset()
    vo.record_market_vol_observation(_ctx(vix=15.6, vxn=18.2, rvx=21.4), _vol_ctx())
    p = vo.vol_observability_payload("SPY")
    assert p["schema_version"] == 1
    assert p["contract_version"] == "1.0.0"
    assert p["route_identity"] == "live"
    assert p["broad_market_iv_source"] == "$VIX"
    assert p["native_iv_consumption"] == "NOT_APPROVED_V2_PENDING"
    for sym in ("$VIX", "$VXN", "$RVX"):
        rec = p["indices"][sym]
        for k in (
            "value", "previous_value", "change", "direction_candidate",
            "source_ts", "recorded_ts", "age_sec", "staleness_status",
            "quality_status", "consumed_status",
        ):
            assert k in rec, f"{sym} missing {k}"


def test_consumed_status_preserves_fetched_unconsumed():
    _reset()
    vo.record_market_vol_observation(_ctx(vix=15.0, vxn=18.0, rvx=21.0), _vol_ctx())
    p = vo.vol_observability_payload()
    assert p["indices"]["$VIX"]["consumed_status"] == "CONSUMED_MARKET_IV"
    assert p["indices"]["$VXN"]["consumed_status"] == "FETCHED_UNCONSUMED"
    assert p["indices"]["$RVX"]["consumed_status"] == "FETCHED_UNCONSUMED"


def test_prev_change_direction_semantics_never_default_zero():
    _reset()
    vo.record_market_vol_observation(_ctx(vix=15.0), _vol_ctx())
    first = vo.vol_observability_payload()["indices"]["$VIX"]
    assert first["previous_value"] is None
    assert first["change"] is None          # missing prev -> None, never 0
    assert first["direction_candidate"] is None
    vo.record_market_vol_observation(_ctx(vix=15.5), _vol_ctx())
    second = vo.vol_observability_payload()["indices"]["$VIX"]
    assert second["previous_value"] == 15.0
    assert second["change"] == 0.5
    assert second["direction_candidate"] == "rising"


def test_missing_and_invalid_values_fail_closed_unavailable():
    _reset()
    vo.record_market_vol_observation(_ctx(vix=None, vxn="garbage", rvx=20.0), _vol_ctx())
    p = vo.vol_observability_payload()
    assert p["indices"]["$VIX"]["quality_status"] == "UNAVAILABLE"
    assert p["indices"]["$VXN"]["quality_status"] == "UNAVAILABLE"
    assert p["indices"]["$VXN"]["value"] is None
    assert p["indices"]["$RVX"]["quality_status"] == "VALID"
    # never-recorded process state
    _reset()
    empty = vo.vol_observability_payload()
    for sym in ("$VIX", "$VXN", "$RVX"):
        assert empty["indices"][sym]["staleness_status"] == "UNAVAILABLE"


def test_staleness_status_ages_out():
    _reset()
    vo.record_market_vol_observation(_ctx(vix=15.0), _vol_ctx())
    with vo._lock:
        vo._observations["$VIX"]["recorded_ts"] -= vo.VOL_OBSERVATION_STALE_SEC + 5
    p = vo.vol_observability_payload()
    assert p["indices"]["$VIX"]["staleness_status"] == "STALE"


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


def test_recorder_never_raises_on_malformed_context():
    _reset()
    vo.record_market_vol_observation(None, None)   # must not raise
    vo.record_market_vol_observation(object(), object())
    p = vo.vol_observability_payload()
    assert p["schema_version"] == 1


def test_money_path_modules_do_not_import_observability():
    """Isolation lock: no money-path module may import vol_observability."""
    for rel in _MONEY_PATH_FORBIDDEN_IMPORTERS:
        src = (_REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert "vol_observability" not in src, f"{rel} references vol_observability"


def test_server_recorder_call_is_statement_only_and_unconsumed():
    """server.py may call record_market_vol_observation exactly once, as a
    bare statement (no assignment), and vol_observability_payload only from
    the read-only endpoint — nothing feeds the pipeline."""
    src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    record_calls = []
    payload_calls = []
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "record_market_vol_observation":
                record_calls.append(node)
            if node.func.id == "vol_observability_payload":
                payload_calls.append(node)
    assert len(record_calls) == 1
    assert isinstance(parents[record_calls[0]], ast.Expr), (
        "recorder result must not be assigned/consumed"
    )
    assert len(payload_calls) == 1
    fn = parents.get(payload_calls[0])
    while fn is not None and not isinstance(fn, ast.FunctionDef):
        fn = parents.get(fn)
    assert fn is not None and fn.name == "api_vol_observability", (
        "payload may only serve the read-only endpoint"
    )


def test_v1_no_consumer_wiring_lock_still_holds():
    """The pre-existing V1 lock stays intact: server.py itself carries no
    native-index attribute wiring (the observability module owns the reads)."""
    src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    for ref in ("ctx.vxn", "ctx.rvx", "mkt_ctx.vxn", "mkt_ctx.rvx", "native_vol_"):
        assert ref not in src
