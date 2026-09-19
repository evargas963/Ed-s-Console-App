"""Ops/governance admin routes: maintenance launcher, level-cross reads, calibration health,
job/sequence runner, and the manual model-promotion/rollback governance actions.

RC-REHAB-1 (Phase 3): third extraction slice out of server.py's monolithic route table,
following the same pattern as app/api/routes/desk.py and pages.py. Every handler here
delegates to a leaf module (ops_runner, db, calibration.writer, arch_competition.*,
ml_predict) via the same local-import convention server.py already used -- none of them
touch server.py's shared mutable state (`_state_cache`, `_terrain_cache`,
`_analytics_inflight`, the candle accumulators, the executor pools).

`APP_DIR`/`static_dir` are imported lazily inside the function bodies that need them,
matching desk.py/pages.py's convention, so this module has zero module-level dependency
back on `server` and can be imported BY it without a circular import.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("ed_server")

router = APIRouter()


@router.get("/ops", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def ops_panel():
    """Interactive maintenance/training launcher (requires ED_OPS_RUNNER for actions)."""
    from server import static_dir

    p = static_dir / "ops.html"
    if not p.exists():
        return HTMLResponse("<p>static/ops.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@router.get("/api/ops/status")
def api_ops_status():
    from ops_runner import allow_remote, is_ops_runner_enabled, jobs_public_list, sequences_public_list

    return JSONResponse(
        {
            "runner_enabled": is_ops_runner_enabled(),
            "allow_remote": allow_remote(),
            "jobs": jobs_public_list(),
            "sequences": sequences_public_list(),
        }
    )


@router.get("/api/level_crosses")
def api_level_crosses(ticker: str = "SPY", n: int = 20, level_name: str | None = None,
                            level_value: float | None = None, lookback_hours: float = 6.5):
    """Pass 4 — read consumer for level_crosses table.

    Two modes:
      * ``ticker`` only -> last ``n`` crosses (recent breach log).
      * ``ticker`` + ``level_name`` + ``level_value`` -> directional test count
        within ``lookback_hours`` (Decision Command "third test of ceiling"
        pattern, served by db.count_level_tests).
    """
    from db import get_db

    edb = get_db()
    try:
        if level_name is not None and level_value is not None:
            counts = edb.count_level_tests(
                ticker=ticker,
                level_name=level_name,
                level_value=float(level_value),
                lookback_hours=float(lookback_hours),
            )
            return JSONResponse({"ok": True, "mode": "test_count", "ticker": ticker,
                                 "level_name": level_name, "level_value": float(level_value),
                                 "lookback_hours": float(lookback_hours), **counts})
        # RC-88: COLLAPSE COINCIDENT CROSSINGS. Price crossing one strike writes one row per
        # NAMED level sitting there, and the producer's debounce is keyed on level_name, so it
        # cannot see that eight names share a value. MEASURED 2026-07-27: 4,747 of 8,108 stored
        # rows (58.5%) share a (ticker, ts_utc, level_value) with another; IWM 295.0 wrote 8 rows
        # for a single tick. The chart asks for n=8, so one coincident crossing filled every slot
        # and hid every other event. That several concepts coincide is real information — it is
        # carried in `level_names` — but it is ONE crossing, not eight. Collapsed at the READ
        # boundary so the stored history stays intact for anything that needs per-level rows.
        raw = edb.get_recent_crosses(ticker=ticker, n=max(int(n) * 8, 64))
        merged: list[dict] = []
        seen: dict[tuple, dict] = {}
        for r in raw:
            key = (r.get("ts_utc"), r.get("level_value"), r.get("direction"))
            hit = seen.get(key)
            if hit is None:
                row = dict(r)
                row["level_names"] = [r.get("level_name")]
                row["coincident_levels"] = 1
                seen[key] = row
                merged.append(row)
                continue
            nm = r.get("level_name")
            if nm and nm not in hit["level_names"]:
                hit["level_names"].append(nm)
                hit["coincident_levels"] = len(hit["level_names"])
                # One event, one name on screen: say what it is rather than picking one arbitrarily.
                hit["level_name"] = f"{len(hit['level_names'])} levels @ {r.get('level_value')}"
        return JSONResponse({"ok": True, "mode": "recent", "ticker": ticker,
                             "n": int(n), "crosses": merged[:int(n)],
                             "collapsed_from": len(raw)})
    except Exception as exc:  # pragma: no cover — defensive ops surface
        log.warning("api_level_crosses failed ticker=%s: %s", ticker, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@router.get("/api/ops/calibration_rowcount")
def api_ops_calibration_rowcount():
    """Pass 3 — forward-only calibration_decision_log rate health.

    Surfaces last-24h vs prior-24h vs expected row counts so an
    ED_CALIBRATION_LOG=1 environment with a silent gap (DB lock, gate-chain
    bug, schema mismatch, etc.) becomes immediately visible on /ops. Without
    this counter, the Apr 12 - May 5 calibration gap went 24 days
    undetected. Reader for calibration_decision_log.
    """
    from calibration.writer import compute_calibration_rate_health
    from db import DB_PATH as _calibration_db_path

    try:
        health = compute_calibration_rate_health(_calibration_db_path)
    except Exception as exc:  # pragma: no cover — defensive ops surface
        log.warning("calibration rowcount health probe failed: %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    if health.get("warn"):
        log.warning(
            "calibration_decision_log rate WARN: last_24h=%d expected=%.0f ratio=%.2f (threshold=%.2f)",
            health.get("last_24h_count", 0),  # caps-ok: log.warning display argument only, not a decision-path read
            health.get("expected_per_24h", 0.0),  # caps-ok: log.warning display argument only, not a decision-path read
            health.get("ratio") or 0.0,  # caps-ok: log.warning argument only, not a decision-path read  # silent-zero-ok: the same line already prints last_24h and expected, so a 0.00 ratio cannot be mistaken for a measurement
            health.get("warn_ratio", 0.0),  # caps-ok: log.warning display argument only, not a decision-path read
        )
    return JSONResponse({"ok": True, **health})


@router.post("/api/ops/run")
def api_ops_run(request: Request, payload: dict = Body(...)):
    from ops_runner import (
        client_may_trigger,
        is_ops_runner_enabled,
        run_job,
    )

    if not is_ops_runner_enabled():
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Ops runner disabled. Set ED_OPS_RUNNER=1 and restart the server.",
            },
        )
    host = request.client.host if request.client else None
    if not client_may_trigger(host):
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Ops runs are restricted to localhost. Use ED_OPS_ALLOW_REMOTE=1 if intentional (risky).",
            },
        )
    job_id = (payload or {}).get("job_id")
    if not job_id or not isinstance(job_id, str):
        return JSONResponse(status_code=400, content={"ok": False, "error": "body needs { job_id }"})
    return JSONResponse(run_job(job_id.strip()))


@router.get("/governance", response_class=HTMLResponse)  # caps-ok: FastAPI route decorator, not a dict.get(key, default) read
def governance_visibility_page():
    """Architecture governance panel (read-only; manual actions gated on server)."""
    from server import static_dir

    p = static_dir / "governance.html"
    if not p.exists():
        return HTMLResponse("<p>static/governance.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@router.get("/api/governance/panel")
def api_governance_panel(
    ticker: str = Query("SPY", description="Ticker symbol"),
    horizon: str = Query("1c", description="ML horizon slug"),
    emit_notifications: bool = Query(
        False,
        description="When true, run notification delivery emit; use false for routine refresh to avoid duplicate sinks",
    ),
    include_live_drift: bool = Query(True, description="Include live drift monitoring in panel payload"),
):
    from arch_competition.governance_visibility import build_governance_panel_payload
    from server import APP_DIR

    model_dir = Path(APP_DIR) / "models"
    return JSONResponse(
        build_governance_panel_payload(
            model_dir,
            horizon,
            ticker,
            include_live_drift=include_live_drift,
            emit_notification_delivery=emit_notifications,
        )
    )


@router.post("/api/internal/reload_models")
def api_internal_reload_models(request: Request, payload: dict = Body(default={})):
    """Evict in-memory model registries for promoted (ticker, horizon) tuples (PR4 P3-10)."""
    from arch_competition.live_model_reload import RELOAD_SCHEMA_VERSION
    from arch_competition.scheduler_auto_promote_policy import console_reload_token
    from ml_predict import invalidate_model_registry

    host = request.client.host if request.client else None
    if host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse(
            status_code=403,
            content={"schema_version": RELOAD_SCHEMA_VERSION, "error": "non-loopback client forbidden"},
        )
    expected_tok = console_reload_token()
    if expected_tok:
        got = (request.headers.get("X-Reload-Token") or "").strip()
        if got != expected_tok:
            return JSONResponse(
                status_code=403,
                content={"schema_version": RELOAD_SCHEMA_VERSION, "error": "invalid or missing X-Reload-Token"},
            )

    body = payload or {}
    reloads = body.get("reloads")
    if not isinstance(reloads, list):
        return JSONResponse(
            status_code=400,
            content={"schema_version": RELOAD_SCHEMA_VERSION, "error": "reloads must be a list"},
        )

    results: list[dict] = []
    partial = False
    for item in reloads:
        if not isinstance(item, dict):
            partial = True
            results.append({"succeeded": False, "error": "invalid reload item"})
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        hz = str(item.get("horizon") or item.get("ml_horizon_slug") or "").strip().lower()
        if not ticker or not hz:
            partial = True
            results.append(
                {
                    "ticker": ticker or None,
                    "horizon": hz or None,
                    "succeeded": False,
                    "error": "ticker and horizon required",
                }
            )
            continue
        try:
            ok = invalidate_model_registry(ticker, hz)
            results.append({"ticker": ticker, "horizon": hz, "succeeded": bool(ok)})
            if not ok:
                partial = True
        except Exception as e:
            partial = True
            results.append(
                {"ticker": ticker, "horizon": hz, "succeeded": False, "error": str(e)}
            )

    return JSONResponse(
        {
            "schema_version": RELOAD_SCHEMA_VERSION,
            "results": results,
            "partial_failure": partial,
        }
    )


@router.post("/api/governance/manual-promote")
def api_governance_manual_promote(request: Request, payload: dict = Body(...)):
    from arch_competition.exceptions import ManualGovernanceError
    from arch_competition.governance_visibility import (
        client_may_run_governance_action,
        is_governance_ui_actions_enabled,
    )
    from arch_competition.manual_control import manual_promote_to_active_explicit
    from server import APP_DIR

    if not is_governance_ui_actions_enabled():
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Governance UI actions disabled. Set ED_GOVERNANCE_UI_ACTIONS=1 and restart the server.",
            },
        )
    host = request.client.host if request.client else None
    if not client_may_run_governance_action(host):
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Governance actions are restricted to localhost unless ED_GOVERNANCE_ALLOW_REMOTE=1.",
            },
        )
    body = payload or {}
    ticker = (body.get("ticker") or "").strip().upper()
    hz = (body.get("horizon") or body.get("ml_horizon_slug") or "1c").strip().lower()
    target = (body.get("target_architecture") or "").strip().lower()
    op = (body.get("operator_id") or "").strip()
    intent = (body.get("manual_intent") or "").strip()   # external-key-ok: operator HTTP POST body
    if not ticker or target not in ("cascade", "parallel") or not op or not intent:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "Expected ticker, horizon, target_architecture (cascade|parallel), operator_id, manual_intent",
            },
        )
    model_dir = Path(APP_DIR) / "models"
    try:
        result = manual_promote_to_active_explicit(
            model_dir,
            ticker,
            hz,
            target_architecture=target,
            operator_id=op,
            manual_intent=intent,
        )
        return JSONResponse({"ok": True, "result": result})
    except ManualGovernanceError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    except Exception as e:
        log.exception("api_governance_manual_promote: %s", e)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@router.post("/api/governance/manual-rollback")
def api_governance_manual_rollback(request: Request, payload: dict = Body(...)):
    from arch_competition.exceptions import ManualGovernanceError
    from arch_competition.governance_visibility import (
        client_may_run_governance_action,
        is_governance_ui_actions_enabled,
    )
    from arch_competition.manual_control import manual_rollback_to_checkpoint_explicit
    from server import APP_DIR

    if not is_governance_ui_actions_enabled():
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Governance UI actions disabled. Set ED_GOVERNANCE_UI_ACTIONS=1 and restart the server.",
            },
        )
    host = request.client.host if request.client else None
    if not client_may_run_governance_action(host):
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Governance actions are restricted to localhost unless ED_GOVERNANCE_ALLOW_REMOTE=1.",
            },
        )
    body = payload or {}
    ticker = (body.get("ticker") or "").strip().upper()
    hz = (body.get("horizon") or body.get("ml_horizon_slug") or "1c").strip().lower()
    op = (body.get("operator_id") or "").strip()
    intent = (body.get("manual_intent") or "").strip()
    ck = body.get("checkpoint_id")
    if not ticker or not op or not intent:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "Expected ticker, horizon, operator_id, manual_intent",
            },
        )
    model_dir = Path(APP_DIR) / "models"
    try:
        result = manual_rollback_to_checkpoint_explicit(
            model_dir,
            ticker,
            hz,
            operator_id=op,
            manual_intent=intent,
            checkpoint_id=str(ck).strip() if ck else None,
        )
        return JSONResponse({"ok": True, "result": result})
    except ManualGovernanceError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    except Exception as e:
        log.exception("api_governance_manual_rollback: %s", e)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@router.post("/api/ops/run-sequence")
def api_ops_run_sequence(request: Request, payload: dict = Body(...)):
    from ops_runner import (
        client_may_trigger,
        is_ops_runner_enabled,
        run_sequence,
    )

    if not is_ops_runner_enabled():
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Ops runner disabled. Set ED_OPS_RUNNER=1 and restart the server.",
            },
        )
    host = request.client.host if request.client else None
    if not client_may_trigger(host):
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "Ops runs are restricted to localhost. Use ED_OPS_ALLOW_REMOTE=1 if intentional (risky).",
            },
        )
    seq_id = (payload or {}).get("sequence_id")
    if not seq_id or not isinstance(seq_id, str):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "body needs { sequence_id }"},
        )
    return JSONResponse(run_sequence(seq_id.strip(), stop_on_error=True))
