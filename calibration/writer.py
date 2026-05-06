"""
Append rows to calibration_decision_log (Phase 2).

Enable with environment variable ED_CALIBRATION_LOG=1 (or true/yes).
Uses a short-lived SQLite connection to the console DB (same file as db.DB_PATH).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from calibration.json_utils import dumps_compact
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.trust import CALIBRATION_TRUST_TRUSTED
from calibration.v2_advisory_backfill import ADVISORY_V2_ADAPTER_VERSION, ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION
from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME

log = logging.getLogger(__name__)

# append_calibration_decision return: idempotent skip (UNIQUE conflict, no duplicate row)
CALIBRATION_INSERT_IDEMPOTENT: int = -1


def _db_path_for_write(explicit: Optional[Path | str] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    try:
        from db import DB_PATH

        return Path(DB_PATH)
    except Exception:
        return DEFAULT_DB


def calibration_logging_enabled() -> bool:
    return os.environ.get("ED_CALIBRATION_LOG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def append_calibration_decision(
    *,
    decision_ts_utc: float,
    ticker: str,
    canonical_timeframe: str,
    inp: Any,
    regime: Any,
    vol_regime: Any,
    fusion: Any,
    canonical: Any,
    pred: Any,
    call: Any,
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
    mc_out: Any,
    ml_bundle: dict,
    mh_bundle: Any,
    db_path: Optional[Path | str] = None,
    signal_layer_v1: Optional[dict[str, Any]] = None,
    advisory_v2_decision_snapshot: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    """
    Insert one analysis-ready row per (ticker_storage_key(ticker), decision_ts_utc).

    Returns:
        None — logging off, missing DB, non-canonical timeframe, or hard insert failure
        positive int — new row id
        CALIBRATION_INSERT_IDEMPOTENT (-1) — row already existed (UNIQUE conflict); not an error
    """
    if not calibration_logging_enabled():
        return None
    path = _db_path_for_write(db_path)
    if not path.is_file():
        log.debug("calibration: DB not found at %s", path)
        return None

    try:
        import sqlite3

        from db import configure_sqlite_connection
    except Exception as e:
        log.debug("calibration import: %s", e)
        return None

    zone = getattr(inp, "zone", None)
    vwap_side = getattr(inp, "vwap_side", None)
    na = getattr(inp, "nearest_above_dist", None)
    nb = getattr(inp, "nearest_below_dist", None)
    structural = {
        "nearest_above_name": getattr(inp, "nearest_above_name", None),
        "nearest_below_name": getattr(inp, "nearest_below_name", None),
        "nearest_above_val": getattr(inp, "nearest_above_val", None),
        "nearest_below_val": getattr(inp, "nearest_below_val", None),
    }

    regime_primary = getattr(regime, "primary", None) if regime is not None else None
    regime_confidence = getattr(regime, "confidence", None) if regime is not None else None
    vol_r = None
    if vol_regime is not None:
        vol_r = getattr(vol_regime, "vol_regime", None) or getattr(vol_regime, "label", None)
        if vol_r is None:
            vol_r = str(getattr(vol_regime, "name", None) or getattr(vol_regime, "regime", None) or "") or None

    vix_bkt = getattr(inp, "vix_bucket", None)
    sess_bkt = getattr(inp, "session_bucket", None)

    fusion_json = dumps_compact(fusion) if fusion is not None else None
    canonical_json = dumps_compact(canonical) if canonical is not None else None
    model_outputs = {
        "xgb": dumps_compact(xgb_out),
        "lstm": dumps_compact(lstm_out),
        "transformer": dumps_compact(transformer_out),
        "stack_probs_bundle": ml_bundle,
    }
    model_outputs_json = dumps_compact(model_outputs)
    monte_carlo_json = dumps_compact(mc_out)
    pred_json = dumps_compact(pred)

    mh_dec = getattr(mh_bundle, "final_decision", None) if mh_bundle is not None else None
    multi_horizon_json = None
    if mh_dec is not None:
        ar = getattr(mh_dec, "alignment_report", None)
        multi_horizon_json = dumps_compact(
            {
                "primary_horizon": getattr(mh_dec, "primary_horizon", None),
                "trade_mode": getattr(mh_dec, "trade_mode", None),
                "alignment_state": getattr(mh_dec, "alignment_state", None),
                "conflict_level": getattr(ar, "conflict_level", None) if ar is not None else None,
                "final_bias": getattr(mh_dec, "final_bias", None),
                "final_tradeable": getattr(mh_dec, "final_tradeable", None),
                "wait_reason": getattr(mh_dec, "wait_reason", None),
                "sizing_modifier": getattr(mh_dec, "sizing_modifier", None),
            }
        )

    raw_bundle = {
        "predictive_card_excerpt": pred_json[:4000] if pred_json else None,
        "fusion_excerpt": fusion_json[:4000] if fusion_json else None,
        "signal_layer_v1": signal_layer_v1,
    }
    raw_bundle_json = dumps_compact(raw_bundle)
    advisory_v2_decision_snapshot_json = (
        dumps_compact(advisory_v2_decision_snapshot)
        if advisory_v2_decision_snapshot is not None
        else None
    )
    advisory_v2_snapshot_schema_version = (
        ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION
        if advisory_v2_decision_snapshot is not None
        else None
    )
    advisory_v2_adapter_version = (
        ADVISORY_V2_ADAPTER_VERSION
        if advisory_v2_decision_snapshot is not None
        else None
    )
    advisory_v2_backfilled_ts_utc = (
        time.time()
        if advisory_v2_decision_snapshot is not None
        else None
    )
    advisory_v2_backfill_status = "ok" if advisory_v2_decision_snapshot is not None else None

    expiry = getattr(inp, "expiry", None)
    build_generation = os.environ.get("ED_BUILD_GENERATION", "").strip() or None

    ct = (canonical_timeframe or CANONICAL_TIMEFRAME).strip()
    if ct != CANONICAL_TIMEFRAME:
        log.error(
            "calibration_decision_log: refusing non-canonical timeframe %r (expected %r)",
            ct,
            CANONICAL_TIMEFRAME,
        )
        return None

    t_key = ticker_storage_key((ticker or "").strip())

    row_params = (
        float(decision_ts_utc),
        t_key,
        ct,
        None,
        expiry,
        build_generation,
        zone,
        vwap_side,
        na,
        nb,
        dumps_compact(structural),
        regime_primary,
        regime_confidence,
        vol_r,
        vix_bkt,
        sess_bkt,
        dumps_compact({"regime": regime_primary, "vol_regime": vol_r}),
        model_outputs_json,
        monte_carlo_json,
        fusion_json,
        canonical_json,
        getattr(call, "signal", None),
        getattr(call, "conviction", None),
        getattr(call, "entry", None),
        getattr(call, "stop", None),
        getattr(call, "target", None),
        getattr(call, "target2", None),
        (getattr(call, "validation_summary", None) or "")[:2000],
        None,
        multi_horizon_json,
        raw_bundle_json,
        advisory_v2_decision_snapshot_json,
        advisory_v2_snapshot_schema_version,
        advisory_v2_adapter_version,
        advisory_v2_backfilled_ts_utc,
        advisory_v2_backfill_status,
        None,
        CALIBRATION_TRUST_TRUSTED,
    )
    insert_sql = """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, session_label, expiry, build_generation,
                zone, vwap_side, nearest_above_dist, nearest_below_dist, structural_json,
                regime_primary, regime_confidence, vol_regime, vix_bucket, session_bucket, regime_json,
                model_outputs_json, monte_carlo_json, fusion_json, canonical_json,
                final_signal, call_conviction, entry_price, stop_price, target_price, target2_price,
                validation_summary, wait_blocker_json, multi_horizon_json,
                raw_bundle_json,
                advisory_v2_decision_snapshot_json,
                advisory_v2_snapshot_schema_version,
                advisory_v2_adapter_version,
                advisory_v2_backfilled_ts_utc,
                advisory_v2_backfill_status,
                advisory_v2_backfill_reason,
                calibration_trust
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(ticker, decision_ts_utc) DO NOTHING
            """

    last_exc: Exception | None = None
    for attempt in range(12):
        conn = sqlite3.connect(str(path), timeout=60.0)
        try:
            configure_sqlite_connection(conn)
            ensure_calibration_schema(conn)
            _chg0 = conn.total_changes
            cur = conn.execute(insert_sql, row_params)
            conn.commit()
            if conn.total_changes == _chg0:
                return CALIBRATION_INSERT_IDEMPOTENT
            return int(cur.lastrowid)
        except sqlite3.OperationalError as e:
            last_exc = e
            try:
                conn.rollback()
            except Exception:
                pass
            msg = str(e).lower()
            if ("locked" in msg or "busy" in msg) and attempt < 11:
                time.sleep(0.05 * (attempt + 1))
                continue
            log.warning("calibration_decision_log insert failed: %s", e)
            return None
        except Exception as e:
            log.warning("calibration_decision_log insert failed: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    if last_exc is not None:
        log.warning("calibration_decision_log insert failed after retries: %s", last_exc)
    return None


def default_decision_ts_utc() -> float:
    """Fallback when SignalInput.refresh_ts_utc is unset (tests / offline callers)."""
    try:
        from db import utc_ts

        return float(utc_ts())
    except Exception:
        return float(time.time())
