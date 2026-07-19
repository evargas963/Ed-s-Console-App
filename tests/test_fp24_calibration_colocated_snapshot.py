"""FP-24: live calibration must colocate with the snapshot clock (tol=29 join)."""

from __future__ import annotations

import ast
from pathlib import Path

from calibration.v2_live_logging import (
    LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT,
    LIVE_ADVISORY_V2_SKIP_NON_MODEL_CYCLE,
    LIVE_ADVISORY_V2_TAIL_APPEND,
    resolve_live_v2_calibration_tail_action,
)

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


def test_expected_calibration_requires_snapshot_reservation() -> None:
    """Anchor must not expect calibration on throttled (no-snapshot) cycles."""
    tree = ast.parse(SERVER)
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    seg = ast.get_source_segment(SERVER, fn) or ""
    assert "and _xid_do_snapshot_insert" in seg
    assert "_xid_expected_cal = bool(" in seg


def test_server_tail_uses_resolve_helper() -> None:
    """Server must call the executable skip resolver (not only string presence)."""
    assert "resolve_live_v2_calibration_tail_action(" in SERVER
    assert "colocated_snapshot_ts_utc=float(_snap_ts)" in SERVER


def test_calibration_tail_skip_branch_executes() -> None:
    """Execution-level: no landed snapshot → skip reason, never append."""
    assert (
        resolve_live_v2_calibration_tail_action(
            model_derived_cycle=True,
            has_execution_identity=True,
            snap_insert_landed=False,
        )
        == LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT
    )
    assert (
        resolve_live_v2_calibration_tail_action(
            model_derived_cycle=False,
            has_execution_identity=False,
            snap_insert_landed=True,
        )
        == LIVE_ADVISORY_V2_SKIP_NON_MODEL_CYCLE
    )
    assert (
        resolve_live_v2_calibration_tail_action(
            model_derived_cycle=True,
            has_execution_identity=True,
            snap_insert_landed=True,
        )
        == LIVE_ADVISORY_V2_TAIL_APPEND
    )


def test_skip_reason_constant_stable() -> None:
    assert LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT != LIVE_ADVISORY_V2_SKIP_NON_MODEL_CYCLE
    assert "colocated_snapshot" in LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT


def test_live_append_passes_colocated_snapshot_ts() -> None:
    """FP-32: server must pass landed snap ts into the live calibration writer."""
    assert "colocated_snapshot_ts_utc=float(_snap_ts)" in SERVER
