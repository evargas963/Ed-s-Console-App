"""Immutable production decision records (I-31) + retrieval for blind reconstruction."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

PRODUCTION_DECISION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS production_decision_records (
    decision_id             TEXT PRIMARY KEY,
    decision_generation_id  INTEGER,
    decision_ts_utc         REAL NOT NULL,
    ticker                  TEXT NOT NULL,
    route                   TEXT NOT NULL,
    release_id              TEXT NOT NULL,
    release_json            TEXT NOT NULL,
    git_sha                 TEXT,
    market_inputs_json      TEXT,
    risk_state_json         TEXT,
    validation_summary      TEXT,
    model_outputs_json      TEXT,
    fusion_json             TEXT,
    final_signal            TEXT,
    call_conviction         TEXT,
    overrides_json          TEXT,
    staleness_json          TEXT,
    quarantine_json         TEXT,
    reconstruction_json     TEXT NOT NULL,
    created_at_utc          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_decision_ts
    ON production_decision_records (decision_ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_production_decision_ticker_ts
    ON production_decision_records (ticker, decision_ts_utc DESC);
"""


def ensure_production_decision_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(PRODUCTION_DECISION_TABLE_SQL)


def new_decision_id() -> str:
    """Immutable UUID4 hex — not calibration row id or in-process counter."""
    return uuid.uuid4().hex


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def _extract_market_inputs(ms_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "spot": ms_dict.get("spot"),
        "bid": ms_dict.get("bid"),
        "ask": ms_dict.get("ask"),
        "spread_pts": ms_dict.get("spread_pts"),
        "quote_source_detail": ms_dict.get("quote_source_detail"),
        "spread_age_ms": ms_dict.get("spread_age_ms"),
        "selected_exp": ms_dict.get("selected_exp"),
        "session_label": ms_dict.get("session_label"),
    }


def _extract_risk_state(ms_dict: dict[str, Any]) -> dict[str, Any]:
    call = ms_dict.get("call") if isinstance(ms_dict.get("call"), dict) else {}
    return {
        "trade_valid": call.get("trade_valid") if call else ms_dict.get("trade_valid"),
        "risk_valid": call.get("risk_valid") if call else ms_dict.get("risk_valid"),
        "validation_summary": ms_dict.get("validation_summary") or call.get("validation_summary"),
        "wait_blockers": ms_dict.get("wait_blockers") or call.get("wait_blockers"),
        "state_error": ms_dict.get("state_error"),
        "state_error_detail": ms_dict.get("state_error_detail"),
    }


def _extract_staleness(ms_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "analytics_stale": ms_dict.get("analytics_stale"),
        "spread_age_ms": ms_dict.get("spread_age_ms"),
        "sse_viewer_rest_cache_ttl_sec": ms_dict.get("sse_viewer_rest_cache_ttl_sec"),
        "_pipeline_ms": ms_dict.get("_pipeline_ms"),
    }


def _extract_quarantine(ms_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_error": ms_dict.get("state_error"),
        "signals_engine_failed": ms_dict.get("signals_engine_failed"),
        "decision_generation_skipped": ms_dict.get("decision_generation_skipped"),
        "market_data_quarantine": ms_dict.get("market_data_quarantine"),
    }


def build_reconstruction_payload(
    ms_dict: dict[str, Any],
    *,
    route: str,
    release: dict[str, Any],
) -> dict[str, Any]:
    """Full reconstruction bundle returned by GET /api/decision/{decision_id}."""
    return {
        "decision_id": ms_dict.get("decision_id"),
        "decision_generation_id": ms_dict.get("decision_generation_id"),
        "decision_timestamp_utc": ms_dict.get("decision_timestamp_utc"),
        "ticker": ms_dict.get("ticker"),
        "route": route,
        "market_inputs": _extract_market_inputs(ms_dict),
        "risk_state": _extract_risk_state(ms_dict),
        "validation_summary": _extract_risk_state(ms_dict).get("validation_summary"),
        "model_outputs": ms_dict.get("mhap_rows") or ms_dict.get("model_outputs"),
        "fusion_result": ms_dict.get("fusion") or ms_dict.get("fusion_by_horizon"),
        "final_signal": ms_dict.get("call_signal"),
        "call_conviction": ms_dict.get("call_conviction"),
        "overrides_active": ms_dict.get("pred_override"),
        "release": release,
        "release_id": release.get("release_id"),
        "git_sha": release.get("git_sha"),
        "build_reference": {
            "git_sha": release.get("git_sha"),
            "build_generation": release.get("build_generation"),
        },
        "staleness": _extract_staleness(ms_dict),
        "quarantine": _extract_quarantine(ms_dict),
        "dominant_dir": ms_dict.get("dominant_dir"),
        "fusion_available": ms_dict.get("fusion_available"),
    }


