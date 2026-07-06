"""STACK_SCOPE_CLOSURE_GOVERNANCE_LOCK_V1 acceptance tests (operator-approved 2026-07-06).

Negative fixtures derive layer/ticker/horizon sets from the CODE authorities
(never hardcoded), so a future 8th stack layer or 5th horizon auto-tightens
these locks.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_lane_closure_scopes import (  # noqa: E402
    check_horizon_authority_consistency,
    check_register,
    run_check,
)


def _auth():
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS, ML_AUTHORITATIVE_TICKERS
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    return (
        list(FULL_STACK_MODEL_LAYERS),
        list(ML_AUTHORITATIVE_TICKERS),
        list(PRIMARY_DECISION_HORIZONS),
    )


def _parent(status="CLOSED_WITH_EVIDENCE", env="local"):
    return {
        "lane": "PARENT_X",
        "kind": "parent",
        "parent": None,
        "status": status,
        "required_scope": {
            "layers": "FULL_STACK_MODEL_LAYERS",
            "tickers": "ML_AUTHORITATIVE_TICKERS",
            "horizons": "PRIMARY_DECISION_HORIZONS",
            "environment": env,
        },
        "caveats": [],
        "caveats_disposition": "open",
    }


def _child(layers, tickers, horizons, env="local", caveats=None, disp="open",
           status="CLOSED_WITH_EVIDENCE"):
    return {
        "lane": "CHILD_X",
        "kind": "child",
        "parent": "PARENT_X",
        "status": status,
        "scope": {
            "layers": layers,
            "tickers": tickers,
            "horizons": horizons,
            "environment": env,
        },
        "caveats": caveats or [],
        "caveats_disposition": disp,
    }


def _reg(*lanes):
    return {"schema_version": "lane_closure_register_v1", "lanes": list(lanes)}


def test_5c_only_child_cannot_close_all_horizon_parent():
    layers, tickers, _ = _auth()
    errs = check_register(_reg(_parent(), _child(layers, tickers, ["5c"])))
    assert any("horizons" in e and "missing" in e for e in errs), errs


def test_5c_15c_child_cannot_close_primary_decision_horizon_parent():
    """The exact D2 shape: 5c+15c research coverage vs the 1c/5c/15c/60c parent."""
    layers, tickers, horizons = _auth()
    errs = check_register(_reg(_parent(), _child(layers, tickers, ["5c", "15c"])))
    missing = [h for h in horizons if h not in ("5c", "15c")]
    assert missing, "authority unexpectedly shrank to 5c/15c only"
    assert any("horizons" in e for e in errs), errs


def test_child_missing_one_active_layer_fails():
    layers, tickers, horizons = _auth()
    errs = check_register(_reg(_parent(), _child(layers[:-1], tickers, horizons)))
    assert any("layers" in e and layers[-1] in e for e in errs), errs


def test_xgb_only_child_cannot_close_full_stack_parent():
    _, tickers, horizons = _auth()
    errs = check_register(_reg(_parent(), _child(["xgb"], tickers, horizons)))
    assert any("layers" in e for e in errs), errs


def test_spy_only_child_cannot_close_universal_parent():
    layers, _, horizons = _auth()
    errs = check_register(_reg(_parent(), _child(layers, ["SPY"], horizons)))
    assert any("tickers" in e for e in errs), errs


def test_research_scratch_child_cannot_close_production_parent():
    layers, tickers, horizons = _auth()
    errs = check_register(
        _reg(_parent(env="production"),
             _child(layers, tickers, horizons, env="research_scratch"))
    )
    # environment-under-rung children contribute nothing -> every dim uncovered
    assert any("coverage" in e for e in errs), errs


def test_caveated_child_blocks_parent_and_waiver_requires_ref():
    layers, tickers, horizons = _auth()
    errs = check_register(
        _reg(_parent(),
             _child(layers, tickers, horizons, caveats=["single_split_pilot"], disp="open"))
    )
    assert any("coverage" in e for e in errs), errs
    # empty waiver reference is itself an error
    errs2 = check_register(
        _reg(_parent(),
             _child(layers, tickers, horizons, caveats=["x"], disp="operator_waived:"))
    )
    assert any("non-empty" in e for e in errs2), errs2
    # proper waiver unblocks
    errs3 = check_register(
        _reg(_parent(),
             _child(layers, tickers, horizons, caveats=["x"],
                    disp="operator_waived:OP-2026-07-06-example"))
    )
    assert not errs3, errs3


def test_positive_joint_coverage_closes_parent():
    layers, tickers, horizons = _auth()
    a = _child(layers[:2], tickers, horizons)
    a["lane"] = "CHILD_A"
    b = _child(layers[2:], tickers, horizons)
    b["lane"] = "CHILD_B"
    errs = check_register(_reg(_parent(), a, b))
    assert not errs, errs


def test_open_parent_statuses_never_flagged():
    """Seeded board states (NOT_PROVEN / PARTIAL / NOT_APPROVED*) are legal
    without any coverage — the lock bites only on closed-class statuses."""
    for status in ("NOT_PROVEN", "PARTIAL", "NOT_APPROVED",
                   "NOT_APPROVED_FOR_PRODUCTION"):
        errs = check_register(_reg(_parent(status=status)))
        assert not errs, (status, errs)


def test_horizon_authorities_consistent_in_repo():
    assert check_horizon_authority_consistency() == []


def test_live_register_and_standards_map_pass():
    """The committed register (D2 seed + parent board) and the standards map
    must validate as-is — and the D2 child's open caveats mean no parent is
    closed by it."""
    result = run_check()
    assert result["ok"], result["errors"]
