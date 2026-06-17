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
) -> dict[str, Any] | None:
    """Insert one calibration row after both v1 signal data and v2 metadata exist.

    This is intentionally single-phase: no prior v1 row is required, and there
    is no second writer that updates the same row later.
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
