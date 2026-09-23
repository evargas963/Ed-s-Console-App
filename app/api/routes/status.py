"""Process/operator status API routes: health, release identity, build identity, a
retired-decision lookup, vol-observability, and the retired /api/price-levels stub
(RC-REHAB-1, Phase 3). Each route's shared dependency (logger state, the process-identity
singleton captured once at server.py's own module import, _HAS_SIGNALS, etc.) has other
callers or is itself a singleton computed in server.py and stays there, imported back
lazily.
"""

from __future__ import annotations

from datetime import datetime

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/health")
def health():
    from server import _logger_lock, _logger_running, _logger_tickers, schwab_capability_state

    with _logger_lock:
        running = _logger_running
        n       = len(_logger_tickers)
    # RC-514 / docs/ARCHITECTURE.md section 4: application availability and capability
    # availability are separate, so `status` answers "is the app alive" and never folds a
    # vendor outage into it. The capability verdict comes from schwab_capability_state(),
    # which asks the canonical client -- credentials, CI gate AND token state -- rather than
    # the credential gate alone, so health cannot advertise a Schwab that could not serve a
    # quote. Failure to answer reports UNAVAILABLE: unmeasurable is not ok (RC-57).
    try:
        schwab_status, schwab_reason = schwab_capability_state()
    except Exception as exc:  # noqa: BLE001 - health must answer, and never optimistically
        schwab_status, schwab_reason = "UNAVAILABLE", f"{type(exc).__name__}: {exc}"
    capability: dict[str, object] = {"schwab": schwab_status}
    if schwab_reason:
        capability["schwab_reason"] = schwab_reason
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "logger_running": running,
        "logger_tickers": n,
        "capabilities": capability,
    }


@router.get("/api/release/current")
def api_release_current():
    """Current process release object (I-25)."""
    from release_object import get_current_release, validate_release_for_emission

    release = get_current_release(required=False)
    ok, reason = validate_release_for_emission(release)
    if not ok:
        return JSONResponse({"ok": False, "reason": reason, "release": release}, status_code=503)
    return {"ok": True, "release": release}


@router.get("/api/decision/{decision_id}")
def api_decision_by_id(decision_id: str):
    """Retrieve immutable production decision by decision_id (I-31)."""
    from server import _HAS_SIGNALS

    if not _HAS_SIGNALS:
        return JSONResponse({"ok": False, "error": "db_unavailable"}, status_code=503)
    from decision_record import get_production_decision_by_id, reconstruction_complete
    from db import DB_PATH

    payload = get_production_decision_by_id(decision_id, DB_PATH)
    if payload is None:
        return JSONResponse({"ok": False, "error": "not_found", "decision_id": decision_id}, status_code=404)
    complete, missing = reconstruction_complete(payload)
    return {
        "ok": True,
        "decision_id": decision_id,
        "reconstruction_complete": complete,
        "missing_fields": missing,
        "decision": payload,
    }


@router.get("/api/build")
def api_build():
    """Build/identity surface (BUILD_IDENTITY consumer semantics, operator-
    approved 2026-07-10).

    ``git_sha`` == ``process_identity.startup_git_sha``: the code identity the
    RUNNING process loaded, stable for the process lifetime. Request-time
    repository state lives ONLY under ``repository_state_now.repo_head_now``
    (it drifts when HEAD moves and is never process identity). ``code_drift``
    reports explicitly when the checkout has moved past the running process.
    Mechanical lock: tests/test_build_identity_semantics.py forbids new code
    from sourcing process identity from request-time git.
    """
    from dataclasses import asdict

    from release_object import get_current_release
    from gamma_last_valid import _LAST_VALID_GEX_CELLS_ERRORS
    from server import (
        PROCESS_IDENTITY_V1,
        UI_MAXIMIZE_PANEL_WARM_TICKERS,
        UI_MAXIMIZE_SLA_MS,
        _repo_git_head_sha,
    )

    release = get_current_release(required=False)
    repo_head_now = _repo_git_head_sha()
    identity = asdict(PROCESS_IDENTITY_V1)
    startup_sha = identity.get("startup_git_sha")
    return {
        "git_sha": startup_sha,  # PROCESS IDENTITY (startup capture) — never request-time git
        "contract": "meet_or_exceed_v1",
        "release_id": release.get("release_id") if release else None,
        "ui_maximize_sla_ms": dict(UI_MAXIMIZE_SLA_MS),
        "ui_maximize_panel_warm_tickers": list(UI_MAXIMIZE_PANEL_WARM_TICKERS),
        "process_identity": identity,
        "repository_state_now": {"repo_head_now": repo_head_now},
        "code_drift": {
            "repo_moved_past_process": bool(
                startup_sha and repo_head_now and startup_sha != repo_head_now
            ),
            "running_code": startup_sha,
            "checked_out_code": repo_head_now,
        },
        "git_sha_semantics": "startup_process_identity",  # deprecation notice for request-time readers
        # Operator directive (2026-09-15, canonical input-validity rules, THIRD pass):
        # "Database hydrate/flush failures must be observable and fail honestly; they may not
        # be swallowed at debug level while the product implies restart durability." Empty
        # dict means every hydrate/flush this process has attempted succeeded (or none has
        # been attempted yet) -- a non-empty entry is a real, named degradation to
        # in-memory-only-this-session for that ticker, never silent.
        "gamma_last_valid_persistence_errors": dict(_LAST_VALID_GEX_CELLS_ERRORS),
    }


@router.get("/api/vol-observability")
def api_vol_observability(ticker: str | None = Query(default=None)):
    """VOL_OBSERVABILITY_V1: read-only projection of the per-cycle vol-index
    observations ($VIX consumed; $VXN/$RVX FETCHED_UNCONSUMED) plus the
    ratified ticker-class mapping candidate. Never feeds the money path."""
    from vol_observability import vol_observability_payload

    return vol_observability_payload(ticker)


@router.get("/api/price-levels")
def get_price_levels(ticker: str = Query(default=DEFAULT_TICKER), extended_hours: bool = Query(default=True)):
    """RETIRED (RC-213 B6, one-faucet-closeout-v1): /api/levels is the ONE levels surface.

    This route measured ZERO client consumers (census 2026-08-03) and was the second HTTP
    producer for the level families. It hard-fails with a pointer rather than aliasing —
    an alias is a second name for one faucet and second names are how duals grow back.
    The compute path is untouched: _fetch_state still uses fetch_price_levels internally
    (which delegates every family to the liquidity_value_engine authorities)."""
    return JSONResponse({
        "error": "retired",
        "detail": "/api/price-levels is retired (RC-213 B6). Use /api/levels — the single "
                  "levels contract (id/price/family/provenance/staleness per level).",
        "replacement": f"/api/levels?ticker={(ticker or DEFAULT_TICKER).upper().strip()}",
    }, status_code=410)
