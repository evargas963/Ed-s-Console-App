"""Single-phase live calibration logging with advisory v2 snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from calibration.v2_advisory_backfill import (
    ADVISORY_V2_ADAPTER_VERSION,
    ADVISORY_V2_DECISION_LOG_COLUMNS,
    ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
)
from calibration.writer import (
    CALIBRATION_INSERT_IDEMPOTENT,
    append_calibration_decision,
    calibration_logging_enabled,
)
from instrument_identity import ticker_storage_key

LIVE_ADVISORY_V2_DECISION_LOG_COLUMNS = ADVISORY_V2_DECISION_LOG_COLUMNS
LIVE_ADVISORY_V2_SOURCE = "live_tier_c_advisory"
LIVE_ADVISORY_V2_SKIP_NO_PAYLOAD = "v2_advisory_log_skipped_no_signal_payload"
LIVE_ADVISORY_V2_SKIP_MISSING_DECISION_TS = (
    "v2_advisory_log_skipped_missing_decision_ts"
)
# execution_identity_v1: a LIVE model-derived calibration row must carry the
# exact production decision identity - a live write without it is REFUSED
# (fail closed), never silently unlinked. Backfill/reconstruction paths call
# calibration.writer directly with decision_source markers; they never use
# this live entry point.
LIVE_ADVISORY_V2_REFUSED_NO_IDENTITY = "v2_live_log_refused_missing_execution_identity"
# EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: a cycle that is NOT model-derived
# (no combined signal, so the anchor contract creates no identity for it)
# performs no governed calibration write at all — an EXPECTED non-write recorded
# with this reason, distinct from the fail-closed identity refusal above.
LIVE_ADVISORY_V2_SKIP_NON_MODEL_CYCLE = "v2_live_log_skipped_non_model_cycle"
# FP-24: calibration rows must share the snapshot clock (1 insert/ticker/UTC minute).
# Logging without a colocated snapshot is the dominant source of residual
# skipped_no_candidate_in_tol near ±29–30s. Skip rather than widen join tol.
LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT = (
    "v2_live_log_skipped_no_colocated_snapshot"
)
# FP-32: live write must carry the landed snapshot ts and it must equal
# SignalInput.refresh_ts_utc — otherwise decision/snapshot clocks diverge and
# outcome join falls back to nearest_within_tol (historical debt class).
LIVE_ADVISORY_V2_REFUSED_SNAPSHOT_TS_MISMATCH = (
    "v2_live_log_refused_snapshot_ts_mismatch"
)
LIVE_ADVISORY_V2_REFUSED_MISSING_COLOCATED_SNAPSHOT_TS = (
    "v2_live_log_refused_missing_colocated_snapshot_ts"
)
LIVE_ADVISORY_V2_TAIL_APPEND = "append"


def resolve_live_v2_calibration_tail_action(
    *,
    model_derived_cycle: bool,
    has_execution_identity: bool,
    snap_insert_landed: bool,
) -> str:
    """Decide server calibration-tail action before any DB write.

    Returns ``LIVE_ADVISORY_V2_TAIL_APPEND`` or a ``LIVE_ADVISORY_V2_SKIP_*`` reason.
    Preserves production order: non-model idle skip, then colocated-snapshot skip,
    else append (writer still fail-closes on identity / clock).
    """
    if not has_execution_identity and not model_derived_cycle:
        return LIVE_ADVISORY_V2_SKIP_NON_MODEL_CYCLE
    if not snap_insert_landed:
        return LIVE_ADVISORY_V2_SKIP_NO_COLOCATED_SNAPSHOT
    return LIVE_ADVISORY_V2_TAIL_APPEND


def build_live_v2_advisory_snapshot(
    *,
    ticker: str,
    decision_ts_utc: float,
    v2_decision: dict[str, Any],
) -> dict[str, Any]:
    """Build the live payload shape stored in the same columns as backfill."""
    return {
        "snapshot_schema_version": ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
        "adapter_version": ADVISORY_V2_ADAPTER_VERSION,
        "source": LIVE_ADVISORY_V2_SOURCE,
        "ticker": ticker_storage_key(ticker),
        "decision_ts_utc": float(decision_ts_utc),
        "v2_decision": v2_decision,
    }


def append_live_v2_calibration_decision(
    *,
    db_path: Path | str,
    calibration_payload: dict[str, Any] | None,
    v2_decision: dict[str, Any],
    decision_id: str | None = None,
    execution_identity_sha256: str | None = None,
    colocated_snapshot_ts_utc: float | None = None,
) -> dict[str, Any] | None:
    """Insert one calibration row after both v1 signal data and v2 metadata exist.

    This is intentionally single-phase: no prior v1 row is required, and there
    is no second writer that updates the same row later.

    ``colocated_snapshot_ts_utc`` is required on the live path: it must be the
    ts just written to ``snapshots`` for this cycle and must equal
    ``inp.refresh_ts_utc``.
    """
    if not calibration_logging_enabled():
        return None
    if not calibration_payload:
        return {
            "status": "skipped",
            "reason": LIVE_ADVISORY_V2_SKIP_NO_PAYLOAD,
        }

    decision_ts_utc = _decision_ts_utc_from_payload(calibration_payload)
    if decision_ts_utc is None:
        return {
            "status": "skipped",
            "reason": LIVE_ADVISORY_V2_SKIP_MISSING_DECISION_TS,
        }
    if colocated_snapshot_ts_utc is None:
        import logging as _logging

        _logging.getLogger(__name__).error(
            "EXECUTION_CLOCK_REFUSED live v2 calibration write for %s: "
            "missing colocated_snapshot_ts_utc (fail closed)",
            calibration_payload.get("ticker"),
        )
        return {
            "status": "refused",
            "reason": LIVE_ADVISORY_V2_REFUSED_MISSING_COLOCATED_SNAPSHOT_TS,
        }
    snap_ts = float(colocated_snapshot_ts_utc)
    if abs(decision_ts_utc - snap_ts) > 1e-9:
        import logging as _logging

        _logging.getLogger(__name__).error(
            "EXECUTION_CLOCK_REFUSED live v2 calibration write for %s: "
            "decision_ts=%s != colocated_snapshot_ts=%s (fail closed)",
            calibration_payload.get("ticker"),
            decision_ts_utc,
            snap_ts,
        )
        return {
            "status": "refused",
            "reason": LIVE_ADVISORY_V2_REFUSED_SNAPSHOT_TS_MISMATCH,
        }
    if not decision_id or not execution_identity_sha256:
        # Live model-derived row without its governed execution identity:
        # REFUSED, loud, mechanically visible (never a linked-looking row
        # that is not actually linked, never a second identity).
        import logging as _logging

        _logging.getLogger(__name__).error(
            "EXECUTION_IDENTITY_REFUSED live v2 calibration write for %s: "
            "missing decision_id/execution_identity_sha256 (fail closed)",
            calibration_payload.get("ticker"),
        )
        return {"status": "refused", "reason": LIVE_ADVISORY_V2_REFUSED_NO_IDENTITY}

    inp = calibration_payload["inp"]
    ticker = calibration_payload["ticker"]
    advisory_snapshot = build_live_v2_advisory_snapshot(
        ticker=ticker,
        decision_ts_utc=decision_ts_utc,
        v2_decision=v2_decision,
    )
    row_id = append_calibration_decision(
        decision_ts_utc=decision_ts_utc,
        ticker=ticker,
        canonical_timeframe=calibration_payload["canonical_timeframe"],
        inp=inp,
        regime=calibration_payload["regime"],
        vol_regime=calibration_payload["vol_regime"],
        fusion=calibration_payload["fusion"],
        canonical=calibration_payload["canonical"],
        pred=calibration_payload["pred"],
        call=calibration_payload["call"],
        xgb_out=calibration_payload["xgb_out"],
        lstm_out=calibration_payload["lstm_out"],
        transformer_out=calibration_payload["transformer_out"],
        mc_out=calibration_payload["mc_out"],
        ml_bundle=calibration_payload["ml_bundle"],
        mh_bundle=calibration_payload["mh_bundle"],
        db_path=db_path,
        signal_layer_v1=calibration_payload["signal_layer_v1"],
        advisory_v2_decision_snapshot=advisory_snapshot,
        decision_id=decision_id,
        execution_identity_sha256=execution_identity_sha256,
    )
    if row_id is None:
        return {"status": "skipped", "reason": "calibration_writer_returned_none"}
    if row_id == CALIBRATION_INSERT_IDEMPOTENT:
        return {"status": "idempotent_skip", "reason": "duplicate_ticker_decision_ts"}
    return {"status": "ok", "row_id": row_id}


def _decision_ts_utc_from_payload(calibration_payload: dict[str, Any]) -> float | None:
    """Authoritative decision instant from SignalInput.refresh_ts_utc only."""
    from numeric_contract import float_positive_or_none

    ts = getattr(calibration_payload["inp"], "refresh_ts_utc", None)
    return float_positive_or_none(ts)