def persist_production_decision(
    ms_dict: dict[str, Any],
    *,
    route: str,
    release: dict[str, Any],
    db_path: Path | str,
) -> Optional[str]:
    """Insert immutable decision row. Returns decision_id or None on skip."""
    decision_id = str(ms_dict.get("decision_id") or "").strip()
    if not decision_id:
        log.warning("persist_production_decision: missing decision_id route=%s", route)
        return None
    quarantine = ms_dict.get("market_data_quarantine") or {}
    if isinstance(quarantine, dict) and quarantine.get("active"):
        log.warning("persist_production_decision: quarantined decision blocked route=%s", route)
        return None
    release_id = str(release.get("release_id") or "").strip()
    if not release_id:
        log.warning("persist_production_decision: missing release_id decision_id=%s", decision_id)
        return None

    reconstruction = build_reconstruction_payload(ms_dict, route=route, release=release)
    risk = _extract_risk_state(ms_dict)
    row = {
        "decision_id": decision_id,
        "decision_generation_id": ms_dict.get("decision_generation_id"),
        "decision_ts_utc": float(ms_dict.get("decision_timestamp_utc") or time.time()),
        "ticker": str(ms_dict.get("ticker") or "").upper(),
        "route": route,
        "release_id": release_id,
        "release_json": _json_dumps(release),
        "git_sha": release.get("git_sha"),
        "market_inputs_json": _json_dumps(_extract_market_inputs(ms_dict)),
        "risk_state_json": _json_dumps(risk),
        "validation_summary": risk.get("validation_summary") if isinstance(risk.get("validation_summary"), str) else _json_dumps(risk.get("validation_summary")),
        "model_outputs_json": _json_dumps(ms_dict.get("mhap_rows") or ms_dict.get("model_outputs")),
        "fusion_json": _json_dumps(ms_dict.get("fusion") or ms_dict.get("fusion_by_horizon")),
        "final_signal": ms_dict.get("call_signal"),
        "call_conviction": ms_dict.get("call_conviction"),
        "overrides_json": _json_dumps(ms_dict.get("pred_override")),
        "staleness_json": _json_dumps(_extract_staleness(ms_dict)),
        "quarantine_json": _json_dumps(_extract_quarantine(ms_dict)),
        "reconstruction_json": _json_dumps(reconstruction),
        "created_at_utc": time.time(),
    }

    path = Path(db_path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    try:
        ensure_production_decision_schema(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO production_decision_records (
                decision_id, decision_generation_id, decision_ts_utc, ticker, route,
                release_id, release_json, git_sha,
                market_inputs_json, risk_state_json, validation_summary,
                model_outputs_json, fusion_json, final_signal, call_conviction,
                overrides_json, staleness_json, quarantine_json,
                reconstruction_json, created_at_utc
            ) VALUES (
                :decision_id, :decision_generation_id, :decision_ts_utc, :ticker, :route,
                :release_id, :release_json, :git_sha,
                :market_inputs_json, :risk_state_json, :validation_summary,
                :model_outputs_json, :fusion_json, :final_signal, :call_conviction,
                :overrides_json, :staleness_json, :quarantine_json,
                :reconstruction_json, :created_at_utc
            )
            """,
            row,
        )
        conn.commit()
    finally:
        conn.close()
    return decision_id


def get_production_decision_by_id(
    decision_id: str,
    db_path: Path | str,
) -> Optional[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        ensure_production_decision_schema(conn)
        row = conn.execute(
            "SELECT reconstruction_json FROM production_decision_records WHERE decision_id = ?",
            (decision_id.strip(),),
        ).fetchone()
        if not row:
            return None
        return json.loads(row["reconstruction_json"])
    finally:
        conn.close()


RECONSTRUCTION_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "decision_id",
        "decision_generation_id",
        "decision_timestamp_utc",
        "ticker",
        "route",
        "market_inputs",
        "risk_state",
        "validation_summary",
        "model_outputs",
        "fusion_result",
        "final_signal",
        "overrides_active",
        "release",
        "release_id",
        "git_sha",
        "staleness",
        "quarantine",
    }
)


def reconstruction_complete(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = [k for k in sorted(RECONSTRUCTION_REQUIRED_KEYS) if k not in payload]
    if missing:
        return False, missing
    if not str(payload.get("decision_id") or "").strip():
        return False, ["decision_id_empty"]
    if not str(payload.get("release_id") or "").strip():
        return False, ["release_id_empty"]
    return True, []


def production_like_decision_emission(
    db_path: Path | str,
    *,
    ticker: str = "SPY",
) -> dict[str, Any]:
    """
    Closest production-like decision emission without live Schwab traffic.

    Uses route server._fetch_state (NOT audit.* seed). Honest limit: no live
    _fetch_state pipeline — post-pipeline ms_dict shape only.
    """
    from live_decision_bundle import persist_stamped_decision, stamp_decision_bundle
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)
    route = "server._fetch_state"
    ms: dict[str, Any] = {
        "ticker": str(ticker).upper(),
        "spot": 500.0,
        "bid": 499.98,
        "ask": 500.02,
        "spread_pts": 0.04,
        "call_signal": "wait",
        "call_conviction": "low",
        "trade_valid": True,
        "risk_valid": True,
        "dominant_dir": "flat",
        "mhap_rows": [{"horizon": "1c", "signal": "wait", "confidence": 0.4}],
        "fusion_by_horizon": {"1c": {"p_up": 0.33, "p_down": 0.33, "p_flat": 0.34}},
        "validation_summary": "production_like_harness_market_and_risk_ok",
        "session_label": "RTH",
        "call": {
            "signal": "wait",
            "trade_valid": True,
            "risk_valid": True,
            "validation_summary": "production_like_harness_market_and_risk_ok",
        },
    }
    stamp_decision_bundle(ms, route=route)
    decision_id = persist_stamped_decision(ms, route=route, db_path=db_path)
    payload = get_production_decision_by_id(str(decision_id or ""), db_path) if decision_id else None
    ok, missing = reconstruction_complete(payload) if payload else (False, ["no_payload"])
    return {
        "source": "production_like_integration_harness",
        "route": route,
        "decision_id": decision_id,
        "release_id": ms.get("release_id"),
        "market_validation_summary": ms.get("validation_summary"),
        "risk_validation_summary": (ms.get("call") or {}).get("validation_summary"),
        "reconstruction_complete": ok,
        "reconstruction_missing": missing,
        "payload": payload,
    }


def _post_fetch_state_ms_stub(ticker: str) -> dict[str, Any]:
    """Minimal ms_dict shape after build_market_state / _fetch_state compute (no Schwab)."""
    t = str(ticker).upper()
    return {
        "ticker": t,
        "spot": 500.0,
        "bid": 499.98,
        "ask": 500.02,
        "spread_pts": 0.04,
        "call_signal": "wait",
        "call_conviction": "low",
        "trade_valid": True,
        "risk_valid": True,
        "dominant_dir": "flat",
        "session_label": "RTH",
        "mhap_rows": [{"horizon": "1c", "signal": "wait", "confidence": 0.4}],
        "fusion_by_horizon": {"1c": {"p_up": 0.33, "p_down": 0.33, "p_flat": 0.34}},
        "validation_summary": "live_path_simulation_market_and_risk_ok",
        "call": {
            "signal": "wait",
            "trade_valid": True,
            "risk_valid": True,
            "validation_summary": "live_path_simulation_market_and_risk_ok",
        },
        "signals_engine_failed": False,
    }


def live_path_simulation_emission(
    db_path: Path | str,
    *,
    ticker: str = "SPY",
) -> dict[str, Any]:
    """
    Exercises server._finalize_production_decision — the _fetch_state decision tail.

    Label: live_path_simulation (not live_schwab, not production_like_harness, not audit_seed).
    Honest limit: no Schwab chain/quote fetch; post-pipeline ms_dict only.
    """
    import server as srv
    from release_object import initialize_release_at_startup

    initialize_release_at_startup(force=True)
    route = "server._fetch_state"
    ms = _post_fetch_state_ms_stub(ticker)
    path = Path(db_path)
    if srv._HAS_SIGNALS:
        try:
            import db as db_mod

            db_mod.DB_PATH = path
        except ImportError:
            pass
    out = srv._finalize_production_decision(ms, route)
    decision_id = out.get("decision_id")
    payload = get_production_decision_by_id(str(decision_id or ""), path) if decision_id else None
    ok, missing = reconstruction_complete(payload) if payload else (False, ["no_payload"])
    return {
        "source": "live_path_simulation",
        "route": route,
        "decision_id": decision_id,
        "release_id": out.get("release_id"),
        "market_validation_summary": out.get("validation_summary"),
        "risk_validation_summary": (out.get("call") or {}).get("validation_summary"),
        "reconstruction_complete": ok,
        "reconstruction_missing": missing,
        "payload": payload,
        "ms_dict": out,
    }
