"""
server.py — Ed Console FastAPI Backend
=======================================
Drop this in C:\\Users\\evarg\\Documents\\EdWebConsole\\
Run with:  uvicorn server:app --host 0.0.0.0 --port 8000

Endpoints:
  GET  /                          → serves static/index.html
  GET  /api/live/state            → Tier A: live quote plane + session + identity (first paint; no chain/DB)
  GET  /api/analytics/light       → L1 authoritative cache read (+ L0 overlay); full compute on cold miss / force; GET /api/diagnostics/l1
  GET  /api/analytics/light/stream → SSE: L1 payloads after authoritative builds (same as HTTP GET; no extra compute)
  GET  /api/analytics/state       → Tier C: full analytical MarketState (chain, exposures, fusion, DB, news)
  POST /api/analytics/warm        → schedule Tier C refresh + optional ML artifact prewarm (UI-MAXIMIZE)
  GET  /api/state                 → legacy alias of Tier C (same payload as /api/analytics/state)
  GET  /api/expiries?ticker=SPY   → list of available expiry dates
  GET  /api/logger/status         → background logger status
  POST /api/logger/add?ticker=X   → add ticker to background logger
  GET  /static/*                  → serves static files
  GET  /guide/data-stewardship   → data stewardship & maintenance runbook (from DATA_STEWARDSHIP.md)
  GET  /guide/training-and-maintenance → training cadence + /ops (from TRAINING_AND_MAINTENANCE.md)
  GET  /guide/pipeline-quality   → TQM checkpoints along ingest → normalized → training (PIPELINE_QUALITY.md)
  GET  /ops                       → optional click-to-run ops panel (needs ED_OPS_RUNNER=1)
  GET  /api/ops/status            → list jobs; POST run when runner enabled + localhost
  GET  /governance               → ML architecture governance operator dashboard (read-only + optional manual actions)
  GET  /api/governance/panel      → governed panel JSON; query emit_notifications=false avoids notification sink emit on refresh
  POST /api/governance/manual-promote|manual-rollback → calls manual_control only (needs ED_GOVERNANCE_UI_ACTIONS=1)

Install deps (once):
  pip install fastapi uvicorn[standard]
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
import asyncio
import logging
import concurrent.futures
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import OrderedDict, defaultdict
from copy import deepcopy
from typing import Any, Dict, Optional
from dataclasses import asdict, dataclass

import time_et as _time_et
from time_et import (now_et, RTH_OPEN_MINS, RTH_END_MINS, is_capturable_session,
                     is_trading_day_et)

import html
import hashlib
import json
import queue

from planes.l1_decision_dependencies import warn_l1_payload_key_drift
from planes.l1_fingerprint_material import build_l1_material_dict_for_fingerprint

from fastapi import Body, FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── App directory = same folder as this file ─────────────────────────────────
APP_DIR = str(Path(__file__).parent.resolve())
sys.path.insert(0, APP_DIR)

# ── Logging ──────────────────────────────────────────────────────────────────
# Visual severity marker: WARNING / ERROR / CRITICAL get a bracket-tag prefix
# (ANSI-colored on a TTY; plain ASCII otherwise) so operator-actionable events
# stand out in the dense INFO/DEBUG console stream. Steady-state DEBUG/INFO
# remain unmarked. The operator-flagged regression was post-LIVE-UI-A: charm/
# IV/seq_len logs were correctly demoted to DEBUG, but the residual WARNINGs
# then sat in the same visual stream as INFO — easy to miss.
class _LevelMarkerFormatter(logging.Formatter):
    _ANSI_BY_LEVEL = {
        logging.WARNING:  "\033[33m[WARN]\033[0m ",   # yellow
        logging.ERROR:    "\033[31m[ERR ]\033[0m ",   # red
        logging.CRITICAL: "\033[1;31m[CRIT]\033[0m ", # bold red
    }
    _PLAIN_BY_LEVEL = {
        logging.WARNING:  "[WARN] ",
        logging.ERROR:    "[ERR ] ",
        logging.CRITICAL: "[CRIT] ",
    }

    def __init__(self, fmt: str | None = None, *, use_ansi: bool = True) -> None:
        super().__init__(fmt)
        self.use_ansi = use_ansi

    def format(self, record: logging.LogRecord) -> str:
        table = self._ANSI_BY_LEVEL if self.use_ansi else self._PLAIN_BY_LEVEL
        marker = table.get(record.levelno, "")
        return marker + super().format(record)


class _FlushingFileHandler(logging.FileHandler):
    """FileHandler that flushes after every emit so quiet-window gates see live lines."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


# Quiet-window / LIVE closeout sink. Root handler so ANY logger (db, ed_server,
# uvicorn, …) at INFO+ lands here; gate fails on WARNING+ / traceback.
ED_SERVER_LOG_PATH = Path(__file__).resolve().parent / "logs" / "ed_server.log"


def install_ed_server_file_sink(
    log_path: Path | None = None,
    *,
    level: int = logging.INFO,
) -> logging.Handler:
    """Attach a flushing plain FileHandler on the root logger for logs/ed_server.log.

    Captures all loggers (root). INFO+ so a healthy process proves the sink is
    alive (gate fail-closes on a stale file); WARNING+/ERROR/CRITICAL still
    appear for the quiet-window matcher. Idempotent for this path.
    """
    path = Path(log_path) if log_path is not None else ED_SERVER_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    abs_target = str(path.resolve())
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            try:
                existing = str(Path(getattr(h, "baseFilename", "")).resolve())
            except (OSError, TypeError, ValueError):
                existing = ""
            if existing == abs_target:
                return h
    handler = _FlushingFileHandler(path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        _LevelMarkerFormatter("%(levelname)s:%(name)s:%(message)s", use_ansi=False)
    )
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return handler


def _install_visual_severity_markers(level: int = logging.INFO) -> None:
    """Replace any default root handlers with one that adds the level marker."""
    use_ansi = bool(getattr(sys.stderr, "isatty", lambda: False)())
    handler = logging.StreamHandler()
    handler.setFormatter(
        _LevelMarkerFormatter("%(levelname)s:%(name)s:%(message)s", use_ansi=use_ansi)
    )
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    # t6/RC-232 board (quiet-gate finding, root-caused): `import server` under pytest
    # attached this SAME live-log file sink, so TEST-emitted warnings (the deliberate
    # ZZQD/ZZQE failure fixtures, fresh-DB migration notices) appended to logs/ed_server.log
    # and the quiet-window gate read them as live console noise. The ZZQD "leak" was never
    # in any DB — it was test log pollution through the shared sink. Tests keep the stream
    # handler; only the FILE sink is skipped under pytest (the sink's own unit test calls
    # install_ed_server_file_sink directly with a tmp path and is unaffected).
    if "pytest" not in sys.modules and not os.environ.get("PYTEST_CURRENT_TEST"):
        install_ed_server_file_sink(ED_SERVER_LOG_PATH, level=level)


_install_visual_severity_markers(logging.INFO)
log = logging.getLogger("ed_server")


def _log_calibration_logging_state_at_boot() -> None:
    """One-shot boot diagnostic: surface whether calibration writer is enabled.

    Root cause of the 2026-04-12 → 2026-05-05 calibration_decision_log gap was the
    writer being env-gated (ED_CALIBRATION_LOG default-OFF) with zero operator
    visibility — silent return None on every call. Emit a clear WARNING (visible
    via the level-marker formatter) at boot when the writer is disabled so the
    operator never restarts into "writer silently dropping all rows" without
    knowing it.
    """
    # RC-230 (second cut): importing config does NOT load .env — only build_config() calls
    # _ensure_dotenv_loaded(). The first fix moved this call after the import and the false
    # DISABLED warning still fired (measured, PID 35680). Load .env explicitly here.
    try:
        from config import _ensure_dotenv_loaded
        _ensure_dotenv_loaded()
    except ImportError:
        pass
    try:
        from calibration.writer import calibration_logging_enabled
    except ImportError:
        log.warning(
            "calibration writer import failed at boot — calibration_decision_log will be silent"
        )
        return
    if calibration_logging_enabled():
        log.info("calibration logging ENABLED (ED_CALIBRATION_LOG=on) — writer will persist decisions")
    else:
        log.warning(
            "calibration logging DISABLED — ED_CALIBRATION_LOG not in {1,true,yes,on}; "
            "calibration_decision_log writer will silently skip all rows. "
            "Set ED_CALIBRATION_LOG=1 in .env to enable."
        )


# ── Import all existing Ed Console modules (unchanged) ───────────────────────
from config import build_config, DEFAULT_TICKER

# RC-230 quiet-gate finding: this boot diagnostic ran BEFORE the config import that loads
# .env, so it read a bare os.environ and warned "calibration logging DISABLED" on every
# boot even with ED_CALIBRATION_LOG=1 correctly present in .env — a false alarm that also
# failed the ed_server_warn_quiet_window gate. It must run AFTER dotenv is loaded.
_log_calibration_logging_state_at_boot()
from schwab_client import (
    auth_is_refreshable,
    build_client_from_token,
    inspect_token_file,
    safe_get_chain,
    safe_get_quote,
    safe_get_price_history,
    SchwabAuthError,
)
from instrument_identity import ticker_storage_key   # RC-126: the ONE query-symbol authority
from math_exposure import (
    MISSING_GREEK_SENTINEL,
    gamma_is_plausible,
    _f,
    compute_exposures_by_strike,
    build_summary_rows,
    build_walls_rows,
    build_totals_rows,
    session_bucket as _session_bucket,
    vix_bucket as _vix_bucket,
    classify_direction as _classify_direction,
    compute_expected_move_straddle, compute_expected_move_iv,
    compute_em_progress, compute_iv_skew, compute_realized_vol, compute_atr,
    compute_iv_rank, compute_iv_percentile, compute_volatility_envelope,
    compute_garch_forecast, blend_garch_sigma,
    compute_iv_model_spread,
    compute_gamma_flip_v2, compute_gamma_void_zones, compute_level_density, gamma_at_price,
    infer_strike_increment, required_strike_count,
    pick_net_gex_peak_strike, exposures_have_dollar_gex, gex_magnitude_label, gex_regime_label,
    aggregate_net_gex, total_gamma_raw_at_strike,
    bucket_metric, compute_dealer_pressure_index, compute_hedging_flow_score,
    compute_gamma_gradient, compute_breakout_score,
    compute_pin_score, compute_vol_expansion_signal, compute_sweep_score,
    compute_sector_strength,
    compute_iwm_confluence,
    compute_volume_oi_ratio,
    compute_smart_money_signal,
    flow_imbalance_label_from_normalized,
    flow_imbalance_normalized_with_fallback,
)
from math_snapshot_derive import derive_pressure_trend, derive_vwap_side
from market_context import (
    fetch_market_context,
    fetch_price_levels,
    market_context_panel_symbols_excluding_core,
    stamp_confluence_display_fields,
    PriceLevels,
    _derive_session,
)
from market_state import MarketVolContextV1, build_market_state, derive_zone
from vol_observability import record_market_vol_observation, vol_observability_payload
from ml_horizon import PRIMARY_DECISION_HORIZONS, SECONDARY_SUPPORT_HORIZONS
from realized_contract_eval import serialize_option_chain_for_eval, build_replay_context_payload
from live_decision_bundle import stamp_decision_bundle, tick_triggers_coherent_refresh, persist_stamped_decision
from v2_decision import build_module_a_a1_decision
from v2_decision.a1_conformal_artifact_attachment import attach_a1_conformal_artifact_to_ms_dict
from v2_decision.a1_isotonic_calibration_attachment import attach_a1_isotonic_calibration_to_ms_dict
from terrain_read import build_terrain_read
from terrain_engine import compute_terrain, wall_geometry_state
from terrain_atr import RING_REGIME, AtrPair, atr_distance, compute_atr_pair, ring_for

try:
    from db import get_db
    _HAS_SIGNALS = True
except Exception as e:
    _HAS_SIGNALS = False
    log.warning(f"signals/db not available: {e}")

import live_market_plane as _lmp

try:
    from crash_trace import step as _diag_step, step_done as _diag_done, trace_crash as _diag_crash, _on as _diag_on
except ImportError:
    _diag_on = lambda: False
    _diag_step = _diag_done = lambda n, t="": None
    _diag_crash = lambda n, e, t="": None

# ── Config + Schwab client (refreshable singleton) ────────────────────────────
cfg     = build_config(APP_DIR)
_client = None


def _log_schwab_startup_diagnostics():
    """Log cwd, token path, existence — helps diagnose link vs manual launch mismatch."""
    cwd = os.getcwd()
    token_path = cfg.token_path
    inv = inspect_token_file(token_path)
    token_exists = inv.file_exists
    refreshable = auth_is_refreshable(inv)
    python_exe = sys.executable
    log.info(
        "Schwab auth diagnostics: cwd=%r token_path=%r token_exists=%s python=%r",
        cwd, token_path, token_exists, python_exe,
    )
    log.info(
        "Schwab token inspection: path=%r exists=%s json_valid=%s refreshable=%s scope=%r expires_at_present=%s",
        token_path,
        inv.file_exists,
        inv.json_valid,
        refreshable,
        inv.scope_value,
        inv.has_expires_at,
    )
    log.info(
        "Schwab token timing: seconds_to_expiry=%s expired=%s expiring_soon=%s",
        inv.seconds_to_expiry,
        inv.is_expired,
        inv.is_expiring_soon,
    )
    if not token_exists:
        log.error(
            "Token file not found. CWD=%r may differ from app dir. "
            "Set SCHWAB_TOKEN_PATH to absolute path, or run from project directory. "
            "Remediation: python reauth_schwab.py",
        )
    elif inv.file_exists and inv.json_valid and inv.has_token_object and not refreshable:
        log.error(
            "Schwab token file exists but is NOT refreshable (refresh_token missing or empty). "
            "Remediation: python reauth_schwab.py --manual",
        )


def reset_schwab_client() -> None:
    """Clear cached client. Next get_client() will rebuild (e.g. after token refresh)."""
    global _client
    _client = None
    log.info("Schwab client cache cleared")


def get_client(force_refresh: bool = False):
    """Return Schwab client. force_refresh=True clears cache and rebuilds."""
    global _client
    if force_refresh:
        _client = None
    if _client is None:
        state = build_client_from_token(
            api_key=cfg.api_key,
            app_secret=cfg.app_secret,
            token_path=cfg.token_path,
        )
        if not state.ok or state.client is None:
            log.error(f"Schwab client init failed: {state.message}")
            raise HTTPException(status_code=503, detail=f"Schwab auth failed: {state.message}")
        _client = state.client
        log.info("Schwab client initialized")
    return _client


def _safe_get_quote_with_retry(client, ticker: str, *, attempt_hook=None):
    """Quote fetch with token-error retry: rebuilds client once and retries."""
    return safe_get_quote(
        client,
        ticker,
        refresh_client_fn=lambda: get_client(force_refresh=True),
        attempt_hook=attempt_hook,
    )


#: AUDIT-QUOTE-MEMO-V1 (operator directive 2026-07-28, RC-112): the terrain poll and the fast
#: lane each called Schwab independently for the SAME ticker — a double vendor fetch per tick,
#: and display could reprice on a quote math never saw. ONE short-TTL memo now sits under BOTH
#: paths: the vendor is read once and display + math fan out from that single read. TTL 1.0s is
#: longer than any same-tick fan-out and far shorter than every consumer cadence, so no reader
#: sees more staleness than the fast lane already tolerated.
QUOTE_MEMO_TTL_SEC: float = 1.0
_quote_memo: dict[str, tuple[float, object]] = {}
_quote_memo_lock = threading.Lock()


def _memoized_quote_response(ticker: str, *, client=None, attempt_hook=None):
    """ONE Schwab quote read per ticker per TTL, shared by the fast lane AND resolve_spot.

    Only a 200 response is memoized — a failure is never cached (fail-loud: the next caller
    goes back to the vendor). Consumers treat the response as READ-ONLY; .json() re-parses
    the already-buffered body, so cross-thread sharing is safe. No single-flight on purpose:
    a same-instant stampede costs at most one duplicate call, and the chain-gate style
    event plumbing is not worth that margin here.
    """
    tk = (ticker or "").upper().strip()
    now = time.monotonic()
    with _quote_memo_lock:
        hit = _quote_memo.get(tk)
        if hit is not None and (now - hit[0]) < QUOTE_MEMO_TTL_SEC:
            return hit[1]
    resp = _safe_get_quote_with_retry(
        client if client is not None else get_client(), tk, attempt_hook=attempt_hook)
    if resp is not None and getattr(resp, "status_code", None) == 200:
        with _quote_memo_lock:
            _quote_memo[tk] = (time.monotonic(), resp)
    return resp


# ── TIER_C_CHAIN_FETCH_GATE_IMPLEMENTATION_V1 — serialize Schwab chain fetches ──
# Root cause (TIER_C_RECOMPUTE_LATENCY_V1 stage-split sample 2026-07-06): three
# concurrent Tier C recomputes stretch safe_get_chain from ~1-3s solo to 10-22s,
# alone exceeding the 10s freshness budget. The gate lives at the _fetch_state
# call site so it covers EVERY trigger source (warm / SSE loop / viewer / force /
# harness) — all converge there. Fail-open: acquire timeout logs loudly and
# proceeds ungated; chain data semantics are untouched either way. The gate is
# held only around the network call — nothing submits into any pool under it.
# Schwab CSV authority checked: yes
# CSV row(s): chains.* via schwab_client.safe_get_chain — call shape unchanged
#   (safe_get_chain(client, ticker, strike_count=CHAIN_STRIKE_COUNT)); this is
#   scheduling-only serialization, no field read/derivation/emission change.
# Derived-field disposition: none required (no derived field touched);
#   chain_gate_wait_sec is passive observability only.
# All consumers checked: yes — c_resp consumed identically downstream in
#   _fetch_state; other safe_get_chain call sites intentionally not gated
#   (approved scope: _fetch_state site only).
# SCHWAB_CSV_CHECKED
# UI_05_OPERATOR_PRIORITY_ADMISSION_V1 (2026-07-10): single-slot gate with a
# two-class wait discipline. Operator-facing chain fetches (viewer switch /
# SSE / REST poll) acquire the slot before queued background acquirers
# (logger / idle refresh / warm). Total Schwab concurrency is UNCHANGED —
# still exactly one chain fetch at a time; only the ORDER of waiters changes.
# Measured cause (2026-07-10 RTH): cold-guest wall-to-chain 11–48s behind
# background chains while pure Schwab fetch is 0.8–2.6s.
CHAIN_GATE_GLOBAL_SLOTS_MAX: int = 2
CHAIN_GATE_DEGRADED_SLOTS: int = 1
CHAIN_GATE_BREAKER_FAILURE_THRESHOLD: int = 3
CHAIN_GATE_BREAKER_COOLDOWN_SEC: float = 120.0


class _ChainGateV2:
    """Bounded TWO-slot chain gate (operator-approved 2026-07-10 EVE).

    Controls (mechanically tested in tests/test_chain_gate_v2.py):
      - global max CHAIN_GATE_GLOBAL_SLOTS_MAX (2) concurrent chain requests;
      - priority-first handoff: while any priority waiter is queued,
        background acquirers stand down (the discipline the single-slot
        gate proved);
      - automatic degradation to CHAIN_GATE_DEGRADED_SLOTS (1) for
        CHAIN_GATE_BREAKER_COOLDOWN_SEC when the source degrades: HTTP
        throttling, auth instability, or
        CHAIN_GATE_BREAKER_FAILURE_THRESHOLD consecutive failures;
        recovery is automatic at cooldown expiry;
      - complete metrics (slot assignment, queue waits, coalescing,
        timeouts, breaker state, fallback reason) via snapshot() ->
        /api/diagnostics/chain-gate.

    Per-ticker max 1 + duplicate coalescing live in _gated_safe_get_chain
    (the request layer); the gate owns global capacity only.
    acquire(timeout=None, priority=False)/release() stay Semaphore-shaped.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._in_use = 0
        self._priority_waiting = 0
        self._degraded_until = 0.0
        self._consecutive_failures = 0
        self.metrics: dict = {
            "acquisitions": 0,
            "priority_acquisitions": 0,
            "timeouts": 0,
            "queue_wait_max_ms": 0.0,
            "coalesced_hits": 0,
            "degraded_entries": 0,
            "degraded_reason_last": None,
            "last_result_ok": None,
        }

    def _capacity(self) -> int:
        return (
            CHAIN_GATE_DEGRADED_SLOTS
            if time.monotonic() < self._degraded_until
            else CHAIN_GATE_GLOBAL_SLOTS_MAX
        )

    def degraded(self) -> bool:
        return time.monotonic() < self._degraded_until

    def acquire(self, timeout: float | None = None, priority: bool = False) -> bool:
        started = time.monotonic()
        deadline = None if timeout is None else started + timeout
        with self._cond:
            if priority:
                self._priority_waiting += 1
            try:
                while True:
                    if self._in_use < self._capacity() and (
                        priority or self._priority_waiting == 0
                    ):
                        self._in_use += 1
                        waited_ms = round((time.monotonic() - started) * 1000.0, 1)
                        self.metrics["acquisitions"] += 1
                        if priority:
                            self.metrics["priority_acquisitions"] += 1
                        if waited_ms > self.metrics["queue_wait_max_ms"]:
                            self.metrics["queue_wait_max_ms"] = waited_ms
                        return True
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        self.metrics["timeouts"] += 1
                        return False
                    self._cond.wait(min(remaining, 1.0) if remaining is not None else 1.0)
            finally:
                if priority:
                    self._priority_waiting -= 1

    def release(self) -> None:
        with self._cond:
            self._in_use = max(0, self._in_use - 1)
            self._cond.notify_all()

    def record_result(self, ok: bool, *, throttled: bool = False, auth_error: bool = False) -> None:
        """Source-health input driving the breaker. Never raises; callers
        re-raise their own exceptions (nothing is swallowed here)."""
        with self._cond:
            self.metrics["last_result_ok"] = bool(ok)
            if ok and not throttled and not auth_error:
                self._consecutive_failures = 0
                return
            self._consecutive_failures += 1
            reason = (
                "http_throttled" if throttled
                else "auth_unstable" if auth_error
                else "consecutive_failures"
                if self._consecutive_failures >= CHAIN_GATE_BREAKER_FAILURE_THRESHOLD
                else None
            )
            if reason is not None:
                self._degraded_until = time.monotonic() + CHAIN_GATE_BREAKER_COOLDOWN_SEC
                self.metrics["degraded_entries"] += 1
                self.metrics["degraded_reason_last"] = reason
                self._cond.notify_all()

    def snapshot(self) -> dict:
        with self._cond:
            return {
                **self.metrics,
                "in_use": self._in_use,
                "capacity_now": self._capacity(),
                "global_slots_max": CHAIN_GATE_GLOBAL_SLOTS_MAX,
                "degraded": time.monotonic() < self._degraded_until,
                "priority_waiting": self._priority_waiting,
                "consecutive_failures": self._consecutive_failures,
            }


_schwab_chain_fetch_gate = _ChainGateV2()
CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC: float = 30.0
_chain_fetch_gate_timeout_count: int = 0

# Per-ticker single-flight + duplicate coalescing (max ONE active chain
# request per ticker; duplicate same-ticker callers wait on the owner
# result: same response object, same ticker, so no cross-ticker delivery
# and no provenance change).
_chain_inflight_lock = threading.Lock()
_chain_inflight: dict = {}


def flatten_chain_contracts(c_json: dict) -> list[dict]:
    """Flatten a Schwab chain response into a flat contract list.

    Single source: this was inline inside _fetch_state and is now shared with the
    terrain loop, so both consume the chain identically. Schwab CSV authority: reads
    chains.callExpDateMap.* / chains.putExpDateMap.* only; no derivation.
    """
    out: list[dict] = []
    if not isinstance(c_json, dict):
        return out
    for side_key in ("callExpDateMap", "putExpDateMap"):
        side_map = c_json.get(side_key) or {}
        if not isinstance(side_map, dict):
            continue
        for exp_map in side_map.values():
            if not isinstance(exp_map, dict):
                continue
            for strike_list in exp_map.values():
                if not isinstance(strike_list, list):
                    continue
                for ct in strike_list:
                    if isinstance(ct, dict):
                        out.append(dict(ct))
    return out


def chain_underlying_spot(c_json: dict) -> float | None:
    """Underlying last price from the chain payload (include_underlying_quote).

    Fails closed: returns None rather than inventing a spot, so terrain refuses to
    publish levels priced off a missing underlying.
    """
    if not isinstance(c_json, dict):
        return None
    u = c_json.get("underlying")
    if not isinstance(u, dict):
        return None
    for key in ("last", "mark", "close"):
        v = _safe_float_quote(u.get(key))
        if v is not None and v > 0:
            return v
    return None


#: Precedence for the ONE spot authority. Highest wins; every entry records where the
#: number came from so a caller can never silently accept a lower-confidence source.
SPOT_SOURCE_QUOTE = "schwab_quote_last"        # quotes.{SYM}.quote.lastPrice - a real trade
SPOT_SOURCE_REGULAR_CLOSE = "regular_close"    # regularMarketLastPrice - a CLOSE, not a spot
SPOT_SOURCE_CHAIN = "chain_underlying"         # chains.underlying.last (== close after hours)
SPOT_SOURCE_SNAPSHOT = "stored_snapshot"       # last persisted snapshot (may be minutes old)

#: Sources that are a SESSION CLOSE rather than a live trade. Verified against the wire
#: 2026-07-19 after hours: quote.closePrice, quote.mark, regular.regularMarketLastPrice,
#: chains.underlying.last and chains.underlyingPrice ALL read 743.29 (Friday's regular
#: close) while quote.lastPrice read 742.4861 (the true last trade, postMarketChange
#: -0.8039). `chain.underlying.last` is therefore NOT a last price -- treating it as one
#: silently serves the prior session's close as though it were spot.
SPOT_CLOSE_SOURCES = frozenset({SPOT_SOURCE_REGULAR_CLOSE, SPOT_SOURCE_CHAIN})


def _spot_from_quote(ticker: str) -> tuple[float | None, float | None]:
    """Live Schwab quote leg of the spot authority. Returns (spot, trade_time)."""
    try:
        # RC-112: through the shared memo — math reads the SAME vendor quote the fast lane
        # serves (and gains its token-retry semantics), never a second independent fetch.
        q_resp = _memoized_quote_response(ticker)
    except Exception as e:
        log.debug("resolve_spot quote leg failed for %s: %s", ticker, e, exc_info=True)
        return None, None
    if q_resp is None or getattr(q_resp, "status_code", None) != 200:
        return None, None
    try:
        node = (q_resp.json() or {}).get(ticker) or {}
        parsed = _parse_quote_node_session_fields(node)
    except Exception as e:
        log.debug("resolve_spot quote parse failed for %s: %s", ticker, e, exc_info=True)
        return None, None
    # KEY NAME IS "spot" -- `_parse_quote_node_session_fields` returns spot/last/mark, NOT
    # "spot_f" (that is the local variable name inside it). Reading the wrong key returned
    # None on every call, so the authority silently fell through to a stale stored
    # snapshot and the card kept disagreeing with the header. Locked by
    # tests/test_spot_authority_v1.py::test_quote_parser_key_contract.
    spot = parsed.get("spot")
    if spot and spot > 0:
        return float(spot), parsed.get("trade_time")
    log.warning("resolve_spot: quote leg produced no usable spot for %s "
                "(last=%s mark=%s) - falling back to a lower-precedence source",
                ticker, parsed.get("last"), parsed.get("mark"))
    return None, None


#: Seconds the graceful shutdown gets before the process is killed outright. Generous
#: enough for real teardown (the executors above cancel queued work immediately), short
#: enough that the operator is never held hostage by one wedged vendor call.
SHUTDOWN_DEADLINE_SEC: float = 12.0
_shutdown_watchdog_armed = threading.Event()


def _hard_exit(reason: str) -> None:
    """Terminate NOW, bypassing atexit. The only thing that beats a stuck join.

    `os._exit` is deliberate: `sys.exit` unwinds through the concurrent.futures atexit
    hook, which is one of the things that hangs. Nothing here needs atexit for durability
    -- DB writes commit inline, and every background pool is a cache/refresh whose work is
    disposable by design.
    """
    try:
        log.warning("HARD EXIT: %s", reason)
        for h in list(getattr(log, "handlers", []) or []):
            # A handler that cannot flush must not stop the exit — that would reintroduce
            # exactly the hang this function exists to end.
            with contextlib.suppress(Exception):
                h.flush()
        sys.stderr.write(f"\nHARD EXIT: {reason}\n")
        sys.stderr.flush()
    finally:
        os._exit(0)


def _arm_shutdown_watchdog(deadline_sec: float = SHUTDOWN_DEADLINE_SEC) -> None:
    """Kill the process if graceful shutdown has not finished within the deadline.

    REFUSES under pytest (RC-10 class). TestClient runs the lifespan inside the TEST
    process; arming here left a daemon thread that outlived the test and os._exit(0)'d
    PYTEST ITSELF 12 s later -- mid-suite, silently, exit code 0, all captured output
    lost. OBSERVED 2026-07-20: tests/adversarial/test_remaining_route_inventory.py
    "passed" with zero output; Cursor's full-suite run died the same way and read as a
    hang. A watchdog that can kill the test runner is worse than the hang it prevents.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if _shutdown_watchdog_armed.is_set():
        return
    _shutdown_watchdog_armed.set()

    def _watch() -> None:
        time.sleep(deadline_sec)
        _hard_exit(
            f"graceful shutdown exceeded {deadline_sec:.0f}s - a background worker is "
            f"blocked (slow vendor call or long query) and cannot be interrupted"
        )

    threading.Thread(target=_watch, name="shutdown-watchdog", daemon=True).start()


def _install_signal_handlers() -> None:
    """First Ctrl+C asks politely; a second one is not a request.

    Without this the operator's only recourse was killing the process from another
    window, because uvicorn's graceful path was blocked downstream of the signal.
    """
    def _on_signal(signum, _frame):
        if _shutdown_watchdog_armed.is_set():
            _hard_exit(f"second interrupt (signal {signum}) - exiting immediately")
        log.warning("signal %s received - shutting down (press Ctrl+C again to force)", signum)
        sys.stderr.write("\nShutting down… press Ctrl+C again to force immediate exit.\n")
        sys.stderr.flush()
        _arm_shutdown_watchdog()
        raise KeyboardInterrupt

    # RC-166: SIGBREAK (Ctrl+Break on Windows) was NOT registered, so it bypassed this handler
    # entirely and the 12s hard-exit watchdog never armed. MEASURED 2026-07-31: a console sent
    # CTRL_BREAK_EVENT took 24.8s to exit — twice the deadline that exists to bound it — because
    # the exit fell through to Python's default and waited on whatever background worker was
    # blocked. Ctrl+Break is the operator's second lever when Ctrl+C is being swallowed, so it
    # must reach the same bounded path. `getattr` because SIGBREAK is Windows-only.
    _sigs = [signal.SIGINT, signal.SIGTERM]
    _sigbreak = getattr(signal, "SIGBREAK", None)
    if _sigbreak is not None:
        _sigs.append(_sigbreak)
    for sig in _sigs:
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError, AttributeError) as e:
            # Not the main thread, or the platform lacks it — never fatal.
            log.debug("could not install handler for %s: %s", sig, e)


def _spot_from_stored(ticker: str) -> tuple[float | None, float | None]:
    """Last persisted snapshot leg. Explicitly stale — lowest precedence."""
    import sqlite3 as _sq

    try:
        con = _sq.connect(f"file:{get_db().db_path}?mode=ro", uri=True, timeout=30.0)
    except Exception as e:
        log.debug("resolve_spot stored leg failed for %s: %s", ticker, e, exc_info=True)
        return None, None
    row = None
    try:
        con.row_factory = _sq.Row
        # `timeframe` MUST be named: idx_snap_ticker_tf_ts is (ticker, timeframe, ts_utc),
        # so skipping the middle column makes the ts_utc ordering unusable and forces a
        # full read of every row for this ticker into a temp B-tree. On a table whose rows
        # carry ~50 KB inline chain blobs that is catastrophic -- the identical omission in
        # _latest_chain_and_spot did not finish inside 300 s (MEASURED 2026-07-20).
        for tf in _STORED_CHAIN_TIMEFRAMES:
            row = con.execute(
                "SELECT spot, ts_utc FROM snapshots "
                "WHERE ticker=? AND timeframe=? AND spot IS NOT NULL "
                "ORDER BY ts_utc DESC LIMIT 1", (ticker, tf)).fetchone()
            if row:
                break
    except Exception:
        return None, None
    finally:
        con.close()
    return (float(row["spot"]), row["ts_utc"]) if row and row["spot"] else (None, None)


def resolve_spot(ticker: str, *, chain_json: dict | None = None,
                 allow_stored: bool = True,
                 quote_node: dict | None = None) -> tuple[float | None, str, float | None]:
    """THE single spot authority. Returns (spot, source, as_of_ts_utc).

    RC-14: four independent spot sources existed and each consumer picked one, so the
    terrain card and the console header displayed different prices for the same ticker at
    the same instant (743.29 vs 742.49). Every consumer now calls this, and every payload
    carries the source, so a divergence is impossible to hide.

    Precedence is by freshness and by matching what the operator SEES:
      1. live Schwab quote (lastPrice -> mark) -- the console header's number
      2. the chain's own underlying node -- as fresh as the chain, no extra call
      3. the last stored snapshot -- explicitly stale, only when nothing better exists
    """
    tk = (ticker or "").upper().strip()
    if not tk:
        return None, "none", None

    # 1. the only source that is a REAL TRADE. When the caller already fetched the quote
    #    (the hot _fetch_state path), reuse that node instead of a second round-trip — the
    #    precedence + fallbacks below are then IDENTICAL to every other consumer, so the
    #    analytics card can no longer derive a different spot than the header / terrain.
    if quote_node is not None:
        _pq = _parse_quote_node_session_fields(quote_node)
        _sp = _pq.get("spot")
        if _sp and _sp > 0:
            return float(_sp), SPOT_SOURCE_QUOTE, _pq.get("trade_time")
    else:
        spot, ts = _spot_from_quote(tk)
        if spot is not None:
            return spot, SPOT_SOURCE_QUOTE, ts

    # 2. stored snapshot BEFORE the chain: a persisted snapshot was itself captured from
    #    quote.lastPrice, so it is a stale TRADE. The chain underlying is a session CLOSE
    #    masquerading as "last", which is worse than a slightly old real price.
    if allow_stored:
        spot, ts = _spot_from_stored(tk)
        if spot is not None:
            return spot, SPOT_SOURCE_SNAPSHOT, ts

    # 3. last resort, explicitly labelled as a CLOSE so no caller can mistake it for spot
    if chain_json is not None:
        spot = chain_underlying_spot(chain_json)
        if spot and spot > 0:
            return float(spot), SPOT_SOURCE_CHAIN, None
    return None, "none", None


def spot_is_a_close(source: str) -> bool:
    """True when the value is a session CLOSE, not a live trade — the UI must say so."""
    return source in SPOT_CLOSE_SOURCES


def _gated_safe_get_chain(client, ticker: str, *, strike_count, priority: bool = False,
                          to_date=None, from_date=None):
    """safe_get_chain behind the bounded two-slot gate -> (resp, gate_wait_sec, fetch_sec).

    Schwab CSV authority checked: yes
    CSV row(s): chains.* via schwab_client.safe_get_chain - call shape
      unchanged (safe_get_chain(client, ticker, strike_count=...)); this is
      scheduling (bounded 2-slot gate + per-ticker single-flight coalescing),
      no field read/derivation/emission change.
    Derived-field disposition: none required.
    All consumers checked: yes - c_resp consumed identically downstream;
      coalesced callers receive the owner response for the SAME ticker only.
    SCHWAB_CSV_CHECKED
    """
    # institutional-length-ok: 85 lines, 13 of them the mandated SCHWAB_CSV_CHECKED
    # docstring. This is ONE protocol for a single chain fetch - coalesce, gate, fetch,
    # then bookkeep - and its stages share key/holder/is_owner/acquired/exc across a
    # try/finally. Extracting any stage means threading five mutable variables through a
    # boundary and splitting the lock/release and event-set bookkeeping away from the
    # code that establishes them, which makes the concurrency harder to verify rather
    # than easier. RC-19: a length ceiling must prompt a judgement, not a reflex split.
    global _chain_fetch_gate_timeout_count
    # Coalesce key MUST include strike_count. Observed 2026-07-20: terrain's
    # SPY strikeCount=200 got Schwab 502; UI/analytics coalesced onto that same
    # ticker key (wanting strikeCount=20) and inherited the failure as
    # "Chain fetch failed". Same-ticker different widths are different fetches.
    # RC-127: to_date joins the coalesce key — a full-book fetch and a 45-day rung are
    # DIFFERENT fetches, same as the strike-width lesson above. Cursor-audit F2: from_date
    # likewise — a single-expiry window (from=to=sel) and the open-near-end horizon fetch are
    # different requests and must never coalesce onto each other.
    key = ((ticker or "").strip().upper(), int(strike_count), str(to_date or ""), str(from_date or ""))
    wait_started = time.monotonic()
    with _chain_inflight_lock:
        holder = _chain_inflight.get(key)
        if holder is None:
            holder = {"event": threading.Event(), "result": None, "exc": None}
            _chain_inflight[key] = holder
            is_owner = True
        else:
            is_owner = False
    if not is_owner:
        _schwab_chain_fetch_gate.metrics["coalesced_hits"] += 1
        done = holder["event"].wait(CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC + 60.0)
        waited = round(time.monotonic() - wait_started, 3)
        if done:
            if holder["exc"] is not None:
                raise holder["exc"]  # source exceptions propagate, never swallowed
            resp, _own_wait, fetch_sec = holder["result"]
            return resp, waited, fetch_sec
        log.warning(
            "chain coalesce wait timed out ticker=%s strike_count=%s - issuing own fetch",
            key[0], key[1],
        )
        # fail-open to an owned fetch WITHOUT registry (the stuck owner still
        # holds the key; never double-register)
    acquired = _schwab_chain_fetch_gate.acquire(
        timeout=CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC, priority=priority
    )
    gate_wait_sec = round(time.monotonic() - wait_started, 3)
    if not acquired:
        _chain_fetch_gate_timeout_count += 1
        log.warning(
            "chain_gate_timeout ticker=%s waited=%.3fs count=%s - proceeding ungated (fail-open)",
            ticker,
            gate_wait_sec,
            _chain_fetch_gate_timeout_count,
        )
    fetch_started = time.monotonic()
    resp = None
    exc = None
    try:
        resp = safe_get_chain(client, ticker, strike_count=strike_count, to_date=to_date, from_date=from_date)
        return resp, gate_wait_sec, round(time.monotonic() - fetch_started, 3)
    except SchwabAuthError as e:
        exc = e
        _schwab_chain_fetch_gate.record_result(False, auth_error=True)
        raise
    except Exception as e:
        exc = e
        _schwab_chain_fetch_gate.record_result(False)
        raise
    finally:
        if exc is None:
            status = getattr(resp, "status_code", None)
            throttled = status == 429
            ok = status is None or int(status) < 500
            _schwab_chain_fetch_gate.record_result(ok and not throttled, throttled=throttled)
        if acquired:
            _schwab_chain_fetch_gate.release()
        if is_owner:
            with _chain_inflight_lock:
                _chain_inflight.pop(key, None)
            if exc is not None:
                holder["exc"] = exc
            else:
                holder["result"] = (resp, 0.0, round(time.monotonic() - fetch_started, 3))
            holder["event"].set()

# ── Server-side state cache (avoids re-fetching everything on each poll) ─────
_state_cache: dict = {}           # (ticker, expiry) -> {ts, ms_dict}
_zone_tracker: dict = {}          # ticker -> {zone, since_bars_1m, since_bars_5m, prev_zone, last_bar_ts_1m, last_bar_ts_5m}
_order_flow_engine = None  # singleton OrderFlowEngine, avoid per-tick instantiation
CACHE_TTL = 5                     # seconds — default REST cache & idle SSE loop when nobody is streaming
# Active browser tab opens SSE /api/stream?ticker=&expiry= → that (ticker, expiry) is "viewed".
# LIVE_OPERATOR_MODE_RESET_V1 Step 2 — single Tier C owner + honest cadence: the SSE
# background loop is the only steady-state recompute scheduler for viewed keys, at a
# cadence the full pipeline (2–8s chain+quote+ML+DB) can actually sustain. TTL equals
# the cadence so "stale" is a truth statement, not a 1s fantasy.
VIEWER_SSE_REFRESH_SEC: float = float(os.environ.get("ED_VIEWER_SSE_REFRESH_SEC", "5.0"))
VIEWER_STATE_CACHE_TTL_SEC: float = float(os.environ.get("ED_VIEWER_STATE_CACHE_TTL_SEC", "5.0"))
# A viewed bundle is STALE only after a full recompute cycle was missed:
# age >= ANALYTICS_STALE_GRACE_CYCLES × TTL. Drives analytics_stale and the
# card_freshness_v1 analytics_age_exceeded stale-reason code (one authority).
ANALYTICS_STALE_GRACE_CYCLES: float = 2.0
# IDLE_SENTINEL_FRESHNESS_V1 (operator-approved 2026-07-09) — standing producer for
# unviewed cache keys. Root cause NOT_COMPUTED: card production was viewer-coupled,
# so keys without an SSE subscriber aged unbounded. Each _sse_background_loop tick
# also recomputes at most IDLE_KEY_REFRESH_MAX_PER_TICK unowned keys whose age
# exceeds the stale budget (CACHE_TTL × ANALYTICS_STALE_GRACE_CYCLES), oldest first.
# Idle cadence contract: worst-case unviewed-key age ≈ n_idle_stale_keys × loop
# interval + one recompute duration (bounded — previously unbounded). Selection is
# cache-key/age driven; no ticker/session input exists.
IDLE_KEY_REFRESH_MAX_PER_TICK: int = 1
# T5 SSE repair — Schwab CSV-first slice declaration (transport-only; no wire/ingestion change):
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE
# All consumers checked: yes — SSE Tier C cache fanout / bounded recompute only; no Schwab wire,
# ingestion, auth/token, CSV parsing, market-data source priority, model/signal, or trading change.
# SCHWAB_CSV_CHECKED
# T5 — bounded SSE recompute wait; cache fanout keeps Tier C SSE alive when _fetch_state is slow.
SSE_RECOMPUTE_FETCH_TIMEOUT_SEC: float = float(
    os.environ.get("ED_SSE_RECOMPUTE_FETCH_TIMEOUT_SEC", "12.0")
)
# UI-MAXIMIZE — panel warm list + binding SLA budgets (mirrored on /api/build + static ED_UI_MAXIMIZE_SLA_MS).
UI_MAXIMIZE_PANEL_WARM_TICKERS: tuple[str, ...] = tuple(
    t.strip().upper()
    for t in os.environ.get("ED_UI_PANEL_WARM_TICKERS", "SPY,QQQ,IWM").split(",")
    if t.strip()
) or ("SPY", "QQQ", "IWM")
UI_MAXIMIZE_WARM_STAGGER_SEC: float = float(os.environ.get("ED_UI_MAXIMIZE_WARM_STAGGER_SEC", "2.0"))
UI_MAXIMIZE_SLA_MS: dict[str, int] = {
    "first_quote": int(os.environ.get("ED_UI_SLA_FIRST_QUOTE_MS", "500")),
    "fusion_cards_panel_warm": int(os.environ.get("ED_UI_SLA_FUSION_PANEL_MS", "2000")),
    "fusion_cards_guest_cold": int(os.environ.get("ED_UI_SLA_FUSION_GUEST_MS", "15000")),
}
# Layer A: push in-memory live quote plane over SSE (no Schwab/DB) — sub-second feel vs analytical loop.
LIVE_QUOTE_SSE_INTERVAL_SEC: float = float(os.environ.get("ED_LIVE_QUOTE_SSE_INTERVAL_SEC", "0.12"))

# ── DB snapshot insert throttle (TQM: bound raw row explosion from SSE + logger) ─
# At most one INSERT per ticker per UTC-minute bucket (matches normalized 1m bucketing).
# Bars persist + outcome backfill ride the same throttle (Step 3, live-path write
# pressure). Set ED_DB_SNAPSHOT_THROTTLE=0 to restore per-fetch writes.
#
# SCHWAB_CSV_CHECKED — Step 3 live-path stall/write-pressure changes:
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — no new market-field site; lock order,
#   write throttling, view-touch enrollment, and live-mode scheduling only.
# Derived-field disposition: none required.
# All consumers checked: yes — no Schwab field read, derivation, or emission changed.
_db_snapshot_minute_bucket: dict[str, int] = {}
_db_snapshot_gate_lock = threading.Lock()


def _snapshot_throttle_enabled() -> bool:
    v = os.environ.get("ED_DB_SNAPSHOT_THROTTLE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _snapshot_row_insert_allowed(ticker: str, ts_utc: float, db=None) -> bool:
    """Atomically RESERVE this ticker's UTC-minute snapshot slot (contract:
    max 1 insert/ticker/UTC minute).

    Repo-wide audit 2026-07-05: the previous check-only gate leaked duplicates
    two ways — (a) concurrent callers (viewer _fetch_state + base money-path
    capture) both passed before either committed, because the bucket only
    updated AFTER a successful insert; (b) every process restart began with an
    empty bucket and re-inserted a minute the previous process had written
    (4,783 duplicate (ticker,minute) groups on disk; SPY dups written same-day).
    Reserving AT CHECK TIME closes (a); the durable same-minute existence probe
    (idx_snap_ticker_tf_ts, ~0.06ms) closes (b). A failed insert must call
    _snapshot_row_insert_release so a later tick in the same minute can retry —
    the pre-fix retry-within-minute semantics are preserved.

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — persistence throttle lifecycle only; no
      market field read, derivation, emission, or actionability logic changed.
    Derived-field disposition: none required.
    All consumers checked: yes — both insert sites (fetch_state + base capture)
      updated in this change set; row contents unchanged.
    SCHWAB_CSV_CHECKED
    """
    if not _snapshot_throttle_enabled():
        return True
    t = ticker.upper().strip()
    b = int(ts_utc // 60)
    with _db_snapshot_gate_lock:
        if _db_snapshot_minute_bucket.get(t) == b:
            return False
        if db is not None:
            try:
                if db.snapshot_exists_in_minute(ticker, CANONICAL_TIMEFRAME, b):
                    _db_snapshot_minute_bucket[t] = b
                    return False
            except Exception as _probe_e:
                # Probe failure degrades to the in-process gate (pre-fix behavior),
                # never blocks the insert path.
                log.debug("snapshot minute-existence probe failed %s: %s", t, _probe_e)
        _db_snapshot_minute_bucket[t] = b
        return True


def _snapshot_row_insert_release(ticker: str, ts_utc: float) -> None:
    """Release a reservation after a FAILED insert (same-minute retry allowed)."""
    t = ticker.upper().strip()
    b = int(ts_utc // 60)
    with _db_snapshot_gate_lock:
        if _db_snapshot_minute_bucket.get(t) == b:
            _db_snapshot_minute_bucket.pop(t, None)


def _snapshot_row_insert_committed(ticker: str, ts_utc: float) -> None:
    t = ticker.upper().strip()
    b = int(ts_utc // 60)
    with _db_snapshot_gate_lock:
        _db_snapshot_minute_bucket[t] = b


# ── SSE client registry ───────────────────────────────────────────────────────
_sse_clients: list[asyncio.Queue] = []
_sse_subscribers: dict[tuple[str, str | None], int] = {}  # (ticker, expiry) -> subscriber count
_sse_lock = threading.Lock()
# Throttled INFO log for SSE background loop cadence (see _sse_background_loop).
_sse_cadence_diag_last_log_mono: float = 0.0

# ── L1 light SSE (/api/analytics/light/stream) — event-driven delivery; same payload as HTTP GET ──
_l1_light_sse_clients: list[tuple[asyncio.Queue, tuple[str, str | None]]] = []
_l1_light_sse_lock = threading.Lock()
_l1_sse_thread_queue: queue.Queue = queue.Queue(maxsize=500)
_l1_sse_throttle_lock = threading.Lock()
_l1_sse_last_emit_mono: dict[tuple[str, str | None], float] = {}
_L1_SSE_MIN_INTERVAL_SEC = 0.05
_l1_sse_diag: dict[str, int] = {
    "l1_light_sse_connections": 0,
    "l1_light_sse_events_queued": 0,
    "l1_light_sse_events_delivered": 0,
    # Legacy: kept for dashboards; prefer evicted_oldest counters (deterministic policy).
    "l1_light_sse_events_dropped_full": 0,
    "l1_light_sse_thread_queue_evicted_oldest": 0,
    "l1_light_sse_client_queue_evicted_oldest": 0,
    "l1_light_sse_events_throttled": 0,
    "l1_payload_identity_violation": 0,
    # Issue 31 — scaling / multi-connection diagnostics
    "l1_light_sse_connections_peak": 0,
    "l1_light_sse_duplicate_scope_same_client_warn_total": 0,
    "l1_light_sse_rejected_total": 0,
}
# Process-local monotonic instant of last SSE backpressure drop (not Schwab/market time).
_l1_sse_last_drop_mono: float = 0.0
# Per scope: last (l1_generation, _server_build_ts, fingerprint) emitted on SSE wire.
_l1_last_emit_identity: dict[tuple[str, str | None], tuple[int, float, str]] = {}

# Issue 28 — Tier B semantic contract (HTTP JSON body and SSE event `payload` must stay identical in assembly).
# Both use _l1_http_get_projection: authoritative L1 snapshot + server-side L0 live quote overlay on cache hits
# (see apply_l1_live_quote_overlay). Not "projection raw without overlay" — overlay is applied before send.
# Canonical Tier B material identity: server _l1_payload_fingerprint(payload) on that assembled dict.
L1_TIER_B_CHANNEL_PAYLOAD_MODE = "full_overlay"

# Issue 31 — hard caps for /api/analytics/light/stream (defined behavior beyond browser limits).
MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL = 64
MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE = 8
# (remote_key, ticker, expiry_key) -> connection count (same client + scope = potential duplicate tab).
_l1_light_sse_remote_scope: dict[tuple[str, str, str], int] = {}


def _l1_sse_remote_key(request: Request) -> str:
    """Coarse client key for duplicate-scope warnings (not authenticated identity)."""
    xf = (request.headers.get("x-forwarded-for") or "").strip()
    if xf:
        return xf.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def _l1_light_sse_count_by_scope() -> dict[str, int]:
    counts: dict[str, int] = {}
    with _l1_light_sse_lock:
        for _, (tick, exp) in _l1_light_sse_clients:
            sk = f"{tick}|{exp}"
            counts[sk] = counts.get(sk, 0) + 1
    return dict(sorted(counts.items()))


def _l1_light_sse_try_reserve(request: Request, key: tuple[str, str]) -> tuple[asyncio.Queue, tuple[str, str, str]]:
    """
    Atomically enforce L1 light SSE limits. Raises HTTPException(503) when over cap.
    Returns (queue, rs_key) for _l1_light_sse_release on disconnect.
    """
    remote = _l1_sse_remote_key(request)
    t, exp_key = key
    rs_key = (remote, t, exp_key)
    with _l1_light_sse_lock:
        n_total = len(_l1_light_sse_clients)
        n_scope = sum(1 for _, csk in _l1_light_sse_clients if csk == key)
        if n_total >= MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL:
            _l1_sse_diag["l1_light_sse_rejected_total"] = int(_l1_sse_diag.get("l1_light_sse_rejected_total", 0)) + 1
            log.warning(
                "L1 light SSE rejected: global cap %s (current=%s)",
                MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL,
                n_total,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    f"L1 SSE connection limit reached ({MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL} total). "
                    "Close other tabs or connections."
                ),
            )
        if n_scope >= MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE:
            _l1_sse_diag["l1_light_sse_rejected_total"] = int(_l1_sse_diag.get("l1_light_sse_rejected_total", 0)) + 1
            log.warning(
                "L1 light SSE rejected: per-scope cap %s (scope=%s current=%s)",
                MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE,
                key,
                n_scope,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    f"L1 SSE per-scope connection limit reached ({MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE}). "
                    "Close duplicate streams for this ticker/expiry."
                ),
            )
        dup = int(_l1_light_sse_remote_scope.get(rs_key, 0))
        if dup >= 1:
            _l1_sse_diag["l1_light_sse_duplicate_scope_same_client_warn_total"] = int(
                _l1_sse_diag.get("l1_light_sse_duplicate_scope_same_client_warn_total", 0)
            ) + 1
            # RC-230 severity calibration (quiet-gate finding, reasoning on record): a SAME-client
            # duplicate is the operator's own multi-tab/multi-monitor viewing — designed-normal,
            # not a malfunction — so it logs INFO with the full diag counter retained. The
            # per-scope and global CAPS above keep their WARNING+503 teeth for real floods;
            # approaching the cap re-escalates to WARNING here so leak growth stays loud.
            if dup + 1 >= MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE - 1:
                log.warning(
                    "L1 light SSE same-client duplicates approaching per-scope cap for %s from %s (existing=%s)",
                    key,
                    remote,
                    dup,
                )
            else:
                log.info(
                    "duplicate L1 light SSE connections for scope %s from client %s (existing=%s) — same-client multi-tab, designed-normal",
                    key,
                    remote,
                    dup,
                )
        _l1_light_sse_remote_scope[rs_key] = dup + 1
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        _l1_light_sse_clients.append((q, key))
        _l1_sse_diag["l1_light_sse_connections"] = int(_l1_sse_diag.get("l1_light_sse_connections", 0)) + 1
        cur = len(_l1_light_sse_clients)
        peak = max(int(_l1_sse_diag.get("l1_light_sse_connections_peak", 0)), cur)
        _l1_sse_diag["l1_light_sse_connections_peak"] = peak
    return q, rs_key


def _l1_light_sse_release(q: asyncio.Queue, key: tuple[str, str], rs_key: tuple[str, str, str]) -> None:
    with _l1_light_sse_lock:
        for i, pair in enumerate(list(_l1_light_sse_clients)):
            if pair[0] is q and pair[1] == key:
                _l1_light_sse_clients.pop(i)
                break
        _l1_sse_diag["l1_light_sse_connections"] = max(0, int(_l1_sse_diag.get("l1_light_sse_connections", 0)) - 1)
        left = int(_l1_light_sse_remote_scope.get(rs_key, 0)) - 1
        if left <= 0:
            _l1_light_sse_remote_scope.pop(rs_key, None)
        else:
            _l1_light_sse_remote_scope[rs_key] = left


def _l1_round_floats_for_json(obj: Any) -> Any:
    """Normalize floats so JSON canonical form is stable across platforms."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return str(obj)
        return round(obj, 9)
    if isinstance(obj, dict):
        return {k: _l1_round_floats_for_json(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_l1_round_floats_for_json(x) for x in obj]
    return obj


def _l1_material_dict_for_fingerprint(payload: dict) -> dict[str, Any]:
    """
    Material allowlist for identity hashing: only fields defined in
    planes.l1_fingerprint_material.build_l1_material_dict_for_fingerprint participate.
    New diagnostics, timestamps, or instrumentation on the payload cannot affect the
    fingerprint unless explicitly allowlisted there.
    """
    mat = build_l1_material_dict_for_fingerprint(payload)
    return _l1_round_floats_for_json(mat)


def _l1_payload_fingerprint(payload: dict) -> str:
    """SHA-256/hex32 over canonical JSON of material projection fields (see _l1_material_dict_for_fingerprint)."""
    mat = _l1_material_dict_for_fingerprint(payload)
    blob = json.dumps(mat, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _l1_record_payload_identity(sk: tuple[str, str | None], gen: int, payload: dict) -> tuple[float, str]:
    """Update per-scope identity; increment violation if same (gen, ts) yields a different fingerprint."""
    warn_l1_payload_key_drift(payload, logger=log)
    ts = float(payload.get("_server_build_ts") or payload.get("as_of_ts") or 0.0)  # silent-zero-ok: epoch-0 is the ANCIENT sentinel — a missing build stamp must read as maximally stale, never fresh
    fp = _l1_payload_fingerprint(payload)
    prev = _l1_last_emit_identity.get(sk)
    if prev is not None:
        pg, pt, pfp = prev
        if gen == pg and abs(ts - pt) < 1e-6 and fp != pfp:
            _l1_sse_diag["l1_payload_identity_violation"] = int(_l1_sse_diag.get("l1_payload_identity_violation", 0)) + 1
    _l1_last_emit_identity[sk] = (gen, ts, fp)
    return ts, fp


def _l1_put_l1_client_queue(q: asyncio.Queue, env: dict) -> None:
    """
    Per-client asyncio.Queue (maxsize=8): on QueueFull, drop oldest pending event for this
    connection, then enqueue the newest — preserves latest projection under saturation.
    """
    global _l1_sse_last_drop_mono
    while True:
        try:
            q.put_nowait(env)
            _l1_sse_diag["l1_light_sse_events_delivered"] = int(_l1_sse_diag.get("l1_light_sse_events_delivered", 0)) + 1
            return
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                _l1_sse_diag["l1_light_sse_client_queue_evicted_oldest"] = int(
                    _l1_sse_diag.get("l1_light_sse_client_queue_evicted_oldest", 0)
                ) + 1
                _l1_sse_last_drop_mono = time.monotonic()
            except asyncio.QueueEmpty:
                _l1_sse_diag["l1_light_sse_events_dropped_full"] = int(_l1_sse_diag.get("l1_light_sse_events_dropped_full", 0)) + 1
                return


def _l1_put_thread_queue_notify(sk: tuple[str, str | None], env: dict) -> None:
    """
    Cross-thread fan-in queue: on Full, evict oldest global item until the newest notify fits.

    Fairness policy (explicit, deliberate — not accidental):
    - Priority is "latest notify always gets queued" for backpressure recovery.
    - Under extreme cross-scope saturation, an older pending notify for scope A may be
      evicted to make room for scope B's newest notify. Per-scope correctness is preserved
      by monotonic l1_generation on the client; a quiet scope may see delayed SSE until its
      next build. No starvation of the newest event for the producer that is currently pushing.
    - Alternative per-scope thread queues would add complexity and memory; not justified here.
    """
    global _l1_sse_last_drop_mono
    while True:
        try:
            _l1_sse_thread_queue.put_nowait((sk, env))
            _l1_sse_diag["l1_light_sse_events_queued"] = int(_l1_sse_diag.get("l1_light_sse_events_queued", 0)) + 1
            return
        except queue.Full:
            try:
                _l1_sse_thread_queue.get_nowait()
                _l1_sse_diag["l1_light_sse_thread_queue_evicted_oldest"] = int(
                    _l1_sse_diag.get("l1_light_sse_thread_queue_evicted_oldest", 0)
                ) + 1
                _l1_sse_last_drop_mono = time.monotonic()
            except queue.Empty:
                _l1_sse_diag["l1_light_sse_events_dropped_full"] = int(_l1_sse_diag.get("l1_light_sse_events_dropped_full", 0)) + 1
                return


# /api/fast-quote and /api/live/state use a dedicated quote-hot pool so Tier C / L1
# route offloads cannot starve the price strip during ticker switches.
_quote_hot_executor: Optional[ThreadPoolExecutor] = None
_route_offload_executor: Optional[ThreadPoolExecutor] = None
# RC-166: L1 light HTTP/SSE must not share ed_route_offload with Tier C JSON copies
# and streaming resubscribe (up to 30s). Wall ≫ _pipeline_ms was mostly that queue.
_l1_light_executor: Optional[ThreadPoolExecutor] = None
L1_LIGHT_EXECUTOR_MAX_WORKERS = 4

# Legacy name retained for call sites that still import the route pool.
_fast_quote_executor: Optional[ThreadPoolExecutor] = None

# Single worker: outcome backfill scans snapshots + bars — must not run on the hot _fetch_state path.
_db_fill_outcomes_executor: Optional[ThreadPoolExecutor] = None

# OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 — dedicated pool for
# recompute-internal LEAF Schwab fetches only (chain, quote, candle seeds), so
# operator-facing card recomputes never queue behind HTTP serve bodies or each
# other's nested route-pool work (measured 8.3-12.6s route-pool queue waits at
# organic load with pure Schwab fetches under 3.2s). Sizing: the analytics pool
# caps concurrent recomputes at 4 and each recompute joins at most 2 leaf
# futures at a time (chain+quote resolve before the seeds run), so 8 workers
# give zero internal queueing by construction. Leaf-ness is AST-locked in
# tests: none of the leaf functions submit anywhere, so the 2026-07-04
# nested-submit deadlock class cannot form.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — executor-pool scheduling only; the Schwab
#   chain/quote/pricehistory reads themselves are byte-identical (same leaf
#   functions, same arguments, same joins — only the pool they run on changes).
# Derived-field disposition: none required (no derived field touched).
# All consumers checked: yes — c_resp/q_resp/seeded candles consumed
#   identically downstream; HTTP serve bodies keep the route pool unchanged.
# SCHWAB_CSV_CHECKED
RECOMPUTE_LEAF_EXECUTOR_MAX_WORKERS = 8
_recompute_leaf_executor: Optional[ThreadPoolExecutor] = None


def _get_quote_hot_executor() -> ThreadPoolExecutor:
    """Tier A + fast-quote only — never queue behind Tier C JSON or L1 rebuilds."""
    global _quote_hot_executor
    if _quote_hot_executor is None:
        _quote_hot_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="ed_quote_hot",
        )
    return _quote_hot_executor


def _get_route_offload_executor() -> ThreadPoolExecutor:
    global _route_offload_executor
    if _route_offload_executor is None:
        _route_offload_executor = ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="ed_route_offload",
        )
    return _route_offload_executor


def _get_fast_quote_executor() -> ThreadPoolExecutor:
    """Route-touch pool (Tier C JSON, streaming POST touch). Not L1 light (RC-166)."""
    return _get_route_offload_executor()


def _get_l1_light_executor() -> ThreadPoolExecutor:
    """Dedicated pool for /api/analytics/light (+ SSE touch). Isolated from Tier C/stream."""
    global _l1_light_executor
    if _l1_light_executor is None:
        _l1_light_executor = ThreadPoolExecutor(
            max_workers=L1_LIGHT_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="ed_l1_light",
        )
    return _l1_light_executor


def _get_recompute_leaf_executor() -> ThreadPoolExecutor:
    """Recompute-internal leaf fetches ONLY (chain, quote, candle seeds).

    Universal by construction: used generically by every non-log_only
    _fetch_state recompute regardless of ticker/roster/session/horizon.
    log_only pipelines stay inline (Step 1) and never touch this pool."""
    global _recompute_leaf_executor
    if _recompute_leaf_executor is None:
        _recompute_leaf_executor = ThreadPoolExecutor(
            max_workers=RECOMPUTE_LEAF_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="ed_recompute_leaf",
        )
    return _recompute_leaf_executor


def _get_priority_leaf_executor() -> ThreadPoolExecutor:
    """UI_05 residual (2026-07-10 PM): leaf fetches for OPERATOR-PRIORITY
    recomputes only. Measured cause: the shared 8-worker leaf pool is FIFO
    across background idle-refresh leaf bursts, so a cold guest's chain leg
    waited 13.7-21s in-queue while the pure Schwab fetch was 0.5-0.8s. This
    bounded 2-worker lane gives priority recomputes their own leaf admission;
    Schwab chain concurrency is still single-slot via the priority gate.

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — executor-pool scheduling and startup
      model prewarm only; the Schwab chain/quote/pricehistory reads themselves
      are byte-identical (same helpers, same call shapes, same single-slot
      chain gate).
    Derived-field disposition: none required (no derived field touched).
    All consumers checked: yes — c_resp/q_resp/seed results consumed
      identically downstream; prewarm loads via the same strict MODEL-04
      gated path.
    SCHWAB_CSV_CHECKED"""
    global _priority_leaf_executor
    if _priority_leaf_executor is None:
        _priority_leaf_executor = ThreadPoolExecutor(
            # UI_05 final tail (2026-07-10 EVE trials @ 1f83a25): with 2
            # workers the lane also carries the three panel anchors' SSE
            # cycles, so a cold switch queued 8.3-9.3s at gate_wait=0 and
            # pure Schwab 0.4-0.6s. Four workers = 3 anchors + 1 operator
            # switch, the measured concurrent demand. Chain concurrency is
            # still bounded by the 2-slot gate.
            # SCHWAB_CSV_CHECKED — Schwab CSV authority checked: yes.
            # CSV row(s): NO_SCHWAB_EQUIVALENT (thread-pool sizing only; no
            # market field read, derived, or displayed by this change).
            # Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (n/a —
            # no derivation touched). All consumers checked: yes — chain,
            # quote, and seed legs submit here unchanged; Schwab reads remain
            # in safe_get_chain/safe_get_quote behind the 2-slot gate.
            max_workers=4,
            thread_name_prefix="ed_priority_leaf",
        )
    return _priority_leaf_executor


def _get_mkt_ctx_refresh_executor() -> ThreadPoolExecutor:
    """UI_05 tail closure (2026-07-10 EVE): single-worker lane for the
    market-context sweep so exactly one refresh runs at a time and NO
    recompute thread ever pays the 17-call sweep inline once a context
    exists. Sized 1 so a second sweep can never start concurrently.

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — executor scheduling only; the sweep
      itself (fetch_market_context) is byte-identical.
    Derived-field disposition: none required (no derived field touched).
    All consumers checked: yes — _get_mkt_ctx callers receive the same
      MarketContext object semantics (fresh, or previous-within-grace while
      one refresh is in flight).
    SCHWAB_CSV_CHECKED"""
    global _mkt_ctx_refresh_executor
    if _mkt_ctx_refresh_executor is None:
        _mkt_ctx_refresh_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ed_mkt_ctx_refresh",
        )
    return _mkt_ctx_refresh_executor


def _get_db_fill_outcomes_executor() -> ThreadPoolExecutor:
    global _db_fill_outcomes_executor
    if _db_fill_outcomes_executor is None:
        _db_fill_outcomes_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ed_fill_outcomes",
        )
    return _db_fill_outcomes_executor

# Tier C — background _fetch_state only; HTTP handlers never await heavy work.
_analytics_executor: Optional[ThreadPoolExecutor] = None
_analytics_bg_shutdown: bool = False
_analytics_inflight: set[tuple] = set()
_analytics_bg_fail_counts: dict[tuple, int] = {}
_analytics_bg_last_error: dict[tuple, str] = {}
_analytics_bg_lock = threading.Lock()
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None
_sse_fetch_timeout_executor: Optional[ThreadPoolExecutor] = None
_operator_priority_executor: Optional[ThreadPoolExecutor] = None
_priority_leaf_executor: Optional[ThreadPoolExecutor] = None
_mkt_ctx_refresh_executor: Optional[ThreadPoolExecutor] = None
ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES = int(
    os.environ.get("ED_ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES", "3")
)


def _get_analytics_executor() -> ThreadPoolExecutor:
    global _analytics_executor
    if _analytics_executor is None:
        _analytics_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="ed_analytics_bg",
        )
    return _analytics_executor


def _get_sse_fetch_timeout_executor() -> ThreadPoolExecutor:
    """Isolated pool so SSE bounded waits do not nest-block the analytics bg pool."""
    global _sse_fetch_timeout_executor
    if _sse_fetch_timeout_executor is None:
        _sse_fetch_timeout_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="ed_sse_fetch_timeout",
        )
    return _sse_fetch_timeout_executor


def _startup_analytics_executor() -> None:
    global _analytics_bg_shutdown
    _analytics_bg_shutdown = False
    _get_analytics_executor()


def _shutdown_analytics_executor(*, wait: bool = True) -> None:
    global _analytics_executor, _analytics_bg_shutdown
    _analytics_bg_shutdown = True
    with _analytics_bg_lock:
        _analytics_inflight.clear()
    ex = _analytics_executor
    _analytics_executor = None
    if ex is not None:
        try:
            ex.shutdown(wait=wait, cancel_futures=True)
        except Exception as exc:
            log.debug("analytics executor shutdown: %s", exc)


def _analytics_executor_shutting_down() -> bool:
    return _analytics_bg_shutdown


# UI_05_OPERATOR_PRIORITY_ADMISSION_V1: background update sources opt IN to
# the background class; anything else (viewer SSE, REST poll, tick refresh,
# ticker switch, unknown) is operator-facing by default — universal by
# construction, no ticker/session input.
_BACKGROUND_UPDATE_SOURCES: frozenset[str] = frozenset(
    {"idle_key_refresh", "startup_warm", "session_open_anchor_warm"}
)


def _is_operator_priority_update_source(update_source) -> bool:
    return str(update_source or "") not in _BACKGROUND_UPDATE_SOURCES


def _get_operator_priority_executor() -> ThreadPoolExecutor:
    """Bounded 2-worker pool for operator-facing recomputes ONLY.

    UI_05 root cause (measured 2026-07-10 open burst): the 4-worker analytics
    pool is FIFO-shared with logger/idle background cycles (~50s each at the
    bell), so a cold guest waited 44.5s just for admission. This pool gives
    operator-facing requests their own bounded admission lane; background
    keeps the analytics pool. Chain fetches remain single-slot gated, so
    Schwab concurrency and call volume are unchanged."""
    global _operator_priority_executor
    if _operator_priority_executor is None:
        _operator_priority_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="ed_operator_priority",
        )
    return _operator_priority_executor


def _submit_analytics_task(fn, *args, priority: bool = False, **kwargs):
    if _analytics_bg_shutdown:
        raise RuntimeError("analytics executor shutting down")
    pool = _get_operator_priority_executor() if priority else _get_analytics_executor()
    return pool.submit(fn, *args, **kwargs)


def _tier_c_inflight_key(ticker: str, expiry: Optional[str]) -> tuple:
    """Dedupe key for REST/SSE/tick refresh jobs (expiry None → '__auto__')."""
    return (ticker.upper().strip(), expiry if expiry is not None else "__auto__")


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1 ───────────────────────────────
# Root cause (ROUTE_OFFLOAD_EXECUTOR_SATURATION_TRACE, 2026-07-08): background
# log_only pipelines and operator-facing card recomputes submit their nested
# leaf Schwab fetches (chain, quote, candle seeds) into the SAME 8-worker FIFO
# route-offload pool, so logger work queues ahead of card recomputes (measured
# 8-17s route-pool queue wait inside heavy cycles, pure Schwab fetch 0.6-3.2s).
# Step 1: log_only pipelines run those leaf fetches INLINE on the caller
# thread — logger latency is acceptable, operator-facing latency is not.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — executor-pool scheduling only; the Schwab
#   chain/quote/pricehistory reads themselves are byte-identical (same
#   functions, same arguments, joined synchronously on both paths).
# Derived-field disposition: none required (no derived field touched).
# All consumers checked: yes — c_resp/q_resp/seeded candles consumed
#   identically downstream on both paths.
# SCHWAB_CSV_CHECKED
def _log_only_inline_leaf_fetches(log_only: bool) -> bool:
    """Universal-by-construction discriminator: background log_only pipelines
    run leaf Schwab fetches inline instead of submitting nested futures into
    the shared route-offload pool. The signature deliberately carries ONLY
    log_only — no ticker, roster, session, horizon, or expiry parameter exists
    for a special case to branch on. Shutdown keeps its existing inline
    behavior via the call-site `or`."""
    return bool(log_only)


def _invalidate_analytics_cache_after_bg_failures(
    inflight_key: tuple,
    ticker: str,
    *,
    reason: str,
    failure_count: Optional[int] = None,
    detail: str = "",
) -> None:
    """Mark cached Tier C payload stale after repeated background recompute failures.

    Institutional rule: never drop the last good analytical bundle — serve stale with
    an explicit operator-visible error instead of an empty pending shell.
    """
    t = ticker.upper().strip()
    exp = inflight_key[1] if len(inflight_key) > 1 else "__auto__"
    n_fail = (
        failure_count
        if failure_count is not None
        else _analytics_bg_fail_counts.get(inflight_key, 0)
    )
    err_msg = (detail or _analytics_bg_last_error.get(inflight_key) or reason or "unknown").strip()
    marked: list[tuple] = []
    for key in list(_state_cache.keys()):
        if not isinstance(key, tuple) or len(key) < 2 or key[0] != t:
            continue
        if exp != "__auto__" and key[1] != exp:
            continue
        ent = _state_cache.get(key)
        if not ent or not isinstance(ent.get("ms_dict"), dict):
            continue
        md = dict(ent["ms_dict"])
        md["state_error"] = "analytics_refresh_failed"
        md["state_error_detail"] = (
            f"Tier C refresh failed after {n_fail} attempt(s): {err_msg[:240]}"
        )
        md["analytics_last_error"] = err_msg[:500]
        md["analytics_stale"] = True
        md["analytics_refresh_in_progress"] = False
        ent["ms_dict"] = md
        marked.append(key)
    if marked:
        _analytics_cache_observability["bg_failure_stale_marks"] += len(marked)
        log.warning(
            "analytics cache marked stale after bg failures ticker=%s exp=%s n=%s reason=%s keys=%s",
            t,
            exp,
            n_fail,
            reason,
            marked,
        )


def _reset_analytics_bg_fail_count(inflight_key: tuple) -> None:
    _analytics_bg_fail_counts.pop(inflight_key, None)
    _analytics_bg_last_error.pop(inflight_key, None)


def _record_analytics_bg_failure(
    inflight_key: tuple,
    ticker: str,
    *,
    reason: str,
    detail: str = "",
    token_invalid: bool = False,
) -> None:
    if detail:
        _analytics_bg_last_error[inflight_key] = detail[:500]
    n = _analytics_bg_fail_counts.get(inflight_key, 0) + 1
    _analytics_bg_fail_counts[inflight_key] = n
    exp = inflight_key[1] if len(inflight_key) > 1 and inflight_key[1] != "__auto__" else None
    if token_invalid or n == 1:
        _write_analytics_bg_error_shell(
            ticker,
            exp,
            detail or reason,
            token_invalid=token_invalid,
        )
    if n >= ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES:
        _invalidate_analytics_cache_after_bg_failures(
            inflight_key,
            ticker,
            reason=reason,
            failure_count=n,
            detail=detail,
        )
        _analytics_bg_fail_counts.pop(inflight_key, None)


def _charm_book_scope(contracts: object) -> str:
    """Which BOOK a charm figure was summed over, counted from the contracts themselves.

    RC-288: this was the literal `"full_chain_banked"`, and `static/exposure.html` carries
    the same literal as its fallback — a label written identically at both ends can never
    disagree with itself, so it could not detect the one thing it exists for.

    It is worth detecting. `compute_net_charm` runs on ONE selected expiry while
    `compute_charm_by_strike` runs on the whole chain, so "charm" names two different
    quantities depending on which producer answered, and the Exposure tab renders them
    under one heading. Counting distinct expirations reports the book actually used and
    changes on its own if the producer changes.

    Absence is reported as absence: an empty or unreadable chain yields "unknown", never a
    confident "full_chain_banked" for a book nobody looked at (RC-274).
    """
    if not isinstance(contracts, list) or not contracts:
        return "unknown"
    expiries = {
        str(c.get("expirationDate") or c.get("expiry") or "").strip()
        for c in contracts if isinstance(c, dict)
    }
    expiries.discard("")
    if not expiries:
        return "unknown"
    if len(expiries) == 1:
        return f"single_expiry_banked:{sorted(expiries)[0][:10]}"
    return "full_chain_banked"


def _analytics_generated_ts(entry: dict) -> float | None:
    """When this entry was computed, or None when it carries no usable timestamp.

    RC-282: this returned 0.0 for an undated entry and each caller invented its own meaning
    for the sentinel. Cursor's audit executed both and they DISAGREE — the freshness
    contract computed `age = 0.0 if gen_ts <= 0` and published `analytics_stale: False`, a
    bundle nobody can date served as brand new, while the stale-serve marker computed
    `now - 0.0`, got ~1.8e9 seconds, and published stale. One sentinel, two opposite
    verdicts about the same cache entry, and the fresh one is on the operator's card.

    None forces each caller to SAY what absence means instead of inheriting a number that
    points whichever way its arithmetic happens to fall.
    """
    from numeric_contract import float_positive_or_none

    return (float_positive_or_none(entry.get("generated_at"))
            or float_positive_or_none(entry.get("ts")))


# ── ANALYTICS_LOG_ONLY_CACHE_CLOBBER_GUARD_V1 ────────────────────────────────
# Root cause (ANALYTICS_BUNDLE_AGE_CADENCE_TRACE_V1, 2026-07-07): the background
# logger calls _fetch_state(ticker, expiry=None, log_only=True) each rotation and
# the log_only branch overwrote _state_cache[(ticker, selected_exp)] with
# {"ms_dict": {}} — destroying the full Tier C bundle's ms_dict / generated_at /
# analytics_version at the SAME key the UI reads. Freshness then took the
# no-bundle branch (stale=True, version 0) and the next full publish restarted
# analytics_version at 1 (observed live: version resets to 1, vanished QQQ/IWM
# entries, pending_shell_builds churn). The guard below preserves any entry that
# carries a publishable bundle (full, progressive-partial, or error shell — all
# have non-empty ms_dict + generated_at) and only refreshes the scalar
# observation fields the recompute diff path consumes (pcr_val / spot_f / vix).
# Entries without a bundle (legacy log-only minimal entries: ms_dict {}) keep
# the pre-existing minimal-write behavior, which never masquerades as a full
# bundle (no generated_at / no analytics_version → freshness no-bundle branch).
# Ticker-agnostic: keyed purely on cache-entry shape.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — cache-slot lifecycle guard only; no market
#   field read, derivation, or emission changed (pcr_val/spot_f/vix pass through
#   unchanged from the existing pipeline values).
# Derived-field disposition: none required (no derived field touched).
# All consumers checked: yes — _state_cache readers (_fetch_state prev_* diff
#   reads, freshness contract, progressive publish, /api/analytics/state serve
#   path) see either the preserved bundle or the unchanged legacy minimal entry.
# SCHWAB_CSV_CHECKED
def _analytics_cache_entry_is_full_bundle(entry: Optional[dict]) -> bool:
    """True when a Tier C cache entry carries a publishable bundle (non-empty
    ms_dict + generated_at) whose freshness state must never be degraded by a
    log-only write. Progressive partials and error shells qualify on purpose —
    replacing either with an empty-ms_dict minimal entry would lose state."""
    if not entry or not isinstance(entry, dict):
        return False
    return bool(entry.get("ms_dict")) and bool(entry.get("generated_at"))


def _log_only_cache_touch(
    cache_key: tuple,
    ticker: str,
    selected_exp: Optional[str],
    pcr_val,
    spot_f,
    vix,
) -> str:
    """Log-only cache write with the full-bundle clobber guard; returns action.

    preserved_full_bundle — entry has a publishable bundle: ms_dict /
    generated_at / analytics_version / ts untouched (version monotonicity and
    freshness state survive logger rotations); only non-None scalar
    observations (pcr_val, spot_f, vix) are refreshed in place.
    legacy_minimal_write — no bundle present: pre-guard minimal entry written
    unchanged (empty ms_dict; renders as no-bundle, never as a stale bundle).
    """
    existing = _state_cache.get(cache_key)
    if _analytics_cache_entry_is_full_bundle(existing):
        if pcr_val is not None:
            existing["pcr_val"] = pcr_val
        if spot_f is not None:
            existing["spot_f"] = spot_f
        if vix is not None:
            existing["vix"] = vix
        action = "preserved_full_bundle"
    else:
        _state_cache[cache_key] = {
            "ts": time.time(), "ms_dict": {}, "pcr_val": pcr_val, "spot_f": spot_f,
            "vix": vix,
            "price_levels": (existing or {}).get("price_levels"),
            "pl_date":      (existing or {}).get("pl_date", ""),
            "pl_generation": (existing or {}).get("pl_generation"),
            "pl_mono":      (existing or {}).get("pl_mono"),
        }
        action = "legacy_minimal_write"
    _evict_old_expiry_entries(ticker, selected_exp)
    return action


def _attach_analytics_freshness_contract(
    md: dict,
    *,
    data_cache_key: tuple,
    entry: Optional[dict],
    now: float,
    sse_live: bool,
    inflight_key: tuple,
) -> None:
    """
    Tier C freshness — every analytics response includes:
    analytics_version, analytics_generated_at, analytics_age_sec,
    analytics_stale, analytics_refresh_in_progress
    """
    ttl = _sse_viewer_cache_ttl(data_cache_key[0], data_cache_key[1])
    with _analytics_bg_lock:
        in_prog = inflight_key in _analytics_inflight
    if entry and entry.get("ms_dict"):
        gen_ts = _analytics_generated_ts(entry)
        ver = int(entry.get("analytics_version", 0))
        if gen_ts is None:
            # RC-282: a bundle that exists but cannot be DATED is not a fresh bundle. The
            # old `else 0.0` published age zero and analytics_stale False. This is the same
            # verdict the missing-bundle branch below already reaches, and for the same
            # reason: an age nobody can compute is not an age of nothing.
            md["analytics_version"] = ver
            md["analytics_generated_at"] = None
            md["analytics_age_sec"] = None
            md["analytics_stale_after_sec"] = round(
                float(ttl) * ANALYTICS_STALE_GRACE_CYCLES, 3)
            md["analytics_stale"] = True
            md["analytics_refresh_due"] = True
            md["analytics_refresh_in_progress"] = bool(in_prog)
            return
        age = max(0.0, now - gen_ts)
        # Operator-facing stale = a recompute cycle was MISSED (age past the grace
        # window) or explicit error — not merely "older than one cadence beat".
        stale_after = float(ttl) * ANALYTICS_STALE_GRACE_CYCLES
        refresh_due = bool(sse_live or (age >= ttl))
        stale = bool(age >= stale_after) or bool(md.get("state_error"))
        # RC-282: gen_ts is a real positive timestamp by here — the undatable case returned
        # above rather than falling through with a zero standing in for one.
        iso = datetime.fromtimestamp(gen_ts, tz=timezone.utc).isoformat()
        md["analytics_version"] = ver
        md["analytics_generated_at"] = iso
        md["analytics_age_sec"] = round(age, 3)
        md["analytics_stale_after_sec"] = round(stale_after, 3)
        md["analytics_stale"] = stale
        md["analytics_refresh_due"] = refresh_due
        md["analytics_refresh_in_progress"] = bool(in_prog)
    else:
        md["analytics_version"] = 0
        md["analytics_generated_at"] = None
        md["analytics_age_sec"] = None
        md["analytics_stale"] = True
        md["analytics_refresh_in_progress"] = bool(in_prog)
        last_err = _analytics_bg_last_error.get(inflight_key)
        if last_err:
            md["analytics_last_error"] = last_err


# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — card_freshness_v1 is descriptive Tier C metadata only; reads existing plane quote via _lmp.get_quote(ticker) and existing md analytics/freshness fields; no new Schwab wire fetch or leaf derivation
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE — quote_age_sec/bundle_age_sec/stale_reason_codes computed from existing exchange_quote_ts, _server_build_ts, quote_source_detail.carried_forward, quote_source_detail.schwab_auth_degraded
# All consumers checked: yes — Tier C /api/analytics/state nested block + S2B-1 operator_* mirrors only; no trade gates; UI lane S3
# card_freshness_v1 — S2A descriptive thresholds (nested API metadata only; not trade gates).
_CARD_FRESHNESS_V1_QUOTE_STALE_SEC = 30.0
_CARD_FRESHNESS_V1_BUNDLE_TRUST_SEC = 45.0
_CARD_FRESHNESS_V1_TRUST_HORIZONS: tuple[str, ...] = ("1c", "5c", "15c", "60c")
# S2A-approved stale_reason_codes only — horizon-specific mhap_* reserved for LANE S4.
_CARD_FRESHNESS_V1_S2A_STALE_REASON_CODES: frozenset[str] = frozenset(
    {
        "analytics_stale",
        "analytics_age_exceeded",
        "quote_age_exceeded",
        "bundle_age_exceeded",
        "quote_newer_than_signal",
        "mhap_older_than_quote",
        "quote_carried_forward",
        "auth_fallback",
        "auth_degraded",
        "tier_c_cache_stale_serve",
        "cache_refresh_in_progress",
        "pending_shell",
        "partial_tier_c",
        "pending_full_analytics",
        "state_error",
        "revalidate_quarantine",
        "fusion_unavailable",
        "stack_integrity_degraded",
        "signals_engine_failed",
        "stack_invalid",
        "ticker_mismatch",
        "token_invalid",
        "missing_quote_ts",
        "missing_bundle_ts",
    }
)


def _card_freshness_trust_reason(
    md: dict,
    *,
    active_ticker: str,
) -> Optional[str]:
    """Mirror analyticsCardTrustGate / tools.run_universal_card_fidelity_runtime (read-only)."""
    if not isinstance(md, dict):
        return "no_payload"
    incoming = str(md.get("ticker") or "").strip().upper()
    active = str(active_ticker or "").strip().upper()
    if incoming and active and incoming != active:
        return "ticker_mismatch"
    if md.get("analytics_stale") is True:
        return "analytics_stale"
    if md.get("analytics_pending_shell") is True:
        return "pending_shell"
    if md.get("analytics_partial_tier_c") is True:
        return "partial_tier_c"
    src = str(md.get("_update_source") or "")
    if md.get("analytics_refresh_in_progress") is True and src == "client_ticker_cache":
        return "cache_refresh_in_progress"
    mhap = md.get("mhap_rows")
    if not isinstance(mhap, list) or len(mhap) == 0:
        return "mhap_missing"
    if len(mhap) < len(_CARD_FRESHNESS_V1_TRUST_HORIZONS):
        return "mhap_incomplete"
    for slug in _CARD_FRESHNESS_V1_TRUST_HORIZONS:
        if not any(
            isinstance(r, dict) and str(r.get("horizon") or "").lower() == slug for r in mhap
        ):
            return f"mhap_horizon_missing_{slug}"
    if md.get("fusion_available") is False:
        return "fusion_unavailable"
    si = md.get("stack_integrity_v1")
    if isinstance(si, dict) and si.get("degraded") is True:
        return "stack_integrity_degraded"
    rt = md.get("stack_runtime") if isinstance(md.get("stack_runtime"), dict) else {}
    if rt.get("signals_engine_failed") is True:
        return "signals_engine_failed"
    if str(rt.get("stack_mode") or "").upper() == "INVALID":
        return "stack_invalid"
    if md.get("state_error"):
        return "state_error"
    if md.get("error") == "token_invalid":
        return "token_invalid"
    return None


def _card_freshness_trust_state(
    *,
    trust_reason: Optional[str],
    stale_reason_codes: list[str],
    analytics_refresh_in_progress: bool,
) -> str:
    if trust_reason in ("state_error", "token_invalid", "no_payload"):
        return "UNAVAILABLE"
    if analytics_refresh_in_progress and trust_reason not in (
        "analytics_stale",
        "state_error",
        "token_invalid",
    ):
        return "REFRESHING"
    if trust_reason in (
        "fusion_unavailable",
        "stack_integrity_degraded",
        "signals_engine_failed",
        "stack_invalid",
        "partial_tier_c",
    ):
        return "DEGRADED"
    if trust_reason or stale_reason_codes:
        return "STALE"
    return "TRUSTED"


def _attach_card_freshness_v1_block(
    md: dict,
    *,
    ticker: str,
    now: float,
    analytics_ttl_sec: float,
    tier_c_cache_stale_serve: bool,
    plane_quote: Optional[dict],
) -> None:
    """Attach nested card_freshness_v1 — descriptive metadata only; no trade-field mutation."""
    active = str(ticker or md.get("ticker") or "").upper().strip()
    trust_reason = _card_freshness_trust_reason(md, active_ticker=active)

    qsd_plane = (plane_quote or {}).get("quote_source_detail") if plane_quote else {}
    if not isinstance(qsd_plane, dict):
        qsd_plane = {}
    carried_forward = bool(qsd_plane.get("carried_forward"))
    schwab_auth_degraded = bool(qsd_plane.get("schwab_auth_degraded"))

    quote_ts_raw = None
    if plane_quote and plane_quote.get("exchange_quote_ts") is not None:
        quote_ts_raw = plane_quote.get("exchange_quote_ts")
    elif md.get("exchange_quote_ts") is not None:
        quote_ts_raw = md.get("exchange_quote_ts")

    bundle_ts_raw = md.get("_server_build_ts")
    mhap_bundle_ts_raw = bundle_ts_raw

    quote_age_sec: Optional[float] = None
    if quote_ts_raw is not None:
        try:
            quote_age_sec = round(max(0.0, now - float(quote_ts_raw)), 3)
        except (TypeError, ValueError):
            quote_age_sec = None

    bundle_age_sec: Optional[float] = None
    if bundle_ts_raw is not None:
        try:
            bundle_age_sec = round(max(0.0, now - float(bundle_ts_raw)), 3)
        except (TypeError, ValueError):
            bundle_age_sec = None

    analytics_age_sec = md.get("analytics_age_sec")
    try:
        analytics_age_f = float(analytics_age_sec) if analytics_age_sec is not None else None
    except (TypeError, ValueError):
        analytics_age_f = None

    stale_reason_codes: list[str] = []

    def _add(code: str) -> None:
        if code and code not in stale_reason_codes:
            stale_reason_codes.append(code)

    if md.get("analytics_stale") is True:
        _add("analytics_stale")
    _analytics_stale_after = float(analytics_ttl_sec) * ANALYTICS_STALE_GRACE_CYCLES
    if analytics_age_f is not None and analytics_age_f >= _analytics_stale_after:
        _add("analytics_age_exceeded")
    if quote_age_sec is not None and quote_age_sec >= _CARD_FRESHNESS_V1_QUOTE_STALE_SEC:
        _add("quote_age_exceeded")
    if bundle_age_sec is not None and bundle_age_sec >= _CARD_FRESHNESS_V1_BUNDLE_TRUST_SEC:
        _add("bundle_age_exceeded")

    if quote_ts_raw is not None and bundle_ts_raw is not None:
        try:
            if float(quote_ts_raw) > float(bundle_ts_raw):
                _add("quote_newer_than_signal")
                _add("mhap_older_than_quote")
        except (TypeError, ValueError):
            pass

    if carried_forward:
        _add("quote_carried_forward")
        _add("auth_fallback")
    if schwab_auth_degraded:
        _add("auth_degraded")
    if tier_c_cache_stale_serve:
        _add("tier_c_cache_stale_serve")

    src = str(md.get("_update_source") or "")
    if md.get("analytics_refresh_in_progress") is True and src == "client_ticker_cache":
        _add("cache_refresh_in_progress")

    if md.get("analytics_pending_shell") is True:
        _add("pending_shell")
        _add("pending_full_analytics")
    if md.get("analytics_partial_tier_c") is True:
        _add("partial_tier_c")
    if md.get("state_error"):
        _add("state_error")
    if md.get("tier_c_cache_gate_ok") is False:
        _add("revalidate_quarantine")

    if trust_reason and trust_reason in _CARD_FRESHNESS_V1_S2A_STALE_REASON_CODES:
        _add(trust_reason)

    if quote_ts_raw is None:
        _add("missing_quote_ts")
    if bundle_ts_raw is None:
        _add("missing_bundle_ts")

    card_trust_state = _card_freshness_trust_state(
        trust_reason=trust_reason,
        stale_reason_codes=stale_reason_codes,
        analytics_refresh_in_progress=bool(md.get("analytics_refresh_in_progress")),
    )
    card_actionable = (
        trust_reason is None
        and not carried_forward
        and not stale_reason_codes
        and md.get("tier_c_cache_gate_ok") is not False
    )

    if carried_forward:
        fallback_status = "auth_carried_forward"
        carry_forward_status = "carried_forward"
    elif schwab_auth_degraded:
        fallback_status = "auth_degraded"
        carry_forward_status = "fresh"
    else:
        fallback_status = "none"
        carry_forward_status = "fresh"

    if card_trust_state == "TRUSTED":
        source_freshness = "trusted"
    elif card_trust_state == "REFRESHING":
        source_freshness = "refreshing"
    elif card_trust_state == "DEGRADED":
        source_freshness = "degraded"
    elif card_trust_state == "UNAVAILABLE":
        source_freshness = "unavailable"
    else:
        source_freshness = "stale"

    md["card_freshness_v1"] = {
        "card_trust_state": card_trust_state,
        "card_actionable": bool(card_actionable),
        "analytics_age_sec": analytics_age_sec,
        "quote_age_sec": quote_age_sec,
        "bundle_age_sec": bundle_age_sec,
        "analytics_ttl_sec": round(float(analytics_ttl_sec), 3),
        "analytics_stale_after_sec": round(_analytics_stale_after, 3),
        "quote_stale_sec": _CARD_FRESHNESS_V1_QUOTE_STALE_SEC,
        "bundle_trust_sec": _CARD_FRESHNESS_V1_BUNDLE_TRUST_SEC,
        "fallback_status": fallback_status,
        "carry_forward_status": carry_forward_status,
        "source_freshness": source_freshness,
        "stale_reason_codes": stale_reason_codes,
        "quote_ts": quote_ts_raw,
        "bundle_ts": bundle_ts_raw,
        "mhap_bundle_ts": mhap_bundle_ts_raw,
        "tier_c_cache_revalidated": md.get("tier_c_cache_revalidated"),
        "tier_c_cache_gate_ok": md.get("tier_c_cache_gate_ok"),
        "analytics_stale": md.get("analytics_stale"),
        "analytics_generated_at": md.get("analytics_generated_at"),
        "analytics_refresh_in_progress": md.get("analytics_refresh_in_progress"),
        "quote_source_detail.carried_forward": carried_forward,
        "quote_source_detail.schwab_auth_degraded": schwab_auth_degraded,
    }

    # S2B-1 — top-level operator mirrors for API consumers (nested card_freshness_v1 authoritative).
    if card_actionable:
        operator_actionability_reason: Optional[str] = None
    elif stale_reason_codes:
        operator_actionability_reason = stale_reason_codes[0]
    elif trust_reason:
        operator_actionability_reason = trust_reason
    else:
        operator_actionability_reason = "not_actionable"

    md["operator_card_actionable"] = bool(card_actionable)
    md["operator_card_trust_state"] = card_trust_state
    md["operator_stale_reason_codes"] = list(stale_reason_codes)
    md["operator_actionability_reason"] = operator_actionability_reason


def _resolve_tier_c_cache_entry_for_sse(
    ticker: str, expiry: Optional[str]
) -> tuple[Optional[tuple], Optional[dict]]:
    """Resolve cached Tier C entry for SSE cache fanout (mirrors REST cache lookup)."""
    t = ticker.upper().strip()
    if expiry is not None:
        ck = (t, expiry)
        ent = _state_cache.get(ck)
        if ent and ent.get("ms_dict"):
            return ck, ent
        return ck, None
    hit = _latest_cache_entry_for_ticker(t)
    if hit:
        return hit[0], hit[1]
    return None, None


def _build_sse_cache_fanout_payload(
    ticker: str,
    expiry: Optional[str],
    *,
    inflight_key: tuple,
    fanout_reason: str,
) -> Optional[dict]:
    """
    Clone cached Tier C bundle for SSE delivery with honest stale/fail-closed metadata.
    Full ms_dict only — never partial patches (Issue 20/23).
    """
    data_cache_key, entry = _resolve_tier_c_cache_entry_for_sse(ticker, expiry)
    if not entry or not entry.get("ms_dict"):
        return None
    t = ticker.upper().strip()
    ck = data_cache_key or (t, entry["ms_dict"].get("selected_exp"))
    now = time.time()
    md = dict(entry["ms_dict"])
    _lmp.merge_into_state(md, t)
    md["_tier"] = "C_analytics"
    md["_endpoint"] = "/api/analytics/state"
    md["_update_source"] = "sse_cache_fanout"
    md["_sse_cache_fanout_reason"] = fanout_reason
    sse_live = bool(ck and _sse_subscribers.get(ck, 0) > 0) or _any_sse_viewer_for_ticker(t)
    _attach_analytics_freshness_contract(
        md,
        data_cache_key=ck or (t, expiry),
        entry=entry,
        now=now,
        sse_live=sse_live,
        inflight_key=inflight_key,
    )
    from trade_impacting_gate import revalidate_cached_decision

    md = revalidate_cached_decision(
        md,
        route="server._build_sse_cache_fanout_payload",
        stale=bool(md.get("analytics_stale")),
    )
    ttl = _sse_viewer_cache_ttl(ck[0], ck[1]) if ck else CACHE_TTL
    _attach_card_freshness_v1_block(
        md,
        ticker=t,
        now=now,
        analytics_ttl_sec=ttl,
        tier_c_cache_stale_serve=bool(md.get("analytics_stale")),
        plane_quote=_lmp.get_quote(t),
    )
    _attach_db_contention_operator_surface(md)
    return md


# ── T5.1 SSE FANOUT DEDUP (2026-07-22) ───────────────────────────────────────
# Measured live (RTH open, one browser tab): the 5s cadence fanout and the
# fetch-in-flight fanout each re-broadcast the SAME cached bundle every tick —
# identical _server_build_ts, ~161 KB apiece — and the client's monotonic gate
# rejected every one as "duplicate" (177 rejects vs 40 accepts in ~18 min).
# Only completed-fetch broadcasts ever carry a new identity. The fanout now
# skips when the (build_ts, analytics_version) it would send is the identity
# already broadcast to the current audience. _sse_conn_epoch is part of the
# identity so a newly connected client still receives the current bundle on
# the next tick. fetch_timeout fanouts share the same suppression: a payload
# the client provably discards is not "keeping SSE alive".
_sse_conn_epoch: int = 0
_last_tier_c_broadcast_identity: dict[tuple, tuple] = {}


def _record_tier_c_broadcast_identity(payload: dict) -> None:
    """Record what was just broadcast so the cache fanout never re-sends it.

    Called synchronously at schedule time (not inside the coroutine): the SSE
    loop fires the cadence fanout and the in-flight fanout in the same event-
    loop turn, so a deferred record would let the second one through.
    """
    try:
        t = payload.get("ticker")
        if not t:
            return
        key = (str(t).upper().strip(), payload.get("selected_exp"))
        _last_tier_c_broadcast_identity[key] = (
            float(payload.get("_server_build_ts") or 0.0),  # silent-zero-ok: epoch-0 ancient sentinel, compared not displayed
            int(payload.get("analytics_version") or 0),  # silent-zero-ok: version 0 means "no analytics version yet", the pre-first-run state this comparison exists to detect
            _sse_conn_epoch,
        )
    except Exception as e:
        # Identity tracking is a suppression hint: a failed record degrades to
        # the pre-fix behavior (one extra broadcast the client dedups), never a
        # lost payload.
        log.debug("tier C broadcast identity record failed: %s", e)


def _tier_c_fanout_is_duplicate(ticker: str, expiry: Optional[str]) -> bool:
    """True when the cached bundle the fanout would send is already on the wire
    for the current connection epoch (client would reject it as a duplicate)."""
    data_cache_key, entry = _resolve_tier_c_cache_entry_for_sse(ticker, expiry)
    if not entry or not entry.get("ms_dict"):
        return False
    md = entry["ms_dict"]
    ck = data_cache_key or (ticker.upper().strip(), md.get("selected_exp"))
    ident = (
        float(md.get("_server_build_ts") or 0.0),  # silent-zero-ok: epoch-0 ancient sentinel, compared not displayed
        int(entry.get("analytics_version") or 0),  # silent-zero-ok: version 0 means "no analytics version yet", the pre-first-run state this comparison exists to detect
        _sse_conn_epoch,
    )
    return _last_tier_c_broadcast_identity.get(ck) == ident


def _schedule_sse_broadcast(payload: dict) -> None:
    if not payload or _main_event_loop is None or _main_event_loop.is_closed():
        return
    _record_tier_c_broadcast_identity(payload)
    asyncio.run_coroutine_threadsafe(_broadcast_snapshot(payload), _main_event_loop)


def _maybe_broadcast_sse_cache_fanout(
    ticker: str,
    expiry: Optional[str],
    *,
    inflight_key: tuple,
    fanout_reason: str,
) -> bool:
    # T5.1: never re-send a bundle identity the current audience already has —
    # the client's monotonic gate rejects it, so it is pure encode/wire waste
    # (checked BEFORE the payload build, which clones + re-attaches contracts).
    if _tier_c_fanout_is_duplicate(ticker, expiry):
        _analytics_cache_observability["sse_fanout_suppressed_duplicate"] += 1
        return False
    payload = _build_sse_cache_fanout_payload(
        ticker,
        expiry,
        inflight_key=inflight_key,
        fanout_reason=fanout_reason,
    )
    if not payload:
        return False
    _schedule_sse_broadcast(payload)
    return True


def _fetch_state_sse_bounded(
    ticker: str,
    expiry: Optional[str],
    *,
    update_source: str,
    timeout_sec: float,
) -> Optional[dict]:
    """Run _fetch_state on an isolated worker with a hard wall-clock timeout."""
    fut = _get_sse_fetch_timeout_executor().submit(
        _fetch_state, ticker, expiry, update_source=update_source
    )
    try:
        return fut.result(timeout=max(0.5, float(timeout_sec)))
    except TimeoutError:
        return None


# SESSION_OPEN_ANCHOR_WARM_SLICE_V1 (additive instrumentation): last completed
# Tier C recompute duration per ticker — proves/refutes the RTH-open latency
# composition (root-cause packet 2026-07-06: cycles ran 15–21s vs the 10s
# staleness budget). Observability only; no freshness/actionability influence.
_analytics_recompute_last_duration_sec: dict[str, float] = {}

# TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 (passive observation only): Tier C cache
# lifecycle counters — pending shells built, bg-failure stale-marks, expiry
# evictions, and cold (version-reset) cache writes. Complements the existing
# _stage_marks/_compute_breakdown stage timers in _fetch_state. Nothing reads
# these for freshness, trust, actionability, sizing, or synthesis decisions.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — timing/counter observability around existing
#   Tier C calls; no market field read, derivation, or emission changed.
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (observability only).
# All consumers checked: yes — additive fields (_finalize_tail_ms,
#   analytics_executor_queue_wait_sec, analytics_cache_observability_v1) are
#   diagnostics/log surfaces; trust/freshness/actionability unchanged (lock:
#   test_timing_fields_do_not_affect_trust_or_actionability).
# SCHWAB_CSV_CHECKED
_analytics_cache_observability: dict[str, int] = {
    "pending_shell_builds": 0,
    "bg_failure_stale_marks": 0,
    "expiry_evictions": 0,
    "cold_entry_writes": 0,
    # FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 — audit-trail-only visibility for
    # post-publish persistence failures (served payload is never degraded).
    "post_publish_snapshot_failures": 0,
    "post_publish_calibration_failures": 0,
    # T5.1 — cadence/in-flight fanouts skipped because the identical bundle
    # identity was already broadcast to the current connection epoch.
    "sse_fanout_suppressed_duplicate": 0,
}

# EXEC-03 POST_PUBLISH_LAST_ERROR_OBSERVABILITY_V1 — most recent post-publish
# persistence failure per kind ("snapshot" | "calibration"), REST-visible via
# ms_dict["post_publish_last_errors_v1"]. Audit-trail-only: the served payload
# is already published when the tail runs, so a failure recorded here appears
# in the NEXT publish's payload copy. Ticker is runtime data — the capture
# path is identical for every ticker (no ticker-conditional behavior).
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — exception metadata (exc_type, detail,
#   traceback tail) around existing persistence calls; the companion nonlocal
#   mkt_ctx repair restores the pre-relocation confluence-completion binding
#   (existing chains/quotes leaf consumption unchanged); no market field read,
#   derivation, or emission changed.
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (observability only).
# All consumers checked: yes — post_publish_last_errors_v1 is an additive
#   diagnostics surface beside analytics_cache_observability_v1; trust,
#   freshness, actionability, sizing, and synthesis unchanged (locks:
#   test_post_publish_last_error_recorder_is_passive,
#   test_tail_mkt_ctx_nonlocal_rebind_restored).
# SCHWAB_CSV_CHECKED
_post_publish_last_errors: dict[str, dict] = {}


def _record_post_publish_failure(kind, ticker, published_version, exc):
    """Record last post-publish persistence failure detail (cause visibility).

    Counters stay at the call sites (locked by the failure-counter source
    tests); this captures cause detail only. Must be called from inside the
    except handler so format_exc() sees the active exception. Never raises;
    never touches _state_cache or the counter dict.
    """
    import traceback as _tb

    try:
        _post_publish_last_errors[kind] = {
            "ts_epoch": round(time.time(), 3),
            "ticker": str(ticker),
            "published_version": published_version,
            "exc_type": type(exc).__name__,
            "detail": str(exc)[:400],
            "traceback_tail": _tb.format_exc().splitlines()[-12:],
        }
    except Exception:
        # institutional-swallow-ok: recording error diagnostics is best-effort and must
        # never disturb the persistence tail; the underlying error is handled upstream.
        pass


def _schedule_analytics_recompute(
    inflight_key: tuple,
    ticker: str,
    expiry: Optional[str],
    update_source: str,
) -> None:
    """
    Run _fetch_state in a thread pool; broadcast full snapshot on success.
    Dedupes identical (ticker, expiry|__auto__) jobs.

    SSE loop path (update_source=sse_loop): cache fanout on each cadence / while in-flight
    so Tier C SSE is not starved by slow _fetch_state or DB lock contention (T5).
    """
    if _analytics_bg_shutdown:
        return
    sse_loop = update_source == "sse_loop"
    # LIVE_OPERATOR_MODE_RESET_V1 Step 3 — deadlock fix: decide the in-flight branch
    # under _analytics_bg_lock, then RELEASE before fanning out. The fanout chain
    # re-enters this same non-reentrant lock via _attach_analytics_freshness_contract,
    # which self-deadlocked the event loop (py-spy proof:
    # reports/ui_transport/step1_2_proof_wedge_pyspy_dump_20260702.txt).
    with _analytics_bg_lock:
        if _analytics_bg_shutdown:
            return
        in_flight = inflight_key in _analytics_inflight
        if not in_flight:
            _analytics_inflight.add(inflight_key)
    if in_flight:
        if sse_loop:
            _maybe_broadcast_sse_cache_fanout(
                ticker,
                expiry,
                inflight_key=inflight_key,
                fanout_reason="fetch_in_flight",
            )
        log.debug("analytics refresh already in flight %s", inflight_key)
        return

    def _work() -> None:
        try:
            executor_queue_wait_sec = round(max(0.0, time.monotonic() - _submitted_monotonic), 3)
            fetch_started_monotonic = time.monotonic()
            if sse_loop:
                timeout_sec = max(0.5, float(SSE_RECOMPUTE_FETCH_TIMEOUT_SEC))
                result = _fetch_state_sse_bounded(
                    ticker,
                    expiry,
                    update_source=update_source,
                    timeout_sec=timeout_sec,
                )
                if result is None:
                    log.info(
                        "sse_loop fetch timeout ticker=%s expiry=%s timeout_s=%.1f",
                        ticker,
                        expiry,
                        timeout_sec,
                    )
                    _maybe_broadcast_sse_cache_fanout(
                        ticker,
                        expiry,
                        inflight_key=inflight_key,
                        fanout_reason="fetch_timeout",
                    )
                    return
            else:
                result = _fetch_state(ticker, expiry, update_source=update_source)
            if result:
                recompute_duration_sec = round(time.monotonic() - fetch_started_monotonic, 3)
                _analytics_recompute_last_duration_sec[ticker.upper().strip()] = recompute_duration_sec
                result["analytics_recompute_duration_sec"] = recompute_duration_sec
                result["analytics_executor_queue_wait_sec"] = executor_queue_wait_sec
                stale_budget_sec = float(CACHE_TTL) * ANALYTICS_STALE_GRACE_CYCLES
                if recompute_duration_sec >= stale_budget_sec:
                    log.info(
                        "analytics recompute exceeded staleness budget ticker=%s "
                        "duration=%.3fs queue_wait=%.3fs budget=%.1fs source=%s",
                        ticker,
                        recompute_duration_sec,
                        executor_queue_wait_sec,
                        stale_budget_sec,
                        update_source,
                    )
                _reset_analytics_bg_fail_count(inflight_key)
                _stamp_analytics_freshness_on_completed_fetch(result, ticker, inflight_key)
                # S2B-1 transport parity: REST serve and SSE cache-fanout attach
                # card_freshness_v1 + operator_card_* mirrors, but this completed-fetch
                # broadcast reached SSE clients WITHOUT them — in a fresh-bundle /
                # stale-quote window an SSE-fed card could paint actionable while REST
                # clients are withheld (quote_age_exceeded). Attach the same block so
                # both transports carry identical actionability truth (audit 2026-07-04).
                # Schwab CSV authority checked: yes
                # CSV row(s): NO_SCHWAB_EQUIVALENT — attaches existing card_freshness_v1 /
                #   operator mirrors to an already-built Tier C payload; no market field
                #   read, derivation, or emission changed.
                # Derived-field disposition: GATE_FAIL_CLOSED (actionability withheld on
                #   stale quote/bundle).
                # All consumers checked: yes — SSE onmessage → resolveCardTrustGate consumers;
                #   REST + SSE cache-fanout already attach the same block.
                # SCHWAB_CSV_CHECKED
                try:
                    _attach_card_freshness_v1_block(
                        result,
                        ticker=ticker,
                        now=time.time(),
                        analytics_ttl_sec=_sse_viewer_cache_ttl(
                            ticker.upper().strip(), result.get("selected_exp")
                        ),
                        tier_c_cache_stale_serve=False,
                        plane_quote=_lmp.get_quote(ticker.upper().strip()),
                    )
                except Exception as _cf_e:
                    log.debug(
                        "card_freshness attach on completed fetch failed ticker=%s: %s",
                        ticker,
                        _cf_e,
                    )
                try:
                    from planes.l1_events import notify_l2_snapshot_ready

                    notify_l2_snapshot_ready(ticker, result.get("selected_exp"))
                except Exception as e:
                    log.debug("notify_l2_snapshot_ready failed ticker=%s: %s", ticker, e, exc_info=True)
            if result and _main_event_loop is not None and not _main_event_loop.is_closed():
                _schedule_sse_broadcast(result)
        except HTTPException as ex:
            log.warning("analytics bg HTTPException for %s", inflight_key)
            detail, token_invalid = _analytics_bg_error_detail(ex)
            _record_analytics_bg_failure(
                inflight_key,
                ticker,
                reason="http_exception",
                detail=detail,
                token_invalid=token_invalid,
            )
        except SchwabAuthError as ex:
            log.warning("analytics bg SchwabAuthError for %s: %s", inflight_key, ex)
            _record_analytics_bg_failure(
                inflight_key,
                ticker,
                reason="schwab_auth",
                detail=str(ex),
                token_invalid=True,
            )
        except Exception as ex:
            if isinstance(ex, RuntimeError) and "shutdown" in str(ex).lower():
                log.debug("analytics bg skipped during shutdown %s", inflight_key)
            else:
                log.error("analytics bg failed %s: %s", inflight_key, ex, exc_info=True)
                detail, token_invalid = _analytics_bg_error_detail(ex)
                _record_analytics_bg_failure(
                    inflight_key,
                    ticker,
                    reason="generic_exception",
                    detail=detail,
                    token_invalid=token_invalid,
                )
        finally:
            with _analytics_bg_lock:
                _analytics_inflight.discard(inflight_key)

    _submitted_monotonic = time.monotonic()
    try:
        # UI_05_OPERATOR_PRIORITY_ADMISSION_V1: operator-facing sources get the
        # bounded priority lane; background sources keep the analytics pool.
        _submit_analytics_task(
            _work, priority=_is_operator_priority_update_source(update_source)
        )
    except RuntimeError:
        with _analytics_bg_lock:
            _analytics_inflight.discard(inflight_key)


def _stamp_analytics_freshness_on_completed_fetch(
    md: dict,
    ticker: str,
    inflight_key: tuple,
) -> None:
    """Align SSE/pushed Tier C payloads with the analytics freshness contract."""
    t = ticker.upper().strip()
    exp = md.get("selected_exp")
    ck = (t, exp)
    ent = _state_cache.get(ck)
    analytics_freshness_eval_wall_ts = time.time()
    sse_live = _sse_subscribers.get(ck, 0) > 0
    _attach_analytics_freshness_contract(
        md,
        data_cache_key=ck,
        entry=ent,
        now=analytics_freshness_eval_wall_ts,
        sse_live=sse_live,
        inflight_key=inflight_key,
    )
    # Completed fetch — this payload is the fresh computation (not a queued stale read).
    md["analytics_stale"] = False
    md["analytics_refresh_in_progress"] = False
    if ent:
        gen_ts = _analytics_generated_ts(ent)
        if gen_ts is not None:      # RC-282: None is undatable, not "timestamp zero"
            md["analytics_age_sec"] = max(
                0.0, round(analytics_freshness_eval_wall_ts - gen_ts, 3)
            )


def _any_sse_viewer_for_ticker(ticker: str) -> bool:
    t = ticker.upper().strip()
    with _sse_lock:
        return any(tk == t and n > 0 for (tk, _), n in _sse_subscribers.items())


def _analytics_bg_error_detail(exc: BaseException) -> tuple[str, bool]:
    """Normalize bg failure text + whether this is a Schwab auth failure."""
    if isinstance(exc, SchwabAuthError):
        return (str(exc)[:500], True)
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            msg = str(
                detail.get("remediation")
                or detail.get("message")
                or detail.get("error")
                or detail
            )
            token_invalid = detail.get("error") == "token_invalid"
            return (msg[:500], token_invalid)
        msg = str(detail or exc)
        token_invalid = "token" in msg.lower() and (
            "invalid" in msg.lower() or "revoked" in msg.lower() or "expired" in msg.lower()
        )
        return (msg[:500], token_invalid)
    msg = str(exc)
    from schwab_client import _is_token_error

    return (msg[:500], _is_token_error(exc))


def _write_analytics_bg_error_shell(
    ticker: str,
    expiry: Optional[str],
    detail: str,
    *,
    token_invalid: bool = False,
) -> None:
    """Cold-cache Tier C: persist operator-visible error instead of endless empty pending shell."""
    t = ticker.upper().strip()
    _, existing_key = _latest_cached_ms_and_key_for_ticker(t)
    if existing_key is not None:
        return
    exp = expiry if expiry is not None else "__auth_error__"
    ck = (t, exp)
    now = time.time()
    rem = "Schwab auth failed — run: python reauth_schwab.py --manual"
    err_text = rem if token_invalid else (detail or "Tier C refresh failed")
    md = _minimal_analytics_pending_dict(t, expiry)
    md["analytics_pending_shell"] = False
    md["state_error"] = "token_invalid" if token_invalid else "analytics_refresh_failed"
    md["state_error_detail"] = err_text[:500]
    md["analytics_last_error"] = (detail or err_text)[:500]
    md["analytics_stale"] = True
    md["analytics_refresh_in_progress"] = False
    if token_invalid:
        md["error"] = "token_invalid"
        md["remediation"] = rem
    md["call_signal"] = "wait"
    md["fusion_available"] = False
    md["mhap_rows"] = []
    _lmp.merge_into_state(md, t)
    _state_cache[ck] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": 0,
        "ms_dict": md,
        "pcr_val": None,
        "spot_f": md.get("spot"),
        "vix": None,
        "price_levels": None,
        "pl_date": "",
        "pl_generation": None,
        "pl_mono": None,
    }


def _minimal_analytics_pending_dict(ticker: str, expiry: Optional[str]) -> dict:
    """Empty Tier C shell when no cache — client keeps Tier A DOM until SSE/REST delivers full bundle."""
    _analytics_cache_observability["pending_shell_builds"] += 1
    t = ticker.upper().strip()
    pending_shell_ingestion_wall_ts = time.time()
    return {
        "_tier": "C_analytics",
        "analytics_pending_shell": True,
        "ticker": t,
        "selected_exp": expiry,
        "expiries": [],
        "walls": [],
        "totals_rows": [],
        "summary_rows": [],
        "state_error": None,
        "_server_build_ts": pending_shell_ingestion_wall_ts,
        "_pipeline_ms": 0,
        "_endpoint": "/api/analytics/state",
    }


def _attach_db_contention_operator_surface(ms_dict: dict) -> None:
    """Operator-visible DB transport warning — does not change model/card direction."""
    try:
        from db import sqlite_contention_metrics_snapshot
        from verification.db_sqlite_contention_impact_audit import (
            build_db_contention_operator_surface,
        )

        ms_dict["db_contention_operator"] = build_db_contention_operator_surface(
            sqlite_contention_metrics_snapshot()
        )
    except Exception as e:
        log.debug("attach db_contention_operator failed: %s", e)
        ms_dict["db_contention_operator"] = {
            "state": "OK",
            "show": False,
            "diagnostics_source": "/api/diagnostics/sqlite-contention",
        }


def _exposure_dataclass_rows_to_dict(rows) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        try:
            out.append(asdict(row))
        except TypeError:
            if isinstance(row, dict):
                out.append(dict(row))
    return out


def _float_key_level(v) -> Optional[float]:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _publish_progressive_tier_c_cache(
    *,
    ticker: str,
    cache_key: tuple,
    inflight_key: tuple,
    selected_exp: str,
    expiries: list[str],
    today_str: str,
    spot_f: float,
    bid,
    ask,
    session_label: str,
    rows,
    walls,
    totals,
    consensus_summary,
    exposures,
    gamma_flip,
    gamma_voids,
    charm_net,
    charm_dir,
    charm_toward,
    pcr_val,
    kl_expiry_source: str,
    quote_spread_pts,
    quote_spread_source: str,
    update_source: Optional[str],
) -> None:
    """
    After chain + exposures: publish a non-pending Tier C cache entry so REST/SSE
    can render expiries, key levels, and exposure tables while ML/fusion completes.
    """
    prev_ent = _state_cache.get(cache_key) or {}
    prev_md = prev_ent.get("ms_dict") if isinstance(prev_ent.get("ms_dict"), dict) else {}
    if prev_md and not prev_md.get("analytics_pending_shell"):
        if prev_md.get("mhap_rows") and prev_md.get("fusion_available"):
            return

    t = ticker.upper().strip()
    # RC-128 cleanup: w0/cs bindings deleted — they fed only the Tier-C kl_ writes the
    # One Levels Faucet burn removed; pure-expression RHS, nothing else read them.
    now = time.time()

    md: dict[str, Any] = {
        "_tier": "C_analytics",
        "analytics_pending_shell": False,
        "analytics_partial_tier_c": True,
        "analytics_refresh_in_progress": True,
        "ticker": t,
        "selected_exp": selected_exp,
        "expiries": [e for e in expiries if e >= today_str],
        "spot": spot_f,
        "spot_disp": f"{spot_f:.2f}",
        "bid": bid,
        "ask": ask,
        "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
        "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
        "session_label": session_label,
        "summary_rows": _exposure_dataclass_rows_to_dict(rows),
        "walls": _exposure_dataclass_rows_to_dict(walls),
        "totals_rows": _exposure_dataclass_rows_to_dict(totals),
        "pcr_val": pcr_val,
        "charm_net": charm_net,
        "charm_direction": charm_dir,
        "charm_drift_toward": charm_toward,
        "kl_expiry_source": kl_expiry_source,
        # RC-128 (One Levels Faucet): every SSOT level key (walls, flip, pin, hvl, max pain,
        # delta walls, EM, and the unowned oi/vanna/inflection set) is written ONLY by
        # _terrain_kl_overlay below — the analytics assignments that lived here were DELETED,
        # not overridden. Placement was the bug: any later write resurrected the dual book.
        "kl_gamma_voids": gamma_voids or [],
        "kl_metrics_dollarized": bool(exposures and exposures_have_dollar_gex(exposures)),
        "spread": quote_spread_pts,
        "spread_source": quote_spread_source,
        "fusion_available": False,
        "call_signal": "wait",
        "call_conviction": "low",
        "dominant_dir": "flat",
        "mhap_rows": list(prev_md.get("mhap_rows") or []),
        "state_error": None,
        "_server_build_ts": now,
        "_pipeline_ms": 0,
        "_endpoint": "/api/analytics/state",
    }
    if update_source is not None:
        md["_update_source"] = update_source
    _terrain_kl_overlay(md, t)   # RC-122: one wall book (terrain SSOT) on every kl_* payload
    _lmp.merge_into_state(md, t)

    _state_cache[cache_key] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": int(prev_ent.get("analytics_version", 0)),
        "ms_dict": md,
        "pcr_val": pcr_val,
        "spot_f": spot_f,
        "vix": prev_ent.get("vix"),
        "price_levels": prev_ent.get("price_levels"),
        "pl_date": prev_ent.get("pl_date", ""),
        "pl_generation": prev_ent.get("pl_generation"),
        "pl_mono": prev_ent.get("pl_mono"),
    }

    if _main_event_loop is not None and not _main_event_loop.is_closed():
        payload = dict(md)
        sse_live = _sse_subscribers.get(cache_key, 0) > 0
        _attach_analytics_freshness_contract(
            payload,
            data_cache_key=cache_key,
            entry=_state_cache.get(cache_key),
            now=now,
            sse_live=sse_live,
            inflight_key=inflight_key,
        )
        try:
            # T5.1: routed through _schedule_sse_broadcast so the identity
            # record covers the progressive partial too (same suppression law
            # as the completed-fetch and fanout broadcasts).
            _schedule_sse_broadcast(payload)
        except Exception as e:
            log.debug("progressive tier C broadcast failed ticker=%s: %s", t, e, exc_info=True)


def _prewarm_inference_models_worker(ticker: str) -> None:
    """Disk → in-memory ML registry load (all primary horizons); no inference."""
    try:
        from ml_predict import prewarm_inference_models_for_ticker

        prewarm_inference_models_for_ticker(ticker)
    except Exception as ex:
        log.debug("inference prewarm failed ticker=%s: %s", ticker, ex, exc_info=True)


def _schedule_analytics_warm(
    ticker: str,
    expiry: Optional[str] = None,
    update_source: str = "client_warm",
    *,
    prewarm_models: bool = True,
) -> dict[str, Any]:
    """UI-MAXIMIZE: queue Tier C recompute + optional model registry prewarm."""
    t = ticker.upper().strip()
    inflight_key = _tier_c_inflight_key(t, expiry)
    if prewarm_models and not _analytics_bg_shutdown:
        try:
            _submit_analytics_task(_prewarm_inference_models_worker, t)
        except RuntimeError:
            pass
    _schedule_analytics_recompute(inflight_key, t, expiry, update_source)
    return {
        "ok": True,
        "ticker": t,
        "expiry": expiry,
        "scheduled_refresh": True,
        "prewarm_models": bool(prewarm_models),
        "update_source": update_source,
    }


def _warm_panel_ticker_after_delay(ticker: str, delay_sec: float, update_source: str) -> None:
    """Shared staggered panel-anchor warm worker (startup + session-open paths)."""
    if delay_sec > 0:
        time.sleep(delay_sec)
    try:
        _schedule_analytics_warm(ticker, None, update_source, prewarm_models=True)
        log.info("panel anchor warm scheduled for %s (%s)", ticker, update_source)
    except Exception as e:
        log.warning("panel anchor warm scheduling failed %s (%s): %s", ticker, update_source, e)


def _schedule_startup_analytics_warm() -> None:
    """Cold start: warm SPY/QQQ/IWM Tier C (+ model prewarm) before logger hammers Schwab."""
    tickers = UI_MAXIMIZE_PANEL_WARM_TICKERS
    stagger = max(0.0, UI_MAXIMIZE_WARM_STAGGER_SEC)

    if _analytics_bg_shutdown or os.environ.get("ED_DISABLE_STARTUP_ANALYTICS_WARM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return

    for i, t in enumerate(tickers):
        try:
            _submit_analytics_task(_warm_panel_ticker_after_delay, t, i * stagger, "startup_warm")
        except RuntimeError:
            break
    log.info("UI-MAXIMIZE startup warm queue: %s stagger=%ss", tickers, stagger)
    _schedule_startup_model_prewarm_sweep()


def _startup_model_prewarm_roster() -> list[str]:
    """Own-bundle tickers under models/active, panel-warm anchors first.

    UI_05 residual: a guest whose bundle is its OWN ticker pays 4-horizon
    torch loads (~12s measured, NFLX-class) on first touch. Sweeping those
    loads sequentially at boot moves the cost off the operator request path.
    Serve-policy withholding still applies inside the load path (a withheld
    bundle logs and stays unloaded - the sweep never bypasses MODEL-04)."""
    try:
        from ml_predict import MODEL_DIR as _model_dir

        base = _model_dir / "active"
        roster = sorted(
            p.name for p in base.iterdir()
            if p.is_dir() and p.name.upper() == p.name and not p.name.startswith(".")
        )
    except OSError:
        return list(UI_MAXIMIZE_PANEL_WARM_TICKERS)
    anchors = [t for t in UI_MAXIMIZE_PANEL_WARM_TICKERS if t in roster]
    rest = [t for t in roster if t not in anchors]
    return anchors + rest


def _startup_model_prewarm_sweep_worker() -> None:
    roster = _startup_model_prewarm_roster()
    log.info("UI_05 startup model prewarm sweep: %d bundle dirs", len(roster))
    for t in roster:
        if _analytics_bg_shutdown:
            return
        _prewarm_inference_models_worker(t)


def _schedule_startup_model_prewarm_sweep() -> None:
    """One sequential background thread — never floods CPU, never touches the
    request path, fail-open per ticker (prewarm worker swallows and logs)."""
    if os.environ.get("ED_DISABLE_STARTUP_MODEL_PREWARM", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return
    threading.Thread(
        target=_startup_model_prewarm_sweep_worker,
        name="ed_model_prewarm_sweep",
        daemon=True,
    ).start()


# ── SESSION_OPEN_ANCHOR_WARM_SLICE_V1 — RTH-open anchor bundle warm ──────────
# Root cause (RTH_ANALYTICS_STALENESS_ROOT_CAUSE_V1): anchor Tier C bundles were
# cold/demand-created after the 09:30 ET open (proof 2026-07-06: QQQ/IWM
# analytics_version=1 only at 08:33 CT via harness warm). Startup warm covers
# process start only; this loop re-warms the same panel anchors once per ET
# trading day at the first observed instant inside RTH, through the SAME
# recompute path (_schedule_analytics_warm → _schedule_analytics_recompute
# in-flight dedupe) — no parallel analytics engine, no TTL/grace change.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — session-clock scheduling of the existing
#   Tier C recompute; no market field read, derivation, or emission changed.
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (scheduling only).
# All consumers checked: yes — delegates to the existing warm/recompute cone;
#   analytics_stale semantics (_attach_analytics_freshness_contract) untouched.
# SCHWAB_CSV_CHECKED
SESSION_OPEN_ANCHOR_WARM_POLL_SEC: float = 15.0
SESSION_OPEN_ANCHOR_WARM_UPDATE_SOURCE: str = "session_open_anchor_warm"
_session_open_anchor_warm_last_date: Optional[str] = None
_session_open_anchor_warm_stop = threading.Event()


def _session_open_anchor_warm_due(et_now: datetime, last_warmed_et_date: Optional[str]) -> bool:
    """True once per ET trading day when the wall clock is inside RTH (09:30–16:00 ET)."""
    if et_now.weekday() >= 5:
        return False
    mins = et_now.hour * 60 + et_now.minute
    if not (RTH_OPEN_MINS <= mins < RTH_END_MINS):
        return False
    return et_now.strftime("%Y-%m-%d") != last_warmed_et_date


def _run_session_open_anchor_warm() -> None:
    """Queue the RTH-open anchor warm — same roster, stagger, and dedupe as startup warm."""
    stagger = max(0.0, UI_MAXIMIZE_WARM_STAGGER_SEC)
    for i, t in enumerate(UI_MAXIMIZE_PANEL_WARM_TICKERS):
        try:
            _submit_analytics_task(
                _warm_panel_ticker_after_delay, t, i * stagger, SESSION_OPEN_ANCHOR_WARM_UPDATE_SOURCE
            )
        except RuntimeError:
            break
    log.info(
        "session-open anchor warm queued: %s stagger=%ss",
        UI_MAXIMIZE_PANEL_WARM_TICKERS,
        stagger,
    )


def _session_open_anchor_warm_loop() -> None:
    """Daemon loop: fire _run_session_open_anchor_warm once per ET trading day in RTH."""
    global _session_open_anchor_warm_last_date
    while not _session_open_anchor_warm_stop.wait(SESSION_OPEN_ANCHOR_WARM_POLL_SEC):
        if _analytics_bg_shutdown:
            continue
        try:
            et = now_et()
            if _session_open_anchor_warm_due(et, _session_open_anchor_warm_last_date):
                _session_open_anchor_warm_last_date = et.strftime("%Y-%m-%d")
                _run_session_open_anchor_warm()
        except Exception as e:
            log.warning("session-open anchor warm loop error: %s", e)


# ── ANCHOR_QUOTE_LANE_REFRESHER_V1 — keep panel-anchor quote lanes fresh ──────
# Root cause (ANCHOR_QUOTE_LANE_QQQ_FROZEN_TIMESTAMP_TRACE_V1, 2026-07-07):
# live_market_plane lanes update only for the currently streamed / actively
# REST-polled ticker and rows never expire — switched-away anchors freeze
# (QQQ quote_ts frozen 7,120s across three captures), never-polled anchors have
# no lane at all (IWM missing_quote_ts), and even SPY drifts when unpolled.
# The frozen/missing quote_ts drives the operator-mirror quote veto and blocks
# card trust continuously. This loop refreshes stale/missing lanes for the
# panel roster through the SAME REST fast-quote path the /api/fast-quote
# endpoint uses (_record_rest_fast_quote_with_auth_fallback → record_quote;
# auth-latch carry-forward preserved). Ticker-agnostic by construction: the
# roster is config (UI_MAXIMIZE_PANEL_WARM_TICKERS) and the staleness predicate
# reads lane fields only. A freshly streamed lane is younger than the threshold
# and is skipped — streaming behavior is untouched.
# Schwab CSV authority checked: yes
# CSV row(s): quotes.*.lastPrice / quotes.*.mark et al via the EXISTING
#   _build_rest_fast_quote_payload (schwab_client.safe_get_quote) — scheduling
#   only; no market field read, derivation, or emission changed.
# Derived-field disposition: none required (no derived field touched).
# All consumers checked: yes — record_quote rows carry quote_ingestion
#   "rest_anchor_lane_refresher" (no consumer branches on that value);
#   card_freshness quote ages simply read fresher exchange_quote_ts.
# SCHWAB_CSV_CHECKED
#: t12 (RC-227 residual): a prior-day fact requires plausibly FULL session coverage from
#: the live accumulator (~390 RTH minutes; floor 300) — below it, /api/levels falls
#: through to banked canonical bars rather than serving a truncated min/max.
LEVELS_PRIOR_SESSION_MIN_BARS: int = 300

ANCHOR_QUOTE_LANE_REFRESH_POLL_SEC: float = 20.0
ANCHOR_QUOTE_LANE_MAX_AGE_SEC: float = 20.0
_anchor_quote_lane_refresh_stop = threading.Event()
_anchor_quote_lane_refresh_counts: dict[str, int] = {
    "refreshes": 0,
    "bootstraps": 0,
    "errors": 0,
}


def _anchor_quote_lane_needs_refresh(row: Optional[dict], now: float) -> bool:
    """Ticker-agnostic lane-staleness predicate: absent row, missing ts, or old ts."""
    if not row:
        return True
    fts = row.get("exchange_quote_ts")
    if fts is None:
        return True
    try:
        return (now - float(fts)) > ANCHOR_QUOTE_LANE_MAX_AGE_SEC
    except (TypeError, ValueError):
        return True


def _run_anchor_quote_lane_refresh_once(now: Optional[float] = None) -> int:
    """Refresh stale/missing plane lanes for the panel roster; returns refresh count."""
    ts = time.time() if now is None else float(now)
    done = 0
    for t in UI_MAXIMIZE_PANEL_WARM_TICKERS:
        try:
            prev = _lmp.get_quote(t)
            if not _anchor_quote_lane_needs_refresh(prev, ts):
                continue
            _anchor_quote_lane_refresh_counts["bootstraps" if not prev else "refreshes"] += 1
            _record_rest_fast_quote_with_auth_fallback(t, prev, "rest_anchor_lane_refresher")
            done += 1
        except Exception as e:
            _anchor_quote_lane_refresh_counts["errors"] += 1
            log.warning("anchor quote lane refresh failed ticker=%s: %s", t, e)
    return done


def _anchor_quote_lane_refresh_loop() -> None:
    """Daemon: keep anchor quote lanes inside the trust threshold during sessions."""
    while not _anchor_quote_lane_refresh_stop.wait(ANCHOR_QUOTE_LANE_REFRESH_POLL_SEC):
        if _analytics_bg_shutdown:
            continue
        try:
            if now_et().weekday() >= 5 or not _is_loggable_session():
                continue
            _run_anchor_quote_lane_refresh_once()
        except Exception as e:
            log.warning("anchor quote lane refresh loop error: %s", e)


def _sse_viewer_cache_ttl(ticker: str, expiry: Optional[str]) -> float:
    """REST /api/state cache TTL: short while a client is SSE-subscribed to this (ticker, expiry)."""
    if expiry is None:
        return CACHE_TTL
    t = ticker.upper().strip()
    with _sse_lock:
        if _sse_subscribers.get((t, expiry), 0) > 0:
            return max(0.5, VIEWER_STATE_CACHE_TTL_SEC)
    return CACHE_TTL


def _evict_old_expiry_entries(ticker: str, keep_expiry: Optional[str]) -> None:
    """Remove cache entries for (ticker, other_expiry) where other_expiry != keep_expiry."""
    keys_to_remove = [
        k for k in list(_state_cache)
        if k[0] == ticker and k[1] != keep_expiry
    ]
    _analytics_cache_observability["expiry_evictions"] += len(keys_to_remove)
    for k in keys_to_remove:
        del _state_cache[k]


def _plane_fast_quote_has_spot(row: dict | None) -> bool:
    if not row or not isinstance(row, dict):
        return False
    spot = row.get("spot")
    if spot is None:
        return False
    try:
        return float(spot) > 0
    except (TypeError, ValueError):
        return False


def _stale_fast_quote_carried_forward(prev: dict, tkr: str) -> dict:
    out = dict(prev)
    qsd = dict(out.get("quote_source_detail") or {})
    qsd["carried_forward"] = True
    qsd["schwab_auth_degraded"] = True
    out["quote_source_detail"] = qsd
    out["fast_generation_id"] = _lmp.next_fast_generation(tkr)
    # W3-C4 / RC-121: the degraded row must be RECORDED, not just served. Five call sites
    # returned this payload while the plane kept the pre-degradation row — so every plane
    # reader (merge_into_state, SSE, L1 overlay) kept serving an undegraded picture under an
    # advanced generation id. Recording here, inside the builder, covers every caller at once.
    _lmp.record_quote(tkr, out)
    return out


def _schwab_auth_http_unavailable(he: HTTPException) -> bool:
    if he.status_code not in (401, 503):
        return False
    detail = str(he.detail or "").lower()
    return "schwab auth" in detail or "token" in detail


def _fast_quote_token_invalid_payload(detail: str) -> dict:
    return {
        "error": "token_invalid",
        "detail": detail or "Schwab auth unavailable.",
        "message": "Schwab authentication failed. Token missing, expired, or invalid.",
        "remediation": "Run: python reauth_schwab.py --manual",
    }


def _record_rest_fast_quote_with_auth_fallback(
    tkr: str, prev: dict | None, quote_ingestion: str
) -> dict:
    """REST fast quote; on Schwab auth failure serve last plane row when spot is present."""
    from schwab_client import SchwabAuthError, _is_token_error, _schwab_auth_latched, _raise_schwab_auth_error

    if _schwab_auth_latched():
        if _plane_fast_quote_has_spot(prev):
            log.warning(
                "fast_quote auth latched ticker=%s — serving carried-forward plane quote",
                tkr,
            )
            return _stale_fast_quote_carried_forward(prev, tkr)
        raise SchwabAuthError("Schwab auth latched — fast quote withheld (no plane cache)")

    try:
        out = _build_rest_fast_quote_payload(tkr, quote_ingestion)
        _lmp.record_quote(tkr, out)
        return out
    except HTTPException as he:
        if not _schwab_auth_http_unavailable(he):
            raise
        try:
            _raise_schwab_auth_error(Exception(str(he.detail)))
        except SchwabAuthError:
            pass
        if _plane_fast_quote_has_spot(prev):
            log.warning(
                "fast_quote Schwab client unavailable ticker=%s — serving carried-forward plane quote",
                tkr,
            )
            return _stale_fast_quote_carried_forward(prev, tkr)
        raise SchwabAuthError(str(he.detail)) from he
    except Exception as e:
        if not (_is_token_error(e) or isinstance(e, SchwabAuthError)):
            raise
        try:
            _raise_schwab_auth_error(e)
        except SchwabAuthError:
            pass
        if _plane_fast_quote_has_spot(prev):
            log.warning(
                "fast_quote REST auth failed ticker=%s — serving carried-forward plane quote",
                tkr,
            )
            return _stale_fast_quote_carried_forward(prev, tkr)
        raise


def _build_rest_fast_quote_payload(tkr: str, quote_ingestion: str) -> dict:
    """Schwab REST quote → plane-shaped dict (does not record)."""
    t0 = time.perf_counter()
    thread_name = threading.current_thread().name
    t_client0 = time.perf_counter()
    client = get_client()
    t_client1 = time.perf_counter()
    t_sess0 = time.perf_counter()
    with _cached_mkt_ctx_lock:
        _cmc = _cached_mkt_ctx
    session_label = getattr(_cmc, "session_label", None) if _cmc is not None else None
    if session_label is not None and not str(session_label).strip():
        session_label = None
    t_sess1 = time.perf_counter()
    quote_attempts = 0

    def _attempt_hook() -> None:
        nonlocal quote_attempts
        quote_attempts += 1

    t_quote0 = time.perf_counter()
    # RC-112: the fast lane reads through the same memo as resolve_spot — one vendor call
    # serves both inside the TTL.
    q_resp = _memoized_quote_response(tkr, client=client, attempt_hook=_attempt_hook)
    t_quote1 = time.perf_counter()
    if q_resp is None or q_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Quote fetch failed")
    q_json = q_resp.json()
    t_parse0 = time.perf_counter()
    _node = q_json.get(tkr.upper()) or q_json.get(tkr) or {}
    pq = _parse_quote_node_session_fields(_node)
    spot_f = pq["spot"]
    spot_source = pq["spot_source"]
    bid = pq["bid"]
    ask = pq["ask"]
    quote_mid = pq["quote_mid"]
    mid_source = pq["mid_source"]
    spread_frac = None
    spread_pts = None
    try:
        if quote_mid is not None and quote_mid > 0 and bid is not None and ask is not None:
            bf, af = float(bid), float(ask)
            spread_frac = (af - bf) / quote_mid
            spread_pts = round(af - bf, 4)
            if spread_pts is not None and spread_pts < 0.0:
                spread_pts = None
    except (TypeError, ValueError):
        pass
    t_parse1 = time.perf_counter()
    quote_ts = pq["quote_ts"]
    server_received_ts = time.time()
    total_ms = (time.perf_counter() - t0) * 1000.0
    log.info(
        "fast_quote_timing ticker=%s thread=%s total_ms=%.2f get_client_ms=%.3f "
        "session_cache_ms=%.3f schwab_quote_ms=%.2f parse_ms=%.3f quote_attempts=%s server_received_ts=%.3f ingestion=%s",
        tkr,
        thread_name,
        total_ms,
        (t_client1 - t_client0) * 1000.0,
        (t_sess1 - t_sess0) * 1000.0,
        (t_quote1 - t_quote0) * 1000.0,
        (t_parse1 - t_parse0) * 1000.0,
        quote_attempts,
        server_received_ts,
        quote_ingestion,
    )
    return {
        "ticker": tkr,
        "spot": float(spot_f) if spot_f is not None else None,
        "bid": float(bid) if bid is not None else None,
        "ask": float(ask) if ask is not None else None,
        "spot_disp": f"{spot_f:.2f}" if spot_f is not None else "—",
        "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
        "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
        "quote_mid": quote_mid,
        "mid_source": mid_source,
        "spread": spread_frac,
        "spread_semantic": "fraction",
        "spread_pts": spread_pts,
        "spread_source": (
            "derived_bid_ask_mid_fraction"
            if spread_frac is not None and mid_source == "derived_bid_ask_mid"
            else (
                "derived_bid_ask_fraction_schwab_mark_denom"
                if spread_frac is not None and mid_source == "schwab_quote_mark"
                else None
            )
        ),
        "spread_pts_source": ("derived_bid_ask_pts" if spread_pts is not None else None),
        "fast_generation_id": _lmp.next_fast_generation(tkr),
        "exchange_quote_ts": quote_ts,
        "quote_time_source": "schwab_rest_quote" if quote_ts is not None else "unavailable",
        "server_received_ts": server_received_ts,
        "quote_ingestion": quote_ingestion,
        "quote_source_detail": {
            "spot": spot_source or "unavailable_missing_last_and_mark",
            "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
            "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
            "mid": mid_source or "unavailable_missing_mark_and_bid_ask",
            "spread": "schwab_bid_ask" if spread_frac is not None else "unavailable_missing_bid_or_ask",
            "quote_ts": pq["quote_ts_clock"],  # M6: exchange clock carried in exchange_quote_ts
            "carried_forward": False,
        },
    }


def _fetch_fast_quote_payload(ticker: str) -> dict:
    """Fast lane: equity quote only. Authority follows order_flow_streaming.get_plane_authority_for_ticker."""
    tkr = ticker.upper().strip()
    try:
        from order_flow_streaming import get_plane_authority_for_ticker

        auth = get_plane_authority_for_ticker(tkr)
    except Exception:
        auth = "rest_only"

    prev = _lmp.get_quote(tkr)

    if auth == "streaming":
        try:
            from order_flow_streaming import streaming_l1_cache_usable
        except ImportError:
            streaming_l1_cache_usable = None  # type: ignore[misc, assignment]
        if (
            streaming_l1_cache_usable is not None
            and prev
            and prev.get("quote_ingestion") == "schwab_streaming_level_one"
            and streaming_l1_cache_usable(tkr)
        ):
            return dict(prev)
        if prev and prev.get("quote_ingestion") == "rest_bootstrap_pending_stream":
            return dict(prev)
        if prev and prev.get("quote_ingestion") == "schwab_streaming_level_one":
            return _record_rest_fast_quote_with_auth_fallback(
                tkr, prev, "rest_fallback_explicit"
            )
        return _record_rest_fast_quote_with_auth_fallback(
            tkr, prev, "rest_bootstrap_pending_stream"
        )

    if auth == "rest_fallback_explicit":
        return _record_rest_fast_quote_with_auth_fallback(
            tkr, prev, "rest_fallback_explicit"
        )

    if auth == "rest_mismatch":
        return _record_rest_fast_quote_with_auth_fallback(
            tkr, prev, "rest_ticker_not_streamed"
        )

    return _record_rest_fast_quote_with_auth_fallback(tkr, prev, "rest_fast_quote")


def _attach_money_path_snapshot_envelope(payload: dict) -> dict:
    """T4 read-only SSE envelope — nested money_path_snapshot; top-level Tier C fields unchanged."""
    out = dict(payload)
    tier_c = (
        out.get("mhap_rows") is not None
        or out.get("decision_generation_id") is not None
        or out.get("_server_build_ts") is not None
    )
    if tier_c:
        out["money_path_snapshot"] = dict(out)
        out["money_path_snapshot_kind"] = "tier_c"
    return out


async def _broadcast_snapshot(data: dict) -> None:
    """Broadcast snapshot to all connected SSE clients. Remove queues that are full."""
    try:
        payload_in = dict(data) if isinstance(data, dict) else data
        if isinstance(payload_in, dict):
            src = payload_in.get("_update_source")
            if src == "rest_poll":
                payload_in["_update_source"] = "sse_fanout_rest"
            payload_in["_sse_delivery"] = True
            payload_in = _attach_money_path_snapshot_envelope(payload_in)
        dead = []
        with _sse_lock:
            clients = list(_sse_clients)
        for q in clients:
            try:
                q.put_nowait(payload_in)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)
        if dead:
            log.debug(f"SSE: removed {len(dead)} stalled client(s)")
    except Exception as e:
        log.warning(f"SSE broadcast failed: {e}", exc_info=True)

# REST fallback: Cum Delta proxy (polling-based) when streamer unavailable.
# Accumulates per ticker, resets at open. Streamer value takes precedence.
_rest_cum_delta: dict = {}        # ticker -> running sum
_rest_cum_delta_session: Optional[str] = None  # ET date "YYYY-MM-DD"

# User prediction override — per ticker: {direction, source}
# direction: "up" | "flat" | "down", source: "user" | "manual"
_pred_overrides: dict = {}        # ticker -> {direction: str, source: str}


def _get_prediction_override(ticker: str) -> Optional[dict]:
    """Return active override for ticker, or None."""
    if not ticker:
        return None
    return _pred_overrides.get(ticker.upper(), None)

# Tick-triggered coherent refresh throttling (Issue 20/23 — no partial ms_dict patches)
_tick_coherent_lock = threading.Lock()
_last_tick_coherent_gate_mono: float = 0.0
TICK_COHERENT_GATE_SEC: float = float(os.environ.get("ED_TICK_COHERENT_GATE_SEC", "0.5"))
_last_tick_coherent_fetch_mono_by_ticker: dict[str, float] = {}
TICK_COHERENT_MIN_SEC: float = float(os.environ.get("ED_TICK_COHERENT_MIN_SEC", "0.45"))


def _latest_cached_ms_and_key_for_ticker(ticker: str) -> tuple[Optional[dict], Optional[tuple]]:
    """Newest ms_dict for this ticker across cache keys (ticker, selected_exp)."""
    t = ticker.upper().strip()
    best_md: Optional[dict] = None
    best_key: Optional[tuple] = None
    best_ts = -1.0
    for key, entry in list(_state_cache.items()):
        if key[0] != t:
            continue
        md = entry.get("ms_dict")
        if not isinstance(md, dict) or not md:
            continue
        ts = float(entry.get("ts") or 0.0)  # silent-zero-ok: epoch-0 ancient sentinel — an undated entry must never win a freshest-wins comparison
        if ts > best_ts:
            best_ts = ts
            best_md = md
            best_key = key
    return best_md, best_key


def _stream_spot_and_of_regime(symbol: str) -> tuple[Optional[float], Optional[str]]:
    """Light read from streamer + OrderFlowEngine for tick-trigger comparison only."""
    global _order_flow_engine
    stream_spot = None
    stream_regime = None
    try:
        from order_flow_live_state import get_content_for_symbol, get_top_of_book
        from order_flow_engine import OrderFlowEngine
    except ImportError:
        return None, None
    content = get_content_for_symbol(symbol)
    if not content:
        return None, None
    try:
        top = get_top_of_book(symbol)
        if isinstance(top, dict) and top.get("LAST_PRICE") is not None:
            try:
                v = float(top["LAST_PRICE"])
                if v > 0:
                    stream_spot = v
            except (TypeError, ValueError):
                pass
    except (ImportError, AttributeError, TypeError):
        pass
    if stream_spot is None:
        for item in reversed(content):
            if isinstance(item, dict) and item.get("LAST_PRICE") is not None:
                try:
                    v = float(item["LAST_PRICE"])
                    if v > 0:
                        stream_spot = v
                        break
                except (TypeError, ValueError):
                    pass
    try:
        if _order_flow_engine is None:
            _order_flow_engine = OrderFlowEngine()
        of_result = _order_flow_engine.compute({"content": content})
        stream_regime = of_result.get("order_flow_regime")
    except Exception as e:
        log.debug("stream OF regime for tick trigger %s: %s", symbol, e)
    return stream_spot, stream_regime if stream_regime is not None else None


def _on_tick_broadcast_sync(symbol: str, main_loop: asyncio.AbstractEventLoop) -> None:
    """
    Issue 20/23: do NOT broadcast partial patches (fresh spot + stale MH/Call/tier state).

    On meaningful stream change vs last coherent bundle, schedule a full _fetch_state
    and broadcast the new monotonic decision_generation_id payload.

    LIVE_OPERATOR_MODE_RESET_V1 Step 2: no longer registered as the streaming on-tick
    callback (see _app_lifespan) — _sse_background_loop is the single Tier C recompute
    owner for viewed keys. Retained for unit tests and reference.
    """
    global _last_tick_coherent_gate_mono
    try:
        sym = symbol.upper().strip()
        with _sse_lock:
            if not any(t == sym for (t, _) in _sse_subscribers.keys()):
                return

        now_m = time.monotonic()
        if now_m - _last_tick_coherent_gate_mono < TICK_COHERENT_GATE_SEC:
            return

        ms_latest, cache_key = _latest_cached_ms_and_key_for_ticker(sym)
        stream_spot, stream_regime = _stream_spot_and_of_regime(sym)
        if not tick_triggers_coherent_refresh(ms_latest or {}, stream_spot, stream_regime):
            return

        with _tick_coherent_lock:
            last_t = _last_tick_coherent_fetch_mono_by_ticker.get(sym, 0.0)
            if now_m - last_t < TICK_COHERENT_MIN_SEC:
                return
            _last_tick_coherent_fetch_mono_by_ticker[sym] = now_m
        _last_tick_coherent_gate_mono = now_m

        exp_param = cache_key[1] if cache_key else None
        ik = _tier_c_inflight_key(sym, exp_param)
        _schedule_analytics_recompute(ik, sym, exp_param, update_source="tick_coherent")
    except Exception as e:
        log.debug(f"Tick coherent refresh hook for {symbol}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# NAMED CONSTANTS — every tunable in one place.
# Nothing below should contain a raw magic number for these parameters.
# ─────────────────────────────────────────────────────────────────────────────

# Market session boundaries (Eastern, minutes-since-midnight)
# RTH_OPEN_MINS — single authority in time_et.py (STACK-WIRE-3)
RTH_CLOSE_MINS:      int   = RTH_END_MINS  # F09: alias of time_et.RTH_END_MINS, not a second close literal
PRE_MARKET_MINS:     int   = 525    # 8:45 AM ET  (logger session buffer start; widened
#   from 9:00 on 2026-08-25 for the universal by-9:30 readiness requirement — the full
#   sweep measured ~43s/ticker, so 61 enrolled tickers need ~44 min; an 08:45 start
#   finishes the first full-snapshot sweep by ~09:29 ET when the process is up)
LOGGER_BUFFER_MINS:  int   = 990    # 4:30 PM ET  (logger session buffer end)
# NOTE: session_label ("RTH"/"Pre-Market"/"After-Hours"/"Closed") is derived ONCE
# from SPY's quote in market_context._derive_session(), stored on MarketContext.session_label,
# and stamped on the per-request bundle as a global market state.
MARKET_CLOSE_HOUR:   float = RTH_END_MINS / 60.0  # F09: 16:00 ET from the one RTH-close authority

# Candle accumulator — max bars centralized in math_exposure (CANDLE_5M/1M_MAX_BARS)
# Canonical timeframe: 1m. See timeframe_config.py for CANONICAL_TIMEFRAME.
CANDLE_5M_SECONDS:   int   = 300    # 5-minute bar period (derived context)
CANDLE_1M_SECONDS:   int   = 60     # 1-minute bar period (canonical)
# Re-seed the in-memory 1m grid from Schwab pricehistory (canonical OHLCV leaf
# pricehistory.candles[]) whenever the last completed bar is older than this gap.
# Root cause (2026-06-11): seeding ran once per server lifetime, so background-logged
# tickers (visited ~1×/15min) built ~6%-density tick grids — fill_outcomes could not
# find forward bars at +1/+5/+15/+60m and the daily scoreboard never scored them.
CANDLE_RESEED_GAP_SECONDS: float = 180.0  # 3 missed canonical bars → grid is stale

# IV tracker
IV_TRACKER_MAX_READINGS: int   = 6      # readings before direction is meaningful
IV_DIRECTION_THRESHOLD:  float = 0.02   # ±2% relative change to call expanding/contracting

# VIX tracker
VIX_DIRECTION_THRESHOLD: float = 0.3   # ±0.3 pts tick-to-tick to call rising/falling

# ETF zone classification (spy_zone / qqq_zone / iwm_zone)
ETF_ZONE_THRESHOLD_PCT:  float = 0.3   # chg_pct beyond ±0.3% → bullish/bearish_trend

# Chain fetch
CHAIN_STRIKE_COUNT:  int   = 20     # strikes per expiry fetched from Schwab (live UI — keep fast)
# FIND-GAMMA-FULLCHAIN-STRIKES-V1: the wide-capture strike count is imported from
# calibration.option_chain_morning_full below — it was ALSO defined here as a literal
# ("aligned with calibration" by hand), i.e. two faucets for one constant. The import is
# the single source; ruff F811 caught the duplicate the moment both were in scope.

# Exposure windows
EXPOSURE_WINDOWS:    list  = [5, 10, 15, 20]   # window sizes passed to build_*_rows

# GEX near-spot window for breakout score
GEX_NEAR_SPOT_RADIUS: float = 2.0   # strikes within $2 of spot are "near spot"

# Void factor distance falloff
VOID_DIST_FALLOFF:   float = 5.0    # $5 from void edge → factor decays to 0

# GARCH horizon — DERIVED from the governed horizons, never a literal (RC-334).
#
# This was `13  # ~1hr RTH`, a comment that was true when BAR_MINUTES was 5 and false after
# the 2026-07-08 realignment to BAR_MINUTES=1, where 13 bars is 13 minutes. Monte Carlo only
# uses the GARCH sigmas when it receives at least `horizon_bars` of them and otherwise falls
# back to the flat IV/RV blend WITHOUT saying so, so the shortfall did not surface as an
# error — it surfaced as a different volatility model. MEASURED against
# `horizon_slug_to_mc_bars`: 1c->1 and 5c->5 were covered, while 15c->15 and 60c->60 — half
# of ALL_GOVERNED_HORIZONS — plus the 15-minute Key Levels display row never used GARCH at
# all. Sizing this from the horizon set means adding a horizon cannot silently un-GARCH it.
def _garch_horizon_bars() -> int:
    from governed_stack_contract import horizon_slug_to_mc_bars
    from ml_horizon import ALL_GOVERNED_HORIZONS

    return max(horizon_slug_to_mc_bars(s) for s in ALL_GOVERNED_HORIZONS)


GARCH_HORIZON_BARS:  int   = _garch_horizon_bars()   # 60 bars = the longest governed horizon

# IV history lookback for IV rank / percentile
IV_HISTORY_LOOKBACK: int   = 5000   # max rows pulled from DB for IV rank calc

# Parity residual minimum to display synthetic forward
PARITY_RESID_MIN:    float = 0.10   # ignore residuals smaller than 10 cents

# Accuracy history display limit
ACCURACY_HISTORY_LIMIT: int = 50    # rows returned by get_accuracy_history
RECENT_CROSSES_DISPLAY_LIMIT: int = 5  # level-cross events in operator UI
STATE_ERROR_DETAIL_MAX_CHARS: int = 120  # truncate exception detail strings for UI / log carry
PRICE_LEVELS_CACHE_SEC: int = 15  # retired as TTL (RC-416); reuse is snapshot generation
# Builds OHLC bars from spot price ticks. Server polls every ~30s, so:
#   5-min bars = ~10 ticks per bar
#   1-min bars = ~2 ticks per bar
# Bars are keyed by ticker. Completed bars stored in ring buffer; maxlen from math_exposure.
# ─────────────────────────────────────────────────────────────────────────────
from math_exposure import CANDLE_5M_MAX_BARS, CANDLE_1M_MAX_BARS
from micro_structure import Candle
from timeframe_config import CANONICAL_TIMEFRAME
# Imported at MODULE LEVEL deliberately: the terrain loop's morning-window guard depends
# on these, and a runtime import inside the loop meant a missing module silently removed
# the guard during the exact 30 minutes it protects. At top level, a broken module stops
# the server AT BOOT -- loud, immediate, and impossible to trade through unnoticed. This
# also ends the fail-open/fail-closed argument (Cursor audit 2026-07-20): the runtime
# path now has no failure mode to pick a policy for.
from calibration.option_chain_morning_full import (
    GEX_FULL_CHAIN_STRIKE_COUNT,
    # RC-161: the MORNING_* aliases are gone from this import because the scheduler no longer
    # reads them. That coupling WAS the defect — the archive's write window was steering the
    # terrain loop's contention guard. The guard now owns TERRAIN_CONTENTION_*, and the archive
    # keeps MORNING_* to itself, so neither can move the other by accident again.
    accrual_window as gex_accrual_window,
    latest_accrual_rows,
    persist_chain_accrual,
    SOURCE_WIDE as GEX_SOURCE_WIDE,
    et_date_and_mins as gex_et_date_and_mins,
    has_morning_full_capture,
    maybe_persist_morning_full_chain,
    universal_capture_window,
)

#: Timeframes to try, in order, when reading stored snapshot rows. The timeframe MUST be
#: named in any query that orders by ts_utc: the only usable index is
#: idx_snap_ticker_tf_ts (ticker, timeframe, ts_utc), and omitting the MIDDLE column makes
#: the ordering unusable, forcing a full read of every row for that ticker (MEASURED
#: 2026-07-20: >300 s vs 0.002 s). Defined beside the import it depends on; both readers
#: resolve it at call time, long after module load.
_STORED_CHAIN_TIMEFRAMES: tuple[str, ...] = (CANONICAL_TIMEFRAME, "5m")

#: RC-168: the oldest a prior totalVolume reading may be and still have its delta charged to
#: the currently open bar. Quote polls run ~1.5s apart, so a gap beyond one bar length means
#: the cumulative delta necessarily spans bars and cannot be attributed to any single minute.
ACCUM_VOL_MAX_ATTRIBUTION_GAP_SEC: float = float(
    os.environ.get("ED_ACCUM_VOL_MAX_GAP_SEC", "60")
)


class _CandleAccumulator:
    """Accumulate spot ticks into OHLCV candle bars."""

    def __init__(self, bar_seconds: int, max_bars: int):
        self.bar_seconds = bar_seconds
        self.max_bars = max_bars
        self._bars: dict[str, list[Candle]] = {}       # ticker -> completed bars
        self._current: dict[str, dict] = {}             # ticker -> {ts, o, h, l, c, v}
        self._prev_total_vol: dict[str, float] = {}    # ticker -> prior totalVolume for delta
        # RC-168: WHEN that prior reading was taken. Without it a cumulative delta spanning
        # minutes was attributed to one bar (see tick()).
        self._prev_total_vol_ts: dict[str, float] = {}
        self._bars_source: dict[str, str] = {}         # ticker -> provenance for VWAP path

    def _bar_start(self, epoch: float) -> float:
        """Round epoch down to bar boundary."""
        return epoch - (epoch % self.bar_seconds)

    def tick(self, ticker: str, price: float, ts: float, total_volume: float | None = None):
        """Feed a new price tick. Automatically closes/opens bars at boundaries.
        total_volume: totalVolume from Schwab quote. Delta vs prior reading is
        accumulated per bar; captures all trades between polls.
        """
        bar_ts = self._bar_start(ts)
        total_now = float(total_volume) if total_volume is not None else None
        prev = self._prev_total_vol.get(ticker)
        prev_ts = self._prev_total_vol_ts.get(ticker)
        vol_source = "schwab_quote_totalVolume_delta"

        # Compute volume delta; reset if value drops (new session)
        if total_now is not None and prev is not None:
            # RC-168 ROOT: totalVolume is CUMULATIVE, so `total_now - prev` covers the whole
            # span between the two readings — not the current minute. The prior reading had no
            # staleness bound, so whenever a ticker went unpolled for minutes (42-symbol
            # rotation, a stalled poll, a mid-session restart) the entire multi-minute delta
            # was attributed to whichever ONE bar happened to be open, producing the spikes
            # this row was opened for. MEASURED on MSFT: the accumulator produced 601
            # non-auction 10x-neighbourhood spikes in 24,284 bars (2.5%) while the vendor's own
            # 1m bars over the same name and period produced 8 in 13,017 (0.06%) — a 40x rate
            # from the same market, which isolates the attribution, not the feed. Past the
            # bound the span is unknowable, so the bar records NO volume rather than a
            # fabricated minute (absence over invention).
            gap = None if prev_ts is None else (ts - float(prev_ts))
            delta = total_now - prev
            if gap is not None and gap > ACCUM_VOL_MAX_ATTRIBUTION_GAP_SEC:
                vol_delta = None
                vol_source = "schwab_quote_totalVolume_gap_unattributable"
            elif delta >= 0:
                vol_delta = delta
            else:
                vol_delta = 0.0
                prev = None
                vol_source = "schwab_quote_totalVolume_session_reset"
        else:
            vol_delta = None
        if total_now is not None:
            self._prev_total_vol[ticker] = total_now
            self._prev_total_vol_ts[ticker] = ts
        if ticker not in self._bars_source or self._bars_source[ticker] != "schwab_pricehistory":
            self._bars_source[ticker] = vol_source

        if ticker not in self._bars:
            self._bars[ticker] = []

        cur = self._current.get(ticker)

        if cur is None or cur["ts"] != bar_ts:
            # Close previous bar (if any)
            if cur is not None:
                completed = Candle(
                    ts=cur["ts"], open=cur["o"], high=cur["h"],
                    low=cur["l"], close=cur["c"],
                    volume=cur.get("v")
                )
                self._bars[ticker].append(completed)
                if len(self._bars[ticker]) > self.max_bars:
                    self._bars[ticker] = self._bars[ticker][-self.max_bars:]

            # Start new bar (reset volume tracker for fresh delta on next tick)
            self._current[ticker] = {
                "ts": bar_ts,
                "o": price,
                "h": price,
                "l": price,
                "c": price,
                "v": vol_delta,
                "volume_source": vol_source,
            }
        else:
            # Update current bar
            cur["h"] = max(cur["h"], price)
            cur["l"] = min(cur["l"], price)
            cur["c"] = price
            if vol_delta is not None:
                cur["v"] = (cur.get("v") or 0.0) + vol_delta  # silent-zero-ok: RC-168/RC-277 — totalVolume is CUMULATIVE, so a bar's FIRST reading has no predecessor and vol_delta is None BY CONSTRUCTION; None means "no delta counted yet", not a missing measurement, and 0.0 is the correct identity to open the sum
            cur["volume_source"] = vol_source

    def get_bars(self, ticker: str) -> list[Candle]:
        """Return completed bars (not including the in-progress bar)."""
        return list(self._bars.get(ticker, []))

    def get_bars_source(self, ticker: str) -> str:
        """Provenance label for bars produced by this accumulator (VWAP / analytics)."""
        return self._bars_source.get(ticker, "schwab_quote_totalVolume_delta")

    def seed(self, ticker: str, bars: list):
        """Seed completed bars from price history. Overwrites existing bars for this ticker."""
        if not bars:
            return
        candles = []
        for b in bars:
            if isinstance(b, Candle):
                candles.append(b)
            elif isinstance(b, dict):
                try:
                    dt_raw = b.get("datetime")
                    if dt_raw is None:
                        continue
                    dt_f = float(dt_raw)
                    if dt_f <= 0:
                        continue
                    ts = dt_f / 1000.0 if dt_f > 1e10 else dt_f
                    candles.append(Candle(
                        ts=ts,
                        open=float(b["open"]),
                        high=float(b["high"]),
                        low=float(b["low"]),
                        close=float(b["close"]),
                        volume=float(b["volume"]),
                    ))
                except (KeyError, ValueError, TypeError):
                    continue
        if candles:
            # BAR_PERSISTENCE_GAP_TRACE_AND_FIX_V1 (2026-07-06): stale-seed guard —
            # never replace a strictly NEWER completed-bar grid with an older
            # pricehistory payload. A two-session-stale Schwab response erased
            # tick-built same-day bars on every reseed, so price_bars_1m gained
            # zero rows for the day. Equal-or-newer payloads still refresh
            # (pricehistory OHLCV beats sparse tick-built bars for the same span).
            existing = self._bars.get(ticker)
            if existing and float(existing[-1].ts) > float(candles[-1].ts):
                log.info(
                    "seed_stale_ignored ticker=%s seed_last_ts=%.0f existing_last_ts=%.0f",
                    ticker,
                    float(candles[-1].ts),
                    float(existing[-1].ts),
                )
                return
            self._bars[ticker] = candles[-self.max_bars:]
            self._bars_source[ticker] = "schwab_pricehistory"
            # Set current bar from last candle so ticks extend properly
            last = candles[-1]
            self._current[ticker] = {
                "ts": self._bar_start(last.ts),
                "o": last.open, "h": last.high, "l": last.low, "c": last.close,
            }

    def grid_stale(self, ticker: str, ts: float, gap_seconds: float) -> bool:
        """True when the completed-bar grid is missing or has a gap vs ``ts``.

        A stale grid means tick-built bars cannot represent the session (sparse
        polling) and the canonical Schwab pricehistory leaf must re-seed it.
        """
        bars = self._bars.get(ticker)
        if not bars:
            return True
        last_bar_end = float(bars[-1].ts) + float(self.bar_seconds)
        return (float(ts) - last_bar_end) > float(gap_seconds)

    def has_bars(self, ticker: str) -> bool:
        """Return True if ticker has any completed bars."""
        return len(self._bars.get(ticker, [])) >= 1


_candles_5m = _CandleAccumulator(bar_seconds=CANDLE_5M_SECONDS, max_bars=CANDLE_5M_MAX_BARS)
_candles_1m = _CandleAccumulator(bar_seconds=CANDLE_1M_SECONDS, max_bars=CANDLE_1M_MAX_BARS)


# ── IV Direction Tracker ─────────────────────────────────────────────────────
# Stores recent ATM IV readings per ticker. Compares latest to rolling avg
# to derive expanding/contracting/flat. Used by vanna context.
class _IVTracker:
    """Track ATM IV direction per ticker from last N readings."""
    def __init__(self, max_readings: int = IV_TRACKER_MAX_READINGS):
        self._max = max_readings
        self._data: Dict[str, list] = {}  # ticker → [iv1, iv2, ...]

    def tick(self, ticker: str, iv: float | None):
        if iv is None or iv <= 0:
            return
        buf = self._data.setdefault(ticker, [])
        buf.append(float(iv))
        if len(buf) > self._max:
            buf.pop(0)

    def direction(self, ticker: str) -> str:
        """Returns 'expanding', 'contracting', or 'flat'.

        Compares latest IV to average of prior readings.
        Threshold: ±2% relative change (e.g., IV 20→20.4 = expanding).
        """
        buf = self._data.get(ticker, [])
        if len(buf) < 3:
            return "flat"  # not enough data
        latest = buf[-1]
        prior_avg = sum(buf[:-1]) / len(buf[:-1])
        if prior_avg <= 0:
            return "flat"
        pct_chg = (latest - prior_avg) / prior_avg
        if pct_chg > IV_DIRECTION_THRESHOLD:
            return "expanding"
        elif pct_chg < -IV_DIRECTION_THRESHOLD:
            return "contracting"
        return "flat"

_iv_tracker = _IVTracker()


class _VIXTracker:
    """Track VIX direction across refreshes."""
    def __init__(self):
        self._prev: float | None = None
        self._direction: str = "flat"

    def tick(self, vix_now: float | None):
        if vix_now is None or vix_now <= 0:
            return
        if self._prev is not None and self._prev > 0:
            diff = vix_now - self._prev
            if diff > VIX_DIRECTION_THRESHOLD:
                self._direction = "rising"
            elif diff < -VIX_DIRECTION_THRESHOLD:
                self._direction = "falling"
            else:
                self._direction = "flat"
        self._prev = vix_now

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def vs_prev(self) -> float | None:
        return None  # filled from market_context vix_vs_prev if available


_vix_tracker = _VIXTracker()


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND MULTI-TICKER LOGGER
# ─────────────────────────────────────────────────────────────────────────────
# Core tickers always logged regardless of what the UI is showing.
# Additional tickers are added automatically when the user views them.
# The logger runs every LOG_INTERVAL seconds, cycling through all tracked
# tickers with a STAGGER_SECS delay between each to avoid rate-limit bursts.
#
# Base money-path tickers (SPY/QQQ/IWM) require equal RTH capture — not guest-style sparsity.
#   • Dedicated ``_base_money_path_logger_loop`` sustains ~1 lightweight quote snapshot/min
#     per base symbol via concurrent capture (logger_source=base_money_path), independent
#     of which ticker is active in the UI (see money_path_ticker_tiers.py).
#   • ED_DB_SNAPSHOT_THROTTLE (default on): at most one INSERT per ticker per UTC-minute bucket.
#   • The general logger still rotates mega-caps + user_persisted; cycle length grows with count.
#   • RTH_ONLY may skip background fetches outside the ET session window.
#   • UNIVERSAL COLLECTION IS UNCONDITIONAL (operator, 2026-08-25, RC-493): the background
#     logger sweeps EVERY enrolled ticker every cycle whether or not a viewer is connected.
#     The former operator-mode throttle (trio + one rotating guest while viewing) is removed;
#     _live_operator_mode_active now governs only UI-side refresh skips, never the sweep.
#   • Guest / briefly viewed symbols legitimately have fewer rows — base trio must not.
#     Gate: ``python tools/check_base_ticker_observability.py --date YYYY-MM-DD``.
#
# Schwab rate limits: ~120 requests/min. Each ticker needs 2 calls (quote +
# chain). 5 core tickers = 10 calls per 30s cycle = well within limits.
# ─────────────────────────────────────────────────────────────────────────────

# ── Core tickers: always logged, always building prediction databases ─────────
# Index ETFs + top SPY constituents. These are the same tickers already quoted
# every cycle by market_context.py for the cross-instrument panel — but those
# calls only fetch a spot quote. The background logger runs the FULL pipeline
# (quote + chain + exposures + snapshot) so they accumulate prediction data.
CORE_TICKERS:   list[str] = [
    "SPY", "QQQ", "IWM",                              # index ETFs
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA",  # mega-caps
    "GOOGL", "AVGO",                                   # mega-caps
]
LOG_INTERVAL:   int       = 30    # seconds — 12 tickers × 3 calls + 17 global ≈ 106/min
STAGGER_SECS:   float     = 2.0  # seconds between each ticker fetch in a cycle
LOGGER_STARTUP_DELAY_SEC: float = float(os.environ.get("ED_LOGGER_STARTUP_DELAY_SEC", "60"))
RTH_ONLY:       bool      = True  # only log during RTH + 30min pre/post buffer

# Issue 22 — persistent universe for non-core symbols (see logging_universe in EdDB).
# Default: no FIFO eviction — symbols selected in the app stay enrolled until explicitly removed.
# Opt-in legacy cap: set ED_LOGGING_UNIVERSE_FIFO_EVICTION=1 and ED_MAX_USER_PERSISTED_LOGGING_TICKERS=N (>=1).
MAX_USER_PERSISTED_LOGGING_TICKERS: int | None = None  # None = unlimited (no eviction)
MAX_PINNED_LOGGING_TICKERS: int = 24


def _market_context_panel_auto_candidates() -> list[str]:
    """Symbols quoted every ``fetch_market_context`` cycle (excluding ``CORE_TICKERS`` duplicates)."""
    core_u = frozenset((c or "").upper().strip() for c in CORE_TICKERS)
    return market_context_panel_symbols_excluding_core(core_u)


def _sync_market_context_panel_into_logging_universe(db, now_ts: float) -> None:
    """Persist cross-panel quote universe into ``logging_universe`` as ``panel_auto`` (data-plane SSOT)."""
    try:
        r = db.logging_universe_sync_panel_auto(_market_context_panel_auto_candidates(), now_ts)
        if r.get("desired"):
            log.info(
                "Issue 22: panel_auto sync — desired=%s upsert_round=%s",
                r.get("desired"),
                r.get("upserted"),
            )
    except Exception as e:
        log.warning("logging_universe panel_auto sync failed: %s", e)


def _logging_universe_fifo_eviction_enabled() -> bool:
    return os.environ.get("ED_LOGGING_UNIVERSE_FIFO_EVICTION", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _max_user_persisted_cap_resolved() -> int | None:
    """Effective cap when FIFO eviction is enabled; None = unlimited."""
    raw = os.environ.get("ED_MAX_USER_PERSISTED_LOGGING_TICKERS", "").strip()
    if raw:
        try:
            n = int(raw)
            return n if n > 0 else None
        except ValueError:
            return None
    v = MAX_USER_PERSISTED_LOGGING_TICKERS
    if isinstance(v, int) and v > 0:
        return v
    return None


def _user_persisted_enrollment_policy() -> dict:
    cap = _max_user_persisted_cap_resolved()
    fifo = _logging_universe_fifo_eviction_enabled()
    return {
        "fifo_eviction_enabled": fifo,
        "max_user_persisted_cap": cap,
        "unlimited_user_persisted": cap is None or not fifo,
    }

# ── Legacy flat JSON (pre–Issue 22). Migrated idempotently via EdDB (migration_log + transaction).
_TICKER_FILE = os.path.join(os.path.dirname(__file__), ".logger_tickers.json")
_TICKER_ARCHIVE = _TICKER_FILE + ".migrated_issue22"

# DB-WRITE-PATH-FIXES (d), 2026-05-31: import-time-defer guard. Counts how many times the
# HEAVY DB-backed logging-universe load (migrations / sync_core / prune / panel-sync) has run.
# The module-import path must NOT trigger it (that work belongs in the FastAPI lifespan); the
# paired test asserts this counter is 0 immediately after `import server`.
_LOGGING_UNIVERSE_DB_LOAD_COUNT = 0


def _run_legacy_logger_json_migration(db) -> None:
    """Delegate to EdDB hardened migration (provably one-time, transactional)."""
    try:
        from pathlib import Path

        r = db.logging_universe_migrate_legacy_json_file(
            primary_path=Path(_TICKER_FILE),
            archive_path=Path(_TICKER_ARCHIVE),
            core_tickers=list(CORE_TICKERS),
        )
        if r.get("status") not in ("already_completed", "skipped_no_source"):
            log.info("Issue 22 legacy logger json migration: %s", r)
    except Exception as e:
        log.warning("legacy logger json migration: %s", e)


def _load_persisted_tickers() -> list[str]:
    """Authoritative enrolled universe: CORE_TICKERS + logging_universe (pinned + user_persisted + panel_auto).

    ``panel_auto`` rows mirror ``market_context.py`` cross-panel quote symbols (excluding core
    duplicates). UNIVERSAL COLLECTION (operator, 2026-08-25): the category records HOW a ticker
    was enrolled, never how much data it gets — panel_auto rows take full snapshot rotation on
    the same terms as every other enrolled ticker (the old confluence-only carve-out is RC-482).

    Distinct tickers appearing only in snapshots / normalized tables do not auto-enroll (Issue 22).
    ml_scheduler and train_all bulk paths use the same EdDB authority via scheduler_user_tickers.
    """
    tickers = list(CORE_TICKERS)
    if not _HAS_SIGNALS:
        try:
            with open(_TICKER_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, list):
                for t in saved:
                    t = str(t).upper().strip()
                    if t and t not in tickers:
                        tickers.append(t)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("fallback load .logger_tickers.json: %s", e)
        return tickers
    try:
        global _LOGGING_UNIVERSE_DB_LOAD_COUNT
        _LOGGING_UNIVERSE_DB_LOAD_COUNT += 1
        db = get_db()
        logging_universe_sync_wall_ts = time.time()
        _run_legacy_logger_json_migration(db)
        db.logging_universe_sync_core(CORE_TICKERS, logging_universe_sync_wall_ts)
        try:
            removed = db.logging_universe_prune_invalid_enrollments()
            if removed:
                log.warning("Issue 22: pruned invalid logging_universe enrollments: %s", removed)
        except Exception as e:
            log.warning("Issue 22: logging_universe prune failed: %s", e)
        _sync_market_context_panel_into_logging_universe(db, logging_universe_sync_wall_ts)
        for row in db.logging_universe_list_rows():
            # UNIVERSAL COLLECTION (RC-482/RC-483, 2026-08-25): panel_auto is in the roster.
            # Neutering filter_tickers_for_background_logging was necessary but NOT sufficient
            # — this construction loop was the real gate; it silently dropped every panel_auto
            # ticker (all 17 dark since 2026-05-27) while the docstring claimed full rotation.
            if row.get("category") in ("user_persisted", "pinned", "panel_auto"):
                t = ticker_storage_key(row.get("ticker"))  # RC-345/F25: canonical enrolled-ticker identity
                if t and t not in tickers:
                    tickers.append(t)
        try:
            from scheduler_user_tickers import filter_tickers_for_background_logging

            tickers = filter_tickers_for_background_logging(tickers, str(db.db_path))
        except Exception as e:
            log.warning("filter_tickers_for_background_logging: %s", e)
        log.info("Issue 22: loaded logging universe from DB — %d symbols", len(tickers))
        return tickers
    except Exception as e:
        log.warning("logging universe DB load failed, using core + JSON fallback: %s", e)
        try:
            with open(_TICKER_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, list):
                for t in saved:
                    t = str(t).upper().strip()
                    if t and t not in tickers:
                        tickers.append(t)
        except FileNotFoundError:
            pass
        except Exception as e2:
            log.warning("JSON fallback failed: %s", e2)
        return tickers


def _hydrate_logger_tickers_from_db() -> None:
    """Re-merge CORE + user_persisted + pinned + panel_auto from DB (startup / heal drift).
    Issue 22; panel_auto added 2026-08-25 for universal collection (RC-482/RC-483)."""
    global _logger_tickers, _LOGGING_UNIVERSE_DB_LOAD_COUNT
    if not _HAS_SIGNALS:
        return
    try:
        _LOGGING_UNIVERSE_DB_LOAD_COUNT += 1
        db = get_db()
        logging_universe_sync_wall_ts = time.time()
        _run_legacy_logger_json_migration(db)
        db.logging_universe_sync_core(CORE_TICKERS, logging_universe_sync_wall_ts)
        try:
            removed = db.logging_universe_prune_invalid_enrollments()
            if removed:
                log.warning("Issue 22: pruned invalid logging_universe enrollments: %s", removed)
        except Exception as e:
            log.warning("Issue 22: logging_universe prune failed: %s", e)
        _sync_market_context_panel_into_logging_universe(db, logging_universe_sync_wall_ts)
        merged = [ticker_storage_key(t) for t in CORE_TICKERS]  # RC-345/F25: canonical logger hydration
        for row in db.logging_universe_list_rows():
            # UNIVERSAL COLLECTION (RC-482/RC-483): panel_auto joins the roster here too.
            if row.get("category") in ("user_persisted", "pinned", "panel_auto"):
                t = ticker_storage_key(row.get("ticker"))  # RC-345/F25: canonical (legacy bare rows resolve on-read)
                if t and t not in merged:
                    merged.append(t)
        try:
            from scheduler_user_tickers import filter_tickers_for_background_logging

            merged = filter_tickers_for_background_logging(merged, str(db.db_path))
        except Exception as e:
            log.warning("filter_tickers_for_background_logging: %s", e)
        with _logger_lock:
            _logger_tickers = merged
    except Exception as e:
        log.warning("hydrate logger tickers from DB: %s", e)

# DB-WRITE-PATH-FIXES (d), 2026-05-31: do NOT run the heavy DB-backed logging-universe load
# (migrations / sync_core / prune / panel-sync) on the module-import path. That work raced the
# retrain write-lock and produced the slow init + the "db load failed" warning that dropped
# pinned tickers. When signals/db are available, import-time init is core-only; the authoritative
# universe is loaded in the FastAPI lifespan via start_logger() -> _hydrate_logger_tickers_from_db()
# (server.py:_app_lifespan). The cheap JSON-file fallback (no DB) is retained for the degraded
# no-signals path so its behavior is unchanged.
_logger_tickers:  list[str] = list(CORE_TICKERS) if _HAS_SIGNALS else _load_persisted_tickers()
_logger_stats:    dict      = {}  # ticker -> {last_logged, count, last_error}
_accuracy_cache:  dict      = {}  # ticker -> {ts, results}
ACCURACY_INTERVAL: int      = 600  # seconds between accuracy computations (~10 min)
_logger_running:  bool      = False
_logger_thread:   threading.Thread | None = None
_logger_lock:     threading.Lock   = threading.Lock()

# ── Global market context cache ───────────────────────────────────────────────
# VIX, SPY/QQQ/IWM quotes, 9 SPY constituents, 4 IWM sectors = 17 API calls.
# This data is IDENTICAL regardless of which ticker we're processing.
# Cache it once per cycle instead of re-fetching per ticker.
_cached_mkt_ctx       = None     # MarketContext object
_cached_mkt_ctx_ts    = 0.0      # epoch when last fetched
_cached_mkt_ctx_lock  = threading.Lock()
MKT_CTX_TTL           = 25.0     # seconds — refresh once per cycle (LOG_INTERVAL=30s)
# UI_05 tail closure (2026-07-10 EVE, measured @ f478208 trials): when the TTL
# lapsed, EVERY concurrent recompute independently ran the 17-call sweep inline
# (no single-flight on the fetch — the lock only guarded check + store), putting
# 8.3-10.5s inside the cold-switch chain window at pure chain <=1.8s and gate
# wait 0. Refresh is now single-flight and stale-while-refresh: one background
# sweep at a time; callers holding a previous context are served immediately.
_mkt_ctx_refresh_inflight = False   # guarded by _cached_mkt_ctx_lock
_mkt_ctx_refresh_cond = threading.Condition(_cached_mkt_ctx_lock)
MKT_CTX_SYNC_JOIN_TIMEOUT_SEC = 30.0   # boot/force_sync bounded join on an in-flight sweep


def _is_loggable_session() -> bool:
    """
    Background snapshot logging session gate (Issue 22 — explicit product policy).

    When RTH_ONLY is True (default): allow ET minutes in [PRE_MARKET_MINS, LOGGER_BUFFER_MINS]
    (see server.py constants — 08:45 pre through extended post-market buffer; the pre-market
    edge widened from 09:00 on 2026-08-25 so the whole enrolled roster is swept by the
    operator's 09:30 readiness bar, RC-482) AND only on a
    capturable trading calendar day. RC-48: the minute-window alone was weekday/holiday-blind,
    so weekend daytime leaked base-logger rows; AND-ing the one calendar authority
    (time_et.is_capturable_session) closes that leak without changing the window.

    When RTH_ONLY is False: no session gate here (logging may run when markets are quiet —
    use only for diagnostics).
    """
    if not RTH_ONLY:
        return True
    if not is_capturable_session():   # RC-48: weekend / full holiday / overnight -> never loggable
        return False
    et = now_et()
    mins = et.hour * 60 + et.minute
    return PRE_MARKET_MINS <= mins <= LOGGER_BUFFER_MINS


def _enrollment_collectability_probe(ticker: str) -> tuple[bool, str]:
    """Cursor-audit F5: prove a symbol can actually PRODUCE a snapshot before enrolling it.

    A snapshot requires BOTH a quote (200) and an option chain (200 with >=1 contract), so a
    symbol with no options ($TNX, a yield index) or one the vendor refuses (SATS, 404) can never
    collect. Enrollment previously validated only string SHAPE (is_valid_production_ticker), which
    conflates "plausible symbol" with "will produce a snapshot" — the exact "visibility is not
    sufficiency" gap that admitted permanent non-collectors. Returns (ok, reason). Bounded: one
    quote plus one index-budget-safe gated chain fetch, both through the standard faucets. This
    is a live one-shot probe: a transient vendor blip rejects the add (the user can retry), which
    is the safe direction — never admit an un-provable non-collector."""
    tk = ticker_storage_key(ticker)
    try:
        client = get_client()
        q = _memoized_quote_response(tk, client=client)
        if q is None or getattr(q, "status_code", None) != 200:
            return False, f"quote unavailable (vendor status {getattr(q, 'status_code', None)})"
        c, _gw, _fs = _gated_safe_get_chain(
            client, tk, strike_count=resolve_chain_strike_count(tk),
            to_date=_chain_to_date_for(tk, None), from_date=_chain_from_date_for(tk, None),
        )
        if c is None or getattr(c, "status_code", None) != 200:
            return False, f"no option chain (vendor status {getattr(c, 'status_code', None)})"
        if not flatten_chain_contracts(c.json()):
            return False, "option chain returned zero contracts"
        return True, "ok"
    except Exception as e:
        return False, f"probe error: {type(e).__name__}: {e}"


def _add_logger_ticker(ticker: str, *, enrollment_source: str = "ui_auto") -> bool:
    """
    Add a symbol to the in-memory logger cycle and durable logging_universe (Issue 22).
    Returns True if newly appended to _logger_tickers.

    Cursor-audit F5: a NEW enrollment must first PROVE it can collect (quote + chain) via
    _enrollment_collectability_probe. Already-enrolled re-adds short-circuit before the probe;
    core tickers are exempt (always collectable — never gate the spine on a transient blip).
    """
    from production_universe import is_valid_production_ticker, normalize_production_ticker

    ticker = normalize_production_ticker(ticker)
    if not ticker or len(ticker) > 10:
        return False
    if not is_valid_production_ticker(ticker):
        log.warning("Background logger: refusing invalid ticker %r", ticker)
        return False
    enrollment_touch_wall_ts = time.time()
    with _logger_lock:
        if ticker in _logger_tickers:
            if _HAS_SIGNALS:
                try:
                    get_db().logging_universe_touch_seen(ticker, enrollment_touch_wall_ts)
                except Exception as e:
                    log.debug(
                        "logging_universe_touch_seen failed ticker=%s: %s",
                        ticker,
                        e,
                        exc_info=True,
                    )
            return False
    # Cursor-audit F5: a genuinely NEW enrollment must prove collectability before it is committed
    # (durable upsert + in-memory append + any FIFO eviction). Core tickers are exempt.
    if ticker not in CORE_TICKERS:
        _probe_ok, _probe_why = _enrollment_collectability_probe(ticker)
        if not _probe_ok:
            log.warning("Background logger: refusing %s — cannot collect a snapshot: %s",
                        ticker, _probe_why)
            return False
    if _HAS_SIGNALS and ticker not in CORE_TICKERS:
        try:
            db = get_db()
            cap = _max_user_persisted_cap_resolved()
            fifo_on = _logging_universe_fifo_eviction_enabled()
            while fifo_on and cap is not None and db.logging_universe_user_persisted_count() >= cap:
                fifo = db.logging_universe_eviction_candidates_fifo()
                victim = db.logging_universe_oldest_user_persisted_ticker()
                if not victim or not fifo or victim != fifo[0]:
                    log.error(
                        "Issue 22: eviction aborted — FIFO mismatch (victim=%s fifo_head=%s)",
                        victim,
                        fifo[:1] if fifo else None,
                    )
                    break
                prot = set(db.logging_universe_protected_tickers())
                if victim in prot:
                    log.error(
                        "Issue 22: eviction aborted — %s is protected (core/pinned)",
                        victim,
                    )
                    break
                db.logging_universe_record_eviction(
                    evicted_ticker=victim,
                    evicted_ts_utc=enrollment_touch_wall_ts,
                    reason="user_persisted_cap_fifo",
                    cap_limit=cap,
                    incoming_ticker=ticker,
                    incoming_enrollment_source=enrollment_source,
                )
                if not db.logging_universe_remove_user_persisted(victim):
                    log.error("Issue 22: eviction failed to delete user_persisted %s", victim)
                    break
                with _logger_lock:
                    if victim in _logger_tickers:
                        _logger_tickers.remove(victim)
                log.info(
                    "Issue 22 hardened: evicted user_persisted %s (cap=%s, incoming=%s reason=user_persisted_cap_fifo)",
                    victim,
                    cap,
                    ticker,
                )
            db.logging_universe_upsert_user_persisted(
                ticker, enrollment_source, enrollment_touch_wall_ts
            )
        except ValueError as e:
            log.warning("logging_universe upsert rejected: %s", e)
        except Exception as e:
            log.warning("logging_universe upsert failed: %s", e)
    with _logger_lock:
        if ticker not in _logger_tickers:
            _logger_tickers.append(ticker)
            log.info(
                "Background logger: added %s (total %d) — durable enrollment",
                ticker,
                len(_logger_tickers),
            )
            # RC-484 (operator requirement, 2026-08-25): a fresh enrollment immediately
            # acquires its available history — one bounded vendor call, off-thread so
            # the add itself stays instant. Boot rehydration bypasses this function, so
            # the seed fires only for genuinely NEW enrollments.
            threading.Thread(
                target=_enrollment_history_seed, args=(ticker,), daemon=True,
                name=f"enroll-seed-{ticker}",
            ).start()
            return True
    return False


def _enrollment_history_seed(ticker: str) -> None:
    """RC-484 (operator requirement 2026-08-25): a newly enrolled ticker immediately
    acquires its available 1m history — today's tape so the chart is not blank from the
    enrollment minute, and the prior trading session so PDH/PDL/PDC/POC/VAH/VAL and the
    overnight window are computable on day 1. One bounded vendor call (period_days=2)
    upserted into the ONE banked bar table (price_bars_1m) — this feeds the existing
    single bar input resolved by _canonical_price_level_bars, so the Phase 2A
    single-faucet invariant is preserved: history acquisition, never a second level
    producer. The source stays the standard price-history token (the bytes ARE Schwab
    price history; a new source value would silently widen the classification
    namespace — the RC-31 classification-by-complement class)."""
    try:
        from schwab_client import safe_get_price_history

        client = get_client()
        resp = safe_get_price_history(client, ticker, frequency_minutes=1, period_days=2)
        status = getattr(resp, "status_code", None)
        if resp is None or status != 200:
            log.warning("enrollment seed: price history unavailable for %s (status=%s)",
                        ticker, status)
            return
        candles = (resp.json() or {}).get("candles") or []
        if not candles:
            log.warning("enrollment seed: empty candle payload for %s", ticker)
            return
        n = _persist_1m_bars(ticker, candles)
        log.info("enrollment seed: %s banked %d 1m bars (period_days=2)", ticker, n)
    except Exception as e:
        log.warning("enrollment seed failed for %s: %s", ticker, e)


def _register_tracked_ticker(ticker: str, *, enrollment_source: str = "ui_auto") -> bool:
    """
    Enroll a user-facing symbol: background logger + ml_scheduler user-ticker file.
    Issue 22: user symbols persist in EdDB.logging_universe (survives restarts).
    Returns True if newly added to the logger rotation list.
    """
    t = ticker_storage_key(ticker)  # RC-345/F25: in-memory logger identity == canonical DB enrollment identity
    if not t or len(t) > 10:
        return False
    added = _add_logger_ticker(t, enrollment_source=enrollment_source)
    try:
        from scheduler_user_tickers import record_user_ticker

        record_user_ticker(t)
    except Exception as e:
        log.debug("record_user_ticker failed ticker=%s: %s", t, e, exc_info=True)
    return added


def _touch_tracked_ticker_view(ticker: str) -> None:
    """VIEW-path last-seen touch — TICKER-PREVIEW-NO-ENROLL (operator 2026-05-31).

    Merely looking up / viewing levels, quotes, or analytics for an arbitrary symbol must NOT
    enroll it (no ``logging_universe`` row, no scheduler user-ticker file write) — enrollment
    into the training roster is reserved for explicit track/pin actions (``/api/logger/add``,
    ``/api/logger/pin``). For an ALREADY-enrolled ticker this refreshes ``last_seen`` (the same
    update the old ``_register_tracked_ticker`` early-return branch did); for an un-enrolled
    ticker it is a no-op and never writes. Safe to call from the offloaded SSE/async paths.
    """
    if not _HAS_SIGNALS:
        return
    t = (ticker or "").upper().strip()
    if not t or len(t) > 10:
        return
    with _logger_lock:
        enrolled = t in _logger_tickers
    if not enrolled:
        return
    try:
        get_db().logging_universe_touch_seen(t, time.time())
    except Exception as e:
        log.debug("view touch_seen failed ticker=%s: %s", t, e, exc_info=True)


def _fetch_and_store_mkt_ctx(client, pcr=None, prev_pcr=None):
    """One full market-context sweep (17 Schwab quote calls) + cache store +
    confluence-tick persist. Extracted verbatim from the pre-2026-07-10 body
    of _get_mkt_ctx; call ONLY under the single-flight discipline in
    _get_mkt_ctx / _mkt_ctx_background_refresh.

    Schwab CSV authority checked: yes
    CSV row(s): quotes.$VIX.*, quotes.SPY.*, quotes.QQQ.*, quotes.IWM.* and
      panel constituents via fetch_market_context (unchanged call shape).
    Derived-field disposition: none required — sweep body byte-identical.
    All consumers checked: yes — same MarketContext object stored/returned.
    SCHWAB_CSV_CHECKED"""
    global _cached_mkt_ctx, _cached_mkt_ctx_ts
    mkt_ctx_fetch_started_wall_ts = time.time()
    _stream_chg_fn = None
    try:
        from order_flow_live_state import get_stream_chg_pct
        _stream_chg_fn = get_stream_chg_pct
    except (ImportError, AttributeError):
        pass
    try:
        ctx = fetch_market_context(
            client,
            # RC-112 recurrence 2: this kwarg handed the RAW vendor fetch by reference into
            # market-context (VIX/TICK quote legs) — invisible to a call-syntax scan. The
            # adapter keeps the (client, ticker) signature the callee expects while routing
            # every quote it makes through the one memoized vendor faucet.
            safe_get_quote_fn=lambda _c, _tk, **_kw: _memoized_quote_response(
                _tk, client=_c, **_kw),
            pcr=pcr,
            prev_pcr=prev_pcr,
            stream_chg_pct_fn=_stream_chg_fn,
        )
        if ctx.error:
            log.warning(f"fetch_market_context returned error: {ctx.error}")
    except Exception as e:
        log.warning(f"fetch_market_context failed: {e}")
        from market_context import MarketContext
        ctx = MarketContext()
    with _cached_mkt_ctx_lock:
        _cached_mkt_ctx = ctx
        _cached_mkt_ctx_ts = mkt_ctx_fetch_started_wall_ts
    if _HAS_SIGNALS:
        try:
            from db import build_ts_et
            from market_context import confluence_quote_rows_from_context
            from time_et import now_et

            _qrows = confluence_quote_rows_from_context(
                ctx,
                ts_utc=mkt_ctx_fetch_started_wall_ts,
                ts_et=build_ts_et(now_et()),
            )
            if _qrows:
                get_db().upsert_confluence_quote_ticks(_qrows)
        except Exception as e:
            log.debug("confluence_quote_ticks persist: %s", e, exc_info=True)
    return ctx


def _mkt_ctx_background_refresh(client, pcr=None, prev_pcr=None):
    """Single-flight worker body for the stale-while-refresh path."""
    global _mkt_ctx_refresh_inflight
    try:
        _fetch_and_store_mkt_ctx(client, pcr=pcr, prev_pcr=prev_pcr)
    except Exception as e:
        # _fetch_and_store_mkt_ctx is internally fail-soft; this guard only
        # protects the inflight flag from an unexpected escape (never silent).
        log.warning("mkt_ctx background refresh failed: %s", e, exc_info=True)
    finally:
        with _cached_mkt_ctx_lock:
            _mkt_ctx_refresh_inflight = False
            _mkt_ctx_refresh_cond.notify_all()


def _get_mkt_ctx(client, pcr=None, prev_pcr=None, *, force_sync=False):
    """Return cached global market context; the sweep is single-flight.

    Fresh cache: served directly. Stale cache while a PREVIOUS context
    exists (and force_sync is False): serve the previous context
    immediately and kick at most ONE background sweep — UI_05 measured
    tail cause was every concurrent recompute paying the 17-call sweep
    inline on TTL lapse (8.3-10.5s inside the cold-switch chain window at
    pure chain <=1.8s, gate wait 0; trials @ 1f83a25 and f478208). No
    context yet (boot) or force_sync=True (_ensure_mkt_ctx_confluence_complete):
    join an in-flight sweep bounded, else perform it synchronously.

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — refresh scheduling only; the Schwab
      sweep itself lives unchanged in _fetch_and_store_mkt_ctx.
    Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE — served context
      is at most TTL + one sweep old, disclosed here; no fabricated values.
    All consumers checked: yes — _fetch_state (stale-while-refresh) and
      _ensure_mkt_ctx_confluence_complete (force_sync=True) both audited.
    SCHWAB_CSV_CHECKED"""
    global _mkt_ctx_refresh_inflight
    mkt_ctx_cache_eval_wall_ts = time.time()
    with _cached_mkt_ctx_lock:
        if (
            _cached_mkt_ctx is not None
            and (mkt_ctx_cache_eval_wall_ts - _cached_mkt_ctx_ts) < MKT_CTX_TTL
        ):
            # Cache is fresh — update PCR values on the cached object
            # (PCR is per-ticker, comes from the chain, not from market context)
            if pcr is not None:
                _cached_mkt_ctx.pcr = pcr
            return _cached_mkt_ctx
        if _cached_mkt_ctx is not None and not force_sync:
            if not _mkt_ctx_refresh_inflight:
                _mkt_ctx_refresh_inflight = True
                try:
                    _get_mkt_ctx_refresh_executor().submit(
                        _mkt_ctx_background_refresh, client, pcr, prev_pcr
                    )
                except RuntimeError:
                    _mkt_ctx_refresh_inflight = False
            if pcr is not None:
                _cached_mkt_ctx.pcr = pcr
            return _cached_mkt_ctx
        # Boot (no context yet) or force_sync: bounded join on any in-flight
        # sweep; take over the sweep if none is running (or the join expires).
        _join_deadline = time.monotonic() + MKT_CTX_SYNC_JOIN_TIMEOUT_SEC
        while _mkt_ctx_refresh_inflight and time.monotonic() < _join_deadline:
            _mkt_ctx_refresh_cond.wait(timeout=1.0)
            if (
                _cached_mkt_ctx is not None
                and (time.time() - _cached_mkt_ctx_ts) < MKT_CTX_TTL
            ):
                if pcr is not None:
                    _cached_mkt_ctx.pcr = pcr
                return _cached_mkt_ctx
        _mkt_ctx_refresh_inflight = True
    try:
        return _fetch_and_store_mkt_ctx(client, pcr=pcr, prev_pcr=prev_pcr)
    finally:
        with _cached_mkt_ctx_lock:
            _mkt_ctx_refresh_inflight = False
            _mkt_ctx_refresh_cond.notify_all()


def _ensure_mkt_ctx_confluence_complete(client, mkt_ctx, *, pcr=None, prev_pcr=None):
    """One forced refresh when weighted_push fields are missing before snapshot persist."""
    from market_context import missing_confluence_weighted_pushes, patch_context_confluence_from_quote_ticks

    missing = missing_confluence_weighted_pushes(mkt_ctx)
    if not missing:
        return mkt_ctx
    log.warning("Market context missing confluence fields %s — forcing refresh", missing)
    global _cached_mkt_ctx_ts
    with _cached_mkt_ctx_lock:
        _cached_mkt_ctx_ts = 0.0
    # force_sync: this path just zeroed the cache ts because required
    # confluence fields are MISSING — a stale-while-refresh serve would
    # hand back the same incomplete object.
    fresh = _get_mkt_ctx(client, pcr=pcr, prev_pcr=prev_pcr, force_sync=True)
    still = missing_confluence_weighted_pushes(fresh)
    if still:
        try:
            from market_context import (
                QQQ_TOP,
                SPY_TOP,
                IWM_SECTORS,
                IWM_TOP_HOLDINGS,
            )

            tickers: set[str] = set()
            for group in (SPY_TOP, QQQ_TOP, IWM_TOP_HOLDINGS):
                tickers.update(sym for sym, _n, _w in group)
            for sym, _n, _w in IWM_SECTORS:
                tickers.add(sym)
            chg_map = get_db().fetch_latest_confluence_quote_chg(sorted(tickers))
            if chg_map:
                patch_context_confluence_from_quote_ticks(fresh, chg_map)
                still = missing_confluence_weighted_pushes(fresh)
        except Exception as e:
            log.debug("confluence_quote_ticks impute failed: %s", e, exc_info=True)
    if still:
        log.error(
            "Confluence fields still missing after refresh: %s (qqq/spy/iwm weighted_push)",
            still,
        )
    return fresh


def _live_operator_mode_active() -> bool:
    """
    LIVE_OPERATOR_MODE_RESET_V1 Step 1 — True only when the ET clock is inside RTH on a
    weekday AND at least one operator/viewer transport is connected (a Tier C
    /api/stream subscriber or an L1 light /api/analytics/light/stream client).

    Consumed by _logger_fetch_and_log: while the operator is live, non-trio background
    rotation must not run full _fetch_state (chain + ML stack + DB writes would compete
    with the live path for the analytics pool, the Schwab request budget, and SQLite).
    """
    et = now_et()
    mins = et.hour * 60 + et.minute
    if et.weekday() >= 5 or not (RTH_OPEN_MINS <= mins < RTH_CLOSE_MINS):
        return False
    with _sse_lock:
        if any(n > 0 for n in _sse_subscribers.values()):
            return True
    with _l1_light_sse_lock:
        return len(_l1_light_sse_clients) > 0


# _operator_mode_cycle_roster REMOVED 2026-08-25 (RC-493): it throttled the background
# logger to trio + one rotating guest while a viewer was connected, refreshing non-trio
# tickers only ~once per 30 min — the operator ruled universal collection unconditional, so
# the throttle is gone (see _logger_loop) rather than left as dead code (RC-474 class).


def _logger_fetch_and_log(ticker: str) -> str:
    """
    Fetch data for one ticker and log a snapshot to the DB.
    Returns 'ok:fetch', 'skipped:closed', 'skipped:quarantined', or 'error:<msg>'.
    Never raises — always returns a status string.
    (2026-08-25 universal collection: the 'skipped:confluence_quote_only' and
    'skipped:live_operator_mode' statuses are retired — no per-ticker capture skip.)
    """
    tk = ticker_storage_key(ticker)   # Cursor-audit F4: the shared quarantine book is keyed canonically
    try:
        if not _is_loggable_session():
            return "skipped:closed"

        # Cursor-audit F4: consult the shared per-symbol vendor-health book BEFORE spending a scarce
        # chain-gate slot. A symbol the vendor PERMANENTLY refuses (SATS 404 -> hard-quarantined after
        # 3 hits) or is briefly unavailable (soft backoff) is skipped here instead of re-requested
        # every cycle. The terrain loop already had this protection; the logger — hitting the SAME
        # 2-slot chain gate — did not, so a dead symbol burned a slot the healthy book needed on
        # every pass (RC-148 class). One book across both loops: whichever hits the 404 quarantines it.
        if _terrain_quarantine_blocks(tk):
            return "skipped:quarantined"

        # UNIVERSAL COLLECTION (operator requirement, 2026-08-25, RC-493): the panel_auto
        # confluence-only skip AND the operator-mode throttle are gone — every enrolled
        # ticker collects full snapshots every cycle through the session, viewer connected
        # or not. (Measured cost of the old hard skip: 52 background rows ALL DAY on
        # 2026-08-20 vs 729–1,414 on neighbor days; XLE/XOM zero-snapshot.)

        # Always run the logging fetch each logger cycle (append-only INSERTs).

        # Full pipeline fetch
        from base_money_path_capture import LOGGER_SOURCE_BACKGROUND

        _fetch_state(
            ticker,
            expiry=None,
            log_only=True,
            logger_source=LOGGER_SOURCE_BACKGROUND,
        )

        logger_cycle_touch_wall_ts = time.time()
        with _logger_lock:
            _logger_stats.setdefault(ticker, {})
            _logger_stats[ticker]["last_logged"] = logger_cycle_touch_wall_ts
            _logger_stats[ticker]["count"]       = _logger_stats[ticker].get("count", 0) + 1
            _logger_stats[ticker]["last_error"]  = None
            _logger_stats[ticker]["source"]      = "fetch"

        if _HAS_SIGNALS:
            try:
                get_db().logging_universe_touch_background_log(ticker, logger_cycle_touch_wall_ts)
            except Exception as e:
                log.debug(
                    "logging_universe_touch_background_log failed ticker=%s: %s",
                    ticker,
                    e,
                    exc_info=True,
                )

        _note_terrain_success(tk)   # Cursor-audit F4: a clean fetch clears any streak/soft hold
        return "ok:fetch"

    except Exception as e:
        err = str(e)[:STATE_ERROR_DETAIL_MAX_CHARS]
        log.warning(f"Logger: {ticker} failed — {err}")
        with _logger_lock:
            _logger_stats.setdefault(ticker, {})
            _logger_stats[ticker]["last_error"] = err
        # Cursor-audit F4: feed the shared quarantine so a permanently-refused symbol stops being
        # re-requested every cycle. Parse the vendor status _fetch_state now carries on its detail
        # (read the FULL detail, not the truncated `err`); unknown -> _classify_chain_failure fails
        # closed to "soft", so an unrecognised error never earns a wrongful permanent quarantine.
        _detail = str(getattr(e, "detail", None) or e)
        _vstatus = None
        if "vendor_status=" in _detail:
            _val = _detail.split("vendor_status=", 1)[1].split("]", 1)[0].strip()
            if _val.isdigit():
                _vstatus = int(_val)
        _note_terrain_failure(tk, err, _classify_chain_failure(_vstatus, type(e).__name__))
        return f"error:{err}"


def _logger_loop():
    """
    Background thread: cycle through all tracked tickers every LOG_INTERVAL
    seconds, staggering fetches to stay well within Schwab rate limits.

    Cycle timing (12 core tickers, 2s stagger, 30s interval):
      t=0s   → SPY fetch  (triggers market context cache: 17 calls)
      t=2s   → QQQ fetch  (market context cached — 3 calls only)
      t=4s   → IWM fetch
      ...
      t=22s  → AVGO fetch
      t=30s  → cycle repeats

    API budget: 17 (global) + 12×3 (per-ticker) = 53 calls / 30s ≈ 106/min
    Plus active UI ticker (if not in core): +6/min → ~112/min (limit: 120/min)
    """
    global _logger_running, _cached_mkt_ctx_ts
    log.info("Background multi-ticker logger started")

    # Delay first cycle so startup warm + first UI request can finish Tier C without
    # competing with 27-ticker logger _fetch_state storms (ED_LOGGER_STARTUP_DELAY_SEC).
    time.sleep(LOGGER_STARTUP_DELAY_SEC)

    while _logger_running:
        cycle_start = time.monotonic()

        with _logger_lock:
            tickers_this_cycle = list(_logger_tickers)

        # UNIVERSAL COLLECTION IS UNCONDITIONAL (operator requirement, 2026-08-25):
        # every enrolled ticker collects EVERY cycle, viewer connected or not. The prior
        # operator-mode throttle (trio + one rotating guest while a viewer was connected)
        # refreshed non-trio tickers only about once per full rotation (~30 min live-
        # measured), which the operator ruled out — "every enrolled ticker must collect and
        # continue through 4:15 ET" carries no while-viewing exception. Viewer/UI contention
        # is absorbed by the per-ticker stagger and the thread pool, not by dropping tickers
        # from the sweep. (_live_operator_mode_active still governs the UI-only refresh
        # skips below and in the terrain loop.)

        with _cached_mkt_ctx_lock:
            _cached_mkt_ctx_ts = 0.0

        log.info(f"Logger cycle: {len(tickers_this_cycle)} tickers — {tickers_this_cycle}")

        for i, ticker in enumerate(tickers_this_cycle):
            if not _logger_running:
                break
            # Stagger: sleep between each ticker (not before the first)
            if i > 0:
                time.sleep(STAGGER_SECS)

            status = _logger_fetch_and_log(ticker)
            log.info(f"Logger: {ticker} → {status}")

        # Wait for remainder of the interval (monotonic — not market/quote time)
        elapsed = time.monotonic() - cycle_start
        wait    = max(0, LOG_INTERVAL - elapsed)
        log.info(f"Logger cycle complete in {elapsed:.1f}s — sleeping {wait:.1f}s")

        # Sleep in small chunks so we can exit cleanly if stopped
        sleep_end = time.monotonic() + wait
        while _logger_running and time.monotonic() < sleep_end:
            time.sleep(1)

    log.info("Background multi-ticker logger stopped")


_base_money_path_logger_running: bool = False
_base_money_path_logger_thread: threading.Thread | None = None


def base_money_path_logger_tickers() -> tuple[str, ...]:
    """SPY/QQQ/IWM — dedicated RTH capture rotation independent of UI-active ticker."""
    from money_path_ticker_tiers import BASE_MONEY_PATH_TICKERS

    return BASE_MONEY_PATH_TICKERS


def _base_money_path_capture_one(ticker: str):
    """Quote-only base capture — tagged logger_source=base_money_path (no full _fetch_state)."""
    from base_money_path_capture import (
        BaseCaptureAttempt,
        LOGGER_SOURCE_BASE_MONEY_PATH,
        build_lightweight_snapshot_row_from_quote,
    )
    from time_et import now_et as _eastern_now

    t0 = time.monotonic()
    t = ticker.upper().strip()
    try:
        if not _is_loggable_session():
            return BaseCaptureAttempt(t, "skipped:closed", time.monotonic() - t0)

        client = get_client()
        if client is None:
            return BaseCaptureAttempt(t, "error:no_client", time.monotonic() - t0)

        q_resp = _memoized_quote_response(t, client=client)   # RC-112/W3-C8: one vendor faucet
        if q_resp is None or getattr(q_resp, "status_code", None) != 200:
            code = getattr(q_resp, "status_code", None)
            return BaseCaptureAttempt(
                t,
                f"error:quote_{code if code is not None else 'none'}",
                time.monotonic() - t0,
            )

        q_json = q_resp.json()
        node = q_json.get(t) or q_json.get(ticker) or {}
        session_q = _parse_quote_node_session_fields(node)
        parsed_last = session_q.get("last")
        parsed_mark = session_q.get("mark")
        spot_f = parsed_last if parsed_last and parsed_last > 0 else (
            parsed_mark if parsed_mark and parsed_mark > 0 else None
        )
        if spot_f is None or float(spot_f) <= 0:
            return BaseCaptureAttempt(t, "error:no_spot", time.monotonic() - t0)

        quote_fields = {
            "spot_f": float(spot_f),
            "bid": session_q.get("bid"),
            "ask": session_q.get("ask"),
            "bid_size": session_q.get("bid_size"),
            "ask_size": session_q.get("ask_size"),
            "last_size": session_q.get("last_size"),
            "total_volume": session_q.get("total_volume"),
        }

        now_et = _eastern_now()
        snap_ts = time.time()
        if not _HAS_SIGNALS:
            return BaseCaptureAttempt(t, "skipped:no_db", time.monotonic() - t0)
        if not _snapshot_row_insert_allowed(t, snap_ts, db=get_db()):
            return BaseCaptureAttempt(t, "skipped:throttle", time.monotonic() - t0)

        try:
            row = build_lightweight_snapshot_row_from_quote(
                t, quote_fields, ts_utc=snap_ts, now_et=now_et
            )
            get_db().insert_snapshot(row)
        except BaseException:
            _snapshot_row_insert_release(t, snap_ts)
            raise
        _snapshot_row_insert_committed(t, snap_ts)

        # RC-69: bars are NOT written here. This is a snapshot capture; bar collection is its own
        # service (_bars_loop), so there is exactly ONE writer of price_bars_1m. An earlier fix
        # bolted bar persistence onto this function — that only moved the defect (collection
        # riding a capture path) instead of removing it.
        touch_ts = time.time()
        if _HAS_SIGNALS:
            try:
                get_db().logging_universe_touch_background_log(t, touch_ts)
            except Exception as e:
                log.debug("base capture touch_background_log %s: %s", t, e)

        with _logger_lock:
            _logger_stats.setdefault(t, {})
            _logger_stats[t]["last_logged"] = touch_ts
            _logger_stats[t]["count"] = _logger_stats[t].get("count", 0) + 1
            _logger_stats[t]["last_error"] = None
            _logger_stats[t]["source"] = LOGGER_SOURCE_BASE_MONEY_PATH

        return BaseCaptureAttempt(t, "ok:insert", time.monotonic() - t0)

    except Exception as e:
        err = str(e)[:STATE_ERROR_DETAIL_MAX_CHARS]
        log.warning("Base money-path capture: %s failed — %s", t, err)
        with _logger_lock:
            _logger_stats.setdefault(t, {})
            _logger_stats[t]["last_error"] = err
        return BaseCaptureAttempt(t, f"error:{err}", time.monotonic() - t0)


def _maybe_schedule_base_normalized_refresh() -> None:
    """
    LIVE_OPERATOR_MODE_RESET_V1 Step 3 — base trio normalized materialize is skipped
    while the operator is live: materialize_normalized_table is a long clear+rebuild
    write transaction on the single SQLite file and must not contend with the live
    path. Raw base capture is unaffected; the first non-live cycle schedules the
    debounced refresh exactly as before.
    """
    if _live_operator_mode_active():
        log.debug("base normalized refresh skipped (live operator mode)")
        return
    try:
        from db import DB_PATH as _base_norm_db_path
        from normalized_training_sync import schedule_debounced_base_money_path_normalized_refresh

        schedule_debounced_base_money_path_normalized_refresh(_base_norm_db_path, logger=log)
    except Exception as _bne:
        log.warning("schedule base money-path normalized refresh: %s", _bne)


def _base_money_path_logger_loop():
    """
    Dedicated base-ticker capture: SPY, QQQ, IWM at ~1 lightweight snapshot/min each during RTH.

    Concurrent quote-only inserts (logger_source=base_money_path) — independent of UI-active
    ticker and without full _fetch_state model/card compute.
    """
    from base_money_path_capture import run_base_money_path_capture_cycle
    from money_path_ticker_tiers import base_money_path_capture_interval_sec

    global _base_money_path_logger_running
    interval = base_money_path_capture_interval_sec()
    tickers = base_money_path_logger_tickers()
    timeout_sec = float(os.environ.get("ED_BASE_CAPTURE_TIMEOUT_SEC", "45"))
    log.info(
        "Base money-path logger started — %s every %.0fs concurrent quote-only (UI-independent)",
        list(tickers),
        interval,
    )

    time.sleep(LOGGER_STARTUP_DELAY_SEC)

    while _base_money_path_logger_running:
        cycle_start = time.monotonic()

        if not _is_loggable_session():
            sleep_end = time.monotonic() + min(interval, 30.0)
            while _base_money_path_logger_running and time.monotonic() < sleep_end:
                time.sleep(1)
            continue

        attempts = run_base_money_path_capture_cycle(
            tickers,
            capture_one=_base_money_path_capture_one,
            max_workers=len(tickers),
            per_ticker_timeout_sec=timeout_sec,
            log=log,
        )
        for attempt in attempts:
            log.info(
                "Base money-path logger: %s → %s (%.2fs)",
                attempt.ticker,
                attempt.status,
                attempt.duration_sec,
            )

        _maybe_schedule_base_normalized_refresh()

        elapsed = time.monotonic() - cycle_start
        wait = max(0.0, interval - elapsed)
        sleep_end = time.monotonic() + wait
        while _base_money_path_logger_running and time.monotonic() < sleep_end:
            time.sleep(1)

    log.info("Base money-path logger stopped")


def start_logger():
    global _logger_running, _logger_thread
    global _base_money_path_logger_running, _base_money_path_logger_thread
    if _logger_running:
        return
    _hydrate_logger_tickers_from_db()
    _logger_running = True
    _base_money_path_logger_running = True
    _logger_thread = threading.Thread(target=_logger_loop, daemon=True, name="ed-ticker-logger")
    _base_money_path_logger_thread = threading.Thread(
        target=_base_money_path_logger_loop,
        daemon=True,
        name="ed-base-money-path-logger",
    )
    _logger_thread.start()
    _base_money_path_logger_thread.start()


def stop_logger():
    global _logger_running, _base_money_path_logger_running
    _logger_running = False
    _base_money_path_logger_running = False


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — convert MarketState to JSON-safe dict
# ─────────────────────────────────────────────────────────────────────────────
def _jsonable(obj):
    """Recursively coerce to JSON-serializable structures (preserve numeric leaves)."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return str(obj)


def _ms_to_dict(ms) -> dict:
    """Convert MarketState dataclass to JSON-serializable dict."""
    d = {}
    for f_name in ms.__dataclass_fields__:
        v = getattr(ms, f_name)
        if isinstance(v, (str, int, float, bool, type(None))):
            d[f_name] = v
        elif isinstance(v, list):
            # Preserve dicts inside lists (e.g. charm_top_drivers)
            out = []
            for x in v:
                if isinstance(x, dict):
                    out.append(_jsonable(x))
                elif isinstance(x, (str, int, float, bool, type(None))):
                    out.append(x)
                else:
                    out.append(str(x))
            d[f_name] = out
        elif isinstance(v, dict):
            d[f_name] = _jsonable(v)
        else:
            d[f_name] = str(v) if v is not None else None
    return d


# Trader-facing REST/SSE payload: primary decision horizons only (Issue 2 + tier contract).
_TRADER_ACCURACY_HORIZONS_UI = frozenset(PRIMARY_DECISION_HORIZONS)
_TRADER_UI_PRODUCT_HORIZONS = frozenset(PRIMARY_DECISION_HORIZONS)
_PRIMARY_UI_HORIZON_MINUTES = frozenset(f"{int(s[:-1])}m" for s in PRIMARY_DECISION_HORIZONS)
_TRADER_HIDDEN_BAR_HORIZONS = tuple(SECONDARY_SUPPORT_HORIZONS)


def _strip_trader_hidden_horizon_keys(ms_dict: dict) -> None:
    """
    Remove internal training/eval horizons (3c/8c/13c) from the trader-facing JSON.

    Product horizons remain as canonical bar-count slugs (1c/5c/15c/60c); the UI maps
    those to 1m/5m/15m/60m labels. Hidden horizons may still exist server-side for
    research/backfill, but must not leak into the main operator surface payload.
    """
    hidden_suffixes = tuple(f"_{hz}" for hz in _TRADER_HIDDEN_BAR_HORIZONS)
    drop_keys = [
        k
        for k in list(ms_dict.keys())
        if isinstance(k, str) and any(k.endswith(suf) for suf in hidden_suffixes)
    ]
    for k in drop_keys:
        ms_dict.pop(k, None)

    def _scrub_mapping(attr: str) -> None:
        m = ms_dict.get(attr)
        if not isinstance(m, dict):
            return
        out = {}
        for kk, vv in m.items():
            if not isinstance(kk, str):
                continue
            if any(kk.endswith(suf) for suf in hidden_suffixes):
                continue
            out[kk] = vv
        ms_dict[attr] = out

    _scrub_mapping("movement_head_probs")
    _scrub_mapping("fusion_policy_snapshot_cols")


def _filter_horizon_prob_bars_primary_only(ms_dict: dict) -> None:
    """Product UI keys only (1m/5m/15m/60m); drop legacy secondary bar keys if present."""
    hpb = ms_dict.get("horizon_prob_bars")
    if not isinstance(hpb, dict):
        return
    allow = _PRIMARY_UI_HORIZON_MINUTES
    ms_dict["horizon_prob_bars"] = {k: v for k, v in hpb.items() if k in allow}


def _apply_trader_horizon_contract(ms_dict: dict) -> None:
    """Strip legacy/non-product horizon fields from JSON sent to the browser."""
    _strip_trader_hidden_horizon_keys(ms_dict)
    _filter_horizon_prob_bars_primary_only(ms_dict)
    _acc = ms_dict.get("accuracy")
    if isinstance(_acc, dict):
        _filt = {
            hz: v
            for hz, v in _acc.items()
            if hz in _TRADER_ACCURACY_HORIZONS_UI and isinstance(v, dict)
        }
        ms_dict["accuracy"] = _filt if _filt else None
    _reads = ms_dict.get("timeframe_reads")
    if isinstance(_reads, dict):
        _legacy_1h = _reads.pop("1h", None)
        if _legacy_1h is not None and "60m" not in _reads:
            _reads["60m"] = _legacy_1h


def _attach_stack_runtime_and_governance(ms_dict: dict, *, ticker: str) -> None:
    """
    Small, UI-oriented bundle for decision surfaces (not a second truth).

    - stack_runtime: fusion active, MC participation, coarse stack mode (FULL/INVALID)
    - stack_governance: architecture competition state from models/arch_state.json (when present)
    """
    try:
        from governed_stack_contract import classify_stack_health
    except Exception:
        def classify_stack_health(*, fusion_available, mc_available, n_ml_layers_available, unified_stack_team_ok=None):  # type: ignore
            team_ok = unified_stack_team_ok
            if team_ok is None:
                team_ok = n_ml_layers_available >= 3 and fusion_available
            if not team_ok or not fusion_available or not mc_available:
                return "INVALID"
            if n_ml_layers_available >= 3:
                return "FULL"
            return "INVALID"

    # STACK-WIRE-4-CAND-MS-DICT-ADOPTION: tradability gate, not bare .available flag.
    # fusion_available=True + canonical_provenance="canonical_forecast_missing" is a
    # non-tradable split-brain state — surface it as fusion_active=False / stack_mode=INVALID.
    from fusion_contract import is_ms_dict_fusion_authoritative
    fusion_ok = is_ms_dict_fusion_authoritative(ms_dict)
    mc_ok = bool(ms_dict.get("mc_available"))
    xgb_ok = bool(ms_dict.get("xgb_available"))
    lstm_ok = bool(ms_dict.get("lstm_available"))
    trans_ok = bool(ms_dict.get("transformer_available"))
    n_ml_layers = 0
    for k in ("xgb_available", "lstm_available", "transformer_available"):
        if ms_dict.get(k):
            n_ml_layers += 1

    from types import SimpleNamespace

    from governed_stack_contract import unified_stack_team_can_authorize

    def _layer_ns(layer: str):
        probs = (ms_dict.get("ml_layer_probs") or {}).get(layer)
        if isinstance(probs, dict) and probs.get("up") is not None:
            return SimpleNamespace(
                available=True,
                prob_up=probs.get("up"),
                prob_down=probs.get("down"),
                prob_flat=probs.get("flat"),
            )
        avail = bool(ms_dict.get(f"{layer}_available"))
        return SimpleNamespace(
            available=avail,
            prob_up=None,
            prob_down=None,
            prob_flat=None,
        )

    team_ok, team_reason = unified_stack_team_can_authorize(
        xgb_out=_layer_ns("xgb"),
        lstm_out=_layer_ns("lstm"),
        transformer_out=_layer_ns("transformer"),
        stack_probs=None,
    )
    ms_dict["unified_stack_team_ok"] = bool(team_ok)
    ms_dict["unified_stack_team_reason"] = team_reason

    cm = ms_dict.get("fusion_contributing_models")
    if not isinstance(cm, list) or not cm:
        cm = []
        fpc = ms_dict.get("fusion_policy_snapshot_cols")
        if isinstance(fpc, dict):
            seen: set[str] = set()
            for hz in sorted(_TRADER_UI_PRODUCT_HORIZONS):
                raw = fpc.get(f"fused_contributing_models_{hz}")
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    parsed = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(parsed, list):
                    continue
                for item in parsed:
                    s = str(item).strip()
                    if not s or s in seen:
                        continue
                    seen.add(s)
                    cm.append(s)

    ms_dict["stack_runtime"] = {
        "fusion_active": fusion_ok,
        "mc_participated": mc_ok,
        "n_ml_layers_live": int(n_ml_layers),
        "unified_stack_team_ok": bool(team_ok),
        "stack_mode": classify_stack_health(
            fusion_available=fusion_ok,
            mc_available=mc_ok,
            n_ml_layers_available=n_ml_layers,
            unified_stack_team_ok=bool(team_ok),
        ),
        "contributing_models": cm,
    }

    gov: dict[str, Any] = {"available": False}
    arch_ent: dict[str, Any] | None = None
    try:
        arch_path = Path(APP_DIR) / "models" / "arch_state.json"
        if arch_path.exists():
            arch = json.loads(arch_path.read_text(encoding="utf-8"))
            ent = arch.get(ticker_storage_key(ticker)) if isinstance(arch, dict) else None  # RC-345/F25: reader key == canonical writer key
            if isinstance(ent, dict):
                arch_ent = ent
                active = str(ent.get("active_architecture") or "").strip().lower()
                promoted = bool(ent.get("promoted"))
                mode = "promoted" if promoted else ("challenger" if active == "cascade" else "baseline")
                gov = {
                    "available": True,
                    "active_architecture": active or None,
                    "promoted": promoted,
                    "promotion_reason": ent.get("promotion_reason"),
                    "authority_mode": mode,
                    # RC-85: the `or ent.get("signal_chain_authoritative")` fallback is REMOVED.
                    # Nothing in this repo has ever written that key and the live payload does
                    # not carry it, so the branch could never be taken — it advertised a second
                    # source that does not exist.
                    "authoritative_stage": ent.get("authoritative_stage"),
                }
    except Exception:
        gov = {"available": False, "error": "arch_state_read_failed"}
    ms_dict["stack_governance"] = gov

    # Signal chain bar (UI): per-stage health + optional authoritative stage (driven by runtime + arch overrides).
    def _tri(active: bool, degraded: bool = False) -> str:
        if degraded:
            return "degraded"
        return "active" if active else "off"

    sm = str(ms_dict.get("stack_runtime", {}).get("stack_mode") or "").upper()
    spot_ok = ms_dict.get("spot") is not None
    # RC-85: `micro_5m_headline` dropped from this chain — never written anywhere in the repo
    # and absent from the live /api/state payload, so it could only ever contribute False.
    rules_ok = bool(
        ms_dict.get("rules_headline")
        or ms_dict.get("rules_conviction")
    )
    valp = ms_dict.get("validation_passed")
    et_raw = ms_dict.get("entry_display_text")
    et_ok = bool(
        et_raw
        and str(et_raw).strip()
        and str(et_raw).strip().lower() not in ("no valid setup", "—", "-")
    )

    feat_st = "off" if sm == "INVALID" else ("degraded" if sm in ("DEGRADED", "PARTIAL") or not spot_ok else "active")
    rules_st = "degraded" if not rules_ok else "active"
    mc_deg = (not mc_ok) and fusion_ok

    if valp is True:
        pol_st = "active"
    elif valp is False:
        pol_st = "degraded"
    else:
        pol_st = "off"

    sc_status = {
        "features": feat_st,
        "rules": rules_st,
        "xgb": _tri(xgb_ok),
        "lstm": _tri(lstm_ok),
        "trans": _tri(trans_ok),
        "mc": _tri(mc_ok, mc_deg),
        "fusion": _tri(fusion_ok),
        "policy": pol_st,
        "trade": _tri(et_ok),
    }

    auth_stage: str | None = None
    try:
        if isinstance(arch_ent, dict):
            raw_a = arch_ent.get("authoritative_stage")   # RC-85: dead alias fallback removed
            if isinstance(raw_a, str) and raw_a.strip():
                a = raw_a.strip().lower()
                alias = {
                    "transformer": "trans",
                    "trade_plan": "trade",
                    "plan": "trade",
                }
                a = alias.get(a, a)
                if a in sc_status:
                    auth_stage = a
    except Exception:
        auth_stage = None

    if auth_stage is None:
        prov = str(ms_dict.get("canonical_provenance") or "")
        pl = prov.lower()
        if pl and "fusion_unavailable" not in pl:
            if "bayesian" in pl or pl.endswith("bayesian_fusion"):
                auth_stage = "fusion"
            elif "xgb" in pl or "tabular" in pl:
                auth_stage = "xgb"
            elif "lstm" in pl:
                auth_stage = "lstm"
            elif "transformer" in pl:
                auth_stage = "trans"
            elif "rules" in pl:
                auth_stage = "rules"
            elif "monte" in pl or "mc" in pl or "carlo" in pl:
                auth_stage = "mc"
            elif "policy" in pl:
                auth_stage = "policy"
            elif "feature" in pl:
                auth_stage = "features"
            elif "trade" in pl or "entry" in pl:
                auth_stage = "trade"

    ms_dict["signal_chain"] = {
        "status": sc_status,
        "authoritative": auth_stage,
    }


def _trader_accuracy_subset(results: dict) -> dict:
    """Subset of compute_accuracy() results exposed on UI-oriented APIs."""
    if not isinstance(results, dict):
        return {}
    return {hz: results[hz] for hz in _TRADER_ACCURACY_HORIZONS_UI if hz in results}


def _current_pred_model_version(ticker: str) -> str:
    """Version string the serving stack stamps on snapshot rows (pred_model_version).

    Repo-wide audit 2026-07-05: accuracy callers defaulted to the legacy
    'statistical_v1' literal, which matches ZERO persisted rows (live stamps on
    SPY: stack(xgb_lstm_tr_meta)_1c 28,647 / rules_v1 908 / stack(xgb_lstm_tr)_1c
    649) — the accuracy payload block and accuracy history were silently empty
    ("Accuracy computed: 0 predictions" every cycle). Accuracy must be computed
    for the version that actually stamps rows; ml_predict.get_model_version is
    that same source. Fallback mirrors its own no-bundle fallback (rules_v1),
    never the dead literal.
    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — model-version selector for persisted
      prediction-accuracy reads; no market field derivation changed.
    Derived-field disposition: none required.
    All consumers checked: yes — both compute_accuracy callers and the
      accuracy-history writer updated in this change set.
    SCHWAB_CSV_CHECKED
    """
    try:
        from ml_predict import get_model_version

        return get_model_version(ticker)
    except Exception:
        return "rules_v1"


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — parse expiries from chain
# ─────────────────────────────────────────────────────────────────────────────
def _expiries_from_contracts(contracts: list) -> list[str]:
    exps = set()
    for ct in contracts:
        exp = ct.get("expirationDate")
        if exp:
            s = str(exp)[:10]
            if len(s) == 10:
                exps.add(s)
    return sorted(exps)


def _filter_contracts_by_selected_expiry(
    contracts: list,
    selected_exp: str | None,
) -> tuple[list[dict], str]:
    """
    Strict Schwab ``expirationDate`` slice for the selected expiry key.
    No silent full-chain fallback (DFR-005 / OP-018).
    """
    exp_key = str(selected_exp or "")[:10]
    if not exp_key or len(exp_key) != 10:
        return [], "unavailable_missing_selected_expiry"
    filtered = [
        ct for ct in (contracts or [])
        if str(ct.get("expirationDate") or "")[:10] == exp_key
    ]
    if not filtered:
        return [], "unavailable_no_contracts_for_expiry"
    return filtered, "schwab_expirationDate"


def _kl_expiry_source_label(
    *,
    expiry_param: str | None,
    slice_source: str,
) -> str:
    if slice_source != "schwab_expirationDate":
        return slice_source
    if expiry_param:
        return "schwab_expirationDate_user"
    return "schwab_expirationDate_default_nearest"


def _selected_schwab_days_to_expiration(
    contracts: list,
    selected_exp: str | None,
    *,
    preferred_strike: float | None = None,
    preferred_side: str | None = None,
) -> int | None:
    # RC-345 / F41: selected-expiry identity is MANDATORY. Without it there is NO selected
    # contract to read a DTE from — return governed absence, never search every expiry
    # (which would answer with some other expiry's DTE). The side/strike-less fallback below
    # is legitimate ONLY because exp_key is proven present here.
    exp_key = str(selected_exp or "")[:10]
    if len(exp_key) != 10:
        return None
    side_key = str(preferred_side or "").upper().strip()
    try:
        strike_key = float(preferred_strike) if preferred_strike is not None else None
    except (TypeError, ValueError):
        strike_key = None

    from numeric_contract import float_finite_or_none as _fin
    matches: list[dict] = []
    for ct in contracts or []:
        exp = str(ct.get("expirationDate") or "")[:10]
        if exp != exp_key:
            continue
        if side_key in ("CALL", "PUT") and str(ct.get("putCall") or "").upper().strip() != side_key:
            continue
        if strike_key is not None:
            # single source: reject NaN via the finite reader. Raw float() let a NaN
            # strike pass (abs(nan-strike_key) >= 0.01 is False), matching the wrong contract.
            _sp = _fin(ct.get("strikePrice"))
            if _sp is None or abs(_sp - strike_key) >= 0.01:
                continue
        matches.append(ct)

    if not matches and (side_key or strike_key is not None):
        return _selected_schwab_days_to_expiration(contracts, selected_exp)

    for ct in matches:
        # single source: finite DTE (canonical reader rejects NaN/±inf that int(float()) raised on)
        _dte_f = _fin(ct.get("daysToExpiration"))
        dte = int(_dte_f) if _dte_f is not None else None
        if dte is not None and dte >= 0:
            return dte
    return None


def _snapshot_expiry_hours_from_schwab_dte(
    schwab_dte: int | None,
    now_et: datetime,
    expiry_et_date: str | None = None,
) -> float | None:
    """Hours to PM-settlement close on the expiry date (or today when dte=0).

    Early-close sessions use 13:00 ET; regular sessions 16:00 ET. Multi-day must
    use the expiry date's own session close — not Schwab DTE*24 plus today's
    remainder, which lands at today's close clock on the expiry date.
    """
    if schwab_dte is None or schwab_dte < 0:
        return None
    from time_et import hours_until_session_close_et

    if expiry_et_date:
        return hours_until_session_close_et(now_et, expiry_et_date=expiry_et_date)
    if schwab_dte == 0:
        return hours_until_session_close_et(now_et)
    return None


def _fetch_expiries_light(ticker: str) -> list[str]:
    """
    Option expiries only — quote + option chain, no snapshot insert or MarketState.
    Used by /api/expiries when cache is cold (avoids logging a DB row per dropdown poll).
    """
    ticker = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX"
    client = get_client()
    # RC-59 chain-width faucet EXEMPTION, declared not accidental: this path reads the EXPIRY
    # DATE LIST only and computes no levels, so strike width is irrelevant to its output — a
    # minimal fetch is correct here. Every LEVEL-computing fetch must use
    # resolve_chain_strike_count(); this one may not, because widening it would only cost
    # latency on a dropdown poll with zero effect on the result.
    c_resp = safe_get_chain(
        client, ticker,
        strike_count=CHAIN_STRIKE_COUNT,   # chain-width-faucet-ok: expiry list only, no level math
    )
    if c_resp is None or c_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Option chain fetch failed")
    c_json = c_resp.json()
    contracts_raw: list[dict] = []
    for _side_key in ("callExpDateMap", "putExpDateMap"):
        _side_map = c_json.get(_side_key) or {}
        if not isinstance(_side_map, dict):
            continue
        for _exp_map in _side_map.values():
            if not isinstance(_exp_map, dict):
                continue
            for _strike_list in _exp_map.values():
                if not isinstance(_strike_list, list):
                    continue
                for _ct in _strike_list:
                    if isinstance(_ct, dict):
                        contracts_raw.append(_ct)
    contracts = [dict(ct) for ct in contracts_raw]
    expiries = _expiries_from_contracts(contracts)
    today = now_et().strftime("%Y-%m-%d")
    return [e for e in expiries if e >= today]


def _default_expiry(expiries: list[str], ticker: str = "?") -> Optional[str]:
    """Pick today's expiry if exists, else nearest future. Never returns a past date."""
    if not expiries:
        return None
    today = now_et().strftime("%Y-%m-%d")
    # Never return an expired date
    valid = [e for e in expiries if e >= today]
    if valid:
        return valid[0]
    # All expiries are in the past — log and return None
    log.warning(
        "_default_expiry: all expiries are past for %s "
        "today=%s expiries=%s",
        ticker, today, expiries[:5]
    )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# REST fallback — Cum Delta proxy (polling-based) when streamer unavailable
# Uses quote.lastPrice, lastSize, bidPrice, askPrice. Accumulates per session.
# ─────────────────────────────────────────────────────────────────────────────
def _safe_float_quote(v) -> Optional[float]:
    """Safe float for quote fields. SINGLE SOURCE: delegates to the canonical
    numeric_contract.float_finite_or_none so NaN/±inf are rejected identically everywhere
    (this previously accepted NaN/inf)."""
    from numeric_contract import float_finite_or_none
    return float_finite_or_none(v)


def _parse_quote_node_session_fields(node: dict) -> dict[str, Any]:
    """
    Canonical Schwab REST per-ticker quote node: quote → extended → regular fallbacks.
    ``node`` is the ticker object from GET /quotes JSON (keys quote, extended, regular).
    """
    _q = node.get("quote") or {}
    _ext = node.get("extended") or {}
    _reg = node.get("regular") or {}
    last = _safe_float_quote(_q.get("lastPrice"))
    if last is None or last <= 0:
        last = _safe_float_quote(_ext.get("lastPrice"))
    if last is None or last <= 0:
        last = _safe_float_quote(_reg.get("regularMarketLastPrice"))
    mark = _safe_float_quote(_q.get("mark"))
    if mark is None or mark <= 0:
        mark = _safe_float_quote(_ext.get("mark"))
    bid = _safe_float_quote(_q.get("bidPrice"))
    if bid is None:
        bid = _safe_float_quote(_ext.get("bidPrice"))
    ask = _safe_float_quote(_q.get("askPrice"))
    if ask is None:
        ask = _safe_float_quote(_ext.get("askPrice"))
    def _epoch_seconds(v: float | None) -> float | None:
        # Schwab wire quoteTime/tradeTime are epoch MILLISECONDS; every downstream consumer
        # (candle accumulators, fill_outcomes bar grid, as_of_ts_utc filters) expects seconds.
        # 2026-06-09 regression: raw ms ticks built ms-grid bars in price_bars_1m, so the
        # seconds-unit outcome filler matched zero bars and no snapshot got labeled all day.
        return v / 1000.0 if v is not None and v > 1e10 else v

    quote_time = _safe_float_quote(_q.get("quoteTime"))
    if quote_time is None:
        quote_time = _safe_float_quote(_ext.get("quoteTime"))
    quote_time = _epoch_seconds(quote_time)
    trade_time = _safe_float_quote(_q.get("tradeTime"))
    if trade_time is None:
        trade_time = _safe_float_quote(_ext.get("tradeTime"))
    if trade_time is None:
        trade_time = _safe_float_quote(_reg.get("regularMarketTradeTime"))
    trade_time = _epoch_seconds(trade_time)
    spot_source = "lastPrice" if last and last > 0 else ("mark" if mark and mark > 0 else None)
    spot = last if spot_source == "lastPrice" else (mark if spot_source == "mark" else None)
    try:
        spot_f = float(spot) if spot and float(spot) > 0 else None
    except (TypeError, ValueError):
        spot_f = None
    quote_mid: float | None = None
    mid_source: str | None = None
    if mark is not None and mark > 0:
        quote_mid = float(mark)
        mid_source = "schwab_quote_mark"
    # Raw Schwab order-flow primitives (CSV-first: quotes.{SYM}.bidSize/askSize/lastSize/
    # totalVolume). Persisted on the snapshot row so ablation can judge the primitives,
    # not only derivations like spread / vol_oi_ratio. No engineered substitutes here.
    bid_size = _safe_float_quote(_q.get("bidSize"))
    if bid_size is None:
        bid_size = _safe_float_quote(_ext.get("bidSize"))
    ask_size = _safe_float_quote(_q.get("askSize"))
    if ask_size is None:
        ask_size = _safe_float_quote(_ext.get("askSize"))
    last_size = _safe_float_quote(_q.get("lastSize"))
    if last_size is None:
        last_size = _safe_float_quote(_ext.get("lastSize"))
    total_volume = _safe_float_quote(_q.get("totalVolume"))
    if total_volume is None:
        total_volume = _safe_float_quote(_ext.get("totalVolume"))
    return {
        "last": last,
        "mark": mark,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "last_size": last_size,
        "total_volume": total_volume,
        "quote_time": quote_time,
        "trade_time": trade_time,
        "quote_ts": quote_time or trade_time,
        # M6: which exchange clock quote_ts carries — a TRADE_TIME_MILLIS value used as the
        # quote clock (quoteTime absent) is a LABELED proxy, never a silent conflation.
        "quote_ts_clock": (
            "QUOTE_TIME_MILLIS" if quote_time is not None
            else ("TRADE_TIME_MILLIS_proxy" if trade_time is not None else "unavailable")
        ),
        "spot_source": spot_source,
        "spot": spot_f,
        "quote_mid": quote_mid,
        "mid_source": mid_source,
    }


def _update_rest_cum_delta(ticker: str, quote: dict, now_et: datetime) -> float | None:
    """
    Update and return REST-based cum_delta accumulator for ticker.
    Resets at 9:30 ET on RTH open (not midnight). Pre-market trades do not carry into RTH.
    """
    global _rest_cum_delta, _rest_cum_delta_session
    try:
        hour, minute = now_et.hour, now_et.minute
        mins = hour * 60 + minute
        in_rth = RTH_OPEN_MINS <= mins < RTH_CLOSE_MINS and now_et.weekday() < 5
        date_str = now_et.strftime("%Y-%m-%d")
        session_key = date_str if in_rth else f"{date_str}-premarket"
        if session_key != _rest_cum_delta_session:
            _rest_cum_delta.clear()
            _rest_cum_delta_session = session_key
    except Exception as e:
        log.debug(f"REST cum_delta session check failed: {e}")
    last_price = _safe_float_quote(quote.get("lastPrice"))
    last_size = _safe_float_quote(quote.get("lastSize"))
    bid_price = _safe_float_quote(quote.get("bidPrice"))
    ask_price = _safe_float_quote(quote.get("askPrice"))
    if last_price is None or last_size is None or last_size <= 0:
        return _rest_cum_delta.get(ticker)
    delta = 0.0
    if ask_price is not None and last_price >= ask_price:
        delta = last_size
    elif bid_price is not None and last_price <= bid_price:
        delta = -last_size
    cur = _rest_cum_delta.get(ticker)
    if cur is None:
        cur = 0.0
    _rest_cum_delta[ticker] = cur + delta
    return _rest_cum_delta[ticker]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2A (operator 2026-08-08): `_compute_vwap_from_bars` was DELETED here.
# It was a second, independent VWAP implementation — a fallback for
# fetch_price_levels returning vwap=None — and it wrote into the snapshot table
# and from there into model features, so a persisted row could carry a VWAP that
# /api/levels never served. The one VWAP accumulation is now
# liquidity_value_engine.compute_session_vwap_path, reached only through the
# canonical PriceLevelSnapshot. Absent VWAP persists NULL (RC-68).
# ─────────────────────────────────────────────────────────────────────────────


# Per-ticker previous DPI normalized score (dealer pressure trend between refreshes)
_dpi_normalized_prev_by_ticker: dict[str, Optional[float]] = {}
# Last good bid-ask width (pts) when quote had both sides — reused if a poll drops one side
_last_spread_by_ticker: dict[str, float] = {}
_last_spread_ts_by_ticker: dict[str, float] = {}


# L1 generation counter per (ticker, expiry|__auto__) — monotonic for this process.
_l1_generation: dict[tuple, int] = {}
_l1_generation_lock = threading.Lock()
# Mirrors last assigned generation per scope (used for strict monotonicity assertion); cleared with scope.
_l1_last_generation_seen: dict[tuple, int] = {}

# Last successful L1 JSON per scope — event-driven rebuilds persist here (same payload shape as HTTP).
_l1_snapshot_cache: dict[tuple, dict] = {}
# LRU order for scopes (oldest first) — used with TTL for eviction under L1_MAX_CACHE_SCOPES.
_l1_scope_lru: OrderedDict[tuple, None] = OrderedDict()

# Quote-hook OF gating (per ticker): cheap input probe + cached signature — avoids redundant engine.compute.
_l1_of_probe_by_ticker: dict[str, tuple[Any, ...]] = {}
_l1_of_sig_cache_by_ticker: dict[str, tuple[Any, ...]] = {}
_l1_of_last_engine_mono_by_ticker: dict[str, float] = {}

# Process-local counters for validation / ops (lightweight; not high-cardinality).
# Names prefixed l1_* for grep; diagnostics endpoint exposes the same structure.
_l1_instrumentation: dict[str, Any] = {
    "l1_build_total": 0,
    "l1_build_ms_sum": 0.0,
    #: RC-291: builds whose pipeline timing was actually READ. The average divides by this,
    #: not by l1_build_total, so an unmeasured build cannot dilute the latency figure the
    #: warn threshold is compared against.
    "l1_build_ms_measured": 0,
    "l1_build_by_reason": defaultdict(int),
    "l1_http_cache_hit_total": 0,
    "l1_quote_material_skip_total": 0,
    "l1_cache_eviction_total": 0,
    "l1_cache_eviction_ttl_total": 0,
    "l1_cache_eviction_cap_total": 0,
    "l1_cache_reconcile_lru_pruned_total": 0,
    "l1_cache_reconcile_lru_backfilled_total": 0,
    "l1_of_quote_hook_engine_total": 0,
    "l1_of_quote_hook_reuse_total": 0,
    "l1_generation_assign_total": 0,
}


# Monotonic clock anchor for L1 diagnostics rates (operational assessment per /api/diagnostics/l1).
_l1_diag_start_mono = time.monotonic()

#: RC-236: minimum 1m bars the ATR needs, and the warmup horizon during which a deficit is the
#: designed state rather than a defect. One bar per minute means the accumulator cannot beat the
#: clock; the horizon carries a small margin for the first partial minute and re-seed latency.
ATR_MIN_BARS: int = 16
ATR_WARMUP_HORIZON_SEC: float = float(ATR_MIN_BARS + 4) * 60.0


def _seconds_since_boot() -> float:
    """Wall seconds this server process has been up (monotonic, restart-anchored)."""
    return max(0.0, time.monotonic() - _l1_diag_start_mono)


def _atr_warmup_active() -> bool:
    """True while the in-memory bar accumulator cannot yet physically hold ATR_MIN_BARS."""
    return _seconds_since_boot() < ATR_WARMUP_HORIZON_SEC


def _l1_generation_pop(key: tuple) -> None:
    """Remove generation state for a scope (eviction); must hold no locks from caller."""
    with _l1_generation_lock:
        _l1_generation.pop(key, None)
        _l1_last_generation_seen.pop(key, None)


def _l1_next_generation(key: tuple) -> int:
    """
    Atomically allocate the next l1_generation for this scope. Strictly increasing per key;
    safe under concurrent _project_l1 / quote hooks across threads.
    """
    with _l1_generation_lock:
        prev = _l1_generation.get(key, 0)
        new_gen = prev + 1
        last = _l1_last_generation_seen.get(key)
        if last is not None and new_gen <= last:
            raise RuntimeError(
                f"L1 generation regression or duplicate for scope {key!r}: "
                f"next={new_gen} last_seen={last}"
            )
        if new_gen <= prev:
            raise RuntimeError(
                f"L1 generation non-monotonic increment for scope {key!r}: "
                f"next={new_gen} prev={prev}"
            )
        _l1_generation[key] = new_gen
        _l1_last_generation_seen[key] = new_gen
        _l1_instrumentation["l1_generation_assign_total"] = (
            int(_l1_instrumentation.get("l1_generation_assign_total", 0)) + 1
        )
        return new_gen


def _l1_touch_scope(key: tuple) -> None:
    """Mark scope as most-recently used for LRU eviction."""
    if key in _l1_scope_lru:
        _l1_scope_lru.move_to_end(key)
    else:
        _l1_scope_lru[key] = None


def _l1_remove_scope(key: tuple) -> None:
    _l1_scope_lru.pop(key, None)


def _l1_after_scope_row_dropped(key: tuple) -> None:
    """LRU + monotonic generation must not retain evicted scopes."""
    _l1_remove_scope(key)
    _l1_generation_pop(key)
    _l1_last_emit_identity.pop(key, None)


def _l1_cache_maintain(now_ts: float) -> None:
    """TTL eviction + max-scope cap (LRU under cap) — _l1_snapshot_cache must not grow without bound."""
    from planes.l1_cache_lifecycle import ensure_lru_covers_snapshot, reconcile_lru_with_snapshot
    from planes.l1_runtime import L1_MAX_CACHE_SCOPES, entry_past_ttl

    dead: list[tuple] = []
    for k, snap in list(_l1_snapshot_cache.items()):
        if entry_past_ttl(snap, now_ts):
            dead.append(k)
    for k in dead:
        _l1_snapshot_cache.pop(k, None)
        _l1_after_scope_row_dropped(k)
        _l1_instrumentation["l1_cache_eviction_total"] += 1
        _l1_instrumentation["l1_cache_eviction_ttl_total"] += 1

    while len(_l1_snapshot_cache) > L1_MAX_CACHE_SCOPES:
        if _l1_scope_lru:
            k, _ = _l1_scope_lru.popitem(last=False)
            _l1_snapshot_cache.pop(k, None)
            _l1_generation_pop(k)
        else:
            k = next(iter(_l1_snapshot_cache.keys()))
            _l1_snapshot_cache.pop(k, None)
            _l1_after_scope_row_dropped(k)
        _l1_instrumentation["l1_cache_eviction_total"] += 1
        _l1_instrumentation["l1_cache_eviction_cap_total"] += 1

    pruned = reconcile_lru_with_snapshot(_l1_snapshot_cache, _l1_scope_lru)
    if pruned:
        _l1_instrumentation["l1_cache_reconcile_lru_pruned_total"] += pruned
    backfilled = ensure_lru_covers_snapshot(_l1_snapshot_cache, _l1_scope_lru)
    if backfilled:
        _l1_instrumentation["l1_cache_reconcile_lru_backfilled_total"] += backfilled


def _l1_attach_freshness_semantics(out: dict[str, Any], now_ts: float) -> None:
    """Explicit quote vs order-flow freshness — safe for cache-hit + live quote overlay."""
    from planes.l1_runtime import L1_ORDER_FLOW_STALE_SEC

    of_ts = out.get("order_flow_as_of_ts")
    if of_ts is None:
        of_ts = out.get("as_of_ts")
    try:
        of_ts_f = float(of_ts)
    except (TypeError, ValueError):
        of_ts_f = float(out.get("as_of_ts") or now_ts)
    of_age = max(0.0, now_ts - of_ts_f)
    out["order_flow_as_of_ts"] = of_ts_f
    out["order_flow_age_sec"] = round(of_age, 3)
    out["order_flow_stale"] = of_age >= L1_ORDER_FLOW_STALE_SEC
    fts = out.get("_live_plane_fast_ts")
    if fts is not None:
        try:
            out["quote_overlay_age_sec"] = round(max(0.0, now_ts - float(fts)), 3)
        except (TypeError, ValueError):
            out["quote_overlay_age_sec"] = None
    else:
        out["quote_overlay_age_sec"] = None
    out["quote_live_overlay_applied"] = bool(out.get("l1_live_overlay_applied"))


def _l1_sync_of_probe_cache_from_authoritative_build(
    tkr: str, row: Optional[dict], out: dict[str, Any], _now_ts: float
) -> None:
    """Keep quote-hook OF probe/sig aligned with _project_l1 (no extra OrderFlowEngine call)."""
    from planes.context_light import build_order_flow_input_probe, order_flow_compact_signature

    of_block = out.get("order_flow") or {}
    _l1_of_sig_cache_by_ticker[tkr] = order_flow_compact_signature(of_block)
    _l1_of_probe_by_ticker[tkr] = build_order_flow_input_probe(tkr, row)
    _l1_of_last_engine_mono_by_ticker[tkr] = time.monotonic()


def _l1_quote_hook_order_flow_signature(ticker: str) -> tuple[Any, ...]:
    """RC-404 (Cursor F10): order flow is ONE L2 computation CARRIED by L1 (ONE FAUCET).

    A quote tick does NOT recompute order flow. This returns the signature of the currently
    PUBLISHED order flow — kept in sync with every authoritative L1 build by
    `_l1_sync_of_probe_cache_from_authoritative_build` — so the quote materiality gate never
    rebuilds on order flow that did not change. Order flow changes only when the single L2
    OrderFlowEngine computation refreshes, which drives its own (L2) rebuild path. This replaced
    a second, chain-less `compute_order_flow_compact` invocation whose signature diverged from the
    value actually published on `/api/analytics/light`.
    """
    from planes.context_light import order_flow_compact_signature

    tkr = ticker.upper().strip()
    sig = _l1_of_sig_cache_by_ticker.get(tkr)
    if sig is not None:
        _l1_instrumentation["l1_of_quote_hook_reuse_total"] += 1
        return sig
    # Cold path: no authoritative build synced yet — the published OF is empty, whose signature
    # matches a fresh build with no acknowledged L2 order flow (fail-closed, never a thin recompute).
    return order_flow_compact_signature({})


def _resolve_l2_cache_entry_for_l1(ticker: str, expiry: Optional[str]) -> Optional[dict]:
    """Last acknowledged L2 row for Tier B merge (ms_dict + versioning fields).

    If the client requested an explicit expiry, only that cache key qualifies — never substitute
    another expiry's row (wrong-merge bug).
    """
    t = ticker.upper().strip()
    if expiry:
        ent = _state_cache.get((t, expiry))
        if ent and ent.get("ms_dict"):
            return ent
        return None
    latest = _latest_cache_entry_for_ticker(t)
    return latest[1] if latest else None


def _l2_refresh_in_progress_for_l1(ticker: str, expiry: Optional[str]) -> bool:
    """True if Tier C job is running for this scope (does not block L1)."""
    t = ticker.upper().strip()
    with _analytics_bg_lock:
        if _tier_c_inflight_key(t, expiry) in _analytics_inflight:
            return True
        if _tier_c_inflight_key(t, None) in _analytics_inflight:
            return True
    return False


def _project_l1(ticker: str, expiry: Optional[str], *, reason: str = "unknown") -> dict:
    """
    L1 near-real-time context projection — delegates to planes.context_light.
    Single authoritative compute path; no chain/DB/ML.

    Persists to _l1_snapshot_cache. Does not call merge_into_state (Tier C); Layer A quote
    truth is injected at HTTP read via apply_l1_live_quote_overlay when serving cache hits.
    """
    from planes.context_light import (
        L1BuildContext,
        build_l1_context,
        order_flow_compact_signature,
    )
    from planes.l1_runtime import build_input_fingerprint

    tkr = ticker.upper().strip()
    key = (tkr, expiry if expiry is not None else "__auto__")
    gen = _l1_next_generation(key)
    row = _lmp.get_quote(tkr)
    ent = _resolve_l2_cache_entry_for_l1(tkr, expiry)
    l1_eval_wall_ts = time.time()
    inflight = _l2_refresh_in_progress_for_l1(tkr, expiry)
    ctx = L1BuildContext(
        ticker=tkr,
        request_expiry=expiry,
        l0_row=row,
        l2_cache_entry=ent,
        now_ts=l1_eval_wall_ts,
        l2_analytics_refresh_in_progress=inflight,
        l1_generation=gen,
    )
    out = build_l1_context(ctx, derive_vwap_side_fn=derive_vwap_side)
    out["_l1_input_fingerprint"] = build_input_fingerprint(row, ent)
    of_block = out.get("order_flow") or {}
    out["_l1_of_signature"] = order_flow_compact_signature(of_block)
    # RC-281: my earlier reason claimed "the caller gates on ms > 0". There is no such gate —
    # the value is accumulated below and published as l1_build_ms, so an absent timing was a
    # measured zero that drags the latency average down and can mask an alarm. Absent timing
    # now contributes NOTHING to the sum and publishes as null.
    from numeric_contract import float_finite_or_none as _fin_ms
    ms = _fin_ms(out.get("l1_pipeline_ms"))
    _l1_instrumentation["l1_build_total"] += 1
    if ms is not None:
        # RC-291: the numerator AND its own denominator move together. RC-281 stopped an
        # absent timing entering the sum and left l1_build_total dividing it, so 19 builds
        # at 26 ms plus one unmeasured published 24.7 ms — under the 25 ms warn threshold.
        # Excluding a value from a mean while counting it in the divisor is the fabricated
        # zero written a different way. l1_build_total still counts BUILDS, which is a
        # different and correct question; the average now uses what was measured.
        _l1_instrumentation["l1_build_ms_sum"] = float(_l1_instrumentation["l1_build_ms_sum"]) + ms
        _l1_instrumentation["l1_build_ms_measured"] += 1
    _l1_instrumentation["l1_build_by_reason"][reason] += 1
    out["l1_instrumentation"] = {
        "l1_build_total": int(_l1_instrumentation["l1_build_total"]),
        "l1_build_reason": reason,
        "l1_build_ms": None if ms is None else round(ms, 3),  # RC-281: absent != 0 ms
        "l1_build_scope": {"ticker": tkr, "expiry": key[1]},
        "l2_merge_acknowledged": bool(out.get("l2_merge_acknowledged")),
        "l1_http_cache_hit_total": int(_l1_instrumentation["l1_http_cache_hit_total"]),
        "l1_quote_material_skip_total": int(_l1_instrumentation["l1_quote_material_skip_total"]),
        "l1_cache_eviction_total": int(_l1_instrumentation["l1_cache_eviction_total"]),
    }
    _l1_attach_freshness_semantics(out, l1_eval_wall_ts)
    _l1_snapshot_cache[key] = deepcopy(out)
    _l1_touch_scope(key)
    _l1_cache_maintain(l1_eval_wall_ts)
    _l1_sync_of_probe_cache_from_authoritative_build(tkr, row, out, l1_eval_wall_ts)
    try:
        _l1_notify_sse_after_authoritative_build(ticker, expiry)
    except Exception as ex:
        log.debug("L1 SSE notify after build: %s", ex)
    return out


def _l1_adaptive_materiality_context(ticker: str, row: Optional[dict[str, Any]], now_ts: float):
    """Session / VIX / microstructure context for L1 quote-path materiality (live plane only)."""
    from market_context import _derive_session
    from planes.l1_thresholds import AdaptiveMaterialityContext

    sess = _derive_session()
    vix_level = None
    for sym in ("$VIX", "VIX"):
        vq = _lmp.get_quote(sym)
        if not vq:
            continue
        try:
            v = float(vq.get("spot"))
            if v and v > 0:
                vix_level = v
                break
        except (TypeError, ValueError):
            continue
    spot = None
    spread_frac = None
    if row:
        try:
            if row.get("spot") is not None:
                spot = float(row["spot"])
        except (TypeError, ValueError):
            spot = None
        try:
            if row.get("spread") is not None:
                spread_frac = float(row["spread"])
        except (TypeError, ValueError):
            spread_frac = None
    return AdaptiveMaterialityContext(
        session_label=sess,
        vix_level=vix_level,
        spot=spot,
        spread_frac=spread_frac,
        now_ts=now_ts,
    )


def _l1_maybe_rebuild_quote_scope(
    ticker: str,
    expiry: Optional[str],
    *,
    of_sig: tuple[Any, ...],
) -> None:
    """Debounced quote path: L0+L2 materiality, then OF signature vs cached (probe-optimized OF on hook)."""
    from planes.l1_runtime import input_fingerprint_materially_changed, snapshot_expired_for_http_serve

    tkr = ticker.upper().strip()
    key = (tkr, expiry if expiry is not None else "__auto__")
    row = _lmp.get_quote(tkr)
    ent = _resolve_l2_cache_entry_for_l1(tkr, expiry)
    l1_eval_wall_ts = time.time()
    cached = _l1_snapshot_cache.get(key)
    if cached is not None and snapshot_expired_for_http_serve(cached, l1_eval_wall_ts):
        _project_l1(ticker, expiry, reason="quote_path_serve_age")
        return
    prev_fp = (cached or {}).get("_l1_input_fingerprint")
    adaptive_ctx = _l1_adaptive_materiality_context(tkr, row, l1_eval_wall_ts)
    if input_fingerprint_materially_changed(prev_fp, row, ent, ticker=tkr, adaptive_context=adaptive_ctx):
        _project_l1(ticker, expiry, reason="quote_material")
        return
    prev_of = (cached or {}).get("_l1_of_signature")
    if prev_of != of_sig:
        _project_l1(ticker, expiry, reason="quote_material_of")
        return
    _l1_instrumentation["l1_quote_material_skip_total"] += 1


def _l1_on_quote_updated(ticker: str) -> None:
    """L0 changed — materiality-gated L1 recompute per scope (OF signature via probe-optimized hook)."""
    t = ticker.upper().strip()
    of_sig = _l1_quote_hook_order_flow_signature(t)
    keys = [k for k in list(_state_cache.keys()) if isinstance(k, tuple) and len(k) >= 2 and k[0] == t]
    if not keys:
        _l1_maybe_rebuild_quote_scope(t, None, of_sig=of_sig)
        return
    for k in keys:
        _l1_maybe_rebuild_quote_scope(k[0], k[1], of_sig=of_sig)
    # L1-SSE-SCOPE-FIX: stream subscribers live on the __auto__ scope, which the
    # resolved-expiry rebuilds above never touch — keep it fresh too while
    # subscribed (same materiality gate; ~ms-scale build, no chain/DB/ML).
    if _l1_auto_scope_has_subscribers(t):
        _l1_maybe_rebuild_quote_scope(t, None, of_sig=of_sig)


def _l1_on_l2_snapshot_ready_auto_scope(ticker: str) -> None:
    """L1-SSE-SCOPE-FIX companion for the L2-ready hook: refresh the __auto__
    scope after a resolved-expiry Tier C build when stream subscribers exist."""
    if _l1_auto_scope_has_subscribers(ticker):
        _project_l1(ticker, None, reason="l2_snapshot_ready")


def _l1_on_l2_snapshot_ready(ticker: str, expiry: Optional[str]) -> None:
    """L2 acknowledged snapshot available — refresh L1 merge against new version."""
    _project_l1(ticker, expiry, reason="l2_snapshot_ready")
    if expiry is not None:
        _l1_on_l2_snapshot_ready_auto_scope(ticker)


def _l1_http_get_projection(ticker: str, expiry: Optional[str], *, force: bool = False) -> dict:
    """
    Single assembly function for Tier B JSON: GET /api/analytics/light and the SSE `payload` field
    (see L1_TIER_B_CHANNEL_PAYLOAD_MODE == \"full_overlay\").

    HTTP read path: authoritative snapshot from _l1_snapshot_cache + L0 overlay.
    Full _project_l1 only on cold miss, serve-age expiry, or force=true (explicit recompute).
    """
    from planes.l1_runtime import L1_HTTP_SERVE_MAX_AGE_SEC, snapshot_expired_for_http_serve

    tkr = ticker.upper().strip()
    l1_eval_wall_ts = time.time()
    _l1_cache_maintain(l1_eval_wall_ts)

    if force:
        return _project_l1(ticker, expiry, reason="http_force_refresh")

    key = (tkr, expiry if expiry is not None else "__auto__")
    cached = _l1_snapshot_cache.get(key)
    if cached is None:
        return _project_l1(ticker, expiry, reason="cold_start")

    if snapshot_expired_for_http_serve(cached, l1_eval_wall_ts):
        return _project_l1(ticker, expiry, reason="http_serve_stale_rebuild")

    _l1_instrumentation["l1_http_cache_hit_total"] += 1
    out = deepcopy(cached)
    _lmp.apply_l1_live_quote_overlay(out, tkr)
    _l1_touch_scope(key)
    built = float(out.get("as_of_ts") or out.get("_server_build_ts") or l1_eval_wall_ts)
    age = max(0.0, l1_eval_wall_ts - built)
    prev_inst = dict(out.get("l1_instrumentation") or {})
    out["l1_projection"] = {
        "mode": "authoritative_cache_read",
        "cache_age_sec": round(age, 3),
        "l1_http_serve_max_age_sec": L1_HTTP_SERVE_MAX_AGE_SEC,
    }
    out["l1_instrumentation"] = {
        **prev_inst,
        "l1_build_total": int(_l1_instrumentation["l1_build_total"]),
        "l1_http_cache_hit_total": int(_l1_instrumentation["l1_http_cache_hit_total"]),
        "l1_quote_material_skip_total": int(_l1_instrumentation["l1_quote_material_skip_total"]),
        "l1_cache_eviction_total": int(_l1_instrumentation["l1_cache_eviction_total"]),
        "l1_projection_read": True,
    }
    _l1_attach_freshness_semantics(out, l1_eval_wall_ts)
    return out


def _l1_scope_key(ticker: str, expiry: Optional[str]) -> tuple[str, str | None]:
    t = ticker.upper().strip()
    return (t, expiry if expiry is not None else "__auto__")


def _l1_auto_scope_has_subscribers(ticker: str) -> bool:
    """True when an /api/analytics/light/stream client is subscribed to this
    ticker's __auto__ scope (no explicit expiry — "whatever is current").

    L1-SSE-SCOPE-FIX (2026-07-22, measured live): stream clients subscribe with
    no expiry → scope (T, "__auto__"), but once the Tier C cache warms, every
    quote/L2-driven rebuild runs under the RESOLVED expiry scope — so the
    exact-scope notify in _l1_notify_sse_after_authoritative_build matched
    nothing and the light stream went silent for the rest of the session
    (14 boot-window deliveries, then 0 across 1,194 builds). The hooks below
    now also maintain the __auto__ scope while it has subscribers; each scope
    keeps its own cache entry, generation counter, throttle, and identity, so
    per-scope monotonicity is untouched.
    """
    auto_sk = (ticker.upper().strip(), "__auto__")
    with _l1_light_sse_lock:
        return any(csk == auto_sk for _, csk in _l1_light_sse_clients)


def _l1_notify_sse_after_authoritative_build(ticker: str, expiry: Optional[str]) -> None:
    """
    Push L1 to /api/analytics/light/stream subscribers after an authoritative _project_l1 build.
    Envelope wraps the same Tier B dict as HTTP (L1_TIER_B_CHANNEL_PAYLOAD_MODE == \"full_overlay\"):
    payload = _l1_http_get_projection(...) — cache read + L0 overlay on hits — no alternate projection-only path.
    """
    sk = _l1_scope_key(ticker, expiry)
    with _l1_light_sse_lock:
        if not _l1_light_sse_clients:
            return
        if not any(csk == sk for _, csk in _l1_light_sse_clients):
            return
    now_m = time.monotonic()
    with _l1_sse_throttle_lock:
        last = _l1_sse_last_emit_mono.get(sk, 0.0)
        if now_m - last < _L1_SSE_MIN_INTERVAL_SEC:
            _l1_sse_diag["l1_light_sse_events_throttled"] += 1
            return
        _l1_sse_last_emit_mono[sk] = now_m
    payload = _l1_http_get_projection(ticker, expiry, force=False)
    gen = int(payload.get("l1_generation") or 0)  # silent-zero-ok: generation 0 is the pre-first-publish state; every real generation is >= 1 so 0 can never impersonate one
    ts, fp = _l1_record_payload_identity(sk, gen, payload)
    env = {
        "l1_sse_schema": 1,
        "scope": {"ticker": sk[0], "expiry": sk[1]},
        "l1_generation": gen,
        "l1_server_build_ts": ts,
        "l1_payload_fingerprint": fp,
        "payload": payload,
    }
    _l1_put_thread_queue_notify(sk, env)


async def _l1_light_sse_dispatch_loop() -> None:
    """
    Drain cross-thread queue and fan out to per-connection asyncio queues (L1 light stream only).

    Backpressure (explicit, deterministic):
    - Thread queue (producer): on queue.Full, evict oldest global item until the newest
      (sk, env) fits — see _l1_put_thread_queue_notify.
    - Per-client asyncio.Queue(maxsize=8): on QueueFull, evict oldest pending event for
      that connection, then enqueue newest — see _l1_put_l1_client_queue (latest projection wins).
    - Clients must tolerate skipped intermediate generations; monotonic l1_generation +
      _server_build_ts (+ optional fingerprint) on the client preserves correctness.
    """
    loop = asyncio.get_running_loop()

    def _blocking_get():
        try:
            return _l1_sse_thread_queue.get(timeout=0.5)
        except queue.Empty:
            return None

    while True:
        item = await loop.run_in_executor(None, _blocking_get)
        if item is None:
            await asyncio.sleep(0.02)
            continue
        sk, env = item
        with _l1_light_sse_lock:
            clients = list(_l1_light_sse_clients)
        for q, csk in clients:
            if csk != sk:
                continue
            _l1_put_l1_client_queue(q, env)


def _latest_cache_entry_for_ticker(ticker: str) -> Optional[tuple[tuple, dict]]:
    """Most recently timestamped _state_cache row for this ticker (any expiry)."""
    t = ticker.upper().strip()
    best_k: Optional[tuple] = None
    best_ts = 0.0
    for k, v in _state_cache.items():
        if not isinstance(k, tuple) or len(k) < 2:
            continue
        if k[0] != t:
            continue
        if not v.get("ms_dict"):
            continue
        ts = float(v.get("ts") or 0.0)  # silent-zero-ok: epoch-0 ancient sentinel — an undated entry sorts oldest, never freshest
        if ts >= best_ts:
            best_ts = ts
            best_k = k
    if best_k is None:
        return None
    return (best_k, _state_cache[best_k])


def _tier_a_live_state_dict(ticker: str, expiry: Optional[str]) -> dict:
    """
    Tier A — live-only JSON for GET /api/live/state.
    live_market_plane + optional single REST quote bootstrap. No chain, exposures,
    build_market_state, DB, news, or model health. Session from ET clock only.
    """
    t0_mono = time.monotonic()
    tkr = ticker.upper().strip()
    sess = _derive_session()
    row = _lmp.get_quote(tkr)
    client = None
    try:
        client = get_client()
    except HTTPException as he:
        if not _plane_fast_quote_has_spot(row):
            if _schwab_auth_http_unavailable(he):
                return {
                    "_tier": "A_live",
                    "ticker": tkr,
                    "selected_exp": expiry,
                    "session_label": sess,
                    "state_error": "token_invalid",
                    "error": "token_invalid",
                    "state_error_detail": str(he.detail or ""),
                    "remediation": "Run: python reauth_schwab.py --manual",
                    "_server_build_ts": time.time(),
                    "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
                    "_endpoint": "/api/live/state",
                }
            raise
    if (not row or row.get("spot") is None) and client:
        q_resp = _memoized_quote_response(tkr, client=client)   # RC-112/W3-C8: one vendor faucet
        if q_resp and q_resp.status_code == 200:
            q_json = q_resp.json()
            _node = q_json.get(tkr.upper()) or q_json.get(tkr) or {}
            pq = _parse_quote_node_session_fields(_node)
            spot_source = pq["spot_source"]
            spot = pq["spot"]
            bid, ask = pq["bid"], pq["ask"]
            if spot and float(spot) > 0:
                sf = float(spot)
                quote_ts = pq["quote_ts"]
                server_received_ts = time.time()
                row = {
                    "ticker": tkr,
                    "spot": sf,
                    "bid": bid,
                    "ask": ask,
                    "spot_disp": f"{sf:.2f}",
                    "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
                    "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
                    "spread": None,
                    "spread_pts": None,
                    "quote_ingestion": "rest_tier_a",
                    "exchange_quote_ts": quote_ts,
                    "quote_time_source": "schwab_rest_quote" if quote_ts is not None else "unavailable",
                    "server_received_ts": server_received_ts,
                    "fast_generation_id": _lmp.next_fast_generation(tkr),
                    "quote_source_detail": {
                        "spot": spot_source,
                        "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
                        "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
                        "mid": "unavailable_missing_mark_and_bid_ask",
                        "spread": "unavailable_missing_bid_or_ask",
                        "quote_ts": pq["quote_ts_clock"],  # M6: exchange clock carried in exchange_quote_ts
                        "carried_forward": False,
                    },
                }
                mid = pq["quote_mid"]
                mid_src = pq["mid_source"]
                if mid is not None:
                    row["quote_mid"] = mid
                    row["mid_source"] = mid_src
                row["quote_source_detail"]["mid"] = mid_src or "unavailable_missing_mark_and_bid_ask"
                if bid is not None and ask is not None:
                    try:
                        b_px, a_px = float(bid), float(ask)
                        raw_spread = round(a_px - b_px, 4)
                        row["spread_pts"] = raw_spread if raw_spread >= 0.0 else None
                        row["spread_pts_source"] = "derived_bid_ask_pts"
                        if mid is not None and mid > 0:
                            row["spread"] = (a_px - b_px) / mid
                            row["spread_source"] = (
                                "derived_bid_ask_mid_fraction"
                                if mid_src == "derived_bid_ask_mid"
                                else "derived_bid_ask_fraction_schwab_mark_denom"
                            )
                        row["quote_source_detail"]["spread"] = "schwab_bid_ask"
                    except (TypeError, ValueError):
                        pass
    if not row or row.get("spot") is None:
        return {
            "_tier": "A_live",
            "ticker": tkr,
            "selected_exp": expiry,
            "session_label": sess,
            "state_error": "no_quote",
            "state_error_detail": "No live plane or REST quote available yet.",
            "_server_build_ts": time.time(),
            "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
            "_endpoint": "/api/live/state",
        }
    spot_f = float(row["spot"])
    from numeric_contract import float_finite_or_none as _fin
    # single source: finite bid/ask (raw float() admitted NaN into spread AND the bid/ask
    # echoed into `out` below); canonical reader also removes the try/except.
    bid = _fin(row.get("bid"))
    ask = _fin(row.get("ask"))
    spread_dollar = None
    if bid is not None and ask is not None:
        spread_dollar = round(ask - bid, 4)
    out: dict = {
        "_tier": "A_live",
        "ticker": tkr,
        "selected_exp": expiry,
        "session_label": sess,
        "spot": spot_f,
        "bid": bid,
        "ask": ask,
        "spot_disp": row.get("spot_disp"),
        "bid_disp": row.get("bid_disp"),
        "ask_disp": row.get("ask_disp"),
        "quote_mid": row.get("quote_mid"),
        "mid_source": row.get("mid_source"),
        "spread": spread_dollar,
        "spread_semantic": "dollar",
        "spread_pts": row.get("spread_pts"),
        "spread_source": (
            "derived_bid_ask_pts"
            if spread_dollar is not None
            else row.get("spread_source")
        ),
        "spread_pts_source": row.get("spread_pts_source"),
        "quote_source_detail": row.get("quote_source_detail"),
        "quote_ingestion": row.get("quote_ingestion"),
        "quote_time_source": row.get("quote_time_source"),
        "server_received_ts": row.get("server_received_ts"),
        "exchange_quote_ts": row.get("exchange_quote_ts"),
        "fast_generation_id": row.get("fast_generation_id"),
        "_live_plane_fast_ts": row.get("exchange_quote_ts"),
        "_server_build_ts": time.time(),
        "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
        "_endpoint": "/api/live/state",
    }
    try:
        from order_flow_streaming import get_streaming_diagnostics, get_plane_authority_for_ticker

        out["streaming_plane"] = {
            **get_streaming_diagnostics(),
            "plane_quote_authority": get_plane_authority_for_ticker(tkr),
        }
    except Exception:
        out["streaming_plane"] = {}
    lw: dict = {}
    ck_hit: Optional[dict] = None
    if expiry:
        c = _state_cache.get((tkr, expiry))
        if c and c.get("ms_dict"):
            ck_hit = c
    if ck_hit is None:
        h2 = _latest_cache_entry_for_ticker(tkr)
        if h2:
            ck_hit = h2[1]
    if ck_hit and ck_hit.get("ms_dict"):
        md0 = ck_hit["ms_dict"]
        for k in (
            "vix",
            "pcr_val",
            "spy_chg_pct",
            "qqq_chg_pct",
            "iwm_chg_pct",
            "spy_last",
            "qqq_last",
            "iwm_last",
            "dte_warn",
            "dte_color",
        ):
            if k in md0 and md0[k] is not None:
                lw[k] = md0[k]
    if lw:
        out["analytics_lightweight"] = lw
    _lmp.merge_into_state(out, tkr)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CORE DATA FETCH — runs the full pipeline, returns MarketState dict
# When log_only=True: runs the full pipeline for DB logging but returns
# a minimal dict (saves serialization overhead for background tickers).
# ─────────────────────────────────────────────────────────────────────────────
def _finalize_production_decision(ms_dict: dict, route: str) -> dict:
    """Stamp immutable decision_id + release_id and persist for I-31 reconstruction.

    EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: records the persist OUTCOME on
    ms_dict["_decision_persist_landed"] so the ledger "decision" surface is
    marked landed only when the row actually inserted — a refused or skipped
    write leaves the ledger honestly OPEN/INCOMPLETE, never falsely complete.
    """
    stamp_decision_bundle(ms_dict, route=route)
    ms_dict["_decision_persist_landed"] = False
    if _HAS_SIGNALS and ms_dict.get("decision_id"):
        try:
            from db import DB_PATH

            _persisted_id = persist_stamped_decision(ms_dict, route=route, db_path=DB_PATH)
            ms_dict["_decision_persist_landed"] = bool(_persisted_id)
        except Exception as exc:
            log.warning("production decision persist failed route=%s: %s", route, exc)
    return ms_dict


def carried_price_levels_match_snapshot(entry, pl_date, pl_generation, today: str, snap) -> bool:
    """Reuse the /api/state PriceLevels carry only when it is THIS snapshot generation.

    Wall-clock PRICE_LEVELS_CACHE_SEC is not a generation identity: a 1s-old carry of
    generation N is the wrong book once /api/levels has materialized N+1 (RC-416).
    """
    if entry is None or snap is None or not today:
        return False
    if str(pl_date or "") != str(today):
        return False
    gen = getattr(snap, "generation", None)
    if gen is None:
        return False
    try:
        cached_gen = int(pl_generation) if pl_generation is not None else None
        entry_gen = getattr(entry, "level_generation", None)
        entry_gen_i = int(entry_gen) if entry_gen is not None else None
        snap_gen = int(gen)
    except (TypeError, ValueError):
        return False
    return cached_gen == snap_gen and entry_gen_i == snap_gen


def _fetch_state(
    ticker: str,
    expiry: Optional[str],
    log_only: bool = False,
    mkt_ctx=None,
    *,
    update_source: Optional[str] = None,
    logger_source: Optional[str] = None,
) -> dict:
    _fetch_start_mono = time.monotonic()
    # Cursor-audit F1: canonicalize the ticker at this single chokepoint. Unlike the
    # terrain/quote/bars endpoints, the analytics/state/warm entry points funnel here WITHOUT
    # first calling ticker_storage_key — so an index root typed or POSTed bare ("SPX") would
    # otherwise take the equity branch of resolve_chain_strike_count / _chain_to_date_for and
    # request the full multi-year book with no strike cap and no date bound (the RC-149/RC-491
    # budget blowout). Normalizing here gives every downstream call — quote, chain, snapshot
    # write — the same "$"-gated protections as "$SPX". ticker_storage_key is idempotent and
    # leaves equities unchanged.
    ticker = ticker_storage_key(ticker)
    # UI_05 tail attribution (def-free marks, same pattern as _stage_marks):
    # splits _chain_ms so an untraced gap can never hide again.
    _chain_window_marks: list[tuple[str, float]] = []
    # LIVE_OPERATOR_MODE_RESET_V1 Step 3 — TICKER-PREVIEW-NO-ENROLL applies here too:
    # a Tier C recompute for a viewed symbol refreshes last-seen only. Enrollment into
    # logging_universe is explicit (/api/logger/add | /api/logger/pin).
    _touch_tracked_ticker_view(ticker)
    _ed_db = get_db() if _HAS_SIGNALS else None
    try:
        from live_pipeline_diag import emit_fetch_state_start

        emit_fetch_state_start(ticker=ticker, log_only=log_only)
    except Exception as e:
        log.debug("emit_fetch_state_start failed ticker=%s: %s", ticker, e, exc_info=True)

    client = get_client()
    from time_et import now_et as _eastern_now

    now_et = _eastern_now()
    _chain_window_marks.append(("chain_window_preamble_ms", time.monotonic()))

    # ── Global market context — session_label before quote parse (shared across tickers) ──
    if mkt_ctx is None:
        mkt_ctx = _get_mkt_ctx(client)
    session_label = mkt_ctx.session_label   # "RTH" | "Pre-Market" | "After-Hours" | "Closed"
    _chain_window_marks.append(("chain_window_mkt_ctx_ms", time.monotonic()))

    # ── Chain + quote in parallel (independent Schwab calls — saves one RTT on cold Tier C) ──
    # These futures must NOT run on _analytics_executor: _fetch_state itself occupies an
    # analytics worker, so nested submit+.result() on the same 4-worker pool self-deadlocks
    # once ≥3 Tier C jobs run concurrently (all workers block at .result() while their
    # chain/quote tasks sit queued behind them — py-spy proof 2026-07-04, all four
    # ed_analytics_bg threads parked here). Same class as the candle-seeding fix below;
    # use the route-offload pool, whose tasks never submit back into the analytics pool.
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — executor-pool scheduling only; the Schwab chain and
    #   quote reads themselves (safe_get_chain / _safe_get_quote_with_retry) are unchanged.
    # Derived-field disposition: none required (no derived field touched).
    # All consumers checked: yes — c_resp/q_resp consumed identically downstream.
    # SCHWAB_CSV_CHECKED
    # TIER_C_CHAIN_FETCH_GATE_IMPLEMENTATION_V1: chain call routed through
    # _gated_safe_get_chain (same call shape, serialized cross-ticker; fail-open).
    _chain_gate_wait_sec: float = 0.0
    _chain_fetch_pure_sec: Optional[float] = None
    # UI_05_OPERATOR_PRIORITY_ADMISSION_V1: operator-facing recomputes acquire
    # the (still single-slot) chain gate ahead of queued background acquirers.
    # log_only pipelines are background by definition.
    _chain_priority = (not log_only) and _is_operator_priority_update_source(update_source)
    try:
        # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1: log_only joins the
        # shutdown inline path — background pipelines stay out of the shared
        # route pool; operator-facing recomputes keep bounded parallelism.
        if _analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only):
            c_resp, _chain_gate_wait_sec, _chain_fetch_pure_sec = _gated_safe_get_chain(
                client, ticker, strike_count=resolve_chain_strike_count(ticker),  # RC-59: one faucet
                to_date=_chain_to_date_for(ticker, expiry),   # RC-494: bound index expiry count (keep an explicit far pick)
                from_date=_chain_from_date_for(ticker, expiry),   # Cursor-audit F2: bound near edge for a far pick
                priority=_chain_priority,
            )
            q_resp = _memoized_quote_response(ticker, client=client)   # RC-112/W3-C8: one vendor faucet
        else:
            # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: leaf futures run on
            # the dedicated recompute-leaf pool — never behind serve bodies.
            # UI_05 residual: PRIORITY recomputes use their own bounded leaf
            # lane so cold-guest chain/quote legs never queue behind
            # background idle-refresh leaf bursts (measured 13.7-21s FIFO
            # wait at pure-fetch 0.5-0.8s).
            _cq_pool = (
                _get_priority_leaf_executor()
                if _chain_priority
                else _get_recompute_leaf_executor()
            )
            _chain_fut = _cq_pool.submit(
                _gated_safe_get_chain, client, ticker,
                strike_count=resolve_chain_strike_count(ticker),   # RC-59: one faucet
                to_date=_chain_to_date_for(ticker, expiry),   # RC-494: bound index expiry count (keep an explicit far pick)
                from_date=_chain_from_date_for(ticker, expiry),   # Cursor-audit F2: bound near edge for a far pick
                priority=_chain_priority,
            )
            # RC-112 recurrence 2 (v10 audit, server.py:6228): this pool leaf passed the raw
            # vendor fetch BY REFERENCE, so the paren-matching structural test never saw it —
            # the hot parallel path bypassed the memo while the inline branch above used it.
            # The lock now counts NAME references, not call syntax.
            _quote_fut = _cq_pool.submit(_memoized_quote_response, ticker, client=client)
            c_resp, _chain_gate_wait_sec, _chain_fetch_pure_sec = _chain_fut.result()
            q_resp = _quote_fut.result()
    except SchwabAuthError as e:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "token_invalid",
                "remediation": e.remediation,
                "message": str(e),
            },
        ) from e
    _chain_window_marks.append(("chain_window_leaf_wall_ms", time.monotonic()))
    if c_resp is None or c_resp.status_code != 200:
        # Cursor-audit F4: carry the real vendor status so the background logger's quarantine can
        # tell a PERMANENT symbol refusal (4xx — e.g. SATS 404) from a transient venue error
        # (timeout/5xx/429). Detail still starts with "Chain fetch failed" for existing consumers.
        raise HTTPException(status_code=502,
                            detail=f"Chain fetch failed [vendor_status={getattr(c_resp, 'status_code', None)}]")
    c_json = c_resp.json()
    contracts     = flatten_chain_contracts(c_json)
    _t_after_chain_mono = time.monotonic()
    _chain_window_marks.append(("chain_window_contracts_parse_ms", _t_after_chain_mono))

    # totalVolume: WebSocket TOTAL_VOLUME preferred; else chain underlying (include_underlying_quote)
    _total_vol = None
    try:
        from order_flow_live_state import get_stream_volume
        _stream_vol = get_stream_volume(ticker)
        if _stream_vol is not None:
            _total_vol = _stream_vol
    except (ImportError, AttributeError):
        pass
    if _total_vol is None:
        _chain_underlying = c_json.get("underlying") or {}
        if isinstance(_chain_underlying, dict):
            _total_vol = _safe_float_quote(_chain_underlying.get("totalVolume"))

    # Quote fetched in parallel with chain above — parse here after chain JSON work.
    if q_resp is None or q_resp.status_code != 200:
        raise HTTPException(status_code=502,   # Cursor-audit F4: carry vendor status (see chain raise)
                            detail=f"Quote fetch failed [vendor_status={getattr(q_resp, 'status_code', None)}]")
    q_json = q_resp.json()
    _t_after_quote_mono = time.monotonic()
    _t_after_quote_wall = time.time()

    # ── Compute-stage instrumentation (lane 3, 2026-07-05) — diagnostic only.
    # The transport audit measured _compute_ms at 13–27s but could not attribute it;
    # these perf_counter deltas split the compute segment into named stages, stamped on the
    # payload as _compute_breakdown. No decision logic, cadence, or gate reads them.
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — diagnostic timing capture only; no market
    #   field read, derivation, emission, or actionability logic changed.
    # Derived-field disposition: none required.
    # All consumers checked: yes — payload diagnostic key + one log line only.
    # SCHWAB_CSV_CHECKED
    # Def-free marks (mega1 section-inventory gate counts every def): append
    # (stage, perf_counter) pairs; consecutive deltas are computed at stamp time.
    _stage_t0 = time.perf_counter()
    _stage_marks: list[tuple[str, float]] = []

    _node_q = q_json.get(ticker.upper()) or q_json.get(ticker) or {}
    _session_q = _parse_quote_node_session_fields(_node_q)
    parsed_last = _session_q["last"]
    parsed_mark = _session_q["mark"]
    parsed_bid = _session_q["bid"]
    parsed_ask = _session_q["ask"]
    parsed_quote_time = _session_q["quote_time"]
    parsed_trade_time = _session_q["trade_time"]
    # SINGLE SPOT AUTHORITY (RC-14): route the analytics-card spot through resolve_spot,
    # reusing the quote node already fetched above (no extra round-trip). It now carries the
    # same value + precedence as /api/spot and the terrain card, and gains the stored-trade
    # fallback this path lacked (an empty live quote used to yield None / a bare mark here).
    spot, _spot_source, _spot_ts = resolve_spot(ticker, quote_node=_node_q, chain_json=None)
    bid    = parsed_bid
    ask    = parsed_ask

    global _last_spread_by_ticker, _last_spread_ts_by_ticker
    _quote_spread_pts = (
        round(float(ask) - float(bid), 4) if (bid is not None and ask is not None) else None
    )
    # single source: finite mark (the bare `> 0` gate let +inf through -> inf mid -> inf spread_frac)
    from numeric_contract import float_finite_or_none as _fin_mk
    _pm = _fin_mk(parsed_mark)
    _quote_mid_for_spread = _pm if (_pm is not None and _pm > 0) else None
    _quote_spread_frac = (
        round(_quote_spread_pts / _quote_mid_for_spread, 6)
        if (
            _quote_spread_pts is not None
            and _quote_mid_for_spread is not None
            and _quote_mid_for_spread > 0
        )
        else None
    )
    _quote_spread = _quote_spread_pts
    _quote_spread_source = "schwab_bid_ask_live" if _quote_spread_pts is not None else "unavailable_missing_bid_or_ask"
    _quote_spread_frac_source = (
        "derived_bid_ask_fraction_schwab_mark_denom"
        if _quote_spread_frac is not None
        else None
    )
    _quote_spread_age_ms = 0 if _quote_spread_pts is not None else None
    if _quote_spread_pts is not None:
        _last_spread_by_ticker[ticker] = _quote_spread_pts
        _last_spread_ts_by_ticker[ticker] = _t_after_quote_wall
    elif ticker in _last_spread_by_ticker and ticker in _last_spread_ts_by_ticker:
        _quote_spread_source = "cached_last_valid_not_tradeable"
        _quote_spread_age_ms = max(0, int((_t_after_quote_wall - _last_spread_ts_by_ticker[ticker]) * 1000))

    # Remaining volume fields from quote REST if stream + chain underlying had none
    if _total_vol is None:
        _quote_node = _node_q if isinstance(_node_q, dict) else {}
        if not (_quote_node.get("quote") or _quote_node.get("extended")):
            _quote_node = q_json.get(ticker.upper()) or q_json.get(ticker) or {}
            if not isinstance(_quote_node, dict):
                if isinstance(q_json, list):
                    for item in q_json:
                        if isinstance(item, dict) and (item.get("symbol") or item.get("key") or "").upper() == ticker.upper():
                            _quote_node = item
                            break
                else:
                    _quote_node = {}
            if not _quote_node and isinstance(q_json, dict) and (q_json.get("quote") or q_json.get("regular")):
                _quote_node = q_json
        _quote_dict = _quote_node.get("quote") or {} if isinstance(_quote_node, dict) else {}
        _extended = _quote_node.get("extended") or {} if isinstance(_quote_node, dict) else {}
        _total_vol = (
            _safe_float_quote(_quote_dict.get("totalVolume"))
            or _safe_float_quote(_extended.get("totalVolume"))
        )

    # ── Select expiry ─────────────────────────────────────────────────────────
    expiries     = _expiries_from_contracts(contracts)
    _today_str   = now_et.strftime("%Y-%m-%d")
    if expiry and expiry < _today_str:
        log.warning("Rejecting past expiry %s for %s (today=%s) — using default", expiry, ticker, _today_str)
        expiry = None
    selected_exp = expiry or _default_expiry(expiries, ticker)
    if not selected_exp:
        log.warning("_fetch_state: no valid expiry for %s — skipping", ticker)
        try:
            spot_disp = f"{float(spot):.2f}" if spot else "—"
        except (TypeError, ValueError):
            spot_disp = "—"
        _minimal = {
            "ticker": ticker.upper(),
            "selected_exp": None,
            "expiries": [e for e in expiries if e >= _today_str],
            "state_error": "no_valid_expiry",
            "state_error_detail": (
                "No usable option expiry (empty chain or all expiries past). "
                "WTDS / Call need an options chain — try another symbol or refresh."
            ),
            "spot": float(spot) if spot else None,
            "spot_disp": spot_disp,
            "bid_disp": "—",
            "ask_disp": "—",
            "session_label": session_label,
            "call_signal": "wait",
            "call_conviction": "low",
            "fusion_available": False,
            "dominant_dir": "flat",
            "rules_headline": "—",
        }
        _minimal_end_mono = time.monotonic()
        _minimal["_server_build_ts"] = time.time()
        _minimal["_pipeline_ms"] = round((_minimal_end_mono - _fetch_start_mono) * 1000)
        _minimal["_chain_ms"] = round((_t_after_chain_mono - _fetch_start_mono) * 1000)
        _minimal["_quote_ms"] = round((_t_after_quote_mono - _t_after_chain_mono) * 1000)
        _minimal["_compute_ms"] = round((_minimal_end_mono - _t_after_quote_mono) * 1000)
        if update_source is not None:
            _minimal["_update_source"] = update_source
        from trade_impacting_gate import apply_trade_impacting_gate

        apply_trade_impacting_gate(_minimal, route="server._fetch_state.no_valid_expiry")
        _lmp.merge_into_state(_minimal, ticker)
        return _finalize_production_decision(_minimal, "server._fetch_state.no_valid_expiry")
    contracts_use, _exp_slice_source = _filter_contracts_by_selected_expiry(contracts, selected_exp)
    _kl_expiry_source = _kl_expiry_source_label(
        expiry_param=expiry,
        slice_source=_exp_slice_source,
    )
    if not contracts_use:
        log.warning(
            "_fetch_state: no contracts for selected_exp=%s ticker=%s (strict expirationDate slice)",
            selected_exp,
            ticker,
        )
        try:
            spot_disp = f"{float(spot):.2f}" if spot else "—"
        except (TypeError, ValueError):
            spot_disp = "—"
        _exp_err = stamp_decision_bundle({
            "ticker": ticker.upper(),
            "selected_exp": selected_exp,
            "expiries": [e for e in expiries if e >= _today_str],
            "state_error": "expiry_slice_empty",
            "state_error_detail": (
                f"No option contracts with Schwab expirationDate={selected_exp}. "
                "Refusing full-chain fallback for KEY LEVELS / exposures."
            ),
            "kl_expiry_source": _kl_expiry_source,
            "spot": float(spot) if spot else None,
            "spot_disp": spot_disp,
            "bid_disp": "—",
            "ask_disp": "—",
            "session_label": session_label,
            "call_signal": "wait",
            "call_conviction": "low",
            "fusion_available": False,
            "dominant_dir": "flat",
            "rules_headline": "—",
        })
        _exp_err["_server_build_ts"] = time.time()
        if update_source is not None:
            _exp_err["_update_source"] = update_source
        _lmp.merge_into_state(_exp_err, ticker)
        return _exp_err

    # ── Exposures ─────────────────────────────────────────────────────────────
    if spot is None:
        return stamp_decision_bundle({
            "ticker": ticker.upper(),
            "selected_exp": selected_exp,
            "expiries": [e for e in expiries if e >= _today_str],
            "state_error": "missing_canonical_spot",
            "state_error_detail": "Schwab quote missing positive lastPrice and mark; refusing to compute state from synthetic spot.",
            "spot": None,
            "spot_disp": "—",
            "bid": bid,
            "ask": ask,
            "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
            "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
            "quote_source_detail": {
                "spot": "unavailable_missing_last_and_mark",
                "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
                "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
                "spread": _quote_spread_source,
                "spread_age_ms": _quote_spread_age_ms,
                "carried_forward": _quote_spread_source == "cached_last_valid_not_tradeable",
            },
            "server_ts": time.time(),
        })
    spot_f    = float(spot)

    # Feed tick into candle accumulators
    _tick_ts = parsed_quote_time or parsed_trade_time

    # Seed candles from Schwab price history when the canonical 1m grid is stale —
    # first visit OR a gap since the last completed bar (background-logged tickers
    # are polled ~1×/15min; tick-built bars alone leave the outcome grid ~94% empty).
    # Canonical (1m) drives snapshot/state; 5m remains derived context.
    _seed_ref_ts = float(_tick_ts) if _tick_ts is not None else time.time()
    if _candles_1m.grid_stale(ticker, _seed_ref_ts, CANDLE_RESEED_GAP_SECONDS):
        def _seed_candles(freq_min: int) -> None:
            resp = safe_get_price_history(client, ticker, frequency_minutes=freq_min, period_days=1)
            if resp and resp.status_code == 200:
                payload = resp.json()
                if "candles" not in payload:
                    raise ValueError(
                        f"Schwab pricehistory response missing 'candles' key (status={resp.status_code})"
                    )
                raw_bars = payload["candles"]
                if freq_min == 5:
                    _candles_5m.seed(ticker, raw_bars)
                    log.info("Seeded %s 5m candles: %d bars from price history", ticker, len(raw_bars))
                else:
                    _candles_1m.seed(ticker, raw_bars)
                    log.info("Seeded %s 1m candles: %d bars from price history", ticker, len(raw_bars))

        try:
            client = get_client()
            if _log_only_inline_leaf_fetches(log_only):
                # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1: background
                # log_only seeds run sequentially inline — identical calls,
                # identical consumption, no shared-pool occupancy.
                _seed_candles(5)
                _seed_candles(1)
            else:
                # UI-MAXIMIZE: parallel seed — must NOT use _analytics_executor (same pool as
                # _fetch_state worker); nested submit+.result() deadlocks all Tier C jobs.
                # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: dedicated leaf pool.
                # UI_05 residual: priority recomputes seed on the priority
                # leaf lane (same selection as the chain/quote leg).
                _seed_pool = (
                    _get_priority_leaf_executor()
                    if _chain_priority
                    else _get_recompute_leaf_executor()
                )
                _f5 = _seed_pool.submit(_seed_candles, 5)
                _f1 = _seed_pool.submit(_seed_candles, 1)
                _f5.result(timeout=45)
                _f1.result(timeout=45)
        except Exception as e:
            log.debug("Candle seeding failed for %s: %s", ticker, e)

    if _tick_ts is not None:
        _candles_5m.tick(ticker, spot_f, _tick_ts, total_volume=_total_vol)
        _candles_1m.tick(ticker, spot_f, _tick_ts, total_volume=_total_vol)

    _bars_5m_count = len(_candles_5m.get_bars(ticker))
    _bars_1m_count = len(_candles_1m.get_bars(ticker))
    log.info(f"Candles: {ticker} 5m={_bars_5m_count} bars, 1m={_bars_1m_count} bars")

    exposures, diag = compute_exposures_by_strike(contracts_use, spot=spot_f, require_oi=True)
    from math_exposure_core import key_level_strikes_with_gamma
    _cons_strikes = sorted(float(k) for k in exposures.keys())
    _gamma_strikes = key_level_strikes_with_gamma(exposures) or _cons_strikes
    _institutional_pin = (
        pick_net_gex_peak_strike(exposures, _gamma_strikes, institutional=True)
        if _gamma_strikes
        else None
    )

    rows      = build_summary_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS)
    walls     = build_walls_rows(exposures, spot_f)
    # RC-420: CONSENSUS gamma/delta wall strikes are terrain SSOT (wide chain).
    # Selected-expiry analytics must not occupy walls[0] while kl_* paints terrain.
    from math_levels import consensus_walls_bind_terrain_ssot
    walls = consensus_walls_bind_terrain_ssot(walls, terrain_cache_get(ticker) or {})
    totals    = build_totals_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS, contracts_for_iv=contracts_use)

    # ── Gamma Flip + Void Zones ───────────────────────────────────────────────
    # FIND-GAMMA-FLIP-METHOD-V1: canonical profile (gamma recomputed at hypothetical spot).
    # The old cumulative-sum method was DISPROVED 2026-07-19 on a real SPY reference chain
    # (corr 0.086, never crossed zero). The confidence flag is mandatory: a narrow chain
    # misplaces the flip by ~3.6%, so it must never be presented as trustworthy.
    _gamma_flip, _gamma_flip_conf, _gamma_flip_diag = compute_gamma_flip_v2(contracts_use, spot_f)
    _gamma_voids = compute_gamma_void_zones(exposures, spot_f)
    # RC-134: analytics compute_hvl / compute_max_pain deleted here — they only fed dead
    # Tier-C kwargs that never wrote payload keys (SSOT is terrain overlay).

    # Feed ATM IV into tracker for direction detection (vanna context)
    _t0 = totals[0] if totals else None
    _atm_iv = getattr(_t0, "atm_iv", None) if _t0 else None
    _iv_tracker.tick(ticker, _atm_iv)
    _iv_direction = _iv_tracker.direction(ticker)

    consensus_summary = rows[0] if rows else None
    _stage_marks.append(("exposures_key_levels", time.perf_counter()))

    # ── Charm — computed HERE, before build_market_state, so signals engine
    # receives real values. charm_direction uses raw strings "buying"/"selling"/"neutral"
    # which is what signals.py expects for Greek bias scoring.
    _charm_net    = None
    _charm_dir    = None
    _charm_toward = None
    _charm_mag    = None
    _charm_drivers = []
    try:
        from math_exposure import compute_net_charm
        # Per-tick diagnostic — demoted from INFO: fires every refresh regardless of
        # outcome, no operator-actionable signal (success and failure logs below carry it).
        log.debug(f"Charm: {ticker} calling compute_net_charm with {len(contracts_use)} contracts, exp={selected_exp}")
        # RC-345 / F18: charm measures the net-charm DIRECTION, not a target STRIKE. It must
        # NOT borrow the net-GEX peak (a gamma quantity) as its drift target — that was a
        # different-Greek substitution masquerading under the charm name. drift_toward is
        # WITHHELD (governed absence); the net-GEX peak keeps its own field, net_gex_peak.
        _charm_raw = compute_net_charm(
            contracts_use, spot_f, selected_exp, drift_toward_strike=None
        )
        _charm_used = _charm_raw.get("contracts_used", 0)
        _charm_err  = _charm_raw.get("error", "")
        if _charm_used > 0:
            _charm_net     = _charm_raw["net_charm_daily"]
            _charm_dir     = _charm_raw["charm_direction"]
            _charm_toward  = _charm_raw.get("drift_toward")
            _charm_mag     = _charm_raw.get("charm_magnitude")
            # RC-85: the read of "top_drivers" is GONE. compute_net_charm has never emitted that
            # key — it returns call_charm_daily, charm_direction, charm_magnitude, contracts_used,
            # drift_toward, error, net_charm_daily, put_charm_daily (its duplicate `gamma_pin`
            # alias was deleted by RC-302) — so
            # `.get("top_drivers", [])` returned [] on every call since the line was written, and
            # charm_top_drivers has been permanently empty. The default was the whole problem: []
            # reads as "computed, no drivers found" when the truth is "never computed", so the
            # name mismatch had no symptom. _charm_drivers stays [] from its initialiser above,
            # which is the same value WITHOUT the claim that a producer was consulted. Populating
            # it needs compute_net_charm to actually rank the contributing strikes; that is a
            # feature, not a rename, and it is not being smuggled in behind a default.
            # RC-292: the log label must not call charm's (withheld) drift target a pin —
            # a pin claim ships only as pin_candidate after qualification.
            log.info(f"Charm: {ticker} ✅ net={_charm_net:.0f} dir={_charm_dir} mag={_charm_mag} drift_toward={_charm_toward} "
                     f"({_charm_used} contracts)")
        else:
            from math_exposure_core import charm_compute_unavailable_log_level

            _lvl = charm_compute_unavailable_log_level(_charm_err)
            if _lvl == logging.DEBUG:
                _log_fn = log.debug
            elif _lvl == logging.INFO:
                _log_fn = log.info
            else:
                _log_fn = log.warning
            _log_fn(
                "Charm: %s ❌ 0 contracts matched. error='%s' input_contracts=%s exp=%s",
                ticker,
                _charm_err,
                len(contracts_use),
                selected_exp,
            )
    except Exception as _ce:
        import traceback
        log.warning(f"Charm: {ticker} 💥 EXCEPTION: {_ce}\n{traceback.format_exc()}")

    # ── PCR ──────────────────────────────────────────────────────────────────
    pcr_val = None
    if totals:
        v = getattr(totals[0], "pcr_oi", None)
        if v is not None:
            pcr_val = float(v)

    _stage_marks.append(("charm_pcr", time.perf_counter()))

    _cache_key = (ticker, selected_exp)
    _progressive_inflight_key = _tier_c_inflight_key(ticker, expiry)
    if not log_only:
        _publish_progressive_tier_c_cache(
            ticker=ticker,
            cache_key=_cache_key,
            inflight_key=_progressive_inflight_key,
            selected_exp=selected_exp,
            expiries=expiries,
            today_str=_today_str,
            spot_f=spot_f,
            bid=bid,
            ask=ask,
            session_label=session_label,
            rows=rows,
            walls=walls,
            totals=totals,
            consensus_summary=consensus_summary,
            exposures=exposures,
            gamma_flip=_gamma_flip,
            gamma_voids=_gamma_voids,
            charm_net=_charm_net,
            charm_dir=_charm_dir,
            charm_toward=_charm_toward,
            pcr_val=pcr_val,
            kl_expiry_source=_kl_expiry_source,
            quote_spread_pts=_quote_spread,
            quote_spread_source=_quote_spread_source,
            update_source=update_source,
        )

    # ── Market context ────────────────────────────────────────────────────────
    prev_pcr  = _state_cache.get(_cache_key, {}).get("pcr_val")
    prev_spot = _state_cache.get(_cache_key, {}).get("spot_f")

    # ── Candle direction + body from last COMPLETED 1m bar (canonical) ─────────
    # Use real OHLC (close - open) of the last completed bar, not a 30s tick
    # delta. Accumulator tick() was already called above.
    _candle_dir  = None
    _candle_body = None
    _c_open = _c_high = _c_low = _c_close = None
    _c_range = None
    _completed_bars_now = _candles_1m.get_bars(ticker)
    if _completed_bars_now:
        _lb = _completed_bars_now[-1]
        _lb_open  = _lb.open
        _lb_high  = _lb.high
        _lb_low   = _lb.low
        _lb_close = _lb.close
        try:
            if _lb_open is not None:
                _c_open = float(_lb_open)
            if _lb_high is not None:
                _c_high = float(_lb_high)
            if _lb_low is not None:
                _c_low = float(_lb_low)
            if _lb_close is not None:
                _c_close = float(_lb_close)
            if _c_high is not None and _c_low is not None:
                _c_range = round(_c_high - _c_low, 4)
        except (TypeError, ValueError):
            pass
        if _lb_open and _lb_close and float(_lb_open) > 0:
            _bar_move    = round(float(_lb_close) - float(_lb_open), 4)
            _candle_dir  = _classify_direction(_bar_move, float(_lb_open))
            _candle_body = abs(_bar_move)
    # ── Global market context (PCR update if we have fresh data) ─────────────
    if pcr_val is not None:
        mkt_ctx.pcr = pcr_val

    # ── Price levels ──────────────────────────────────────────────────────────
    # Carry the SAME canonical snapshot /api/levels serializes. Reuse the carried
    # PriceLevels object only while its level_generation matches that snapshot.
    # A wall-clock TTL (PRICE_LEVELS_CACHE_SEC) is not a generation identity:
    # it let /api/state keep generation N (or an empty PriceLevels() after a
    # swallowed fetch failure) while /api/levels had already materialized N+1.
    from liquidity_value_engine import LevelCarrierConflict as _LevelCarrierConflict
    _today_date_str = now_et.strftime("%Y-%m-%d")
    _pl_snap = canonical_price_level_snapshot(ticker)
    _pl_bucket = _state_cache.get(_cache_key, {})
    _pl_cache_entry = _pl_bucket.get("price_levels")
    _pl_cache_date  = _pl_bucket.get("pl_date", "")
    _pl_cache_gen   = _pl_bucket.get("pl_generation")

    if carried_price_levels_match_snapshot(
        _pl_cache_entry, _pl_cache_date, _pl_cache_gen, _today_date_str, _pl_snap,
    ):
        price_levels = _pl_cache_entry
    else:
        try:
            price_levels = fetch_price_levels(
                client, symbol=ticker, quote_raw=q_json,
                level_snapshot=_pl_snap,
            )
            if price_levels.error:
                log.warning(f"PriceLevels: {ticker} partial error: {price_levels.error}")
            if price_levels.vwap is None and price_levels.bars_today > 0:
                log.warning(f"PriceLevels: {ticker} has {price_levels.bars_today} bars but VWAP is None")
            elif price_levels.vwap is not None:
                log.debug(f"PriceLevels: {ticker} VWAP={price_levels.vwap:.2f} bars={price_levels.bars_today}")
        except _LevelCarrierConflict:
            raise
        except Exception as e:
            log.warning(f"PriceLevels: {ticker} FAILED: {e}")
            price_levels = PriceLevels()
        else:
            _sc = _state_cache.get(_cache_key, {})
            _sc["price_levels"] = price_levels
            _sc["pl_date"]      = _today_date_str
            _sc["pl_generation"] = getattr(_pl_snap, "generation", None)
            _sc["pl_mono"]      = time.monotonic()
            _state_cache[_cache_key] = _sc
    _stage_marks.append(("progressive_publish_price_levels", time.perf_counter()))

    # ── Expected Move (straddle + IV-based) ──────────────────────────────────
    _em_straddle = {"straddle": None, "em_pts": None, "upper": None, "lower": None}
    _em_iv = {"em_pts": None, "upper": None, "lower": None}
    _em_progress = {
        "progress_pct": None,
        "breached": None,
        "direction": None,
        "severity": None,
    }
    _em_up = None
    _em_lo = None
    _em_band_source = "unavailable"  # RC-345 / F06: which EM methodology produced the band
    from time_et import hours_until_session_close_et as _hours_until_close
    _hours_rem = _hours_until_close(now_et) or 0.0
    _kl_em_anchor = "unavailable"
    _mc_iv_level = None
    _mc_iv_source = "unavailable"

    try:
        _today_open = getattr(price_levels, "today_open", None)

        # ATM straddle: find ATM call + put mark from chain
        # single source: reject NaN via the finite reader (raw float() admitted NaN into
        # the strike set, corrupting sorting and the ATM-strike nearest-neighbour pick).
        from numeric_contract import float_finite_or_none as _fin
        _all_strikes = sorted({
            sp
            for ct in contracts_use
            if (sp := _fin(ct.get("strikePrice"))) is not None
        })
        if _all_strikes and spot_f > 0:
            _atm_k = min(_all_strikes, key=lambda k: abs(k - spot_f))
            _atm_calls = [
                ct
                for ct in contracts_use
                if str(ct.get("putCall", "")).upper() == "CALL"
                and (sp := _f(ct.get("strikePrice"))) is not None
                and abs(sp - _atm_k) < 0.01
            ]
            _atm_puts = [
                ct
                for ct in contracts_use
                if str(ct.get("putCall", "")).upper() == "PUT"
                and (sp := _f(ct.get("strikePrice"))) is not None
                and abs(sp - _atm_k) < 0.01
            ]
            _c_mark = _f(_atm_calls[0].get("mark")) if _atm_calls else None
            _p_mark = _f(_atm_puts[0].get("mark")) if _atm_puts else None

            if _c_mark and _p_mark and _today_open:
                _em_straddle = compute_expected_move_straddle(_c_mark, _p_mark, _today_open)

        # IV-based EM (shrinks through the day)
        if _atm_iv and _atm_iv > 0 and spot_f > 0 and _hours_rem > 0:
            _em_iv = compute_expected_move_iv(spot_f, _atm_iv, _hours_rem)

        # EM progress (use straddle EM if available, fall back to IV) — no synthetic 6.5h session fill.
        # RC-345 / F06: the operator-facing EM band is ONE of two economically distinct
        # methodologies — STRADDLE_IMPLIED (market ATM straddle premium) or IV_MODEL
        # (spot x IV x sqrt(T)). Record WHICH produced the band so no consumer treats the
        # generic _em_up/_em_lo as method-agnostic or silently mistakes one for the other.
        if _em_straddle.get("upper") is not None and _em_straddle.get("lower") is not None:
            _em_up, _em_lo, _em_band_source = (
                _em_straddle.get("upper"), _em_straddle.get("lower"), "STRADDLE_IMPLIED")
        elif _em_iv.get("upper") is not None and _em_iv.get("lower") is not None:
            _em_up, _em_lo, _em_band_source = (
                _em_iv.get("upper"), _em_iv.get("lower"), "IV_MODEL")
        else:
            _em_up, _em_lo, _em_band_source = None, None, "unavailable"
        if _em_up and _em_lo and _today_open:
            _em_progress = compute_em_progress(spot_f, _today_open, _em_up, _em_lo)

        from math_volatility import resolve_kl_em_anchor, resolve_mc_iv_for_kl_em_anchor

        _kl_em_anchor = resolve_kl_em_anchor(_em_straddle, _em_iv)
        _mc_iv_level, _mc_iv_source = resolve_mc_iv_for_kl_em_anchor(
            kl_em_anchor=_kl_em_anchor,
            atm_iv=_atm_iv,
            spot=spot_f,
            em_straddle=_em_straddle,
            hours_remaining=_hours_rem,
        )

    except Exception as e:
        log.warning(f"Expected move calc failed: {e}")

    # ── Volatility signals — IV Skew, Realized Vol, ATR, IV Rank/Percentile ──
    _iv_skew = {}
    _realized_vol = None
    _atr = None
    _iv_rank = None
    _iv_percentile = None
    _bars = None
    try:
        _iv_skew = compute_iv_skew(contracts_use, spot_f)
        # Realized vol + ATR from canonical (1m) candle bars
        _bars = _candles_1m.get_bars(ticker)
        if _bars:
            _closes = [float(b.close) for b in _bars if b.close is not None]
            if _closes:
                _realized_vol = compute_realized_vol(_closes, bar_minutes=1.0)
            _atr = compute_atr(_bars)
        # IV Rank/Percentile from DB historical iv_level
        # Burndown (2026-07-05): narrow iv_level projection — the full-width
        # get_recent_snapshots read (5,000 rows x 200+ cols incl. chain blobs)
        # was ~all of the vol_flow_signals stage (py-spy 1,258/3,062 samples).
        # Same row window/order/as-of as before; values identical.
        # Schwab CSV authority checked: yes
        # CSV row(s): NO_SCHWAB_EQUIVALENT — persisted-snapshot SQLite read
        #   (iv_level history for rank/percentile); no market field derivation,
        #   emission, or actionability logic changed.
        # Derived-field disposition: none required.
        # All consumers checked: yes — _iv_history filter semantics unchanged.
        # SCHWAB_CSV_CHECKED
        if _atm_iv and _ed_db and _tick_ts is not None:
            try:
                _iv_hist_vals = _ed_db.get_recent_iv_levels(
                    ticker,
                    CANONICAL_TIMEFRAME,
                    n=IV_HISTORY_LOOKBACK,
                    as_of_ts_utc=_tick_ts,
                )
                _iv_history = [
                    float(v) for v in _iv_hist_vals
                    if v is not None and float(v) > 0
                ]
                if _iv_history:
                    _iv_rank = compute_iv_rank(_atm_iv, _iv_history)
                    _iv_percentile = compute_iv_percentile(_atm_iv, _iv_history)
            except Exception as e:
                log.debug(
                    "IV rank/percentile history load failed ticker=%s: %s",
                    ticker,
                    e,
                    exc_info=True,
                )
    except Exception as e:
        log.debug(f"Volatility signals calc: {e}")
    # RC-236 (same calibration law as the tier-1 lock waits): a bar deficit during ACCUMULATOR
    # WARMUP is the designed state — the in-memory series re-seeds from zero on every restart
    # and cannot hold 16 one-minute bars until 16 minutes of wall clock have passed. Logging
    # that at WARNING makes the quiet gate fail for doing exactly what it must do, and trains
    # the operator to ignore the channel. Past the warmup horizon the SAME deficit is genuine
    # starvation and keeps its WARNING; the deficit is always logged, only the severity moves.
    if _atr is None:
        _warm = _atr_warmup_active()
        _msg = (f"ATR NULL for {ticker}: only {len(_bars)} bars, need {ATR_MIN_BARS}"
                if _bars else f"ATR NULL for {ticker}: no bars, need {ATR_MIN_BARS}")
        if _warm:
            log.info("%s (accumulator warmup, %.0fs since boot)", _msg, _seconds_since_boot())
        else:
            log.warning(_msg)

    # ── GARCH Volatility Forecast ─────────────────────────────────────────────
    _garch_sigma_bars = None
    try:
        if _closes and len(_closes) > 20:
            _garch_raw = compute_garch_forecast(_closes, horizon=GARCH_HORIZON_BARS)
            if _garch_raw:
                from volatility_regime import vol_percent_to_decimal

                _iv_dec = vol_percent_to_decimal(_atm_iv)
                _rv_dec = vol_percent_to_decimal(_realized_vol)
                # RC-334: _closes are ONE-MINUTE closes — `_candles_1m.get_bars` above, and
                # the realized-vol call on this same list passes bar_minutes=1.0 — so the
                # GARCH sigmas are per-minute and the IV/RV terms must be de-annualized to
                # the same minute. Monte Carlo then consumes this list DIRECTLY as per-bar
                # sigma at monte_carlo.BAR_MINUTES, so a third party has to agree too. The
                # interval is stated from the DATA, not borrowed from MC's constant, and the
                # agreement is asserted: if MC's bar ever moves, this must fail loudly rather
                # than keep feeding it minute sigmas under a five-minute name.
                from monte_carlo import BAR_MINUTES as _MC_BAR_MINUTES

                _GARCH_BAR_MINUTES = 1.0          # _candles_1m is one-minute by construction
                if float(_MC_BAR_MINUTES) != _GARCH_BAR_MINUTES:
                    raise RuntimeError(
                        f"GARCH/Monte-Carlo bar mismatch: sigmas built on "
                        f"{_GARCH_BAR_MINUTES}-minute closes but monte_carlo.BAR_MINUTES is "
                        f"{_MC_BAR_MINUTES}. MC consumes these as per-bar sigma, so the "
                        f"units must match (RC-334).")
                _garch_sigma_bars = blend_garch_sigma(
                    _garch_raw, _iv_dec, _rv_dec, spot_f,
                    bar_minutes=_GARCH_BAR_MINUTES,
                )
    except Exception as e:
        log.debug(f"GARCH forecast calc: {e}")

    # ── Order Flow Signals (from option volume + bid/ask size) ────────────────
    _vol_oi_ratio = {}
    _smart_money = {}
    _iv_model_spread = {}
    try:
        _vol_oi_ratio = compute_volume_oi_ratio(exposures, spot_f)
    except Exception as e:
        log.debug(f"Order flow signals calc: {e}")
    # RC-345 / F11 residual: ONE computation for the served number AND its label.
    # The live path used to call compute_option_flow_imbalance independently for
    # flow_imbalance_label while persisting flow_imbalance_normalized_with_fallback.
    # MEASURED on current main: empty ATM book + call-heavy volume → number 0.6
    # (source=volume) beside label "balanced" (book-only zero). Label is now a
    # function of the same normalized value the wrapper returns.
    _flow_imb_norm = None
    _flow_imb_source = "none"
    try:
        _flow_imb_norm, _flow_imb_source = flow_imbalance_normalized_with_fallback(exposures, spot_f)
    except Exception as e:
        log.warning(f"flow_imbalance (one-producer authority) failed: {e}")
    try:
        _smart_money = compute_smart_money_signal(exposures, spot_f)
    except Exception as e:
        log.warning(f"smart_money_score failed: {e}")
    try:
        _iv_model_spread = compute_iv_model_spread(contracts_use, spot_f)
    except Exception as e:
        log.debug(f"Order flow signals calc: {e}")

    # ── Section 8 — Predictive Positioning Signals ───────────────────────────
    _dpi = {}
    _hedging_flow = {}
    _gamma_gradient = None
    _breakout_score = {}
    _pin_score_val = {}
    _vol_expansion = {}
    _sweep_score = {}
    # Sweep score post-build_market_state needs _void_factor even if Section 8 raised early.
    _void_factor = 0.0
    def _bucket_total_oi(_bkt: dict) -> float | None:
        call_oi = _bkt.get("call_oi")
        put_oi = _bkt.get("put_oi")
        if call_oi is None and put_oi is None:
            return None
        return (float(call_oi) if call_oi is not None else 0.0) + (float(put_oi) if put_oi is not None else 0.0)

    # Gamma-audit 2026-08-26 (latent NameError, found tracing the F9 regime source): the terrain-SSOT
    # reads below live INSIDE this try, whose `except` only logs (server.py: "Section 8 signals calc")
    # and sets no defaults. Any earlier raise in the block therefore left these names UNDEFINED, and
    # the later build_market_state(absolute_gamma_strike=_pin_strike, net_gamma_at_spot=...) raised
    # NameError — caught as a build_market_state crash, so ONE failed sub-computation blanked the
    # ENTIRE market state instead of degrading a single field. Pre-initialized here so the block
    # degrades field-wise and fail-closed (None = the consumer withholds its claim), never all-or-nothing.
    _pin_strike = None
    _regime_gamma_at_spot = None
    try:
        # Aggregate totals — same full-chain Σ net_gex_1pct as kl_net_gex / ExposureRow CONSENSUS
        _sum_gex = float(aggregate_net_gex(exposures, _cons_strikes) or 0.0)
        _sum_dex = 0.0
        _sum_oi = None
        _sum_vanna = 0.0
        for _bkt in exposures.values():
            _dex = bucket_metric(_bkt, "net_dex_dollars")
            if _dex is not None:
                _sum_dex += _dex
            _bucket_oi = _bucket_total_oi(_bkt)
            if _bucket_oi is not None:
                _sum_oi = (_sum_oi or 0.0) + _bucket_oi
            _cv = bucket_metric(_bkt, "call_vanna")
            _pv = bucket_metric(_bkt, "put_vanna")
            if _cv is not None:
                _sum_vanna += _cv
            if _pv is not None:
                _sum_vanna += _pv

        # 1. DPI
        _dpi = compute_dealer_pressure_index(_sum_dex, _sum_gex, _sum_oi)

        # 2. Hedging Flow Score — normalize inputs to -1..+1
        _max_gex = max(abs(_sum_gex), 1.0)
        _max_dex = max(abs(_sum_dex), 1.0)
        _max_charm = max(abs(_charm_net), 1.0) if _charm_net is not None else 1.0
        _max_vanna = max(abs(_sum_vanna), 1.0)
        _charm_norm = (
            _charm_net / _max_charm
            if _charm_net is not None and _max_charm > 0
            else None
        )
        _hedging_flow = compute_hedging_flow_score(
            net_gex_normalized=_sum_gex / _max_gex if _max_gex > 0 else 0,
            net_dex_normalized=_sum_dex / _max_dex if _max_dex > 0 else 0,
            charm_normalized=_charm_norm,
            vanna_normalized=_sum_vanna / _max_vanna if _max_vanna > 0 else 0,
        )

        # 3. Gamma Gradient
        _gamma_gradient = compute_gamma_gradient(exposures, spot_f)

        # 4. Breakout Score
        _gex_near_spot = 0.0
        for k, b in exposures.items():
            if abs(float(k) - spot_f) > GEX_NEAR_SPOT_RADIUS:
                continue
            _ng = bucket_metric(b, "net_gex_1pct")
            if _ng is not None:
                _gex_near_spot += abs(_ng)
        _void_factor = 0.0
        for _vz in (_gamma_voids or []):
            if _vz.get("contains_spot"):
                _void_factor = 1.0
                break
            _vz_dist = min(abs(_vz.get("lower", spot_f) - spot_f), abs(_vz.get("upper", spot_f) - spot_f))
            _void_factor = max(_void_factor, max(0, 1.0 - _vz_dist / VOID_DIST_FALLOFF))
        try:
            _breakout_score = compute_breakout_score(_gex_near_spot, _gamma_gradient, _void_factor)
        except Exception as e:
            log.warning(f"breakout_score failed: {e}")
            _breakout_score = {}

        # 5. Pin Score — strike AND GEX/OI from the terrain SSOT book (RC-124/RC-292/RC-413).
        # Never consensus_summary.net_gex_peak (analytics |net GEX$| peak) and never analytics
        # `exposures` for magnitude at that strike. RC-292 rename: the terrain payload field
        # is absolute_gamma_strike — the raw total-gamma concentration; pin_score grades it.
        _t_pin_snap = terrain_cache_get(ticker) or {}
        _pin_strike = (
            _t_pin_snap.get("absolute_gamma_strike")
            if _t_pin_snap and not _t_pin_snap.get("levels_stale")
            else None
        )
        _gex_at_pin = None
        _oi_concentration = None
        if _pin_strike is not None and _t_pin_snap and not _t_pin_snap.get("levels_stale"):
            try:
                _tg = _t_pin_snap.get("absolute_gamma_gex_dollars")
                _toi = _t_pin_snap.get("absolute_gamma_oi")
                _tbook = _t_pin_snap.get("book_oi_total")
                if _tg is not None and _toi is not None and _tbook is not None:
                    _book_oi = float(_tbook)
                    _gex_at_pin = float(_tg)
                    _oi_concentration = (
                        (float(_toi) / _book_oi) if _book_oi > 0 else None
                    )
            except (TypeError, ValueError):
                _gex_at_pin = None
                _oi_concentration = None
        try:
            _pin_score_val = compute_pin_score(_gex_at_pin, _oi_concentration)
        except Exception as e:
            log.warning(f"pin_score failed: {e}")
            _pin_score_val = {}

        # Cursor-audit F9 / gamma audit: the dealer dampen/amplify REGIME sign, read from the SAME
        # terrain SSOT snapshot as the pin above and on the SAME fail-closed terms. net_gex_at_spot
        # IS gamma_at_spot over the wide multi-expiry book (terrain_engine) — the exact value the
        # terrain card renders — so the Call/regime consumers and the card read ONE number and cannot
        # disagree in sign. Sourcing it from the selected-expiry analytics diag (the first cut of this
        # fix) could disagree, and a one-expiry slice is the wrong basis for a whole-book hedging
        # claim. Missing or stale snapshot -> None -> every consumer withholds its regime claim.
        _regime_gamma_at_spot = (
            _t_pin_snap.get("net_gex_at_spot")
            if _t_pin_snap and not _t_pin_snap.get("levels_stale")
            else None
        )

        # 6. Vol Expansion Signal
        _iv_dir_num = 1.0 if _iv_direction == "expanding" else -1.0 if _iv_direction == "contracting" else 0.0
        _vol_expansion = compute_vol_expansion_signal(_sum_gex, _iv_dir_num, _gamma_gradient)

        # Sweep Score moved below: needs ms.nearest_above_dist / ms.nearest_below_dist
        # which are only populated by build_market_state. The previous compute here read
        # `getattr(ms, _wname, None) if 'ms' in dir() else None` — `ms` was undefined at
        # this point in execution, so the loop always set _nearest_wall_dist=None and
        # sweep_score was silently degraded every tick.

    except Exception as e:
        log.debug(f"Section 8 signals calc: {e}")

    # ── Volatility Envelope, Level Density, Sector Strength ──────────────────
    _vol_envelope = {}
    _level_density = {}
    _sector_strength = {}
    _index_strength = {}
    _spy_strength = {}
    _iwm_deep = {}
    # VOL_INPUT_CONTRACT 1.0.0 (lane V1): compute the market-vol context
    # ONCE per cycle. The tracker ticks exactly once here — the previous
    # per-surface ticks (confluence / snapshot / ms_dict) re-ticked the
    # SAME value, forcing direction to "flat" after the first tick, and
    # each surface recomputed vs-prev independently (MSD-001 divergence).
    # All downstream surfaces consume this one frozen struct. Deliberately
    # OUTSIDE the envelope/density/sector try: vol_ctx must be bound on every
    # path that reaches build_market_state / the persistence tail / ms_dict —
    # a swallowed envelope exception must degrade envelope fields only, never
    # unbind the vol context (NameError = broken serve cycle).
    #
    # Schwab CSV authority checked: yes
    # CSV row(s): quotes.$VIX.lastPrice — market_iv_level source primitive: the
    #   macro $VIX quote fetched in market_context.fetch_market_context via
    #   safe_get_quote and carried here as mkt_ctx.vix (no substitute source).
    # market_iv_change / market_iv_direction: NO_SCHWAB_EQUIVALENT — derived as
    #   the signed vol-point delta vs the previous PUBLISHED $VIX observation
    #   and the tracker enum over the same quote series; Schwab provides no
    #   primitive for either; absence stays None (never 0/"flat"), no synthetic
    #   value is represented as a Schwab field.
    # Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE
    # All consumers checked: yes — SignalInput stamp, snapshot row, ms_dict,
    #   confluence, vix_bucket all consume this one frozen vol_ctx (MSD-001
    #   parity locks in tests/test_market_context_fetch_fail_closed.py).
    # SCHWAB_CSV_CHECKED
    _vol_prev_published_vix = _state_cache.get(_cache_key, {}).get("vix")
    _vol_vix_now = None
    if getattr(mkt_ctx, "vix", None) is not None:
        try:
            _vol_vix_now = float(mkt_ctx.vix)
            _vix_tracker.tick(_vol_vix_now)
        except (TypeError, ValueError):
            _vol_vix_now = None
    vol_ctx = MarketVolContextV1(
        market_iv_level=_vol_vix_now,
        market_iv_change=(
            round(_vol_vix_now - float(_vol_prev_published_vix), 4)
            if _vol_vix_now is not None and _vol_prev_published_vix is not None
            else None
        ),
        market_iv_direction=(_vix_tracker.direction if _vol_vix_now is not None else None),
        quality_status=("VALID" if _vol_vix_now is not None else "UNAVAILABLE"),
        as_of_ts=time.time(),
    )
    # VOL_OBSERVABILITY_V1 (V2 prerequisite, read-only): record the per-cycle
    # vol-index observations. Statement-only, never assigned, never consumed
    # by this pipeline — native-index consumption stays NOT_APPROVED.
    record_market_vol_observation(mkt_ctx, vol_ctx)
    try:
        _vol_envelope = compute_volatility_envelope(spot_f, _atr)

        # Build levels dict for density check
        # RC-432: density is a live congestion read. It must count the SAME terrain-bound
        # walls and terrain flip the KL table paints. Pre-fix used selected-expiry
        # `_gamma_flip` and `locals().get('_cgw')` — those wall names are assigned hundreds
        # of lines later, so density silently counted pin/EM only and labeled "clear"
        # while a terrain put wall sat inside the radius (PROVEN on SPY fixture: spot
        # 743.88, put wall 745.0 → clear vs light).
        _all_levels = {}
        _t_dens = terrain_cache_get(ticker) or {}
        _dens_fresh = bool(_t_dens) and not _t_dens.get("levels_stale")
        if _dens_fresh and _t_dens.get("absolute_gamma_strike") is not None:
            _all_levels["absolute_gamma_strike"] = float(_t_dens["absolute_gamma_strike"])
        _w0 = walls[0] if walls else None
        if _w0 is not None:
            for _dn, _attr in (
                ("call_gamma_wall", "call_gamma_wall"),
                ("put_gamma_wall", "put_gamma_wall"),
                ("call_delta_wall", "call_delta_wall"),
                ("put_delta_wall", "put_delta_wall"),
            ):
                _dv = getattr(_w0, _attr, None)
                if _dv is not None:
                    _all_levels[_dn] = float(_dv)
        if _dens_fresh and _t_dens.get("gamma_flip") is not None:
            _all_levels["gamma_flip"] = float(_t_dens["gamma_flip"])
        # RC-433 / F06: density counts the SAME EM band KL paints (terrain IV_SIGMA_1D =
        # spot ± implied_1d_move.points). Pre-fix injected remaining-risk straddle/IV_MODEL
        # bands, which often sit inside the 3pt radius while the operator KL band is the wider
        # 1σ day move — congestion labeled "moderate" from a band the KL table does not show.
        # Remaining-risk EM stays on SignalInput / em_progress.
        if _dens_fresh:
            _em_move = _t_dens.get("implied_1d_move") or {}
            _em_pts = _em_move.get("points")
            _em_spot = _t_dens.get("spot")
            if _em_pts is not None and _em_spot is not None:
                _all_levels["em_upper"] = float(_em_spot) + float(_em_pts)
                _all_levels["em_lower"] = float(_em_spot) - float(_em_pts)
        _level_density = compute_level_density(_all_levels, spot_f)

        # Sector strength — 3 groups
        # Group 1: Indices (SPY, QQQ, IWM)
        _idx_data = {}
        for _ik, _ig in [('SPY', mkt_ctx.spy_chg_pct), ('QQQ', mkt_ctx.qqq_chg_pct), ('IWM', mkt_ctx.iwm_chg_pct)]:
            if _ig is not None: _idx_data[_ik] = float(_ig)
        _index_strength = compute_sector_strength(_idx_data)

        # Group 2: SPY top holdings (from mkt_ctx.constituents)
        _spy_holdings = {}
        for _cq in getattr(mkt_ctx, 'constituents', []):
            _sym = getattr(_cq, 'symbol', '').upper()
            _chg = getattr(_cq, 'chg_pct', None)
            if _sym and _chg is not None:
                _spy_holdings[_sym] = float(_chg)
        _spy_strength = compute_sector_strength(_spy_holdings)

        # Group 3: IWM sector proxies (from mkt_ctx.iwm_sectors)
        _sector_data = {}
        for _sq in getattr(mkt_ctx, 'iwm_sectors', []):
            _sym = getattr(_sq, 'symbol', '').upper()
            _chg = getattr(_sq, 'chg_pct', None)
            if _sym and _chg is not None:
                _sector_data[_sym] = float(_chg)
        _sector_strength = compute_sector_strength(_sector_data)

        # VOL_INPUT_CONTRACT 1.0.0: confluence consumes the same per-cycle
        # context as every other surface (computed above, outside this try).
        _vix_dir_for_confluence = vol_ctx.market_iv_direction
        _iwm_deep = compute_iwm_confluence(
            spy_chg=mkt_ctx.spy_chg_pct,
            qqq_chg=mkt_ctx.qqq_chg_pct,
            iwm_chg=mkt_ctx.iwm_chg_pct,
            kre_chg=_sector_data.get('KRE'),
            xbi_chg=_sector_data.get('XBI'),
            psci_chg=_sector_data.get('PSCI'),
            xrt_chg=_sector_data.get('XRT'),
            vix_level=vol_ctx.market_iv_level,
            vix_direction=_vix_dir_for_confluence,
        )
    except Exception as e:
        log.debug(f"Envelope/density/sector calc: {e}")
    _stage_marks.append(("vol_flow_signals", time.perf_counter()))

    # ── Zone tracking ─────────────────────────────────────────────────────────
    # zone_since_bars_1m = execution-layer recency (canonical 1m bars) — primary for models/features.
    # zone_since_bars_5m = structure-layer recency (derived 5m bars) — for structure context only.
    # We track both independently so there is no mixed-clock dependency.
    bias_sig = (consensus_summary.bias_signal if consensus_summary else "") or ""
    nd_raw   = (consensus_summary.net_delta   if consensus_summary else None)
    cur_zone = derive_zone(bias_sig, nd_raw)

    _zone_bars_1m = _candles_1m.get_bars(ticker)
    _zone_bars_5m = _candles_5m.get_bars(ticker)
    _latest_bar_ts_1m = _zone_bars_1m[-1].ts if _zone_bars_1m else 0.0
    _latest_bar_ts_5m = _zone_bars_5m[-1].ts if _zone_bars_5m else 0.0

    zt = _zone_tracker.get(ticker, {
        "zone": cur_zone, "prev_zone": cur_zone,
        "since_bars_1m": 0, "since_bars_5m": 0,
        "last_bar_ts_1m": 0.0, "last_bar_ts_5m": 0.0,
    })
    if cur_zone != zt["zone"]:
        zt["prev_zone"]      = zt["zone"]
        zt["zone"]           = cur_zone
        zt["since_bars_1m"]  = 0
        zt["since_bars_5m"]  = 0
        zt["last_bar_ts_1m"] = _latest_bar_ts_1m
        zt["last_bar_ts_5m"] = _latest_bar_ts_5m
    else:
        if _latest_bar_ts_1m > zt.get("last_bar_ts_1m", 0.0):
            zt["since_bars_1m"]  += 1
            zt["last_bar_ts_1m"]  = _latest_bar_ts_1m
        if _latest_bar_ts_5m > zt.get("last_bar_ts_5m", 0.0):
            zt["since_bars_5m"]  += 1
            zt["last_bar_ts_5m"]  = _latest_bar_ts_5m
    _zone_tracker[ticker] = zt

    # ── DB counts + crosses ───────────────────────────────────────────────────
    if _diag_on():
        _diag_step("pre_db_counts", ticker)
    db_counts  = {"total": 0, "filled": 0}
    ceil_tests = floor_tests = 0
    recent_crosses = []

    if _ed_db:
        try:
            db_counts = _ed_db.count_snapshots(ticker, CANONICAL_TIMEFRAME)
            cgw = _f(getattr(walls[0], "call_gamma_wall", None)) if walls else None
            pgw = _f(getattr(walls[0], "put_gamma_wall",  None)) if walls else None
            if cgw:
                _ceil = _ed_db.count_level_tests(ticker, "Call Gamma Wall", cgw)
                _ct = _ceil.get("total")
                ceil_tests = int(_ct) if _ct is not None else 0
            if pgw:
                _floor = _ed_db.count_level_tests(ticker, "Put Gamma Wall", pgw)
                _ft = _floor.get("total")
                floor_tests = int(_ft) if _ft is not None else 0
            rc = _ed_db.get_recent_crosses(ticker, n=RECENT_CROSSES_DISPLAY_LIMIT)
            recent_cross_eval_wall_ts = time.time()
            for c in rc:
                bars_ago = int(
                    (recent_cross_eval_wall_ts - c.get("ts_utc", 0)) / 60
                )  # 1m bar cadence (canonical)
                recent_crosses.append({
                    "level_name": c.get("level_name"),
                    "direction":  c.get("direction"),
                    "bars_ago":   bars_ago,
                })
        except Exception as e:
            log.warning(f"DB query failed: {e}")
    if _diag_on():
        _diag_done("db_counts", ticker)

    # session_label already computed above — reuse it
    et_h = now_et.hour
    et_m = now_et.minute
    mins_to_close = max(0.0, RTH_CLOSE_MINS - (et_h * 60 + et_m))

    # Candle volume from last completed 1m bar (canonical) for build_market_state + snapshot
    _c_vol = None
    _completed_for_vol = _candles_1m.get_bars(ticker)

    # Order Flow Engine input — full Claude proxy field set from current fetches
    if _diag_on():
        _diag_step("pre_order_flow_data", ticker)
    _order_flow_data = {}
    try:
        _q_node = q_json.get(ticker.upper()) or q_json.get(ticker) or q_json
        if isinstance(_q_node, dict):
            _order_flow_data["quote"] = _q_node.get("quote") or {}
            _order_flow_data["extended"] = _q_node.get("extended") or {}
            _order_flow_data["regular"] = _q_node.get("regular") or {}
            _order_flow_data["fundamental"] = _q_node.get("fundamental") or {}
            _order_flow_data["reference"] = _q_node.get("reference") or {}
        else:
            _order_flow_data["quote"] = {}
            _order_flow_data["extended"] = {}
            _order_flow_data["regular"] = {}
            _order_flow_data["fundamental"] = {}
            _order_flow_data["reference"] = {}
        # Reuse parsed chain JSON — second c_resp.json() reparsed the full payload every tick.
        _order_flow_data["callExpDateMap"] = c_json.get("callExpDateMap") or {}
        _order_flow_data["putExpDateMap"] = c_json.get("putExpDateMap") or {}
        _order_flow_data["underlying"] = c_json.get("underlying") or {}
        # Order flow candles: 1m only (execution-aligned). No 5m fallback, no 5m aggregation.
        _bars_1m = _candles_1m.get_bars(ticker)
        _order_flow_data["candles"] = [
            {
                "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                "volume": getattr(b, "volume", 0.0),
                "datetime": int(getattr(b, "ts", 0) * 1000),
            }
            for b in (_bars_1m or [])
        ]
        # Merge live streaming data (book + tape) if available
        try:
            if _diag_on():
                _diag_step("pre_get_content_for_symbol", ticker)
            from order_flow_live_state import get_content_for_symbol
            _live_content = get_content_for_symbol(ticker)
            if _diag_on():
                _diag_done("get_content_for_symbol", ticker)
            if _live_content:
                _order_flow_data["content"] = _live_content
        except ImportError:
            pass
    except Exception as _ofd_e:
        log.debug(f"Order flow data build: {_ofd_e}")

    # REST fallback: Cum Delta accumulator (polling-based) when streamer has no tape.
    # Update each poll; inject into ms after build_market_state if engine returns None.
    _quote_for_cum = dict(_order_flow_data.get("extended") or {})
    _quote_for_cum.update(_order_flow_data.get("quote") or {})
    _update_rest_cum_delta(ticker, _quote_for_cum, now_et)

    # Candle volume priority: 1) Price history candles.*.volume (primary), 2) accumulator (secondary)
    # Use 1m price history to match canonical (1m) bar timestamps.
    _c_vol = None
    if _completed_for_vol:
        _raw_vol = getattr(_completed_for_vol[-1], "volume", None)
        if _raw_vol is not None:
            try:
                v = float(_raw_vol)
                if v > 0:
                    _c_vol = v
            except (TypeError, ValueError):
                pass
    # Price history fetch only when accumulator has no usable volume (avoid duplicate Schwab RTT).
    if _c_vol is None and ticker:
        try:
            resp_ph = safe_get_price_history(client, ticker, frequency_minutes=1, period_days=1)
            if (not resp_ph or resp_ph.status_code != 200 or not resp_ph.json().get("candles")) and ticker.startswith("$"):
                resp_ph = safe_get_price_history(client, ticker[1:], frequency_minutes=1, period_days=1)
            if resp_ph and resp_ph.status_code == 200:
                payload_ph = resp_ph.json()
                if "candles" not in payload_ph:
                    raise ValueError(
                        f"Schwab pricehistory response missing 'candles' key (status={resp_ph.status_code})"
                    )
                ph_candles = payload_ph["candles"]
                if ph_candles and _completed_for_vol:
                    last_ts = getattr(_completed_for_vol[-1], "ts", None)

                    def _ph_candle_ts_sec(bar: dict) -> Optional[float]:
                        dt = bar.get("datetime")
                        if dt is None:
                            return None
                        try:
                            dt_f = float(dt)
                        except (TypeError, ValueError):
                            return None
                        if dt_f <= 0:
                            return None
                        return dt_f / 1000.0 if dt_f > 1e10 else dt_f

                    timed = [b for b in ph_candles if _ph_candle_ts_sec(b) is not None]
                    if last_ts is not None and timed:
                        best = min(timed, key=lambda b: abs(_ph_candle_ts_sec(b) - last_ts))
                    elif timed:
                        best = timed[-1]
                    else:
                        best = ph_candles[-1]
                    ph_vol = best.get("volume")
                    if ph_vol is not None:
                        try:
                            v = float(ph_vol)
                            if v > 0:
                                _c_vol = v
                        except (TypeError, ValueError):
                            pass
                if _c_vol is None and ph_candles:
                    v = ph_candles[-1].get("volume")
                    if v is not None:
                        try:
                            vf = float(v)
                            if vf > 0:
                                _c_vol = vf
                        except (TypeError, ValueError):
                            pass
        except Exception as _ph_e:
            log.debug(f"Price history volume for {ticker}: {_ph_e}")
    # 2. Accumulator secondary — WebSocket TOTAL_VOLUME or REST quote delta
    if _c_vol is None and _completed_for_vol:
        _raw_vol = getattr(_completed_for_vol[-1], "volume", None)
        if _raw_vol is not None:
            try:
                v = float(_raw_vol)
                if v > 0:
                    _c_vol = v
            except (TypeError, ValueError):
                pass
    # ── Build MarketState ─────────────────────────────────────────────────────
    _stage_marks.append(("db_reads_orderflow_input", time.perf_counter()))
    if _diag_on():
        _diag_step("pre_build_market_state", ticker)
    from db import utc_ts as _utc_ts_refresh
    _refresh_ts_utc = _utc_ts_refresh()
    try:
        ms = build_market_state(
        ticker=ticker,
        selected_exp=selected_exp,
        session_label=session_label,
        spot=spot_f,
        bid=bid,
        ask=ask,
        consensus_summary=consensus_summary,
        contracts_use=contracts_use,
        walls=walls,
        totals=totals,
        price_levels=price_levels,
        mkt_ctx=mkt_ctx,
        vol_ctx=vol_ctx,
        live_on=True,
        zone_since_bars=zt["since_bars_1m"],
        zone_since_bars_5m=zt["since_bars_5m"],
        prev_zone=zt["prev_zone"],
        ceiling_tests_today=ceil_tests,
        floor_tests_today=floor_tests,
        recent_crosses=recent_crosses,
        total_snapshots=db_counts.get("total", 0),
        filled_snapshots=db_counts.get("filled", 0),
        et_hour=et_h,
        et_minute=et_m,
        mins_to_close=mins_to_close,
        candle_direction=_candle_dir,
        candle_body_pts=_candle_body,
        candles_5m=_candles_5m.get_bars(ticker),
        candles_1m=_candles_1m.get_bars(ticker),
        charm_net=_charm_net,
        charm_direction=_charm_dir,
        charm_drift_toward=_charm_toward,
        charm_magnitude=_charm_mag,
        charm_top_drivers=_charm_drivers,
        # RC-292/RC-295: terrain SSOT absolute-gamma strike — the same fail-closed read
        # the pin score uses above (None when the terrain cache is absent or stale).
        absolute_gamma_strike=_pin_strike,
        # Cursor-audit F9 (corrected after the gamma audit): dealer gamma AT SPOT — the regime SIGN
        # authority — read from the TERRAIN SSOT, the same wide-book value the terrain card renders
        # as net_gex_at_spot (terrain_engine: compute_gamma_profile over the full multi-expiry
        # capture book). The first cut of this fix sourced _gamma_flip_diag["gamma_at_spot"], which is
        # computed on contracts_use — the SELECTED-EXPIRY slice — so the Call could still disagree in
        # sign with the card, and a one-expiry slice is the wrong basis for a claim about dealer
        # hedging, which spans the whole book. Fail-closed exactly like the pin read above: no terrain
        # snapshot, or a stale one, yields None and the consumers emit NO regime claim.
        net_gamma_at_spot=_regime_gamma_at_spot,
        iv_direction=_iv_direction,
        em_upper=_em_up,
        em_lower=_em_lo,
        mc_iv_level=_mc_iv_level,
        mc_em_anchor=_kl_em_anchor,
        mc_iv_source=_mc_iv_source,
        realized_vol=_realized_vol,
        atr=_atr,
        garch_sigma_bars=_garch_sigma_bars,
        candle_volume=_c_vol,
        flow_imbalance=_flow_imb_norm,
        spread=_quote_spread,
        iv_rank=_iv_rank,
        smart_money_score=_smart_money.get("score") if _smart_money else None,
        breakout_score=_breakout_score.get("normalized") if _breakout_score else None,
        pin_score=_pin_score_val.get("normalized") if _pin_score_val else None,
        order_flow_data=_order_flow_data,
        db=_ed_db,
        pred_override=_get_prediction_override(ticker),
        refresh_ts_utc=_refresh_ts_utc,
    )
    except Exception as _bms_e:
        _diag_crash("build_market_state", _bms_e, ticker)
        raise
    _stage_marks.append(("signals_engine_build_market_state", time.perf_counter()))
    if _diag_on():
        _diag_done("build_market_state", ticker)

    # ── Section 8 (post-build) — Sweep Score reads ms.nearest_above_dist/nearest_below_dist ──
    # build_market_state populates these from walls + price_levels. Computing here (not in the
    # Section 8 try block above) is the only point at which the inputs are actually available.
    try:
        _nearest_wall_dist = None
        for _wname in ("nearest_above_dist", "nearest_below_dist"):
            _wd = getattr(ms, _wname, None)
            if _wd is None:
                continue
            try:
                _wd_abs = abs(float(_wd))
            except (TypeError, ValueError):
                continue
            if _nearest_wall_dist is None or _wd_abs < _nearest_wall_dist:
                _nearest_wall_dist = _wd_abs
        _momentum = 0.0
        if _atr and _atr > 0 and _candle_body:
            _momentum = min(1.0, abs(_candle_body) / _atr)
        _sweep_score = compute_sweep_score(_nearest_wall_dist, _void_factor, _momentum) or {}
    except Exception as _ss_e:
        log.debug("sweep_score post build_market_state: %s", _ss_e)

    # REST fallback: when streamer has no tape, inject polling-based cum_delta.
    # Streamer value takes precedence when available.
    if ms.cum_delta_proxy is None and ticker in _rest_cum_delta:
        ms.cum_delta_proxy = _rest_cum_delta[ticker]
        log.debug("Cum Delta: REST proxy (polling-based)")

    # ── Additive context: liquidity behavior + news/sentiment (non-authoritative) ──
    try:
        from institutional_behavior import compute_liquidity_behavior_row
        ms.liquidity_behavior = compute_liquidity_behavior_row(
            spot=spot_f,
            candle_open=_c_open,
            candle_high=_c_high,
            candle_low=_c_low,
            candle_close=_c_close,
            candle_volume=_c_vol,
            flow_imbalance=_flow_imb_norm,
            net_gamma=ms.net_gamma,
            atr=_atr,
            candle_range_pts=_c_range,
            candle_body_pts=_candle_body,
        )
    except Exception as _lb_e:
        log.debug("liquidity_behavior: %s", _lb_e)
        ms.liquidity_behavior = None
    try:
        from news_sentiment import refresh_and_context_for_ui

        _news_throttle = float(os.environ.get("ED_NEWS_THROTTLE_SEC", "90"))
        ms.news_context = refresh_and_context_for_ui(
            ticker.upper(),
            db=_ed_db,
            throttle_sec=_news_throttle,
        )
    except Exception as _nc_e:
        log.debug("news_context: %s", _nc_e)
        ms.news_context = None
    _stage_marks.append(("context_news", time.perf_counter()))

    # ── V2 decision build (pre-publish) ──────────────────────────────────────
    # FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1: the decision is computed BEFORE the
    # bundle publish and the SAME object is served (ms_dict["v2_decision"]) and
    # logged by the post-publish calibration append — no served/logged drift.
    _v2_decision_for_response = None
    _v2_logging_ms_dict = None  # bound before the try: the identity anchor reads it
    try:
        _v2_logging_ms_dict = _ms_to_dict(ms)
        _v2_logging_ms_dict["selected_exp"] = selected_exp
        _v2_logging_ms_dict["decision_time_ms"] = int(_refresh_ts_utc * 1000)
        _v2_logging_ms_dict["_server_build_ts"] = time.time()
        _attach_stack_runtime_and_governance(_v2_logging_ms_dict, ticker=ticker)
        _apply_trader_horizon_contract(_v2_logging_ms_dict)
        stamp_decision_bundle(_v2_logging_ms_dict)
        attach_a1_conformal_artifact_to_ms_dict(_v2_logging_ms_dict, ticker=ticker)
        attach_a1_isotonic_calibration_to_ms_dict(_v2_logging_ms_dict, ticker=ticker)
        _v2_decision_for_response = build_module_a_a1_decision(_v2_logging_ms_dict)
    except Exception as _v2_build_e:
        log.warning("v2 decision build failed: %s", _v2_build_e)

    # ── EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1 — identity anchor ─────────
    # Anchor the ONE (decision_id, execution_identity) pair for this cycle
    # BEFORE every governed consumer: the production-decision finalize (full
    # path), the log_only early return, and the post-publish persistence tail
    # (snapshot + calibration writes). Root cause of the 2026-07-13 RTH
    # contradiction: the anchor lived inside the tail, which runs AFTER
    # _finalize_production_decision on the full path — stamping minted a
    # decision_id with no identity and the linkage trigger refused every
    # production-decision write (255/258 ledgers OPEN missing "decision").
    # expected_surfaces mirror the cycle's REAL writers: "decision" only when
    # this cycle finalizes on a production route (never on log_only),
    # "snapshot" only when the per-minute throttle reservation admits this
    # cycle, "calibration" only when logging is enabled and the payload +
    # served v2 decision exist. A writer-side divergence after anchoring
    # leaves the ledger OPEN → INCOMPLETE (honest, mechanically visible).
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — provenance anchor ordering only;
    #   no market field read, derived, or emitted by this block.
    # Derived-field disposition: none required.
    # All consumers checked: yes — finalize (ms_dict pair seed), tail snapshot
    #   kwargs, tail calibration append, v2 logging dict; all consume the one
    #   anchored pair below.
    # SCHWAB_CSV_CHECKED
    _xid_do_snapshot_insert = False
    if _ed_db:
        try:
            # Reservation hoisted from the tail (same key: ticker + refresh ts;
            # still exactly one reservation per cycle). The tail releases it on
            # a failed insert exactly as before.
            _xid_do_snapshot_insert = bool(
                _snapshot_row_insert_allowed(ticker, _refresh_ts_utc, db=_ed_db)
            )
        except Exception as _thr_e:
            log.warning("snapshot throttle reservation failed ticker=%s: %s", ticker, _thr_e)
    # Model-derived predicate reads the SAME source the snapshot writer uses
    # (the tail sets combined_signal=ms.call_signal) — noncanonical runtime
    # proof 2026-07-13 caught the v2-dict projection lacking this key, which
    # skipped the anchor and fail-closed every model-derived surface.
    _xid_model_derived = getattr(ms, "call_signal", None) is not None
    if _ed_db and _xid_model_derived:
        from decision_record import new_decision_id as _new_did
        from execution_identity import ExecutionIdentityError as _XidErr
        from execution_identity import anchor_production_execution as _xid_anchor
        from trade_impacting_gate import (
            classify_route as _xid_classify_route,
            resolve_fetch_state_decision_route as _xid_resolve_route,
        )
        from calibration.writer import calibration_logging_enabled as _cal_on

        _v2md = _v2_logging_ms_dict
        # ONE cycle = ONE decision: the v2 build's stamped decision_id (same
        # MarketState, same refresh, gate-checked) is the single owner; every
        # downstream writer consumes it and stamp_decision_bundle reuses it.
        _xid_did = str(_v2md.get("decision_id") or "") or _new_did()
        _xid_route = _xid_resolve_route(update_source)
        _xid_expected_decision = (
            (not log_only)
            and bool(_v2md.get("decision_id"))
            and _xid_classify_route(_xid_route) == "production"
        )
        # FP-24: expect calibration only when this cycle reserved a snapshot
        # slot — otherwise decision_ts (wall clock) drifts past tol=29 from the
        # minute's single snapshot and outcome join debt accumulates.
        _xid_expected_cal = bool(
            _cal_on()
            and getattr(ms, "_calibration_payload", None)
            and _v2_decision_for_response is not None
            and _xid_do_snapshot_insert
        )
        _xid_surfaces = []
        if _xid_expected_decision:
            _xid_surfaces.append("decision")
        if _xid_do_snapshot_insert:
            _xid_surfaces.append("snapshot")
        if _xid_expected_cal:
            _xid_surfaces.append("calibration")
        # Exact calibration state USED by this cycle's decision: attached at
        # the v2 build (BEFORE this anchor); absence recorded explicitly.
        _cal_info = None
        _conf = _v2md.get("a1_conformal_artifact")
        _iso_lineage = _v2md.get("a1_calibrated_probability_lineage_id")
        if isinstance(_conf, dict) or _iso_lineage:
            _cal_info = {
                str(_v2md.get("primary_horizon") or "1c"): {
                    "conformal": (
                        {
                            k: _conf.get(k)
                            for k in ("run_id", "lineage_id", "artifact_id",
                                       "created_at", "horizon", "ticker")
                            if _conf.get(k) is not None
                        }
                        if isinstance(_conf, dict) else None
                    ),
                    "isotonic_lineage_id": _iso_lineage,
                }
            }
        if _xid_surfaces:
            try:
                with _ed_db._connect() as _xconn0:
                    _xid_sha0 = _xid_anchor(
                        requested_ticker=ticker,
                        serving_provenance=getattr(ms, "model_serving_provenance_v1", None),
                        calibration_info=_cal_info,
                        db_conn=_xconn0,
                        decision_id=_xid_did,
                        executed_at_utc=float(_refresh_ts_utc),
                        expected_surfaces=_xid_surfaces,
                    )
            except _XidErr as _x_exc0:
                log.error(
                    "EXECUTION_IDENTITY_REFUSED ticker=%s reason=%s — every "
                    "model-derived persistence surface REFUSED this cycle (fail closed)",
                    ticker, _x_exc0,
                )
            else:
                setattr(ms, "_execution_identity_pair", (_xid_did, _xid_sha0))
                _v2_logging_ms_dict["decision_id"] = _xid_did
                _v2_logging_ms_dict["execution_identity_sha256"] = _xid_sha0
    _stage_marks.append(("execution_identity_anchor", time.perf_counter()))

    # ── FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 — post-publish persistence tail ──
    # Root cause (FIX_B read-only trace, 2026-07-08): the DB snapshot/accuracy
    # block and the calibration append ran BEFORE the full-bundle cache write
    # that stamps generated_at, delaying freshness by 3.5-13.5s per cycle while
    # contributing nothing the served payload consumes. This tail now runs
    # synchronously in the same worker AFTER the publish (full path) and before
    # the early return (log_only path — the logger's persistence purpose is the
    # write itself, so its order is unchanged). Failure semantics are
    # audit-trail-only: the served bundle is never degraded or unpublished by a
    # telemetry write failure; failures are visible via warnings carrying the
    # published analytics_version and via the two post_publish_* counters. The
    # tail never touches _state_cache. Payload counters (total_snapshots /
    # filled_snapshots) and the accuracy block read the pre-publish count/cache
    # and tolerate a one-cycle lag.
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — publish/persistence ORDER change only;
    #   no market field read, derivation, or emission changed (snapshot row,
    #   bars persist, outcome backfill, accuracy scans, calibration append all
    #   run with identical inputs and once-per-cycle semantics).
    # Derived-field disposition: none required (no derived field touched).
    # All consumers checked: yes — served payload assembly reads the pre-read
    #   db_counts and module accuracy cache; calibration/snapshot consumers
    #   receive identical rows, later in the same cycle.
    # SCHWAB_CSV_CHECKED
    # Captured PRE-publish: the snapshot row's vix_vs_prev must diff against the
    # PREVIOUS cycle's published vix; after the reorder the cache entry already
    # holds THIS cycle's vix by the time the tail runs.
    # VOL_INPUT_CONTRACT 1.0.0: prev-published VIX is captured once inside
    # vol_ctx (market_iv_change); no per-surface recapture.

    def _post_publish_persistence_tail(published_version, v2_decision_for_log):
        """Persistence/telemetry tail: DB snapshot + accuracy + calibration append.

        Runs post-publish on the full path, pre-return on the log_only path.
        Never mutates _state_cache; never raises (per-section try/except).
        """
        # FIX_B relocation repair: the confluence-completion rebind
        # (mkt_ctx = _ensure_mkt_ctx_confluence_complete(...)) was owned by
        # _fetch_state before the tail extraction; without this declaration the
        # assignment makes mkt_ctx tail-local and its own RHS read raises
        # UnboundLocalError, killing every snapshot persist at that line.
        nonlocal mkt_ctx
        # ── DB snapshot logging ───────────────────────────────────────────────────
        # Initialized outside `if _ed_db` so the calibration gate below can read it.
        _snap_insert_landed = False
        if _ed_db:  # snapshot INSERT, bars persist + outcome backfill all throttled (see ED_DB_SNAPSHOT_THROTTLE)
            if _diag_on():
                _diag_step("pre_db_snapshot", ticker)
            # Reservation lifecycle: released in the except below iff the insert never
            # landed (failure between reserve and insert must not burn the minute;
            # releasing after a landed insert would re-open it). Initialized before
            # the try so the handler can never NameError.
            _snap_ts = _refresh_ts_utc
            _do_insert = False
            try:
                from db import SnapshotRow, build_ts_et
                from math_exposure import _f as _mf
                # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the throttle
                # reservation was taken at the pre-publish identity anchor so
                # expected_surfaces could include "snapshot" truthfully; this
                # tail consumes that single reservation (release-on-failure
                # semantics below are unchanged).
                _do_insert = _xid_do_snapshot_insert
                if not _do_insert:
                    log.debug(
                        "DB snapshot insert skipped (throttle: max 1 insert/ticker/UTC minute; set ED_DB_SNAPSHOT_THROTTLE=0 to disable): %s",
                        ticker,
                    )
                if _do_insert:
                    _et_now = now_et
                    from base_money_path_capture import resolve_logger_source_from_update_source

                    _resolved_logger_source = logger_source or resolve_logger_source_from_update_source(
                        update_source
                    )

                    # DTE is Schwab-native. Missing daysToExpiration fails closed for snapshot persistence.
                    _dte = _selected_schwab_days_to_expiration(
                        contracts_use,
                        selected_exp,
                        preferred_strike=getattr(ms, "rec_strike", None),
                        preferred_side=getattr(ms, "call_option_right", None),
                    )
                    _hours_to_expiry = _snapshot_expiry_hours_from_schwab_dte(
                        _dte, _et_now, expiry_et_date=selected_exp
                    )
    
                    # ── Compute fields from available data ─────────────────────────────
    
                    # Candle OHLC from canonical (1m) accumulator's current bar
                    _cur_bar = _candles_1m._current.get(ticker)
                    _c_open  = _cur_bar["o"] if _cur_bar else None
                    _c_high  = _cur_bar["h"] if _cur_bar else None
                    _c_low   = _cur_bar["l"] if _cur_bar else None
                    _c_close = _cur_bar["c"] if _cur_bar else None
                    _c_range = round(_c_high - _c_low, 4) if (_c_high and _c_low) else None
                    # _c_vol computed above before build_market_state
    
                    # VWAP distance — the PERSISTED vwap is the carried canonical value.
                    # Phase 2A: the old `_compute_vwap_from_bars` fallback here was a
                    # SECOND VWAP materialization writing into the snapshot table and
                    # from there into model features, so a row's vwap could be a number
                    # /api/levels never served. A fallback that produces a different
                    # answer is not resilience; absence is the honest output (RC-68).
                    _vwap = getattr(price_levels, "vwap", None)
                    _vwap_f = float(_vwap) if _vwap is not None else None
                    if _vwap_f is None:
                        # Schwab index symbols ($SPX, $VIX, $NDX, etc.) don't carry intraday
                        # volume data; VWAP (price × volume sum) cannot compute by definition.
                        # Steady-state DEBUG for those; WARNING for real tickers.
                        _is_index_symbol = isinstance(ticker, str) and ticker.startswith("$")
                        _vwap_log = log.debug if _is_index_symbol else log.warning
                        _vwap_log(
                            "VWAP absent for %s (canonical snapshot generation=%s) — writing NULL",
                            ticker, getattr(price_levels, "level_generation", None),
                        )
                    _vwap_dist = round(spot_f - _vwap_f, 4) if _vwap_f else None
    
                    # VWAP side must follow the same vwap we persist (API VWAP or bar-derived fallback).
                    _row_vwap_side = getattr(ms, "vwap_side", None)
                    if _row_vwap_side is None:
                        _row_vwap_side = derive_vwap_side(spot_f, _vwap_f)
    
                    global _dpi_normalized_prev_by_ticker
                    _prev_dn = _dpi_normalized_prev_by_ticker.get(ticker)
                    _cur_raw = _dpi.get("normalized") if _dpi else None
                    try:
                        _cur_dn_f = float(_cur_raw) if _cur_raw is not None else None
                    except (TypeError, ValueError):
                        _cur_dn_f = None
                    _pressure_trend_live = derive_pressure_trend(_prev_dn, _cur_dn_f)
                    _dpi_normalized_prev_by_ticker[ticker] = _cur_dn_f
                    _pressure_label_live = None
                    if _dpi:
                        _pressure_label_live = _dpi.get("direction")
                    if not _pressure_label_live and _hedging_flow:
                        _pressure_label_live = _hedging_flow.get("direction")
                    if not _pressure_label_live:
                        _pressure_label_live = "unavailable_no_dpi_or_hedging_flow_direction"
    
                    # Wall absolute values
                    _cgw = _mf(getattr(walls[0], "call_gamma_wall", None)) if walls else None
                    _pgw = _mf(getattr(walls[0], "put_gamma_wall",  None)) if walls else None
                    _cdw = _mf(getattr(walls[0], "call_delta_wall", None)) if walls else None
                    _pdw = _mf(getattr(walls[0], "put_delta_wall",  None)) if walls else None
                    _cow = _mf(getattr(walls[0], "call_oi_wall",    None)) if walls else None
                    _pow = _mf(getattr(walls[0], "put_oi_wall",     None)) if walls else None
                    _cvw = _mf(getattr(walls[0], "call_vanna_wall", None)) if walls else None
                    _pvw = _mf(getattr(walls[0], "put_vanna_wall",  None)) if walls else None
                    # Inflection points live on ExposureRow (consensus), NOT WallsRow
                    _gi  = _mf(getattr(consensus_summary, "gamma_inflection", None)) if consensus_summary else None
                    _di  = _mf(getattr(consensus_summary, "delta_inflection", None)) if consensus_summary else None
    
                    # Distance = wall_level - spot (positive = above, negative = below)
                    _d = lambda lvl: round(lvl - spot_f, 4) if lvl is not None else None
                    _dist_cgw = _d(_cgw)
                    _dist_pgw = _d(_pgw)
                    _dist_cdw = _d(_cdw)
                    _dist_pdw = _d(_pdw)
                    _dist_cow = _d(_cow)
                    _dist_pow = _d(_pow)
                    _dist_cvw = _d(_cvw)
                    _dist_pvw = _d(_pvw)
                    _dist_gi  = _d(_gi)
                    _dist_di  = _d(_di)
    
                    # Pin width (call gamma wall - put gamma wall) — RC-345/F20 one authority
                    from math_levels import compute_pin_width_pts
                    _pin_w = compute_pin_width_pts(_cgw, _pgw)
    
                    # Constituents from market context — wrap each fetch independently for partial results
                    mkt_ctx = _ensure_mkt_ctx_confluence_complete(client, mkt_ctx)
                    _const_map = {}
                    if hasattr(mkt_ctx, "constituents"):
                        for cq in mkt_ctx.constituents:
                            try:
                                if cq.chg_pct is not None:
                                    _const_map[cq.symbol.upper()] = round(float(cq.chg_pct), 4)
                            except Exception as e:
                                log.warning(f"Constituent {getattr(cq, 'symbol', '?')} chg_pct fetch failed: {e}")
                    try:
                        _spw = getattr(getattr(mkt_ctx, "confluence", None), "weighted_push", None)
                    except Exception as e:
                        log.warning(f"spy_weighted_push (confluence) failed: {e}")
                        _spw = None
                    try:
                        _qqqw = getattr(getattr(mkt_ctx, "qqq_confluence", None), "weighted_push", None)
                    except Exception as e:
                        log.warning(f"qqq_weighted_push (qqq_confluence) failed: {e}")
                        _qqqw = None

                    # IWM sectors from market context — wrap each fetch independently for partial results
                    _sect_map = {}
                    if hasattr(mkt_ctx, "iwm_sectors"):
                        for sq in mkt_ctx.iwm_sectors:
                            try:
                                if sq.chg_pct is not None:
                                    _sect_map[sq.symbol.upper()] = round(float(sq.chg_pct), 4)
                            except Exception as e:
                                log.warning(f"Sector {getattr(sq, 'symbol', '?')} chg_pct fetch failed: {e}")
                    try:
                        from market_context import iwm_blended_participation_push
                        _iwp = iwm_blended_participation_push(mkt_ctx)
                    except Exception as e:
                        log.warning(f"iwm_weighted_push (blended participation) failed: {e}")
                        _iwp = None
    
                    # VOL_INPUT_CONTRACT 1.0.0: snapshot row consumes the one
                    # per-cycle context (no re-tick, no independent vs-prev).
                    _vix_vs_prev = vol_ctx.market_iv_change
                    _vix_dir = vol_ctx.market_iv_direction
    
                    # ETF zone helper: derive bullish/bearish/neutral from chg_pct.
                    # Used for spy_zone / qqq_zone / iwm_zone in snapshot row.
                    def _etf_zone(chg):
                        if chg is None: return None
                        if float(chg) >  ETF_ZONE_THRESHOLD_PCT: return "bullish_trend"
                        if float(chg) < -ETF_ZONE_THRESHOLD_PCT: return "bearish_trend"
                        return "neutral"

                    # Price-action cone (operator 2026-06-11): persist bar-derived
                    # momentum/structure primitives from the in-memory 1m accumulator
                    # (completed bars only; bar_end <= ts_utc — leak-free). Honest
                    # nulls when history is short; never fabricated fills.
                    _pa_cols: dict[str, Any] = {}
                    try:
                        from types import SimpleNamespace as _PA_NS
                        from features.signal_layer_v1 import compute_price_action_snapshot_columns
                        _pa_bars = [
                            {
                                "bar_start_ts_utc": float(_cb.ts),
                                "bar_end_ts_utc": float(_cb.ts) + float(CANDLE_1M_SECONDS),
                                "open": _cb.open, "high": _cb.high, "low": _cb.low,
                                "close": _cb.close, "volume": _cb.volume,
                            }
                            for _cb in (_candles_1m.get_bars(ticker) or [])
                        ]
                        _pa_cols = compute_price_action_snapshot_columns(
                            _pa_bars, decision_ts_utc=float(_snap_ts), inp=_PA_NS(vwap=_vwap_f),
                        )
                    except Exception as e:
                        log.warning("price-action snapshot columns failed (%s): %s", ticker, e)
                        _pa_cols = {}

                    # RC-292/RC-429: the persisted quantity is UNCHANGED — terrain
                    # total-gamma, read from the renamed payload field. The DB column
                    # stays `gamma_pin` (historical schema; time_et.py owns its era
                    # semantics) so no third era is created by the rename.
                    _t_pin_snap = terrain_cache_get(ticker) or {}
                    _ssot_gamma_pin = (
                        _t_pin_snap.get("absolute_gamma_strike")
                        if _t_pin_snap and not _t_pin_snap.get("levels_stale")
                        else None
                    )

                    _snapshot_kwargs = dict(
                        **_pa_cols,
                        ticker=ticker,
                        timeframe=CANONICAL_TIMEFRAME,
                        expiry=selected_exp,
                        dte=_dte,
                        hours_to_expiry=_hours_to_expiry,
                        ts_utc=_snap_ts,
                        ts_et=build_ts_et(_et_now),
                        et_hour=et_h,
                        et_minute=et_m,
                        market_session=(session_label or "unknown").lower().replace("-", ""),
                        session_bucket=_session_bucket(et_h, et_m),
                        spot=spot_f,
                        spread=_quote_spread,
                        # Raw Schwab quote primitives (same parsed node as bid/ask/spread):
                        # quotes.{SYM}.bidPrice/askPrice/bidSize/askSize/lastSize/totalVolume.
                        bid_price=parsed_bid,
                        ask_price=parsed_ask,
                        bid_size=_session_q.get("bid_size"),
                        ask_size=_session_q.get("ask_size"),
                        last_size=_session_q.get("last_size"),
                        total_volume=(_total_vol if _total_vol is not None else _session_q.get("total_volume")),
                        candle_open=_c_open, candle_high=_c_high, candle_low=_c_low,
                        candle_close=_c_close, candle_volume=_c_vol, candle_direction=_candle_dir,
                        candle_body_pts=_candle_body, candle_range_pts=_c_range,
                        vwap=_vwap_f,
                        vwap_side=_row_vwap_side,
                        vwap_dist_pts=_vwap_dist,
                        pressure_label=_pressure_label_live,
                        pressure_trend=_pressure_trend_live,
                        pdh=getattr(price_levels, "pdh", None),
                        pdl=getattr(price_levels, "pdl", None),
                        pdc=getattr(price_levels, "pdc", None),
                        orb_high=getattr(price_levels, "orb_high", None),
                        orb_low=getattr(price_levels, "orb_low", None),
                        zone=ms.zone,
                        zone_since_bars=zt["since_bars_1m"],
                        zone_since_bars_1m=zt["since_bars_1m"],
                        zone_since_bars_5m=zt["since_bars_5m"],
                        prev_zone=zt["prev_zone"],
                        dist_call_gamma_wall=_dist_cgw, dist_put_gamma_wall=_dist_pgw,
                        dist_call_delta_wall=_dist_cdw, dist_put_delta_wall=_dist_pdw,
                        dist_gamma_inflection=_dist_gi, dist_delta_inflection=_dist_di,
                        dist_call_oi_wall=_dist_cow, dist_put_oi_wall=_dist_pow,
                        dist_call_vanna_wall=_dist_cvw, dist_put_vanna_wall=_dist_pvw,
                        call_gamma_wall=_cgw, put_gamma_wall=_pgw,
                        call_delta_wall=_cdw, put_delta_wall=_pdw,
                        gamma_inflection=_gi, delta_inflection=_di,
                        call_oi_wall=_cow, put_oi_wall=_pow,
                        call_vanna_wall=_cvw, put_vanna_wall=_pvw,
                        pin_width_pts=_pin_w,
                        nearest_above_name=ms.nearest_above_name if hasattr(ms, "nearest_above_name") else None,
                        nearest_above_val=ms.nearest_above_val if hasattr(ms, "nearest_above_val") else None,
                        nearest_above_dist=ms.nearest_above_dist if hasattr(ms, "nearest_above_dist") else None,
                        nearest_below_name=ms.nearest_below_name if hasattr(ms, "nearest_below_name") else None,
                        nearest_below_val=ms.nearest_below_val if hasattr(ms, "nearest_below_val") else None,
                        nearest_below_dist=ms.nearest_below_dist if hasattr(ms, "nearest_below_dist") else None,
                        net_gamma=ms.net_gamma, net_delta=ms.net_delta,
                        net_vanna=getattr(ms, "net_vanna", None),
                        charm_net=_charm_net, charm_direction=_charm_dir, charm_drift_toward=_charm_toward,
                        charm_magnitude=_charm_mag,
                        iv_level=(float(getattr(totals[0], "atm_iv")) if totals and getattr(totals[0], "atm_iv", None) is not None else None),  # percent for DB / iv_rank history
                        iv_direction=getattr(ms, "iv_direction", None),
                        put_call_oi_ratio=pcr_val,
                        oi_center=getattr(consensus_summary, "oi_center", None) if consensus_summary else None,
                        gamma_pin=_ssot_gamma_pin,
                        spy_spot=mkt_ctx.spy_last, spy_chg_pct=mkt_ctx.spy_chg_pct,
                        spy_zone=_etf_zone(mkt_ctx.spy_chg_pct), spy_vwap_side=None, spy_net_delta=None,
                        qqq_spot=mkt_ctx.qqq_last, qqq_chg_pct=mkt_ctx.qqq_chg_pct,
                        qqq_zone=_etf_zone(mkt_ctx.qqq_chg_pct), qqq_vwap_side=None, qqq_net_delta=None,
                        qqq_vs_spy=(round(float(mkt_ctx.qqq_chg_pct) - float(mkt_ctx.spy_chg_pct), 4)
                                    if mkt_ctx.qqq_chg_pct is not None and mkt_ctx.spy_chg_pct is not None else None),
                        qqq_vs_spy_delta=None,
                        iwm_spot=mkt_ctx.iwm_last, iwm_chg_pct=mkt_ctx.iwm_chg_pct,
                        iwm_zone=_etf_zone(mkt_ctx.iwm_chg_pct), iwm_vwap_side=None, iwm_net_delta=None,
                        iwm_vs_spy=(round(float(mkt_ctx.iwm_chg_pct) - float(mkt_ctx.spy_chg_pct), 4)
                                    if mkt_ctx.iwm_chg_pct is not None and mkt_ctx.spy_chg_pct is not None else None),
                        iwm_risk_signal=None,
                        nvda_chg_pct=_const_map.get("NVDA"),
                        aapl_chg_pct=_const_map.get("AAPL"),
                        msft_chg_pct=_const_map.get("MSFT"),
                        amzn_chg_pct=_const_map.get("AMZN"),
                        googl_chg_pct=_const_map.get("GOOGL"),
                        avgo_chg_pct=_const_map.get("AVGO"),
                        meta_chg_pct=_const_map.get("META"),
                        tsla_chg_pct=_const_map.get("TSLA"),
                        spy_weighted_push=round(float(_spw), 4) if _spw is not None else None,
                        qqq_weighted_push=round(float(_qqqw), 4) if _qqqw is not None else None,
                        kre_chg_pct=_sect_map.get("KRE"),
                        xbi_chg_pct=_sect_map.get("XBI"),
                        psci_chg_pct=_sect_map.get("PSCI"),
                        xrt_chg_pct=_sect_map.get("XRT"),
                        iwm_weighted_push=round(float(_iwp), 4) if _iwp is not None else None,
                        vix_level=vol_ctx.market_iv_level,
                        vix_direction=_vix_dir,
                        vix_vs_prev=_vix_vs_prev,
                        vix_bucket=(
                            _vix_bucket(vol_ctx.market_iv_level)
                            if vol_ctx.market_iv_level is not None else None
                        ),
                        rules_signal=ms.rules_signal,
                        rules_conviction=ms.rules_conviction,
                        rules_entry=ms.entry, rules_stop=ms.stop, rules_target=ms.target,
                        call_target2=ms.target2,
                        reward_risk=ms.reward_risk,
                        reward_risk2=ms.reward_risk2,
                        rules_summary=ms.rules_headline,
                        pred_1c_up_prob=ms.up_prob_1c, pred_1c_down_prob=ms.down_prob_1c,
                        pred_1c_flat_prob=ms.flat_prob_1c,
                        pred_5c_up_prob=ms.up_prob_5c, pred_5c_down_prob=ms.down_prob_5c,
                        pred_5c_flat_prob=ms.flat_prob_5c,
                        pred_15c_up_prob=ms.up_prob_15c, pred_15c_down_prob=ms.down_prob_15c,
                        pred_15c_flat_prob=ms.flat_prob_15c,
                        pred_60c_up_prob=getattr(ms, "up_prob_60c", None),
                        pred_60c_down_prob=getattr(ms, "down_prob_60c", None),
                        pred_60c_flat_prob=getattr(ms, "flat_prob_60c", None),
                        pred_model_version=ms.model_version or "rules_v1",
                        pred_model_source=getattr(ms, 'pred_model_source', None),
                        pred_override_source=getattr(ms, 'pred_override_source', None),
                        logger_source=_resolved_logger_source,
                        pred_confidence=ms.confidence,
                        pred_samples_used=ms.samples_used,
                        prediction_direction=getattr(ms, 'dominant_dir', None),
                        prediction_dominant_prob=getattr(ms, 'dominant_prob', None),
                        combined_signal=ms.call_signal,
                        combined_conviction=ms.call_conviction,
                        rules_pred_agree=ms.rules_pred_agree,
                        # ── Model stack (regime, fusion, MC, individual models) ────
                        regime_primary=getattr(ms, 'regime_primary', None),
                        regime_confidence=getattr(ms, 'regime_confidence', None),
                        regime_score=getattr(ms, 'regime_score', None),
                        fusion_dominant=getattr(ms, 'fusion_dominant', None),
                        fusion_dominant_prob=getattr(ms, 'fusion_dominant_prob', None),
                        fusion_confidence=getattr(ms, 'fusion_confidence', None),
                        fusion_breakout=getattr(ms, 'fusion_breakout', None),
                        fusion_pinning=getattr(ms, 'fusion_pinning', None),
                        fusion_continuation=getattr(ms, 'fusion_continuation', None),
                        fusion_reversal=getattr(ms, 'fusion_reversal', None),
                        fusion_vol_expansion=getattr(ms, 'fusion_vol_expansion', None),
                        fusion_mean_reversion=getattr(ms, 'fusion_mean_reversion', None),
                        fusion_model_agreement=getattr(ms, 'fusion_model_agreement', None),
                        fusion_n_models_active=getattr(ms, 'fusion_n_models_active', None),
                        fusion_prob_up=getattr(ms, 'fusion_prob_up', None),
                        fusion_prob_down=getattr(ms, 'fusion_prob_down', None),
                        fusion_prob_flat=getattr(ms, 'fusion_prob_flat', None),
                        fusion_dominant_direction=getattr(ms, 'fusion_dominant_direction', None),
                        mc_efe=getattr(ms, 'mc_efe', None),
                        mc_eae=getattr(ms, 'mc_eae', None),
                        mc_containment=getattr(ms, 'mc_containment', None),
                        mc_expansion=getattr(ms, 'mc_expansion', None),
                        mc_upper_50=getattr(ms, 'mc_upper_50', None),
                        mc_lower_50=getattr(ms, 'mc_lower_50', None),
                        mc_paths=getattr(ms, 'mc_paths', None),
                        mc_horizon=getattr(ms, 'mc_horizon', None),
                        mc_vol_source=getattr(ms, 'mc_vol_source', None),
                        mc_sigma_value=getattr(ms, 'mc_sigma_value', None),
                        # ── Individual model outputs (stack visibility) ─────────────────
                        xgb_available=getattr(ms, 'xgb_available', None),
                        xgb_dominant=getattr(ms, 'xgb_dominant', None),
                        xgb_confidence=getattr(ms, 'xgb_confidence', None),
                        xgb_approved=getattr(ms, 'xgb_approved', None),
                        lstm_available=getattr(ms, 'lstm_available', None),
                        lstm_dominant=getattr(ms, 'lstm_dominant', None),
                        lstm_confidence=getattr(ms, 'lstm_confidence', None),
                        lstm_approved=getattr(ms, 'lstm_approved', None),
                        transformer_available=getattr(ms, 'transformer_available', None),
                        transformer_dominant=getattr(ms, 'transformer_dominant', None),
                        transformer_confidence=getattr(ms, 'transformer_confidence', None),
                        transformer_approved=getattr(ms, 'transformer_approved', None),
                        # ── Volatility signals ─────────────────────────────────
                        iv_skew=_iv_skew.get("skew"),
                        realized_vol=_realized_vol,
                        atr=_atr,
                        iv_rank=_iv_rank,
                        iv_percentile=_iv_percentile,
                        # ── Section 8 predictive signals ───────────────────────
                        dpi_raw=_dpi.get("raw"),
                        dpi_normalized=_dpi.get("normalized"),
                        dpi_direction=_dpi.get("direction"),
                        hedging_flow_score=_hedging_flow.get("normalized"),
                        hedging_flow_direction=_hedging_flow.get("direction"),
                        gamma_gradient=_gamma_gradient,
                        breakout_score=_breakout_score.get("normalized"),
                        pin_score=_pin_score_val.get("normalized"),
                        vol_expansion_score=_vol_expansion.get("normalized"),
                        sweep_score=_sweep_score.get("normalized"),
                        # ── Session levels + sweeps ────────────────────────────
                        session_high=getattr(ms, 'session_high', None),
                        session_low=getattr(ms, 'session_low', None),
                        last_sweep_type=getattr(ms, 'last_sweep_type', None),
                        last_sweep_level=getattr(ms, 'last_sweep_level', None),
                        last_sweep_held=getattr(ms, 'last_sweep_held', None),
                        n_sweeps_today=getattr(ms, 'n_sweeps_today', 0),
                        # ── Trade Validation Gate ──────────────────────────
                        validation_passed=getattr(ms, 'validation_passed', None),
                        structure_valid=getattr(ms, 'structure_valid', None),
                        probability_valid=getattr(ms, 'probability_valid', None),
                        risk_valid=getattr(ms, 'risk_valid', None),
                        validation_summary=getattr(ms, 'validation_summary', ''),
                        # ── Position Sizing ────────────────────────────────────
                        r_units=getattr(ms, 'r_units', None),
                        execution_mode=getattr(ms, 'execution_mode', 'NO_TRADE'),
                        # ── Catalog signals ────────────────────────────────────
                        vol_env_upper=_vol_envelope.get("upper"),
                        vol_env_lower=_vol_envelope.get("lower"),
                        level_density_count=_level_density.get("count"),
                        level_density_label=_level_density.get("density_label"),
                        sector_leader=_sector_strength.get("leader"),
                        sector_laggard=_sector_strength.get("laggard"),
                        sector_breadth=_sector_strength.get("breadth"),
                        sector_risk_signal=_sector_strength.get("risk_signal"),
                        index_leader=_index_strength.get("leader"),
                        index_laggard=_index_strength.get("laggard"),
                        index_breadth=_index_strength.get("breadth"),
                        index_risk_signal=_index_strength.get("risk_signal"),
                        spy_holdings_leader=_spy_strength.get("leader"),
                        spy_holdings_laggard=_spy_strength.get("laggard"),
                        spy_holdings_breadth=_spy_strength.get("breadth"),
                        spy_holdings_risk=_spy_strength.get("risk_signal"),
                        # ── IWM Deep Confluence ────────────────────────────────
                        iwm_risk_regime=_iwm_deep.get("risk_regime"),
                        iwm_risk_score=_iwm_deep.get("risk_score"),
                        spy_iwm_divergence=_iwm_deep.get("spy_iwm_divergence"),
                        spy_iwm_fragile=_iwm_deep.get("spy_iwm_fragile"),
                        iwm_early_warning=_iwm_deep.get("early_warning"),
                        rotation_signal=_iwm_deep.get("rotation_signal"),
                        # ── Bond Yields ────────────────────────────────────────
                        tnx_yield=getattr(mkt_ctx, 'tnx_yield', None),
                        tnx_chg=getattr(mkt_ctx, 'tnx_chg', None),
                        bond_signal=getattr(mkt_ctx, 'bond_signal', None),
                        # ── Order Flow Signals ─────────────────────────────────
                        vol_oi_ratio=_vol_oi_ratio.get("ratio"),
                        flow_imbalance=_flow_imb_norm,
                        flow_imbalance_source=_flow_imb_source,  # RC-345/F11: persist economic book identity
                        smart_money_score=_smart_money.get("score"),
                        smart_money_direction=_smart_money.get("direction"),
                        iv_model_spread=_iv_model_spread.get("spread"),
                        option_chain_json=serialize_option_chain_for_eval(contracts_use, selected_exp),
                        replay_context_json=build_replay_context_payload(
                            walls=walls,
                            totals=totals,
                            option_chain_selection_proof=getattr(ms, "option_chain_selection_proof", None),
                            regime_primary=getattr(ms, "regime_primary", None),
                            regime_confidence=getattr(ms, "regime_confidence", None),
                            zone=getattr(ms, "zone", None),
                            vol_regime=getattr(ms, "vol_regime", None),
                            trade_type=getattr(ms, "trade_type", None),
                            time_qualifier=getattr(ms, "time_qualifier", None),
                            replay_max_hold_bars_live=getattr(ms, "replay_max_hold_bars", None),
                            vwap=_vwap_f,
                            vwap_side=_row_vwap_side,
                        ),
                        absorption_score=(getattr(ms, "liquidity_behavior", None) or {}).get("absorption_score"),
                        continuation_score=(getattr(ms, "liquidity_behavior", None) or {}).get("continuation_score"),
                        liquidity_behavior_label=(getattr(ms, "liquidity_behavior", None) or {}).get("behavior_label"),
                        sentiment_composite=(getattr(ms, "news_context", None) or {}).get("sentiment_composite"),
                        sentiment_buzz=(getattr(ms, "news_context", None) or {}).get("sentiment_buzz"),
                        sentiment_finnhub=(getattr(ms, "news_context", None) or {}).get("sentiment_finnhub"),
                        sentiment_av=(getattr(ms, "news_context", None) or {}).get("sentiment_av"),
                        breaking_news_flag=(1 if (getattr(ms, "news_context", None) or {}).get("breaking_news_flag") else 0),
                        breaking_news_headline=(getattr(ms, "news_context", None) or {}).get("breaking_news_headline"),
                        pre_market_sentiment=(getattr(ms, "news_context", None) or {}).get("pre_market_sentiment"),
                    )
                    # FIND-GAMMA-FULLCHAIN-STRIKES-V1: once/day morning *wide*
                    # near-term chain (strike_count=GEX_FULL_CHAIN_STRIKE_COUNT).
                    # Does NOT reuse the live UI 20-strike ``contracts`` list.
                    # Idempotent before fetch; never widens option_chain_json;
                    # try/except so live path is untouched on any failure.
                    try:
                        _gex_tk = str(ticker).upper()
                        if _gex_tk in ("SPY", "QQQ", "IWM"):
                            from calibration.option_chain_morning_full import (
                                GEX_FULL_CHAIN_STRIKE_COUNT as _GEX_STRIKES,
                                MORNING_END_MINS as _GEX_END,
                                MORNING_START_MINS as _GEX_START,
                                SOURCE_WIDE as _GEX_SRC,
                                et_date_and_mins as _gex_et,
                                has_morning_full_capture,
                                maybe_persist_morning_full_chain,
                            )
                            from db import DB_PATH as _gex_db_path

                            _gex_date, _gex_mins = _gex_et(float(_snap_ts))
                            if _GEX_START <= _gex_mins <= _GEX_END and not has_morning_full_capture(
                                _gex_db_path, _gex_tk, _gex_date
                            ):
                                _wide_resp, _, _ = _gated_safe_get_chain(
                                    client,
                                    ticker,
                                    # The once-daily WIDE research capture deliberately takes the
                                    # maximum vendor-safe width, not this ticker's minimum
                                    # sufficient width: its whole purpose is to preserve strikes
                                    # the live faucet would trim.
                                    strike_count=_GEX_STRIKES,  # chain-width-faucet-ok: wide research capture takes max width by design
                                    priority=False,
                                )
                                _wide_contracts: list = []
                                if (
                                    _wide_resp is not None
                                    and getattr(_wide_resp, "status_code", None) == 200
                                ):
                                    _wj = _wide_resp.json()
                                    for _side_key in ("callExpDateMap", "putExpDateMap"):
                                        _side_map = _wj.get(_side_key) or {}
                                        if not isinstance(_side_map, dict):
                                            continue
                                        for _exp_map in _side_map.values():
                                            if not isinstance(_exp_map, dict):
                                                continue
                                            for _strike_list in _exp_map.values():
                                                if not isinstance(_strike_list, list):
                                                    continue
                                                for _ct in _strike_list:
                                                    if isinstance(_ct, dict):
                                                        _wide_contracts.append(dict(_ct))
                                if _wide_contracts:
                                    maybe_persist_morning_full_chain(
                                        _gex_db_path,
                                        ticker=_gex_tk,
                                        contracts=_wide_contracts,
                                        spot=float(spot) if spot is not None else None,
                                        ts_utc=float(_snap_ts),
                                        source=_GEX_SRC,
                                    )
                    except Exception as _gex_chain_e:
                        log.warning(
                            "option_chain_morning_full persist failed ticker=%s: %s",
                            ticker,
                            _gex_chain_e,
                        )
                    _mh_live = getattr(ms, "movement_head_probs", None)
                    if isinstance(_mh_live, dict):
                        for _k, _v in _mh_live.items():
                            if not isinstance(_k, str) or _v is None:
                                continue
                            try:
                                _fv = float(_v)
                            except (TypeError, ValueError):
                                continue
                            if _fv == _fv and abs(_fv) != float("inf"):
                                _snapshot_kwargs[_k] = _fv
                    _fp_live = getattr(ms, "fusion_policy_snapshot_cols", None)
                    if isinstance(_fp_live, dict):
                        for _k, _v in _fp_live.items():
                            if not isinstance(_k, str) or _v is None:
                                continue
                            if _k.startswith("fused_contributing_models_") or _k.startswith("fused_stack_status_"):
                                if isinstance(_v, str):
                                    _snapshot_kwargs[_k] = _v[:8000]
                                continue
                            try:
                                _fv = float(_v)
                            except (TypeError, ValueError):
                                continue
                            if _fv == _fv and abs(_fv) != float("inf"):
                                _snapshot_kwargs[_k] = _fv
                    # ECON-01 producer guard (fail-LOUD, 2026-07-11): a tradeable
                    # decision row persisting without execution-replay context is
                    # starvation at the source — replay can never recover it later
                    # without fabricating history. Coverage at audit was 100%
                    # (1,263/1,263 trailing-30d long/short rows); this guard keeps
                    # any regression visible on the day it happens.
                    # Schwab CSV authority checked: yes
                    # CSV row(s): NO_SCHWAB_EQUIVALENT — observability guard only;
                    #   no market field read, derived, or emitted by this block.
                    # Derived-field disposition: none required.
                    # All consumers checked: yes — log line only; snapshot insert
                    #   proceeds unchanged (history is never dropped).
                    # SCHWAB_CSV_CHECKED
                    from realized_contract_eval import decision_row_context_starvation_reason

                    _starve_reason = decision_row_context_starvation_reason(
                        combined_signal=_snapshot_kwargs.get("combined_signal"),
                        replay_context_json=_snapshot_kwargs.get("replay_context_json"),
                        option_chain_json=_snapshot_kwargs.get("option_chain_json"),
                    )
                    if _starve_reason:
                        log.error(
                            "REPLAY_CONTEXT_STARVATION ticker=%s signal=%s reason=%s "
                            "(ECON-01 producer guard: tradeable row missing execution context)",
                            ticker,
                            _snapshot_kwargs.get("combined_signal"),
                            _starve_reason,
                        )
                    # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the identity
                    # anchor now lives at the pre-publish site (before the
                    # decision finalize AND this tail); the tail only CONSUMES
                    # the anchored pair. Fail-closed unchanged: a MODEL-DERIVED
                    # snapshot with no anchored identity is REFUSED (loud ERROR
                    # + skip) — never persisted without its immutable identity.
                    # Quote-only rows (no combined_signal) stay NOT_APPLICABLE.
                    # Schwab CSV authority checked: yes
                    # CSV row(s): NO_SCHWAB_EQUIVALENT — provenance linkage only;
                    #   no market field read, derived, or emitted by this block.
                    # Derived-field disposition: none required.
                    # All consumers checked: yes — additive identity fields.
                    # SCHWAB_CSV_CHECKED
                    _xid_refused = False
                    if _snapshot_kwargs.get("combined_signal") is not None:
                        _xid_pair_snap = getattr(ms, "_execution_identity_pair", None)
                        if _xid_pair_snap:
                            _snapshot_kwargs["decision_id"] = _xid_pair_snap[0]
                            _snapshot_kwargs["execution_identity_sha256"] = _xid_pair_snap[1]
                            _snapshot_kwargs["execution_identity_class"] = "MODEL_DERIVED"
                        else:
                            log.error(
                                "EXECUTION_IDENTITY_REFUSED ticker=%s reason=%s — "
                                "model-derived snapshot write REFUSED (fail closed)",
                                ticker,
                                "no anchored execution identity for this cycle "
                                "(pre-publish anchor missing or refused)",
                            )
                            _xid_refused = True
                    _snapshotrow_field_names = set(getattr(SnapshotRow, "__annotations__", {}).keys())
                    _dropped_snapshot_fields = sorted(k for k in _snapshot_kwargs if k not in _snapshotrow_field_names)
                    if _dropped_snapshot_fields:
                        log.warning("SnapshotRow field drift detected; dropping unsupported fields: %s", _dropped_snapshot_fields)
                    if _xid_refused:
                        _snapshot_row_insert_release(ticker, _snap_ts)
                    elif not is_capturable_session():
                        # RC-48: off-hours (overnight / weekend / full holiday) snapshot carries
                        # no signal — options don't trade and spot doesn't move — is excluded from
                        # training (ml_train RTH filter) and read by nothing. The SSE _fetch_state
                        # path had no session gate (only the 1/min throttle), so a viewer left
                        # connected off-hours wrote a row every minute. Do not persist; release the
                        # minute reservation so throttle bookkeeping stays clean. Premarket/RTH/
                        # afterhours are unaffected (is_capturable_session is True for [04:00,20:00)
                        # ET on a trading calendar day).
                        _snapshot_row_insert_release(ticker, _snap_ts)
                        log.debug("RC-48 off-hours snapshot skip: %s (session not capturable)", ticker)
                    else:
                        _snap = SnapshotRow(**{k: v for k, v in _snapshot_kwargs.items() if k in _snapshotrow_field_names})
                        _ed_db.insert_snapshot(_snap)
                        _snapshot_row_insert_committed(ticker, _snap_ts)
                        _snap_insert_landed = True
                        if _snapshot_kwargs.get("execution_identity_sha256"):
                            from execution_identity import mark_surface_landed as _xid_mark

                            with _ed_db._connect() as _xconn2:
                                _xid_mark(_xconn2, _snapshot_kwargs["decision_id"], "snapshot")
                # LIVE_OPERATOR_MODE_RESET_V1 Step 3 — bars persist + outcome backfill ride
                # the snapshot throttle (1/min/ticker): per-refresh writes contended with the
                # live path; bars re-seed from Schwab pricehistory after any gap and labels
                # only advance when new rows exist.
                #
                # Lane-4 (2026-07-05) measured the bar write at 8,090.8ms of the 10,760ms
                # db_snapshot_write_accuracy stage and moved it off the synchronous path onto
                # this ordered background task.
                # RC-69 (2026-07-27) went further and removed the bar write from this render
                # path ENTIRELY. Persisting bars here made COLLECTION a side-effect of DISPLAY:
                # a ticker only got bars while it was on screen. The bar collection service
                # (_bars_loop) is now the single writer, running the whole enrolled universe on
                # its own cadence, so bars are durable independently of any render and the
                # old upsert-before-fill ordering race disappears with the upsert.
                # What remains on this task is outcome labelling for the snapshot just written.
                # Schwab CSV authority checked: yes
                # CSV row(s): pricehistory.candles[].open/high/low/close/volume — persistence
                #   scheduling only; no market field read, derivation, emission, or
                #   actionability logic changed; bar values and their Schwab leaf unchanged.
                # Derived-field disposition: none required.
                # All consumers checked: yes — upsert return value unread at this call site;
                #   fill_outcomes ordering preserved by the max_workers=1 executor.
                # SCHWAB_CSV_CHECKED
                if _do_insert:
                    # RC-69 SINGLE BAR FAUCET: this render path no longer PERSISTS bars. It used
                    # to be the only writer, which made bar collection a side-effect of display —
                    # MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar lag 3.1 min vs QQQ 19.1
                    # and IWM 19.1 (off screen), while all three had ~1.0 min snapshot lag, and
                    # 39.8% of all snapshots carry unfilled outcomes because the forward bars they
                    # needed were never written. `_bars_loop` is now the ONE writer of
                    # price_bars_1m, running for every enrolled ticker regardless of the viewport.
                    # The accumulator is still ticked above for this card's own forming candle.
                    # fill_outcomes stays here: it labels the snapshot just inserted.
                    def _bg_persist_bars_then_fill_outcomes() -> None:
                        try:
                            get_db().fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)
                        except Exception as ex:
                            log.warning(
                                "fill_outcomes_bg failed ticker=%s thread=%s: %s",
                                ticker,
                                threading.current_thread().name,
                                ex,
                            )

                    _get_db_fill_outcomes_executor().submit(_bg_persist_bars_then_fill_outcomes)
                # Heavy normalized-table materialize must not run from every snapshot by default;
                # set ED_LIVE_SNAPSHOT_MATERIALIZE=1 to re-enable debounced refresh on this path, or use ml_scheduler/CLI.
                if os.environ.get("ED_LIVE_SNAPSHOT_MATERIALIZE", "0").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                ):
                    try:
                        from normalized_training_sync import schedule_debounced_normalized_refresh

                        schedule_debounced_normalized_refresh(_ed_db.db_path, logger=log)
                    except Exception as _nz:
                        log.warning("schedule normalized refresh: %s", _nz)
                db_counts = _ed_db.count_snapshots(ticker, CANONICAL_TIMEFRAME)
                if _do_insert:
                    log.info(f"DB snapshot logged: {ticker} total={db_counts['total']} filled={db_counts['filled']} signal={ms.rules_signal}")

                # ── Periodic accuracy tracking (~every 10 min per ticker) ─────────
                _last_acc = _accuracy_cache.get(ticker, {}).get("ts", 0)
                if time.time() - _last_acc > ACCURACY_INTERVAL and db_counts["filled"] >= 50:
                    try:
                        # RTH-scoped accuracy is the trading-relevance primary
                        # (operator decision 2026-07-06); all-hours kept as audit
                        # context only. Fail-closed: an empty RTH scope yields
                        # accuracy None — never silently widened to all-hours.
                        _acc_version = _current_pred_model_version(ticker)
                        acc = _ed_db.compute_accuracy(
                            ticker, CANONICAL_TIMEFRAME,
                            model_version=_acc_version, rth_only=True,
                        )
                        _acc_all_hours = _ed_db.compute_accuracy(
                            ticker, CANONICAL_TIMEFRAME,
                            model_version=_acc_version, rth_only=False,
                        )
                        _accuracy_cache[ticker] = {
                            "ts": time.time(), "results": acc, "all_hours": _acc_all_hours,
                        }
                        _acc_5c = acc.get("5c", {}).get("accuracy")
                        _acc_n  = acc.get("5c", {}).get("total", 0)
                        _acc_edge = acc.get("5c", {}).get("edge_vs_baseline_pp")
                        log.info(
                            f"Accuracy computed (RTH scope): {ticker} 5c={_acc_5c}% "
                            f"({_acc_n} predictions, edge_vs_baseline={_acc_edge}pp)"
                        )
                    except Exception as _ae:
                        log.warning(f"Accuracy computation failed: {_ae}")
            except Exception as e:
                if _do_insert and not _snap_insert_landed:
                    _snapshot_row_insert_release(ticker, _snap_ts)
                _diag_crash("db_snapshot", e, ticker)
                import traceback as _tb
                _analytics_cache_observability["post_publish_snapshot_failures"] += 1
                _record_post_publish_failure("snapshot", ticker, published_version, e)
                log.warning(
                    f"post-publish snapshot persistence failed ticker={ticker} "
                    f"published_version={published_version}: {e}\n{_tb.format_exc()}"
                )
            if _diag_on():
                _diag_done("db_snapshot", ticker)
        _stage_marks.append(("db_snapshot_write_accuracy", time.perf_counter()))

        try:
            from calibration.v2_live_logging import (
                LIVE_ADVISORY_V2_TAIL_APPEND,
                append_live_v2_calibration_decision,
                resolve_live_v2_calibration_tail_action,
            )
            from db import DB_PATH as _calibration_db_path

            _xid_pair_cal = getattr(ms, "_execution_identity_pair", None)
            _tail_action = resolve_live_v2_calibration_tail_action(
                model_derived_cycle=bool(_xid_model_derived),
                has_execution_identity=_xid_pair_cal is not None,
                snap_insert_landed=bool(_snap_insert_landed),
            )
            if _tail_action != LIVE_ADVISORY_V2_TAIL_APPEND:
                # Idle/non-model skip or FP-24 no-colocated-snapshot skip.
                _v2_log_result = {"status": "skipped", "reason": _tail_action}
            else:
                _v2_log_result = append_live_v2_calibration_decision(
                    db_path=_calibration_db_path,
                    calibration_payload=getattr(ms, "_calibration_payload", None),
                    v2_decision=v2_decision_for_log,
                    decision_id=_xid_pair_cal[0] if _xid_pair_cal else None,
                    execution_identity_sha256=_xid_pair_cal[1] if _xid_pair_cal else None,
                    colocated_snapshot_ts_utc=float(_snap_ts),
                )
            if _v2_log_result and _v2_log_result.get("status") != "ok":
                log.debug("live v2 calibration logging skipped: %s", _v2_log_result)
            if _v2_log_result and _v2_log_result.get("status") == "ok" and _xid_pair_cal:
                from execution_identity import mark_surface_landed as _xid_mark_cal

                with get_db()._connect() as _xconn_cal:
                    _xid_mark_cal(_xconn_cal, _xid_pair_cal[0], "calibration")
        except Exception as _v2_log_e:
            _analytics_cache_observability["post_publish_calibration_failures"] += 1
            _record_post_publish_failure("calibration", ticker, published_version, _v2_log_e)
            log.warning(
                "post-publish calibration append failed ticker=%s published_version=%s: %s",
                ticker,
                published_version,
                _v2_log_e,
            )
        _stage_marks.append(("v2_calibration_logging", time.perf_counter()))

    # ── If log_only, persist then touch cache (clobber-guarded) and return ────
    # ANALYTICS_LOG_ONLY_CACHE_CLOBBER_GUARD_V1: never replace a publishable
    # bundle with an empty-ms_dict minimal entry (see _log_only_cache_touch).
    # FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1: the log_only path has no publish, so
    # its persistence order is unchanged — tail first, exactly as before.
    if log_only:
        _post_publish_persistence_tail(None, _v2_decision_for_response)
        _log_only_cache_touch(
            _cache_key,
            ticker,
            selected_exp,
            pcr_val,
            spot_f,
            # VOL_INPUT_CONTRACT 1.0.0 single-source: the published "vix"
            # (next cycle's prev source) comes from the per-cycle context.
            # Schwab CSV authority checked: yes
            # CSV row(s): quotes.$VIX.lastPrice (same primitive; vol_ctx.market_iv_level
            #   IS the converted quote — no new derivation, no NO_SCHWAB_EQUIVALENT change)
            # Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE
            # All consumers checked: yes — cache "vix" publishes + SignalInput vix_bucket
            #   now consume vol_ctx; zero raw reads outside the canonical conversion
            #   (AST lock in tests/test_market_context_fetch_fail_closed.py).
            # SCHWAB_CSV_CHECKED
            vol_ctx.market_iv_level,
        )
        return {}

    # ── Build full API response dict ──────────────────────────────────────────
    ms_dict             = _ms_to_dict(ms)
    ms_dict["analytics_partial_tier_c"] = False
    ms_dict["expiries"] = [e for e in expiries if e >= _today_str]
    ms_dict["selected_exp"] = selected_exp
    ms_dict["quote_source_detail"] = {
        "spot": "lastPrice" if parsed_last and parsed_last > 0 else ("mark" if parsed_mark and parsed_mark > 0 else "unavailable_missing_last_and_mark"),
        "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
        "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
        "spread": _quote_spread_source,
        "spread_age_ms": _quote_spread_age_ms,
        "carried_forward": _quote_spread_source == "cached_last_valid_not_tradeable",
    }
    ms_dict["spread"] = _quote_spread_pts
    ms_dict["spread_frac"] = _quote_spread_frac
    ms_dict["spread_pts"] = _quote_spread_pts
    ms_dict["spread_source"] = _quote_spread_source
    ms_dict["spread_frac_source"] = _quote_spread_frac_source
    ms_dict["spread_pts_source"] = (
        "derived_bid_ask_pts_schwab_quote" if _quote_spread_pts is not None else None
    )
    ms_dict["spread_age_ms"] = _quote_spread_age_ms
    # VOL_INPUT_CONTRACT 1.0.0: ms_dict consumes the one per-cycle context —
    # identical values to the SignalInput stamp and the snapshot row (MSD-001).
    ms_dict["vix"] = vol_ctx.market_iv_level
    ms_dict["vix_direction"] = vol_ctx.market_iv_direction
    ms_dict["vix_vs_prev"] = vol_ctx.market_iv_change
    ms_dict["server_ts"]    = time.time()
    # Client diagnostics: when a tab has SSE open for this (ticker, expiry), full pipeline re-runs about this often.
    ms_dict["sse_viewer_refresh_sec"] = round(VIEWER_SSE_REFRESH_SEC, 3)
    ms_dict["sse_viewer_rest_cache_ttl_sec"] = round(VIEWER_STATE_CACHE_TTL_SEC, 3)
    try:
        from api_pressure import throttle_ui_payload

        ms_dict["api_throttle"] = throttle_ui_payload()
    except ImportError:
        ms_dict["api_throttle"] = {"active": False, "message": "", "hint": "", "n_429_recent": 0}
    ms_dict["pcr_val"]      = pcr_val

    # charm_net / charm_direction / charm_direction_display / charm_drift_toward
    # are already on MarketState (set in build_market_state) so _ms_to_dict
    # carries them. No override needed here.

    ms_dict["pred_override"] = _get_prediction_override(ticker)

    # Liquidity-behavior + news/sentiment (additive; same data also on snapshot rows)
    ms_dict["context_layer"] = {
        "liquidity_behavior": getattr(ms, "liquidity_behavior", None),
        "news": getattr(ms, "news_context", None),
    }

    # ── Key level prices (wall values not on MarketState dataclass fields) ────
    w0 = walls[0] if walls else None
    cs = consensus_summary

    def _fv(v):
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None

    # RC-128 (One Levels Faucet): the wall/level assignments that lived here were DELETED,
    # not overridden — _terrain_kl_overlay below is the ONLY writer of every SSOT level key.
    # Placement was the bug: any assignment after the overlay resurrected the dual book.

    # ── Wall strengths (formatted strings) ────────────────────────────────────
    def _fs(v):
        try:
            f = float(v)
            if f >= 1_000_000: return f"${f/1_000_000:.1f}M/pt"
            if f >= 1_000:     return f"${f/1_000:.0f}K/pt"
            return f"${f:.0f}/pt"
        except (TypeError, ValueError):
            return "—"

    def _foi(v):
        try:
            f = float(v)
            if f >= 1_000_000: return f"{f/1_000_000:.1f}M OI"
            if f >= 1_000:     return f"{f/1_000:.0f}K OI"
            return f"{f:.0f} OI"
        except (TypeError, ValueError):
            return "—"

    # RC-128: strength strings deleted with their book — a dollar strength computed from the
    # analytics chain beside an SSOT strike is the dual-book lie in a smaller cell. The
    # overlay blanks every strength it does not own.

    # ── New institutional levels ───────────────────────────────────────────────
    # RC-128: pin/hvl/max-pain/flip/oi_center and their strength strings deleted — the
    # overlay below is the only writer for the SSOT set and blanks unowned strengths.
    # v23: the flip CONFIDENCE writes that lived here were the last half of the dual book —
    # narrow-analytics confidence stamped beside a terrain flip strike. Deleted, not
    # overridden; the overlay now writes kl_gamma_flip_confidence from the SAME terrain
    # payload as the strike. kl_gamma_flip_diag had ZERO consumers repo-wide (client,
    # tests, server reads all enumerated 2026-07-29) — an orphan narrow-book key, deleted.

    # ── Terrain read: single source of truth (RC-33) ─────────────────────────
    # Terrain regime/posture/headline/lines are served ONLY by /api/terrain
    # (terrain_engine.compute_terrain) on the wide-capture multi-expiry chain.
    # This analytics-state pipeline used to attach a SECOND terrain read computed
    # on the selected-expiry (0DTE) slice alone — a chain too narrow to trust, so
    # it fail-closed to UNAVAILABLE/STAND_ASIDE and contradicted the card's
    # SHORT_GAMMA_TREND for the same ticker at the same instant. Those four
    # terrain_* fields were read by nothing (whole-repo consumer audit) and are
    # removed: one terrain, one chain. The narrow-chain confidence gate in
    # compute_gamma_flip_v2 stays as the fail-closed backstop — the fix is
    # single-source, not gate-weakening (operator decision 2026-07-24).

    _net_gex_raw = getattr(cs, "net_gamma", None) if cs else None
    try:
        _net_gex_f = float(_net_gex_raw) if _net_gex_raw is not None else None
    except (TypeError, ValueError):
        _net_gex_f = None
    ms_dict["kl_net_gex"] = round(_net_gex_f, 2) if _net_gex_f is not None else None
    if _net_gex_f is not None:
        from math_exposure import fmt_money as _fmt_gex_money
        ms_dict["kl_net_gex_disp"] = _fmt_gex_money(_net_gex_f)
        ms_dict["kl_net_gex_mag"] = gex_magnitude_label(_net_gex_f)
        ms_dict["kl_net_gex_regime"] = gex_regime_label(_net_gex_f)
    else:
        ms_dict["kl_net_gex_disp"] = "—"
        ms_dict["kl_net_gex_mag"] = "negligible"
        ms_dict["kl_net_gex_regime"] = "neutral"
    ms_dict["kl_expiry_source"] = _kl_expiry_source
    ms_dict["kl_level_window"] = "selected_expiry"
    ms_dict["kl_metrics_dollarized"] = bool(exposures and exposures_have_dollar_gex(exposures))
    ms_dict["kl_institutional_ready"] = ms_dict["kl_metrics_dollarized"]
    _kl_contracts_total = max(int(getattr(diag, "contracts_total", 0) or 0), 1)
    ms_dict["kl_gex_input_completeness"] = round(
        float(getattr(diag, "contracts_used", 0) or 0) / _kl_contracts_total,
        4,
    )
    _em_up_straddle = _fv(_em_straddle.get("upper"))
    _em_lo_straddle = _fv(_em_straddle.get("lower"))
    _em_up_iv = _fv(_em_iv.get("upper"))
    _em_lo_iv = _fv(_em_iv.get("lower"))
    # RC-128 / E-34 closed: kl_em_* now comes ONLY from the terrain sigma band via the
    # overlay. The straddle/IV figures stay published as em_straddle_* — a diagnostic that
    # never shares the level vocabulary — and mc_em_anchor keeps its consumer.
    ms_dict["em_straddle_upper_diag"] = _em_up_straddle or _em_up_iv
    ms_dict["em_straddle_lower_diag"] = _em_lo_straddle or _em_lo_iv
    ms_dict["kl_em_anchor"] = _kl_em_anchor
    ms_dict["mc_em_anchor"] = _kl_em_anchor
    ms_dict["mc_iv_source"] = _mc_iv_source
    ms_dict["kl_gamma_voids"]  = _gamma_voids or []
    # RC-122: applied AFTER every kl_* assignment above (a first placement two pages up was
    # silently overwritten by the pin/hvl/flip writes below it — placement IS the fix here).
    # The gamma-family values were computed from the narrow analytics chain; the screen gets
    # ONE book (terrain SSOT) or an honest blank.
    _terrain_kl_overlay(ms_dict, ticker)
    if not _gamma_voids:
        # Diagnostic: why no voids?
        _n_strikes = len(exposures)
        _gex_vals = [
            v
            for b in exposures.values()
            if (v := total_gamma_raw_at_strike(b)) is not None
        ]
        _max_gex = max(_gex_vals, default=0)
        _oi_values = [_bucket_total_oi(b) for b in exposures.values()]
        _oi_values = [v for v in _oi_values if v is not None]
        _max_oi = max(_oi_values, default=0)
        log.debug(f"Gamma void: {_n_strikes} strikes, max_gex={_max_gex:.0f}, max_oi={_max_oi:.0f}, spot_passed={'yes' if spot_f else 'no'}")
        # Count how many strikes pass each threshold independently
        _gex_low = (
            sum(
                1
                for b in exposures.values()
                if (v := total_gamma_raw_at_strike(b)) is not None
                and v < _max_gex * 0.20
            )
            if _max_gex > 0
            else 0
        )
        _oi_low = sum(1 for b in exposures.values() if (_bucket_total_oi(b) is not None and _bucket_total_oi(b) < _max_oi * 0.25)) if _max_oi > 0 else 0
        _both_low = sum(
            1
            for b in exposures.values()
            if (
                (
                    (v := total_gamma_raw_at_strike(b)) is not None
                    and v < _max_gex * 0.20
                    if _max_gex > 0
                    else False
                )
                and (
                    _bucket_total_oi(b) is not None
                    and _bucket_total_oi(b) < _max_oi * 0.25
                    if _max_oi > 0
                    else False
                )
            )
        ) if _max_gex > 0 else 0
        log.debug(f"Gamma void: gex_low={_gex_low}, oi_low={_oi_low}, both_low={_both_low} (need 2+ consecutive)")

    # ── Top GEX/DEX drivers (which strikes are driving the walls) ─────────────
    ms_dict["top_gex_drivers"] = getattr(cs, "top_gex_drivers", []) or []
    ms_dict["top_dex_drivers"] = getattr(cs, "top_dex_drivers", []) or []

    # ── Synthetic forward (parity level) ──────────────────────────────────────
    try:
        from math_exposure import parity_f_minus_spot_from_contracts
        _parity_resid = parity_f_minus_spot_from_contracts(contracts_use, spot=spot_f)
        # RC-301: None means the residual could not be computed from this chain, which is
        # not the same as a residual of zero. It used to arrive as 0.0 and fall under the
        # threshold, so the right thing happened for the wrong reason.
        if _parity_resid is not None and abs(_parity_resid) > PARITY_RESID_MIN:
            ms_dict["kl_synth_fwd"]       = round(spot_f + _parity_resid, 2)
            ms_dict["kl_synth_fwd_resid"] = round(_parity_resid, 4)
            ms_dict["kl_synth_fwd_side"]  = "CALL" if _parity_resid > 0 else "PUT"
            ms_dict["kl_synth_fwd_label"] = "Calls slightly rich" if _parity_resid > 0 else "Puts slightly rich"
        else:
            ms_dict["kl_synth_fwd"] = None
    except Exception:
        ms_dict["kl_synth_fwd"] = None

    # ── Price levels (VWAP / PDH / PDL / PDC / ORB) ───────────────────────────
    # PDH_PRECISION kill (one-faucet-closeout-v1): the LEVEL family travels RAW — the state
    # payload must never round what /api/levels serves unrounded (MEASURED same instant:
    # state pdh 748.89 vs levels PDH 748.895 — one number, two precisions on two surfaces).
    # Rounding is a RENDER concern; consumers format. _fv (2dp) stays for non-level fields.
    from numeric_contract import float_finite_or_none as _raw_level
    ms_dict["vwap"]     = _raw_level(getattr(price_levels, "vwap",     None))
    ms_dict["pdh"]      = _raw_level(getattr(price_levels, "pdh",      None))
    ms_dict["pdl"]      = _raw_level(getattr(price_levels, "pdl",      None))
    ms_dict["pdc"]      = _raw_level(getattr(price_levels, "pdc",      None))
    ms_dict["orb_high"] = _raw_level(getattr(price_levels, "orb_high", None))
    ms_dict["orb_low"]  = _raw_level(getattr(price_levels, "orb_low",  None))
    # F15: the rest of the Phase 2A snapshot family travels RAW on /api/state the
    # same way PDH/VWAP/ORB already do. market_context.fetch_price_levels carries
    # TODAY_POC/VAH/VAL (and PD_POC, overnight, ORB mid, VWAP σ) from the one
    # PriceLevelSnapshot; dropping them here left Chart (/api/levels) as the only
    # live consumer while the console payload could not bind them.
    ms_dict["today_poc"]      = _raw_level(getattr(price_levels, "today_poc",      None))
    ms_dict["today_vah"]      = _raw_level(getattr(price_levels, "today_vah",      None))
    ms_dict["today_val"]      = _raw_level(getattr(price_levels, "today_val",      None))
    ms_dict["pd_poc"]         = _raw_level(getattr(price_levels, "pd_poc",         None))
    ms_dict["pd_vah"]         = _raw_level(getattr(price_levels, "pd_vah",         None))
    ms_dict["pd_val"]         = _raw_level(getattr(price_levels, "pd_val",         None))
    ms_dict["overnight_high"] = _raw_level(getattr(price_levels, "overnight_high", None))
    ms_dict["overnight_low"]  = _raw_level(getattr(price_levels, "overnight_low",  None))
    ms_dict["orb_midpoint"]   = _raw_level(getattr(price_levels, "orb_midpoint",   None))
    ms_dict["vwap_p1"]        = _raw_level(getattr(price_levels, "vwap_p1",        None))
    ms_dict["vwap_m1"]        = _raw_level(getattr(price_levels, "vwap_m1",        None))
    ms_dict["vwap_p2"]        = _raw_level(getattr(price_levels, "vwap_p2",        None))
    ms_dict["vwap_m2"]        = _raw_level(getattr(price_levels, "vwap_m2",        None))

    # ── Expected Move ────────────────────────────────────────────────────────
    ms_dict["em_straddle"]       = _fv(_em_straddle.get("straddle"))
    ms_dict["em_straddle_pts"]   = _fv(_em_straddle.get("em_pts"))
    ms_dict["em_straddle_upper"] = _fv(_em_straddle.get("upper"))
    ms_dict["em_straddle_lower"] = _fv(_em_straddle.get("lower"))
    ms_dict["em_iv_pts"]         = _fv(_em_iv.get("em_pts"))
    ms_dict["em_iv_upper"]       = _fv(_em_iv.get("upper"))
    ms_dict["em_iv_lower"]       = _fv(_em_iv.get("lower"))
    ms_dict["em_progress_pct"]   = _em_progress.get("progress_pct")
    ms_dict["em_breached"]       = _em_progress.get("breached")
    ms_dict["em_direction"]      = _em_progress.get("direction")
    ms_dict["em_severity"]       = _em_progress.get("severity")
    ms_dict["em_move_pts"]       = _em_progress.get("move_pts")

    # ── Volatility signals ────────────────────────────────────────────────────
    ms_dict["iv_skew"]           = _iv_skew.get("skew")
    ms_dict["iv_skew_interp"]    = _iv_skew.get("interpretation")
    ms_dict["realized_vol"]      = _realized_vol  # percent (compute_realized_vol); SignalInput uses decimal via market_state stamp
    ms_dict["atr"]               = _atr
    ms_dict["iv_rank"]           = _iv_rank
    ms_dict["iv_percentile"]     = _iv_percentile

    # ── Section 8 — Predictive Positioning Signals ────────────────────────────
    ms_dict["dpi_raw"]               = _dpi.get("raw")
    ms_dict["dpi_normalized"]        = _dpi.get("normalized")
    # Fail-closed labels: helpers (Action 11.4) emit None when inputs absent; defaults removed
    # so snapshots persist NULL (functional shift landed in 11.4, this pass is structural).
    ms_dict["dpi_direction"]         = _dpi.get("direction")
    ms_dict["dpi_magnitude"]         = _dpi.get("magnitude")
    ms_dict["hedging_flow_raw"]      = _hedging_flow.get("raw")
    ms_dict["hedging_flow_normalized"] = _hedging_flow.get("normalized")
    ms_dict["hedging_flow_direction"]  = _hedging_flow.get("direction")
    ms_dict["gamma_gradient"]        = _gamma_gradient
    ms_dict["breakout_score"]        = _breakout_score.get("normalized")
    ms_dict["breakout_label"]        = _breakout_score.get("label")
    ms_dict["pin_score"]             = _pin_score_val.get("normalized")
    ms_dict["pin_label"]             = _pin_score_val.get("label")
    ms_dict["vol_expansion_score"]   = _vol_expansion.get("normalized")
    ms_dict["vol_expansion_label"]   = _vol_expansion.get("label")
    ms_dict["sweep_score"]           = _sweep_score.get("normalized")
    ms_dict["sweep_label"]           = _sweep_score.get("label")

    # ── Session levels + liquidity sweeps ─────────────────────────────────────
    ms_dict["session_high"]          = getattr(ms, "session_high", None)
    ms_dict["session_low"]           = getattr(ms, "session_low", None)
    ms_dict["last_sweep_type"]       = getattr(ms, "last_sweep_type", None)
    ms_dict["last_sweep_level"]      = getattr(ms, "last_sweep_level", None)
    ms_dict["last_sweep_held"]       = getattr(ms, "last_sweep_held", None)
    ms_dict["n_sweeps_today"]        = getattr(ms, "n_sweeps_today", 0)

    # ── Trade Validation Gate ─────────────────────────────────────────────────
    ms_dict["validation_passed"]     = getattr(ms, "validation_passed", None)
    ms_dict["structure_valid"]       = getattr(ms, "structure_valid", None)
    ms_dict["probability_valid"]     = getattr(ms, "probability_valid", None)
    ms_dict["risk_valid"]            = getattr(ms, "risk_valid", None)
    ms_dict["validation_summary"]    = getattr(ms, "validation_summary", "")

    # ── Call Readiness (from MarketState; computed in call_engine.py) ──────────
    ms_dict["call_readiness"] = {
        "call_state": getattr(ms, "call_state", "WAIT"),
        "forecast_state": getattr(ms, "call_forecast_state", "dormant"),
        "readiness_score": getattr(ms, "call_readiness_score", 0),
        "reasons": list(getattr(ms, "call_readiness_reasons", []) or []),
        "missing_conditions": list(getattr(ms, "call_missing_conditions", []) or []),
        "component_scores": dict(getattr(ms, "call_readiness_component_scores", {}) or {}),
        "wait_blocker": getattr(ms, "call_wait_blocker", None),
    }

    # ── Put Readiness (from MarketState; computed in call_engine.py) ────────────
    ms_dict["put_readiness"] = {
        "call_state": getattr(ms, "put_state", "WAIT"),
        "forecast_state": getattr(ms, "put_forecast_state", "dormant"),
        "readiness_score": getattr(ms, "put_readiness_score", 0),
        "reasons": list(getattr(ms, "put_readiness_reasons", []) or []),
        "missing_conditions": list(getattr(ms, "put_missing_conditions", []) or []),
        "component_scores": dict(getattr(ms, "put_readiness_component_scores", {}) or {}),
    }

    # ── Formal Position Sizing ────────────────────────────────────────────────
    ms_dict["r_units"]               = getattr(ms, "r_units", None)
    ms_dict["execution_mode"]        = getattr(ms, "execution_mode", "NO_TRADE")
    ms_dict["sizing_summary"]        = getattr(ms, "sizing_summary", "")

    # ── Volatility Envelope ───────────────────────────────────────────────────
    ms_dict["vol_env_upper"]         = _vol_envelope.get("upper")
    ms_dict["vol_env_lower"]         = _vol_envelope.get("lower")
    ms_dict["vol_env_width"]         = _vol_envelope.get("width_pts")

    # ── Level Density ─────────────────────────────────────────────────────────
    ms_dict["level_density_count"]   = _level_density.get("count")
    ms_dict["level_density_label"]   = _level_density.get("density_label")
    ms_dict["level_density_names"]   = _level_density.get("level_names")

    # ── Sector Strength (3 groups) ───────────────────────────────────────────
    ms_dict["index_leader"]          = _index_strength.get("leader")
    ms_dict["index_laggard"]         = _index_strength.get("laggard")
    ms_dict["index_breadth"]         = _index_strength.get("breadth")
    ms_dict["index_risk_signal"]     = _index_strength.get("risk_signal")
    ms_dict["index_spread"]          = _index_strength.get("spread")

    ms_dict["spy_holdings_leader"]   = _spy_strength.get("leader")
    ms_dict["spy_holdings_laggard"]  = _spy_strength.get("laggard")
    ms_dict["spy_holdings_breadth"]  = _spy_strength.get("breadth")
    ms_dict["spy_holdings_risk"]     = _spy_strength.get("risk_signal")
    ms_dict["spy_holdings_spread"]   = _spy_strength.get("spread")

    ms_dict["sector_leader"]         = _sector_strength.get("leader")
    ms_dict["sector_laggard"]        = _sector_strength.get("laggard")
    ms_dict["sector_breadth"]        = _sector_strength.get("breadth")
    ms_dict["sector_risk_signal"]    = _sector_strength.get("risk_signal")
    ms_dict["sector_spread"]         = _sector_strength.get("spread")

    # ── IWM Deep Confluence ───────────────────────────────────────────────────
    ms_dict["iwm_risk_regime"]       = _iwm_deep.get("risk_regime")
    ms_dict["iwm_risk_confidence"]   = _iwm_deep.get("risk_regime_confidence")
    ms_dict["spy_iwm_divergence"]    = _iwm_deep.get("spy_iwm_divergence")
    ms_dict["spy_iwm_div_label"]     = _iwm_deep.get("spy_iwm_divergence_label")
    ms_dict["spy_iwm_fragile"]       = _iwm_deep.get("spy_iwm_fragile")
    ms_dict["qqq_iwm_spread"]        = _iwm_deep.get("qqq_iwm_spread")
    ms_dict["rotation_signal"]       = _iwm_deep.get("rotation_signal")
    ms_dict["sector_breadth_quality"] = _iwm_deep.get("sector_breadth_quality")
    ms_dict["iwm_early_warning"]     = _iwm_deep.get("early_warning")
    ms_dict["iwm_early_warning_type"] = _iwm_deep.get("early_warning_type")
    ms_dict["iwm_risk_score"]        = _iwm_deep.get("risk_score")
    ms_dict["iwm_risk_score_label"]  = _iwm_deep.get("risk_score_label")
    ms_dict["iwm_confluence_summary"] = _iwm_deep.get("summary")

    # ── Bond Yields ───────────────────────────────────────────────────────────
    ms_dict["tnx_yield"]             = getattr(mkt_ctx, "tnx_yield", None)
    ms_dict["tnx_chg"]              = getattr(mkt_ctx, "tnx_chg", None)
    ms_dict["bond_signal"]          = getattr(mkt_ctx, "bond_signal", None)

    # ── Order Flow Signals ────────────────────────────────────────────────────
    ms_dict["vol_oi_ratio"]          = _vol_oi_ratio.get("ratio")
    ms_dict["vol_oi_label"]          = _vol_oi_ratio.get("label")
    ms_dict["flow_imbalance"]        = _flow_imb_norm
    # RC-345 / F11: the SOURCE book travels beside the value so a consumer knows whether this
    # flow_imbalance is 'book' (bid/ask size), 'volume' (call/put traded volume) or 'none'.
    # Book and volume imbalance are different economic truths; the numeric value alone cannot
    # tell them apart, and this authority returns book-preferred with a governed volume
    # fallback — the same on the live and backfill paths, so the union is train/serve-consistent.
    ms_dict["flow_imbalance_source"] = _flow_imb_source
    ms_dict["flow_imbalance_label"]  = flow_imbalance_label_from_normalized(_flow_imb_norm)
    ms_dict["smart_money_score"]     = _smart_money.get("score")
    ms_dict["smart_money_direction"] = _smart_money.get("direction")
    ms_dict["smart_money_label"]     = _smart_money.get("label")
    ms_dict["iv_model_spread"]       = _iv_model_spread.get("spread")
    ms_dict["iv_model_spread_label"] = _iv_model_spread.get("label")

    # ── Model Health Dashboard (per-ticker ML stack artifacts from active/) ─────────
    # Status semantics: LIVE = binary + meta + provenance compliant; NON-COMPLIANT = binary+meta, no provenance;
    # BINARY MISSING = meta exists, binary absent; NOT TRAINED = no meta
    _model_health = []
    _models_dir = Path(__file__).parent / "models"
    try:
        from ml_horizon import live_inference_horizon_slug as _live_ml_hz_slug

        _dashboard_ml_hz = _live_ml_hz_slug()
    except Exception:
        _dashboard_ml_hz = "1c"
    _arch_path = _models_dir / "arch_state.json"
    _dashboard_ticker = "SPY"
    if _arch_path.exists():
        try:
            _arch = json.loads(_arch_path.read_text())
            _dashboard_ticker = next((t for t in ("SPY", "QQQ", "IWM") if t in _arch), next(iter(_arch), "SPY"))
        except Exception as e:
            log.debug("dashboard arch_state.json parse failed: %s", e, exc_info=True)
    _active_dir = _models_dir / "active" / _dashboard_ticker

    # Sync missing binaries: if active has meta but not .pt/.pkl, copy from parallel/cascade/flat.
    # Log explicitly; warn when sync is used — indicates promotion pipeline may not have run.
    def _sync_missing_binaries_to_active(ticker: str, active_dir: Path) -> int:
        """Copy missing binaries from candidate dirs. Returns count of files synced."""
        allow_sync = os.environ.get("ED_ALLOW_ACTIVE_SYNC", "0").strip().lower() in ("1", "true", "yes")
        if not allow_sync:
            log.info("Active artifact sync disabled (set ED_ALLOW_ACTIVE_SYNC=1 to enable)")
            return 0
        t = ticker
        synced = 0
        hz = _dashboard_ml_hz
        for model_file, meta_file in [
            (f"lstm_{t}_{hz}.pt", f"lstm_{t}_{hz}_meta.json"),
            (f"transformer_{t}_{hz}.pt", f"transformer_{t}_{hz}_meta.json"),
            (f"xgb_{t}_{hz}.pkl", f"xgb_{t}_{hz}_meta.json"),
        ]:
            dest = active_dir / model_file
            meta = active_dir / meta_file
            if meta.exists() and not dest.exists():
                for src_dir in [
                    _models_dir / "parallel" / t,
                    _models_dir / "cascade" / t,
                    _models_dir,  # flat train_all output
                ]:
                    src = src_dir / model_file
                    if src.exists():
                        try:
                            shutil.copy2(src, dest)
                            synced += 1
                            log.info("Synced %s to active/%s/%s (from %s)", model_file, t, model_file, src_dir.name)
                            break
                        except Exception as e:
                            log.warning("Sync %s failed: %s", model_file, e)
        if synced > 0:
            log.warning(
                "Model sync used for %s (%d file(s)) — promotion pipeline may not have run. "
                "Run: python ml_scheduler.py --run-now",
                ticker, synced,
            )
        return synced
    try:
        _sync_count = _sync_missing_binaries_to_active(_dashboard_ticker, _active_dir)
    except Exception as e:
        log.debug("sync_missing_binaries: %s", e)
        _sync_count = 0

    # Governance-aware status from compliance check
    try:
        from verify_active_models import check_artifact_compliance
        _comp = check_artifact_compliance(_dashboard_ticker)
    except Exception:
        _comp = {"compliant": False, "artifacts": {}, "issues": None}
    _artifacts = _comp.get("artifacts", {})

    def _model_status_from_artifact(name: str, display_name: str, meta_path: Path, edge_key: str, version_key: str = "version") -> dict:
        art = _artifacts.get(name, {"exists": False, "has_provenance": False, "issues": []})
        meta_exists = meta_path.exists()
        if not meta_exists:
            return {"model": display_name, "status": "NOT TRAINED", "status_reason": "No metadata — model never promoted", "edge": None, "version": "—", "ticker": _dashboard_ticker}
        if not art.get("exists", False):
            return {"model": display_name, "status": "BINARY MISSING", "status_reason": "Metadata present but model file missing — run training/promotion", "edge": None, "version": "—", "ticker": _dashboard_ticker}
        if not art.get("has_provenance", False):
            issues = "; ".join(art.get("issues", [])) or "Metadata lacks provenance"
            return {"model": display_name, "status": "NON-COMPLIANT", "status_reason": issues, "edge": None, "version": "—", "ticker": _dashboard_ticker}
        # RC-377 (Cursor drift-audit F1): this display path parses the SAME governed
        # meta the serve path refuses when tampered — without the Item-4 verify here,
        # the weakest parser of the artifact defines the real integrity boundary.
        from ml_predict import _verify_governed_artifact as _item4_verify
        if _item4_verify(_active_dir, _dashboard_ticker, _dashboard_ml_hz, f"{name}_meta", meta_path.name) is None:
            return {"model": display_name, "status": "INTEGRITY FAILED",
                    "status_reason": "Metadata failed bundle integrity verification — not parsed",
                    "edge": None, "version": "—", "ticker": _dashboard_ticker}
        try:
            _m = json.loads(meta_path.read_text())
            # RC-285: no `, 0` default. A model whose metadata omits the metric has not
            # scored zero edge, it has not been scored — and my earlier annotation defending
            # 0 as "this endpoint's existing missing convention" described the defect rather
            # than justifying it. `status` is no longer load-bearing for reading `edge`.
            # RC-291: NO val_accuracy fallback. RC-285 removed the `, 0` default and then
            # substituted a DIFFERENT METRIC — accuracy is not edge over a baseline, so a
            # coin-flip model with val_accuracy 0.55 published `edge: 55.0` and the UI counts
            # every LIVE model toward "N approved". Substituting a different measurement is
            # worse than reporting none, because none is legible and a wrong one is not.
            from numeric_contract import float_finite_or_none as _fin_edge
            # RC-364/RC-291 port: edge comes ONLY from the requested edge metric — never a
            # val_accuracy translation (accuracy is not edge over a baseline; a coin-flip
            # model with val_accuracy 0.55 must not publish edge 55.0 and read as approved).
            # val_accuracy is stamped under its OWN name for any consumer that wants it.
            edge = _fin_edge(_m.get(edge_key))
            val_accuracy = _fin_edge(_m.get("val_accuracy"))
            version = _m.get(version_key, _m.get("model_version", "—"))
        except Exception:
            edge, version, val_accuracy = None, "—", None
        # RC-293: compliant with NO edge measurement is not APPROVED. RC-291 made `edge`
        # an honest None and left status LIVE, and static/index.html counts every LIVE model
        # toward "N approved" — so a model nobody scored still read as approved, which was
        # the substance of the finding rather than the field's type.
        if edge is None:
            return {"model": display_name, "status": "UNSCORED",
                    "status_reason": "Binary + metadata + provenance compliant, but no edge "
                                     "metric recorded — not scored, so not approved",
                    "edge": None, "val_accuracy": val_accuracy, "metric_name": edge_key,
                    "version": version or "—", "ticker": _dashboard_ticker}
        return {"model": display_name, "status": "LIVE", "status_reason": "Binary + metadata + provenance compliant", "edge": edge, "val_accuracy": val_accuracy, "metric_name": edge_key, "version": version or "—", "ticker": _dashboard_ticker}

    _xgb_meta = _active_dir / f"xgb_{_dashboard_ticker}_{_dashboard_ml_hz}_meta.json"
    _lstm_meta = _active_dir / f"lstm_{_dashboard_ticker}_{_dashboard_ml_hz}_meta.json"
    _tf_meta = _active_dir / f"transformer_{_dashboard_ticker}_{_dashboard_ml_hz}_meta.json"
    try:
        _model_health.append(_model_status_from_artifact("xgb", "XGBoost", _xgb_meta, "edge_pp", "model_version"))
    except Exception:
        _model_health.append({"model": "XGBoost", "status": "ERROR", "status_reason": "Check failed", "edge": None, "version": "—", "ticker": _dashboard_ticker})
    try:
        _model_health.append(_model_status_from_artifact("transformer", "Transformer", _tf_meta, "edge_pp"))
    except Exception:
        _model_health.append({"model": "Transformer", "status": "ERROR", "status_reason": "Check failed", "edge": None, "version": "—", "ticker": _dashboard_ticker})
    try:
        # RC-364/RC-291 port: request edge_pp for LSTM like every other model — absent
        # edge_pp → edge None → UNSCORED, never val_accuracy masquerading as edge.
        _model_health.append(_model_status_from_artifact("lstm", "LSTM", _lstm_meta, "edge_pp", "model_type"))
    except Exception:
        _model_health.append({"model": "LSTM", "status": "ERROR", "status_reason": "Check failed", "edge": None, "version": "—", "ticker": _dashboard_ticker})

    # MC + Rules + Regime + Fusion (always live)
    for m in [{"model": "Monte Carlo", "version": "10K paths"}, {"model": "Regime Engine", "version": "8 families"}, {"model": "Bayesian Fusion", "version": "6 posteriors"}]:
        _model_health.append({**m, "status": "LIVE", "status_reason": "Always active", "edge": None, "ticker": _dashboard_ticker})

    ms_dict["model_health"] = _model_health
    ms_dict["n_models_live"] = sum(1 for m in _model_health if m["status"] == "LIVE")
    ms_dict["model_sync_used"] = _sync_count > 0  # True when binaries were recovered via sync (publication problem)
    ms_dict["active_compliant"] = _comp.get("compliant")
    ms_dict["active_compliance_issues"] = _comp.get("issues")

    # ── Confluence (market context) ────────────────────────────────────────────
    ms_dict["spy_chg_pct"]    = getattr(mkt_ctx, "spy_chg_pct",  None)
    ms_dict["qqq_chg_pct"]    = getattr(mkt_ctx, "qqq_chg_pct",  None)
    ms_dict["iwm_chg_pct"]    = getattr(mkt_ctx, "iwm_chg_pct",  None)
    ms_dict["spy_last"]       = _fv(getattr(mkt_ctx, "spy_last",  None))
    ms_dict["qqq_last"]       = _fv(getattr(mkt_ctx, "qqq_last",  None))
    ms_dict["iwm_last"]       = _fv(getattr(mkt_ctx, "iwm_last",  None))
    # CME index futures (optional — full contract symbols via ED_FUTURES_ES / NQ / RTY)
    ms_dict["fut_es_symbol"]   = getattr(mkt_ctx, "fut_es_symbol", "") or ""
    ms_dict["fut_es_last"]     = _fv(getattr(mkt_ctx, "fut_es_last", None))
    ms_dict["fut_es_chg_pct"]  = getattr(mkt_ctx, "fut_es_chg_pct", None)
    ms_dict["fut_nq_symbol"]   = getattr(mkt_ctx, "fut_nq_symbol", "") or ""
    ms_dict["fut_nq_last"]     = _fv(getattr(mkt_ctx, "fut_nq_last", None))
    ms_dict["fut_nq_chg_pct"]  = getattr(mkt_ctx, "fut_nq_chg_pct", None)
    ms_dict["fut_rty_symbol"]  = getattr(mkt_ctx, "fut_rty_symbol", "") or ""
    ms_dict["fut_rty_last"]    = _fv(getattr(mkt_ctx, "fut_rty_last", None))
    ms_dict["fut_rty_chg_pct"] = getattr(mkt_ctx, "fut_rty_chg_pct", None)
    ms_dict["vix_implication"] = getattr(mkt_ctx, "vix_implication", "")

    # RC-365/F39: absent weighted_push stays None (not 0). Dots None when the push is absent.
    ms_dict.update(stamp_confluence_display_fields(mkt_ctx))

    # Constituent dots
    _constituents = []
    for cq in (getattr(mkt_ctx, "constituents", None) or []):
        _constituents.append({
            "symbol":       cq.symbol,
            "chg_pct":      cq.chg_pct,
            "weight":       cq.weight,
            "contribution": cq.contribution,
            "dot_color":    cq.dot_color,
        })
    ms_dict["constituents"] = _constituents

    _qqq_c = []
    for cq in (getattr(mkt_ctx, "qqq_constituents", None) or []):
        _qqq_c.append({
            "symbol":       cq.symbol,
            "chg_pct":      cq.chg_pct,
            "weight":       cq.weight,
            "contribution": cq.contribution,
            "dot_color":    cq.dot_color,
        })
    ms_dict["qqq_constituents"] = _qqq_c

    _iwm_h = []
    for cq in (getattr(mkt_ctx, "iwm_holdings", None) or []):
        _iwm_h.append({
            "symbol":       cq.symbol,
            "chg_pct":      cq.chg_pct,
            "weight":       cq.weight,
            "contribution": cq.contribution,
            "dot_color":    cq.dot_color,
        })
    ms_dict["iwm_holdings_constituents"] = _iwm_h

    # IWM sector proxies
    _iwm_sectors = []
    for sq in (getattr(mkt_ctx, "iwm_sectors", None) or []):
        _iwm_sectors.append({
            "symbol":       sq.symbol,
            "label":        getattr(sq, "label", ""),
            "chg_pct":      sq.chg_pct,
            "weight":       sq.weight,
            "contribution": sq.contribution,
            "dot_color":    sq.dot_color,
        })
    ms_dict["iwm_sectors"] = _iwm_sectors

    # ── Logger stats for UI display ───────────────────────────────────────────
    with _logger_lock:
        ms_dict["logger_tickers"] = list(_logger_tickers)
        ms_dict["logger_running"] = _logger_running

    # ── DB snapshot counts (for counter display) ──────────────────────────────
    ms_dict["total_snapshots"]  = db_counts.get("total", 0)
    ms_dict["filled_snapshots"] = db_counts.get("filled", 0)

    # ── Accuracy (from cache — never blocks the main response) ────────────────
    # Primary block is RTH-scoped with baseline edge (operator decision
    # 2026-07-06: all-hours accuracy flattered tradeable-session performance —
    # SPY 5c 40.1%% all-hours vs 34.5%% RTH against a 38.1%% RTH baseline).
    # All-hours rides as a separate audit-context block; a missing RTH scope
    # fails closed to None here rather than borrowing the all-hours numbers.
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — persisted-snapshot prediction-accuracy
    #   scoping/provenance only; no market field read, derivation, emission, or
    #   actionability logic changed; model outputs untouched.
    # Derived-field disposition: none required.
    # All consumers checked: yes — payload block, /api/accuracy, history writer,
    #   ops.html panel all updated in this change set.
    # SCHWAB_CSV_CHECKED
    _acc = _accuracy_cache.get(ticker, {}).get("results")
    if _acc:
        ms_dict["accuracy"] = {
            hz: {
                "accuracy": v.get("accuracy"),
                "total": v.get("total"),
                "baseline_pct": v.get("baseline_pct"),
                "edge_vs_baseline_pp": v.get("edge_vs_baseline_pp"),
                "scope": v.get("scope"),
            }
            for hz, v in _acc.items() if v.get("accuracy") is not None
        }
        ms_dict["accuracy_scope"] = "rth_0930_1600_et"
    else:
        ms_dict["accuracy"] = None
        ms_dict["accuracy_scope"] = None
    _acc_ah = _accuracy_cache.get(ticker, {}).get("all_hours")
    if _acc_ah:
        ms_dict["accuracy_all_hours"] = {
            hz: {
                "accuracy": v.get("accuracy"),
                "total": v.get("total"),
                "baseline_pct": v.get("baseline_pct"),
                "edge_vs_baseline_pp": v.get("edge_vs_baseline_pp"),
                "scope": v.get("scope"),
            }
            for hz, v in _acc_ah.items() if v.get("accuracy") is not None
        }
    else:
        ms_dict["accuracy_all_hours"] = None

    # ── Fusion-calibration provenance (ticker-agnostic lock, 2026-07-06) ──────
    # The temperature artifact is host-local (models/** gitignored): a host that
    # never ran `python -m calibration.fusion_temperature` silently serves RAW
    # fusion probabilities (fail-closed identity). This block makes that state
    # observable per payload — artifact_loaded=false IS the raw-serving signal.
    # Horizon-keyed only; no per-ticker calibration surface exists.
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — calibration-artifact load-state
    #   diagnostic; no market field read, derivation, emission, or
    #   actionability logic changed.
    # Derived-field disposition: none required.
    # All consumers checked: yes — new additive diagnostic key; probability
    #   values themselves unchanged by this block.
    # SCHWAB_CSV_CHECKED
    try:
        from multi_horizon_ml_bundle import fusion_calibration_status

        ms_dict["fusion_calibration_v1"] = fusion_calibration_status()
    except Exception as _fcs_e:
        log.debug("fusion_calibration_status attach failed: %s", _fcs_e)
        ms_dict["fusion_calibration_v1"] = None

    _events = list(getattr(ms, "stack_integrity_events", None) or [])
    if _events:
        try:
            from features.stack_integrity_v1 import finalize_stack_integrity_v1

            ms_dict["stack_integrity_events"] = _events
            ms_dict["stack_integrity_v1"] = finalize_stack_integrity_v1(_events)
        except Exception as e:
            log.warning(
                "finalize_stack_integrity_v1 failed ticker=%s: %s",
                ticker,
                e,
                exc_info=True,
            )
    _attach_stack_runtime_and_governance(ms_dict, ticker=ticker)
    _stage_marks.append(("stack_runtime_governance_attach", time.perf_counter()))
    if ms_dict.get("signals_engine_failed"):
        sr = ms_dict.get("stack_runtime")
        if isinstance(sr, dict):
            sr["signals_engine_failed"] = True
    _apply_trader_horizon_contract(ms_dict)
    from trade_impacting_gate import resolve_fetch_state_decision_route

    _decision_route = resolve_fetch_state_decision_route(update_source)
    # execution_identity_v1: one cycle = one decision_id = one identity. Seed
    # the anchored pair so stamping binds the SAME decision the snapshot carries.
    _xid_pair = getattr(ms, "_execution_identity_pair", None)
    if _xid_pair:
        ms_dict["decision_id"] = _xid_pair[0]
        ms_dict["execution_identity_sha256"] = _xid_pair[1]
    _finalize_production_decision(ms_dict, _decision_route)
    if (
        _xid_pair
        and ms_dict.get("decision_id") == _xid_pair[0]
        and not ms_dict.get("decision_generation_skipped")
        # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: only a write that
        # actually landed marks the "decision" surface — a refused/skipped
        # persist leaves the ledger honestly OPEN.
        and ms_dict.get("_decision_persist_landed")
    ):
        try:
            from execution_identity import mark_surface_landed as _xid_mark_dec

            with get_db()._connect() as _xconn3:
                _xid_mark_dec(_xconn3, _xid_pair[0], "decision")
        except Exception as _x_exc2:
            log.error("execution identity decision-surface landing failed: %s", _x_exc2)
    _stage_marks.append(("payload_assembly_model_health_finalize", time.perf_counter()))
    _t_pipeline_end_mono = time.monotonic()
    ms_dict["_server_build_ts"] = time.time()
    ms_dict["_pipeline_ms"] = round((_t_pipeline_end_mono - _fetch_start_mono) * 1000)
    ms_dict["_chain_ms"] = round((_t_after_chain_mono - _fetch_start_mono) * 1000)
    ms_dict["_quote_ms"] = round((_t_after_quote_mono - _t_after_chain_mono) * 1000)
    ms_dict["_compute_ms"] = round((_t_pipeline_end_mono - _t_after_quote_mono) * 1000)
    # Lane-3 diagnostic: stage split of _compute_ms (+ chain/quote copies for one-stop reads).
    _stage_ms: dict[str, float] = {}
    _stage_prev_pc = _stage_t0
    for _stage_name, _stage_pc in _stage_marks:
        _stage_ms[_stage_name] = round((_stage_pc - _stage_prev_pc) * 1000.0, 1)
        _stage_prev_pc = _stage_pc
    # Chain gate: schwab_chain_ms is the PURE Schwab fetch (helper-measured);
    # gate wait is split out; _chain_ms keeps its wall-clock-to-chain meaning.
    _stage_ms["schwab_chain_ms"] = (
        round(_chain_fetch_pure_sec * 1000.0, 1)
        if _chain_fetch_pure_sec is not None
        else float(ms_dict["_chain_ms"])
    )
    _stage_ms["chain_gate_wait_ms"] = round(_chain_gate_wait_sec * 1000.0, 1)
    _stage_ms["schwab_quote_ms"] = float(ms_dict["_quote_ms"])
    # UI_05 tail attribution: consecutive deltas across the _chain_ms window
    # (preamble | mkt_ctx | leaf submit->result wall | contracts parse).
    _cw_prev_mono = _fetch_start_mono
    for _cw_name, _cw_mono in _chain_window_marks:
        _stage_ms[_cw_name] = round((_cw_mono - _cw_prev_mono) * 1000.0, 1)
        _cw_prev_mono = _cw_mono
    ms_dict["chain_gate_wait_sec"] = _chain_gate_wait_sec
    ms_dict["_compute_breakdown"] = dict(_stage_ms)
    log.info(
        f"_fetch_state: {ticker} pipeline_ms={ms_dict['_pipeline_ms']} "
        f"quote_ms={ms_dict['_quote_ms']} chain_ms={ms_dict['_chain_ms']} compute_ms={ms_dict['_compute_ms']} expiry={expiry}"
    )
    log.info("_fetch_state_breakdown: %s %s", ticker, json.dumps(_stage_ms, sort_keys=True))
    if update_source is not None:
        ms_dict["_update_source"] = update_source

    attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)
    attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker=ticker)
    ms_dict["v2_decision"] = _v2_decision_for_response or build_module_a_a1_decision(ms_dict)
    _lmp.merge_into_state(ms_dict, ticker)

    _prev_ent = _state_cache.get(_cache_key) or {}
    _gen_ts = time.time()
    _next_ver = int(_prev_ent.get("analytics_version", 0)) + 1
    if not _prev_ent:
        # Version restarts at 1 — a cold entry write (fresh key or prior eviction).
        _analytics_cache_observability["cold_entry_writes"] += 1

    # ── Pass 4: level cross detection ─────────────────────────────────────────
    # Writer for level_crosses, consumer at /api/level_crosses + Decision
    # Command "third test of ceiling" pattern (db.count_level_tests). Debounced
    # by (ticker, level_name, direction) per EdDB.LEVEL_CROSS_DEBOUNCE_S.
    if _ed_db is not None:
        try:
            from live_decision_bundle import _key_levels_from_ms_dict as _kl_for_cross
            _prev_spot_for_cross = _prev_ent.get("spot_f")
            _levels_for_cross = _kl_for_cross(ms_dict)
            if _prev_spot_for_cross is not None and spot_f is not None and _levels_for_cross:
                _ts_et_str = _eastern_now().strftime("%Y-%m-%d %H:%M:%S ET")
                _crosses = _ed_db.detect_and_log_level_crosses(
                    ticker=ticker,
                    prev_spot=float(_prev_spot_for_cross),
                    cur_spot=float(spot_f),
                    levels=_levels_for_cross,
                    ts_utc=_gen_ts,
                    ts_et=_ts_et_str,
                    timeframe="1m",
                    zone_before=(_prev_ent.get("ms_dict") or {}).get("zone"),
                    zone_after=ms_dict.get("zone"),
                )
                for _xc in _crosses:
                    log.info(
                        "level_cross ticker=%s level=%s value=%.2f direction=%s spot=%.2f",
                        ticker,
                        _xc["level_name"],
                        _xc["level_value"],
                        _xc["direction"],
                        _xc["spot_at_cross"],
                    )
        except Exception as _xce:
            log.debug("level cross detection failed ticker=%s: %s", ticker, _xce)

    _state_cache[_cache_key] = {
        "ts": _gen_ts,
        "generated_at": _gen_ts,
        "analytics_version": _next_ver,
        "ms_dict": ms_dict, "pcr_val": pcr_val, "spot_f": spot_f,
        # VOL_INPUT_CONTRACT 1.0.0 single-source: publish the context level —
        # this is the value the next cycle's market_iv_change diffs against.
        "vix": vol_ctx.market_iv_level,
        "price_levels": _prev_ent.get("price_levels"),
        "pl_date":      _prev_ent.get("pl_date", ""),
        "pl_generation": _prev_ent.get("pl_generation"),
        "pl_mono":      _prev_ent.get("pl_mono"),
    }
    _evict_old_expiry_entries(ticker, selected_exp)
    _attach_db_contention_operator_surface(ms_dict)
    from market_state import attach_operator_visible_field_lineage

    attach_operator_visible_field_lineage(ms_dict)
    # TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 — post-pipeline tail (merge_into_state,
    # level-cross detection, cache write, eviction, lineage) runs AFTER _pipeline_ms
    # stops; time it separately so cycle totals attribute fully. Passive observation.
    ms_dict["_finalize_tail_ms"] = round((time.monotonic() - _t_pipeline_end_mono) * 1000)
    ms_dict["analytics_cache_observability_v1"] = dict(_analytics_cache_observability)
    # EXEC-03 POST_PUBLISH_LAST_ERROR_OBSERVABILITY_V1 — failure cause detail for
    # the counters above; recorded by the tail, so it reflects failures up to the
    # PREVIOUS cycle (publish-before-persistence ordering).
    ms_dict["post_publish_last_errors_v1"] = {
        k: dict(v) for k, v in _post_publish_last_errors.items()
    }
    # FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1: persistence/telemetry runs AFTER the
    # generated_at-stamping publish above, same worker, same cycle; the SERVED
    # decision object (ms_dict["v2_decision"]) is the logged object.
    _post_publish_persistence_tail(_next_ver, ms_dict["v2_decision"])
    return ms_dict


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────
from contextlib import asynccontextmanager


@asynccontextmanager
async def _app_lifespan(app):
    """Startup and shutdown: logger, order flow, SSE, ML scheduler."""
    # ── Startup ─────────────────────────────────────────────────────────────
    # Installed FIRST: until these exist, Ctrl+C depends on uvicorn's graceful path
    # completing, and that path joins background workers which may be blocked.
    _install_signal_handlers()
    _startup_analytics_executor()
    # Schwab auth diagnostics (helps debug link vs manual launch)
    _log_schwab_startup_diagnostics()

    # Lightweight auth validation — don't wait for first /api/state to discover issues
    try:
        _inv_startup = inspect_token_file(cfg.token_path)
        log.info(
            "Schwab startup auth: token_path=%r exists=%s refreshable=%s scope=%r",
            cfg.token_path,
            _inv_startup.file_exists,
            auth_is_refreshable(_inv_startup),
            _inv_startup.scope_value,
        )
        log.info(
            "Schwab token timing: seconds_to_expiry=%s expired=%s expiring_soon=%s",
            _inv_startup.seconds_to_expiry,
            _inv_startup.is_expired,
            _inv_startup.is_expiring_soon,
        )
        if (
            _inv_startup.file_exists
            and _inv_startup.json_valid
            and _inv_startup.has_token_object
            and not auth_is_refreshable(_inv_startup)
        ):
            log.error(
                "Schwab startup: token exists but NOT refreshable (no refresh_token). "
                "Remediation: python reauth_schwab.py --manual",
            )
        state = build_client_from_token(
            api_key=cfg.api_key,
            app_secret=cfg.app_secret,
            token_path=cfg.token_path,
        )
        if not state.ok or state.client is None:
            log.error(
                "Schwab auth invalid at startup: %s — Remediation: run python reauth_schwab.py",
                state.message,
            )
        else:
            r_near_expiry = None
            if _inv_startup.is_expiring_soon:
                log.info("Token near expiry — performing refresh validation")
                try:
                    r_near_expiry = state.client.get_quote("SPY")
                    if not r_near_expiry or getattr(r_near_expiry, "status_code", 0) != 200:
                        log.warning("Refresh validation failed: bad response")
                except Exception as e:
                    log.error("Refresh validation failed: %s", e)
                    r_near_expiry = None
            # Validate token works with a minimal call (reuse SPY quote if near-expiry already fetched)
            try:
                r = r_near_expiry if r_near_expiry is not None else state.client.get_quote("SPY")
                if not r or getattr(r, "status_code", 0) != 200:
                    log.warning(
                        "Schwab token validation failed (SPY quote returned %s). "
                        "Token may be expired. Remediation: python reauth_schwab.py",
                        getattr(r, "status_code", "None"),
                    )
                else:
                    log.info("Schwab auth validated at startup")
            except Exception as ve:
                from schwab_client import _is_token_error
                if _is_token_error(ve):
                    log.error(
                        "Schwab token invalid at startup: %s — Remediation: python reauth_schwab.py",
                        ve,
                    )
                else:
                    log.warning("Schwab startup validation: %s", ve)
    except Exception as e:
        log.warning("Schwab auth check: %s", e)

    try:
        from release_object import initialize_release_at_startup

        initialize_release_at_startup()
    except Exception as rel_e:
        log.error("release_object startup failed: %s — production decisions will not stamp release_id", rel_e)

    # Canonical 1m: snapshot inserts MUST use timeframe='1m'. Fail loudly if misconfigured.
    if CANONICAL_TIMEFRAME != "1m":
        log.error("CANONICAL_TIMEFRAME=%r != '1m' — snapshot inserts will use wrong timeframe!", CANONICAL_TIMEFRAME)
        raise RuntimeError(f"timeframe_config.CANONICAL_TIMEFRAME must be '1m', got {CANONICAL_TIMEFRAME!r}")
    log.info("Canonical timeframe: 1m (snapshot inserts enforced in db.insert_snapshot)")
    # DB-WRITE-PATH-FIXES (d): start_logger() -> _hydrate_logger_tickers_from_db() performs the
    # DB-backed logging-universe load here in the lifespan (kept off the module-import path).
    start_logger()
    log.info(f"Background logger started — core tickers: {CORE_TICKERS}")

    # Terrain collection — its OWN loop, never gated on operator mode. The background
    # logger runs the full model stack and therefore had to be throttled while a viewer
    # is connected; terrain is ~5 ms of math plus one chain call per ticker, so it keeps
    # every ticker's levels fresh regardless of what the model stack is doing.
    start_terrain_loop()
    # RC-69: bar collection is its own always-on service — never a side-effect of rendering.
    start_bars_loop()
    start_terrain_prewarm()
    log.info("Terrain loop started — %.0fs cadence, %d workers, per-ticker strike width "
             "derived from measured geometry (%d..%d, cold start %d)",
             TERRAIN_REFRESH_SEC, TERRAIN_WORKERS, TERRAIN_STRIKE_COUNT_MIN,
             TERRAIN_STRIKE_COUNT_MAX, TERRAIN_STRIKE_COUNT_COLD_START)

    # ML scheduler is OPT-IN for the operator console (2026-07-03): the unconditional
    # nightly 16:15 ET run trained/promoted models from whatever console instance was
    # open — an ungoverned writer into models/active (operator ruling: BLESS_RUN=NO,
    # MODELS_ACTIVE_AS_OUTPUT_LANE=NOT_APPROVED), it spawned multiprocess workers that
    # outlive console crashes, and it contended with the live DB during operator use.
    # Training hosts opt in explicitly; `python ml_scheduler.py --run-now` is unchanged.
    #
    # SCHWAB_CSV_CHECKED — console usability slice (scheduler gate + incremental
    #   normalized materialize):
    # Schwab CSV authority checked: yes
    # CSV row(s): NO_SCHWAB_EQUIVALENT — process scheduling and DB write batching only;
    #   no market field read, derivation, or emission changed.
    if os.environ.get("ED_ENABLE_BACKGROUND_SCHEDULER", "0").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from ml_scheduler import start_background_scheduler
            start_background_scheduler()
            log.info("ML scheduler started — next run at 16:15 ET (ED_ENABLE_BACKGROUND_SCHEDULER on)")
        except Exception as e:
            log.warning(f"ML scheduler not started: {e}")
    else:
        log.info(
            "ML scheduler NOT started — operator console default "
            "(set ED_ENABLE_BACKGROUND_SCHEDULER=1 on a training host to opt in)"
        )

    # Order flow streaming (nasdaq_book, nyse_book, level_one_equity)
    try:
        client = get_client()
        if client:
            account_id = None
            try:
                an = client.get_account_numbers()
                status = getattr(an, "status_code", 0) if an else 0
                if status == 200:
                    data = an.json() if hasattr(an, "json") and callable(an.json) else []
                    if isinstance(data, list) and data:
                        account_id = data[0].get("accountNumber") or data[0].get("hashValue")
                    if account_id and str(account_id).isdigit():
                        account_id = int(account_id)
                elif status == 401:
                    resp_text = getattr(an, "text", str(an)) if an else ""
                    log.error(f"Accounts 401 — response: {resp_text}")
            except Exception as ae:
                log.debug(f"Account numbers for streaming: {ae}")
            if account_id:
                from order_flow_streaming import start_order_flow_stream

                # LIVE_OPERATOR_MODE_RESET_V1 Step 2 — single Tier C owner: the
                # tick-coherent recompute callback (_on_tick_broadcast_sync) is no
                # longer registered; _sse_background_loop owns viewed-key cadence.
                # The quote lane (live_market_plane → live_quote SSE) still updates
                # per tick via record_from_level_one_equity.
                start_order_flow_stream(client, account_id, DEFAULT_TICKER)
            else:
                log.info("Order flow streaming: no account_id, running REST-only")
    except ImportError as ie:
        log.debug(f"Order flow streaming not started: {ie}")
    except Exception as e:
        log.warning(f"Order flow streaming startup: {e}")

    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
    asyncio.create_task(_sse_background_loop())
    asyncio.create_task(_sse_live_quote_loop())
    asyncio.create_task(_l1_light_sse_dispatch_loop())
    log.info("SSE background loop + live quote SSE loop + L1 light SSE dispatch started")

    _schedule_startup_analytics_warm()

    _session_open_anchor_warm_stop.clear()
    threading.Thread(
        target=_session_open_anchor_warm_loop,
        name="ed_session_open_anchor_warm",
        daemon=True,
    ).start()
    log.info("session-open anchor warm loop started (poll=%ss)", SESSION_OPEN_ANCHOR_WARM_POLL_SEC)

    _anchor_quote_lane_refresh_stop.clear()
    threading.Thread(
        target=_anchor_quote_lane_refresh_loop,
        name="ed_anchor_quote_lane_refresh",
        daemon=True,
    ).start()
    log.info(
        "anchor quote lane refresh loop started (poll=%ss max_age=%ss)",
        ANCHOR_QUOTE_LANE_REFRESH_POLL_SEC,
        ANCHOR_QUOTE_LANE_MAX_AGE_SEC,
    )

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    # BOUNDED BY CONSTRUCTION. Everything below joins background workers
    # (`shutdown(wait=True)`, `join_timeout=40`), and `cancel_futures=True` only drops
    # QUEUED work -- it cannot interrupt a RUNNING one. A single worker inside a slow
    # Schwab call or a long query therefore blocked the whole chain, so Ctrl+C was
    # accepted and the console never exited (operator, 2026-07-20). Python then makes it
    # worse: concurrent.futures registers an atexit hook that joins every executor's
    # non-daemon workers, so even abandoning the lifespan would not free the interpreter.
    # The watchdog guarantees the process dies whether or not the joins below return.
    _arm_shutdown_watchdog()
    _session_open_anchor_warm_stop.set()
    _anchor_quote_lane_refresh_stop.set()
    _shutdown_analytics_executor(wait=True)
    # Schwab stream thread + websocket: must close before loop/thread teardown
    # (avoids pending websockets tasks destroyed with the event loop).
    try:
        from order_flow_streaming import stop_order_flow_stream

        stop_order_flow_stream(join_timeout=40.0)
    except Exception as e:
        log.warning("Order flow streaming shutdown: %s", e)

    stop_terrain_loop()
    stop_bars_loop()
    stop_logger()
    # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: leaf pool shuts down AFTER
    # the analytics executor above — no new leaf submits can arrive first (the
    # _analytics_bg_shutdown branch also forces inline leaf fetches).
    global _recompute_leaf_executor
    if _recompute_leaf_executor is not None:
        _recompute_leaf_executor.shutdown(wait=True, cancel_futures=True)
        _recompute_leaf_executor = None
    # UI_05_OPERATOR_PRIORITY_ADMISSION_V1: priority lane tears down with the
    # same discipline (after the analytics executor; _analytics_bg_shutdown
    # already rejects new submits at the wrapper).
    global _operator_priority_executor
    if _operator_priority_executor is not None:
        _operator_priority_executor.shutdown(wait=True, cancel_futures=True)
        _operator_priority_executor = None
    global _priority_leaf_executor
    if _priority_leaf_executor is not None:
        _priority_leaf_executor.shutdown(wait=True, cancel_futures=True)
        _priority_leaf_executor = None
    global _mkt_ctx_refresh_executor
    if _mkt_ctx_refresh_executor is not None:
        _mkt_ctx_refresh_executor.shutdown(wait=True, cancel_futures=True)
        _mkt_ctx_refresh_executor = None
    global _quote_hot_executor, _route_offload_executor, _fast_quote_executor, _db_fill_outcomes_executor
    if _quote_hot_executor is not None:
        _quote_hot_executor.shutdown(wait=True)
        _quote_hot_executor = None
    if _route_offload_executor is not None:
        _route_offload_executor.shutdown(wait=True)
        _route_offload_executor = None
    _fast_quote_executor = None
    if _db_fill_outcomes_executor is not None:
        _db_fill_outcomes_executor.shutdown(wait=True)
        _db_fill_outcomes_executor = None


app = FastAPI(title="Ed Console API", version="1.0", lifespan=_app_lifespan)

# F09: serve the JS projection from time_et on every request. Registered BEFORE
# the StaticFiles mount so a committed or leftover disk blob cannot become a
# second clock authority (Starlette matches routes in order).
app.add_api_route(
    "/static/rth_clock_authority.js",
    lambda: Response(
        _time_et.rth_clock_js_source(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    ),
    methods=["GET"],
    include_in_schema=False,
)

static_dir = Path(APP_DIR) / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    html_path = static_dir / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>static/index.html not found</h1>", status_code=404)
    # Avoid stale shell JS after edits (browser disk cache of "/" was masking localForce→force fix).
    return HTMLResponse(
        content=html_path.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers request this automatically; without a route they log 404 (harmless but noisy)."""
    return Response(status_code=204)


@app.get("/guide/data-stewardship", response_class=HTMLResponse)
def guide_data_stewardship():
    """Serve DATA_STEWARDSHIP.md in the browser (king / jewels / guards + runbook)."""
    md_path = Path(APP_DIR) / "DATA_STEWARDSHIP.md"
    if not md_path.exists():
        return HTMLResponse(
            "<p>DATA_STEWARDSHIP.md not found in app directory.</p>",
            status_code=404,
        )
    raw = md_path.read_text(encoding="utf-8")
    body = html.escape(raw)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Data stewardship &amp; ops — Ed Console</title>
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0c0f; color: #e5e7eb;
            margin: 0; padding: 24px; line-height: 1.55; font-size: 14px; }}
    .wrap {{ max-width: 52rem; margin: 0 auto; }}
    a {{ color: #60a5fa; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 13px;
           background: #111418; border: 1px solid #252c36; padding: 16px; border-radius: 8px; }}
    .nav {{ margin-bottom: 20px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="nav"><a href="/">&larr; Back to console</a></div>
    <pre>{body}</pre>
  </div>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/guide/training-and-maintenance", response_class=HTMLResponse)
def guide_training_and_maintenance():
    md_path = Path(APP_DIR) / "TRAINING_AND_MAINTENANCE.md"
    if not md_path.exists():
        return HTMLResponse(
            "<p>TRAINING_AND_MAINTENANCE.md not found in app directory.</p>",
            status_code=404,
        )
    raw = md_path.read_text(encoding="utf-8")
    body = html.escape(raw)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Training &amp; maintenance — Ed Console</title>
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0c0f; color: #e5e7eb;
            margin: 0; padding: 24px; line-height: 1.55; font-size: 14px; }}
    .wrap {{ max-width: 52rem; margin: 0 auto; }}
    a {{ color: #60a5fa; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 13px;
           background: #111418; border: 1px solid #252c36; padding: 16px; border-radius: 8px; }}
    .nav {{ margin-bottom: 20px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="nav">
      <a href="/">&larr; Back to console</a>
      · <a href="/guide/data-stewardship">Data stewardship</a>
      · <a href="/guide/pipeline-quality">Pipeline quality (TQM)</a>
      · <a href="/ops">Run tasks</a>
    </div>
    <pre>{body}</pre>
  </div>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/guide/pipeline-quality", response_class=HTMLResponse)
def guide_pipeline_quality():
    """TQM-style checkpoints: ingest throttles, audits, normalized layer, readiness."""
    md_path = Path(APP_DIR) / "PIPELINE_QUALITY.md"
    if not md_path.exists():
        return HTMLResponse(
            "<p>PIPELINE_QUALITY.md not found in app directory.</p>",
            status_code=404,
        )
    raw = md_path.read_text(encoding="utf-8")
    body = html.escape(raw)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pipeline quality (TQM) — Ed Console</title>
  <style>
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0c0f; color: #e5e7eb;
            margin: 0; padding: 24px; line-height: 1.55; font-size: 14px; }}
    .wrap {{ max-width: 52rem; margin: 0 auto; }}
    a {{ color: #60a5fa; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 13px;
           background: #111418; border: 1px solid #252c36; padding: 16px; border-radius: 8px; }}
    .nav {{ margin-bottom: 20px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="nav">
      <a href="/">&larr; Back to console</a>
      · <a href="/guide/data-stewardship">Data stewardship</a>
      · <a href="/guide/training-and-maintenance">Training &amp; maintenance</a>
      · <a href="/ops">Run tasks</a>
    </div>
    <pre>{body}</pre>
  </div>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/ops", response_class=HTMLResponse)
def ops_panel():
    """Interactive maintenance/training launcher (requires ED_OPS_RUNNER for actions)."""
    p = static_dir / "ops.html"
    if not p.exists():
        return HTMLResponse("<p>static/ops.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/api/ops/status")
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


@app.get("/api/level_crosses")
def api_level_crosses(ticker: str = "SPY", n: int = 20, level_name: str | None = None,
                            level_value: float | None = None, lookback_hours: float = 6.5):
    """Pass 4 — read consumer for level_crosses table.

    Two modes:
      * ``ticker`` only -> last ``n`` crosses (recent breach log).
      * ``ticker`` + ``level_name`` + ``level_value`` -> directional test count
        within ``lookback_hours`` (Decision Command "third test of ceiling"
        pattern, served by db.count_level_tests).
    """
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


@app.get("/api/ops/calibration_rowcount")
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
            health.get("last_24h_count", 0),
            health.get("expected_per_24h", 0.0),
            health.get("ratio") or 0.0,  # silent-zero-ok: log.warning argument only — the same line already prints last_24h and expected, so a 0.00 ratio cannot be mistaken for a measurement
            health.get("warn_ratio", 0.0),
        )
    return JSONResponse({"ok": True, **health})


@app.post("/api/ops/run")
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


@app.get("/governance", response_class=HTMLResponse)
def governance_visibility_page():
    """Architecture governance panel (read-only; manual actions gated on server)."""
    p = static_dir / "governance.html"
    if not p.exists():
        return HTMLResponse("<p>static/governance.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/api/governance/panel")
def api_governance_panel(
    ticker: str = Query("SPY", description="Ticker symbol"),
    horizon: str = Query("1c", description="ML horizon slug"),
    emit_notifications: bool = Query(
        False,
        description="When true, run notification delivery emit; use false for routine refresh to avoid duplicate sinks",
    ),
    include_live_drift: bool = Query(True, description="Include live drift monitoring in panel payload"),
):
    from pathlib import Path

    from arch_competition.governance_visibility import build_governance_panel_payload

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


@app.post("/api/internal/reload_models")
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


@app.post("/api/governance/manual-promote")
def api_governance_manual_promote(request: Request, payload: dict = Body(...)):
    from pathlib import Path

    from arch_competition.exceptions import ManualGovernanceError
    from arch_competition.governance_visibility import (
        client_may_run_governance_action,
        is_governance_ui_actions_enabled,
    )
    from arch_competition.manual_control import manual_promote_to_active_explicit

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


@app.post("/api/governance/manual-rollback")
def api_governance_manual_rollback(request: Request, payload: dict = Body(...)):
    from pathlib import Path

    from arch_competition.exceptions import ManualGovernanceError
    from arch_competition.governance_visibility import (
        client_may_run_governance_action,
        is_governance_ui_actions_enabled,
    )
    from arch_competition.manual_control import manual_rollback_to_checkpoint_explicit

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


@app.post("/api/ops/run-sequence")
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


def _tier_c_analytics_json_response(
    ticker: str,
    expiry: Optional[str],
    force: bool,
    update_source: str,
) -> JSONResponse:
    """
    Tier C — stale-while-refresh: always return from cache or a lightweight pending shell
    immediately; heavy _fetch_state runs only in background threads.
    """
    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: the Tier C analytics view must not enroll the symbol — only
    # refresh last-seen if it is already tracked (enrollment is /api/logger/add|pin only).
    _touch_tracked_ticker_view(ticker)

    inflight_key = _tier_c_inflight_key(ticker, expiry)
    now = time.time()

    data_cache_key: Optional[tuple] = None
    entry: Optional[dict] = None
    if expiry is not None:
        data_cache_key = (ticker, expiry)
        entry = _state_cache.get(data_cache_key)
    else:
        _md_latest, data_cache_key = _latest_cached_ms_and_key_for_ticker(ticker)
        if data_cache_key:
            entry = _state_cache.get(data_cache_key)

    if data_cache_key:
        sse_live = _sse_subscribers.get(data_cache_key, 0) > 0
    elif expiry is not None:
        sse_live = _sse_subscribers.get((ticker, expiry), 0) > 0
    else:
        sse_live = _any_sse_viewer_for_ticker(ticker)

    ttl = _sse_viewer_cache_ttl(
        ticker,
        data_cache_key[1] if data_cache_key else expiry,
    )
    # RC-282: this reached the RIGHT verdict for an undated entry by accident — `now - 0.0`
    # is ~1.8e9 seconds, which trips the grace window. The rule is now stated instead of
    # emerging from arithmetic on 1970, so it cannot flip if the sentinel ever changes.
    gen_ts = _analytics_generated_ts(entry) if entry else None
    age = None if gen_ts is None else max(0.0, now - gen_ts)

    has_body = bool(entry and entry.get("ms_dict"))
    # Stale-serve marker follows the honest grace window (missed cycle), same
    # authority as _attach_analytics_freshness_contract.
    stale = bool(
        (not has_body) or age is None
        or (age >= float(ttl) * ANALYTICS_STALE_GRACE_CYCLES)
    )

    # LIVE_OPERATOR_MODE_RESET_V1 Step 2 — single Tier C owner: when a live SSE
    # viewer owns this scope, _sse_background_loop is the only recompute scheduler
    # and REST is a read-only cache view. force=true (manual REFRESH) and the
    # cold/no-viewer poll path still self-schedule.
    need_refresh = bool(
        force or (not has_body) or age is None       # RC-282: undatable => recompute
        or ((not sse_live) and (age >= ttl))
    )

    if has_body:
        try:
            from live_pipeline_diag import emit_api_state_cache

            emit_api_state_cache(
                ticker=ticker,
                expiry=expiry if expiry is not None else (data_cache_key[1] if data_cache_key else None),
                cache_hit=True,
                ttl=ttl,
            )
        except Exception as e:
            log.debug("emit_api_state_cache (hit) failed ticker=%s: %s", ticker, e, exc_info=True)
        md = dict(entry["ms_dict"])
        _lmp.merge_into_state(md, ticker)
        md["_tier"] = "C_analytics"
        md["_endpoint"] = "/api/analytics/state"
        _attach_analytics_freshness_contract(
            md,
            data_cache_key=data_cache_key or (ticker, expiry),
            entry=entry,
            now=now,
            sse_live=sse_live,
            inflight_key=inflight_key,
        )
        if need_refresh:
            _schedule_analytics_recompute(inflight_key, ticker, expiry, update_source)
        from trade_impacting_gate import revalidate_cached_decision

        md = revalidate_cached_decision(
            md,
            route="server._tier_c_analytics_json_response",
            stale=bool(stale),
        )
        _attach_card_freshness_v1_block(
            md,
            ticker=ticker,
            now=now,
            analytics_ttl_sec=ttl,
            tier_c_cache_stale_serve=bool(stale and has_body),
            plane_quote=_lmp.get_quote(ticker),
        )
        _attach_db_contention_operator_surface(md)
        from market_state import attach_operator_visible_field_lineage

        attach_operator_visible_field_lineage(md)
        return JSONResponse(md)

    log.info(
        "Tier C cache miss — pending shell for %s expiry=%s; scheduling background",
        ticker,
        expiry,
    )
    try:
        from live_pipeline_diag import emit_api_state_cache

        emit_api_state_cache(ticker=ticker, expiry=expiry, cache_hit=False, ttl=None)
    except Exception as e:
        log.debug("emit_api_state_cache (miss) failed ticker=%s: %s", ticker, e, exc_info=True)
    md = _minimal_analytics_pending_dict(ticker, expiry)
    last_err = _analytics_bg_last_error.get(inflight_key)
    if last_err:
        md["analytics_last_error"] = last_err
        md["state_error"] = "analytics_refresh_failed"
        md["state_error_detail"] = last_err
    _lmp.merge_into_state(md, ticker)
    _attach_analytics_freshness_contract(
        md,
        data_cache_key=data_cache_key or (ticker, expiry),
        entry=None,
        now=now,
        sse_live=sse_live,
        inflight_key=inflight_key,
    )
    _attach_card_freshness_v1_block(
        md,
        ticker=ticker,
        now=now,
        analytics_ttl_sec=ttl,
        tier_c_cache_stale_serve=False,
        plane_quote=_lmp.get_quote(ticker),
    )
    _schedule_analytics_recompute(inflight_key, ticker, expiry, update_source)
    _attach_db_contention_operator_surface(md)
    from market_state import attach_operator_visible_field_lineage

    attach_operator_visible_field_lineage(md)
    return JSONResponse(md)


def _resolve_ticker_param(
    ticker: str,
    symbol: Optional[str] = None,
) -> str:
    """Canonical query param is ``ticker``; ``symbol`` is a documented alias (audit/diag scripts)."""
    raw = (symbol if symbol is not None and str(symbol).strip() else ticker) or DEFAULT_TICKER
    return str(raw).upper().strip()


@app.get("/api/live/state")
async def get_live_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: Optional[str] = Query(default=None),
    expiry: Optional[str] = Query(default=None),
):
    """
    Tier A — instant live quote plane + session + identity. No chain, exposures, DB, news, or heavy compute.
    Primary driver for responsive UI; use GET /api/analytics/state for full analytical bundle.
    """
    t = _resolve_ticker_param(ticker, symbol)
    # SWITCH-LATENCY FIX: this route is async, so ANY blocking work here stalls the whole
    # event loop (all SSE streams, the fast-quote poll, every other request) until it
    # returns — the root cause of slow ticker switches. Both _register_tracked_ticker
    # (persists the symbol to the SQLite logging_universe — a DB write that contends with
    # the live logger/retrain) and _tier_a_live_state_dict (blocking Schwab REST + retry on
    # a cold ticker) must run OFF the loop. Offload to the thread pool, like /api/fast-quote.
    def _build():
        # TICKER-PREVIEW-NO-ENROLL: live-state view touches last-seen only, never enrolls.
        _touch_tracked_ticker_view(t)
        return _tier_a_live_state_dict(t, expiry)
    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_quote_hot_executor(), _build)
    return JSONResponse(payload)


# ── TERRAIN COLLECTION LOOP ──────────────────────────────────────────────────
# 5-whys root cause (2026-07-19): 24 of 31 tickers refreshed only every ~11 minutes
# because `_live_operator_mode_active()` HARD-SKIPS non-SPY/QQQ/IWM background rotation
# whenever a viewer is connected -- a gate that exists because `_fetch_state` runs the
# full model stack and would otherwise compete with the live UI.
#
# Terrain does not run the model stack. Measured: ~5 ms of math per ticker plus one chain
# call each, i.e. ~31 req/min against a ~120 req/min Schwab budget. So terrain gets its
# OWN loop, is never gated on operator mode, and cannot be starved by inference work.
TERRAIN_REFRESH_SEC: float = 60.0
# Match the 2-slot Schwab chain gate. 4 workers × 200-strike payloads queued ~51 tickers
# and starved the operator card (gate timeouts, Tier-C partial/STALE) at the open.
TERRAIN_WORKERS: int = 2
RADAR_NEAR_PCT: float = 0.0020   # at the wall
RADAR_WATCH_PCT: float = 0.0075  # in the sector, worth watching
# Strike count is DERIVED per instrument, never tabulated — see math_levels.
# required_strike_count(). The bar is the flip's +/-5% span requirement
# (GAMMA_FLIP_MIN_SPAN_PCT); how many strikes that takes depends on the instrument's own
# strike spacing, so it is computed from measured geometry rather than assumed.
#
# MEASURED 2026-07-20 across 52 stored chains: the previous hardcoded table was wrong in
# BOTH directions — $SPX needed 150 and got 40; IWM needed 30 and got 80; ~48 equities
# needed under 20 and got 40. Over-fetching is not free: it saturates the 2-slot chain
# gate (observed starving the operator card at the open) and every payload is persisted
# twice (RC-6).
#: Floor. Below this, wall/pin selection has too few strikes to be meaningful regardless
#: of what the span arithmetic asks for; it is also the live UI's own chain width.
TERRAIN_STRIKE_COUNT_MIN: int = 20
#: Ceiling, set by the VENDOR not by us. Schwab returned HTTP 502 for SPY/QQQ at
#: strikeCount=200 at the 2026-07-20 open; 100 was observed working the same session.
#: A ticker whose requirement exceeds this is fetched at the ceiling and honestly reports
#: LOW_CONFIDENCE_NARROW_CHAIN rather than pretending.
#: RAISED 100 -> 120, MEASURED 2026-07-26 by `python tools/probe_chain_depth_v1.py` against the
#: live vendor (the previous 100 was an ASSUMPTION: 200 had 502'd and nothing between was tried).
#: Ladder result: SPY 120 OK / 150 -> HTTP 502; QQQ 120 OK / 150 -> 502; IWM OK to 250 (saturates
#: at 246 distinct strikes = its whole chain). 120 is therefore the highest UNIVERSALLY safe
#: request. What it delivers is far wider than the span bar suggests, because strikeCount applies
#: PER EXPIRY across ~35 expiries: SPY at 120 returned 259 distinct strikes spanning -40.5%/+44.8%
#: of spot (8,118 contracts), vs 219 strikes / -33.7%/+33.3% at 100.
#: KNOWN GAP: $SPX 502s even at 100, so it is not truncated — it fails outright and needs its own
#: LOWER ladder probe (RC-63); raising this ceiling does not help it.
TERRAIN_STRIKE_COUNT_MAX: int = 120
#: Used only until this ticker's geometry is known. The prewarm seeds geometry from
#: stored chains, so this normally applies to a ticker we have never seen.
TERRAIN_STRIKE_COUNT_COLD_START: int = 40

#: ticker -> (spot, strike_increment), learned from chains we have already fetched.
_strike_geometry: dict[str, tuple[float, float]] = {}
_strike_geometry_lock = threading.Lock()
#: ticker -> distinct expiry count, learned the same way (guarded by the same lock).
_strike_expiry_count: dict[str, int] = {}

#: RC-63 — the vendor's REAL limit, MEASURED 2026-07-26 (`python tools/probe_chain_depth_v1.py`).
#: Schwab caps the number of CONTRACTS in a chain response, not strikeCount: SPY returned 8,118
#: contracts at strikeCount=120 and HTTP 502 at 150; QQQ 7,894 at 120 then 502; $SPX 502'd at 80
#: with only 60 working (6,950 contracts) purely because it lists 55 expiries vs SPY's 35; IWM
#: never failed even at 250 because its whole chain is 5,492. So a single global strikeCount
#: ceiling is structurally wrong — it starves wide-expiry instruments and under-fetches narrow
#: ones.
#: VALUE CHOSEN BY BACK-TEST against those four measured ceilings, not by picking a round number:
#: `strikeCount * 2 * expiries` UNDER-predicts the real payload for some instruments ($SPX
#: returned 6,950 contracts where the estimate said 6,600), so a budget tuned to the largest
#: success (SPY's 8,118) would have allowed $SPX 72 — above its measured 502 threshold of 60.
#: 6,600 is the largest budget that reproduces EVERY measured ceiling without exceeding one:
#: SPY 94 (safe vs 120), QQQ 97 (vs 120), $SPX 60 (exactly its max), IWM 100 (vs 250).
#: Deliberately conservative: a 502 returns NO chain at all, while a slightly narrower request
#: still delivers far more than the span bar needs (SPY at 94 still spans ~±31% of spot).
SCHWAB_CHAIN_CONTRACT_BUDGET: int = 6600
#: Index option books ($SPX, $VIX, $RUT, $NDX, ...) list expirations out for YEARS (daily +
#: weekly + monthly + LEAPS), far more than the contract budget allows at any usable strike
#: width — RC-491 measured $SPX still 502 even at width 33 (33 * 2 * ~150 expiries = 9,900 >
#: 6,600). RC-494: the _fetch_state chain is therefore fetched only out to a bounded DTE
#: horizon (_chain_to_date_for → to_date), which caps the expiry count so a FIXED, generous
#: strike width fits the budget deterministically (no geometry feedback loop, RC-149).
#: SCOPE (verified 2026-08-25 — SAFE on all six semantics): this bound is correct ONLY for the
#: _fetch_state path, which slices the chain to a SINGLE (front) expiry before any gamma/flip/
#: pin/vanna/charm math runs, so the far expiries it drops were already discarded. It must NOT
#: be wired into the TERRAIN producer (_terrain_refresh_one): terrain is a deliberate
#: MULTI-EXPIRY aggregate over the FULL book (dealers hedge the whole delta book across weekly/
#: monthly expiries), so bounding it to 45d WOULD silently drop real gamma/flip/pin/wall/charm
#: contributions. Terrain keeps its own full→120d→45d ladder (to_date=None first rung).
#: 60 strikes * 2 * ~34 expiries in 45 days = ~4,080 < 6,600 (safe even at 55 expiries).
INDEX_CHAIN_DTE_HORIZON_DAYS: int = 45
INDEX_CHAIN_STRIKE_COUNT: int = 60


def _learn_strike_geometry(ticker: str, contracts: list | None, spot: float | None,
                           *, date_window_narrowed: bool = False) -> bool:
    """Remember this instrument's spot and strike spacing from a chain we just read.

    Returns True when a geometry was stored, so callers can count outcomes without
    reading the shared dict outside the lock (Cursor audit 2026-07-20: the seed loop
    compared len() across calls unlocked while workers mutate under the lock).

    RC-149 — `date_window_narrowed` exists because the expiry count is the DENOMINATOR of the
    width budget, and learning it from a date-narrowed chain inverts the safety it provides.
    A `to_date`-limited fetch returns only the expiries inside that window, so n_exp comes back
    SMALL; a small n_exp makes `resolve_chain_strike_count` compute a LARGER ceiling; the next
    cycle then asks for that wider chain over the FULL date range and blows the contract budget.
    The narrower the rung that rescued us, the more certain the next request is to fail — a
    feedback loop that cannot recover on its own. MEASURED 2026-07-30: $SPX's last success was
    on `chain_basis: dte<=120` with contracts_used 6785, and every fetch after it returned
    HTTP 502 for 2h10m. A narrowed chain's count is a FLOOR, never the truth, so it may seed an
    unknown instrument but must never overwrite a full-basis measurement.
    """
    tk = (ticker or "").upper().strip()
    if not tk or not contracts or spot is None or spot <= 0:
        return False
    incr = infer_strike_increment(contracts)
    if incr is None:
        return False
    # RC-63: also learn how many EXPIRIES this instrument lists. The vendor's real limit is on
    # the number of CONTRACTS returned, and contracts ~= strikeCount * 2 * expiries — so the
    # safe strikeCount depends on the expiry count, not on the ticker.
    n_exp = len({str(c.get("expirationDate"))[:10] for c in contracts
                 if isinstance(c, dict) and c.get("expirationDate")})
    with _strike_geometry_lock:
        _strike_geometry[tk] = (float(spot), float(incr))
        if n_exp > 0:
            if not date_window_narrowed:
                _strike_expiry_count[tk] = n_exp
            else:
                # a floor: raise a missing/too-low count, never lower a full-basis one
                _strike_expiry_count[tk] = max(_strike_expiry_count.get(tk, 0), n_exp)
    return True


def resolve_chain_strike_count(ticker: str) -> int:
    """THE strike-count faucet — one authority for EVERY chain fetch that feeds level math.

    RC-59: the console/analytics path (`_fetch_state`) and the terrain path used to size their
    chains differently — `_fetch_state` on a hardcoded CHAIN_STRIKE_COUNT=20 ("keep fast") and
    terrain on measured geometry — so the SAME ticker was analysed at two widths and the levels
    persisted to `snapshots` were narrower than the ones served on screen. Two widths is two
    answers; the width is now derived HERE and nowhere else.

    Right-sizing is not "always wider": MEASURED across 52 stored chains 2026-07-20, the old fixed
    count was wrong in BOTH directions — ~48 equities need UNDER 20 and were fetched at 40, while
    $SPX needs ~150 and got 40. Routing the console through this faucet therefore makes most
    tickers CHEAPER, not more expensive, and widens only where the +/-5% span requires it.

    Fail-closed: unknown geometry returns the cold-start default rather than a guessed width.
    The MAX is a VENDOR limit, not ours (Schwab 502s above it) — a ticker needing more is fetched
    at the ceiling and its levels self-report LOW_CONFIDENCE_NARROW_CHAIN rather than pretending.
    """
    tk = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX" so the
    #                                   faucet can't be bypassed by an un-normalized caller.
    if tk.startswith("$"):   # canonical index roots: $SPX/$VIX/$RUT/$NDX/$DJI
        # RC-494: index books are fetched over a bounded DTE horizon (_chain_to_date_for), so a
        # FIXED budget-safe width covers the whole near-term surface. Deterministic on purpose —
        # letting learned geometry drive the width recreated the RC-149 full-book feedback loop
        # that kept $SPX 502-ing. Paired with the to_date bound this is always well under budget.
        return INDEX_CHAIN_STRIKE_COUNT
    with _strike_geometry_lock:
        geom = _strike_geometry.get(tk)
        n_exp = _strike_expiry_count.get(tk)
    if geom is None:
        return TERRAIN_STRIKE_COUNT_COLD_START
    need = required_strike_count(geom[0], geom[1])
    if need is None:
        return TERRAIN_STRIKE_COUNT_COLD_START
    ceiling = TERRAIN_STRIKE_COUNT_MAX
    if n_exp and n_exp > 0:
        # RC-63: respect the VENDOR's contract budget, which is what actually 502s. A chain
        # returns ~ strikeCount * 2 (call+put) * expiries contracts, so an instrument listing 55
        # expiries ($SPX) must request a far smaller strikeCount than one listing 35 (SPY) to
        # return the same payload. Deriving the ceiling per ticker replaces a global constant
        # that was simultaneously too high for $SPX (502) and too low for everything else.
        ceiling = min(ceiling, max(TERRAIN_STRIKE_COUNT_MIN,
                                   SCHWAB_CHAIN_CONTRACT_BUDGET // (2 * n_exp)))
    return max(TERRAIN_STRIKE_COUNT_MIN, min(ceiling, need))


#: Back-compat alias — terrain's original name for the same authority.
_terrain_strike_count = resolve_chain_strike_count


def _chain_to_date_for(ticker: str, selected_expiry: str | None = None) -> str | None:
    """Bounded chain to_date (ISO YYYY-MM-DD) for index books, None for equities.

    RC-494: index option books ($SPX/$VIX/$RUT/...) list expirations out for years; fetching
    the FULL book blows Schwab's contract budget at any usable strike width (the $SPX 502).
    Capping the fetch to the near-term DTE horizon bounds the expiry count so
    resolve_chain_strike_count's fixed index width fits the budget. Equities return None (full
    book, unchanged). One authority for the index date bound, mirroring the strike-count faucet.

    If a caller EXPLICITLY selects a far-dated index expiry (beyond the horizon), to_date is
    extended to it — otherwise the downstream slice to that expiry would be empty and error
    (RC-494 robustness). Cursor-audit F2: extending to_date ALONE turned a one-expiry request
    into a today->far multi-expiry sweep (Schwab returns every expiry up to to_date), re-blowing
    the budget. The companion _chain_from_date_for bounds the NEAR edge to the same far date for
    that case, so the window is [sel, sel] — a single expiry (60*2=120 contracts). The auto/default
    path passes no expiry and gets the open-near-end horizon."""
    tk = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX"
    if not tk.startswith("$"):
        return None
    from datetime import date, timedelta

    from time_et import now_et

    horizon = (now_et() + timedelta(days=INDEX_CHAIN_DTE_HORIZON_DAYS)).date()
    if selected_expiry:
        try:
            sel = date.fromisoformat(str(selected_expiry)[:10])
            if sel > horizon:
                return sel.isoformat()
        except ValueError:
            pass
    return horizon.isoformat()


def _chain_from_date_for(ticker: str, selected_expiry: str | None = None) -> str | None:
    """Chain fetch from_date (ISO YYYY-MM-DD) — the NEAR edge of the window, normally None so
    Schwab defaults it to today.

    Cursor-audit F2: paired with _chain_to_date_for. When an operator explicitly selects an index
    expiry BEYOND the 45-day horizon, _chain_to_date_for pushes to_date out to it; without also
    bounding the near edge Schwab returns EVERY expiry from today through that far date
    (60 strikes * 2 * ~150 expiries = ~18,000 contracts >> SCHWAB_CHAIN_CONTRACT_BUDGET), the
    RC-491 502 — even though _fetch_state then slices to that ONE expiry and discards the rest.
    Bounding from_date to the same far date pulls only that expiry's strikes (60*2=120). Fires ONLY
    for a far index pick; equities, the auto path, and near picks (already inside the bounded
    horizon window) keep the open near end unchanged."""
    tk = ticker_storage_key(ticker)   # Cursor-audit F1: bare index root ("SPX") -> "$SPX"
    if not tk.startswith("$") or not selected_expiry:
        return None
    from datetime import date, timedelta

    from time_et import now_et

    horizon = (now_et() + timedelta(days=INDEX_CHAIN_DTE_HORIZON_DAYS)).date()
    try:
        sel = date.fromisoformat(str(selected_expiry)[:10])
    except ValueError:
        return None
    return sel.isoformat() if sel > horizon else None

_terrain_cache: dict[str, dict] = {}
_terrain_cache_lock = threading.Lock()
#: RC-126: the producer's last failure per ticker, so terrain_not_ready can say WHY instead
#: of shrugging forever (how $SPX stayed dark a full session). Cleared on the next success.
_terrain_refresh_last_error: dict[str, str] = {}
#: RC-146: the producer's DELIBERATE skips, per ticker. Distinct channel from the error dict
#: above on purpose — a budget-justified pause is not a failure, and collapsing the two would
#: report a working scheduler as broken. Written by _terrain_loop at the moment it drops a
#: ticker from the cycle, read by terrain_staleness so every stale payload carries the real
#: reason. A degradation that records nothing is indistinguishable from a malfunction.
_terrain_skipped_reason: dict[str, str] = {}
_terrain_skip_lock = threading.Lock()

#: RC-148 — QUARANTINE. Visibility is not sufficiency: RTY and XXT are rejected by the vendor
#: (`chain fetch failed (HTTP 400)`, no spot, no expiries) yet the loop re-requested them every
#: 60 s against a 2-slot chain gate, indefinitely. A permanently-rejected symbol is not a
#: transient error to retry — it is a symbol that will never answer, and retrying it spends a
#: scarce vendor slot the healthy book needs. Hard rejections (HTTP 4xx: the symbol itself is
#: refused) quarantine PERMANENTLY after TERRAIN_QUARANTINE_HARD_FAILS consecutive hits and stay
#: out until an operator re-admits. Soft failures (timeout / 5xx / 429: the venue is busy, the
#: symbol is fine) back off exponentially and re-admit themselves.
TERRAIN_QUARANTINE_HARD_FAILS: int = 3
TERRAIN_QUARANTINE_SOFT_BASE_SEC: float = 60.0
TERRAIN_QUARANTINE_SOFT_MAX_SEC: float = 900.0
#: Env override exists for TESTS ONLY (set in tests/conftest.py before any import, so a
#: lazy mid-test `import server` can never write the tracked operator audit file — the
#: class CI's ledger firewall caught 2026-08-24). Production never sets the variable.
TERRAIN_QUARANTINE_LEDGER = Path(
    os.environ.get("ED_TERRAIN_QUARANTINE_LEDGER")
    or (Path(APP_DIR) / "reports" / "terrain_quarantine_ledger.jsonl"))

_terrain_quarantine: dict[str, dict] = {}
_terrain_consecutive_fails: dict[str, int] = {}
_terrain_quarantine_skips: dict[str, int] = {}
_terrain_quarantine_lock = threading.Lock()


def _quarantine_ledger_append(event: str, tk: str, payload: dict) -> None:
    """Append-only record of every quarantine decision. A control the operator cannot audit
    after the fact is a control they have to take on trust."""
    try:
        TERRAIN_QUARANTINE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts_utc": time.time(), "et": now_et().isoformat(), "event": event,
               "ticker": tk, **payload}
        with open(TERRAIN_QUARANTINE_LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError as e:                      # a ledger that cannot write must not stop the loop
        log.warning("quarantine ledger write failed for %s: %s", tk, e)


def _classify_chain_failure(status_code: int | None, exc_name: str | None) -> str:
    """"hard" = the vendor refuses THIS SYMBOL (4xx); "soft" = the venue is busy (timeout/5xx/429).

    Fail-closed to "soft": an unrecognised failure must never earn a permanent quarantine, because
    a wrong permanent verdict silently removes a real instrument from the board.
    """
    if status_code is not None:
        code = int(status_code)
        if code == 429:
            return "soft"                     # rate limit is about US, never about the symbol
        if 400 <= code < 500:
            return "hard"
        return "soft"
    if exc_name in ("ReadTimeout", "ConnectTimeout", "TimeoutException"):
        return "soft"
    return "soft"


def terrain_quarantine_state(ticker: str | None = None) -> dict:
    """Snapshot of the quarantine book (whole book, or one ticker's entry)."""
    with _terrain_quarantine_lock:
        if ticker:
            tk = ticker_storage_key(ticker)
            e = _terrain_quarantine.get(tk)
            return dict(e) if e else {}
        return {k: dict(v) for k, v in _terrain_quarantine.items()}


def terrain_quarantine_reason(ticker: str | None) -> str:
    """Why this ticker is not being requested at all, or "" when it is in the rotation."""
    if not ticker:
        return ""
    tk = ticker_storage_key(ticker)
    with _terrain_quarantine_lock:
        e = _terrain_quarantine.get(tk)
        if not e:
            return ""
        if e.get("permanent"):
            return (f"QUARANTINED after {e.get('failures')} consecutive hard rejections — "
                    f"{e.get('reason')}. The vendor refuses this symbol, so the loop has stopped "
                    f"requesting it; it stays out until an operator re-admits it "
                    f"(POST /api/terrain/quarantine/release?ticker={tk})")
        # RC-281: every constructor supplies until_ts, so absence is MALFORMED STATE, not
        # "no cooldown". My earlier reason claimed the latter; Cursor's runtime probe showed
        # it releases the hold and erases the entry, turning an invariant failure into an
        # immediate vendor retry with the evidence gone.
        from numeric_contract import float_finite_or_none as _fin_q
        until = _fin_q(e.get("until_ts"))
        if until is None:
            return (f"backing off after {e.get('failures')} consecutive failures — "
                    f"{e.get('reason')}; hold has NO expiry recorded (malformed entry), "
                    f"so it is held until an operator releases it")
        left = max(0.0, until - time.time())
        return (f"backing off after {e.get('failures')} consecutive failures — {e.get('reason')}; "
                f"next attempt in {left:.0f}s")


def _terrain_quarantine_blocks(tk: str) -> bool:
    """True when this ticker must NOT be requested this cycle. Expired soft holds self-release."""
    now = time.time()
    with _terrain_quarantine_lock:
        e = _terrain_quarantine.get(tk)
        if not e:
            return False
        if e.get("permanent"):
            _terrain_quarantine_skips[tk] = _terrain_quarantine_skips.get(tk, 0) + 1
            return True
        # RC-281: fail CLOSED on a malformed hold. `or 0.0` dated the expiry to 1970, so the
        # branch never fired, the entry was popped, and the ticker went straight back into
        # rotation — the opposite of a quarantine, reached by a missing field.
        from numeric_contract import float_finite_or_none as _fin_qb
        until = _fin_qb(e.get("until_ts"))
        if until is None or now < until:
            _terrain_quarantine_skips[tk] = _terrain_quarantine_skips.get(tk, 0) + 1
            return True
        _terrain_quarantine.pop(tk, None)      # soft hold expired — back into the rotation
    _quarantine_ledger_append("soft_release", tk, {"note": "backoff elapsed, retrying"})
    return False


def _note_terrain_failure(tk: str, reason: str, kind: str) -> None:
    """Record a failed refresh and quarantine when the pattern earns it.

    The streak counter lives under the SAME lock as the quarantine book it feeds. TERRAIN_WORKERS
    threads run the rotation while `/api/terrain` can drive `_terrain_refresh_one(priority=True)`
    for the same ticker concurrently, so a read-modify-write outside the lock can drop a failure —
    and a dropped failure is a retry storm that never reaches its own threshold.
    """
    log_msg: tuple | None = None
    ledger: tuple | None = None
    with _terrain_quarantine_lock:
        n = _terrain_consecutive_fails.get(tk, 0) + 1
        _terrain_consecutive_fails[tk] = n
        if n >= TERRAIN_QUARANTINE_HARD_FAILS:
            if kind == "hard":
                already = bool(_terrain_quarantine.get(tk, {}).get("permanent"))
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "permanent": True,
                                           "since_ts": time.time(), "until_ts": None,
                                           "kind": kind}
                if not already:
                    log_msg = ("terrain QUARANTINE (permanent) %s after %d hard rejections: %s",
                               tk, n, reason)
                    ledger = ("quarantine_permanent", {"failures": n, "reason": reason})
            else:
                wait = min(TERRAIN_QUARANTINE_SOFT_MAX_SEC,
                           TERRAIN_QUARANTINE_SOFT_BASE_SEC
                           * (2 ** (n - TERRAIN_QUARANTINE_HARD_FAILS)))
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "permanent": False,
                                           "since_ts": time.time(),
                                           "until_ts": time.time() + wait, "kind": kind}
                log_msg = ("terrain backoff %s for %.0fs after %d failures: %s",
                           tk, wait, n, reason)
                ledger = ("backoff", {"failures": n, "reason": reason,
                                      "wait_sec": round(wait, 1)})
    # Disk and logging stay OUTSIDE the lock: a slow ledger write must never hold the producer.
    if log_msg:
        log.warning(*log_msg)
    if ledger:
        _quarantine_ledger_append(ledger[0], tk, ledger[1])


def _note_terrain_success(tk: str) -> None:
    """A success clears the streak AND any soft hold — the symbol answered."""
    with _terrain_quarantine_lock:
        _terrain_consecutive_fails.pop(tk, None)
        had = _terrain_quarantine.pop(tk, None)
    if had and not had.get("permanent"):
        _quarantine_ledger_append("cleared_by_success", tk, {})


def terrain_quarantine_release(ticker: str) -> dict:
    """Operator re-admission. Explicit, logged, and the ONLY way out of a permanent hold."""
    tk = ticker_storage_key(ticker)
    with _terrain_quarantine_lock:
        had = _terrain_quarantine.pop(tk, None)
        _terrain_consecutive_fails.pop(tk, None)
        _terrain_quarantine_skips.pop(tk, None)
    _quarantine_ledger_append("operator_release", tk, {"was": had or {}})
    log.warning("terrain quarantine RELEASED by operator: %s (was %s)", tk, had)
    return {"ticker": tk, "released": bool(had), "was": had or {}}


def _note_terrain_skip(tickers: list[str], reason: str) -> None:
    """Record WHY these tickers were dropped from a cycle; clear everyone else.

    Keyed through `ticker_storage_key` — the ONE normalisation authority (RC-126) — because
    `_terrain_refresh_last_error` beside it is keyed that way too. Two dicts describing the same
    ticker under two different spellings is how a reader silently misses one of them.
    """
    keep = {ticker_storage_key(t) for t in tickers if t}
    with _terrain_skip_lock:
        _terrain_skipped_reason.clear()
        for t in keep:
            _terrain_skipped_reason[t] = reason


def _clear_terrain_skips() -> None:
    with _terrain_skip_lock:
        _terrain_skipped_reason.clear()


def terrain_skip_reason(ticker: str | None) -> str:
    """The producer's own reason for not refreshing this ticker, or "" when none."""
    if not ticker:
        return ""
    with _terrain_skip_lock:
        return _terrain_skipped_reason.get(ticker_storage_key(ticker), "")


def _terrain_kl_overlay(md: dict, ticker: str) -> None:
    """W3-C1 / RC-122: ONE wall book on the screen.

    The Key Levels table read kl_* gamma-family values computed from the ANALYTICS pipeline's
    narrow chain while the terrain cards painted the wide-capture book beside them — two wall
    books, one screen, no label saying which is which (the dual-book lie the operator's
    audits carried since Wave-1). Terrain is THE levels SSOT (RC-33); every gamma-family kl_*
    is overlaid from its cached payload, stamped kl_levels_source. Absent or stale terrain
    BLANKS the keys — absence, never a silently different second book. The narrow-book wall
    STRENGTH strings are blanked with the same stroke: a dollar figure computed from one
    chain printed beside a strike from another is the same lie in a smaller cell.
    OI/vanna walls, inflections, and oi_center stay blank: terrain does not compute them,
    so analytics must never stand in for an absent SSOT value (RC-128 / RC-422).
    """
    t = dict(terrain_cache_get(ticker) or {})
    fresh = bool(t) and not t.get("levels_stale")
    # RC-124/RC-292: kl_absolute_gamma_strike carries the total-gamma concentration under
    # its metric's name (formerly kl_gamma_pin — a pin claim the metric had not earned);
    # kl_pin_candidate carries the QUALIFIED pin claim, blank with its blocker names
    # otherwise; kl_hvl carries the net-GEX peak (the former "pin", honestly renamed on
    # the card) — that key name is historical, the row label and tooltip say what it is.
    # RC-128 (One Levels Faucet): this helper is THE ONLY WRITER of every SSOT level key on
    # a UI payload. The analytics assignments were DELETED, not overridden — placement was
    # the bug (a write after this call resurrected the dual book). Delta walls joined the
    # terrain producer; EM comes from the terrain sigma band; concepts terrain does not
    # compute (OI/vanna walls, inflections, oi_center) are BLANKED with the reason — an
    # analytics book may never stand in for an absent SSOT value.
    # Explicit literal assignments, deliberately not a loop: the orphan-key detector (RC-84)
    # counts literal write sites, and a loop-driven write made three honest reads look
    # writerless. Verbosity is the price of a detector that can actually see the writer.
    _g = (lambda k: t.get(k)) if fresh else (lambda k: None)
    md["kl_call_gamma_wall"] = _g("call_wall")
    md["kl_put_gamma_wall"] = _g("put_wall")
    md["kl_gamma_flip"] = _g("gamma_flip")
    md["kl_absolute_gamma_strike"] = _g("absolute_gamma_strike")
    md["kl_absolute_gamma_strength_pct"] = _g("absolute_gamma_strength_pct")
    # RC-292 operator disposition: the pin CLAIM ships only after regime/proximity/DTE/
    # liquidity/completeness qualification (terrain_engine.qualify_pin_candidate); the
    # blocker names ship beside it so absence renders with its reason, never a bare dash.
    md["kl_pin_candidate"] = _g("pin_candidate")
    md["kl_pin_candidate_blockers"] = _g("pin_candidate_blockers")
    # RC-292/RC-417: payload `absolute_gamma_strike` is the same SSOT total-gamma value as
    # kl_absolute_gamma_strike (top-level key kept so the terrain- and analytics-payload
    # shapes agree, and so any resurrected analytics writer of this name is overwritten by
    # the SSOT here). Analytics consensus_summary.net_gex_peak is pick_net_gex_peak_strike
    # (selected-expiry |net GEX$| peak) and must never occupy this key. MEASURED on the
    # real SPY 0DTE fixture: total-gamma concentration 745 vs net peak 743.
    md["absolute_gamma_strike"] = md["kl_absolute_gamma_strike"]
    md["kl_hvl"] = _g("net_gex_peak")
    # RC-354: GSF/GRC ride the same SSOT terrain book (one profile, one producer). The
    # STATE ships beside the prices so the UI can render BELOW SUPPORT as a verdict, never
    # a dash that reads like "unknown" when the truth is "support is already gone".
    md["kl_gsf"] = _g("gsf")
    md["kl_grc"] = _g("grc")
    md["kl_gsf_state"] = _g("gsf_state")
    md["kl_gsf_state_disp"] = "BELOW SUPPORT" if _g("gsf_state") == "BELOW_SUPPORT" else None
    # RC-357: 0DTE share of the gamma book — level persistence, same SSOT terrain book.
    md["kl_zero_dte_share"] = _g("zero_dte_gamma_share_pct")
    # RC-358: 25Δ risk reversal — skew steepness; flattened for the payload, fail-closed.
    _rr = _g("rr_25d") or {}
    md["kl_rr25_pts"] = _rr.get("rr_pts") if isinstance(_rr, dict) else None
    md["kl_rr25_dte"] = _rr.get("dte") if isinstance(_rr, dict) else None
    # RC-359: ΔOI walls — fresh vs stale positioning; None until two sessions are banked.
    _doi = _g("delta_oi_walls") or {}
    _doi_ok = isinstance(_doi, dict)
    md["kl_doi_call_strike"] = _doi.get("call_build_strike") if _doi_ok else None
    md["kl_doi_call_oi"] = _doi.get("call_build_doi") if _doi_ok else None
    md["kl_doi_put_strike"] = _doi.get("put_build_strike") if _doi_ok else None
    md["kl_doi_put_oi"] = _doi.get("put_build_doi") if _doi_ok else None
    md["kl_doi_unwind_strike"] = _doi.get("unwind_strike") if _doi_ok else None
    md["kl_doi_unwind_oi"] = _doi.get("unwind_doi") if _doi_ok else None
    # RC-361: aggregate dealer DEX $ — directional inventory beside the GEX-per-1% row.
    _dex = _g("dex_dollars") or {}
    md["kl_dex_net"] = _dex.get("net_dex") if isinstance(_dex, dict) else None
    # RC-362: aggregate dealer vanna $ per vol-pt — the IV-driven hedge-flow size.
    _vna = _g("vanna_agg") or {}
    md["kl_vanna_net_dollars"] = _vna.get("net_vanna_dollars_per_volpt") if isinstance(_vna, dict) else None
    md["kl_max_pain"] = _g("max_pain")
    md["kl_call_delta_wall"] = _g("call_delta_wall")
    md["kl_put_delta_wall"] = _g("put_delta_wall")
    # v23: the flip's CONFIDENCE rides the same book as the flip's STRIKE — it was still
    # analytics-written while the strike was terrain's, a half-dual book.
    md["kl_gamma_flip_confidence"] = _g("confidence")
    # RC-130: the geometry state travels WITH the wall value it qualifies — as of the same
    # terrain generation (kl_levels_from_computed_ts). A wall value without its state let
    # the KL table caption "support" on a put wall sitting above spot.
    md["kl_call_wall_state"] = _g("call_wall_state")
    md["kl_put_wall_state"] = _g("put_wall_state")
    # v23 Lock-3 drift visibility: which terrain generation stamped these values — the KL
    # table and the terrain cards can only differ by generation skew, and now it is visible.
    md["kl_levels_from_computed_ts"] = _g("computed_ts_utc")
    em = (t.get("implied_1d_move") or {}) if fresh else {}
    _em_pts, _em_spot = em.get("points"), (t.get("spot") if fresh else None)
    if _em_pts is not None and _em_spot:
        md["kl_em_upper"] = round(float(_em_spot) + float(_em_pts), 2)
        md["kl_em_lower"] = round(float(_em_spot) - float(_em_pts), 2)
        # RC-345 / F06: the operator-facing kl_em band comes from the terrain implied-1d-move
        # (IV sigma band: S x sigma_ATM x sqrt(1/252)). Carry its methodology to the payload so
        # the operator never receives an EM number without knowing which EM semantic produced
        # it — the terrain `method` string travels beside the band, not dropped.
        md["kl_em_source"] = "IV_SIGMA_1D"
        md["kl_em_method_detail"] = em.get("method") or "S x sigma_ATM x sqrt(1/252)"
    else:
        md["kl_em_upper"] = md["kl_em_lower"] = None
        md["kl_em_source"] = "unavailable"
        md["kl_em_method_detail"] = None
    # terrain does not compute these yet — absence, never a second book
    md["kl_call_oi_wall"] = None
    md["kl_put_oi_wall"] = None
    md["kl_call_vanna_wall"] = None
    md["kl_put_vanna_wall"] = None
    md["kl_gamma_inflection"] = None
    md["kl_delta_inflection"] = None
    md["kl_oi_center"] = None
    # a strength from another book beside an SSOT strike is the same lie — blanked
    md["kl_call_delta_str"] = "—"
    md["kl_put_delta_str"] = "—"
    md["kl_call_oi_str"] = "—"
    md["kl_put_oi_str"] = "—"
    md["kl_call_vanna_str"] = "—"
    md["kl_put_vanna_str"] = "—"
    md["kl_levels_source"] = ("terrain_wide_chain" if fresh else
                              "terrain_unavailable — gamma-family levels withheld")
    for k in ("kl_call_gamma_str", "kl_put_gamma_str", "kl_hvl_str", "kl_max_pain_str"):
        md[k] = "—"
_terrain_loop_running: bool = False
_terrain_loop_thread: threading.Thread | None = None


def terrain_cache_get(ticker: str) -> dict | None:
    """Return the cached wide-chain terrain snapshot with staleness merged.

    RC-424: the loop stores computed_ts_utc, not levels_stale. Every consumer that
    gates pin/wall/overlay freshness must derive staleness from terrain_staleness
    (the production authority), never treat a missing levels_stale key as fresh.
    """
    tk = ticker_storage_key(ticker)
    with _terrain_cache_lock:
        raw = _terrain_cache.get(tk)
    if raw is None:
        return None
    out = dict(raw)
    out.update(terrain_staleness(out.get("computed_ts_utc"), ticker))
    return out


def terrain_cache_size() -> int:
    with _terrain_cache_lock:
        return len(_terrain_cache)


#: (ticker, et_date) pairs whose morning wide capture is already persisted — in-process
#: memo so the loop does not hit the DB with has_morning_full_capture every 60s.
_morning_capture_done: set[tuple[str, str]] = set()
_morning_capture_lock = threading.Lock()


def _universal_capture_wanted(tk: str) -> tuple[bool, tuple[str, str]]:
    """Does `tk` still need today's wide morning capture?

    UNIVERSAL MORNING CAPTURE (operator 2026-07-20). The sentinel-only capture rides the
    money-path logger, which RC-1's operator-mode gate skips for non-sentinels whenever a
    viewer is connected — measured result: 3 of ~51 tickers captured today. The terrain
    loop touches EVERY ticker each cycle, so it closes the gap in the post-window span
    (10:00-11:30 ET, deliberately AFTER the money-path window): one wide fetch serves
    both terrain and the archive. Idempotent per (ticker, ET day); DB checked once per
    day per ticker, then memoised in-process.
    """
    cap_date, cap_mins = gex_et_date_and_mins()
    key = (tk, cap_date)
    if not universal_capture_window(cap_mins):
        return False, key
    with _morning_capture_lock:
        if key in _morning_capture_done:
            return False, key
        attempts = _morning_capture_attempts.get(key, 0)
        if attempts >= _MORNING_CAPTURE_MAX_ATTEMPTS:
            # Three wide fetches produced nothing persistable — stop paying for wide
            # width every cycle; the day is a miss for this ticker, said out loud once.
            _morning_capture_done.add(key)
            log.warning("morning wide capture GIVEN UP ticker=%s after %d attempts",
                        tk, attempts)
            return False, key
        _morning_capture_attempts[key] = attempts + 1
    if has_morning_full_capture(get_db().db_path, tk, cap_date):
        with _morning_capture_lock:
            _morning_capture_done.add(key)
        return False, key
    return True, key


#: Per-(ticker, et_date) persist attempts. Bugbot MEDIUM (confirmed): an empty flatten
#: skipped persist WITHOUT memoising, so the loop re-forced the wide width every ~60s for
#: the entire 90-minute span. Three strikes and the day is done for that ticker.
_morning_capture_attempts: dict[tuple[str, str], int] = {}
_MORNING_CAPTURE_MAX_ATTEMPTS = 3


def _persist_universal_capture(tk: str, key: tuple[str, str], width: int,
                               contracts: list, spot: float | None) -> None:
    """Persist the wide chain just fetched. Archive concern — terrain must still serve.

    Bugbot 2026-07-20 (HIGH — confirmed): the first version ignored the persist RETURN
    DICT and memoised + logged success on any non-exception — including the status
    dicts that mean "nothing was written". A silently-discarded capture then read as
    captured for the rest of the ET day. The dict is now the arbiter:
      ok / idempotent_skip            -> memoise (done for the day), log accordingly
      too_few_near_term_contracts    -> memoise WITH WARNING (a thin chain will not
                                         thicken intraday; retrying burns wide fetches)
      anything else                  -> warn, do NOT memoise, bounded by the attempt cap
    """
    try:
        result = maybe_persist_morning_full_chain(
            get_db().db_path, ticker=tk, contracts=contracts,
            spot=float(spot) if spot is not None else None,
            ts_utc=time.time(), source=GEX_SOURCE_WIDE,
        )
    except Exception as e:
        log.warning("morning wide capture persist failed ticker=%s: %s", tk, e)
        return
    status = str(result.get("status", ""))
    if status == "ok":
        with _morning_capture_lock:
            _morning_capture_done.add(key)
        log.info("morning wide capture persisted ticker=%s width=%d n=%s",
                 tk, width, result.get("n_contracts"))
    elif status == "idempotent_skip":
        with _morning_capture_lock:
            _morning_capture_done.add(key)
    elif result.get("reason") == "too_few_near_term_contracts":
        with _morning_capture_lock:
            _morning_capture_done.add(key)
        log.warning("morning wide capture SKIPPED for the day ticker=%s: only %s "
                    "near-term contracts", tk, result.get("n"))
    else:
        log.warning("morning wide capture not persisted ticker=%s status=%s reason=%s",
                    tk, status, result.get("reason"))


#: Flip-drift measurement (unproven-register row due 2026-07-31): the mechanism is
#: proven (gamma depends on spot/IV/time) but the intraday MAGNITUDE of flip movement
#: is unmeasured. Every terrain-loop compute appends one JSONL row here so a week of
#: cycles yields per-ticker intraday min/max/range. reports/ file, not a table — the
#: operational DB grows by zero bytes (RC-6 discipline). flip=None is absence and is
#: not logged; gaps read as gaps from the timestamps.
_FLIP_DRIFT_LOG_PATH = Path(APP_DIR) / "reports" / "flip_drift_log.jsonl"
_flip_drift_lock = threading.Lock()


def _log_flip_drift(tk: str, payload: dict) -> None:
    """Append one flip-drift row. Never raises — terrain refresh must stay ok:x
    even if logging row assembly or disk write fails (measurement only)."""
    try:
        flip = payload.get("gamma_flip")
        if flip is None:
            return
        _ts = round(float(payload.get("computed_ts_utc") or time.time()), 1)
        # RC-58: INTRADAY drift is the question, so only real trading sessions may be logged.
        # The loop runs around the clock, and the first week of this log was 784 of 784 rows from
        # a single SUNDAY window — spot frozen, so it measured a median 0.023 percent movement and
        # would have been reported as "the flip is stable intraday". Market-closed rows do not
        # add noise here, they manufacture the null.
        from time_et import is_tradable_session_ts_utc as _tradable
        if not _tradable(_ts):
            return
        row = {"ts_utc": _ts,
               "ticker": tk, "flip": round(float(flip), 4),
               "spot": payload.get("spot"), "confidence": payload.get("confidence")}
        with _flip_drift_lock, open(_FLIP_DRIFT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("flip drift log append failed: %s", e)


#: How old the terrain snapshot may be before it must stop calling itself current. DERIVED from
#: the loop's own cadence: TERRAIN_REFRESH_SEC=60 plus one full cycle's slack for fetch time, so a
#: healthy loop never trips it and a stopped one trips within two cycles.
TERRAIN_STALE_AFTER_SEC: float = 180.0


#: RC-108: Schwab refresh tokens die at 7 days, hard. The 2026-07-28 open went fully dark
#: because the expiry sat in schwab_token.json for a week with no forward warning — the system
#: only screamed AFTER the data was lost. Warn from day 5, red from day 6.
_SCHWAB_TOKEN_WARN_DAYS = 5.0
_SCHWAB_TOKEN_RED_DAYS = 6.0


def schwab_token_countdown(creation_ts: float | None) -> dict:
    """Pure urgency computation from the token file's creation_timestamp (unit-tested)."""
    if creation_ts is None:
        return {"schwab_token_age_days": None, "schwab_token_urgency": "unknown",
                "schwab_token_note": "token file unreadable — collection may be dead"}
    age_days = round((time.time() - float(creation_ts)) / 86400.0, 2)
    if age_days >= _SCHWAB_TOKEN_RED_DAYS:
        urgency, note = "red", (f"Schwab token is {age_days:.1f} days old (7-day hard limit) — "
                                f"re-auth NOW: python reauth_schwab.py --manual")
    elif age_days >= _SCHWAB_TOKEN_WARN_DAYS:
        urgency, note = "warn", (f"Schwab token is {age_days:.1f} days old — re-auth before "
                                 f"day 7 kills collection: python reauth_schwab.py --manual")
    else:
        urgency, note = "ok", ""
    return {"schwab_token_age_days": age_days, "schwab_token_urgency": urgency,
            "schwab_token_note": note}


def _schwab_token_creation_ts() -> float | None:
    """creation_timestamp from schwab_token.json; None (never a fake age) when unreadable."""
    try:
        raw = json.loads((Path(APP_DIR) / "schwab_token.json").read_text(encoding="utf-8"))
        return float(raw["creation_timestamp"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def terrain_staleness(computed_ts_utc: float | None, ticker: str | None = None) -> dict:
    """Whether the levels are current, and WHY NOT when they are not (RC-91).

    RC-146 — the reason must come from the PRODUCER, not be inferred from a clock. Age alone
    cannot tell a deliberate pause from a broken loop, so this function used to answer "inside
    its window but not producing" for a scheduler that was working exactly as designed. When a
    ticker was skipped on purpose, `terrain_skip_reason` has the real sentence and it wins.
    Pass `ticker` wherever it is known; omitting it degrades to the old clock-only reason.

    MEASURED 2026-07-27 18:02 ET: /api/terrain computed_ts_utc did not advance across 90s against
    a 60s cadence, the gamma panel served data 90 MINUTES old under a `terrain_live_cache` label,
    and spot beside it was 3 seconds old. The terrain loop refreshes only while
    _is_loggable_session() is true, which ends at LOGGER_BUFFER_MINS (16:30 ET) — 210 minutes
    before the capture window closes. That function is the BACKGROUND LOGGING gate; using it to
    decide whether the screen is current answered a different question with the same switch.

    Stopping the loop after the post-market buffer may well be correct. Serving its last output
    under a live label is not: staleness that is budget-justified gets LABELLED, staleness that is
    not gets removed (the RC-78 rule, applied to the scorecard that day and never to terrain).
    """
    refreshing = _is_loggable_session()
    token = schwab_token_countdown(_schwab_token_creation_ts())   # RC-108: warn BEFORE death
    skipped = terrain_skip_reason(ticker)   # RC-146: the producer's own words, when it has any
    # RC-147: the FAILURE channel, which RC-146 left unread. `_terrain_refresh_last_error` was
    # consulted at exactly ONE call site — the not-ready branch of /api/terrain, reachable only
    # when NO snapshot exists. The moment a ticker has any cached snapshot, that branch is dead
    # and the recorded exception becomes unreachable, so a ticker failing every single refresh
    # reported `error: ""` and a generic "inside its window but not producing". MEASURED
    # 2026-07-30 10:16 ET: $SPX served levels 2,737 s old (45.6 min) with volume bars painting
    # beside them, chain_basis already degraded to `dte<=120`, and no surface anywhere naming
    # the cause. Precedence: a pause recorded for THIS cycle is why it is not refreshing right
    # now and wins; otherwise the last failure is the live reason; the clock is the last resort.
    # RC-148: quarantine outranks both. A quarantined ticker is not merely failing — it is not
    # being REQUESTED, which is a different fact and a different operator action (re-admit it,
    # or accept it is gone). Precedence for the REASON: quarantine > this-cycle pause > last
    # failure > clock. The FLAGS stay orthogonal on purpose: a hard quarantine is still FAILING
    # (the vendor refuses the symbol) and is emphatically NOT "paused, resumes on its own", so
    # collapsing it into either single flag would restore the ambiguity RC-146/147 removed.
    q_entry = terrain_quarantine_state(ticker)
    quarantined = terrain_quarantine_reason(ticker)
    failure = "" if (skipped or quarantined) else str(_terrain_refresh_last_error.get(
        ticker_storage_key(ticker) if ticker else "", "") or "")
    hard_quarantine = bool(q_entry.get("permanent"))
    if computed_ts_utc is None:
        return {"levels_stale": True, "levels_age_sec": None, "levels_refresh_active": refreshing,
                "levels_stale_reason": (
                    quarantined or skipped
                    or (f"no terrain snapshot has been computed yet — {failure}" if failure
                        else "no terrain snapshot has been computed yet")),
                "levels_paused_on_purpose": bool(skipped and not quarantined),
                "levels_quarantined": bool(quarantined),
                "levels_failing": bool(failure or hard_quarantine), **token}
    age = round(time.time() - float(computed_ts_utc), 1)
    # RC-165: judge age against the cycle the loop ACTUALLY delivers, not the nominal floor.
    # `TERRAIN_REFRESH_SEC` (60s) is a sleep floor between cycles; the delivered spacing is
    # whatever a full sweep costs, and MEASURED 2026-07-31 12:57 ET that was a 156s median on
    # SPY. With a fixed 180s threshold and a 60s sentence, a ticker 234s old — barely 1.5
    # cycles, entirely healthy — was reported to the operator as "the loop is inside its window
    # but not producing". That is RC-146's defect returning through a different door: a
    # correctly-working scheduler described as broken, this time because the yardstick was a
    # number the loop cannot reach rather than a silence nobody recorded.
    observed = _terrain_last_cycle_sec if _terrain_last_cycle_sec > 0 else TERRAIN_REFRESH_SEC
    expected = max(float(TERRAIN_REFRESH_SEC), float(observed))
    # Stale only past the FLOOR *and* past two delivered cycles — one missed sweep is normal
    # jitter, two is a real gap. The floor is retained so a fast loop cannot hide staleness.
    stale_after = max(float(TERRAIN_STALE_AFTER_SEC), 2.0 * expected)
    stale = age > stale_after
    reason = ""
    if stale:
        reason = (f"levels are {age:.0f}s old — {quarantined}" if quarantined else
                  f"levels are {age:.0f}s old — {skipped}" if skipped else
                  f"levels are {age:.0f}s old and every refresh since is failing — {failure}"
                  if failure else
                  f"levels are {age:.0f}s old; the terrain loop is not refreshing "
                  f"(outside the background-logging window, which closes at "
                  f"{LOGGER_BUFFER_MINS // 60:02d}:{LOGGER_BUFFER_MINS % 60:02d} ET)"
                  if not refreshing else
                  f"levels are {age:.0f}s old — over two full sweeps at the loop's DELIVERED "
                  f"cycle of {expected:.0f}s (nominal floor {TERRAIN_REFRESH_SEC:.0f}s), so this "
                  f"ticker is genuinely behind rather than merely between sweeps")
    return {"levels_stale": stale, "levels_age_sec": age,
            "levels_refresh_active": refreshing, "levels_stale_reason": reason,
            # RC-146: a stale panel must be able to distinguish "paused by design, resumes at a
            # known time" from "should be refreshing and is not". They are different operator
            # actions — wait, versus go find out what broke.
            "levels_paused_on_purpose": bool(stale and skipped and not quarantined),
            # RC-147: and the third state — actively FAILING — is a different action again
            # (the chain call is erroring, the levels will not come back on their own).
            "levels_failing": bool(stale and (failure or hard_quarantine)),
            # RC-148: the fourth — not even being REQUESTED. Distinct from failing: re-admission
            # is an operator act, not something the loop will do on its own.
            "levels_quarantined": bool(quarantined), **token}


#: RC-159 accrual cadence, stated rather than implied. Sentinels every minute (they ARE the
#: money path); the rest of the enrolled board every five. These are FLOORS between writes, not
#: a schedule — the terrain loop's own cadence still governs when a chain exists to bank.
ACCRUAL_MIN_INTERVAL_SENTINEL_SEC: float = 60.0
ACCRUAL_MIN_INTERVAL_OTHER_SEC: float = 300.0
ACCRUAL_SENTINELS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
_accrual_last_write: dict[str, float] = {}
_accrual_lock = threading.Lock()


def _accrue_chain_observation(tk: str, snap) -> None:
    """Bank one wide-chain per-strike observation. Never raises into the producer.

    A failure to ARCHIVE must never take down the loop that FEEDS the screen: collection is
    downstream of display, and losing a row is recoverable while losing the refresh is not.
    """
    try:
        _d, mins = gex_et_date_and_mins()
        if not gex_accrual_window(mins):
            return
        floor = (ACCRUAL_MIN_INTERVAL_SENTINEL_SEC if tk in ACCRUAL_SENTINELS
                 else ACCRUAL_MIN_INTERVAL_OTHER_SEC)
        now = time.time()
        with _accrual_lock:
            if now - _accrual_last_write.get(tk, 0.0) < floor:
                return
            _accrual_last_write[tk] = now
        rows = (getattr(snap, "per_strike", None) or {}).get("all") or []
        if not rows:
            return                      # absence stays absence; never bank an empty observation
        res = persist_chain_accrual(
            get_db().db_path, ticker=tk, per_strike_rows=rows,
            spot=getattr(snap, "spot", None), ts_utc=now)
        if res.get("status") != "written":
            log.debug("chain accrual %s: %s", tk, res)
    except Exception as e:
        log.warning("chain accrual failed for %s: %s", tk, e)


#: RC-161 — the morning contention guard's OWN start, decoupled from the archive write gate.
#: RC-159 widened `MORNING_START_MINS` 570 -> 555 so the once-daily archive could open at the
#: mandated 09:15 ET. That constant was ALSO the scheduler's sentinel-only filter, so the same
#: edit lengthened non-sentinel starvation by 15 minutes at precisely the moment the accrual
#: mandate begins. One constant was answering two different questions: "when may the archive
#: accept a first write" and "when is the chain gate too busy for a full sweep".
#: RC-165: the DELIVERED cycle time, published by `_terrain_loop` from the duration it already
#: measures. `TERRAIN_REFRESH_SEC` is a sleep FLOOR, not a promise — a full sweep over ~40
#: tickers on 2 workers against a 2-slot chain gate costs more than that, and judging freshness
#: against the floor reports healthy tickers as broken. 0.0 until the first cycle completes, in
#: which case readers fall back to the nominal floor.
_terrain_last_cycle_sec: float = 0.0

TERRAIN_CONTENTION_START_MINS: int = RTH_OPEN_MINS  # F09: cash open = time_et.RTH_OPEN_MINS
TERRAIN_CONTENTION_END_MINS: int = 600     # 10:00 ET


def terrain_cycle_tickers(
    all_tickers: list[str], mins: int, cycle_n: int
) -> tuple[list[str], list[str]]:
    """Which tickers this cycle refreshes, and which are DEFERRED to a later cycle.

    RC-161. The morning guard used to DROP every non-sentinel for a full half hour, which made
    the accrual mandate sentinel-only in [555, 600) — a universal claim that three tickers were
    meeting. Exclusion is now ROTATION: no enrolled ticker is ever removed from the board, it is
    scheduled later within the window.

    The rotation depth is derived from the accrual cadence, not guessed: a non-sentinel needs one
    refresh per ACCRUAL_MIN_INTERVAL_OTHER_SEC, so with a TERRAIN_REFRESH_SEC cycle it needs to
    appear once every `depth` cycles. Refreshing it more often would spend vendor budget on a
    write the accrual floor would throw away, so this rotation costs nothing the mandate does not
    already require — and it keeps the original budget intent (RC-146: do not pile a 54-ticker
    sweep on top of the money-path wide fetches at the open) by spreading, not by starving.

    Returns (refresh_now, deferred_this_cycle). Outside the contention window every ticker
    refreshes, exactly as before.
    """
    sentinels = [t for t in all_tickers if str(t).upper() in ACCRUAL_SENTINELS]
    others = [t for t in all_tickers if str(t).upper() not in ACCRUAL_SENTINELS]
    if not (TERRAIN_CONTENTION_START_MINS <= int(mins) <= TERRAIN_CONTENTION_END_MINS):
        return list(all_tickers), []
    # integer ceiling division — server.py has no module-level `math`, and adding an import for
    # one division would be a wider change than the fix
    _cyc = max(1, int(TERRAIN_REFRESH_SEC))
    depth = max(1, -(-int(ACCRUAL_MIN_INTERVAL_OTHER_SEC) // _cyc))
    idx = int(cycle_n) % depth
    slice_now = others[idx::depth]
    deferred = [t for t in others if t not in set(slice_now)]
    return sentinels + slice_now, deferred


def _terrain_refresh_one(ticker: str, priority: bool = False) -> str:
    """Fetch one chain and compute terrain into the cache. Never raises.

    RC-80 — THE SINGLE PRODUCER OF LEVELS. /api/terrain calls this on a cache miss rather than
    computing its own snapshot, because a second producer is a second faucet even when both write
    the same cache key. `priority` is True for that operator-facing miss (someone is waiting on
    the response) and False for the background rotation.
    """
    tk = ticker_storage_key(ticker)   # RC-126: SPX -> $SPX at the producer too — background
    if not tk:                        # callers (radar, enroll lists) don't pass the endpoints
        return "skip:empty"
    # RC-148: BEFORE the client, before the gate, before any vendor budget is spent. MEASURED
    # 2026-07-30 11:14 ET: RTY and XXT had each been re-requested every ~60 s all session for a
    # symbol Schwab answers with HTTP 400 — two permanently-wasted slots per minute out of a
    # 2-slot gate, against a book where $SPX could not get a chain through. Making that visible
    # (RC-147) was necessary and not sufficient: a control that reports the burn while the burn
    # continues has not fixed anything. A `priority` request (an operator is on the endpoint,
    # waiting) still honours the hold — the answer would be the same HTTP 400, just slower.
    if _terrain_quarantine_blocks(tk):
        return "skip:quarantined"
    try:
        client = get_client()
        want_capture, cap_key = _universal_capture_wanted(tk)
        _width = _terrain_strike_count(tk)
        if want_capture:
            _width = max(_width, GEX_FULL_CHAIN_STRIKE_COUNT)
        # RC-127: the FULL multi-year index book ($SPX: weeklies + quarterlies + LEAPS) can
        # exceed the vendor read timeout under live load — measured 2026-07-29: every $SPX
        # refresh died in ReadTimeout while the same fetch succeeded on a quiet box. The
        # ladder narrows the DATE WINDOW on timeout, one rung at a time, and STAMPS the
        # basis on the payload — degraded is visible, never silent. The operator-locked
        # full-chain basis stays the first attempt always; the rungs keep the weekly+monthly
        # book dealers actually hedge (120d, then 45d) rather than serving nothing.
        _chain_basis = "full"
        resp = None
        # RC-149: the ladder narrowed on a TIMEOUT EXCEPTION only. An over-budget index chain does
        # not time out — the vendor answers, with HTTP 502 — so `break` fired on the first rung and
        # the narrower rungs it exists to reach were never tried. MEASURED 2026-07-30: $SPX
        # returned HTTP 502 on every cycle for 2h10m while a ladder built for exactly this case
        # sat unused, because RC-127 was written from a day when the same over-width request
        # happened to die in ReadTimeout instead. One failure, two vendor expressions; the rung
        # must advance on the CONDITION (this window is too big), never on the expression of it.
        _OVER_BUDGET_CODES = (502, 413, 500, 504)
        for _basis, _to_days in (("full", None), ("dte<=120", 120), ("dte<=45", 45)):
            try:
                _to = ((datetime.now(timezone.utc) + timedelta(days=_to_days)).date()
                       if _to_days else None)
                resp, _gate_wait, _fetch_sec = _gated_safe_get_chain(
                    client, tk, strike_count=_width, priority=priority, to_date=_to,
                )
                _code = getattr(resp, "status_code", None)
                if _code in _OVER_BUDGET_CODES and _to_days != 45:
                    _terrain_refresh_last_error[tk] = (
                        f"chain fetch HTTP {_code} at basis {_basis!r} — trying a narrower window")
                    resp = None          # do NOT keep a failed response as the answer
                    continue
                _chain_basis = _basis
                break
            except Exception as _fe:
                if type(_fe).__name__ not in ("ReadTimeout", "ConnectTimeout", "TimeoutException"):
                    raise
                _terrain_refresh_last_error[tk] = (
                    f"chain fetch timeout at basis {_basis!r} — trying a narrower window")
                continue
        if resp is None or getattr(resp, "status_code", None) != 200:
            _code = getattr(resp, "status_code", None)
            _msg = f"chain fetch failed (HTTP {_code if _code is not None else 'timeout-at-all-rungs'})"
            _terrain_refresh_last_error[tk] = _msg
            # RC-148: classify so the response fits the cause. A 4xx is the vendor refusing THIS
            # SYMBOL and will refuse it identically forever; a timeout or 5xx is the venue being
            # busy and deserves a backoff, not a death sentence.
            _note_terrain_failure(tk, _msg, _classify_chain_failure(
                _code, "timeout-at-all-rungs" if resp is None else None))
            return "error:chain_http"
        c_json = resp.json()
        contracts = flatten_chain_contracts(c_json)
        # ONE spot authority (RC-14) — never the chain underlying on its own.
        spot, spot_source, spot_ts = resolve_spot(tk, chain_json=c_json)
        if want_capture and contracts:
            _persist_universal_capture(tk, cap_key, _width, contracts, spot)
        # Learn this instrument's geometry from the chain we just read, so the NEXT cycle
        # requests the width its +/-5% span actually needs instead of a tabulated guess.
        # RC-149: tell the learner WHICH basis produced this chain. A narrowed window under-counts
        # expiries, and that count is the denominator of the next request's width budget.
        _learn_strike_geometry(tk, contracts, spot,
                               date_window_narrowed=(_chain_basis != "full"))
        snap = compute_terrain(tk, contracts, spot)
        payload = snap.to_dict()
        payload["computed_ts_utc"] = time.time()
        # RC-82: stamp WHICH producer computed these levels. The radar merges this loop's
        # wide-chain output with stored-chain fallback rows and ranks them against each other;
        # wall selection depends on chain width (RC-80 measured an 11-point difference on SPY),
        # so an unlabelled merge sorts systematically-different numbers as if they were peers.
        payload["levels_source"] = LEVELS_SOURCE_WIDE_CHAIN
        # RC-127: which rung of the timeout ladder produced this book — 'full' is the
        # operator-locked basis; a narrower rung is visible degradation, never silent.
        payload["chain_basis"] = _chain_basis
        payload["spot_source"] = spot_source
        payload["spot_as_of_ts_utc"] = spot_ts
        _atr = _radar_atr(tk)
        payload["atr_daily"] = round(_atr.daily, 3) if _atr.daily else None
        payload["atr_15m"] = round(_atr.m15, 3) if _atr.m15 else None
        # RC-68: carry the LIVE per-strike map into the cache. to_dict() deliberately drops it
        # (hundreds of entries, far too heavy for every poll — same reason `profile` is dropped),
        # so /api/terrain/strikes reads it from the cached snapshot instead of the frozen morning
        # archive. Underscore-prefixed so it is unmistakably an internal cache field, not payload.
        # getattr, not attribute access: a snapshot without the map (older shape, or a stub) must
        # degrade to an EMPTY per-strike panel, never take down the whole terrain refresh.
        payload["_per_strike"] = getattr(snap, "per_strike", None) or {}
        with _terrain_cache_lock:
            _terrain_cache[tk] = payload
            _terrain_profile_cache[tk] = snap.profile
        # RC-159 (operator mandate 2026-07-30): ACCRUE the wide chain across
        # [09:15, 16:15] ET == [08:15, 15:15] CT. The chain is already fetched and the
        # per-strike map already computed above, so this costs ZERO additional vendor calls —
        # it persists what RC-68 kept in memory and then discarded every cycle. Sentinels bank
        # every minute; the rest of the board every five, because 40 tickers x 1/min of
        # per-strike JSON is hundreds of MB a day for data no surface reads at that resolution.
        _accrue_chain_observation(tk, snap)
        _log_flip_drift(tk, payload)
        _terrain_refresh_last_error.pop(tk, None)   # RC-126: success clears the sticky reason
        _note_terrain_success(tk)                   # RC-148: and the failure streak with it
        # RC-354: bank the day's ATM IV from the sigma band this refresh already computed
        # (one faucet, zero added vendor calls). UPSERT — last write of the session wins,
        # converging to the CLOSING IV that IV Rank/Percentile are defined against.
        try:
            _em_band = payload.get("implied_1d_move") or {}
            _iv = _em_band.get("iv_pct_atm")
            if _iv is not None and float(_iv) > 0:
                from time_et import now_et as _iv_now_et
                get_db().bank_daily_atm_iv(
                    tk, _iv_now_et().strftime("%Y-%m-%d"), float(_iv),
                    _em_band.get("dte_used"), _em_band.get("method"), time.time())
        except Exception as _iv_e:
            # institutional-swallow-ok: IV banking is an accrual side-effect — a write
            # failure is logged but must never take down the terrain refresh that feeds
            # the live desk. The gap simply shows as a missing day in iv_daily.
            log.warning("iv_daily banking failed for %s: %s", tk, _iv_e)
        # RC-359: bank today's per-strike OI (same exposures book) and compute the ΔOI
        # walls vs the prior banked session. Fail-closed: no prior session -> walls None
        # (the Console says 'banking'), never a fabricated diff.
        try:
            _oi_map = getattr(snap, "oi_by_strike", None) or {}
            if _oi_map:
                from math_exposure_core import compute_delta_oi_walls as _doiw
                from time_et import now_et as _oi_now_et
                _oi_date = _oi_now_et().strftime("%Y-%m-%d")
                get_db().bank_daily_strike_oi(
                    tk, _oi_date,
                    [(k, c, p) for k, (c, p) in _oi_map.items()], time.time())
                _prev_oi = get_db().prev_session_strike_oi(tk, _oi_date)
                _walls = _doiw(_oi_map, _prev_oi)
                with _terrain_cache_lock:
                    if tk in _terrain_cache:
                        _terrain_cache[tk]["delta_oi_walls"] = _walls
        except Exception as _oi_e:
            # institutional-swallow-ok: same accrual doctrine as iv_daily above — log,
            # never break the refresh; a missing day is a visible gap.
            log.warning("oi_daily banking failed for %s: %s", tk, _oi_e)
        return f"ok:{snap.confidence}"
    except Exception as e:
        # RC-126: DEBUG here meant $SPX failed silently for a full session while the operator
        # stared at 'not_ready' with no reason. The failure is WARNING-visible AND kept, so
        # the endpoint can tell the operator WHY instead of an eternal shrug.
        _terrain_refresh_last_error[tk] = f"{type(e).__name__}: {e}"
        # RC-148: an exception is never a symbol rejection (those arrive as a 4xx RESPONSE), so
        # it always classifies soft — backoff, never a permanent hold. A crash in our own code
        # must not be able to evict a real instrument from the board.
        _note_terrain_failure(tk, f"{type(e).__name__}: {e}", "soft")
        log.warning("terrain refresh %s failed: %s", tk, e, exc_info=True)
        return f"error:{type(e).__name__}"


def _terrain_loop() -> None:
    log.info("Terrain loop started (levels only, no model stack)")
    _terrain_cycle_n = 0        # RC-161: drives the morning rotation; monotonic per loop
    # Seed strike geometry BEFORE the first fetch cycle, in THIS thread. The seed
    # previously lived only in the prewarm worker, and _app_lifespan starts the loop
    # first -- so the first cycle raced the seed and could fetch every ticker at the
    # cold-start width (Cursor audit 2026-07-20: "race remains"). With the timeframe-
    # indexed read this is ~2 ms per ticker, so doing it inline is cheap and makes the
    # ordering deterministic instead of a race that usually goes our way.
    try:
        _seed_strike_geometry_from_storage()
    except Exception as e:
        log.warning("strike-geometry seed failed - first cycle uses cold-start width: %s", e)
    while _terrain_loop_running:
        cycle_start = time.monotonic()
        tickers: list[str] = []
        try:
            with _logger_lock:
                tickers = list(_logger_tickers)
        except Exception:
            tickers = list(CORE_TICKERS)
        # RC-146: a skip reason is only true for the cycle that recorded it. Cleared at the TOP
        # of every cycle so a pause that has ended cannot keep telling the operator to wait —
        # the branch below re-records it while, and only while, it still applies.
        _clear_terrain_skips()
        if tickers and _is_loggable_session():
            # During the morning wide-chain window (09:30-10:00 ET) SPY/QQQ/IWM already
            # take 100-strike gated fetches on the money path. Do not pile a full-universe
            # terrain sweep on top of that — refresh sentinels only until the window ends.
            # No try/except: the imports are module-level, so this path cannot fail at
            # runtime — a missing module stops the server at boot instead.
            _d, _mins = gex_et_date_and_mins()
            _terrain_cycle_n += 1
            _all_this_cycle = list(tickers)
            tickers, _dropped = terrain_cycle_tickers(_all_this_cycle, _mins, _terrain_cycle_n)
            if _dropped:
                # RC-146: SAY SO. This pause is deliberate and budget-justified, but it was a
                # silent list filter — nothing anywhere recorded that these tickers were skipped
                # on purpose. MEASURED 2026-07-30 09:43 ET: MSFT's per-strike panel served a
                # chain read at 09:29:52 (8 s before the bell, so session volume was 0 on all 44
                # strikes) under the message "no option volume yet this session", while
                # terrain_staleness could only offer "inside its window but not producing" — a
                # correct scheduler reported as a malfunction, and a pre-open corpse reported as
                # a market fact. The producer knows why it skipped; now the reader can ask.
                # RC-161: the wording follows the mechanism. This is no longer an exclusion for
                # the whole window — the ticker is DEFERRED to a later cycle inside it, and will
                # be refreshed within the accrual cadence rather than held until 10:00.
                _note_terrain_skip(
                    _dropped,
                    f"deferred to a later cycle inside the "
                    f"{TERRAIN_CONTENTION_START_MINS // 60:02d}:"
                    f"{TERRAIN_CONTENTION_START_MINS % 60:02d}-"
                    f"{TERRAIN_CONTENTION_END_MINS // 60:02d}:"
                    f"{TERRAIN_CONTENTION_END_MINS % 60:02d} ET window, while the morning "
                    f"wide-chain capture holds the chain slots — the enrolled board rotates at "
                    f"the accrual cadence ({ACCRUAL_MIN_INTERVAL_OTHER_SEC:.0f}s) instead of "
                    f"being held out, so this ticker still accrues inside the window",
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=TERRAIN_WORKERS) as pool:
                list(pool.map(_terrain_refresh_one, tickers))
        elapsed = time.monotonic() - cycle_start
        # RC-165: publish the DELIVERED cycle so freshness is judged against reality, not the
        # sleep floor. This number was already computed and only logged; readers had no access
        # to it, so terrain_staleness was left comparing against a cadence the loop never meets.
        globals()["_terrain_last_cycle_sec"] = float(elapsed)
        log.info("Terrain cycle: %d tickers in %.1fs", len(tickers), elapsed)
        sleep_end = time.monotonic() + max(0.0, TERRAIN_REFRESH_SEC - elapsed)
        while _terrain_loop_running and time.monotonic() < sleep_end:
            time.sleep(0.5)
    log.info("Terrain loop stopped")


def _terrain_prewarm_worker() -> None:
    """Warm the radar caches off the request path.

    MEASURED: a cold radar sweep costs ~22.5 s -- ~11.5 s computing ATR for 51 tickers and
    the rest reading 51 chain payloads out of a 23 GB snapshots table (RC-6). Paying that
    on the operator's first click leaves the scope empty long enough to look broken. The
    app already prewarms model bundles at boot for the same reason; this is the same move
    for terrain. Failures are logged and ignored: a cold cache is slow, never wrong.
    """
    try:
        _seed_strike_geometry_from_storage()
    except Exception as e:
        log.warning("strike-geometry seed failed (first cycle uses the cold-start width): %s", e)
    try:
        get_terrain_radar(limit=60)
        log.info("terrain radar prewarm complete: %d cached", terrain_cache_size())
    except Exception as e:
        log.warning("terrain radar prewarm failed (cache stays cold): %s", e)


def _seed_strike_geometry_from_storage() -> None:
    """Learn every ticker's strike spacing from its last stored chain, at boot.

    Without this the first cycle after a restart fetches TERRAIN_STRIKE_COUNT_COLD_START
    for every ticker -- too narrow for SPY/QQQ, so they would report
    LOW_CONFIDENCE_NARROW_CHAIN for one cycle on every restart. The geometry is already
    on disk; reading it once off the request path removes that window entirely.
    """
    try:
        with _logger_lock:
            tickers = list(_logger_tickers)
    except Exception:
        tickers = list(CORE_TICKERS)
    seeded = 0
    for tk in tickers:
        try:
            contracts, stored_spot = _latest_chain_and_spot(tk)
        except Exception:
            continue
        if _learn_strike_geometry(tk, contracts, stored_spot):
            seeded += 1
    log.info("strike geometry seeded for %d/%d tickers", seeded, len(tickers))


def start_terrain_prewarm() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    threading.Thread(target=_terrain_prewarm_worker, name="terrain-prewarm",
                     daemon=True).start()


#: RC-69 — BAR COLLECTION SERVICE. Collection is not a side-effect of display.
#: Bars used to be written only inside _fetch_state (the render path), so a ticker's chart
#: decayed to whenever it was last LOOKED AT. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar
#: lag 3.1 min vs QQQ 19.1 and IWM 19.1 (off screen) — while all three had ~1.0 min SNAPSHOT lag.
#: The quotes were current; the bars were not. 39.8% of all snapshots (122,795/308,796) carry
#: unfilled outcomes because fill_outcomes reads price_bars_1m for the forward price and the bars
#: were never written. This loop mirrors _terrain_loop (RC-1), which solved the identical problem
#: for levels: a cheap, always-on, viewport-independent path over the WHOLE enrolled universe.
BARS_REFRESH_SEC: float = 30.0
#: Quotes are far cheaper than chains; this pool is deliberately small so bar collection can never
#: contend with the operator card the way an unbounded sweep did at the open (TERRAIN_WORKERS=2).
#:
#: RC-243 (2026-08-04, PM GO executed post-RTH): sized DOWN 3 -> 2. The comment above reasons about
#: the API this loop READS FROM; the binding constraint is the seam it WRITES THROUGH. Every bar
#: upsert serializes on the single process-wide db._TIER1_SNAPSHOT_WRITE_LOCK, so workers past the
#: first cannot parallelise — they queue, and each extra contender lengthens the queue against a
#: file that reached 27.3 GB. MEASURED on the live console: threads ed_bars_0/1/2 took 426/407/405
#: lock waits (1,238 of them on upsert_1m_bars vs 449 on insert_snapshot), lifetime max wait
#: 180,340 ms, recent-window max 64,229 ms, with busy_retry_count 0 — the wait is on the Python
#: mutex, not SQLite's busy handler. Two workers keep the loop concurrent with the quote fetch
#: (which is the latency this pool exists to hide) while cutting write-seam contenders by a third.
BARS_WORKERS: int = 2
_bars_loop_running: bool = False
_bars_loop_thread: threading.Thread | None = None


def _persist_1m_bars(tk: str, bars) -> int:
    """THE single price_bars_1m writer in server.py (RC-69 single-faucet contract).

    Both producers of banked 1m bars — the live quote->accumulator collection service and
    the RC-484 enrollment history seed — persist through here, so the console has exactly
    ONE place that writes the canonical bar table. A second write call site is how
    collection once drifted into the render path; the audit counts the literal db-write
    call, so the invariant is that this function is its only occurrence. ``bars`` may be
    Candle objects (accumulator) or vendor candle dicts (history seed) — the db writer
    accepts both shapes."""
    return get_db().upsert_1m_bars(tk, bars)


def _bars_collect_one(tk: str) -> str:
    """Quote -> accumulator -> price_bars_1m for ONE ticker. Never raises."""
    try:
        client = get_client()
        q = _memoized_quote_response(tk, client=client)   # RC-112/W3-C8: one vendor faucet
        if q is None or getattr(q, "status_code", None) != 200:
            return "error:quote_http"
        node = q.json().get(tk) or {}
        fields = _parse_quote_node_session_fields(node)
        # RC-38 single source: a raw float() on a Schwab leaf silently admits NaN/inf, and a NaN
        # price would enter the bar series as a real value. One canonical reader; absence stays
        # absence.
        from numeric_contract import float_positive_or_none

        px = float_positive_or_none(fields.get("last"))
        if px is None:
            px = float_positive_or_none(fields.get("mark"))
        if px is None:
            return "skip:no_price"      # absence reads as absence — never a fabricated tick
        _candles_1m.tick(tk, px, time.time(), total_volume=fields.get("total_volume"))
        bars = _candles_1m.get_bars(tk)
        if not bars:
            return "ok:no_completed_bar"
        _persist_1m_bars(tk, bars)
        return "ok:persisted"
    except Exception as e:
        log.debug("bars collect %s: %s", tk, e)
        return f"error:{type(e).__name__}"


def _bars_loop() -> None:
    log.info("Bar collection loop started (quotes only, whole enrolled universe, viewport-independent)")
    while _bars_loop_running:
        cycle_start = time.monotonic()
        try:
            with _logger_lock:
                tickers = list(_logger_tickers)
        except Exception:
            tickers = list(CORE_TICKERS)
        # RC-48: only capturable sessions. A market-closed tick would persist a frozen bar.
        if tickers and _is_loggable_session():
            try:
                with ThreadPoolExecutor(max_workers=BARS_WORKERS,
                                        thread_name_prefix="ed_bars") as pool:
                    list(pool.map(_bars_collect_one, tickers))
            except Exception as e:
                log.warning("bars loop cycle failed: %s", e)
        sleep_end = time.monotonic() + max(1.0, BARS_REFRESH_SEC - (time.monotonic() - cycle_start))
        while _bars_loop_running and time.monotonic() < sleep_end:
            time.sleep(0.5)


def start_bars_loop() -> None:
    """Start bar collection. Refuses under pytest for the same reason as the terrain loop:
    a production thread inside the test process mutates shared state no test controls (RC-5)."""
    global _bars_loop_running, _bars_loop_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        log.debug("bars loop not started: running under pytest")
        return
    if _bars_loop_running:
        return
    _bars_loop_running = True
    _bars_loop_thread = threading.Thread(target=_bars_loop, name="bars-loop", daemon=True)
    _bars_loop_thread.start()


def stop_bars_loop() -> None:
    global _bars_loop_running
    _bars_loop_running = False


def start_terrain_loop() -> None:
    """Start the terrain collection thread.

    Refuses to start under pytest. A production background thread inside the test
    process fetches chains and consumes the shared 2-slot chain gate for the rest of
    the session, which silently breaks any test asserting on gate concurrency -- the
    same shared-mutable-state failure class as RC-5 in governance/root_cause_log.md.
    Tests that need the loop call _terrain_loop / _terrain_refresh_one directly.
    """
    global _terrain_loop_running, _terrain_loop_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        log.debug("terrain loop not started: running under pytest")
        return
    if _terrain_loop_running:
        return
    _terrain_loop_running = True
    _terrain_loop_thread = threading.Thread(target=_terrain_loop, name="terrain-loop", daemon=True)
    _terrain_loop_thread.start()


def stop_terrain_loop() -> None:
    global _terrain_loop_running
    _terrain_loop_running = False


_radar_fallback_cache: tuple[float, list[dict]] = (0.0, [])
RADAR_FALLBACK_TTL_SEC: float = 60.0


#: ATR is derived from ~100 sessions of 1-minute bars, so it moves slowly. Recomputing it
#: per radar poll would re-read the bar table for every ticker every 20 seconds.
_radar_atr_cache: dict[str, tuple[float, "AtrPair"]] = {}
RADAR_ATR_TTL_SEC: float = 900.0
#: Tickers whose ATR is being computed right now, so N concurrent requests trigger ONE
#: computation instead of N. Guards the cache fill, not the cache read.
_radar_atr_inflight: set[str] = set()
_radar_atr_lock = threading.Lock()
_radar_atr_refresh_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ed_atr_refresh")


#: RC-484 (2026-08-25): vendor daily-ATR fallback cache — one Schwab daily-candle fetch
#: per (ticker, ET date). Keyed by date so a fresh ticker's radar scale appears today
#: and refreshes tomorrow, without a per-cycle vendor call.
_radar_daily_atr_vendor_cache: dict[str, tuple[str, float | None]] = {}


def _radar_daily_atr_vendor_fallback(tk: str) -> float | None:
    """Daily ATR from Schwab DAILY candles when local 1m history spans <15 sessions
    (RC-484: chain walls exist from minute one but the radar ring stayed blind ~3 weeks
    for a fresh enrollee). Cached per ticker per ET date; fail-closed to None."""
    from time_et import now_et as _now_et

    day_key = _now_et().date().isoformat()
    hit = _radar_daily_atr_vendor_cache.get(tk)
    if hit and hit[0] == day_key:
        return hit[1]
    daily = None
    try:
        from schwab_client import safe_get_daily_price_history
        from terrain_atr import compute_atr_from_daily_candles

        resp = safe_get_daily_price_history(get_client(), tk, period_months=2)
        if resp is not None and getattr(resp, "status_code", None) == 200:
            daily = compute_atr_from_daily_candles((resp.json() or {}).get("candles") or [])
    except Exception as e:
        log.debug("radar daily-ATR vendor fallback failed for %s: %s", tk, e, exc_info=True)
    _radar_daily_atr_vendor_cache[tk] = (day_key, daily)
    return daily


def _radar_atr_compute_into_cache(tk: str) -> "AtrPair":
    """Compute one ticker's ATR and publish it. Always clears the in-flight marker."""
    try:
        pair = compute_atr_pair(str(get_db().db_path), tk)
    except Exception as e:
        log.debug("radar ATR failed for %s: %s", tk, e, exc_info=True)
        pair = AtrPair(None, None)
    if pair.daily is None:
        # RC-484: local bars cannot scale a fresh ticker for ~15 sessions; the vendor
        # daily series can, immediately. m15 stays local-only (it needs today's tape,
        # which the accumulator provides within minutes anyway).
        fallback_daily = _radar_daily_atr_vendor_fallback(tk)
        if fallback_daily is not None:
            pair = AtrPair(daily=fallback_daily, m15=pair.m15)
    with _radar_atr_lock:
        _radar_atr_cache[tk] = (time.time(), pair)
        _radar_atr_inflight.discard(tk)
    return pair


def _radar_atr(ticker: str | None) -> "AtrPair":
    """Cached ATR pair for a radar row. NEVER blocks on a recomputation. Never raises.

    OBSERVED 2026-07-20 (py-spy dump of the live console, PID 33156): eleven AnyIO worker
    threads were simultaneously inside compute_atr_pair via _radar_atr <- get_terrain_radar.

    `get_terrain_radar` is a SYNC endpoint, so FastAPI runs it in the AnyIO threadpool.
    The old body checked the cache and, on a miss, computed inline with NO single-flight
    guard -- so every concurrent request that missed recomputed ATR for all 51 tickers,
    each a 24,000-row read of price_bars_1m. That is a cache stampede, and because those
    are the SHARED threadpool workers, exhausting them blocks every other sync endpoint in
    the app. The operator saw the whole console hang, not just the terrain tab.

    Two changes make a request incapable of causing it:
      * SINGLE FLIGHT -- one computation per ticker at a time; concurrent callers do not
        queue behind it.
      * STALE WHILE REVALIDATE -- an expired entry is returned IMMEDIATELY and refreshed
        on a small dedicated pool. ATR over ~100 sessions does not change meaningfully in
        the seconds a refresh takes, so serving a slightly old value is correct, and it is
        strictly better than blocking a request thread to avoid it.

    Only a ticker with NO cached value at all can still compute inline; the boot prewarm
    fills those, and the dedicated pool bounds it at 2 threads regardless.
    """
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical — cache key AND compute_atr_pair DB query hit $-index bars
    if not tk:
        return AtrPair(None, None)
    now = time.time()
    with _radar_atr_lock:
        hit = _radar_atr_cache.get(tk)
        if hit is not None and (now - hit[0]) < RADAR_ATR_TTL_SEC:
            return hit[1]
        already_running = tk in _radar_atr_inflight
        if not already_running:
            _radar_atr_inflight.add(tk)
    if hit is not None:
        # STALE-WHILE-REVALIDATE: hand back the old value now, refresh off the request path.
        if not already_running:
            try:
                _radar_atr_refresh_pool.submit(_radar_atr_compute_into_cache, tk)
            except RuntimeError:  # pool shut down during teardown
                with _radar_atr_lock:
                    _radar_atr_inflight.discard(tk)
        return hit[1]
    if already_running:
        # First-ever value for this ticker and someone else is computing it. Report
        # absence rather than block a shared worker; ring_for() treats None as "no ring"
        # and the contact simply does not appear until the value lands.
        return AtrPair(None, None)
    return _radar_atr_compute_into_cache(tk)


#: WHICH producer computed a set of levels. The radar deliberately merges two of them, and an
#: unlabelled merge is how systematically-different numbers get ranked as peers (RC-82).
LEVELS_SOURCE_WIDE_CHAIN = "wide_chain_loop"      # _terrain_refresh_one, the single producer
LEVELS_SOURCE_STORED_CHAIN = "stored_chain_fallback"  # narrower; walls sit inward
LEVELS_SOURCE_UNKNOWN = "unknown"                 # unstamped reads as unknown, never as trusted


def _radar_row(t: dict, spot: float, atr: "AtrPair", status: str, level_name: str,
               level: float, gap: float | None, gap_atr: float | None,
               sort_key: float | None) -> dict:
    """One radar contact. `_sort` puts regime changes ahead of every wall."""
    return {
        "ticker": t.get("ticker"), "spot": spot, "regime": t.get("regime"),
        "posture": t.get("posture"), "status": status,
        "wall_name": level_name, "wall": level,
        "distance_pct": round(gap / spot * 100, 3) if gap is not None else None,
        "distance_atr": round(gap_atr, 3) if gap_atr is not None else None,
        "distance_atr_15m": (round(abs(gap) / atr.m15, 2)
                             if (atr.m15 and gap is not None) else None),
        "atr_daily": round(atr.daily, 3) if atr.daily else None,
        "atr_15m": round(atr.m15, 3) if atr.m15 else None,
        "call_wall": t.get("call_wall"), "put_wall": t.get("put_wall"),
        "gamma_flip": t.get("gamma_flip"), "confidence": t.get("confidence"),
        # RC-82: which producer computed the walls on THIS row. Absent stamp reads as unknown,
        # never as the trusted wide chain.
        "levels_source": t.get("levels_source") or LEVELS_SOURCE_UNKNOWN,
        "_sort": sort_key if sort_key is not None else (gap_atr if gap_atr is not None else 9e9),
    }


def _radar_contact(t: dict, spot: float, atr: "AtrPair") -> dict | None:
    """The one contact this ticker earns on the scope, or None if it stays invisible.

    A ticker about to cross its FLIP outranks every wall: a regime change alters what all
    the other levels mean, so it sorts first regardless of wall distance.
    """
    flip_raw = t.get("gamma_flip")
    if flip_raw is not None:
        flip = float(flip_raw)
        flip_atr = atr_distance(flip - spot, atr.daily)
        if flip_atr is not None and flip_atr <= RING_REGIME:
            return _radar_row(t, spot, atr, "REGIME CHANGE", "gamma flip", flip,
                              flip - spot, flip_atr, sort_key=-1.0)

    # RC-83 — a strike that is BOTH walls is not a directional level. When call_wall and put_wall
    # land on the same strike the market has put gamma on both sides of it: that is a magnet, not
    # a barrier. This used to resolve by tuple order — `abs(v - spot) < abs(...)` is a STRICT
    # less-than, so on an exact tie the put never displaced the call and every such row rendered
    # "CALL WALL". MEASURED 2026-07-27: 7 of 22 tracked rows, including NVDA 200/200 with spot at
    # 196.49. "Call wall" reads resistance above and "put wall" reads support below, so choosing
    # one by position in a tuple states a direction the data does not support.
    cw, pw = t.get("call_wall"), t.get("put_wall")
    if cw is not None and pw is not None and float(cw) == float(pw):
        best = ("gamma wall", float(cw))
    else:
        best = None
        for name, v in (("call wall", cw), ("put wall", pw)):
            if v is not None and (best is None or abs(v - spot) < abs(best[1] - spot)):
                best = (name, v)
    if best is None:
        return None
    name, level = best[0], float(best[1])
    gap = level - spot
    ring = ring_for(gap, atr.daily)
    if ring is None:
        return None                       # beyond the scope — deliberately invisible
    status = {"CONTACT": "AT WALL", "CLOSING": "APPROACHING", "SECTOR": "IN SECTOR"}[ring]
    return _radar_row(t, spot, atr, status, name, level, gap,
                      atr_distance(gap, atr.daily), sort_key=None)


def _terrain_snapshots_for_radar() -> list[dict]:
    """Terrain for every tracked ticker: live cache first, stored chains as fallback.

    Without the fallback the radar is blank until the first loop cycle completes, so a
    freshly started console shows an empty scope and looks broken. The fallback reads the
    most recent stored chain per ticker (read-only, no Schwab call) and is superseded the
    moment the loop caches a fresher one.
    """
    with _terrain_cache_lock:
        live_tickers = [t.get("ticker") for t in _terrain_cache.values() if t.get("ticker")]
    cached: dict[str, dict] = {}
    for tkr in live_tickers:
        snap = terrain_cache_get(tkr)
        if snap is not None and snap.get("ticker"):
            cached[snap["ticker"]] = snap

    # MERGE, never choose. Returning only the cache meant that as soon as the loop had
    # cached its first ticker the stored-chain fallback was skipped entirely, so a warming
    # console showed an almost-empty scope. Live cache wins per ticker; everything not yet
    # refreshed still appears from its most recent stored chain.
    # NEVER BLOCKS (2026-07-23 open, measured): the inline recompute cost 21.7 s while
    # the sentinel-only morning window kept ~48 tickers on the fallback, and the terrain
    # view polls every 20 s — the sweep monopolised the sync threadpool and the operator
    # felt the whole app slow (favicon no-op measured 1.4 s). Same stampede class as
    # _radar_atr, same cure: serve the LAST memo immediately and refresh it on a
    # single-flight background thread. A stale memo beats a 21 s stall — the live cache
    # wins per ticker, so staleness only touches tickers the loop has not refreshed.
    ts, memo = _radar_fallback_cache
    # Kick on never-initialized (ts<=0) or TTL expiry — NOT on empty memo.
    # A successful recompute can legitimately land [] (live cache covers all
    # tickers); treating that as uninitialized re-stampeded the 21s DB sweep.
    if ts <= 0 or (time.time() - ts) >= RADAR_FALLBACK_TTL_SEC:
        _kick_radar_fallback_refresh()
    return list(cached.values()) + [m for m in (memo or [])
                                    if m.get("ticker") not in cached]


_radar_fallback_flight_lock = threading.Lock()
_radar_fallback_inflight = False


def _kick_radar_fallback_refresh() -> None:
    """Start ONE background fallback recompute; concurrent callers never queue."""
    global _radar_fallback_inflight
    with _radar_fallback_flight_lock:
        if _radar_fallback_inflight:
            return
        _radar_fallback_inflight = True
    threading.Thread(target=_radar_fallback_refresh_worker,
                     name="radar-fallback-refresh", daemon=True).start()


def _radar_fallback_refresh_worker() -> None:
    global _radar_fallback_cache, _radar_fallback_inflight
    try:
        out = _radar_fallback_recompute()
        if out is not None:
            _radar_fallback_cache = (time.time(), out)
    except Exception as e:
        log.warning("radar fallback refresh failed: %s", e)
    finally:
        with _radar_fallback_flight_lock:
            _radar_fallback_inflight = False


def _radar_fallback_recompute() -> list[dict] | None:
    """The heavy sweep (runs OFF the request path). None = keep the previous memo —
    a DB hiccup must degrade to stale data, never wipe the scope."""
    with _terrain_cache_lock:
        cached = {t.get("ticker"): t for t in _terrain_cache.values() if t.get("ticker")}
    out: list[dict] = []
    try:
        db = get_db()
    except Exception as e:
        # Degrading to live-cache-only is correct, but doing it SILENTLY made a DB outage
        # indistinguishable from a quiet market on the radar (Cursor audit 2026-07-20:
        # empty return with no note). The scope keeps the stale memo; say so.
        log.warning("radar fallback: DB unavailable (%s: %s) — keeping previous memo",
                    type(e).__name__, e)
        return None
    import sqlite3 as _sq
    try:
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=30.0)
    except Exception as e:
        log.warning("radar fallback: DB open failed (%s: %s) — keeping previous memo",
                    type(e).__name__, e)
        return None
    try:
        con.row_factory = _sq.Row
        # Ticker LIST only — index-only aggregate, no blob touched. The per-ticker chain
        # read goes through _latest_chain_and_spot, NOT hand-rolled SQL here: the old
        # inline query took MAX(ts_utc) across BOTH timeframes, so a legacy 5m row could
        # shadow a newer-in-kind canonical 1m row (Bugbot 2026-07-20, confirmed).
        # _latest_chain_and_spot already encodes canonical-then-legacy, index-served.
        tickers = [r["ticker"] for r in con.execute(
            "SELECT DISTINCT ticker FROM snapshots "
            "WHERE option_chain_json IS NOT NULL AND spot IS NOT NULL"
        )]
    finally:
        con.close()
    for tk in tickers:
        if tk in cached:
            continue
        try:
            contracts, spot = _latest_chain_and_spot(tk)
            if not contracts or not spot:
                continue
            # NO live quote per ticker here. The radar sweeps ~51 symbols; calling
            # resolve_spot on each made 51 Schwab round-trips and the cold sweep
            # measured 40.5 s, so the first render always timed out and the scope
            # came up empty. `snapshots.spot` is itself persisted from
            # quote.lastPrice, i.e. a real trade, just older. Any ticker the terrain
            # loop has refreshed already wins via the cache above, so the live value
            # reaches the scope through the loop rather than through 51 fetches.
            snap = compute_terrain(tk, contracts, spot)
        except (ValueError, TypeError):
            continue
        # RC-82: a stored-chain row is PROVISIONAL — narrower than the loop's chain, so its
        # walls sit systematically inward. Labelled, not hidden: it cannot be removed (per-symbol
        # vendor calls measured a 40.5s cold sweep) and it must not masquerade as a loop row.
        out.append(snap.to_dict() | {"spot_source": SPOT_SOURCE_SNAPSHOT,
                                     "levels_source": LEVELS_SOURCE_STORED_CHAIN})
    return out


@app.get("/api/terrain/radar")
def get_terrain_radar(limit: int = Query(default=12, ge=1, le=60)):
    """Air-traffic radar: ONLY tickers currently in the operator's airspace.

    A 51-row grid is a list, not a radar. A controller tracks the aircraft that are
    actually in the sector, so a ticker earns a slot only by doing something:
      * sitting at a wall (within RADAR_NEAR_PCT)
      * having broken a wall with acceptance
      * an unambiguous regime with a wall within RADAR_WATCH_PCT
    Everything mid-box and quiet is deliberately invisible. Untrusted tickers are never
    ranked as if their levels were real -- they are reported separately as blind spots.
    """
    # Coerced so the handler is callable directly in tests, not only over HTTP
    # (FastAPI passes a Query object when the default is used outside a request).
    try:
        max_rows = int(limit)
    except (TypeError, ValueError):
        max_rows = 12

    rows: list[dict] = []
    blind = 0
    cached = _terrain_snapshots_for_radar()
    for t in cached:
        spot = t.get("spot")
        if t.get("confidence") != "TRUSTED" or not spot:
            blind += 1
            continue
        atr = _radar_atr(t.get("ticker"))
        if not atr.daily:
            blind += 1                    # no scale means no ring; never guess one
            continue
        contact = _radar_contact(t, spot, atr)
        if contact is not None:
            rows.append(contact)

    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        r.pop("_sort", None)
    return {"rows": rows[:max_rows], "tracked": len(rows), "scanned": len(cached),
            "blind_spots": blind, "near_pct": RADAR_NEAR_PCT, "watch_pct": RADAR_WATCH_PCT}


#: Gamma profiles for cached tickers, keyed by ticker. Kept beside the payload cache so a
#: cached payload can be re-priced without refetching the chain (RC-28).
_terrain_profile_cache: dict[str, list] = {}


def _reprice_cached_terrain(payload: dict, ticker: str) -> dict:
    """Serve CACHED LEVELS against a LIVE SPOT.

    RC-28: levels move slowly (a 60 s loop is right for them) but spot moves continuously,
    and spot was frozen into the cached payload. The card therefore ran up to 75 s behind
    the header -- observed 745.10 on the card against 744.88 live.

    Levels, walls and the profile stay as cached. Spot is re-resolved every request, and
    the REGIME is recomputed as the sign of the cached profile at that fresh spot, so the
    regime can never disagree with the price shown beside it.
    """
    spot, spot_source, spot_ts = resolve_spot(ticker)
    if spot is None:
        return payload

    out = dict(payload)
    out["spot"] = spot
    out["spot_source"] = spot_source
    out["spot_as_of_ts_utc"] = spot_ts
    # RC-130: wall geometry states are a function of SPOT, which was just re-resolved —
    # recomputed with the SAME producer definition (wall_geometry_state), and BEFORE the
    # profile early-return below, or a wall crossed intra-cycle would keep claiming the
    # containment the painted spot contradicts. Needs only spot + the cached walls.
    out["call_wall_state"] = wall_geometry_state(spot, payload.get("call_wall"), "call")
    out["put_wall_state"] = wall_geometry_state(spot, payload.get("put_wall"), "put")

    profile = _terrain_profile_cache.get(ticker_storage_key(ticker))  # RC-345/F25: read key matches canonical write (tk)
    if not profile:
        return out                      # levels stand; regime left as cached

    fresh_gamma = gamma_at_price(profile, spot)
    read = build_terrain_read(
        spot=spot,
        flip=payload.get("gamma_flip"),
        flip_confidence=payload.get("confidence") or "UNAVAILABLE",
        put_wall=payload.get("put_wall"),
        call_wall=payload.get("call_wall"),
        gamma_at_spot=fresh_gamma,
        ticker=ticker,   # SIGN-DEMOTION: single names get regime withheld, levels stand
    )
    out["regime"] = read.regime
    out["posture"] = read.posture
    out["headline"] = read.headline
    out["lines"] = read.lines
    # flip_diag travels WITH the regime it justified. The regime above was recomputed at
    # the fresh spot but flip_diag still carried the loop-time gamma_at_spot, so the
    # dealer tile printed a stale γ beside a live regime — the two could even disagree in
    # sign (Bugbot 2026-07-20, confirmed: the UI renders flip_diag.gamma_at_spot).
    out["flip_diag"] = {**(payload.get("flip_diag") or {}), "gamma_at_spot": fresh_gamma}
    # net_gex_at_spot IS gamma_at_spot (schema v2) — reprice both or the NET GEX chip
    # would show loop-time gamma beside a live-spot regime (same defect class as above).
    out["net_gex_at_spot"] = fresh_gamma
    # RC-91: the levels are cached and the spot is live, so the payload must say HOW OLD the
    # levels are rather than let a live price imply live structure. Every consumer gets the age,
    # a stale flag and the reason — absence of the flag is not permission to assume currency.
    out.update(terrain_staleness(payload.get("computed_ts_utc"), ticker))
    return out


@app.get("/api/diagnostics/terrain-producer")
def get_terrain_producer_diagnostics():
    """RC-148: the producer's own state, readable. Until this existed, `_terrain_refresh_last_error`
    was reachable only through one dead branch and the console had NO way to answer "why is this
    ticker not refreshing" — the question that cost a session on $SPX (RC-126) and another on
    RTY/XXT. Read-only, no Schwab call, no model stack."""
    with _terrain_skip_lock:
        skips = dict(_terrain_skipped_reason)
    with _terrain_quarantine_lock:
        quar = {k: dict(v) for k, v in _terrain_quarantine.items()}
        avoided = dict(_terrain_quarantine_skips)
    return JSONResponse({
        "last_error": dict(_terrain_refresh_last_error),
        "consecutive_failures": dict(_terrain_consecutive_fails),
        "quarantined": quar,
        "fetches_avoided_by_quarantine": avoided,
        "skipped_this_cycle": skips,
        "cache_size": terrain_cache_size(),
        "stale_after_sec": TERRAIN_STALE_AFTER_SEC,
        "refresh_sec": TERRAIN_REFRESH_SEC,
        "hard_fail_threshold": TERRAIN_QUARANTINE_HARD_FAILS,
        "ledger_path": str(TERRAIN_QUARANTINE_LEDGER),
    })


@app.post("/api/terrain/quarantine/release")
def post_terrain_quarantine_release(ticker: str = Query(...)):
    """Operator re-admission — the ONLY exit from a permanent hold, and it is logged.

    A quarantine with no way back is a deletion the operator never approved, so this exists in
    the same commit as the quarantine itself rather than as a follow-up.
    """
    return JSONResponse(terrain_quarantine_release(ticker))


# ── CR-03 screen 1 — per-strike gamma/volume bars for the histogram panel ────
# Feeds the /chart sidebar: today's per-strike dealer gamma + traded volume, plus
# the PRIOR wide capture's bars (the day-over-day migration ghosts), each in three
# expiry scopes (all / near<=7DTE / far). Sources are STORED chains only (wide
# morning capture preferred, live narrow chain as fallback) — read-only, no Schwab
# call, no model stack. Bar heights use the same exposure math as terrain.
@app.get("/api/terrain/strikes")
def get_terrain_strikes(ticker: str = Query(default=DEFAULT_TICKER)):
    from math_exposure_core import compute_exposures_by_strike as _cebs

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority

    def _per_strike(contracts: list, spot: float) -> dict:
        def _scope(cts: list) -> list:
            if not cts:
                return []
            exposures, _diag = _cebs(cts, spot=spot, require_oi=True)
            vol_by_k: dict[float, float] = {}
            # SINGLE SOURCE: totalVolume read through the canonical non-negative reader so
            # the REST aggregation drops NaN/±inf (raw float() used to admit them, poisoning
            # the sum) and reads 0/negatives identically to the exposure and order-flow paths.
            from numeric_contract import (
                float_finite_or_none as _fin,
                float_nonnegative_or_none as _vol_read,
            )
            for ct in cts:
                # single source: reject NaN strike (raw float() let a NaN become a dict key)
                k = _fin(ct.get("strikePrice"))
                if k is None:
                    continue
                v = _vol_read(ct.get("totalVolume"))
                if v:
                    vol_by_k[k] = vol_by_k.get(k, 0.0) + v
            out = []
            for k, b in exposures.items():
                g = bucket_metric(b, "net_gex_1pct")
                if g is None:
                    g = total_gamma_raw_at_strike(b)
                if g is None:
                    # RC-276: the second copy of the terrain_engine:202 bar RC-274 removed. A
                    # strike whose gamma resolves nowhere drew a bar at 0.0, indistinguishable
                    # from a strike measured at flat gamma on the surface used to read dealer
                    # positioning. Hidden here because server.py was allowlisted wholesale.
                    continue
                out.append([round(float(k), 2), round(float(g), 1),
                            int(vol_by_k.get(float(k), 0))])
            out.sort(key=lambda r: r[0])
            return out

        # Cursor-audit F8: unknown DTE must belong to NEITHER near nor far, not silently to far.
        # This endpoint carried its own near/far splitter with the old 999.0 sentinel — a duplicate
        # of the RC-290-fixed canonical _dte_of, which drops an unreadable DTE from BOTH sides. With
        # 999.0 a parse-failed 0-DTE was rendered in the prior-day MONTHLY+ (far) chip and omitted
        # from the ≤7DTE (near) chip. Use the ONE canonical splitter so the two can't diverge again.
        from terrain_engine import _dte_of
        near = [c for c in contracts if (d := _dte_of(c)) is not None and d <= 7]
        far = [c for c in contracts if (d := _dte_of(c)) is not None and d > 7]
        return {"all": _scope(contracts), "near": _scope(near), "far": _scope(far)}

    import sqlite3 as _sq
    today_src, prior_src = None, None
    today, prior = None, None
    spot_used = None
    today_age_sec = None
    # RC-146: bound BEFORE the try. `_snap` was assigned only inside the try body yet read
    # unconditionally in the response dict below — a raising terrain_cache_get took the
    # logged-and-swallowed path and then killed the endpoint with NameError on the way out,
    # turning a degraded panel into a 500. Absence must degrade, never explode.
    _snap: dict = {}
    # RC-68 SINGLE SOURCE FOR TODAY'S PER-STRIKE DATA: the LIVE terrain snapshot.
    # This panel used to render from option_chain_morning_full — MEASURED 2026-07-27 11:31 ET:
    # a 09:47 capture served at 11:31 understated session volume by 281 percent (1,095,874 shown
    # vs 4,176,672 live), ~500K missing on strike 740 alone, while the walls beside it moved on
    # the 60s loop. Two clocks, one story. The terrain loop already computes this exact map from
    # a live wide chain every cycle (terrain_engine._per_strike_map) — it was simply discarded.
    # Reading it here costs ZERO additional vendor calls. The archive is demoted to the
    # prior-day ghost, which is the one thing it is genuinely correct for.
    try:
        _snap = terrain_cache_get(tk) or {}
        _ps = _snap.get("_per_strike") or {}
        # RC-79: the terrain loop hands over FINISHED rows ({all,near,far} of
        # [strike, net_gex_1pct$, volume]) and they are served as-is. This previously rebuilt
        # synthetic contract dicts out of them and pushed those back through
        # compute_exposures_by_strike(require_oi=True) — the synthetics had no open interest, so
        # every row was rejected and the panel rendered EMPTY on a live, 7-second-old snapshot.
        # Data that is already computed is never recomputed from a lossy reconstruction of its
        # own inputs.
        if isinstance(_ps, dict) and _ps.get("all"):
            today = {k: (_ps.get(k) or []) for k in ("all", "near", "far")}
            spot_used = _snap.get("spot")
            _cts_utc = _snap.get("computed_ts_utc")
            today_age_sec = round(time.time() - float(_cts_utc), 1) if _cts_utc else None
            today_src = "terrain_live_cache"
    except Exception as e:
        log.debug("terrain strikes live read failed %s: %s", tk, e)
    # RC-162 — THE BANK'S FIRST READER. RC-159 built the accrual writer and RC-161 made the
    # producer universal, but nothing ever read it: with a cold, thin or stale live cache the
    # Chart painted NOTHING while this session's own gamma and volume sat in the DB. Banking is
    # not rendering, and a bank with no reader satisfies no operator intent.
    #
    # This is a DECLARED SECOND SOURCE, not a silent one, and it is bounded three ways so it
    # cannot become the RC-68 failure again (a 09:47 archive served at 11:31 under a live label):
    #   1. It serves only when the live snapshot is ABSENT or older than TERRAIN_STALE_AFTER_SEC.
    #   2. It serves only rows banked TODAY, and only if they are NEWER than what live has.
    #   3. It stamps its own source and age, so no consumer can mistake it for the live cache.
    # The prior-day morning_full archive is untouched and still serves ONLY the ghost — a bank
    # row is this session's own wide book, which is exactly what the archive is not.
    try:
        _live_ts = float(_snap.get("computed_ts_utc") or 0.0) if isinstance(_snap, dict) else 0.0  # silent-zero-ok: epoch-0 ancient sentinel — an undated snapshot must lose every freshness comparison
        _live_stale = (today is None) or (
            _live_ts <= 0.0) or ((time.time() - _live_ts) > TERRAIN_STALE_AFTER_SEC)
        if _live_stale:
            _bank = latest_accrual_rows(get_db().db_path, tk)
            if _bank and _bank.get("rows") and _bank["ts_utc"] > _live_ts:
                # `near`/`far` stay EMPTY on purpose: the bank holds the `all` scope only, and
                # inventing a DTE split it never measured would be a fabricated level. The scope
                # chips render empty and say so rather than showing `all` under another name.
                today = {"all": _bank["rows"], "near": [], "far": []}
                spot_used = _bank.get("spot") if _bank.get("spot") is not None else spot_used
                today_age_sec = round(time.time() - _bank["ts_utc"], 1)
                today_src = f"accrual_bank:{_bank['et_minute']:04d}et"
    except Exception as e:
        log.debug("terrain strikes accrual fallback failed %s: %s", tk, e)
    try:
        db = get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            rows = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 2", (tk,)).fetchall()
        finally:
            con.close()
        if rows:
            # ONE FAUCET FOR TODAY. The archive is NOT a fallback for today's per-strike data —
            # a fallback IS a second faucet, and it is exactly how a 09:47 capture ended up
            # rendering at 11:31 under the label "TODAY'S OPTION VOLUME". If the live terrain
            # snapshot is absent (cold start), `today` stays empty and today_source stays None so
            # the panel can say so: absence reads as absence, never as a stale substitute.
            # The archive serves ONLY the prior-day ghost, which is what it is genuinely correct
            # for — yesterday's close does not change.
            _prior_row = rows[1] if len(rows) > 1 else (rows[0] if today_src else None)
            if _prior_row is not None:
                d1, s1, c1 = _prior_row
                prior = _per_strike(json.loads(c1), float(s1))
                prior_src = f"wide_capture:{d1}"
    except Exception as e:
        log.debug("terrain strikes wide read failed %s: %s", tk, e)
    # The narrow-snapshot fallback is REMOVED (RC-68). It was the third faucet for one field:
    # the same panel could be fed by the live cache, the morning archive, or a stored narrow
    # chain — three different widths and three different clocks — with nothing on screen saying
    # which. If the live snapshot is absent the panel renders empty and says so.
    live_spot, live_src, _ts = resolve_spot(tk)
    _payload_spot = live_spot if live_spot is not None else spot_used

    # STRIP kill (one-faucet-closeout-v1): per-side GEX/OV sums are computed HERE, against
    # the exact spot this payload serves — the chart strip used to re-derive them in the
    # browser from the same rows (a second aggregation site that breaks silently when the
    # payload changes, and can straddle a different spot than the server's). One aggregator.
    def _side_sums(rows, s):
        from numeric_contract import float_finite_or_none, float_nonnegative_or_none
        if not rows or s is None:
            return None
        gb = ga = vb = va = 0.0
        for r in rows:
            # RC-276: the third copy. A row with no gamma used to add 0.0 to a side sum, which
            # is not neutral -- it drags the below/above comparison toward whichever side holds
            # the unmeasured strikes. Absence is dropped, not counted as flat.
            k = float_finite_or_none(r[0])
            g = float_finite_or_none(r[1])
            v = float_nonnegative_or_none(r[2])
            if k is None or g is None or v is None:
                continue
            if k < s:
                gb += g; vb += v
            elif k > s:
                ga += g; va += v
        return {"gex_below": round(gb, 1), "gex_above": round(ga, 1),
                "vol_below": int(vb), "vol_above": int(va),
                "spot_basis": float(s)}

    return JSONResponse({
        "ticker": tk, "spot": _payload_spot,
        "spot_source": live_src,
        "today": today or {"all": [], "near": [], "far": []},
        "today_side_sums": _side_sums((today or {}).get("all"), _payload_spot),
        "today_source": today_src,
        # RC-68: every consumer must be able to render an AGE on the panel's face. A number with
        # no age is how a 2.1-hour-old volume histogram sat under the label "TODAY'S OPTION VOLUME".
        "today_age_sec": today_age_sec,
        # RC-91: PROVENANCE IS NOT FRESHNESS. single_faucet_provenance passes here — one declared
        # source, no fallback — while the panel served levels 90 MINUTES old under a
        # `terrain_live_cache` label, because the terrain loop stops at the background-logging
        # window (16:30 ET) and nothing said so. Naming the right source proves only that the
        # right tap was opened, never that anything is still coming out of it.
        **terrain_staleness(_snap.get("computed_ts_utc") if isinstance(_snap, dict) else None, tk),
        "prior": prior or {"all": [], "near": [], "far": []},
        "prior_source": prior_src,
    })


# ── CR-03 pre-work (operator directive 2026-07-22 "we have plenty of time"):
# the chart-first screen v0 at /chart reads canonical 1m bars via this endpoint.
# Read-only, index-served (ticker+timeframe named — the idx_snap lesson applies to
# price_bars_1m equally), no Schwab call, no model stack. The WS transport replaces
# the page's polling when CR-CAP clears; this endpoint stays as the history hydrator.
@app.get("/api/bars1m")
def get_bars1m(ticker: str = Query(default=DEFAULT_TICKER),
               limit: int = Query(default=780, ge=1, le=3000)):
    """Canonical 1m bars, newest-last: [{t,o,h,l,c,v}] epoch-seconds bar starts."""
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    import sqlite3 as _sq
    try:
        db = get_db()
    except Exception:
        return JSONResponse({"ticker": tk, "bars": [], "error": "db unavailable"})
    con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
    try:
        rows = con.execute(
            "SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
            "WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT ?", (tk, int(limit)),
        ).fetchall()
    finally:
        con.close()
    bars = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
            for r in reversed(rows)]
    if not bars:
        # RC-484 (2026-08-25): a PREVIEWED (typed-in, not enrolled) ticker banks no
        # price_bars_1m — RC-69 made _bars_loop the only banked writer and it serves
        # enrolled tickers only — so its chart stayed empty all session (measured:
        # CRWV 2026-08-13, 127 snapshots, 0 bars). Fall through to the live
        # accumulator's COMPLETED bars, read-only and clearly tagged: display feed,
        # not a second banked producer (nothing is written).
        try:
            acc = _candles_1m.get_bars(tk)
        except Exception:
            acc = []
        bars = [{"t": float(b.ts), "o": float(b.open), "h": float(b.high),
                 "l": float(b.low), "c": float(b.close),
                 "v": (float(b.volume) if getattr(b, "volume", None) is not None else None)}
                for b in list(acc)[-int(limit):]]
        if bars:
            return JSONResponse({"ticker": tk, "bars": bars, "n": len(bars),
                                 "source": "live_accumulator_unbanked"})
    return JSONResponse({"ticker": tk, "bars": bars, "n": len(bars)})


#: RC-192/RC-199 FORCES (RE-LANDED 2026-08-02 after a worktree reset destroyed the
#: uncommitted originals — RC-210): ΔOI/DEX from the two newest banked wide chains; the
#: strip's GEX/OV rows come from the live strikes payload client-side; ΔOI and DEX need the
#: two newest wide captures, which only the server can read.
_FORCES_CACHE: dict = {}


@app.get("/api/forces")
def get_forces(ticker: str = Query(default=DEFAULT_TICKER)):
    """Forces rows from banked chains (RC-192/RC-199): per-strike OI delta FIRST, then
    bucketed by the NEWER capture's spot — bucketing each day by its own spot lets the moving
    boundary masquerade as OI change (measured inversion, OPEN_ITEMS DIR-01 method note).
    DEX is the newer capture's net_dex_dollars side sums. CHARM side sums (RC-199): operator
    2026-08-02 revoked the DIR-01(i) vote-lock — serve dealer-signed net_charm below/above
    spot from the newer banked chain via compute_charm_by_strike (same book as terrain walls).
    """
    import sqlite3 as _sq

    from math_exposure_core import compute_exposures_by_strike as _cebs
    from math_levels import compute_charm_by_strike as _ccs

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _FORCES_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False,
                     "reason": "fewer than 2 banked wide captures for this ticker"}
    try:
        db = get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            # RC-193: pull a wider candidate window and keep only trading ET dates —
            # ORDER BY et_date DESC LIMIT 2 silently preferred Sunday stock.
            cand = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 12", (tk,)).fetchall()
        finally:
            con.close()
        rows = [r for r in cand if r[0] and is_trading_day_et(str(r[0]))][:2]
        if len(rows) >= 2:
            (d1, s1, c1), (d0, s0, c0) = rows[0], rows[1]
            per1 = _cebs(json.loads(c1), spot=float(s1))[0]
            per0 = _cebs(json.loads(c0), spot=float(s0))[0]

            def _g(v: dict, k: str) -> float:
                x = v.get(k)
                return float(x) if x is not None else 0.0

            oi1 = {k: _g(v, "call_oi") + _g(v, "put_oi") for k, v in per1.items()}
            oi0 = {k: _g(v, "call_oi") + _g(v, "put_oi") for k, v in per0.items()}
            spot1 = float(s1)
            # RC-199: CHARM below/above from the NEWER banked wide chain (full book).
            # Dealer-signed net_charm = call_charm - put_charm per strike (RC-179).
            charm_below = charm_above = None
            charm_err = None
            try:
                chain1 = json.loads(c1)
                contracts = chain1 if isinstance(chain1, list) else (
                    (chain1.get("contracts") if isinstance(chain1, dict) else None) or [])
                per_ch = _ccs(contracts, spot1) if contracts else {}
                if not per_ch:
                    charm_err = "charm_by_strike empty on newer banked chain"
                else:
                    # RC-276: a strike with no net_charm is not a strike with zero charm.
                    # Summed as 0.0 it silently tilted the below/above pair the Exposure tab
                    # renders as dealer charm pressure.
                    from numeric_contract import float_finite_or_none as _fin_ch

                    def _ch(v: dict) -> float | None:
                        return _fin_ch(v.get("net_charm"))

                    charm_below = round(sum(
                        c for c in (_ch(v) for k, v in per_ch.items() if k < spot1)
                        if c is not None), 4)
                    charm_above = round(sum(
                        c for c in (_ch(v) for k, v in per_ch.items() if k > spot1)
                        if c is not None), 4)
            except Exception as _ce:
                charm_err = str(_ce)[:120]
            payload = {
                "ticker": tk, "available": True,
                "doi_below": round(sum(oi1[k] - oi0.get(k, 0.0) for k in oi1 if k < spot1)),
                "doi_above": round(sum(oi1[k] - oi0.get(k, 0.0) for k in oi1 if k > spot1)),
                "dex_below_dollars": round(sum(
                    _g(v, "net_dex_dollars") for k, v in per1.items() if k < spot1)),
                "dex_above_dollars": round(sum(
                    _g(v, "net_dex_dollars") for k, v in per1.items() if k > spot1)),
                "charm_below": charm_below,
                "charm_above": charm_above,
                # RC-288: DERIVED from the chain actually summed, not asserted. This was the
                # string literal "full_chain_banked", and static/exposure.html hardcodes the
                # same literal as its fallback — a label identical on both sides of the wire
                # can never disagree with itself, so it could not detect the one thing it
                # exists for. It matters because the repo computes charm two ways:
                # compute_net_charm on ONE selected expiry, compute_charm_by_strike on the
                # whole book. Counting the distinct expiries in `contracts` reports which
                # book these numbers came from and changes if the producer ever changes.
                "charm_book_scope": _charm_book_scope(contracts),
                "charm_error": charm_err,
                "newer_et_date": d1, "older_et_date": d0, "bucket_spot": spot1,
                "method": ("per-strike OI delta first, bucketed by the newer capture's spot; "
                           "DEX = net_dex_dollars side sums on the newer capture; "
                           "CHARM = dealer-signed net_charm side sums on the newer capture"),
            }
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"forces read failed: {e}"}
    _FORCES_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


#: RC-208 (re-landed with RC-210): the banked intraday accrual frames — the only per-minute
#: per-strike exposure time series the console has.
_EXPOSURE_FLOW_CACHE: dict = {}


@app.get("/api/exposure/flow")
def get_exposure_flow(ticker: str = Query(default=DEFAULT_TICKER)):
    """RC-208: serve option_chain_accrual frames for the latest banked session so the
    Exposure tab paints per-minute Pika/Barney structure, the intraday King path, and
    volume-delta bubbles at the minute they happened. per_strike_json served verbatim
    ([[strike, gex_dollars, session_volume], ...]; MEASURED: SPY 07-31 = 133 frames, ET
    minutes 556-975), spot-windowed ±5%. 5-min cache like /api/forces."""
    import sqlite3 as _sq

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _EXPOSURE_FLOW_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False,
                     "reason": "no banked accrual frames for this ticker"}
    try:
        db = get_db()
        frames: list[dict] = []
        latest = None
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            latest = con.execute(
                "SELECT MAX(et_date) FROM option_chain_accrual WHERE ticker=?", (tk,),
            ).fetchone()
            if latest and latest[0]:
                for ts, m, spot, psj in con.execute(
                        "SELECT ts_utc, et_minute, spot, per_strike_json "
                        "FROM option_chain_accrual WHERE ticker=? AND et_date=? "
                        "ORDER BY ts_utc", (tk, latest[0])):
                    try:
                        rows2 = json.loads(psj)
                    except (ValueError, TypeError):
                        continue
                    sp = float(spot) if spot is not None else None
                    if sp:
                        rows2 = [r for r in rows2 if abs(float(r[0]) - sp) <= sp * 0.05]
                    frames.append({"t": int(float(ts) // 60) * 60, "m": int(m),
                                   "spot": sp, "rows": rows2})
        finally:
            con.close()
        if frames:
            payload = {"ticker": tk, "available": True, "et_date": latest[0],
                       "n_frames": len(frames), "frames": frames,
                       "method": ("option_chain_accrual per_strike_json verbatim "
                                  "[[strike, gex_dollars, session_volume]...], "
                                  "spot-windowed ±5%, latest banked session")}
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"flow read failed: {e}"}
    _EXPOSURE_FLOW_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


#: RC-209: Split·DEX and multi-day structure were gated ONLY by missing endpoints.
_EXPOSURE_BOOK_CACHE: dict = {}
_EXPOSURE_HISTORY_CACHE: dict = {}


@app.get("/api/exposure/book")
def get_exposure_book(ticker: str = Query(default=DEFAULT_TICKER)):
    """RC-209: per-strike call/put GEX split + net DEX + volumes from the NEWEST banked wide
    chain — turns the Exposure tab's Split·DEX pill live. Vendor convention researched this
    turn (FlashAlpha): green = call side, red = put side. 5-min cache."""
    import sqlite3 as _sq

    from math_exposure_core import compute_exposures_by_strike as _cebs

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _EXPOSURE_BOOK_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False, "reason": "no banked wide chain"}
    try:
        db = get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            cand = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 12", (tk,)).fetchall()
        finally:
            con.close()
        rows_t = [r for r in cand if r[0] and is_trading_day_et(str(r[0]))][:1]
        if rows_t:
            d1, s1, c1 = rows_t[0]
            spot1 = float(s1)
            per, _diag = _cebs(json.loads(c1), spot=spot1)

            def _f(v: dict, k: str) -> float:
                x = v.get(k)
                return float(x) if x is not None else 0.0

            out_rows = [
                [k, round(_f(v, "call_gex_1pct")), round(_f(v, "put_gex_1pct")),
                 round(_f(v, "net_dex_dollars")),
                 round(_f(v, "call_volume")), round(_f(v, "put_volume"))]
                for k, v in sorted(per.items())
                if abs(float(k) - spot1) <= spot1 * 0.05
            ]
            payload = {"ticker": tk, "available": True, "et_date": d1, "spot": spot1,
                       "rows": out_rows,
                       "method": ("newest banked wide chain -> compute_exposures_by_strike; "
                                  "[strike, call_gex_1pct, put_gex_1pct, net_dex_dollars, "
                                  "call_volume, put_volume], ±5% spot window")}
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"book read failed: {e}"}
    _EXPOSURE_BOOK_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


@app.get("/api/exposure/history")
def get_exposure_history(ticker: str = Query(default=DEFAULT_TICKER)):
    """RC-209 (operator: multi-day scroll-back goes live): per-day per-strike net GEX$ for
    EVERY banked session, so scrolled-back days paint THEIR OWN structure under their own
    candles. ±5% of each day's spot; 10-min cache (the bank changes nightly)."""
    import sqlite3 as _sq

    from math_exposure_core import compute_exposures_by_strike as _cebs

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _EXPOSURE_HISTORY_CACHE.get(tk)
    if hit and now - hit[0] < 600.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False, "reason": "no banked sessions"}
    try:
        db = get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            cand = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date", (tk,)).fetchall()
        finally:
            con.close()
        days = []
        for d0, s0, c0 in cand:
            if not d0 or not is_trading_day_et(str(d0)):
                continue
            sp = float(s0)
            per, _diag = _cebs(json.loads(c0), spot=sp)
            rws = []
            for k, v in sorted(per.items()):
                if abs(float(k) - sp) > sp * 0.05:
                    continue
                x = v.get("net_gex_1pct")
                rws.append([k, round(float(x) if x is not None else 0.0)])
            if rws:
                days.append({"date": d0, "spot": sp, "rows": rws})
        if days:
            payload = {"ticker": tk, "available": True, "n_days": len(days), "days": days,
                       "method": ("every banked session -> compute_exposures_by_strike "
                                  "net_gex_1pct per strike, ±5% of that day's spot")}
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"history read failed: {e}"}
    _EXPOSURE_HISTORY_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


#: /api/spot upstream guard (operator 2026-07-23: "spot needs to be the fastest
#: polling"). Every resolve_spot is a REAL Schwab REST quote against the shared
#: ~120 req/min budget, so the endpoint caches per ticker for a short TTL — all
#: viewers share one upstream call per window and the client can poll at 1.5s.
_spot_poll_cache: dict[str, tuple[float, dict]] = {}
_spot_poll_lock = threading.Lock()
_spot_poll_inflight: dict[str, threading.Event] = {}
SPOT_POLL_TTL_SEC = 1.25


@app.get("/api/spot")
def get_spot(ticker: str = Query(default=DEFAULT_TICKER)):
    """Featherweight live spot for fast UI polling. The ONE price authority
    (resolve_spot, RC-14) behind a 1.25s per-ticker cache — no chain, no model
    stack, budget-bounded regardless of poll rate or viewer count.

    Concurrent cache misses single-flight: one Schwab quote; waiters join and
    reuse the TTL-fresh cached payload. Waiters never each call resolve_spot —
    on timeout they re-contend for leadership or serve the last cache entry
    (stale beats a quote stampede).
    """
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    deadline = time.time() + 10.0
    while True:
        now = time.time()
        with _spot_poll_lock:
            hit = _spot_poll_cache.get(tk)
            if hit and (now - hit[0]) < SPOT_POLL_TTL_SEC:
                return JSONResponse(hit[1])
            leader = tk not in _spot_poll_inflight
            if leader:
                _spot_poll_inflight[tk] = threading.Event()
            done = _spot_poll_inflight[tk]
        if not leader:
            remaining = deadline - time.time()
            if remaining <= 0:
                with _spot_poll_lock:
                    hit = _spot_poll_cache.get(tk)
                if hit:
                    return JSONResponse(hit[1])  # stale > stampede
                return JSONResponse(
                    {"ticker": tk, "spot": None, "spot_source": None,
                     "spot_as_of_ts_utc": None, "error": "spot_resolve_timeout"},
                    status_code=504,
                )
            done.wait(timeout=remaining)
            continue
        try:
            spot, source, ts = resolve_spot(tk)
            payload = {"ticker": tk, "spot": spot, "spot_source": source,
                       "spot_as_of_ts_utc": ts}
            with _spot_poll_lock:
                _spot_poll_cache[tk] = (time.time(), payload)
            return JSONResponse(payload)
        finally:
            with _spot_poll_lock:
                _spot_poll_inflight.pop(tk, None)
            done.set()


#: Trading days a daily scorecard may be old and still be quoted as a measurement. 1 = yesterday's
#: run is current, the day before that is not. DERIVED from the artifact's own cadence: the job is
#: daily, so anything older than one trading day means a run was MISSED, and a missed run is
#: exactly the condition under which the numbers must stop speaking.
SCORECARD_MAX_TRADING_DAY_AGE: int = 1


def scorecard_trading_day_age(generated_utc: object) -> int | None:
    """TRADING days between `generated_utc` (YYYY-MM-DD...) and today ET. None = unusable.

    Counts sessions, not hours, so a Friday scorecard reads as 1 day old on Monday rather than 3
    — the distinction between "the job did not run" and "the market was shut"."""
    # RC-98: CONVERT to ET, never slice the UTC string. `generated_utc[:10]` is a UTC calendar
    # date being compared against an ET calendar date, and after 20:00 ET the UTC date is already
    # TOMORROW — so a scorecard that had just run successfully scored `gen > today`, returned
    # None, and the API reported the FRESH artifact as unusable. MEASURED 2026-07-27 21:21 ET:
    # generated_utc 2026-07-28T00:30:00+00:00 (= 20:30 ET today) returned None instead of 0.
    # The session calendar is ET, so the timestamp must be moved onto that clock before any date
    # arithmetic — comparing two different clocks' dates is the defect, not the comparison.
    raw = str(generated_utc or "").strip()
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if len(raw) == 10:
            # A DATE-ONLY string carries no time and no zone — it is already a calendar date, so
            # converting it is the bug, not the fix. Treating "2026-07-24" as UTC midnight and
            # shifting to ET lands on 07-23 and ages the scorecard by an extra day. Caught by
            # tests/test_scorecard_stale_fails_closed_v1.py the moment the ET conversion landed.
            gen = ts.date()
        else:
            if ts.tzinfo is None:            # naive TIMESTAMPS are UTC by this repo's storage law
                ts = ts.replace(tzinfo=timezone.utc)
            gen = ts.astimezone(now_et().tzinfo).date()
    except (TypeError, ValueError):
        return None                          # unparseable age is NOT a fresh age
    today = now_et().date()
    if gen > today:
        return None                          # a future stamp is a broken clock, never "fresh"
    age, day = 0, gen
    while day < today:
        day += timedelta(days=1)
        if is_trading_day_et(day.isoformat()):
            age += 1
    return age


@app.get("/api/terrain/scorecard")
def get_terrain_scorecard():
    """Coach copy's measured numbers, LIVE from the latest daily scorecard.

    Operator 2026-07-23: "will the coach be updated as we self-test?" — the
    tooltip hold-rates were frozen into the page the night they were measured.
    Now the UI reads them from reports/terrain_backtest_latest.json, so every
    daily scorecard run updates what the coach is allowed to claim.

    FAIL-CLOSED ON STALE AS WELL AS ABSENT (RC-78). This previously refused a
    missing or malformed report and served an out-of-date one, while claiming in
    this very docstring that it "never" served a stale rate — and it was found
    serving hold-rates 111.6 hours (4.6 days) old under the coach's "Measured on
    our own history". Age is a precondition to serve, not a footnote to display:
    a date printed beside a number does not stop the number being read. Past the
    budget the figures are WITHHELD and the reason is published, so the coach
    says "measuring" instead of quoting a four-day-old measurement.

    The budget counts TRADING days, so Friday's scorecard is still current on
    Monday and stale on Tuesday. A wall-clock budget would condemn every
    scorecard each weekend and teach the operator to ignore the warning."""
    p = Path(APP_DIR) / "reports" / "terrain_backtest_latest.json"
    try:
        rep = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JSONResponse({})
    gen = rep.get("generated_utc")
    age = scorecard_trading_day_age(gen)
    if age is None or age > SCORECARD_MAX_TRADING_DAY_AGE:
        return JSONResponse({
            "generated_utc": gen,
            "stale": True,
            "age_trading_days": age,
            "max_trading_days": SCORECARD_MAX_TRADING_DAY_AGE,
            "stale_reason": (
                "scorecard has not been regenerated" if age is None
                else f"scorecard is {age} trading day(s) old"
            ),
        })
    return JSONResponse({
        "generated_utc": gen,
        "stale": False,
        "age_trading_days": age,
        "wall_hold_trusted": rep.get("wall_hold_trusted"),
        "weighting_scorecard": rep.get("weighting_scorecard"),
        "pdca": rep.get("pdca"),
    })


@app.get("/chart", response_class=HTMLResponse)
def chart_page():
    """CR-03 screen-1 v0 — chart-first view (candles + terrain bands + coach)."""
    p = static_dir / "chart.html"
    if not p.exists():
        return HTMLResponse("<p>static/chart.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/exposure", response_class=HTMLResponse)
def exposure_page():
    """RC-200 (re-landed with RC-210) — the Exposure Overlay tab: dealer positioning on
    price (operator #1 project, LIVE order 2026-08-02)."""
    p = static_dir / "exposure.html"
    if not p.exists():
        return HTMLResponse("<p>static/exposure.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/desk", response_class=HTMLResponse)
def desk_page():
    """Desk — research, candidates and book, replayable at an earlier knowledge time."""
    p = static_dir / "desk.html"
    if not p.exists():
        return HTMLResponse("<p>static/desk.html not found</p>", status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/api/desk/radar")
def get_desk_radar(as_of: float = Query(default=0.0), limit: int = Query(default=60)):
    """Candidate structure as it stood at `as_of` (epoch seconds; 0 = now).

    The whole point of the parameter is that moving it BACKWARD must remove rows. Filtering
    happens on knowledge time inside `desk_store.radar_rows`, never on event time — see the
    module docstring for the six-day FINRA lag that makes the distinction load-bearing.
    """
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    try:
        payload = desk_store.radar_rows(_desk_db, at, limit=max(1, min(int(limit), 500)))
    except Exception as e:  # absence reaches the surface as absence, never as zeros
        return {"as_of_utc": at, "rows": [], "n_total": 0, "error": f"{type(e).__name__}: {e}"}
    payload["server_now_utc"] = time.time()
    payload["is_replay"] = bool(as_of and as_of > 0)
    return payload


@app.get("/api/desk/dossier")
def get_desk_dossier(ticker: str = Query(default=DEFAULT_TICKER),
                     as_of: float = Query(default=0.0)):
    """One name's measured structure, as it stood at `as_of`."""
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    try:
        payload = desk_store.dossier(_desk_db, tk, at)
    except Exception as e:
        return {"subject": tk, "as_of_utc": at, "error": f"{type(e).__name__}: {e}",
                "missing": ["request failed"]}
    payload["server_now_utc"] = time.time()
    payload["is_replay"] = bool(as_of and as_of > 0)
    return payload


@app.get("/api/desk/evidence")
def get_desk_evidence(as_of: float = Query(default=0.0)):
    """The study scoreboard, read from reports/ rather than retyped.

    RC-172: honours the replay clock. A scoreboard generated after the instant being replayed is
    refused with its reason — on a tab whose premise is judging a screen by what was knowable,
    the surface that adjudicates claims cannot be the one reading the future.
    """
    import desk_store

    at = float(as_of) if as_of and as_of > 0 else time.time()
    try:
        return desk_store.evidence_rows(APP_DIR, at)
    except Exception as e:
        return {"rows": [], "empty_reason": f"{type(e).__name__}: {e}"}


@app.get("/api/desk/structure")
def get_desk_structure(
    ticker: str = Query(default=DEFAULT_TICKER),
    horizon_sessions: int = Query(default=5),
    long_strike: float = Query(default=0.0),
    short_strike: float = Query(default=0.0),
    long_price: float = Query(default=0.0),
    short_price: float = Query(default=0.0),
    contracts: int = Query(default=1),
    as_of: float = Query(default=0.0),
):
    """Deterministic payoff plus the PHYSICAL terminal distribution.

    The risk-neutral half is refused, not approximated — see `desk_store` for the reason, which
    is stated once so every surface refuses in the same words.
    """
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    out: dict = {"subject": tk, "as_of_utc": at}
    try:
        out["distribution"] = desk_store.terminal_distribution(
            _desk_db, tk, at, horizon_sessions=max(1, min(int(horizon_sessions), 60)))
    except Exception as e:
        out["distribution"] = {"available": False, "reason": f"{type(e).__name__}: {e}"}
    if long_strike > 0 and short_strike > 0:
        try:
            payoff = desk_store.vertical_spread(
                long_strike, short_strike, long_price, short_price,
                contracts=max(1, int(contracts)))
            out["payoff"] = payoff
            out["pop"] = desk_store.probability_of_profit(
                out["distribution"], payoff["breakeven"])
        except desk_store.DeskFactError as e:
            out["payoff_error"] = str(e)
    out["server_now_utc"] = time.time()
    return out


@app.get("/api/desk/brief")
def get_desk_brief(as_of: float = Query(default=0.0)):
    """The newest research brief we held at `as_of`, blocks aged against that instant."""
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    try:
        brief = desk_store.latest_brief(_desk_db, at)
    except Exception as e:
        return {"brief": None, "empty_reason": f"{type(e).__name__}: {e}"}
    if brief is None:
        return {"brief": None, "as_of_utc": at, "empty_reason": (
            "no research brief has been ingested — the Brief is a publish target and nothing "
            "has published to it yet")}
    return {"brief": brief, "as_of_utc": at, "empty_reason": None}


@app.post("/api/desk/materialize")
def post_desk_materialize():
    """Rebuild the fact store from tables this repo already fills. Idempotent.

    RC-172: this was a GET. A GET that rewrites tens of thousands of rows against a 25 GB
    database is fired by anything that speculatively fetches a URL — a link prefetch, a crawler,
    a browser preconnect, an operator refreshing a saved tab — and this database already has an
    open root cause for write contention (RC-166). POST is the fix: the method now matches what
    the call actually does.
    """
    import desk_store
    from db import DB_PATH as _desk_db

    t0 = time.time()
    try:
        res = desk_store.materialize_all(_desk_db)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "elapsed_sec": round(time.time() - t0, 2), "counts": res}


@app.get("/api/terrain")
def get_terrain(ticker: str = Query(default=DEFAULT_TICKER)):
    """Terrain payload — levels only, NO model stack.

    Deliberately separate from /api/state: that path runs the full pipeline (chain +
    greeks + xgb/lstm/transformer x 4 horizons + fusion + decision bundle), which is why
    background collection had to be throttled to keep it responsive. Terrain is ~5 ms of
    math on the same chain, so it never needs to compete for that budget.
    """
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    cached = terrain_cache_get(tk)
    if cached is None:
        # RC-80 — ONE PRODUCER OF LEVELS. This branch used to compute its own terrain from
        # _latest_chain_and_spot(), the most recent NARROW stored snapshot chain, while the
        # terrain loop computed from a WIDE chain sized by the resolve_chain_strike_count
        # faucet. Wall and flip selection depends on how much of the wing is present, so the
        # two disagreed: MEASURED 2026-07-27, /api/terrain?ticker=SPY alternated between
        # call=750/put=740/flip=746.59 and call=739/put=736/flip=739.80 within ten seconds
        # while spot moved four cents. The operator was reading two different sets of trade
        # levels from one endpoint. A second producer is a second faucet even when both write
        # the same cache key — the provenance audit only ever saw the read side.
        #
        # So on a miss the endpoint drives THE producer instead of imitating it, and if that
        # cannot deliver, the terrain reads UNAVAILABLE. Absence reads as absence; it never
        # reads as a narrower chain's answer.
        _terrain_refresh_one(tk, priority=True)
        cached = terrain_cache_get(tk)
    if cached is not None:
        # Cached LEVELS, live SPOT (RC-28). Never serve a frozen price beside a live header.
        return _reprice_cached_terrain(cached, tk)
    spot, spot_source, spot_ts = resolve_spot(tk)
    _why = _terrain_refresh_last_error.get(tk)
    return compute_terrain(tk, None, spot).to_dict() | {
        "spot_source": spot_source, "spot_as_of_ts_utc": spot_ts,
        # RC-126: not_ready carries its REASON when the producer has one — an eternal
        # unexplained shrug is how $SPX stayed dark for a session.
        "error": ("terrain_not_ready: no wide-chain snapshot yet for this ticker"
                  + (f" (last refresh error: {_why})" if _why else "")),
        # RC-151: and it carries the STRUCTURED state too. The cached branch above spreads
        # terrain_staleness while this one shipped only a prose `error` string, so
        # levels_failing / levels_quarantined were absent on /api/terrain for precisely the
        # tickers that were failing — MEASURED 2026-07-30 12:08 ET: RTY returned [] structured
        # fields while SPY returned all five. A flag a consumer must parse English to discover
        # is not a flag, and "absent" is indistinguishable from "healthy" to every reader.
        **terrain_staleness(None, tk),
    }


def _latest_chain_and_spot(ticker: str) -> tuple[list | None, float | None]:
    """Most recent stored chain + spot for a ticker (read-only, no Schwab call).

    MEASURED 2026-07-20 — this query was the single worst latency in the app.

    Without `timeframe` in the predicate the plan was:
        SEARCH snapshots USING INDEX idx_snap_ticker_tf_ts (ticker=?)
        USE TEMP B-TREE FOR ORDER BY
    SQLite could seek to the ticker but not use the index's ts_utc ordering, because
    timeframe sits between them in the composite key. Satisfying ORDER BY ts_utc DESC
    therefore meant reading EVERY row for that ticker -- 70,556 for SPY, each carrying an
    inline ~50 KB option_chain_json -- into a temp B-tree to sort, to return one row. It
    did not complete inside a 300 s timeout.

    Naming the timeframe closes the index gap:
        SEARCH snapshots USING INDEX idx_snap_ticker_tf_ts (ticker=? AND timeframe=?)
    No temp B-tree, no scan. MEASURED after: SPY 0.002 s, QQQ 0.005 s, NVDA 0.002 s.

    This is RC-6's root cause made concrete -- an archival blob sharing a table with the
    operational query surface is paid for on every read that touches the rows. The index
    fix removes the cost here; it does not remove the cause.
    """
    import sqlite3 as _sqlite3

    try:
        db = get_db()
    except Exception:
        return None, None
    con = _sqlite3.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=30.0)
    row = None
    try:
        con.row_factory = _sqlite3.Row
        # Canonical first, legacy second. Two index-served lookups are still orders of
        # magnitude cheaper than one unbounded scan, and a ticker whose history is all
        # legacy 5m rows still resolves instead of silently returning nothing.
        for tf in _STORED_CHAIN_TIMEFRAMES:
            row = con.execute(
                "SELECT spot, option_chain_json FROM snapshots "
                "WHERE ticker=? AND timeframe=? "
                "AND option_chain_json IS NOT NULL AND spot IS NOT NULL "
                "ORDER BY ts_utc DESC LIMIT 1",
                (ticker, tf),
            ).fetchone()
            if row:
                break
    finally:
        con.close()
    if not row:
        return None, None
    try:
        return json.loads(row["option_chain_json"]), float(row["spot"])
    except (ValueError, TypeError):
        return None, None


@app.get("/api/analytics/light")
async def get_analytics_light(
    ticker: str = Query(default=DEFAULT_TICKER),
    expiry: Optional[str] = Query(default=None),
    force: bool = Query(
        default=False,
        description="Explicit full L1 recompute (default: read authoritative _l1_snapshot_cache + L0 overlay).",
    ),
):
    """
    L1 context plane — reads authoritative _l1_snapshot_cache by default; full compute on cold miss,
    serve-age expiry, or force=true. Materiality-gated rebuilds run on quote/L2 hooks only.
    """
    t = ticker.upper().strip()
    from planes.l1_events import notify_ticker_expiry_changed

    # RC-166: L1 assembly runs on ed_l1_light (not ed_route_offload). logging_universe
    # touch is fire-and-forget on the route pool so a SQLITE wait cannot hold the L1
    # response (L1 itself is memory-only; _pipeline_ms never included that wait).
    route_t0 = time.perf_counter()
    submit_ts = time.perf_counter()
    try:
        _get_route_offload_executor().submit(_touch_tracked_ticker_view, t)
    except Exception:
        log.debug("analytics_light: touch_seen submit failed ticker=%s", t, exc_info=True)

    def _build():
        return notify_ticker_expiry_changed(t, expiry, force=force)

    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_l1_light_executor(), _build)
    after_exec = time.perf_counter()
    await_ms = (after_exec - submit_ts) * 1000.0
    total_ms = (after_exec - route_t0) * 1000.0
    log.info(
        "analytics_light_route_done ticker=%s await_executor_ms=%.2f route_total_ms=%.2f "
        "pipeline_ms=%s",
        t,
        await_ms,
        total_ms,
        (payload or {}).get("_pipeline_ms") if isinstance(payload, dict) else None,
    )
    # Shallow copy so route timing fields never mutate the authoritative L1 cache object.
    out = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(out, dict):
        out["_route_await_executor_ms"] = round(await_ms, 2)
        out["_route_total_ms"] = round(total_ms, 2)
    return JSONResponse(out)


@app.get("/api/analytics/light/stream")
async def get_analytics_light_stream(
    request: Request,
    ticker: str = Query(default=DEFAULT_TICKER),
    expiry: Optional[str] = Query(default=None),
):
    """
    Server-Sent Events for L1: pushes when _project_l1 completes for this scope (generation advances).
    Payload matches GET /api/analytics/light (uses _l1_http_get_projection — no duplicate compute path).
    """
    t = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: an L1 SSE subscription is a VIEW (chart open), not a track —
    # touch last-seen only. Fire-and-forget (RC-166): do not block SSE setup on SQLite.
    try:
        _get_route_offload_executor().submit(_touch_tracked_ticker_view, t)
    except Exception:
        log.debug("analytics_light_stream: touch_seen submit failed ticker=%s", t, exc_info=True)
    exp_key = expiry if expiry is not None else "__auto__"
    key = (t, exp_key)
    q, rs_key = _l1_light_sse_try_reserve(request, key)

    async def event_generator():
        yield ": ok\n\n"
        try:
            while True:
                try:
                    env = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"event: l1_projection\ndata: {json.dumps(env, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _l1_light_sse_release(q, key, rs_key)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/analytics/state")
async def get_analytics_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: Optional[str] = Query(default=None),
    expiry: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
):
    """
    Tier C — full analytical pipeline (_fetch_state): chain, exposures, fusion, DB, news, model health.
    Not required for first paint; cache-first when TTL allows.
    """
    t = _resolve_ticker_param(ticker, symbol)
    # SWITCH-LATENCY FIX: async route — the handler is stale-while-refresh (light), but it
    # calls _register_tracked_ticker (SQLite write) on entry, which blocks the event loop
    # during DB contention. Offload it; the heavy recompute it schedules already runs on
    # its own thread pool.
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _get_fast_quote_executor(),
        lambda: _tier_c_analytics_json_response(t, expiry, force, "rest_analytics"),
    )


@app.post("/api/analytics/warm")
async def post_analytics_warm(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: Optional[str] = Query(default=None),
    expiry: Optional[str] = Query(default=None),
):
    """
    UI-MAXIMIZE — schedule Tier C background recompute + ML artifact prewarm (non-blocking).
    Client fires on ticker switch / typeahead; does not await _fetch_state completion.
    """
    t = _resolve_ticker_param(ticker, symbol)

    def _warm():
        _touch_tracked_ticker_view(t)
        return _schedule_analytics_warm(t, expiry, "client_warm_post", prewarm_models=True)

    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_route_offload_executor(), _warm)
    return JSONResponse(payload)


@app.get("/api/state")
# SWITCH-LATENCY FIX: sync def → Starlette runs it in its worker threadpool, off the
# event loop (this handler does blocking Tier C work and no await).
def get_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    symbol: Optional[str] = Query(default=None),
    expiry: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
):
    """
    Deprecated alias for GET /api/analytics/state (Tier C full bundle).
    Prefer /api/live/state + /api/analytics/state for real-time UX.
    Query ``ticker=`` (preferred) or ``symbol=`` (alias).
    """
    return _tier_c_analytics_json_response(
        _resolve_ticker_param(ticker, symbol), expiry, force, update_source="rest_poll_legacy"
    )


@app.get("/api/live/plane")
def api_live_plane(ticker: str = Query(default=DEFAULT_TICKER)):
    """Diagnostics: Layer A row + streaming health — no Schwab REST quote call."""
    t = (ticker or DEFAULT_TICKER).upper().strip()
    row = _lmp.get_quote(t)
    base = dict(row) if row else {}
    try:
        from order_flow_streaming import get_streaming_diagnostics, get_plane_authority_for_ticker

        base.update(get_streaming_diagnostics())
        base["plane_quote_authority"] = get_plane_authority_for_ticker(t)
    except Exception:
        base["plane_quote_authority"] = "rest_only"
    base["streaming_fallback_explicit"] = base.get("plane_quote_authority") == "rest_fallback_explicit"
    try:
        from order_flow_live_state import get_stream_chg_pct, get_top_of_book_sizes

        _scp = get_stream_chg_pct(t)
        if _scp is not None:
            base["stream_chg_pct"] = _scp
        base.update(get_top_of_book_sizes(t))
    except Exception as e:
        log.warning(
            "order_flow_live_state merge failed for /api/state ticker=%s: %s",
            t,
            e,
            exc_info=True,
        )
    return JSONResponse(base)


@app.get("/api/order-flow/microstructure")
def api_order_flow_microstructure(ticker: str = Query(default=DEFAULT_TICKER)):
    """Canonical L2 book microstructure (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1): top-of-book,
    spread, microprice, Top 1/3/5 depth totals + imbalance, depth-pressure curve, book slope,
    liquidity concentration, wall_candidates, and ages — every field classified
    NATIVE/DERIVED/PROXY. SERIALIZER, not a second producer: it delegates to the ONE canonical
    order_flow_engine.compute_book_microstructure keyed by this ticker, which carries the
    engine's already-computed structural state for the current book (memoized per ticker +
    BOOK_TIME) rather than re-walking the raw book. No Schwab REST quote call; the client
    renders, never recomputes."""
    t = (ticker or DEFAULT_TICKER).upper().strip()
    # VIEW endpoint: touch last-seen only, never enroll (RC-160 ticker-scope discipline).
    _touch_tracked_ticker_view(t)
    data: dict = {}
    try:
        from order_flow_live_state import get_content_for_symbol
        _content = get_content_for_symbol(t)
        if _content:
            data["content"] = _content
    except Exception as e:  # streaming state optional — fail closed to 'no_book', never fabricate
        log.debug("microstructure content build failed for %s: %s", t, e)
    _row = _lmp.get_quote(t)
    if _row and _row.get("exchange_quote_ts") is not None:
        data["exchange_quote_ts"] = _row.get("exchange_quote_ts")
    from order_flow_engine import compute_book_microstructure
    # ticker=t → serialize the canonical state carried per (ticker, BOOK_TIME); no independent recompute.
    payload = compute_book_microstructure(data, ticker=t)
    payload["ticker"] = t
    return JSONResponse(payload)


@app.post("/api/streaming/active-ticker")
async def post_streaming_active_ticker(payload: dict = Body(default={})):
    """Subscribe Schwab L1+book to the active UI ticker (dynamic; replaces prior subscription)."""
    t = (payload.get("ticker") or DEFAULT_TICKER)
    t = str(t).upper().strip()
    # SWITCH-LATENCY FIX (critical): set_streaming_active_ticker blocks on fut.result(timeout=30)
    # while it does 6 websocket re-subscribe round-trips, and this endpoint fires on EVERY ticker
    # switch. Running it on the async event loop froze the entire UI (all SSE/requests) for up to
    # 30s per switch. Offload the whole blocking block to the thread pool; the loop stays free.
    def _apply():
        from order_flow_streaming import set_streaming_active_ticker, get_streaming_diagnostics, get_plane_authority_for_ticker

        ok = set_streaming_active_ticker(t)
        _lmp.reset_sse_push_cursor(t)
        diag = get_streaming_diagnostics()
        return {"ok": ok, "ticker": t, **diag, "plane_quote_authority": get_plane_authority_for_ticker(t)}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "ticker": t}, status_code=500)
    return JSONResponse(out)


def _l1_sse_light_diag_payload() -> dict[str, Any]:
    """Authoritative counters + derived health hints for operators (see l1_sse_field_semantics)."""
    now_m = time.monotonic()
    drop_m = float(_l1_sse_last_drop_mono or 0.0)  # silent-zero-ok: 0 means "no drop ever recorded" and every consumer below gates on drop_m > 0.0 before deriving an age
    drop_age_sec = float(now_m - drop_m) if drop_m > 0.0 else None
    out: dict[str, Any] = {**dict(_l1_sse_diag)}
    out["l1_sse_backpressure_policy"] = (
        "thread_queue_evict_oldest_on_full; per_client_asyncio_evict_oldest_on_full"
    )
    out["l1_sse_thread_queue_fairness_policy"] = (
        "global_fifo_evict_oldest_under_saturation: newest notify always enqueueable; older pending "
        "notify for another scope may be dropped (see _l1_put_thread_queue_notify docstring)."
    )
    out["l1_sse_last_drop_age_sec"] = drop_age_sec
    out["l1_sse_saturated_recent"] = bool(drop_m > 0.0 and drop_age_sec is not None and drop_age_sec < 60.0)
    viol = int(out.get("l1_payload_identity_violation", 0) or 0)  # silent-zero-ok: a violation COUNTER — absent means none were recorded, which is what 0 states
    if viol > 0:
        out["l1_sse_health_hint"] = "identity_violation"
    elif out["l1_sse_saturated_recent"]:
        out["l1_sse_health_hint"] = "drops_recent_latest_state_preserved"
    else:
        out["l1_sse_health_hint"] = "healthy"
    out["l1_light_sse_limit_max_total"] = MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL
    out["l1_light_sse_limit_max_per_scope"] = MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE
    out["l1_light_sse_connections_by_scope"] = _l1_light_sse_count_by_scope()
    out["l1_sse_field_semantics"] = {
        "l1_light_sse_connections": "authoritative_counter",
        "l1_light_sse_events_queued": "authoritative_counter",
        "l1_light_sse_events_delivered": "authoritative_counter",
        "l1_light_sse_events_dropped_full": "authoritative_edge_case_queue_race",
        "l1_light_sse_thread_queue_evicted_oldest": "authoritative_counter",
        "l1_light_sse_client_queue_evicted_oldest": "authoritative_counter",
        "l1_light_sse_events_throttled": "authoritative_counter",
        "l1_payload_identity_violation": "authoritative_counter",
        "l1_light_sse_connections_peak": "authoritative_peak_since_process_start",
        "l1_light_sse_duplicate_scope_same_client_warn_total": "authoritative_counter",
        "l1_light_sse_rejected_total": "authoritative_counter",
        "l1_light_sse_limit_max_total": "static_policy_constant",
        "l1_light_sse_limit_max_per_scope": "static_policy_constant",
        "l1_light_sse_connections_by_scope": "derived_snapshot",
        "l1_sse_backpressure_policy": "static_documentation",
        "l1_sse_thread_queue_fairness_policy": "static_documentation",
        "l1_sse_last_drop_age_sec": "derived_seconds_since_last_drop_process_monotonic_or_null",
        "l1_sse_saturated_recent": "derived_bool_60s_window_monotonic",
        "l1_sse_health_hint": "derived_enum",
    }
    return out


@app.get("/api/diagnostics/l1")
def get_l1_diagnostics():
    """
    L1 operational metrics: build counts, reason histogram, cache hits/skips, policy constants.
    For live validation and tuning materiality / TTL without log scraping.
    """
    from planes.l1_runtime import (
        L1_CACHE_ENTRY_TTL_SEC,
        L1_HTTP_SERVE_MAX_AGE_SEC,
        L1_MAX_CACHE_SCOPES,
        L1_OF_MIN_COMPUTE_INTERVAL_SEC,
        L1_OF_PROBE_FORCE_REFRESH_SEC,
        L1_ORDER_FLOW_STALE_SEC,
    )
    from planes.l1_cache_lifecycle import l1_cache_invariants
    from planes.l1_operational import build_l1_operational_assessment

    bt = int(_l1_instrumentation["l1_build_total"])
    # RC-291: divide by builds whose timing was MEASURED, not by all builds. Dividing a sum
    # that excludes unmeasured builds by a count that includes them understates the average
    # and can hold it under the warn threshold — measured at 24.7 ms for a true 26.0 ms.
    bt_measured = int(_l1_instrumentation["l1_build_ms_measured"])
    avg_ms = float(_l1_instrumentation["l1_build_ms_sum"]) / max(1, bt_measured)
    reasons = {str(k): int(v) for k, v in _l1_instrumentation["l1_build_by_reason"].items()}
    uptime_sec = max(0.0, time.monotonic() - _l1_diag_start_mono)
    operational = build_l1_operational_assessment(
        # RC-293: the TRUE build count drives the rate alarm; the TIMED count drives the
        # latency average. RC-291 passed bt_measured as l1_build_total, which fixed the
        # average and made builds_per_min report timed builds — a true 500/min read as
        # 100/min and graded healthy. Two questions, two inputs.
        l1_build_total=bt,
        timing_sample_count=bt_measured,
        l1_build_ms_sum=float(_l1_instrumentation["l1_build_ms_sum"]),
        reasons=reasons,
        l1_http_cache_hit_total=int(_l1_instrumentation["l1_http_cache_hit_total"]),
        l1_quote_material_skip_total=int(_l1_instrumentation["l1_quote_material_skip_total"]),
        l1_cache_eviction_total=int(_l1_instrumentation["l1_cache_eviction_total"]),
        l1_of_quote_hook_engine_total=int(_l1_instrumentation["l1_of_quote_hook_engine_total"]),
        l1_of_quote_hook_reuse_total=int(_l1_instrumentation["l1_of_quote_hook_reuse_total"]),
        cache_scope_count=len(_l1_snapshot_cache),
        l1_max_cache_scopes=L1_MAX_CACHE_SCOPES,
        uptime_sec=uptime_sec,
    )
    sample = []
    for k, v in list(_l1_snapshot_cache.items())[:64]:
        inst = v.get("l1_instrumentation") or {}
        sample.append(
            {
                "scope": {"ticker": k[0], "expiry": k[1]},
                "as_of_ts": v.get("as_of_ts"),
                "l1_build_reason_last": inst.get("l1_build_reason"),
            }
        )
    now_diag = time.time()
    from planes.l1_thresholds import resolve_l1_materiality_engine

    row_spy = _lmp.get_quote("SPY") or {}
    ctx_spy = _l1_adaptive_materiality_context("SPY", row_spy, now_diag)
    res_spy = resolve_l1_materiality_engine("SPY", context=ctx_spy)
    row_penny = {"spot": 4.5, "spread": 0.002}
    ctx_penny = _l1_adaptive_materiality_context("XYZ", row_penny, now_diag)
    res_penny = resolve_l1_materiality_engine("XYZ", context=ctx_penny)
    l1_adaptive_materiality = {
        "l1_materiality_engine_schema_version": 1,
        "sample_spy_adaptive": res_spy.as_dict(),
        "sample_penny_equity_adaptive": res_penny.as_dict(),
        "context_inputs_spy": {
            "session_label": ctx_spy.session_label,
            "vix_level": ctx_spy.vix_level,
            "spot": ctx_spy.spot,
            "spread_frac": ctx_spy.spread_frac,
        },
        "context_inputs_penny_sample": {
            "session_label": ctx_penny.session_label,
            "vix_level": ctx_penny.vix_level,
            "spot": ctx_penny.spot,
            "spread_frac": ctx_penny.spread_frac,
        },
        "static_defaults_reference": resolve_l1_materiality_engine("SPY", context=None).as_dict(),
    }

    return JSONResponse(
        {
            "ed_l1": {
                "schema_version": 2,
                "l1_diag_uptime_sec": round(uptime_sec, 4),
                "l1_build_total": bt,
                "l1_build_ms_avg": round(avg_ms, 4),
                "l1_build_ms_sum": float(_l1_instrumentation["l1_build_ms_sum"]),
                "l1_build_by_reason": reasons,
                "l1_http_cache_hit_total": int(_l1_instrumentation["l1_http_cache_hit_total"]),
                "l1_quote_material_skip_total": int(_l1_instrumentation["l1_quote_material_skip_total"]),
                "l1_cache_eviction_total": int(_l1_instrumentation["l1_cache_eviction_total"]),
                "l1_cache_eviction_ttl_total": int(_l1_instrumentation["l1_cache_eviction_ttl_total"]),
                "l1_cache_eviction_cap_total": int(_l1_instrumentation["l1_cache_eviction_cap_total"]),
                "l1_cache_reconcile_lru_pruned_total": int(_l1_instrumentation["l1_cache_reconcile_lru_pruned_total"]),
                "l1_cache_reconcile_lru_backfilled_total": int(
                    _l1_instrumentation["l1_cache_reconcile_lru_backfilled_total"]
                ),
                "l1_cache_lifecycle": l1_cache_invariants(_l1_snapshot_cache, _l1_scope_lru),
                "l1_of_quote_hook_engine_total": int(_l1_instrumentation["l1_of_quote_hook_engine_total"]),
                "l1_of_quote_hook_reuse_total": int(_l1_instrumentation["l1_of_quote_hook_reuse_total"]),
                "l1_cache_scope_count": len(_l1_snapshot_cache),
                "l1_lru_order_len": len(_l1_scope_lru),
                "policy": {
                    "L1_CACHE_ENTRY_TTL_SEC": L1_CACHE_ENTRY_TTL_SEC,
                    "L1_HTTP_SERVE_MAX_AGE_SEC": L1_HTTP_SERVE_MAX_AGE_SEC,
                    "L1_MAX_CACHE_SCOPES": L1_MAX_CACHE_SCOPES,
                    "L1_ORDER_FLOW_STALE_SEC": L1_ORDER_FLOW_STALE_SEC,
                    "L1_OF_MIN_COMPUTE_INTERVAL_SEC": L1_OF_MIN_COMPUTE_INTERVAL_SEC,
                    "L1_OF_PROBE_FORCE_REFRESH_SEC": L1_OF_PROBE_FORCE_REFRESH_SEC,
                },
                "cached_scopes_sample": sample,
                "operational": operational,
                "l1_adaptive_materiality": l1_adaptive_materiality,
                "l1_sse_light": _l1_sse_light_diag_payload(),
            }
        }
    )


@app.post("/api/diagnostics/ticker-switch")
def post_ticker_switch_diagnostics(payload: dict = Body(default={})):
    """Ingest client ticker-switch timing records into in-memory ring buffer."""
    from ticker_switch_diagnostics import record_switch_event

    record_switch_event(payload if isinstance(payload, dict) else {})
    return JSONResponse({"ok": True})


@app.get("/api/diagnostics/ticker-switch")
def get_ticker_switch_diagnostics(limit: int = Query(50, ge=1, le=200)):
    """Recent ticker-switch timing events (newest first)."""
    from ticker_switch_diagnostics import get_recent_events

    return JSONResponse({"events": get_recent_events(limit), "buffer_max": 100})


@app.get("/api/diagnostics/sqlite-contention")
def get_sqlite_contention_diagnostics():
    """
    Tier-1 SQLite lock-wait / busy / locked counters (process-local).

    For operator trust audits — does not change retry policy. See Card Trust Contract §8.
    """
    from db import sqlite_contention_metrics_snapshot
    from verification.db_sqlite_contention_impact_audit import (
        build_db_contention_operator_surface,
    )

    metrics = sqlite_contention_metrics_snapshot()
    return JSONResponse(
        {
            **metrics,
            "operator": build_db_contention_operator_surface(metrics),
        }
    )


@app.get("/api/fast-quote")
async def fast_quote(ticker: str = Query(default=DEFAULT_TICKER)):
    """
    Fast lane: latest equity quote fields only. Independent fast_generation_id / exchange_quote_ts.
    Does not return chain, fusion, or decision data.
    """
    ticker = ticker_storage_key(ticker)   # RC-126: SPX -> $SPX etc., ONE authority
    route_t0 = time.perf_counter()
    asyncio_thread = threading.current_thread().name
    log.info(
        "fast_quote_route_enter ticker=%s asyncio_thread=%s",
        ticker,
        asyncio_thread,
    )
    loop = asyncio.get_event_loop()
    submit_ts = time.perf_counter()
    # SWITCH-LATENCY FIX: _register_tracked_ticker persists to the SQLite logging_universe
    # (a DB write); keep it off the event loop alongside the quote fetch.
    def _reg_and_fetch():
        # TICKER-PREVIEW-NO-ENROLL: fast-quote view touches last-seen only, never enrolls.
        _touch_tracked_ticker_view(ticker)
        return _fetch_fast_quote_payload(ticker)
    try:
        payload = await loop.run_in_executor(_get_quote_hot_executor(), _reg_and_fetch)
        after_exec = time.perf_counter()
        log.info(
            "fast_quote_route_done ticker=%s asyncio_thread=%s route_total_ms=%.2f await_executor_ms=%.2f",
            ticker,
            asyncio_thread,
            (after_exec - route_t0) * 1000.0,
            (after_exec - submit_ts) * 1000.0,
        )
        return JSONResponse(payload)
    except HTTPException as he:
        if _schwab_auth_http_unavailable(he):
            stale = _lmp.get_quote(ticker)
            if _plane_fast_quote_has_spot(stale):
                return JSONResponse(_stale_fast_quote_carried_forward(stale, ticker))
            return JSONResponse(
                status_code=401,
                content=_fast_quote_token_invalid_payload(str(he.detail or "")),
            )
        if he.status_code >= 400:
            log.warning("Fast quote HTTP %s for %s: %s", he.status_code, ticker, he.detail)
        raise
    except Exception as e:
        from schwab_client import SchwabAuthError, _is_token_error

        if _is_token_error(e) or isinstance(e, SchwabAuthError):
            stale = _lmp.get_quote(ticker)
            if _plane_fast_quote_has_spot(stale):
                return JSONResponse(_stale_fast_quote_carried_forward(stale, ticker))
            return JSONResponse(
                status_code=401,
                content=_fast_quote_token_invalid_payload(str(e)),
            )
        log.error(f"Fast quote failed for {ticker}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stream")
async def sse_stream(
    ticker: str = Query(default=DEFAULT_TICKER),
    expiry: Optional[str] = Query(default=None),
):
    """
    Server-Sent Events stream: pushes market state snapshots whenever fresh data is available.
    Client connects with ?ticker=X&expiry=Y; server fetches that ticker periodically and pushes.
    """
    ticker = ticker.upper().strip()
    expiry = expiry or None
    key = (ticker, expiry)
    # TICKER-PREVIEW-NO-ENROLL: an SSE stream connect is a VIEW subscription, not a track —
    # touch last-seen only (offloaded; may do a SQLite write for an already-enrolled ticker).
    await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _touch_tracked_ticker_view, ticker)

    stream_route_t0 = time.perf_counter()

    async def event_generator():
        global _sse_conn_epoch
        q = asyncio.Queue(maxsize=10)
        with _sse_lock:
            _sse_clients.append(q)
            _sse_subscribers[key] = _sse_subscribers.get(key, 0) + 1
            # T5.1: a new connection changes the audience — the epoch bump makes
            # the next cadence fanout deliver the current bundle to this client
            # even when its identity is otherwise already-broadcast.
            _sse_conn_epoch += 1
        # Immediate SSE comment chunk: first body bytes must not wait on q.get() (up to 30s) or
        # some proxies/clients defer visible connection until first chunk — CONNECTING sticks.
        yield ": ok\n\n"
        log.info(
            "sse_stream_first_yield ticker=%s expiry=%s ms_since_route_entry=%.2f",
            ticker,
            expiry,
            (time.perf_counter() - stream_route_t0) * 1000.0,
        )
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=30.0)
                    if (
                        isinstance(raw, tuple)
                        and len(raw) == 2
                        and raw[0] == "live_quote"
                    ):
                        yield f"event: live_quote\ndata: {json.dumps(raw[1])}\n\n"
                    else:
                        yield f"data: {json.dumps(raw)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)
                cnt = _sse_subscribers.get(key, 0) - 1
                if cnt <= 0:
                    _sse_subscribers.pop(key, None)
                else:
                    _sse_subscribers[key] = cnt

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _broadcast_live_quote_sse_payloads() -> None:
    """
    Layer A: push latest in-memory quote rows to SSE clients as `event: live_quote`.
    No Schwab, no DB, no _fetch_state — subscribers see quote updates at LIVE_QUOTE_SSE_INTERVAL_SEC
    whenever the plane has a new fast_generation_id (streaming Level One or REST fast-quote).
    """
    try:
        with _sse_lock:
            subs = list(_sse_subscribers.keys())
        if not subs:
            return
        tickers = sorted({t for (t, _) in subs})
        dead: list[asyncio.Queue] = []
        for t in tickers:
            payload = _lmp.take_fresh_sse_quote_payload(t)
            if not payload:
                continue
            with _sse_lock:
                clients = list(_sse_clients)
            for q in clients:
                try:
                    q.put_nowait(("live_quote", payload))
                except asyncio.QueueFull:
                    dead.append(q)
        for q in dead:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)
        if dead:
            log.debug("SSE live_quote: removed %s stalled client(s)", len(dead))
    except Exception as e:
        log.warning("live_quote broadcast: %s", e, exc_info=True)


async def _sse_live_quote_loop() -> None:
    """Layer A SSE — memory-only quote events, independent of analytical refresh cadence."""
    while True:
        try:
            await asyncio.sleep(max(0.05, LIVE_QUOTE_SSE_INTERVAL_SEC))
            await _broadcast_live_quote_sse_payloads()
        except Exception as e:
            log.warning("SSE live quote loop error: %s", e, exc_info=True)


# IDLE_SENTINEL_FRESHNESS_V1 — pure selection for the idle-refresh arm below.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — recompute scheduling only; the scheduled
#   _fetch_state path and its existing chains/quotes/pricehistory leaf reads are
#   unchanged; no market field read, derivation, or emission changed.
# Derived-field disposition: none required (scheduling metadata only).
# All consumers checked: yes — _schedule_analytics_recompute (dedupes inflight
#   keys) and the freshness contract; stale/actionable semantics untouched.
# SCHWAB_CSV_CHECKED
def _select_idle_stale_keys(owned_keys: set, max_keys: int) -> list[tuple]:
    """Oldest-first cached (ticker, expiry) keys with no live SSE owner whose age
    exceeds the stale budget — the standing producer for unviewed cards.

    Ownership is ticker-level from the live subscriber set (a viewer subscribed
    with a None/default expiry owns its resolved cache key, so those tickers are
    excluded to preserve single-owner semantics). Selection is cache-key/age
    driven — identical for sentinel, guest, or any expiry; no ticker literal
    exists. Rate-bounded by max_keys; inflight keys are skipped (the scheduler's
    dedupe is the second guard). Never raises.

    ENROLLED-ONLY (RC-483, 2026-08-25): the idle producer keeps only ENROLLED cards
    warm. Viewing a ticker does not enroll it (TICKER-PREVIEW-NO-ENROLL) but does
    populate _state_cache, and the cache has no time eviction — so before this filter a
    glanced-at, un-enrolled ticker (measured: CRM, DKS) became a permanent
    idle_key_refresh snapshot writer for the rest of the process, making the collecting
    universe disagree with the enrolled universe. A live viewer still refreshes its own
    ticker through the owner path regardless of enrollment; only the STANDING producer
    for cards nobody is viewing is scoped to the enrolled set.
    """
    if max_keys <= 0:
        return []
    try:
        owned_tickers = {k[0] for k in owned_keys if isinstance(k, tuple) and k}
        with _logger_lock:
            enrolled = set(_logger_tickers)   # in-process mirror of the enrolled universe
        stale_after = float(CACHE_TTL) * ANALYTICS_STALE_GRACE_CYCLES
        now = time.time()
        candidates: list[tuple[float, tuple]] = []
        for key, entry in list(_state_cache.items()):
            if not isinstance(key, tuple) or not key:
                continue
            if key[0] in owned_tickers:
                continue
            if key[0] not in enrolled:
                continue   # RC-483: an un-enrolled viewed card ages out, never resurrected
            if not isinstance(entry, dict) or not entry.get("ms_dict"):
                continue
            ts = entry.get("ts")
            if not isinstance(ts, (int, float)):
                continue
            age = now - float(ts)
            if age < stale_after:
                continue
            if _tier_c_inflight_key(key[0], key[1] if len(key) > 1 else None) in _analytics_inflight:
                continue
            candidates.append((age, key))
        candidates.sort(key=lambda x: -x[0])
        return [k for _, k in candidates[:max_keys]]
    except Exception:
        # The idle arm must never take down the SSE loop.
        return []


async def _sse_background_loop() -> None:
    """Layer C: on each cadence, schedule background _fetch_state for active SSE keys (deduped).

    HTTP and this loop share the same thread-pool refresh — no synchronous chain work here.
    Cache fanout runs first each tick so SSE clients receive Tier C payloads even when
    _fetch_state is blocked on DB lock contention (T5).
    """
    global _sse_cadence_diag_last_log_mono
    while True:
        try:
            with _sse_lock:
                subs = list(_sse_subscribers.keys())
            # No viewers: sleep long to avoid idle churn.
            interval = max(0.5, VIEWER_SSE_REFRESH_SEC) if subs else float(CACHE_TTL)
            # IDLE_SENTINEL_FRESHNESS_V1 — standing producer for unowned keys:
            # runs on EVERY tick (with or without viewers) so unviewed cards can
            # never age unbounded; viewed keys keep the existing owner below.
            for (_it, _ie) in _select_idle_stale_keys(
                owned_keys=set(subs), max_keys=IDLE_KEY_REFRESH_MAX_PER_TICK
            ):
                _schedule_analytics_recompute(
                    _tier_c_inflight_key(_it, _ie), _it, _ie,
                    update_source="idle_key_refresh",
                )
            if not subs:
                await asyncio.sleep(interval)
                continue
            _loop_t0 = time.perf_counter()
            for (t, e) in subs:
                ik = _tier_c_inflight_key(t, e)
                _maybe_broadcast_sse_cache_fanout(
                    t,
                    e,
                    inflight_key=ik,
                    fanout_reason="sse_loop_cadence",
                )
                _schedule_analytics_recompute(ik, t, e, update_source="sse_loop")
            _loop_wall_ms = (time.perf_counter() - _loop_t0) * 1000.0
            _now_m = time.monotonic()
            if _now_m - _sse_cadence_diag_last_log_mono >= 30.0 or (
                subs and _loop_wall_ms >= 3000.0
            ):
                _sse_cadence_diag_last_log_mono = _now_m
                log.info(
                    "sse_background_cadence n_subs=%s sleep_interval_s=%.3f fetch_wall_ms=%.1f "
                    "keys=%s",
                    len(subs),
                    interval,
                    _loop_wall_ms,
                    subs,
                )
            await asyncio.sleep(interval)
        except Exception as e:
            log.warning(f"SSE background loop error: {e}", exc_info=True)


@app.get("/api/expiries")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write + Schwab expiry fetch, no await).
def get_expiries(ticker: str = Query(default=DEFAULT_TICKER)):
    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: listing expiries is a VIEW — touch last-seen only.
    _touch_tracked_ticker_view(ticker)
    # Use any cached (ticker, expiry) entry — expiries list is same for all
    cached = next(
        (v for (t, e), v in _state_cache.items() if t == ticker and v.get("ms_dict")),
        None
    )
    if cached:
        return JSONResponse({"expiries": cached["ms_dict"].get("expiries", [])})
    try:
        return JSONResponse({"expiries": _fetch_expiries_light(ticker)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logger/status")
def logger_status():
    """Return background logger status — which tickers are being logged and their stats."""
    with _logger_lock:
        tickers = list(_logger_tickers)
        stats   = dict(_logger_stats)
        running = _logger_running

    db_rows: dict[str, dict] = {}
    if _HAS_SIGNALS:
        try:
            for row in get_db().logging_universe_list_rows():
                db_rows[ticker_storage_key(row.get("ticker"))] = row  # RC-345/F25: canonical join key
        except Exception as e:
            log.debug("logger_status DB join: %s", e)

    now = time.time()
    result = []
    for t in tickers:
        s = stats.get(t, {})
        last_logged = s.get("last_logged")
        dbr = db_rows.get(t, {})
        enroll = dbr.get("enrollment_source") or ("core_bootstrap" if t in CORE_TICKERS else None)
        result.append({
            "ticker":       t,
            "core":         t in CORE_TICKERS,
            "category":     dbr.get("category") or ("core" if t in CORE_TICKERS else "unknown"),
            "enrollment_source": enroll,
            "enrolled_ts_utc": dbr.get("enrolled_ts_utc"),
            "last_seen_ts_utc": dbr.get("last_seen_ts_utc"),
            "last_background_log_ts_utc": dbr.get("last_background_log_ts_utc"),
            "count":        s.get("count", 0),
            "last_logged":  last_logged,
            "secs_ago":     round(now - last_logged, 0) if last_logged else None,
            "last_error":   s.get("last_error"),
            "source":       s.get("source", "—"),
            "eligible_background_log": _is_loggable_session(),
        })

    orphan_tickers: list[str] = []
    if _HAS_SIGNALS:
        try:
            orphan_tickers = get_db().logging_universe_snapshot_ticker_orphans()
        except Exception as e:
            log.debug("logger_status orphan scan: %s", e)

    return JSONResponse({
        "running":       running,
        "interval_secs": LOG_INTERVAL,
        "stagger_secs":  STAGGER_SECS,
        "rth_only":      RTH_ONLY,
        "session_gate":  {
            "premarket_start_et_minute": PRE_MARKET_MINS,
            "buffer_end_et_minute": LOGGER_BUFFER_MINS,
            "loggable_now": _is_loggable_session(),
        },
        "max_user_persisted_symbols": MAX_USER_PERSISTED_LOGGING_TICKERS,
        "user_persisted_enrollment_policy": _user_persisted_enrollment_policy(),
        "max_pinned_symbols": MAX_PINNED_LOGGING_TICKERS,
        "core_tickers":  CORE_TICKERS,
        "tickers":       result,
        "snapshot_tickers_orphaned_from_logging_universe": orphan_tickers,
        "snapshot_orphan_count": len(orphan_tickers),
    })


@app.get("/api/logger/universe")
def logger_universe():
    """Issue 22 hardened — auditable logging_universe with eviction_status per row."""
    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    try:
        db = get_db()
        rows = db.logging_universe_list_rows_audit()
        protected = db.logging_universe_protected_tickers()
        candidates = db.logging_universe_eviction_candidates_fifo()
        evictions = db.logging_universe_recent_evictions(limit=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    with _logger_lock:
        in_memory = list(_logger_tickers)
    return JSONResponse(
        {
            "schema": "logging_universe_audit_v2",
            "rth_only": RTH_ONLY,
            "session_gate_loggable_now": _is_loggable_session(),
            "premarket_start_et_minute": PRE_MARKET_MINS,
            "buffer_end_et_minute": LOGGER_BUFFER_MINS,
            "max_user_persisted_symbols": MAX_USER_PERSISTED_LOGGING_TICKERS,
            "user_persisted_enrollment_policy": _user_persisted_enrollment_policy(),
            "max_pinned_symbols": MAX_PINNED_LOGGING_TICKERS,
            "core_tickers": CORE_TICKERS,
            "symbols_in_memory_logger_cycle": in_memory,
            "protected_symbols": protected,
            "eviction_candidates_fifo_user_persisted": candidates,
            "recent_evictions": evictions,
            "logging_universe_rows": rows,
        }
    )


@app.get("/api/logger/universe/by-category")
def logger_universe_by_category(
    category: str = Query(..., description="core | pinned | user_persisted"),
):
    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    c = (category or "").strip().lower()
    if c not in ("core", "pinned", "user_persisted"):
        raise HTTPException(status_code=400, detail="category must be core, pinned, or user_persisted")
    try:
        rows = [
            r
            for r in get_db().logging_universe_list_rows_audit()
            if (r.get("category") or "").lower() == c
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return JSONResponse({"category": c, "rows": rows, "count": len(rows)})


@app.post("/api/logger/pin")
def logger_pin(ticker: str = Query(..., description="Symbol to pin (non-core only)")):
    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical pin identity (matches enrollment + dedup)
    if not t or len(t) > 10:
        raise HTTPException(status_code=400, detail="invalid ticker")
    if t in CORE_TICKERS:
        raise HTTPException(status_code=400, detail="core symbols are already protected; pin not applicable")
    db = get_db()
    is_already_pinned = any(
        ticker_storage_key(r.get("ticker")) == t and r.get("category") == "pinned"  # RC-345/F25: canonical pin-dedup
        for r in db.logging_universe_list_rows()
    )
    if (
        not is_already_pinned
        and db.logging_universe_pinned_count() >= MAX_PINNED_LOGGING_TICKERS
    ):
        raise HTTPException(
            status_code=409,
            detail=f"max pinned symbols ({MAX_PINNED_LOGGING_TICKERS}) reached — unpin one first",
        )
    now = time.time()
    db.logging_universe_upsert_pinned(t, "api_logger_pin", now)
    _hydrate_logger_tickers_from_db()
    with _logger_lock:
        all_t = list(_logger_tickers)
    return JSONResponse({"ok": True, "ticker": t, "all_tickers": all_t})


@app.post("/api/logger/unpin")
def logger_unpin(ticker: str = Query(...)):
    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    t = ticker.upper().strip()
    db = get_db()
    ok = db.logging_universe_unpin_to_user_persisted(t, time.time())
    if not ok:
        raise HTTPException(status_code=400, detail="symbol is not pinned")
    _hydrate_logger_tickers_from_db()
    with _logger_lock:
        all_t = list(_logger_tickers)
    return JSONResponse({"ok": True, "ticker": t, "all_tickers": all_t})


@app.post("/api/logger/add")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def logger_add(ticker: str = Query(..., description="Ticker to add to background logger")):
    """Manually add a ticker to the background logger."""
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    added = _register_tracked_ticker(ticker, enrollment_source="api_logger_add")
    with _logger_lock:
        tickers = list(_logger_tickers)
    return JSONResponse({"added": added, "ticker": ticker, "all_tickers": tickers})


@app.post("/api/logger/remove")
def logger_remove(ticker: str = Query(..., description="Ticker to remove from logger")):
    """Remove a non-core ticker from the background logger and durable logging_universe."""
    ticker = ticker.upper().strip()
    if ticker in CORE_TICKERS:
        raise HTTPException(status_code=400, detail=f"{ticker} is a core ticker and cannot be removed")
    panel_auto = frozenset(_market_context_panel_auto_candidates())
    if ticker in panel_auto:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{ticker} is auto-enrolled from the market cross-panel (see market_context.py) "
                "and cannot be removed via /api/logger/remove"
            ),
        )
    db_removed = False
    if _HAS_SIGNALS:
        try:
            db_removed = get_db().logging_universe_remove_non_core(ticker)
        except Exception as e:
            log.warning("logging_universe_remove_non_core: %s", e)
    with _logger_lock:
        if ticker in _logger_tickers:
            _logger_tickers.remove(ticker)
            removed = True
        else:
            removed = False
        tickers = list(_logger_tickers)
    return JSONResponse(
        {
            "removed": removed,
            "db_removed": db_removed,
            "ticker": ticker,
            "all_tickers": tickers,
        }
    )


@app.post("/api/prediction/override")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def prediction_override(ticker: str = Query(...), direction: str = Query(...), source: str = Query("user")):
    """Set manual override for prediction direction. direction: up|flat|down. source: user|manual."""
    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL (Decision 3): setting a prediction override acts on an existing
    # tracked symbol; it must not silently enroll a new one into the training roster.
    _touch_tracked_ticker_view(ticker)
    d = (direction or "").strip().lower()
    if d not in ("up", "flat", "down"):
        raise HTTPException(status_code=400, detail="direction must be up, flat, or down")
    src = (source or "user").lower()
    _pred_overrides[ticker] = {"direction": d, "source": src}
    return JSONResponse({"ok": True, "ticker": ticker, "direction": d, "source": src})


@app.post("/api/prediction/override/clear")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def prediction_override_clear(ticker: str = Query(...)):
    """Clear prediction override for ticker."""
    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL (Decision 3): clearing an override must not enroll.
    _touch_tracked_ticker_view(ticker)
    if ticker in _pred_overrides:
        del _pred_overrides[ticker]
        return JSONResponse({"ok": True, "ticker": ticker, "cleared": True})
    return JSONResponse({"ok": True, "ticker": ticker, "cleared": False})


@app.get("/api/health")
def health():
    with _logger_lock:
        running = _logger_running
        n       = len(_logger_tickers)
    return {"status": "ok", "time": datetime.now().isoformat(), "logger_running": running, "logger_tickers": n}


def _repo_git_head_sha() -> Optional[str]:
    """Best-effort repo tip for runtime-vs-disk checks (Meet-or-Exceed cycle)."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=3.0,
        )
        sha = (proc.stdout or "").strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


@app.get("/api/release/current")
def api_release_current():
    """Current process release object (I-25)."""
    from release_object import get_current_release, validate_release_for_emission

    release = get_current_release(required=False)
    ok, reason = validate_release_for_emission(release)
    if not ok:
        return JSONResponse({"ok": False, "reason": reason, "release": release}, status_code=503)
    return {"ok": True, "release": release}


@app.get("/api/decision/{decision_id}")
def api_decision_by_id(decision_id: str):
    """Retrieve immutable production decision by decision_id (I-31)."""
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


# ── BUILD_IDENTITY_PROCESS_DRIFT_V1 — immutable process-start identity ───────
# Root cause fixed here: /api/build used to serve _repo_git_head_sha() (a
# request-time repo read) as the only identity, so a HEAD move after launch
# made the endpoint report code the process never loaded (proven 2026-07-09:
# PID 57076 booted @ 930c678 reported 9664be4). The identity below is captured
# exactly ONCE at module import — before any request is served — and is a
# frozen dataclass: normal code paths cannot mutate it. Request-time repo reads
# feed only the separately named repository_state_now diagnostic (and the
# legacy top-level git_sha compatibility field).
_IDENTITY_SHA_HEX_CHARS = frozenset("0123456789abcdef")


def _is_full_git_sha(value: str) -> bool:
    """True only for a 40-char lowercase-hex string — malformed git output is
    rejected rather than represented as a valid identity."""
    return len(value) == 40 and set(value) <= _IDENTITY_SHA_HEX_CHARS


@dataclass(frozen=True)
class ProcessIdentityV1:
    """Immutable process-start identity (schema v1). Captured once; never
    recomputed per request. identity_capture_error carries a sanitized fixed
    classification only — never raw subprocess output or stack traces."""

    schema_version: str
    startup_git_sha: Optional[str]
    startup_git_sha_short: Optional[str]
    startup_git_dirty: Optional[bool]
    startup_git_available: bool
    startup_identity_captured_at_utc: float
    process_started_at_utc: Optional[float]
    process_id: int
    package_build_id: Optional[str]
    identity_source: str
    identity_capture_error: Optional[str]


def _capture_process_identity() -> ProcessIdentityV1:
    """Build the process-start identity. Called once at module import for the
    production singleton; kept callable so tests can exercise every capture
    state deterministically against temp repos / mocked subprocess layers.

    Dirty semantics: ``git status --porcelain`` with ANY output (tracked
    changes OR untracked files) = dirty — matching the repo's clean-tree
    policy used by the commit gates. A failed dirty probe yields None
    (unknown), never a fabricated clean=False->false claim of cleanliness.

    process_started_at_utc: OS process creation time via optional psutil;
    None when that support is unavailable — startup_identity_captured_at_utc
    (module-import wall clock, UTC) is the honestly named capture instant.
    """
    import subprocess

    captured_at = datetime.now(tz=timezone.utc).timestamp()
    pid = os.getpid()

    started_at: Optional[float] = None
    try:
        import psutil  # optional process-metadata support — NOT a governed runtime dependency

        started_at = float(psutil.Process(pid).create_time())
    except Exception:  # noqa: BLE001 — identity capture must never kill startup
        started_at = None

    sha: Optional[str] = None
    sha_short: Optional[str] = None
    dirty: Optional[bool] = None
    git_available = False
    capture_error: Optional[str] = None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            check=True,
            timeout=5.0,
        )
        raw = (proc.stdout or "").strip().lower()
        if _is_full_git_sha(raw):
            sha = raw
            sha_short = raw[:12]  # derived from the captured full SHA — no second git call
            git_available = True
        else:
            capture_error = "git_output_not_a_sha"
    except FileNotFoundError:
        capture_error = "git_executable_unavailable"
    except subprocess.TimeoutExpired:
        capture_error = "git_timeout"
    except (OSError, subprocess.SubprocessError):
        capture_error = "git_command_failed"

    if git_available:
        try:
            st = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=APP_DIR,
                capture_output=True,
                text=True,
                check=True,
                timeout=10.0,
            )
            dirty = bool((st.stdout or "").strip())
        except (OSError, subprocess.SubprocessError):
            dirty = None  # unknown dirty state is NOT clean
            if capture_error is None:
                capture_error = "git_dirty_state_unavailable"

    package_build_id: Optional[str] = None
    try:
        from release_object import get_current_release

        _rel = get_current_release(required=False)
        package_build_id = _rel.get("release_id") if _rel else None
    except Exception:  # noqa: BLE001 — identity capture must never kill startup
        package_build_id = None

    if git_available:
        identity_source = "git_startup_capture"
    elif package_build_id is not None:
        identity_source = "release_object_package"
    else:
        identity_source = "unavailable"

    return ProcessIdentityV1(
        schema_version="1",
        startup_git_sha=sha,
        startup_git_sha_short=sha_short,
        startup_git_dirty=dirty,
        startup_git_available=git_available,
        startup_identity_captured_at_utc=captured_at,
        process_started_at_utc=started_at,
        process_id=pid,
        package_build_id=package_build_id,
        identity_source=identity_source,
        identity_capture_error=capture_error,
    )


# Captured exactly once, at module import, before uvicorn serves any request
# (single-process, single-worker, no --reload per start_ed_console.bat).
PROCESS_IDENTITY_V1: ProcessIdentityV1 = _capture_process_identity()


@app.get("/api/build")
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
    from release_object import get_current_release

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
    }


@app.get("/api/vol-observability")
def api_vol_observability(ticker: Optional[str] = Query(default=None)):
    """VOL_OBSERVABILITY_V1: read-only projection of the per-cycle vol-index
    observations ($VIX consumed; $VXN/$RVX FETCHED_UNCONSUMED) plus the
    ratified ticker-class mapping candidate. Never feeds the money path."""
    return vol_observability_payload(ticker)


@app.get("/api/diagnostics/chain-gate")
def api_chain_gate_diagnostics():
    """Read-only chain-gate observability: slots, waits, coalescing, breaker."""
    with _chain_inflight_lock:
        # Keys are (ticker, strike_count); render as SPY@20 for operators.
        inflight = sorted(
            f"{k[0]}@{k[1]}" if isinstance(k, tuple) and len(k) == 2 else str(k)
            for k in _chain_inflight
        )
    return {
        "gate": _schwab_chain_fetch_gate.snapshot(),
        "inflight_tickers": inflight,
        "acquire_timeout_sec": CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC,
        "fail_open_timeout_count": _chain_fetch_gate_timeout_count,
        "breaker_cooldown_sec": CHAIN_GATE_BREAKER_COOLDOWN_SEC,
        "breaker_failure_threshold": CHAIN_GATE_BREAKER_FAILURE_THRESHOLD,
    }


@app.get("/api/price-levels")
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


def _canonical_price_level_bars(tk: str, session_date) -> tuple[list, str, list]:
    """Resolve the ONE bar input for the canonical snapshot: accumulator, else banked.

    Phase 2A: this is the only bar-input resolution for the Phase 2A level ids. The
    second materialization that produced overnight 773.3975 on /api/levels and 773.40
    on /api/liquidity-snapshot at the same instant was a second BAR INPUT (a
    synchronous Schwab fetch), not a second formula — so the input is resolved once,
    here, and every surface reads what came out of it.
    """
    import sqlite3 as _sq

    from liquidity_value_engine import _bars_to_list, prior_trading_session_date

    degraded: list[dict] = []
    bars_norm = _bars_to_list(_liquidity_live_1m_overlay_bars(tk))
    bar_source = "live_accumulator"
    # t12 (RC-227 residual, MEASURED): the accumulator's rolling buffer can hold a
    # TRUNCATED prior session — the prior date resolves but min()/max() run over a
    # partial tape (PDL served 756.84 vs the true 749.59 while PDH/PDC matched).
    # A prior-day fact needs the FULL session: require plausible full coverage
    # (>= 300 of ~390 RTH minutes) or fall through to banked canonical bars.
    _prior_probe = prior_trading_session_date(bars_norm, session_date)
    _prior_full = False
    if _prior_probe is not None:
        from liquidity_value_engine import _bar_dt_et as _bde
        _n_prior = sum(
            1 for b in bars_norm
            if (lambda d: d is not None and d.date() == _prior_probe)(_bde(b))
        )
        _prior_full = _n_prior >= LEVELS_PRIOR_SESSION_MIN_BARS
    if not _prior_full:
        # Accumulator holds no prior RTH session or only a truncated slice —
        # fall back to banked canonical bars. Read-only, indexed, no vendor call.
        try:
            db = get_db()
            con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
            try:
                rows = con.execute(
                    "SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
                    "WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT 2500", (tk,),
                ).fetchall()
            finally:
                con.close()
            bars_norm = _bars_to_list([
                {"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3],
                 "close": r[4], "volume": r[5]} for r in reversed(rows)
            ])
            bar_source = "banked_price_bars_1m"
            # AUDIT ROUND 2 (2026-08-25): the >=LEVELS_PRIOR_SESSION_MIN_BARS coverage
            # check existed only on the accumulator path, and this fallback fires
            # precisely WHEN coverage is low — so truncated banked tapes (measured: MTA
            # sessions banked at 188/236/316 of 390 RTH bars) served PDH/PDL as
            # prior-day fact with up to half the session missing. A low banked count is
            # ambiguous (thin trading vs collection gap), so the levels still serve but
            # the prior_day family is stamped degraded with the measured count — never
            # silently.
            _b_prior = prior_trading_session_date(bars_norm, session_date)
            if _b_prior is not None:
                from liquidity_value_engine import _bar_dt_et as _bde2
                _n_banked = sum(
                    1 for b in bars_norm
                    if (lambda d: d is not None and d.date() == _b_prior)(_bde2(b))
                )
                if _n_banked < LEVELS_PRIOR_SESSION_MIN_BARS:
                    degraded.append({
                        "family": "prior_day",
                        "reason": (f"banked prior session {_b_prior} holds only "
                                   f"{_n_banked} of >= {LEVELS_PRIOR_SESSION_MIN_BARS} "
                                   f"RTH bars — thin trading or a collection gap; "
                                   f"prior-day levels derive from a partial tape"),
                        "last_good_ts_utc": None})
        except Exception as e:
            degraded.append({"family": "prior_day",
                             "reason": f"banked bar read failed: {str(e)[:80]}",
                             "last_good_ts_utc": None})
            bars_norm = []
    return bars_norm, bar_source, degraded


def canonical_price_level_snapshot(ticker: str):
    """THE Phase 2A entry point for every server surface.

    Materializes once per generation and returns the SAME object for the rest of that
    generation. No endpoint may call the engine's level helpers directly — the static
    guard `check_phase2a_single_level_computation` fails the build if one does, alias
    or not.
    """
    from liquidity_value_engine import PlaybookConfig, materialize_price_level_snapshot
    from time_et import now_et

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    session_date = now_et().date()
    bars_norm, bar_source, degraded = _canonical_price_level_bars(tk, session_date)
    return materialize_price_level_snapshot(
        tk, session_date, bars_norm, bar_source=bar_source,
        config=PlaybookConfig(), degraded=degraded,
    )


@app.get("/api/levels")
# Phase 2A (operator 2026-08-08): /api/levels is the canonical SERVING CONTRACT for the
# one materialized PriceLevelSnapshot — it serializes, it does not compute. Every other
# surface (liquidity-snapshot, market_context, /api/state, ML features, persistence,
# chart) carries the values out of the same snapshot object and generation.
def get_levels(ticker: str = Query(default=DEFAULT_TICKER)):
    """Single levels contract (schema v1): id/price/family/evidence_tier/provenance/staleness."""
    import time as _time

    from liquidity_value_engine import carry_snapshot_levels

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    served_ts = _time.time()
    spot, spot_source, spot_ts = resolve_spot(tk)
    snap = canonical_price_level_snapshot(tk)
    # Register this surface against the runtime carrier contract: if any other carrier
    # already shipped a different value/generation/provenance for this generation, the
    # disagreement raises here instead of reaching two screens (RC-262 pattern).
    carry_snapshot_levels(snap, "api.levels")

    levels: list[dict] = []
    for lid, value in snap.levels.items():
        row = value.to_contract_dict()
        as_of = value.as_of_ts_utc
        row["staleness"] = {
            "as_of_ts_utc": as_of,
            "age_sec": None if as_of is None else round(served_ts - as_of, 1),
            "stale_after_sec": None,
            "stale": False,
            "reason": f"carried from canonical snapshot generation {snap.generation}",
        }
        levels.append(row)

    families_absent = list(snap.families_absent)
    for fam, why in (
        ("gamma", "Phase 2A slice excludes gamma — served by /api/terrain until migration"),
        ("expected_move", "Phase 2A slice excludes EM — served by /api/state until migration"),
    ):
        families_absent.append({"family": fam, "reason": why})

    return JSONResponse({
        "ticker": tk,
        "schema_version": 1,
        "served_ts_utc": served_ts,
        "spot": spot,
        "spot_source": spot_source,
        "spot_as_of_ts_utc": spot_ts,
        "generation": snap.generation,
        "snapshot_as_of_ts_utc": snap.as_of_ts_utc,
        "bar_source": snap.bar_source,
        "levels": levels,
        # The VWAP curve and its σ bands, CARRIED. chart.html and exposure.html each
        # used to accumulate their own from /api/bars1m — two more VWAPs for one
        # session, drawn beside a level neither of them agreed with.
        # [epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ]
        "vwap_series": [list(row) for row in snap.vwap_series],
        "families_absent": families_absent,
        "degraded": list(snap.degraded),
    })


def _build_raw_levels_used(raw_levels: dict, snapshot_type: str) -> list:
    """Flatten raw_levels into [{tag, value}] for display, ordered by price.

    Phase 2A scope rule: a canonical id names the canonical (ticker, scope, generation)
    value and nothing else. A CHECKPOINT snapshot (premarket/opening/midday/afternoon)
    measures the same concept through a different cutoff — a legitimately different
    number — so it travels under an explicitly distinct id (`VWAP@checkpoint:midday`)
    and is never compared against, or mistaken for, the canonical `VWAP`.
    """
    items = []
    _scope = "" if snapshot_type == "live" else f"@checkpoint:{snapshot_type}"
    tag_map = {
        "pdh": "PDH", "pdl": "PDL", "pdc": "PDC",
        "pd_poc": "PD_POC", "pd_vah": "PD_VAH", "pd_val": "PD_VAL",
        "overnight_high": "OVERNIGHT_HIGH", "overnight_low": "OVERNIGHT_LOW",
        "orb_high": "ORB_HIGH", "orb_low": "ORB_LOW", "orb_mid": "ORB_MID",
        "vwap": "VWAP", "plus1": "VWAP_P1", "minus1": "VWAP_M1",
        "plus2": "VWAP_P2", "minus2": "VWAP_M2",
        "poc": "TODAY_POC", "vah": "TODAY_VAH", "val": "TODAY_VAL",
    }
    prev = raw_levels.get("prev_day") or raw_levels.get("prev") or {}
    for k, v in prev.items():
        if v is not None and isinstance(v, (int, float)) and k in tag_map:
            items.append({"tag": tag_map[k] + _scope, "value": float(v)})
    for k in ["overnight_high", "overnight_low"]:
        v = (raw_levels.get("overnight") or {}).get(k)
        if v is not None:
            items.append({"tag": tag_map[k] + _scope, "value": float(v)})
    orb = raw_levels.get("orb") or {}
    for k in ["orb_high", "orb_low", "orb_mid"]:
        if orb.get(k) is not None:
            items.append({"tag": tag_map[k] + _scope, "value": float(orb[k])})
    if raw_levels.get("vwap") is not None and snapshot_type != "premarket":
        items.append({"tag": "VWAP" + _scope, "value": float(raw_levels["vwap"])})
    vwap_bands = raw_levels.get("vwap_bands") or {}
    for k, tag in [("plus2", "VWAP_P2"), ("plus1", "VWAP_P1"),
                   ("minus1", "VWAP_M1"), ("minus2", "VWAP_M2")]:
        if vwap_bands.get(k) is not None:
            items.append({"tag": tag + _scope, "value": float(vwap_bands[k])})
    for k in ["poc", "vah", "val"]:
        if raw_levels.get(k) is not None:
            items.append({"tag": tag_map[k] + _scope, "value": float(raw_levels[k])})
    return sorted(items, key=lambda x: x["value"])


def _liquidity_live_1m_overlay_bars(ticker: str) -> list[dict]:
    """1m bars + forming bar from the console accumulator (same tape as /api/state when active)."""
    t = ticker.upper().strip()
    out: list[dict] = []
    for c in _candles_1m.get_bars(t):
        out.append({
            "timestamp": int(c.ts * 1000),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": float(c.volume) if c.volume is not None else None,
        })
    cur = _candles_1m._current.get(t)
    if cur:
        ts = float(cur["ts"])
        out.append({
            "timestamp": int(ts * 1000),
            "open": float(cur["o"]),
            "high": float(cur["h"]),
            "low": float(cur["l"]),
            "close": float(cur["c"]),
            "volume": float(cur["v"]) if cur.get("v") is not None else None,
        })
    return out


def _liquidity_spot_from_cache_any_expiry(ticker: str) -> Optional[float]:
    """Best-effort spot from any cached /api/state row for this ticker (expiry may differ)."""
    t = ticker.upper().strip()
    for (tk, _), ent in _state_cache.items():
        if tk != t:
            continue
        d = ent.get("ms_dict") or {}
        s = d.get("spot")
        if s is None:
            continue
        try:
            sf = float(s)
            if sf > 0:
                return sf
        except (TypeError, ValueError):
            continue
    return None


def _liquidity_fusion_from_cache(
    ticker: str, expiry: Optional[str],
) -> tuple[list[tuple[float, str]], Optional[float], str]:
    """Pull options/EW key strikes from last /api/state cache hit for (ticker, expiry)."""
    t = ticker.upper().strip()
    e = (expiry or "").strip()
    if not e:
        return [], None, "no_expiry"
    ent = _state_cache.get((t, e))
    if not ent or not ent.get("ms_dict"):
        return [], None, "cache_miss"
    d = ent["ms_dict"]
    spot_v = d.get("spot")
    try:
        spot_f = float(spot_v) if spot_v is not None else None
    except (TypeError, ValueError):
        spot_f = None
    pairs = [
        (d.get("kl_call_gamma_wall"), "GAMMA_CALL_WALL"),
        (d.get("kl_put_gamma_wall"), "GAMMA_PUT_WALL"),
        (d.get("kl_call_delta_wall"), "DELTA_CALL_WALL"),
        (d.get("kl_put_delta_wall"), "DELTA_PUT_WALL"),
        (d.get("kl_call_oi_wall"), "OI_CALL_WALL"),
        (d.get("kl_put_oi_wall"), "OI_PUT_WALL"),
        (d.get("kl_gamma_inflection"), "GAMMA_INFLECTION"),
        (d.get("kl_delta_inflection"), "DELTA_INFLECTION"),
        # RC-292: the tag says what the metric is — a total-gamma concentration, not a
        # pin claim (the qualified claim is kl_pin_candidate, not tagged here as a level
        # because it is the SAME strike when present).
        (d.get("kl_absolute_gamma_strike"), "ABS_GAMMA"),
        # RC-134: kl_hvl is the NET book (RC-124); the tag must not say HVL, since that
        # name means total gamma (the absolute-gamma concentration).
        (d.get("kl_hvl"), "NET_GEX_PEAK"),
        (d.get("kl_max_pain"), "MAX_PAIN"),
        (d.get("kl_gamma_flip"), "GAMMA_FLIP"),
        (d.get("kl_oi_center"), "OI_CENTER"),
        (d.get("kl_em_upper"), "EM_UPPER"),
        (d.get("kl_em_lower"), "EM_LOWER"),
        (d.get("kl_synth_fwd"), "SYNTH_FWD"),
    ]
    levels: list[tuple[float, str]] = []
    for val, tag in pairs:
        if val is None:
            continue
        try:
            p = float(val)
            if p > 0:
                levels.append((p, tag))
        except (TypeError, ValueError):
            continue
    return levels, spot_f, "fused" if levels else "fused_empty"


def _liquidity_zone_tradeable_fields(zp: dict, spot: Optional[float]) -> None:
    """Add anchor, distance_to_spot, tradeable_score, options_level_count (mutates zp)."""
    from liquidity_value_engine import liquidity_zone_tradeable_score

    tags = zp.get("source_tags") or []
    lo, hi = float(zp["zone_low"]), float(zp["zone_high"])
    mid = zp.get("zone_mid")
    if mid is None:
        mid = (lo + hi) / 2.0
    zp["anchor"] = round(float(mid), 4)
    n_opt = sum(
        1
        for t in tags
        if t.startswith(("GAMMA_", "DELTA_", "OI_", "EM_", "SYNTH_"))
    )
    zp["options_level_count"] = n_opt
    if spot is None:
        zp["distance_to_spot"] = None
        zp["spot_inside_zone"] = None
        zp["tradeable_score"] = liquidity_zone_tradeable_score(
            n_tags=len(tags), n_opt=n_opt, inside=False, dist_pen=0.0, spot=None
        )
        return
    sf = float(spot)
    inside = lo <= sf <= hi
    if inside:
        d = 0.0
    else:
        d = min(abs(sf - lo), abs(sf - hi))
    zp["distance_to_spot"] = round(d, 4)
    zp["spot_inside_zone"] = inside
    dist_pen = min((d / sf) * 12.0, 10.0)
    zp["tradeable_score"] = liquidity_zone_tradeable_score(
        n_tags=len(tags), n_opt=n_opt, inside=inside, dist_pen=dist_pen, spot=sf
    )


@app.get("/api/liquidity-snapshot")
# SWITCH-LATENCY FIX: sync def → threadpool. This fires on every ticker switch (client
# setTimeout pollLiquiditySnapshot) and every 60s; it does a blocking Schwab bar fetch with
# no await, so as async it stalled the event loop on each switch.
def get_liquidity_snapshot(
    ticker: str = Query(default=DEFAULT_TICKER),
    date: Optional[str] = Query(default=None, description="Session date YYYY-MM-DD (default: today ET)"),
    snapshot: str = Query(
        default="premarket",
        description="live | premarket | opening | midday | afternoon. live = rolling cutoff (now ET) + optional options fusion",
    ),
    expiry: Optional[str] = Query(default=None, description="Expiry YYYY-MM-DD for fusion with cached /api/state walls"),
    fusion: bool = Query(default=True, description="When snapshot=live, merge options walls from state cache (needs expiry)"),
):
    """Return liquidity & value playbook snapshot (zones, summary, raw_levels) for ticker/session.
    Uses PlaybookConfig(clustering_mode='percent'). ``live`` uses min(now,RTH close) cutoff; checkpoints unchanged."""
    try:
        from polling_adapter import fetch_bars_via_schwab_for_session
        from liquidity_value_engine import build_live_snapshot, generate_liquidity_value_snapshot
        from liquidity_models import SnapshotType, PlaybookConfig

        session_date = date or now_et().strftime("%Y-%m-%d")
        ticker_upper = ticker.upper().strip()
        # TICKER-PREVIEW-NO-ENROLL: liquidity snapshot is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker_upper)
        client = get_client()
        from datetime import date as date_type

        session_date_obj = date_type.fromisoformat(session_date)
        bars = fetch_bars_via_schwab_for_session(
            client, ticker_upper, session_date_obj, include_extended_hours=True
        )
        if not bars:
            return JSONResponse(
                {"error": f"No bar data for {ticker_upper} on {session_date}"},
                status_code=404,
            )
        config = PlaybookConfig(clustering_mode="percent", max_zone_width=2.0)
        snap_raw = snapshot.lower().strip()
        fusion_status = "n/a"
        spot_for_zones: Optional[float] = None
        extra: list[tuple[float, str]] = []
        bar_merge_note = "schwab"

        if snap_raw == "live":
            today_ld = now_et().date()
            if session_date_obj == today_ld:
                from liquidity_value_engine import merge_schwab_bars_with_live_overlay

                _ov = _liquidity_live_1m_overlay_bars(ticker_upper)
                if _ov:
                    bars = merge_schwab_bars_with_live_overlay(bars, _ov)
                    bar_merge_note = "schwab+live_1m_overlay"

        if snap_raw == "live":
            extra = []
            if fusion and expiry:
                extra, spot_for_zones, fusion_status = _liquidity_fusion_from_cache(ticker_upper, expiry)
            elif fusion and not expiry:
                fusion_status = "no_expiry"
            else:
                fusion_status = "disabled"
            if spot_for_zones is None:
                spot_for_zones = _liquidity_spot_from_cache_any_expiry(ticker_upper)
            _extra_for_build = list(extra) if fusion else []
            if spot_for_zones is not None and fusion:
                _extra_for_build.append((spot_for_zones, "SPOT_LIVE"))
            # Phase 2A: this endpoint CARRIES the canonical snapshot; it does not compute
            # the Phase 2A families. MEASURED before this change, same instant, same
            # ticker: /api/levels overnight 773.3975/773.3975 vs this endpoint
            # 773.40/772.55 — one concept, two bar inputs, two answers on two screens.
            _canon = None
            if session_date_obj == now_et().date():
                from liquidity_value_engine import carry_snapshot_levels
                _canon = canonical_price_level_snapshot(ticker_upper)
                carry_snapshot_levels(_canon, "api.liquidity_snapshot")
            out = build_live_snapshot(
                ticker_upper,
                bars,
                session_date_obj,
                config,
                extra_levels=_extra_for_build if fusion else None,
                spot=spot_for_zones,
                canonical=_canon,
            )
            if spot_for_zones is None:
                _rv = (out.raw_levels or {}).get("vwap")
                if _rv is not None:
                    try:
                        spot_for_zones = float(_rv)
                    except (TypeError, ValueError):
                        spot_for_zones = None
        else:
            out = generate_liquidity_value_snapshot(
                ticker=ticker_upper,
                bars_dataframe=bars,
                session_date=session_date,
                snapshot_type=SnapshotType(snap_raw),
                config=config,
            )
        snapshot_val = out.snapshot_type.value
        zones_payload = []
        for z in out.zones:
            w = z.zone_high - z.zone_low
            merged = len(z.source_tags)
            zp = {
                "zone_type": z.zone_type.value,
                "zone_class": z.zone_class,
                "zone_low": z.zone_low,
                "zone_high": z.zone_high,
                "zone_mid": z.zone_mid,
                "zone_width": round(w, 4),
                "source_levels": z.source_levels,
                "source_tags": z.source_tags,
                "confluence_score": z.confluence_score,
                "merged_levels_count": merged,
                "interpretation_notes": z.interpretation_notes or "",
                "first_snapshot": snapshot_val,
                "last_snapshot": snapshot_val,
                "persistence": 1,
            }
            if snap_raw == "live":
                _liquidity_zone_tradeable_fields(zp, spot_for_zones)
            zones_payload.append(zp)
        if snap_raw == "live":
            zones_payload.sort(
                key=lambda x: (
                    x["distance_to_spot"] is None,
                    x["distance_to_spot"] if x["distance_to_spot"] is not None else 1e9,
                    -x.get("tradeable_score", 0),
                )
            )
        result = {
            "ticker": out.ticker,
            "symbol": ticker_upper,
            "session_date": out.session_date,
            "snapshot_type": snapshot_val,
            "zones": zones_payload,
            "summary": None,
            "raw_levels": out.raw_levels,
            "raw_levels_used": _build_raw_levels_used(out.raw_levels, snapshot_val),
        }
        if snap_raw == "live":
            result["fusion"] = fusion_status
            result["bar_merge"] = bar_merge_note
            result["as_of_cutoff_et"] = (out.raw_levels or {}).get("cutoff_et")
            result["expiry_used_for_fusion"] = expiry.strip() if expiry else None
            result["spot_used_for_scoring"] = spot_for_zones
            # Phase 2A carriage stamp: which snapshot generation these level values ARE.
            # Two carriers that agree on the number but not on the generation are still
            # two answers — the generation travels so the skew is visible, never silent.
            result["level_generation"] = _canon.generation if _canon is not None else None
            result["level_semantic_scope"] = (out.raw_levels or {}).get("semantic_scope")
            result["level_snapshot_as_of_ts_utc"] = (
                _canon.as_of_ts_utc if _canon is not None else None)
            result["level_bar_source"] = _canon.bar_source if _canon is not None else None
        if out.summary:
            result["summary"] = {
                "value_state": out.summary.value_state,
                "vwap_relation": out.summary.vwap_relation,
                "auction_interpretation": out.summary.auction_interpretation,
                "notes": out.summary.notes,
            }
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/liquidity-playbook-state")
# SWITCH-LATENCY FIX: sync def → threadpool (blocking Schwab bar fetch, no await).
def get_liquidity_playbook_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    date: Optional[str] = Query(default=None, description="Session date YYYY-MM-DD (default: today ET)"),
):
    """Return full PlaybookState with all four snapshots (premarket, opening, midday, afternoon).
    Each snapshot uses only data through its cutoff time (no lookahead)."""
    try:
        from polling_adapter import fetch_bars_via_schwab_for_session
        from liquidity_value_engine import generate_playbook_state, playbook_state_to_dict
        from liquidity_models import PlaybookConfig

        session_date = date or now_et().strftime("%Y-%m-%d")
        ticker_upper = ticker.upper().strip()
        # TICKER-PREVIEW-NO-ENROLL: playbook-state is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker_upper)
        client = get_client()
        from datetime import date as date_type
        session_date_obj = date_type.fromisoformat(session_date)
        bars = fetch_bars_via_schwab_for_session(
            client, ticker_upper, session_date_obj, include_extended_hours=True
        )
        if not bars:
            return JSONResponse(
                {"error": f"No bar data for {ticker_upper} on {session_date}"},
                status_code=404,
            )
        state = generate_playbook_state(
            ticker=ticker_upper,
            bars_dataframe=bars,
            session_date=session_date,
            config=PlaybookConfig(clustering_mode="percent", max_zone_width=2.0),
        )
        return playbook_state_to_dict(state)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/debug/charm")
# SWITCH-LATENCY FIX: sync def → threadpool (blocking chain fetch, no await).
def debug_charm(ticker: str = DEFAULT_TICKER):
    """Diagnose why charm is not computing."""
    try:
        ticker = ticker_storage_key(ticker or DEFAULT_TICKER)   # Cursor-audit F1: bare "SPX" -> "$SPX"
        # TICKER-PREVIEW-NO-ENROLL: charm diagnostic is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker)
        from math_exposure import compute_net_charm

        cl       = get_client()
        # RC-59: charm IS level math — the debug view must see the same width the product
        # computes on, or it debugs a different chain than the one that produced the number.
        # Cursor-audit A1: and the same index DATE bound — without to_date this fetched the full
        # multi-year $SPX book (no cap) and 502'd on the budget, unlike the product's bounded path.
        c_resp   = safe_get_chain(cl, ticker, strike_count=resolve_chain_strike_count(ticker),
                                  to_date=_chain_to_date_for(ticker, None))
        if c_resp is None or c_resp.status_code != 200:
            return {"error": f"Chain fetch failed: status={getattr(c_resp, 'status_code', 'None')}"}
        chain_json = c_resp.json()
        raw_cts: list[dict] = []
        for _side_key in ("callExpDateMap", "putExpDateMap"):
            _side_map = chain_json.get(_side_key) or {}
            if not isinstance(_side_map, dict):
                continue
            for _exp_map in _side_map.values():
                if not isinstance(_exp_map, dict):
                    continue
                for _strike_list in _exp_map.values():
                    if not isinstance(_strike_list, list):
                        continue
                    for _ct in _strike_list:
                        if isinstance(_ct, dict):
                            raw_cts.append(_ct)
        contracts = [dict(ct) for ct in raw_cts]

        # Sample first contract raw fields
        first_raw = raw_cts[0] if raw_cts else {}
        raw_keys  = list(first_raw.keys())

        # Check expiration fields
        sample_exp  = [ct.get("expirationDate") for ct in contracts[:5]]
        sample_dte  = [ct.get("daysToExpiration") for ct in contracts[:5]]

        # Schwab uses -999.0 as a "missing greek" sentinel. The has_* counters
        # below reflect contracts with USABLE greeks/IV (sentinel-aware: not
        # None, not -999.0, finite) so this debug surface honestly diagnoses
        # why charm is or isn't computing.
        usable_gamma = 0
        usable_delta = 0
        usable_theta = 0
        usable_vega = 0
        usable_iv = 0
        sentinel_gamma = 0
        has_oi = 0
        from numeric_contract import float_finite_or_none as _fin
        for ct in contracts:
            # single source: canonical finite reader for every greek. Raw float() admitted
            # NaN (the counts were already NaN-safe via inline isfinite gates, now folded
            # into the reader); MISSING_GREEK_SENTINEL is finite, survives the read, and is
            # excluded explicitly — behaviour-identical, one fewer finite-check faucet.
            _g = _fin(ct.get("gamma"))
            _d = _fin(ct.get("delta"))
            if gamma_is_plausible(_g, _d):
                usable_gamma += 1
            if ct.get("gamma") == MISSING_GREEK_SENTINEL:
                sentinel_gamma += 1
            if _d is not None and _d != MISSING_GREEK_SENTINEL:
                usable_delta += 1
            _t = _fin(ct.get("theta"))
            if _t is not None and _t != MISSING_GREEK_SENTINEL:
                usable_theta += 1
            _v = _fin(ct.get("vega"))
            if _v is not None and _v != MISSING_GREEK_SENTINEL:
                usable_vega += 1
            _iv = _fin(ct.get("volatility"))
            if _iv is not None and _iv > 0 and _iv != MISSING_GREEK_SENTINEL:
                usable_iv += 1
            if ct.get("openInterest"):
                has_oi += 1

        # What expiries exist?
        expiries     = _expiries_from_contracts(contracts)
        selected_exp = _default_expiry(expiries, ticker)

        # Try charm with all contracts, no filter
        # single source: finite spot via the canonical reader. Raw float() admitted a NaN
        # underlyingPrice, and the `spot <= 0` guard does NOT catch NaN (nan <= 0 is False),
        # so a NaN spot used to flow into compute_net_charm.
        from numeric_contract import float_finite_or_none as _fin
        spot = _fin(chain_json.get("underlyingPrice"))   # external-key-ok: Schwab chain JSON node
        if spot is None or spot <= 0:
            return {"error": f"underlyingPrice missing or zero in chain response for {ticker}"}
        charm_all = compute_net_charm(contracts, spot, selected_exp or "")

        return {
            "spot": spot,
            "total_contracts": len(contracts),
            "has_gamma": usable_gamma,
            "has_delta": usable_delta,
            "has_theta": usable_theta,
            "has_vega": usable_vega,
            "has_iv": usable_iv,
            "gamma_sentinel_count": sentinel_gamma,
            "has_oi": has_oi,
            "raw_keys_sample": raw_keys[:20],
            "sample_expirationDate": sample_exp,
            "sample_daysToExpiration": sample_dte,
            "expiries_found": expiries[:10],
            "selected_exp": selected_exp,
            "charm_result": charm_all,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


@app.get("/api/accuracy")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def get_accuracy(ticker: str = Query(default=DEFAULT_TICKER)):
    """Return prediction accuracy for a ticker.

    Returns cached results if available (updated every ~10 min),
    otherwise computes fresh. Also returns accuracy history for charting.
    """
    ticker = (ticker or DEFAULT_TICKER).upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: accuracy is a VIEW — touch last-seen only.
    _touch_tracked_ticker_view(ticker)

    db = get_db() if _HAS_SIGNALS else None
    if not db:
        return {"error": "Database not connected"}

    # Use cache if fresh enough
    _serving_version = _current_pred_model_version(ticker)
    cached = _accuracy_cache.get(ticker, {})
    if cached and time.time() - cached.get("ts", 0) < ACCURACY_INTERVAL:
        results = cached["results"]
        all_hours = cached.get("all_hours")
    else:
        try:
            # RTH-scoped is the trading-relevance primary; all-hours is audit
            # context (operator decision 2026-07-06). Empty RTH scope fails
            # closed (accuracy None) — never widened to all-hours silently.
            results = db.compute_accuracy(
                ticker, CANONICAL_TIMEFRAME, model_version=_serving_version,
                rth_only=True,
            )
            all_hours = db.compute_accuracy(
                ticker, CANONICAL_TIMEFRAME, model_version=_serving_version,
                rth_only=False,
            )
            _accuracy_cache[ticker] = {
                "ts": time.time(), "results": results, "all_hours": all_hours,
            }
        except Exception as e:
            return {"error": str(e)}

        # Pass 5a: persist accuracy snapshot per horizon when value
        # meaningfully changed vs last logged row (db.maybe_log_model_accuracy
        # handles the dedup epsilon). Throttled by the existing 10-min
        # ACCURACY_INTERVAL cache above — at most one INSERT per ticker per
        # horizon per ~10min.
        for _hz, _hz_res in (results or {}).items():
            if not isinstance(_hz_res, dict):
                continue
            try:
                _new_id = db.maybe_log_model_accuracy(
                    ticker=ticker,
                    timeframe=CANONICAL_TIMEFRAME,
                    model_version=_serving_version,
                    horizon=_hz,
                    total_predictions=int(_hz_res.get("total", 0) or 0),  # silent-zero-ok: a COUNT of rows returned — no rows is genuinely zero predictions, not an unmeasured quantity
                    correct_direction=_hz_res.get("correct"),
                    accuracy_pct=_hz_res.get("accuracy"),
                )
                if _new_id is not None:
                    log.info(
                        "model_accuracy ticker=%s horizon=%s acc=%s%% n=%s",
                        ticker, _hz,
                        _hz_res.get("accuracy"),
                        _hz_res.get("total"),
                    )
            except Exception as _mae:
                log.debug("log_model_accuracy ticker=%s hz=%s failed: %s", ticker, _hz, _mae)

    # Fetch history via Pass 5a reader (get_model_accuracy_history).
    history: list[dict] = []
    try:
        from ml_horizon import PRIMARY_DECISION_HORIZONS
        for _hz in PRIMARY_DECISION_HORIZONS:
            rows = db.get_model_accuracy_history(
                ticker=ticker,
                timeframe=CANONICAL_TIMEFRAME,
                model_version=_serving_version,
                horizon=_hz,
                limit=int(ACCURACY_HISTORY_LIMIT),
            )
            history.extend(rows)
    except Exception:
        history = []

    return {
        "ticker": ticker,
        "model_version": _serving_version,
        # Trading-relevance primary: RTH-scoped, with per-horizon baseline +
        # edge fields so raw accuracy cannot read as edge.
        "accuracy_scope": "rth_0930_1600_et",
        "current": _trader_accuracy_subset(results),
        # Audit context only — measured over every session the logger ran.
        "all_hours": _trader_accuracy_subset(all_hours or {}),
        "history": history,
    }


@app.get("/api/debug/prediction")
# SWITCH-LATENCY FIX: sync def → threadpool (blocking full _fetch_state, no await).
def debug_prediction(ticker: str = DEFAULT_TICKER):
    """Show exactly what the prediction engine is querying — non-production debug surface (R-011)."""
    if os.environ.get("ED_ALLOW_DEBUG_ENDPOINTS", "").strip().lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404, detail="debug endpoints disabled")
    try:
        state = _fetch_state(ticker, expiry=None, update_source="debug_endpoint")
        zone = state.get("zone", "?")
        vwap_side = state.get("vwap_side", "?")
        bias = state.get("bias_signal", "?")
        pin = state.get("pin_strength", "?")
        nd = state.get("net_delta", "?")
        ng = state.get("net_gamma", "?")
        gex_mag = state.get("gex_magnitude", "?")
        dex_mag = state.get("dex_magnitude", "?")
        samples = state.get("samples_used", "?")
        model_note = state.get("model_note", "?")
        session_bkt = state.get("session_bucket", "?")
        vix_bkt = state.get("vix_bucket", "?")

        # Count snapshots per zone in DB
        zone_counts = {}
        if _HAS_SIGNALS:
            db = get_db()
            if db:
                zone_counts = db.get_zone_distribution(ticker, CANONICAL_TIMEFRAME)

        return {
            "current_query": {
                "zone": zone,
                "vwap_side": vwap_side,
                "session_bucket": session_bkt,
                "vix_bucket": vix_bkt,
                "bias_signal": bias,
                "pin_strength": pin,
                "net_delta": nd,
                "net_gamma": ng,
                "gex_magnitude": gex_mag,
                "dex_magnitude": dex_mag,
            },
            "prediction_result": {
                "samples_used": samples,
                "model_note": model_note,
            },
            "db_zone_distribution": zone_counts,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
