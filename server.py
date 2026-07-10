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
import sys
import time
import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from collections import OrderedDict, defaultdict
from copy import deepcopy
from typing import Any, Dict, Optional
from dataclasses import asdict, dataclass

from time_et import now_et, RTH_OPEN_MINS, RTH_END_MINS

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


_log_calibration_logging_state_at_boot()

# ── Import all existing Ed Console modules (unchanged) ───────────────────────
from config import build_config, DEFAULT_TICKER
from schwab_client import (
    auth_is_refreshable,
    build_client_from_token,
    inspect_token_file,
    safe_get_chain,
    safe_get_quote,
    safe_get_price_history,
    SchwabAuthError,
)
from math_exposure import (
    MISSING_GREEK_SENTINEL,
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
    compute_gamma_flip, compute_gamma_void_zones, compute_level_density,
    compute_hvl, compute_max_pain, hvl_gamma_strength, max_pain_oi_strength,
    pick_gamma_pin_strike, exposures_have_dollar_gex, gex_magnitude_label, gex_regime_label,
    aggregate_net_gex, total_gex_dollars_at_strike, total_gamma_raw_at_strike,
    bucket_metric, compute_dealer_pressure_index, compute_hedging_flow_score,
    compute_gamma_gradient, compute_breakout_score,
    compute_pin_score, compute_vol_expansion_signal, compute_sweep_score,
    compute_sector_strength,
    compute_iwm_confluence,
    compute_volume_oi_ratio, compute_option_flow_imbalance,
    compute_smart_money_signal,
)
from math_snapshot_derive import derive_pressure_trend, derive_vwap_side
from market_context import (
    fetch_market_context,
    fetch_price_levels,
    market_context_panel_symbols_excluding_core,
    PriceLevels,
    _derive_session,
)
from market_state import build_market_state, derive_zone
from ml_horizon import PRIMARY_DECISION_HORIZONS, SECONDARY_SUPPORT_HORIZONS
from realized_contract_eval import serialize_option_chain_for_eval, build_replay_context_payload
from live_decision_bundle import stamp_decision_bundle, tick_triggers_coherent_refresh, persist_stamped_decision
from v2_decision import build_module_a_a1_decision
from v2_decision.a1_conformal_artifact_attachment import attach_a1_conformal_artifact_to_ms_dict
from v2_decision.a1_isotonic_calibration_attachment import attach_a1_isotonic_calibration_to_ms_dict

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
_schwab_chain_fetch_gate = threading.Semaphore(1)
CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC: float = 30.0
_chain_fetch_gate_timeout_count: int = 0


