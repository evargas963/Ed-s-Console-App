"""
Append rows to calibration_decision_log (Phase 2).

Enable with environment variable ED_CALIBRATION_LOG=1 (or true/yes).
Uses a short-lived SQLite connection to the console DB (same file as db.DB_PATH).
"""

from __future__ import annotations

import logging
import os
import sqlite3
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

# Max chars for raw_bundle JSON excerpts (audit preview; may be unparseable if truncated).
_RAW_BUNDLE_EXCERPT_LIMIT = 4000

# SQLite locked/busy retries (attempts 0..10): ~3.13s total sleep worst case (linear was ~3.3s).
_SQLITE_BUSY_RETRY_MAX_SLEEP_S = 0.5
_SQLITE_BUSY_RETRY_BASE_SLEEP_S = 0.01


def sqlite_busy_retry_sleep_seconds(attempt: int) -> float:
    return min(_SQLITE_BUSY_RETRY_MAX_SLEEP_S, _SQLITE_BUSY_RETRY_BASE_SLEEP_S * (2**attempt))


def _sqlite_busy_or_locked(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _json_excerpt(obj: Any, limit: int = _RAW_BUNDLE_EXCERPT_LIMIT) -> str | None:
    """Serialize for storage; truncate only for human/audit preview (not guaranteed parseable)."""
    if obj is None:
        return None
    text = dumps_compact(obj)
    if len(text) <= limit:
        return text
    sentinel = '..."[TRUNCATED]"'
    if limit <= len(sentinel):
        return sentinel[:limit]
    return text[: limit - len(sentinel)] + sentinel


def _db_path_for_write(explicit: Optional[Path | str] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    try:
        from db import DB_PATH

        return Path(DB_PATH)
    except ImportError as e:
        log.warning("db.DB_PATH not available — using DEFAULT_DB: %s", e)
        return DEFAULT_DB


def calibration_logging_enabled() -> bool:
    """Env-gated kill switch for the calibration_decision_log writer.

    Returns True only when ``ED_CALIBRATION_LOG`` env var is one of
    {"1", "true", "yes", "on"} (case-insensitive). When False, every call to
    ``append_live_v2_calibration_decision`` silently returns None — the
    calibration_decision_log table gets zero new rows with no log warning.

    **Default is OFF.** Operators must set ``ED_CALIBRATION_LOG=1`` in the
    server environment (typically ``.env``) to enable persistence. Forgetting
    to set this is the root cause of the 2026-04-12 → 2026-05-05 calibration
    gap (24 days of silent zero-row writes); ``server.py`` now logs a WARNING
    at boot when this returns False, so the operator can't restart into a
    silent-skip state without seeing it.
    """
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
        log.warning(
            "calibration logging enabled (ED_CALIBRATION_LOG=1) but DB not found at %s — row dropped",
            path,
        )
        return None

    try:
        from db import configure_sqlite_connection
    except ImportError as e:
        log.warning("calibration writer sqlite/db import failed: %s", e)
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
    # Single JSON encode: xgb/lstm/transformer are objects in the outer JSON (not nested JSON strings).
    # Downstream readers still accept legacy double-encoded string values via isinstance(blk, str).
    model_outputs = {
        "xgb": xgb_out,
        "lstm": lstm_out,
        "transformer": transformer_out,
        "stack_probs_bundle": ml_bundle,
    }
    model_outputs_json = dumps_compact(model_outputs)
    monte_carlo_json = dumps_compact(mc_out)

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
        "predictive_card_excerpt": _json_excerpt(pred),
        "fusion_excerpt": _json_excerpt(fusion),
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

    ct_raw = (canonical_timeframe or "").strip()
    if not ct_raw:
        log.error(
            "calibration_decision_log: canonical_timeframe required, got %r",
            canonical_timeframe,
        )
        return None
    if ct_raw != CANONICAL_TIMEFRAME:
        log.error(
            "calibration_decision_log: refusing non-canonical timeframe %r (expected %r)",
            ct_raw,
            CANONICAL_TIMEFRAME,
        )
        return None

    t_raw = (ticker or "").strip()
    if not t_raw:
        log.error("calibration_decision_log: ticker required, got %r", ticker)
        return None
    t_key = ticker_storage_key(t_raw)

    validation_summary = getattr(call, "validation_summary", None) or ""
    if len(validation_summary) > 2000:
        log.info(
            "calibration_decision_log: validation_summary truncated from %d to 2000 chars",
            len(validation_summary),
        )
        validation_summary = validation_summary[:2000]

    row_params = (
        float(decision_ts_utc),
        t_key,
        ct_raw,
        None,  # session_label: reserved; live path uses session_bucket only
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
        validation_summary,
        None,  # wait_blocker_json: reserved for future multi-horizon wait-blocker capture
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
            # COH-I-D: logical-time inversion diagnostic. The UNIQUE (ticker, decision_ts_utc)
            # constraint plus INSERT ... ON CONFLICT DO NOTHING guarantees idempotent dedup,
            # but does NOT prevent out-of-order writes (a delayed writer for an older tick
            # can insert after a newer-tick row already landed). Log a warning so the operator
            # can detect this in production. Diagnostic-only — the insert proceeds either way.
            try:
                prior = conn.execute(
                    "SELECT MAX(decision_ts_utc) FROM calibration_decision_log WHERE ticker = ?",
                    (ticker_storage_key(ticker),),
                ).fetchone()
                prior_max = prior[0] if prior and prior[0] is not None else None
                if prior_max is not None and float(prior_max) > float(decision_ts_utc):
                    log.warning(
                        "calibration_decision_log logical-time inversion: ticker=%s incoming_ts=%.6f prior_max_ts=%.6f (proceeding with insert; COH-I-D diagnostic)",
                        ticker,
                        float(decision_ts_utc),
                        float(prior_max),
                    )
            except sqlite3.Error as e:
                # Diagnostic-only — do not block the insert on the inversion check.
                log.debug("calibration_decision_log inversion check skipped: %s", e)
            cur = conn.execute(insert_sql, row_params)
            conn.commit()
            if cur.rowcount == 0:
                return CALIBRATION_INSERT_IDEMPOTENT
            return int(cur.lastrowid)
        except sqlite3.OperationalError as e:
            last_exc = e
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            if _sqlite_busy_or_locked(e) and attempt < 11:
                time.sleep(sqlite_busy_retry_sleep_seconds(attempt))
                continue
            log.warning("calibration_decision_log insert failed: %s", e)
            return None
        except sqlite3.Error as e:
            log.warning("calibration_decision_log insert failed: %s", e)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            return None
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    if last_exc is not None:
        log.warning("calibration_decision_log insert failed after retries: %s", last_exc)
    return None


def default_decision_ts_utc() -> float:
    """Fallback when SignalInput.refresh_ts_utc is unset (tests / offline callers)."""
    try:
        from db import utc_ts

        return float(utc_ts())
    except ImportError as e:
        log.warning("db.utc_ts not available — using time.time(): %s", e)
        return float(time.time())