def _gated_safe_get_chain(client, ticker: str, *, strike_count):
    """safe_get_chain serialized behind the chain gate → (resp, gate_wait_sec, fetch_sec)."""
    global _chain_fetch_gate_timeout_count
    wait_started = time.monotonic()
    acquired = _schwab_chain_fetch_gate.acquire(timeout=CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC)
    gate_wait_sec = round(time.monotonic() - wait_started, 3)
    if not acquired:
        _chain_fetch_gate_timeout_count += 1
        log.warning(
            "chain_gate_timeout ticker=%s waited=%.3fs count=%s — proceeding ungated (fail-open)",
            ticker,
            gate_wait_sec,
            _chain_fetch_gate_timeout_count,
        )
    fetch_started = time.monotonic()
    try:
        resp = safe_get_chain(client, ticker, strike_count=strike_count)
    finally:
        if acquired:
            _schwab_chain_fetch_gate.release()
    return resp, gate_wait_sec, round(time.monotonic() - fetch_started, 3)

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
            log.warning(
                "duplicate L1 light SSE connections for scope %s from client %s (existing=%s)",
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
    ts = float(payload.get("_server_build_ts") or payload.get("as_of_ts") or 0.0)
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
    """Route-touch pool (Tier B/C JSON, streaming POST touch, L1 SSE subscribe)."""
    return _get_route_offload_executor()


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


def _submit_analytics_task(fn, *args, **kwargs):
    if _analytics_bg_shutdown:
        raise RuntimeError("analytics executor shutting down")
    return _get_analytics_executor().submit(fn, *args, **kwargs)


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


def _analytics_generated_ts(entry: dict) -> float:
    return float(entry.get("generated_at") or entry.get("ts") or 0.0)


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
        age = max(0.0, now - gen_ts) if gen_ts > 0 else 0.0
        ver = int(entry.get("analytics_version", 0))
        # Operator-facing stale = a recompute cycle was MISSED (age past the grace
        # window) or explicit error — not merely "older than one cadence beat".
        stale_after = float(ttl) * ANALYTICS_STALE_GRACE_CYCLES
        refresh_due = bool(sse_live or (age >= ttl))
        stale = bool(age >= stale_after) or bool(md.get("state_error"))
        iso = None
        if gen_ts > 0:
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
# Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE — quote_age_sec/bundle_age_sec/stale_reason_codes computed from existing fast_server_ts, _server_build_ts, quote_source_detail.carried_forward, quote_source_detail.schwab_auth_degraded
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
    if plane_quote and plane_quote.get("fast_server_ts") is not None:
        quote_ts_raw = plane_quote.get("fast_server_ts")
    elif md.get("fast_server_ts") is not None:
        quote_ts_raw = md.get("fast_server_ts")

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


def _schedule_sse_broadcast(payload: dict) -> None:
    if not payload or _main_event_loop is None or _main_event_loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(_broadcast_snapshot(payload), _main_event_loop)


def _maybe_broadcast_sse_cache_fanout(
    ticker: str,
    expiry: Optional[str],
    *,
    inflight_key: tuple,
    fanout_reason: str,
) -> bool:
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
        # Observability must never disturb the persistence tail.
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
        _submit_analytics_task(_work)
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
        if gen_ts > 0:
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
    hvl,
    max_pain,
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
    w0 = walls[0] if walls else None
    cs = consensus_summary
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
        "kl_gamma_flip": _float_key_level(gamma_flip),
        "kl_gamma_voids": gamma_voids or [],
        "kl_hvl": _float_key_level(hvl),
        "kl_max_pain": _float_key_level(max_pain),
        "kl_call_gamma_wall": _float_key_level(getattr(w0, "call_gamma_wall", None)),
        "kl_put_gamma_wall": _float_key_level(getattr(w0, "put_gamma_wall", None)),
        "kl_gamma_inflection": _float_key_level(getattr(cs, "gamma_inflection", None)),
        "kl_call_delta_wall": _float_key_level(getattr(w0, "call_delta_wall", None)),
        "kl_put_delta_wall": _float_key_level(getattr(w0, "put_delta_wall", None)),
        "kl_delta_inflection": _float_key_level(getattr(cs, "delta_inflection", None)),
        "kl_call_oi_wall": _float_key_level(getattr(w0, "call_oi_wall", None)),
        "kl_put_oi_wall": _float_key_level(getattr(w0, "put_oi_wall", None)),
        "kl_gamma_pin": _float_key_level(getattr(cs, "gamma_pin", None)),
        "kl_oi_center": _float_key_level(getattr(cs, "oi_center", None)),
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
            asyncio.run_coroutine_threadsafe(_broadcast_snapshot(payload), _main_event_loop)
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
#   card_freshness quote ages simply read fresher fast_server_ts.
# SCHWAB_CSV_CHECKED
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
    fts = row.get("fast_server_ts")
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
    q_resp = _safe_get_quote_with_retry(client, tkr, attempt_hook=_attempt_hook)
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
        "fast_server_ts": quote_ts,
        "quote_time_source": "schwab_rest_quote" if quote_ts is not None else "unavailable",
        "server_received_ts": server_received_ts,
        "quote_ingestion": quote_ingestion,
        "quote_source_detail": {
            "spot": spot_source or "unavailable_missing_last_and_mark",
            "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
            "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
            "mid": mid_source or "unavailable_missing_mark_and_bid_ask",
            "spread": "schwab_bid_ask" if spread_frac is not None else "unavailable_missing_bid_or_ask",
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
        ts = float(entry.get("ts") or 0.0)
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
RTH_CLOSE_MINS:      int   = 960    # 4:00 PM ET  (used for mins_to_close calc)
PRE_MARKET_MINS:     int   = 540    # 9:00 AM ET  (logger session buffer start)
LOGGER_BUFFER_MINS:  int   = 990    # 4:30 PM ET  (logger session buffer end)
# NOTE: session_label ("RTH"/"Pre-Market"/"After-Hours"/"Closed") is derived ONCE
# from SPY's quote in market_context._derive_session(), stored on MarketContext.session_label,
# and stamped on the per-request bundle as a global market state.
MARKET_CLOSE_HOUR:   float = 16.0   # 4:00 PM ET (used for hours-remaining calc)

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
CHAIN_STRIKE_COUNT:  int   = 20     # strikes per expiry fetched from Schwab

# Exposure windows
EXPOSURE_WINDOWS:    list  = [5, 10, 15, 20]   # window sizes passed to build_*_rows

# GEX near-spot window for breakout score
GEX_NEAR_SPOT_RADIUS: float = 2.0   # strikes within $2 of spot are "near spot"

# Void factor distance falloff
VOID_DIST_FALLOFF:   float = 5.0    # $5 from void edge → factor decays to 0

# GARCH horizon
GARCH_HORIZON_BARS:  int   = 13     # forward-looking bars for GARCH forecast (~1hr RTH)

# IV history lookback for IV rank / percentile
IV_HISTORY_LOOKBACK: int   = 5000   # max rows pulled from DB for IV rank calc

# Parity residual minimum to display synthetic forward
PARITY_RESID_MIN:    float = 0.10   # ignore residuals smaller than 10 cents

# Accuracy history display limit
ACCURACY_HISTORY_LIMIT: int = 50    # rows returned by get_accuracy_history
RECENT_CROSSES_DISPLAY_LIMIT: int = 5  # level-cross events in operator UI
STATE_ERROR_DETAIL_MAX_CHARS: int = 120  # truncate exception detail strings for UI / log carry
PRICE_LEVELS_CACHE_SEC: int = 15  # intraday VWAP refresh (process-local)
# Builds OHLC bars from spot price ticks. Server polls every ~30s, so:
#   5-min bars = ~10 ticks per bar
#   1-min bars = ~2 ticks per bar
# Bars are keyed by ticker. Completed bars stored in ring buffer; maxlen from math_exposure.
# ─────────────────────────────────────────────────────────────────────────────
from math_exposure import CANDLE_5M_MAX_BARS, CANDLE_1M_MAX_BARS
from micro_structure import Candle
from timeframe_config import CANONICAL_TIMEFRAME

class _CandleAccumulator:
    """Accumulate spot ticks into OHLCV candle bars."""

    def __init__(self, bar_seconds: int, max_bars: int):
        self.bar_seconds = bar_seconds
        self.max_bars = max_bars
        self._bars: dict[str, list[Candle]] = {}       # ticker -> completed bars
        self._current: dict[str, dict] = {}             # ticker -> {ts, o, h, l, c, v}
        self._prev_total_vol: dict[str, float] = {}    # ticker -> prior totalVolume for delta
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
        vol_source = "schwab_quote_totalVolume_delta"

        # Compute volume delta; reset if value drops (new session)
        if total_now is not None and prev is not None:
            delta = total_now - prev
            vol_delta = max(0.0, delta) if delta >= 0 else 0.0
            if delta < 0:
                prev = None
                vol_source = "schwab_quote_totalVolume_session_reset"
        else:
            vol_delta = None
        if total_now is not None:
            self._prev_total_vol[ticker] = total_now
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
                cur["v"] = (cur.get("v") or 0.0) + vol_delta
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
#   • Live Operator Mode (Step 1): during RTH with any SSE viewer connected, non-trio
#     rotation returns skipped:live_operator_mode — see _live_operator_mode_active.
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

    ``panel_auto`` rows mirror ``market_context.py`` cross-panel quote symbols (excluding core duplicates)
    for enrollment tracking and thin ``confluence_quote_ticks`` logging — not full snapshot rotation.

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
            if row.get("category") in ("user_persisted", "pinned"):
                t = (row.get("ticker") or "").upper().strip()
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
    """Re-merge CORE + user_persisted + pinned from DB (startup / heal drift). Issue 22."""
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
        merged = list(CORE_TICKERS)
        for row in db.logging_universe_list_rows():
            if row.get("category") in ("user_persisted", "pinned"):
                t = (row.get("ticker") or "").upper().strip()
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


def _is_loggable_session() -> bool:
    """
    Background snapshot logging session gate (Issue 22 — explicit product policy).

    When RTH_ONLY is True (default): allow ET minutes in [PRE_MARKET_MINS, LOGGER_BUFFER_MINS]
    (see server.py constants — ≈ 9:00 pre through extended post-market buffer).

    When RTH_ONLY is False: no session gate here (logging may run when markets are quiet —
    use only for diagnostics).
    """
    if not RTH_ONLY:
        return True
    et = now_et()
    mins = et.hour * 60 + et.minute
    return PRE_MARKET_MINS <= mins <= LOGGER_BUFFER_MINS


def _add_logger_ticker(ticker: str, *, enrollment_source: str = "ui_auto") -> bool:
    """
    Add a symbol to the in-memory logger cycle and durable logging_universe (Issue 22).
    Returns True if newly appended to _logger_tickers.
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
            return True
    return False


def _register_tracked_ticker(ticker: str, *, enrollment_source: str = "ui_auto") -> bool:
    """
    Enroll a user-facing symbol: background logger + ml_scheduler user-ticker file.
    Issue 22: user symbols persist in EdDB.logging_universe (survives restarts).
    Returns True if newly added to the logger rotation list.
    """
    t = (ticker or "").upper().strip()
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


def _get_mkt_ctx(client, pcr=None, prev_pcr=None):
    """Return cached global market context, refreshing if stale.

    This is the KEY optimization: VIX + SPY/QQQ/IWM + 9 constituents +
    4 IWM sectors = 17 API calls. Previously called per-ticker (3+ tickers
    = 51+ duplicate calls). Now called ONCE per cycle.
    """
    global _cached_mkt_ctx, _cached_mkt_ctx_ts
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

    # Cache is stale — fetch fresh
    _stream_chg_fn = None
    try:
        from order_flow_live_state import get_stream_chg_pct
        _stream_chg_fn = get_stream_chg_pct
    except (ImportError, AttributeError):
        pass
    try:
        ctx = fetch_market_context(
            client,
            safe_get_quote_fn=_safe_get_quote_with_retry,
            pcr=pcr,
            prev_pcr=prev_pcr,
            stream_chg_pct_fn=_stream_chg_fn,
        )
        if getattr(ctx, "error", None):
            log.warning(f"fetch_market_context returned error: {ctx.error}")
    except Exception as e:
        log.warning(f"fetch_market_context failed: {e}")
        from market_context import MarketContext
        ctx = MarketContext()
    with _cached_mkt_ctx_lock:
        _cached_mkt_ctx = ctx
        _cached_mkt_ctx_ts = mkt_ctx_cache_eval_wall_ts
    if _HAS_SIGNALS:
        try:
            from db import build_ts_et
            from market_context import confluence_quote_rows_from_context
            from time_et import now_et

            _qrows = confluence_quote_rows_from_context(
                ctx,
                ts_utc=mkt_ctx_cache_eval_wall_ts,
                ts_et=build_ts_et(now_et()),
            )
            if _qrows:
                get_db().upsert_confluence_quote_ticks(_qrows)
        except Exception as e:
            log.debug("confluence_quote_ticks persist: %s", e, exc_info=True)
    return ctx


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
    fresh = _get_mkt_ctx(client, pcr=pcr, prev_pcr=prev_pcr)
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


def _logger_fetch_and_log(ticker: str) -> str:
    """
    Fetch data for one ticker and log a snapshot to the DB.
    Returns 'ok:fetch', 'skipped:closed', 'skipped:confluence_quote_only',
    'skipped:live_operator_mode', or 'error:<msg>'.
    Never raises — always returns a status string.
    """
    try:
        if not _is_loggable_session():
            return "skipped:closed"

        try:
            from money_path_ticker_tiers import should_skip_background_full_snapshot
            from scheduler_user_tickers import panel_auto_ticker_set

            if should_skip_background_full_snapshot(
                ticker, panel_auto_ticker_set(str(get_db().db_path))
            ):
                return "skipped:confluence_quote_only"
        except Exception as e:
            log.debug("panel_auto logger skip check: %s", e, exc_info=True)

        # LIVE_OPERATOR_MODE_RESET_V1 Step 1 — hard skip: non-trio full capture defers
        # to no-viewer windows (Research Mode). SPY/QQQ/IWM are never gated here and
        # keep full rotation capture plus the dedicated base money-path logger.
        from money_path_ticker_tiers import is_base_money_path_ticker

        if not is_base_money_path_ticker(ticker) and _live_operator_mode_active():
            return "skipped:live_operator_mode"

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

        return "ok:fetch"

    except Exception as e:
        err = str(e)[:STATE_ERROR_DETAIL_MAX_CHARS]
        log.warning(f"Logger: {ticker} failed — {err}")
        with _logger_lock:
            _logger_stats.setdefault(ticker, {})
            _logger_stats[ticker]["last_error"] = err
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

        q_resp = _safe_get_quote_with_retry(client, t)
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
            ent = arch.get(str(ticker).upper().strip()) if isinstance(arch, dict) else None
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
                    "authoritative_stage": ent.get("authoritative_stage")
                    or ent.get("signal_chain_authoritative"),
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
    rules_ok = bool(
        ms_dict.get("rules_headline")
        or ms_dict.get("micro_5m_headline")
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
            raw_a = arch_ent.get("authoritative_stage") or arch_ent.get("signal_chain_authoritative")
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
    exp_key = str(selected_exp or "")[:10]
    side_key = str(preferred_side or "").upper().strip()
    try:
        strike_key = float(preferred_strike) if preferred_strike is not None else None
    except (TypeError, ValueError):
        strike_key = None

    matches: list[dict] = []
    for ct in contracts or []:
        exp = str(ct.get("expirationDate") or "")[:10]
        if exp_key and exp != exp_key:
            continue
        if side_key in ("CALL", "PUT") and str(ct.get("putCall") or "").upper().strip() != side_key:
            continue
        if strike_key is not None:
            try:
                if abs(float(ct.get("strikePrice")) - strike_key) >= 0.01:
                    continue
            except (TypeError, ValueError):
                continue
        matches.append(ct)

    if not matches and (side_key or strike_key is not None):
        return _selected_schwab_days_to_expiration(contracts, selected_exp)

    for ct in matches:
        raw_dte = ct.get("daysToExpiration")
        try:
            dte = int(float(raw_dte)) if raw_dte is not None else None
        except (TypeError, ValueError):
            dte = None
        if dte is not None and dte >= 0:
            return dte
    return None


def _snapshot_expiry_hours_from_schwab_dte(
    schwab_dte: int | None,
    now_et: datetime,
) -> float | None:
    if schwab_dte is None:
        return None
    market_close = now_et.replace(hour=int(MARKET_CLOSE_HOUR), minute=0, second=0, microsecond=0)
    if schwab_dte == 0:
        secs = (market_close - now_et).total_seconds()
        return round(secs / 3600.0, 2) if secs > 0 else None
    if schwab_dte > 0:
        return round((schwab_dte * 24.0) + max(0.0, (market_close - now_et).total_seconds() / 3600.0), 2)
    return None


def _fetch_expiries_light(ticker: str) -> list[str]:
    """
    Option expiries only — quote + option chain, no snapshot insert or MarketState.
    Used by /api/expiries when cache is cold (avoids logging a DB row per dropdown poll).
    """
    ticker = ticker.upper().strip()
    client = get_client()
    c_resp = safe_get_chain(
        client, ticker,
        strike_count=CHAIN_STRIKE_COUNT,
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
    """Safe float for quote fields."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
# HELPER — compute VWAP from candle bars (seeded from price history)
# Used as fallback when fetch_price_levels returns vwap=None (individual equities).
# ─────────────────────────────────────────────────────────────────────────────
def _compute_vwap_from_bars(
    bars: list,
    *,
    source_bars: str = "schwab_quote_totalVolume_delta",
) -> tuple[Optional[float], str]:
    """Compute VWAP = Σ(typical_price × volume) / Σ(volume) from completed bars.

    Returns (vwap, source_bars). ``source_bars`` documents Schwab leaf lineage
    (pricehistory vs quote totalVolume delta per Day 1 OHLCV contract).
    """
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for b in bars:
        if b.volume is None or float(b.volume) <= 0:
            continue
        tp = (float(b.high) + float(b.low) + float(b.close)) / 3.0
        cum_tp_vol += tp * float(b.volume)
        cum_vol += float(b.volume)
    if cum_vol > 0:
        return round(cum_tp_vol / cum_vol, 4), source_bars
    return None, source_bars


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
    """
    OF signature for debounced quote materiality only — hybrid: input probe + cadence + periodic refresh.
    Does not replace _project_l1; skips redundant OrderFlowEngine.compute when safe.
    """
    from planes.context_light import (
        build_order_flow_input_probe,
        compute_order_flow_compact,
        order_flow_compact_signature,
    )
    from planes.l1_runtime import (
        L1_OF_MIN_COMPUTE_INTERVAL_SEC,
        L1_OF_PROBE_FORCE_REFRESH_SEC,
    )

    tkr = ticker.upper().strip()
    row = _lmp.get_quote(tkr)
    now_mono = time.monotonic()
    probe = build_order_flow_input_probe(tkr, row)

    last_sig = _l1_of_sig_cache_by_ticker.get(tkr)
    last_probe = _l1_of_probe_by_ticker.get(tkr)
    last_eng_mono = _l1_of_last_engine_mono_by_ticker.get(tkr, 0.0)

    if (
        last_sig is not None
        and last_probe is not None
        and probe == last_probe
        and (now_mono - last_eng_mono) < L1_OF_PROBE_FORCE_REFRESH_SEC
    ):
        _l1_instrumentation["l1_of_quote_hook_reuse_total"] += 1
        return last_sig

    if last_sig is not None and (now_mono - last_eng_mono) < L1_OF_MIN_COMPUTE_INTERVAL_SEC:
        if (now_mono - last_eng_mono) < L1_OF_PROBE_FORCE_REFRESH_SEC:
            _l1_instrumentation["l1_of_quote_hook_reuse_total"] += 1
            return last_sig

    ofc = compute_order_flow_compact(tkr, row)
    sig = order_flow_compact_signature(ofc)
    _l1_of_probe_by_ticker[tkr] = probe
    _l1_of_sig_cache_by_ticker[tkr] = sig
    _l1_of_last_engine_mono_by_ticker[tkr] = now_mono
    _l1_instrumentation["l1_of_quote_hook_engine_total"] += 1
    return sig


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
    ms = float(out.get("l1_pipeline_ms") or 0.0)
    _l1_instrumentation["l1_build_total"] += 1
    _l1_instrumentation["l1_build_ms_sum"] = float(_l1_instrumentation["l1_build_ms_sum"]) + ms
    _l1_instrumentation["l1_build_by_reason"][reason] += 1
    out["l1_instrumentation"] = {
        "l1_build_total": int(_l1_instrumentation["l1_build_total"]),
        "l1_build_reason": reason,
        "l1_build_ms": round(ms, 3),
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


def _l1_on_l2_snapshot_ready(ticker: str, expiry: Optional[str]) -> None:
    """L2 acknowledged snapshot available — refresh L1 merge against new version."""
    _project_l1(ticker, expiry, reason="l2_snapshot_ready")


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
    gen = int(payload.get("l1_generation") or 0)
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
        ts = float(v.get("ts") or 0.0)
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
        q_resp = _safe_get_quote_with_retry(client, tkr)
        if q_resp and q_resp.status_code == 200:
            q_json = q_resp.json()
            _node = q_json.get(tkr.upper()) or q_json.get(tkr) or {}
            pq = _parse_quote_node_session_fields(_node)
            spot_source = pq["spot_source"]
            spot = pq["spot"]
            bid, ask = pq["bid"], pq["ask"]
            pq_mark = pq["mark"]
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
                    "fast_server_ts": quote_ts,
                    "quote_time_source": "schwab_rest_quote" if quote_ts is not None else "unavailable",
                    "server_received_ts": server_received_ts,
                    "fast_generation_id": _lmp.next_fast_generation(tkr),
                    "quote_source_detail": {
                        "spot": spot_source,
                        "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
                        "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
                        "mid": "unavailable_missing_mark_and_bid_ask",
                        "spread": "unavailable_missing_bid_or_ask",
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
    bid = row.get("bid")
    ask = row.get("ask")
    spread_dollar = None
    if bid is not None and ask is not None:
        try:
            spread_dollar = round(float(ask) - float(bid), 4)
        except (TypeError, ValueError):
            pass
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
        "fast_server_ts": row.get("fast_server_ts"),
        "fast_generation_id": row.get("fast_generation_id"),
        "_live_plane_fast_ts": row.get("fast_server_ts"),
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
    """Stamp immutable decision_id + release_id and persist for I-31 reconstruction."""
    stamp_decision_bundle(ms_dict, route=route)
    if _HAS_SIGNALS and ms_dict.get("decision_id"):
        try:
            from db import DB_PATH

            persist_stamped_decision(ms_dict, route=route, db_path=DB_PATH)
        except Exception as exc:
            log.warning("production decision persist failed route=%s: %s", route, exc)
    return ms_dict


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

    # ── Global market context — session_label before quote parse (shared across tickers) ──
    if mkt_ctx is None:
        mkt_ctx = _get_mkt_ctx(client)
    session_label = mkt_ctx.session_label   # "RTH" | "Pre-Market" | "After-Hours" | "Closed"

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
    try:
        # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1: log_only joins the
        # shutdown inline path — background pipelines stay out of the shared
        # route pool; operator-facing recomputes keep bounded parallelism.
        if _analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only):
            c_resp, _chain_gate_wait_sec, _chain_fetch_pure_sec = _gated_safe_get_chain(
                client, ticker, strike_count=CHAIN_STRIKE_COUNT
            )
            q_resp = _safe_get_quote_with_retry(client, ticker)
        else:
            # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: leaf futures run on
            # the dedicated recompute-leaf pool — never behind serve bodies.
            _cq_pool = _get_recompute_leaf_executor()
            _chain_fut = _cq_pool.submit(
                _gated_safe_get_chain, client, ticker, strike_count=CHAIN_STRIKE_COUNT
            )
            _quote_fut = _cq_pool.submit(_safe_get_quote_with_retry, client, ticker)
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
    if c_resp is None or c_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Chain fetch failed")
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
    contracts     = [dict(ct) for ct in contracts_raw]
    _t_after_chain_mono = time.monotonic()

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
        raise HTTPException(status_code=502, detail="Quote fetch failed")
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
    spot = parsed_last if parsed_last and parsed_last > 0 else (
        parsed_mark if parsed_mark and parsed_mark > 0 else None
    )
    bid    = parsed_bid
    ask    = parsed_ask

    global _last_spread_by_ticker, _last_spread_ts_by_ticker
    _quote_spread_pts = (
        round(float(ask) - float(bid), 4) if (bid is not None and ask is not None) else None
    )
    _quote_mid_for_spread = None
    if parsed_mark is not None and parsed_mark > 0:
        _quote_mid_for_spread = float(parsed_mark)
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
                _seed_pool = _get_recompute_leaf_executor()
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
        pick_gamma_pin_strike(exposures, _gamma_strikes, institutional=True)
        if _gamma_strikes
        else None
    )

    rows      = build_summary_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS)
    walls     = build_walls_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS)
    totals    = build_totals_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS, contracts_for_iv=contracts_use)

    # ── Gamma Flip + Void Zones ───────────────────────────────────────────────
    _gamma_flip = compute_gamma_flip(exposures, spot_f)
    _gamma_voids = compute_gamma_void_zones(exposures, spot_f)
    _hvl = compute_hvl(exposures)
    _max_pain = compute_max_pain(exposures)

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
        _charm_raw = compute_net_charm(
            contracts_use, spot_f, selected_exp, drift_toward_strike=_institutional_pin
        )
        _charm_used = _charm_raw.get("contracts_used", 0)
        _charm_err  = _charm_raw.get("error", "")
        if _charm_used > 0:
            _charm_net     = _charm_raw["net_charm_daily"]
            _charm_dir     = _charm_raw["charm_direction"]
            _charm_toward  = _charm_raw.get("drift_toward")
            _charm_mag     = _charm_raw.get("charm_magnitude")
            _charm_drivers = _charm_raw.get("top_drivers", [])
            log.info(f"Charm: {ticker} ✅ net={_charm_net:.0f} dir={_charm_dir} mag={_charm_mag} pin={_charm_toward} "
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
            hvl=_hvl,
            max_pain=_max_pain,
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
    # PDH / PDL / PDC / ORB don't change during a trading day — cache by date.
    # VWAP does change intraday so we still refresh every 60s within the day.
    _today_date_str = now_et.strftime("%Y-%m-%d")
    _pl_cache_entry = _state_cache.get(_cache_key, {}).get("price_levels")
    _pl_cache_date  = _state_cache.get(_cache_key, {}).get("pl_date", "")
    _pl_cache_mono = _state_cache.get(_cache_key, {}).get("pl_mono", None)

    _now_mono = time.monotonic()
    _pl_stale = (
        _pl_cache_entry is None
        or _pl_cache_date != _today_date_str          # new trading day → force refresh
        or _pl_cache_mono is None
        or (_now_mono - float(_pl_cache_mono)) >= PRICE_LEVELS_CACHE_SEC  # intraday VWAP refresh (process-local)
    )

    if not _pl_stale:
        price_levels = _pl_cache_entry
    else:
        try:
            price_levels = fetch_price_levels(client, symbol=ticker, quote_raw=q_json)
            if price_levels.error:
                log.warning(f"PriceLevels: {ticker} partial error: {price_levels.error}")
            if price_levels.vwap is None and price_levels.bars_today > 0:
                log.warning(f"PriceLevels: {ticker} has {price_levels.bars_today} bars but VWAP is None")
            elif price_levels.vwap is not None:
                log.debug(f"PriceLevels: {ticker} VWAP={price_levels.vwap:.2f} bars={price_levels.bars_today}")
        except Exception as e:
            log.warning(f"PriceLevels: {ticker} FAILED: {e}")
            price_levels = PriceLevels()
        # Cache with date key so PDH/PDL/ORB survive restarts within the same day
        _sc = _state_cache.get(_cache_key, {})
        _sc["price_levels"] = price_levels
        _sc["pl_date"]      = _today_date_str
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
    _hours_rem = max(0.0, (MARKET_CLOSE_HOUR * 60 - (now_et.hour * 60 + now_et.minute)) / 60.0)
    _kl_em_anchor = "unavailable"
    _mc_iv_level = None
    _mc_iv_source = "unavailable"

    try:
        _today_open = getattr(price_levels, "today_open", None)

        # ATM straddle: find ATM call + put mark from chain
        _all_strikes = sorted(set(
            float(ct.get("strikePrice"))
            for ct in contracts_use
            if ct.get("strikePrice") is not None
        ))
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
        _em_up = _em_straddle.get("upper") or _em_iv.get("upper")
        _em_lo = _em_straddle.get("lower") or _em_iv.get("lower")
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
    if _atr is None and _bars:
        log.warning(f"ATR NULL for {ticker}: only {len(_bars)} bars, need 16")
    elif _atr is None:
        log.warning(f"ATR NULL for {ticker}: no bars, need 16")

    # ── GARCH Volatility Forecast ─────────────────────────────────────────────
    _garch_sigma_bars = None
    try:
        if _closes and len(_closes) > 20:
            _garch_raw = compute_garch_forecast(_closes, horizon=GARCH_HORIZON_BARS)
            if _garch_raw:
                from volatility_regime import vol_percent_to_decimal

                _iv_dec = vol_percent_to_decimal(_atm_iv)
                _rv_dec = vol_percent_to_decimal(_realized_vol)
                _garch_sigma_bars = blend_garch_sigma(
                    _garch_raw, _iv_dec, _rv_dec, spot_f
                )
    except Exception as e:
        log.debug(f"GARCH forecast calc: {e}")

    # ── Order Flow Signals (from option volume + bid/ask size) ────────────────
    _vol_oi_ratio = {}
    _flow_imbalance = {}
    _smart_money = {}
    _iv_model_spread = {}
    try:
        _vol_oi_ratio = compute_volume_oi_ratio(exposures, spot_f)
    except Exception as e:
        log.debug(f"Order flow signals calc: {e}")
    try:
        _flow_imbalance = compute_option_flow_imbalance(exposures, spot_f)
    except Exception as e:
        log.warning(f"flow_imbalance failed: {e}")
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

        # 5. Pin Score
        _pin_strike = getattr(consensus_summary, "gamma_pin", None) if consensus_summary else None
        _gex_at_pin = None
        _oi_at_pin = None
        if _pin_strike and exposures:
            _pin_bkt = exposures.get(float(_pin_strike), {})
            if exposures_have_dollar_gex(exposures):
                _gex_at_pin = total_gex_dollars_at_strike(_pin_bkt)
            else:
                _gex_at_pin = total_gamma_raw_at_strike(_pin_bkt)
            _oi_at_pin = _bucket_total_oi(_pin_bkt)
        _oi_concentration = (_oi_at_pin / _sum_oi) if _oi_at_pin is not None and _sum_oi and _sum_oi > 0 else None
        try:
            _pin_score_val = compute_pin_score(_gex_at_pin, _oi_concentration)
        except Exception as e:
            log.warning(f"pin_score failed: {e}")
            _pin_score_val = {}

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
    try:
        _vol_envelope = compute_volatility_envelope(spot_f, _atr)

        # Build levels dict for density check
        _all_levels = {}
        if consensus_summary:
            for attr in ['gamma_pin', 'oi_center']:
                v = getattr(consensus_summary, attr, None)
                if v: _all_levels[attr] = float(v)
        for name, var in [
            ('call_gamma_wall', '_cgw'), ('put_gamma_wall', '_pgw'),
            ('call_delta_wall', '_cdw'), ('put_delta_wall', '_pdw'),
            ('gamma_inflection', '_gi'), ('delta_inflection', '_di'),
            ('call_oi_wall', '_cow'), ('put_oi_wall', '_pow'),
            ('call_vanna_wall', '_cvw'), ('put_vanna_wall', '_pvw'),
        ]:
            v = locals().get(var)
            if v: _all_levels[name] = float(v)
        if _gamma_flip: _all_levels['gamma_flip'] = float(_gamma_flip)
        if _em_up: _all_levels['em_upper'] = float(_em_up)
        if _em_lo: _all_levels['em_lower'] = float(_em_lo)
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

        # IWM deep confluence analysis (VIX direction from $VIX tracker, not IV tracker)
        if getattr(mkt_ctx, "vix", None) is not None:
            try:
                _vix_tracker.tick(float(mkt_ctx.vix))
            except (TypeError, ValueError):
                pass
        _vix_dir_for_confluence = (
            _vix_tracker.direction if getattr(mkt_ctx, "vix", None) is not None else None
        )
        _iwm_deep = compute_iwm_confluence(
            spy_chg=mkt_ctx.spy_chg_pct,
            qqq_chg=mkt_ctx.qqq_chg_pct,
            iwm_chg=mkt_ctx.iwm_chg_pct,
            kre_chg=_sector_data.get('KRE'),
            xbi_chg=_sector_data.get('XBI'),
            psci_chg=_sector_data.get('PSCI'),
            xrt_chg=_sector_data.get('XRT'),
            vix_level=mkt_ctx.vix,
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
        flow_imbalance=_flow_imbalance.get("normalized") if _flow_imbalance else None,
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
            flow_imbalance=(_flow_imbalance.get("normalized") if _flow_imbalance else None),
            net_gamma=ms.net_gamma,
            atr=_atr,
            candle_range_pts=_c_range,
            candle_body_pts=_candle_body,
            order_flow_score=ms.order_flow_score,
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
    _pre_publish_prev_vix = _state_cache.get(_cache_key, {}).get("vix")

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
        if _ed_db:  # snapshot INSERT, bars persist + outcome backfill all throttled (see ED_DB_SNAPSHOT_THROTTLE)
            if _diag_on():
                _diag_step("pre_db_snapshot", ticker)
            # Reservation lifecycle: released in the except below iff the insert never
            # landed (failure between reserve and insert must not burn the minute;
            # releasing after a landed insert would re-open it). Initialized before
            # the try so the handler can never NameError.
            _snap_ts = _refresh_ts_utc
            _do_insert = False
            _snap_insert_landed = False
            try:
                from db import SnapshotRow, build_ts_et
                from math_exposure import _f as _mf
                _do_insert = _snapshot_row_insert_allowed(ticker, _snap_ts, db=_ed_db)
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
                    _hours_to_expiry = _snapshot_expiry_hours_from_schwab_dte(_dte, _et_now)
    
                    # ── Compute fields from available data ─────────────────────────────
    
                    # Candle OHLC from canonical (1m) accumulator's current bar
                    _cur_bar = _candles_1m._current.get(ticker)
                    _c_open  = _cur_bar["o"] if _cur_bar else None
                    _c_high  = _cur_bar["h"] if _cur_bar else None
                    _c_low   = _cur_bar["l"] if _cur_bar else None
                    _c_close = _cur_bar["c"] if _cur_bar else None
                    _c_range = round(_c_high - _c_low, 4) if (_c_high and _c_low) else None
                    # _c_vol computed above before build_market_state
    
                    # VWAP distance
                    _vwap = getattr(price_levels, "vwap", None)
                    _vwap_f = float(_vwap) if _vwap is not None else None
                    # Fallback: compute VWAP from seeded candle bars when price_levels has none.
                    # This fixes ~87% NaN rate for individual equities whose price_levels.vwap
                    # comes back empty because the API call fails or returns no intraday data.
                    if _vwap_f is None:
                        _bars_for_vwap = _candles_1m.get_bars(ticker)
                        if _bars_for_vwap:
                            _vwap_f, _vwap_source_bars = _compute_vwap_from_bars(
                                _bars_for_vwap,
                                source_bars=_candles_1m.get_bars_source(ticker),
                            )
                            if _vwap_f is not None:
                                log.debug(
                                    "VWAP: %s computed from %s bars: %.4f",
                                    ticker,
                                    _vwap_source_bars,
                                    _vwap_f,
                                )
                    if _vwap_f is None:
                        _pl_vwap = getattr(price_levels, "vwap", None)
                        _n_bars = len(_bars_for_vwap) if _bars_for_vwap else 0
                        # Schwab index symbols ($SPX, $VIX, $NDX, etc.) don't carry intraday
                        # volume data; VWAP (price × volume sum) cannot compute by definition.
                        # Steady-state DEBUG for those; WARNING for real tickers where bars
                        # present + VWAP failed indicates a data-quality issue.
                        _is_index_symbol = isinstance(ticker, str) and ticker.startswith("$")
                        _vwap_log = log.debug if _is_index_symbol else log.warning
                        _vwap_log(
                            "VWAP failed for %s: price_levels=%s bars=%s — writing NULL",
                            ticker, _pl_vwap, _n_bars,
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
    
                    # Pin width (call gamma wall - put gamma wall)
                    _pin_w = round(_cgw - _pgw, 4) if (_cgw and _pgw) else None
    
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
    
                    # VIX vs previous (captured pre-publish — see _pre_publish_prev_vix)
                    _prev_vix = _pre_publish_prev_vix
                    _vix_vs_prev = None
                    if mkt_ctx.vix is not None and _prev_vix is not None:
                        _vix_vs_prev = round(mkt_ctx.vix - _prev_vix, 4)
    
                    # Track VIX direction across refreshes
                    _vix_tracker.tick(mkt_ctx.vix)
                    _vix_dir = _vix_tracker.direction
    
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
                        gamma_pin=getattr(consensus_summary, "gamma_pin", None) if consensus_summary else None,
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
                        vix_level=mkt_ctx.vix,
                        vix_direction=_vix_dir,
                        vix_vs_prev=_vix_vs_prev,
                        vix_bucket=_vix_bucket(mkt_ctx.vix) if mkt_ctx.vix is not None else None,
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
                        flow_imbalance=_flow_imbalance.get("normalized"),
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
                    _snapshotrow_field_names = set(getattr(SnapshotRow, "__annotations__", {}).keys())
                    _dropped_snapshot_fields = sorted(k for k in _snapshot_kwargs if k not in _snapshotrow_field_names)
                    if _dropped_snapshot_fields:
                        log.warning("SnapshotRow field drift detected; dropping unsupported fields: %s", _dropped_snapshot_fields)
                    _snap = SnapshotRow(**{k: v for k, v in _snapshot_kwargs.items() if k in _snapshotrow_field_names})
                    _ed_db.insert_snapshot(_snap)
                    _snapshot_row_insert_committed(ticker, _snap_ts)
                    _snap_insert_landed = True
                # LIVE_OPERATOR_MODE_RESET_V1 Step 3 — bars persist + outcome backfill ride
                # the snapshot throttle (1/min/ticker): per-refresh writes contended with the
                # live path; bars re-seed from Schwab pricehistory after any gap and labels
                # only advance when new rows exist.
                #
                # Lane-4 (2026-07-05): the bars upsert measured 8,090.8ms of the 10,760ms
                # db_snapshot_write_accuracy stage (sqlite_tier1_ok op=upsert_1m_bars
                # ticker=SPY exec_ms=8090.8; warm ~0.5s) while its return value is never
                # read by the live payload. Bars persist + outcome backfill now run as ONE
                # ordered task on the single-worker fill-outcomes executor: bars are durable
                # before labels advance (same relative order as the previous synchronous
                # form), the Tier C payload no longer blocks on persistence, and a dropped
                # write self-heals via the re-seed contract above. _bars_persist is a fresh
                # list copy (get_bars) of immutable completed Candles — race-free handoff.
                # Schwab CSV authority checked: yes
                # CSV row(s): pricehistory.candles[].open/high/low/close/volume — persistence
                #   scheduling only; no market field read, derivation, emission, or
                #   actionability logic changed; bar values and their Schwab leaf unchanged.
                # Derived-field disposition: none required.
                # All consumers checked: yes — upsert return value unread at this call site;
                #   fill_outcomes ordering preserved by the max_workers=1 executor.
                # SCHWAB_CSV_CHECKED
                if _do_insert:
                    _bars_persist = _candles_1m.get_bars(ticker)

                    def _bg_persist_bars_then_fill_outcomes() -> None:
                        try:
                            if _bars_persist:
                                get_db().upsert_1m_bars(ticker, _bars_persist)
                        except Exception as _pe:
                            log.warning("upsert_1m_bars %s: %s", ticker, _pe)
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
            from calibration.v2_live_logging import append_live_v2_calibration_decision
            from db import DB_PATH as _calibration_db_path

            _v2_log_result = append_live_v2_calibration_decision(
                db_path=_calibration_db_path,
                calibration_payload=getattr(ms, "_calibration_payload", None),
                v2_decision=v2_decision_for_log,
            )
            if _v2_log_result and _v2_log_result.get("status") != "ok":
                log.debug("live v2 calibration logging skipped: %s", _v2_log_result)
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
            mkt_ctx.vix if mkt_ctx else None,
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
    if mkt_ctx is not None and getattr(mkt_ctx, "vix", None) is not None:
        try:
            _vix_tracker.tick(float(mkt_ctx.vix))
        except (TypeError, ValueError):
            pass
    _prev_vix_live = _state_cache.get(_cache_key, {}).get("vix")
    ms_dict["vix"] = float(mkt_ctx.vix) if mkt_ctx and mkt_ctx.vix is not None else None
    ms_dict["vix_direction"] = (
        _vix_tracker.direction if mkt_ctx and mkt_ctx.vix is not None else None
    )
    ms_dict["vix_vs_prev"] = (
        round(float(mkt_ctx.vix) - float(_prev_vix_live), 4)
        if mkt_ctx and mkt_ctx.vix is not None and _prev_vix_live is not None
        else None
    )
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

    ms_dict["kl_call_gamma_wall"]  = _fv(getattr(w0, "call_gamma_wall",  None))
    ms_dict["kl_put_gamma_wall"]   = _fv(getattr(w0, "put_gamma_wall",   None))
    ms_dict["kl_gamma_inflection"] = _fv(getattr(cs, "gamma_inflection", None))
    ms_dict["kl_call_delta_wall"]  = _fv(getattr(w0, "call_delta_wall",  None))
    ms_dict["kl_put_delta_wall"]   = _fv(getattr(w0, "put_delta_wall",   None))
    ms_dict["kl_delta_inflection"] = _fv(getattr(cs, "delta_inflection", None))
    ms_dict["kl_call_oi_wall"]     = _fv(getattr(w0, "call_oi_wall",     None))
    ms_dict["kl_put_oi_wall"]      = _fv(getattr(w0, "put_oi_wall",      None))
    ms_dict["kl_call_vanna_wall"]  = _fv(getattr(w0, "call_vanna_wall",  None))
    ms_dict["kl_put_vanna_wall"]   = _fv(getattr(w0, "put_vanna_wall",   None))

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

    ms_dict["kl_call_gamma_str"]  = _fs(getattr(w0, "call_gamma_strength", None))
    ms_dict["kl_put_gamma_str"]   = _fs(getattr(w0, "put_gamma_strength",  None))
    ms_dict["kl_call_delta_str"]  = _fs(getattr(w0, "call_delta_strength", None))
    ms_dict["kl_put_delta_str"]   = _fs(getattr(w0, "put_delta_strength",  None))
    ms_dict["kl_call_oi_str"]     = _fs(getattr(w0, "call_oi_strength",    None))
    ms_dict["kl_put_oi_str"]      = _fs(getattr(w0, "put_oi_strength",     None))
    ms_dict["kl_call_vanna_str"]  = _fs(getattr(w0, "call_vanna_strength", None))
    ms_dict["kl_put_vanna_str"]   = _fs(getattr(w0, "put_vanna_strength",  None))

    # ── New institutional levels ───────────────────────────────────────────────
    ms_dict["kl_gamma_pin"]    = _fv(getattr(cs, "gamma_pin", None))
    ms_dict["kl_hvl"]          = _fv(_hvl)
    ms_dict["kl_max_pain"]     = _fv(_max_pain)
    ms_dict["kl_hvl_str"]      = _fs(hvl_gamma_strength(exposures, _hvl))
    ms_dict["kl_max_pain_str"] = _foi(max_pain_oi_strength(exposures, _max_pain))
    ms_dict["kl_oi_center"]    = _fv(getattr(cs, "oi_center", None))
    ms_dict["kl_gamma_flip"]   = _fv(_gamma_flip)
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
    ms_dict["kl_em_upper"] = _em_up_straddle or _em_up_iv
    ms_dict["kl_em_lower"] = _em_lo_straddle or _em_lo_iv
    ms_dict["kl_em_anchor"] = _kl_em_anchor
    ms_dict["mc_em_anchor"] = _kl_em_anchor
    ms_dict["mc_iv_source"] = _mc_iv_source
    ms_dict["kl_gamma_voids"]  = _gamma_voids or []
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
        if abs(_parity_resid) > PARITY_RESID_MIN:
            ms_dict["kl_synth_fwd"]       = round(spot_f + _parity_resid, 2)
            ms_dict["kl_synth_fwd_resid"] = round(_parity_resid, 4)
            ms_dict["kl_synth_fwd_side"]  = "CALL" if _parity_resid > 0 else "PUT"
            ms_dict["kl_synth_fwd_label"] = "Calls slightly rich" if _parity_resid > 0 else "Puts slightly rich"
        else:
            ms_dict["kl_synth_fwd"] = None
    except Exception:
        ms_dict["kl_synth_fwd"] = None

    # ── Price levels (VWAP / PDH / PDL / PDC / ORB) ───────────────────────────
    ms_dict["vwap"]     = _fv(getattr(price_levels, "vwap",     None))
    ms_dict["pdh"]      = _fv(getattr(price_levels, "pdh",      None))
    ms_dict["pdl"]      = _fv(getattr(price_levels, "pdl",      None))
    ms_dict["pdc"]      = _fv(getattr(price_levels, "pdc",      None))
    ms_dict["orb_high"] = _fv(getattr(price_levels, "orb_high", None))
    ms_dict["orb_low"]  = _fv(getattr(price_levels, "orb_low",  None))

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
    ms_dict["flow_imbalance"]        = _flow_imbalance.get("normalized")
    ms_dict["flow_imbalance_label"]  = _flow_imbalance.get("label")
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
            return {"model": display_name, "status": "NOT TRAINED", "status_reason": "No metadata — model never promoted", "edge": 0, "version": "—", "ticker": _dashboard_ticker}
        if not art.get("exists", False):
            return {"model": display_name, "status": "BINARY MISSING", "status_reason": "Metadata present but model file missing — run training/promotion", "edge": 0, "version": "—", "ticker": _dashboard_ticker}
        if not art.get("has_provenance", False):
            issues = "; ".join(art.get("issues", [])) or "Metadata lacks provenance"
            return {"model": display_name, "status": "NON-COMPLIANT", "status_reason": issues, "edge": 0, "version": "—", "ticker": _dashboard_ticker}
        try:
            _m = json.loads(meta_path.read_text())
            raw = _m.get(edge_key, _m.get("val_accuracy", 0))
            edge = float(raw) * 100 if edge_key == "val_accuracy" else float(raw or 0)
            version = _m.get(version_key, _m.get("model_version", "—"))
        except Exception:
            edge, version = 0, "—"
        return {"model": display_name, "status": "LIVE", "status_reason": "Binary + metadata + provenance compliant", "edge": edge, "version": version or "—", "ticker": _dashboard_ticker}

    _xgb_meta = _active_dir / f"xgb_{_dashboard_ticker}_{_dashboard_ml_hz}_meta.json"
    _lstm_meta = _active_dir / f"lstm_{_dashboard_ticker}_{_dashboard_ml_hz}_meta.json"
    _tf_meta = _active_dir / f"transformer_{_dashboard_ticker}_{_dashboard_ml_hz}_meta.json"
    try:
        _model_health.append(_model_status_from_artifact("xgb", "XGBoost", _xgb_meta, "edge_pp", "model_version"))
    except Exception:
        _model_health.append({"model": "XGBoost", "status": "ERROR", "status_reason": "Check failed", "edge": 0, "version": "—", "ticker": _dashboard_ticker})
    try:
        _model_health.append(_model_status_from_artifact("transformer", "Transformer", _tf_meta, "edge_pp"))
    except Exception:
        _model_health.append({"model": "Transformer", "status": "ERROR", "status_reason": "Check failed", "edge": 0, "version": "—", "ticker": _dashboard_ticker})
    try:
        _model_health.append(_model_status_from_artifact("lstm", "LSTM", _lstm_meta, "val_accuracy", "model_type"))
    except Exception:
        _model_health.append({"model": "LSTM", "status": "ERROR", "status_reason": "Check failed", "edge": 0, "version": "—", "ticker": _dashboard_ticker})

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

    _cf  = getattr(mkt_ctx, "confluence",     None)
    _qcf = getattr(mkt_ctx, "qqq_confluence", None)
    _icf = getattr(mkt_ctx, "iwm_confluence", None)
    _ihcf = getattr(mkt_ctx, "iwm_holdings_confluence", None)
    ms_dict["cf_weighted_push"] = getattr(_cf,  "weighted_push",   None)
    ms_dict["cf_label"]         = getattr(_cf,  "label",           "—")
    ms_dict["cf_color"]         = getattr(_cf,  "color",           "#9ca3af")
    ms_dict["cf_dot_green"]     = getattr(_cf,  "dot_count_green", 0)
    ms_dict["cf_dot_total"]     = getattr(_cf,  "dot_count_total", 0)
    ms_dict["qqq_cf_weighted_push"] = getattr(_qcf, "weighted_push", None)
    ms_dict["qqq_cf_label"]        = getattr(_qcf, "label", "—")
    ms_dict["qqq_cf_color"]        = getattr(_qcf, "color", "#9ca3af")
    ms_dict["iwm_holdings_cf_push"]  = getattr(_ihcf, "weighted_push", None)
    ms_dict["iwm_holdings_cf_label"] = getattr(_ihcf, "label", "—")
    ms_dict["iwm_holdings_cf_color"] = getattr(_ihcf, "color", "#9ca3af")
    try:
        from market_context import iwm_blended_participation_push
        ms_dict["iwm_participation_push"] = iwm_blended_participation_push(mkt_ctx)
    except Exception:
        ms_dict["iwm_participation_push"] = None
    ms_dict["iwm_cf_label"]     = getattr(_icf, "label",           "—")
    ms_dict["iwm_cf_color"]     = getattr(_icf, "color",           "#9ca3af")
    ms_dict["iwm_cf_push"]      = getattr(_icf, "weighted_push",   None)

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
    _finalize_production_decision(ms_dict, _decision_route)
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
        "vix": mkt_ctx.vix if mkt_ctx else None,
        "price_levels": _prev_ent.get("price_levels"),
        "pl_date":      _prev_ent.get("pl_date", ""),
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

    stop_logger()
    # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: leaf pool shuts down AFTER
    # the analytics executor above — no new leaf submits can arrive first (the
    # _analytics_bg_shutdown branch also forces inline leaf fetches).
    global _recompute_leaf_executor
    if _recompute_leaf_executor is not None:
        _recompute_leaf_executor.shutdown(wait=True, cancel_futures=True)
        _recompute_leaf_executor = None
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
        rows = edb.get_recent_crosses(ticker=ticker, n=int(n))
        return JSONResponse({"ok": True, "mode": "recent", "ticker": ticker,
                             "n": int(n), "crosses": rows})
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
            health.get("ratio") or 0.0,
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
    intent = (body.get("manual_intent") or "").strip()
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
    age = 0.0
    if entry:
        age = max(0.0, now - _analytics_generated_ts(entry))

    has_body = bool(entry and entry.get("ms_dict"))
    # Stale-serve marker follows the honest grace window (missed cycle), same
    # authority as _attach_analytics_freshness_contract.
    stale = bool(
        (not has_body) or (age >= float(ttl) * ANALYTICS_STALE_GRACE_CYCLES)
    )

    # LIVE_OPERATOR_MODE_RESET_V1 Step 2 — single Tier C owner: when a live SSE
    # viewer owns this scope, _sse_background_loop is the only recompute scheduler
    # and REST is a read-only cache view. force=true (manual REFRESH) and the
    # cold/no-viewer poll path still self-schedule.
    need_refresh = bool(
        force or (not has_body) or ((not sse_live) and (age >= ttl))
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

    # SWITCH-LATENCY FIX: async route — keep the symbol persist (DB write) and the L1
    # projection build (a full recompute on a cold miss) OFF the event loop.
    def _build():
        # TICKER-PREVIEW-NO-ENROLL: L1 light view touches last-seen only, never enrolls.
        _touch_tracked_ticker_view(t)
        return notify_ticker_expiry_changed(t, expiry, force=force)
    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_fast_quote_executor(), _build)
    return JSONResponse(payload)


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
    # touch last-seen only. Offloaded because it may do a SQLite write for enrolled tickers.
    await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _touch_tracked_ticker_view, t)
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
    drop_m = float(_l1_sse_last_drop_mono or 0.0)
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
    viol = int(out.get("l1_payload_identity_violation", 0) or 0)
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
    avg_ms = float(_l1_instrumentation["l1_build_ms_sum"]) / max(1, bt)
    reasons = {str(k): int(v) for k, v in _l1_instrumentation["l1_build_by_reason"].items()}
    uptime_sec = max(0.0, time.monotonic() - _l1_diag_start_mono)
    operational = build_l1_operational_assessment(
        l1_build_total=bt,
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
    Fast lane: latest equity quote fields only. Independent fast_generation_id / fast_server_ts.
    Does not return chain, fusion, or decision data.
    """
    ticker = ticker.upper().strip()
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
        q = asyncio.Queue(maxsize=10)
        with _sse_lock:
            _sse_clients.append(q)
            _sse_subscribers[key] = _sse_subscribers.get(key, 0) + 1
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
    """
    if max_keys <= 0:
        return []
    try:
        owned_tickers = {k[0] for k in owned_keys if isinstance(k, tuple) and k}
        stale_after = float(CACHE_TTL) * ANALYTICS_STALE_GRACE_CYCLES
        now = time.time()
        candidates: list[tuple[float, tuple]] = []
        for key, entry in list(_state_cache.items()):
            if not isinstance(key, tuple) or not key:
                continue
            if key[0] in owned_tickers:
                continue
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
                db_rows[(row.get("ticker") or "").upper().strip()] = row
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
    t = ticker.upper().strip()
    if not t or len(t) > 10:
        raise HTTPException(status_code=400, detail="invalid ticker")
    if t in CORE_TICKERS:
        raise HTTPException(status_code=400, detail="core symbols are already protected; pin not applicable")
    db = get_db()
    is_already_pinned = any(
        (r.get("ticker") or "").upper() == t and r.get("category") == "pinned"
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
    """Build/identity surface.

    ``process_identity`` is the IMMUTABLE identity captured once at process
    start — the only block that proves which code this process loaded.
    ``repository_state_now`` is a request-time diagnostic of the repository on
    disk: it drifts when HEAD moves and is NOT process identity. The legacy
    top-level ``git_sha`` mirrors repository_state_now.repo_head_now for
    compatibility with existing consumers and must not be read as proof of
    the running process's code.
    """
    from release_object import get_current_release

    release = get_current_release(required=False)
    repo_head_now = _repo_git_head_sha()
    return {
        "git_sha": repo_head_now,  # LEGACY-COMPAT: dynamic repo read, not process identity
        "contract": "meet_or_exceed_v1",
        "release_id": release.get("release_id") if release else None,
        "ui_maximize_sla_ms": dict(UI_MAXIMIZE_SLA_MS),
        "ui_maximize_panel_warm_tickers": list(UI_MAXIMIZE_PANEL_WARM_TICKERS),
        "process_identity": asdict(PROCESS_IDENTITY_V1),
        "repository_state_now": {"repo_head_now": repo_head_now},
    }


@app.get("/api/price-levels")
# SWITCH-LATENCY FIX: sync def → threadpool (Schwab quote + price-levels compute, no await).
def get_price_levels(ticker: str = Query(default=DEFAULT_TICKER), extended_hours: bool = Query(default=True)):
    """Return PDH/PDL/PDC, POC/VAH/VAL, VWAP bands, ORB, overnight range as JSON."""
    try:
        # TICKER-PREVIEW-NO-ENROLL: price-levels is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker)
        client = get_client()
        q_resp = _safe_get_quote_with_retry(client, ticker)
        q_json = q_resp.json() if q_resp and hasattr(q_resp, "json") else {}
        pl = fetch_price_levels(client, symbol=ticker, quote_raw=q_json, include_extended_hours=extended_hours)
        return asdict(pl)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _build_raw_levels_used(raw_levels: dict, snapshot_type: str) -> list:
    """Flatten raw_levels into [{tag, value}] for display, ordered by price."""
    items = []
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
            items.append({"tag": tag_map[k], "value": float(v)})
    for k in ["overnight_high", "overnight_low"]:
        v = (raw_levels.get("overnight") or {}).get(k)
        if v is not None:
            items.append({"tag": tag_map[k], "value": float(v)})
    orb = raw_levels.get("orb") or {}
    for k in ["orb_high", "orb_low", "orb_mid"]:
        if orb.get(k) is not None:
            items.append({"tag": tag_map[k], "value": float(orb[k])})
    if raw_levels.get("vwap") is not None and snapshot_type != "premarket":
        items.append({"tag": "VWAP", "value": float(raw_levels["vwap"])})
    vwap_bands = raw_levels.get("vwap_bands") or {}
    for k, tag in [("plus2", "VWAP_P2"), ("plus1", "VWAP_P1"),
                   ("minus1", "VWAP_M1"), ("minus2", "VWAP_M2")]:
        if vwap_bands.get(k) is not None:
            items.append({"tag": tag, "value": float(vwap_bands[k])})
    for k in ["poc", "vah", "val"]:
        if raw_levels.get(k) is not None:
            items.append({"tag": tag_map[k], "value": float(raw_levels[k])})
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
        (d.get("kl_gamma_pin"), "GAMMA_PIN"),
        (d.get("kl_hvl"), "HVL"),
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
            out = build_live_snapshot(
                ticker_upper,
                bars,
                session_date_obj,
                config,
                extra_levels=_extra_for_build if fusion else None,
                spot=spot_for_zones,
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
        ticker = (ticker or DEFAULT_TICKER).upper().strip()
        # TICKER-PREVIEW-NO-ENROLL: charm diagnostic is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker)
        from math_exposure import compute_net_charm
        import math as _charm_math

        cl       = get_client()
        c_resp   = safe_get_chain(cl, ticker, strike_count=CHAIN_STRIKE_COUNT)
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
        for ct in contracts:
            try:
                _g = float(ct.get("gamma")) if ct.get("gamma") is not None else None
            except (TypeError, ValueError):
                _g = None
            if _g is not None and _g != MISSING_GREEK_SENTINEL and _charm_math.isfinite(_g):
                usable_gamma += 1
            if ct.get("gamma") == MISSING_GREEK_SENTINEL:
                sentinel_gamma += 1
            try:
                _d = float(ct.get("delta")) if ct.get("delta") is not None else None
            except (TypeError, ValueError):
                _d = None
            if _d is not None and _d != MISSING_GREEK_SENTINEL and _charm_math.isfinite(_d):
                usable_delta += 1
            try:
                _t = float(ct.get("theta")) if ct.get("theta") is not None else None
            except (TypeError, ValueError):
                _t = None
            if _t is not None and _t != MISSING_GREEK_SENTINEL and _charm_math.isfinite(_t):
                usable_theta += 1
            try:
                _v = float(ct.get("vega")) if ct.get("vega") is not None else None
            except (TypeError, ValueError):
                _v = None
            if _v is not None and _v != MISSING_GREEK_SENTINEL and _charm_math.isfinite(_v):
                usable_vega += 1
            try:
                _iv = float(ct.get("volatility")) if ct.get("volatility") is not None else None
            except (TypeError, ValueError):
                _iv = None
            if _iv is not None and _iv > 0 and _iv != MISSING_GREEK_SENTINEL and _charm_math.isfinite(_iv):
                usable_iv += 1
            if ct.get("openInterest"):
                has_oi += 1

        # What expiries exist?
        expiries     = _expiries_from_contracts(contracts)
        selected_exp = _default_expiry(expiries, ticker)

        # Try charm with all contracts, no filter
        raw_spot = chain_json.get("underlyingPrice")
        try:
            spot = float(raw_spot) if raw_spot is not None else None
        except (TypeError, ValueError):
            spot = None
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
                    total_predictions=int(_hz_res.get("total", 0) or 0),
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
