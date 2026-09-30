"""Ed Console web server: the levels loop, the bar writer, and the routes the screens read."""

from __future__ import annotations

import os
import signal
import sqlite3
import sys
import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import concurrent.futures
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Annotated, Optional
from dataclasses import asdict, dataclass

from time_et import (ET, now_et, RTH_OPEN_MINS, ct_label, is_capturable_session, et_date_str_from_ts_utc,
                     et_minute_total_from_ts_utc,
                     is_trading_day_et, session_close_mins_for_et_date, session_label, settlement_et)
from math_exposure_core import bucket_metric, merge_exposure_books

import json
from html import escape as html_escape


from fastapi import Body, FastAPI, Query, HTTPException
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

    def __init__(self, fmt: str | None = None, *, datefmt: str | None = None,
                 use_ansi: bool = True) -> None:
        super().__init__(fmt, datefmt)
        self.use_ansi = use_ansi

    def format(self, record: logging.LogRecord) -> str:
        table = self._ANSI_BY_LEVEL if self.use_ansi else self._PLAIN_BY_LEVEL
        marker = table.get(record.levelno, "")
        return marker + super().format(record)


# Quiet-window / LIVE closeout sink. Root handler so ANY logger (db, ed_server,
# uvicorn, …) at INFO+ lands here; gate fails on WARNING+ / traceback.
# RC-523: under the RUNTIME root (runtime_layout), which is this checkout unless
# ED_RUNTIME_ROOT moves it — runtime output must not pollute the source tree (§8).
from runtime_layout import logs_dir as _runtime_logs_dir  # noqa: E402

ED_SERVER_LOG_PATH = _runtime_logs_dir() / "ed_server.log"


def _console_formatter(*, use_ansi: bool) -> "_LevelMarkerFormatter":
    """The one line format for the console window and logs/ed_server.log: the time in Central
    (the operator's clock), the level, the logger, the message."""
    fmt = _LevelMarkerFormatter("%(asctime)s %(levelname)s:%(name)s:%(message)s",
                                datefmt="%H:%M:%S CT", use_ansi=use_ansi)
    fmt.converter = lambda t: datetime.fromtimestamp(t, ZoneInfo("America/Chicago")).timetuple()
    return fmt


def install_ed_server_file_sink(
    log_path: Path | None = None,
    *,
    level: int = logging.INFO,
) -> logging.Handler:
    """Attach the log file on the root logger for logs/ed_server.log: rotated at 50 MB with one
    previous file kept, the capture daemon's own policy (the plain file reached 1.3 GB, 2026-09-27).
    Every record is flushed as it is written (logging.StreamHandler.emit).

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
    handler = RotatingFileHandler(path, maxBytes=50 * 1024 * 1024, backupCount=1, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        _console_formatter(use_ansi=False)
    )
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return handler


def _install_visual_severity_markers(level: int = logging.INFO) -> None:
    """Replace any default root handlers with one that adds the level marker."""
    use_ansi = bool(getattr(sys.stderr, "isatty", lambda: False)())
    handler = logging.StreamHandler()
    handler.setFormatter(_console_formatter(use_ansi=use_ansi))
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
    # A checkout bound to ANOTHER checkout's runtime (runtime_layout.live_binding_error) must
    # not write that checkout's live log -- measured 2026-09-23: a worktree console appended
    # 15,451 errors to the production logs/ed_server.log. The stream handler still prints.
    from runtime_layout import live_binding_error as _live_binding_error
    if ("pytest" not in sys.modules and not os.environ.get("PYTEST_CURRENT_TEST")
            and _live_binding_error() is None):
        install_ed_server_file_sink(ED_SERVER_LOG_PATH, level=level)


_install_visual_severity_markers(logging.INFO)
log = logging.getLogger("ed_server")


# ── Import all existing Ed Console modules (unchanged) ───────────────────────
from config import build_config, load_dotenv_file

from schwab_client import (
    auth_is_refreshable,
    build_client_from_token,
    fetch_full_chain,
    flatten_chain_contracts,
    inspect_token_file,
    safe_get_chain,
    SchwabAuthError,
)
from instrument_identity import display_symbol, ticker_storage_key   # RC-126: the ONE query-symbol authority
import live_market_plane as lmp
from numeric_contract import schwab_number
from terrain_engine import (TerrainSnapshot, chain_ladder, compute_terrain, nearest_strike, positioning_migration)
from terrain_atr import AtrPair, compute_atr_pair

from db import LevelCrossEvent, get_db

import live_price_rows as _lpr        # the chart bar, its roll-up and its change
import push_changes

# ── Config + Schwab client (refreshable singleton) ────────────────────────────
load_dotenv_file()
cfg     = build_config()
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


def schwab_capability_state() -> tuple[str, str]:
    """`("AVAILABLE" | "UNAVAILABLE", reason)` for the Schwab capability.

    RC-514 second cut. The first published this from `config.schwab_live_blocked_for()` alone,
    which only proves credentials and CI state PERMIT an attempt — it says nothing about the
    token. A missing, malformed, or unrefreshable token file leaves the capability unable to
    operate while that gate reads clear, so health could advertise AVAILABLE for a Schwab that
    cannot serve a single quote.

    This asks the canonical client instead, through the SAME `build_client_from_token` and the
    SAME `_client` cache `get_client()` uses — not a parallel health computation. The gate is
    still enforced, because it is the first thing that builder checks.

    Cost is why it can sit on a polled endpoint. MEASURED: every UNAVAILABLE verdict is cheap
    and local — missing file 3.3 ms, malformed JSON 15.3 ms, malformed layout 0.3 ms,
    unrefreshable 13.4 ms — while the ~400 ms client construction happens only on the
    AVAILABLE path, once, and populates the cache the app then uses. An expired token WITH a
    refresh token builds fine and is correctly AVAILABLE; schwab-py refreshes it.
    """
    global _client
    if _client is not None:
        return "AVAILABLE", ""
    try:
        state = build_client_from_token(
            api_key=cfg.api_key,
            app_secret=cfg.app_secret,
            token_path=cfg.token_path,
        )
    except Exception as exc:  # noqa: BLE001 — health must answer, never optimistically
        return "UNAVAILABLE", f"{type(exc).__name__}: {exc}"
    if state.ok and state.client is not None:
        _client = state.client
        return "AVAILABLE", ""
    return "UNAVAILABLE", (state.message or "").strip()


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


#: Precedence for the ONE spot authority. Highest wins; every entry records where the
#: number came from so a caller can never silently accept a lower-confidence source.
SPOT_SOURCE_PLANE = "streaming_plane"          # live_market_plane.get_quote — the freshest real trade this process has seen
SPOT_SOURCE_CAPTURE = "chain_capture"          # underlyingPrice of a stored chain capture (DATA_FLOW decision 7)


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


def resolve_spot(ticker: str) -> tuple[float | None, str, float | None]:
    """(spot, source, as_of_ts_utc): the daemon's price row's live Schwab LAST_PRICE and its
    trade time, the value the header shows; (None, "none", None) while it is not live."""
    from app.options.order_flow.streaming import price_row

    row = price_row(ticker)
    if not row or row.get("spot_state") != "live":
        return None, "none", None
    return row["spot"], SPOT_SOURCE_PLANE, row.get("trade_ts")


def _gated_safe_get_chain(client, ticker: str, *, strike_count=None, strike_range=None,
                          priority: bool = False, to_date=None, from_date=None):
    """safe_get_chain behind the bounded two-slot gate -> (resp, gate_wait_sec, fetch_sec).

    Schwab CSV authority checked: yes
    CSV row(s): chains.* via schwab_client.safe_get_chain - call shape
      unchanged (safe_get_chain(client, ticker, strike_count=..., strike_range=...));
      this is scheduling (bounded 2-slot gate + per-ticker single-flight coalescing),
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
    # different requests and must never coalesce onto each other. strike_range joins it too
    # (OPTIONS_ORDER_FLOW_V1 2026-08-30): a strike_range="ALL" complete-chain request and a
    # bounded strike_count request for the SAME ticker/dates are DIFFERENT fetches — MEASURED
    # live, "ALL" returned 69 more real strikes than strike_count=250 alone for the same SPY
    # expiry, so coalescing them onto each other would silently hand a caller wanting the
    # complete set a truncated bounded response, or vice versa.
    key = ((ticker or "").strip().upper(),
          int(strike_count) if strike_count is not None else None,
          str(strike_range or ""), str(to_date or ""), str(from_date or ""))
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
        resp = safe_get_chain(client, ticker, strike_count=strike_count, strike_range=strike_range,
                              to_date=to_date, from_date=from_date)
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



_route_offload_executor: Optional[ThreadPoolExecutor] = None


def _get_route_offload_executor() -> ThreadPoolExecutor:
    global _route_offload_executor
    if _route_offload_executor is None:
        _route_offload_executor = ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="ed_route_offload",
        )
    return _route_offload_executor


# (REST fast-quote writer DELETED 2026-09-24, independent-audit finding #3: it wrote REST
# quotes into live_market_plane by REPLACING the ticker's row -- and streamed LEVELONE deltas
# merge onto the prior row, so the next streamed delta could inherit REST bid/ask under the
# schwab_streaming_level_one label. It also served a stale row "carried forward" on auth
# failure. The plane now has ONE writer: the stream. /api/fast-quote reads it.)


# ─────────────────────────────────────────────────────────────────────────────
# NAMED CONSTANTS — every tunable in one place.
# Nothing below should contain a raw magic number for these parameters.
# ─────────────────────────────────────────────────────────────────────────────

PRE_MARKET_MINS:     int   = 525    # 8:45 AM ET  (logger session buffer start; widened
#   from 9:00 on 2026-08-25 for the universal by-9:30 readiness requirement — the full
#   sweep measured ~43s/ticker, so 61 enrolled tickers need ~44 min; an 08:45 start
#   finishes the first full-snapshot sweep by ~09:29 ET when the process is up)
#: the refresh ends this long after the day's close (16:00, or 13:00 on an early close):
#: 15 minutes after SPY/QQQ/IWM and the index options stop trading (16:15 / 13:15 ET)
REFRESH_AFTER_CLOSE_MIN: int = 30


def _refresh_window_et(et_date: str) -> "tuple[int, int] | None":
    """(start, end) ET minute-of-day of the console's chain refresh on `et_date`; None when
    the market does not open that day (the one calendar, time_et)."""
    close = session_close_mins_for_et_date(et_date) if is_trading_day_et(et_date) else None
    return None if close is None else (PRE_MARKET_MINS, close + REFRESH_AFTER_CLOSE_MIN)


def _refresh_window_ct(et_date: str) -> str:
    """The refresh window as the operator reads it: Central time."""
    win = _refresh_window_et(et_date)
    if win is None:
        return "no refresh today (market closed)"
    day = datetime.fromisoformat(et_date)
    ct = [datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=ET)
          .astimezone(ZoneInfo("America/Chicago")).strftime("%I:%M %p").lstrip("0") for m in win]
    return f"{ct[0]}-{ct[1]} CT"



# ETF zone classification (spy_zone / qqq_zone / iwm_zone)


# Builds OHLC bars from spot price ticks. Server polls every ~30s, so:
#   5-min bars = ~10 ticks per bar
#   1-min bars = ~2 ticks per bar
# Bars are keyed by ticker. Completed bars stored in ring buffer; maxlen from math_exposure.
# ─────────────────────────────────────────────────────────────────────────────
#: one RTH day of 1-minute bars
CANDLE_1M_MAX_BARS: int = 390
from micro_structure import Candle
# Imported at MODULE LEVEL deliberately: the terrain loop's morning-window guard depends
# on these, and a runtime import inside the loop meant a missing module silently removed
# the guard during the exact 30 minutes it protects. At top level, a broken module stops
# the server AT BOOT -- loud, immediate, and impossible to trade through unnoticed. This
# also ends the fail-open/fail-closed argument (Cursor audit 2026-07-20): the runtime
# path now has no failure mode to pick a policy for.
from app.options.contracts.default import front_atm_call
from calibration.complete_chain_capture import (
    CAPTURE_BASIS,
    board_tickers,
    last_capture_per_day,
    newest_capture_ts,
)
from liquidity_models import ZONE_DISPLAY, PlaybookConfig
from liquidity_value_engine import LEVEL_NAMES, build_zones, value_context


#: one bar as SQLite writes values in SQL (quote: every stored double exactly, NULL as NULL)
_BAR_TEXT = " || ' ' || ".join(f"quote({f})" for f in ("bar_start_ts_utc", "open", "high", "low", "close", "volume"))


def _read_bars_1m(tk: str, limit: int) -> list:
    """The newest `limit` rows of price_bars_1m for `tk`, oldest first:
    (bar_start_ts_utc, open, high, low, close, volume). Read in one SQLite step: a row-by-row read
    hands the interpreter lock back at every row and waits for it behind the option pricing."""
    import sqlite3 as _sq
    con = _sq.connect(f"file:{get_db().db_path}?mode=ro", uri=True, timeout=10.0)
    try:
        (text,) = con.execute(
            f"SELECT group_concat({_BAR_TEXT}, ';' ORDER BY bar_start_ts_utc) FROM (SELECT * FROM "
            "price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT ?)",
            (ticker_storage_key(tk), int(limit))).fetchone()
    finally:
        con.close()
    return [tuple(None if v == "NULL" else float(v) for v in row.split(" ")) for row in text.split(";")] if text else []


def _bars_1m(tk: str, limit: int = CANDLE_1M_MAX_BARS) -> "list[Candle]":
    """`tk`'s completed 1-minute bars, oldest first, from price_bars_1m -- which only Schwab's
    streamed CHART_EQUITY bars write (_bar_writer). A minute the stream did not deliver is
    absent, never filled in."""
    return [Candle(ts=float(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in _read_bars_1m(tk, limit)]


def _bar_dict(c: "Candle") -> dict:
    return {"t": float(c.ts), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}


def _write_streamed_bar(msg: dict) -> bool:
    """Write one streamed 1-minute bar (Schwab CHART_EQUITY) to price_bars_1m: the chart's bar
    (live_price_rows.minute_bar, the one the daemon pushes to the screen); False when it is not
    one (then nothing is written)."""
    b = _lpr.minute_bar(msg)
    if b is None:
        log.debug("streamed bar for %s is not a chart bar, not written: %s", msg.get("symbol"), msg)
        return False
    get_db().upsert_1m_bars(msg["symbol"], [Candle(ts=b["t"], open=b["o"], high=b["h"], low=b["l"],
                                                   close=b["c"], volume=b["v"])])
    return True


def _write_streamed_bars(msgs: list) -> None:
    """Write streamed bars, then build the price levels of each ticker written: every bar is
    written before any level is built (a minute's bars for the whole board arrive together)."""
    written = []
    for msg in msgs:
        try:
            if _write_streamed_bar(msg):
                written.append(msg["symbol"])
        except Exception as e:  # noqa: BLE001 -- logged; the next bar is still written
            log.warning("streamed bar for %s not written: %s", msg.get("symbol"), e)
    for tk in dict.fromkeys(written):
        _publish_price_levels(tk)


def _bar_writer() -> None:
    """The price_bars_1m writer: every streamed bar the capture daemon pushes, as it arrives,
    with the bars already waiting behind it."""
    from app.options.order_flow.streaming import streamed_bars
    while True:
        msgs = [streamed_bars.get()]
        while not streamed_bars.empty():
            msgs.append(streamed_bars.get_nowait())
        _write_streamed_bars(msgs)


def start_bar_writer() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    threading.Thread(target=_bar_writer, name="bar-writer", daemon=True).start()


# The board is the logging_universe table, read by board_tickers in both processes; every row is
# processed alike, whatever its category.
RTH_ONLY:       bool      = True  # only log during RTH + 30min pre/post buffer


def _hydrate_logger_tickers_from_db() -> None:
    """The board, read from the logging_universe table by board_tickers -- the same reader the
    capture daemon uses, so both processes hold one roster (startup / heal drift)."""
    global _logger_tickers
    try:
        db = get_db()
        try:
            removed = db.logging_universe_prune_invalid_enrollments()
            if removed:
                log.warning("Issue 22: pruned invalid logging_universe enrollments: %s", removed)
        except Exception as e:
            log.warning("Issue 22: logging_universe prune failed: %s", e)
        board = board_tickers(db.db_path)
        with _logger_lock:
            _logger_tickers = board
    except Exception as e:
        log.warning("hydrate logger tickers from DB: %s", e)


_logger_tickers:  list[str] = []
_logger_lock:     threading.Lock   = threading.Lock()


def _is_loggable_session(now: float) -> bool:
    """
    Background snapshot logging session gate at `now` (epoch seconds; Issue 22 — explicit
    product policy).

    When RTH_ONLY is True (default): allow ET minutes in _refresh_window_et (PRE_MARKET_MINS to
    30 minutes after the day's close)
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
    et = datetime.fromtimestamp(now, ET)
    if not is_capturable_session(et):   # RC-48: weekend / full holiday / overnight -> never loggable
        return False
    win = _refresh_window_et(et.date().isoformat())
    return win is not None and win[0] <= et.hour * 60 + et.minute <= win[1]




# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────
from contextlib import asynccontextmanager


@asynccontextmanager
async def _app_lifespan(app):
    """Startup and shutdown: logger, order flow, SSE, ML scheduler."""
    # ── Startup ─────────────────────────────────────────────────────────────
    # FIRST, before any worker, client or database is touched: a checkout whose runtime is
    # ANOTHER checkout (a worktree converging on production) does not start a live console
    # (runtime_layout.live_binding_error -- a worktree console ran against production on
    # 2026-09-23). Refusing here stops uvicorn before it serves anything.
    from runtime_layout import live_binding_error
    _binding = live_binding_error()
    if _binding is not None:
        log.critical("LIVE CONSOLE REFUSED: %s", _binding)
        raise RuntimeError(f"live console refused: {_binding}")
    # Installed FIRST: until these exist, Ctrl+C depends on uvicorn's graceful path
    # completing, and that path joins background workers which may be blocked.
    _install_signal_handlers()
    # Schwab auth diagnostics (helps debug link vs manual launch)
    _log_schwab_startup_diagnostics()

    # Lightweight auth validation — don't wait for first /api/state to discover issues.
    #
    # MEASURED (operator finding, 2026-09-11): this block used to (a) build a SEPARATE
    # client via build_client_from_token() instead of the canonical cached owner
    # get_client() — so the ~400ms construction cost (schwab_capability_state's own
    # docstring measurement) was paid AGAIN on the first real request, and (b) issue a
    # BLOCKING live client.get_quote("SPY") call here, before `yield` below — since
    # FastAPI does not accept ANY HTTP request (including Schwab-independent ones, like
    # static assets) until this lifespan function reaches `yield`, a slow or unavailable
    # vendor delayed the whole app's first byte, not just Schwab-dependent routes.
    #
    # Fix: the file-based inspection above stays synchronous (cheap, local, no network).
    # Client construction now goes through get_client() — the SAME cache every other
    # consumer uses, so it is built here ONCE, not rebuilt on first use. The actual vendor
    # round-trip (the real "does the token work" proof) is dispatched as a background task
    # and does NOT block `yield` — HTTP serving is available immediately once the (fast,
    # local) construction step above returns; the live-quote verdict lands in the log a
    # moment later. No decision restriction changes: schwab_capability_state()/get_client()
    # are still the SAME enforcement points every route already calls at decision time.
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
        try:
            startup_client = get_client()
        except HTTPException as ce:
            startup_client = None
            log.error(
                "Schwab auth invalid at startup: %s — Remediation: run python reauth_schwab.py",
                ce.detail,
            )

        if startup_client is not None:
            def _validate_schwab_quote_sync(client):
                try:
                    r = client.get_quote("SPY")
                    if not r or getattr(r, "status_code", 0) != 200:
                        log.warning(
                            "Schwab token validation failed (SPY quote returned %s). "
                            "Token may be expired. Remediation: python reauth_schwab.py",
                            getattr(r, "status_code", "None"),
                        )
                    else:
                        log.info("Schwab auth validated at startup (background)")
                except Exception as ve:
                    from schwab_client import _is_token_error
                    if _is_token_error(ve):
                        log.error(
                            "Schwab token invalid at startup: %s — Remediation: python reauth_schwab.py",
                            ve,
                        )
                    else:
                        log.warning("Schwab startup validation: %s", ve)

            if _inv_startup.is_expiring_soon:
                log.info("Token near expiry — background validation will also exercise refresh")
            asyncio.get_event_loop().run_in_executor(
                None, _validate_schwab_quote_sync, startup_client
            )
    except Exception as e:
        log.warning("Schwab auth check: %s", e)

    # DB-WRITE-PATH-FIXES (d): start_logger() -> _hydrate_logger_tickers_from_db() performs the
    # DB-backed logging-universe load here in the lifespan (kept off the module-import path).
    _hydrate_logger_tickers_from_db()

    # Terrain collection — its OWN loop, never gated on operator mode. The background
    # logger runs the full model stack and therefore had to be throttled while a viewer
    # is connected; terrain is ~5 ms of math plus one chain call per ticker, so it keeps
    # every ticker's levels fresh regardless of what the model stack is doing.
    start_terrain_loop()
    # RC-69: bar collection is its own always-on service — never a side-effect of rendering.
    start_bar_writer()
    log.info("Terrain loop started — %.0fs cadence, %d workers, full chain per ticker",
             TERRAIN_REFRESH_SEC, TERRAIN_WORKERS)

    # Live-plane feed (nasdaq_book, nyse_book, level_one_equity) — READ-ONLY from the
    # canonical capture daemon's stream_capture.db. SINGLE-STREAM-AUTHORITY repair: this
    # used to gate on a resolved Schwab account_id because it needed one to open its own
    # StreamClient. It opens no Schwab session now, so it has no account dependency —
    # gating it behind account resolution was a correctness bug under the new
    # architecture (a broken/expiring token would silently disable the live UI's quote
    # feed even though the daemon was capturing fine). Unconditional.
    from app.options.order_flow.streaming import start_order_flow_stream
    # every streamed equity quote and option greeks/OI/volume quote -> _on_stream_tick,
    # which reprices a viewed ticker through the one levels producer
    start_order_flow_stream(None, None, None, on_tick_callback=_on_stream_tick)

    push_changes.bind(asyncio.get_running_loop())


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
    # Live-plane feed task (reads the canonical capture daemon's DB — no Schwab socket
    # of its own to close here since single-stream-authority root fix 2026-08-30).
    try:
        from app.options.order_flow.streaming import stop_order_flow_stream

        stop_order_flow_stream(join_timeout=40.0)
    except Exception as e:
        log.warning("Order flow streaming shutdown: %s", e)

    stop_terrain_loop()
    global _route_offload_executor
    if _route_offload_executor is not None:
        _route_offload_executor.shutdown(wait=True)
        _route_offload_executor = None


app = FastAPI(title="Ed Console API", version="1.0", lifespan=_app_lifespan)


class _RevalidateStaticFiles(StaticFiles):
    """StaticFiles sends no Cache-Control at all, leaving freshness to each browser's own
    heuristic (commonly ~10% of Last-Modified age, RFC 7234). MEASURED (2026-09-11): after a
    real code change + server restart, a browser served a stale ed-gamma.js across THREE
    separate full navigations (not just a soft reload) with zero requests reaching this
    server for that file -- silent staleness a `curl` or a direct no-store fetch never
    reveals, because it only affects the browser's own normal navigation path. `no-cache`
    forces revalidation on every load (the existing ETag/Last-Modified still make an
    unchanged file a cheap 304, so this costs nothing beyond a round trip) instead of
    trusting a heuristic a shipped fix cannot control.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


static_dir = Path(APP_DIR) / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", _RevalidateStaticFiles(directory=str(static_dir)), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

_LIVE_UI_PORT_META = '<meta name="ed-live-ui-port" content="">'
_MARKET_CONTEXT_META = '<meta name="ed-market-context" content="">'


def _with_live_ui_port(html: str) -> str:
    """Tell the page where the capture daemon's price socket listens (the same
    ED_LIVE_UI_PORT the daemon binds) and which market-context symbols it always shows
    (streaming.MARKET_CONTEXT_SYMBOLS, each with its display name). An unfilled page opens no
    price socket -- its prices read UNAVAILABLE rather than reaching a daemon nobody configured
    it for."""
    from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT
    from app.options.order_flow.streaming import MARKET_CONTEXT_SYMBOLS
    context = json.dumps([{"key": k, "display": display_symbol(k)} for k in MARKET_CONTEXT_SYMBOLS])
    return (html.replace(_LIVE_UI_PORT_META,
                         f'<meta name="ed-live-ui-port" content="{int(LIVE_UI_PORT)}">', 1)
            .replace(_MARKET_CONTEXT_META,
                     f'<meta name="ed-market-context" content="{html_escape(context)}">', 1))


@app.get("/", response_class=HTMLResponse)
def root():
    html_path = static_dir / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>static/index.html not found</h1>", status_code=404)
    # Avoid stale shell JS after edits (browser disk cache of "/" was masking localForce→force fix).
    return HTMLResponse(
        content=_with_live_ui_port(html_path.read_text(encoding="utf-8")),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers request this automatically; without a route they log 404 (harmless but noisy)."""
    return Response(status_code=204)


#: the stored cross direction in words; a direction not stored reads "through", never a side
_CROSS_WORD = {"up": "above", "down": "below"}


def _merged_crosses_since(edb, ticker: str, since_ts_utc: float) -> "list[dict]":
    """Every level cross at or after `since_ts_utc`, newest first, each (time, value, direction)
    one event carrying every level named there in `level_names`. The one reader of level crosses
    for every route. Price crossing one strike writes one stored row per named level sitting
    there; they are merged here, at the read, so the stored history keeps its per-level rows."""
    raw = edb.get_crosses_since(ticker, since_ts_utc)
    merged: list[dict] = []
    seen: dict[tuple, dict] = {}
    for r in raw:
        key = (r.get("ts_utc"), r.get("level_value"), r.get("direction"))
        hit = seen.get(key)
        if hit is None:
            row = dict(r)
            row["level_names"] = [r.get("level_name")]
            seen[key] = row
            merged.append(row)
            continue
        nm = r.get("level_name")
        if nm and nm not in hit["level_names"]:
            hit["level_names"].append(nm)
    return merged


def _required_ticker(ticker: Optional[str]) -> str:
    """The ticker the caller asked for -- never a default one (universality, operator
    2026-09-23: a missing ticker used to silently become SPY). Blank -> HTTP 400."""
    t = str(ticker or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail="ticker is required")
    return t


# ── TERRAIN COLLECTION LOOP ──────────────────────────────────────────────────
# 5-whys root cause (2026-07-19): 24 of 31 tickers refreshed only every ~11 minutes
# because `_live_operator_mode_active()` HARD-SKIPS non-SPY/QQQ/IWM background rotation
# whenever a viewer is connected -- a gate that exists because `_fetch_state` runs the
# full model stack and would otherwise compete with the live UI.
#
# Terrain does not run the model stack. Measured: ~5 ms of math per ticker plus one chain
# call each.
#
# RC-570 (2026-09-21, operator directive): the prior 60.0 was throttled against a "~120
# req/min Schwab budget" this comment cited without distinguishing WHICH Schwab budget --
# the operator's explicit correction: that ceiling governs trade/order (two-way) execution
# calls, not read-only market-data polling, and this loop has never placed a trade. Holding
# a live market-data UI to a trading rate limit was the wrong model, not a real constraint.
# Lowered to run the loop back-to-back with only a minimal floor -- ACTUAL fetch latency
# (network + vendor response time), not an artificial policy pause, is now what paces this
# loop. If Schwab's real market-data limit turns out to be lower than assumed here, that
# will surface as observable 429/502s on THIS loop's own chain calls (see
# _persist_universal_complete_chain/_gated_safe_get_chain's existing status handling) --
# a measured fact to revisit, not a reason to keep guessing conservatively today.
TERRAIN_REFRESH_SEC: float = 5.0
# Match the 2-slot Schwab chain gate. 4 workers × 200-strike payloads queued ~51 tickers
# and starved the operator card (gate timeouts, Tier-C partial/STALE) at the open.
TERRAIN_WORKERS: int = 2
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
#: refused) hold the ticker out after TERRAIN_QUARANTINE_HARD_FAILS consecutive hits until the
#: next ET day, when it is tried again -- a 4xx can be our own request's fault (2026-09-26: every
#: ticker was refused all weekend for asking for Friday's expired expiry), and a hold nobody
#: lifts would keep a real instrument dark. Soft failures (timeout / 5xx / 429: the venue is
#: busy, the symbol is fine) back off exponentially and re-admit themselves.
TERRAIN_QUARANTINE_HARD_FAILS: int = 3
TERRAIN_QUARANTINE_SOFT_BASE_SEC: float = 60.0
TERRAIN_QUARANTINE_SOFT_MAX_SEC: float = 900.0

_terrain_quarantine: dict[str, dict] = {}
_terrain_consecutive_fails: dict[str, int] = {}
_terrain_quarantine_skips: dict[str, int] = {}
_terrain_quarantine_lock = threading.Lock()


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


def terrain_quarantine_reason(ticker: str | None, now: float) -> str:
    """Why this ticker is not being requested at all at `now`, or "" when it is in the rotation."""
    if not ticker:
        return ""
    tk = ticker_storage_key(ticker)
    with _terrain_quarantine_lock:
        e = _terrain_quarantine.get(tk)
        if not e:
            return ""
        if e.get("hard"):
            return (f"QUARANTINED after {e.get('failures')} consecutive hard rejections — "
                    f"{e.get('reason')}. The vendor refused this symbol, so the loop has stopped "
                    f"requesting it until the next ET day, when it is tried again")
        # RC-281: every constructor supplies until_ts, so absence is MALFORMED STATE, not
        # "no cooldown". My earlier reason claimed the latter; Cursor's runtime probe showed
        # it releases the hold and erases the entry, turning an invariant failure into an
        # immediate vendor retry with the evidence gone.
        from numeric_contract import float_finite_or_none as _fin_q
        until = _fin_q(e.get("until_ts"))
        if until is None:
            return (f"backing off after {e.get('failures')} consecutive failures — "
                    f"{e.get('reason')}; hold has NO expiry recorded (malformed entry), "
                    f"so it is held until the console restarts")
        left = max(0.0, until - now)
        return (f"backing off after {e.get('failures')} consecutive failures — {e.get('reason')}; "
                f"next attempt in {left:.0f}s")


def _terrain_quarantine_blocks(tk: str, now: float) -> bool:
    """True when this ticker must NOT be requested at `now`. Expired soft holds self-release."""
    with _terrain_quarantine_lock:
        e = _terrain_quarantine.get(tk)
        if not e:
            return False
        # RC-281: fail CLOSED on a malformed hold. `or 0.0` dated the expiry to 1970, so the
        # branch never fired, the entry was popped, and the ticker went straight back into
        # rotation — the opposite of a quarantine, reached by a missing field.
        from numeric_contract import float_finite_or_none as _fin_qb
        until = _fin_qb(e.get("until_ts"))
        if until is None or now < until:
            _terrain_quarantine_skips[tk] = _terrain_quarantine_skips.get(tk, 0) + 1
            return True
        _terrain_quarantine.pop(tk, None)      # hold expired — back into the rotation
    log.info("terrain hold elapsed for %s, retrying", tk)
    return False


def _note_terrain_failure(tk: str, reason: str, kind: str, now: float) -> None:
    """Record a refresh that failed at `now` and quarantine when the pattern earns it.

    The streak counter lives under the SAME lock as the quarantine book it feeds. TERRAIN_WORKERS
    threads run the rotation while `/api/terrain` can drive `_terrain_refresh_one(priority=True)`
    for the same ticker concurrently, so a read-modify-write outside the lock can drop a failure —
    and a dropped failure is a retry storm that never reaches its own threshold.
    """
    log_msg: tuple | None = None
    with _terrain_quarantine_lock:
        n = _terrain_consecutive_fails.get(tk, 0) + 1
        _terrain_consecutive_fails[tk] = n
        if n >= TERRAIN_QUARANTINE_HARD_FAILS:
            if kind == "hard":
                already = bool(_terrain_quarantine.get(tk, {}).get("hard"))
                next_day = (datetime.fromtimestamp(now, ET) + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0)
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "hard": True,
                                           "since_ts": now,
                                           "until_ts": next_day.timestamp(), "kind": kind}
                if not already:
                    log_msg = ("terrain QUARANTINE %s until the next ET day after %d hard "
                               "rejections: %s", tk, n, reason)
            else:
                wait = min(TERRAIN_QUARANTINE_SOFT_MAX_SEC,
                           TERRAIN_QUARANTINE_SOFT_BASE_SEC
                           * (2 ** (n - TERRAIN_QUARANTINE_HARD_FAILS)))
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "hard": False,
                                           "since_ts": now,
                                           "until_ts": now + wait, "kind": kind}
                log_msg = ("terrain backoff %s for %.0fs after %d failures: %s",
                           tk, wait, n, reason)
    if log_msg:                               # logged outside the lock
        log.warning(*log_msg)


def _note_terrain_success(tk: str) -> None:
    """A success clears the streak AND any soft hold — the symbol answered."""
    with _terrain_quarantine_lock:
        _terrain_consecutive_fails.pop(tk, None)
        had = _terrain_quarantine.pop(tk, None)
    if had:
        log.info("terrain %s answered, hold cleared", tk)


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


_terrain_loop_running: bool = False
_terrain_loop_thread: threading.Thread | None = None


def terrain_cache_get(ticker: str, now: float) -> dict | None:
    """Return the cached wide-chain terrain snapshot with its staleness at `now` merged.

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
    out.update(terrain_staleness(out.get("computed_ts_utc"), ticker, now))
    return out


#: The least age at which a terrain snapshot stops calling itself current (terrain_staleness also
#: allows two of the loop's delivered cycles).
TERRAIN_STALE_AFTER_SEC: float = 180.0


#: Schwab's sign-in (the refresh token) ends 7 days after it was made; every Schwab call fails
#: from then until the operator signs in again. The header warns from day 5 and is red from day 6.
SCHWAB_SIGN_IN_LIFE_DAYS = 7.0
_SCHWAB_TOKEN_WARN_DAYS = 5.0
_SCHWAB_TOKEN_RED_DAYS = 6.0
SIGN_IN_OK, SIGN_IN_WARN, SIGN_IN_RED, SIGN_IN_UNKNOWN = "ok", "warn", "red", "unknown"
SIGN_IN_REMEDY = "run: python reauth_schwab.py --manual"


def schwab_sign_in_status(creation_ts: float | None, now: float) -> dict:
    """The Schwab sign-in's state at `now`, for the page header (the /api/changes push):
    {urgency, expires, note}, from the token file's creation time. `expires` is the instant it
    ends, in Central Time; unreadable file: unknown, said so."""
    if creation_ts is None:
        return {"urgency": SIGN_IN_UNKNOWN, "expires": None,
                "note": "the Schwab token file is unreadable: the sign-in's age is unknown"}
    age_days = (now - float(creation_ts)) / 86400.0
    expires = ct_label(float(creation_ts) + SCHWAB_SIGN_IN_LIFE_DAYS * 86400.0)
    if age_days >= SCHWAB_SIGN_IN_LIFE_DAYS:
        return {"urgency": SIGN_IN_RED, "expires": expires, "note": f"Schwab sign-in ended {expires}; {SIGN_IN_REMEDY}"}
    if age_days >= _SCHWAB_TOKEN_WARN_DAYS:
        return {"urgency": SIGN_IN_RED if age_days >= _SCHWAB_TOKEN_RED_DAYS else SIGN_IN_WARN,
                "expires": expires, "note": f"Schwab sign-in ends {expires}; {SIGN_IN_REMEDY}"}
    return {"urgency": SIGN_IN_OK, "expires": expires, "note": ""}


def _schwab_token_creation_ts() -> float | None:
    """creation_timestamp from schwab_token.json; None (never a fake age) when unreadable."""
    try:
        raw = json.loads(Path(cfg.token_path).read_text(encoding="utf-8"))
        return float(raw["creation_timestamp"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def terrain_staleness(computed_ts_utc: float | None, ticker: str | None, now: float) -> dict:
    """Whether the levels are current at `now` (epoch seconds), and WHY NOT when they are not (RC-91).

    RC-146 — the reason must come from the PRODUCER, not be inferred from a clock. Age alone
    cannot tell a deliberate pause from a broken loop, so this function used to answer "inside
    its window but not producing" for a scheduler that was working exactly as designed. When a
    ticker was skipped on purpose, `terrain_skip_reason` has the real sentence and it wins.
    Pass `ticker` wherever it is known; omitting it degrades to the old clock-only reason.

    MEASURED 2026-07-27 18:02 ET: /api/terrain computed_ts_utc did not advance across 90s against
    a 60s cadence, the gamma panel served data 90 MINUTES old under a `terrain_live_cache` label,
    and spot beside it was 3 seconds old. The terrain loop refreshes only while
    _is_loggable_session() is true, which ends 30 minutes after the day's close — 210 minutes
    before the capture window closes. That function is the BACKGROUND LOGGING gate; using it to
    decide whether the screen is current answered a different question with the same switch.

    Stopping the loop after the post-market buffer may well be correct. Serving its last output
    under a live label is not: staleness that is budget-justified gets LABELLED, staleness that is
    not gets removed (the RC-78 rule, applied to the scorecard that day and never to terrain).
    """
    refreshing = _is_loggable_session(now)
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
    quarantined = terrain_quarantine_reason(ticker, now)
    failure = "" if (skipped or quarantined) else str(_terrain_refresh_last_error.get(
        ticker_storage_key(ticker) if ticker else "", "") or "")
    hard_quarantine = bool(q_entry.get("hard"))
    if not refreshing and computed_ts_utc is not None:
        return {"levels_stale": False, "levels_age_sec": round(now - float(computed_ts_utc), 1),
                "levels_refresh_active": False, "levels_market_closed": True,
                "levels_as_of": ct_label(computed_ts_utc),
                "levels_stale_reason": "", "levels_paused_on_purpose": False,
                "levels_quarantined": False, "levels_failing": False}
    if computed_ts_utc is None:
        return {"levels_stale": True, "levels_age_sec": None, "levels_refresh_active": refreshing,
                "levels_stale_reason": (
                    quarantined or skipped
                    or (f"no terrain snapshot has been computed yet — {failure}" if failure
                        else "no terrain snapshot has been computed yet")),
                "levels_paused_on_purpose": bool(skipped and not quarantined),
                "levels_quarantined": bool(quarantined),
                "levels_failing": bool(failure or hard_quarantine)}
    age = round(now - float(computed_ts_utc), 1)
    # age is judged against the cycle the loop delivers (a full sweep), not its sleep floor
    # (TERRAIN_REFRESH_SEC)
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
                  f"(outside the refresh window: "
                  f"{_refresh_window_ct(datetime.fromtimestamp(now, ET).date().isoformat())})"
                  if not refreshing else
                  f"levels are {age:.0f}s old; the refresh loop is running but has not reached "
                  f"this ticker in two of its cycles ({expected:.0f}s each)")
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
            "levels_quarantined": bool(quarantined)}


#: Rotation depth inside the 09:30-10:00 contention window for tickers nobody is viewing: each
#: still refreshes at least once per this many seconds.
CONTENTION_ROTATION_SEC: float = 300.0


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
    all_tickers: list[str], mins: int, cycle_n: int,
    viewed: "list[str] | None" = None,
) -> tuple[list[str], list[str]]:
    """Which tickers this cycle refreshes, and which are DEFERRED to a later cycle.

    RC-161. The morning guard used to DROP every non-sentinel for a full half hour, which made
    the accrual mandate sentinel-only in [555, 600) — a universal claim that three tickers were
    meeting. Exclusion is now ROTATION: no enrolled ticker is ever removed from the board, it is
    scheduled later within the window.

    Priority inside the window is by VIEWING DEMAND, never by symbol name (universality,
    operator 2026-09-23): the tickers a page has open (`viewed`, _viewed_tickers) refresh every
    cycle; every other enrolled ticker rotates so it still refreshes
    at least once per CONTENTION_ROTATION_SEC (RC-146: spread the open's vendor budget, never
    starve a ticker).

    Returns (refresh_now, deferred_this_cycle). Outside the contention window every enrolled
    ticker refreshes every cycle -- viewing never rotates the board (collection mandate; the
    audit of #280 found rotation-while-viewing cut every non-viewed ticker to one refresh per
    300 s or more, all session).
    """
    viewed_set = {str(t).upper() for t in (viewed or [])}
    sentinels = [t for t in all_tickers if str(t).upper() in viewed_set]
    others = [t for t in all_tickers if str(t).upper() not in viewed_set]
    in_contention = TERRAIN_CONTENTION_START_MINS <= int(mins) <= TERRAIN_CONTENTION_END_MINS
    if not in_contention:
        return list(all_tickers), []
    # integer ceiling division — server.py has no module-level `math`, and adding an import for
    # one division would be a wider change than the fix
    _cyc = max(1, int(TERRAIN_REFRESH_SEC))
    depth = max(1, -(-int(CONTENTION_ROTATION_SEC) // _cyc))
    idx = int(cycle_n) % depth
    slice_now = others[idx::depth]
    deferred = [t for t in others if t not in set(slice_now)]
    return sentinels + slice_now, deferred


def _gamma_surface_wanted(tk: str) -> bool:
    """Viewed: a page has the ticker open (its /api/changes connection), on any workspace, for
    as long as it stays open. The one viewing signal, the same for every ticker."""
    return tk in push_changes.watched()


def _viewed_tickers() -> list[str]:
    """Every viewed ticker: the levels loop refreshes each one every cycle, on the board or not,
    keeps its chain and projects its heatmap."""
    return sorted(push_changes.watched())


def _live_stream_greeks(streamed: dict, now: float) -> dict:
    """The streamed option values whose contract is live at `now` (the one live rule)."""
    return {s: g for s, g in streamed.items() if lmp.feed_live_for(s, "LEVELONE_OPTIONS", now)}

#: Per-ticker revision of `_gamma_surface`, bumped on every publication; guarded by
#: _terrain_cache_lock.
_gamma_surface_seq: dict[str, int] = {}


def _next_gamma_surface_seq(tk: str) -> int:
    """Caller must hold _terrain_cache_lock."""
    n = _gamma_surface_seq.get(tk, 0) + 1
    _gamma_surface_seq[tk] = n
    return n


def _desired_stream_greeks_for_ticker(tk: str, listed: "frozenset | None" = None) -> dict:
    """Every currently-live streamed GAMMA/DELTA/OPEN_INTEREST/VOLUME entry for a
    contract belonging to `tk` — the PRIMARY/pinned contract AND every ADDITIONALLY-
    desired contract (RC-UI-3 multi-contract coverage), gathered FRESH on every call.

    Independent-review finding (2026-09-12), root cause of the "refreshing B loses A's
    update" defect: the two callers below used to build a single-entry
    `{contract_symbol: greeks}` map for whichever ONE contract triggered that particular
    refresh, then overlay it onto the untouched REST baseline — so refreshing B always
    discarded A's already-fresh streamed value, because the baseline itself carries no
    memory of a prior overlay. Fixed at the root by never relying on such memory: this
    reconstructs the FULL multi-contract streamed set from scratch every call.
    `get_stream_greeks` IS the live per-symbol store (app.options.order_flow.state),
    cleared exactly when a symbol's coverage genuinely ends (clear_symbol) — so
    re-querying it for every currently-desired symbol on every refresh, no matter which
    one triggered it, always reconstructs every symbol's latest known state, and a symbol
    whose coverage has ended is correctly absent (never lingers as a stale entry here).
    A contract is the ticker's when Schwab listed it in the ticker's chain: `listed`, the chain
    being published, else the held one."""
    from app.options.order_flow.state import get_stream_greeks
    out: dict = {}
    for sym in _desired_option_symbols_for_ticker(tk, listed):
        greeks = get_stream_greeks(sym)
        if greeks:
            out[sym] = greeks
    return out


def _desired_option_symbols_for_ticker(tk: str, listed: "frozenset | None" = None) -> "list[str]":
    """Every option-contract symbol this daemon currently DESIRES for `tk` — the primary/
    pinned contract AND every additionally-desired contract (RC-UI-3 multi-contract
    coverage) — regardless of whether a stream tick has landed for it yet.

    Extracted from `_desired_stream_greeks_for_ticker` (2026-09-16, coverage-summary
    'pending' state): that function's own candidate set already IS "desired", but it only
    ever surfaced the subset with an existing `get_stream_greeks` entry — a symbol the
    vendor has genuinely admitted but which has not yet produced its first tick was
    therefore indistinguishable from a symbol nobody ever asked for. This is the desired
    set on its own, so a caller can tell "requested, awaiting first tick" (PENDING) apart
    from "never desired at all" (UNAVAILABLE)."""
    from app.options.order_flow.streaming import (
        get_active_option_contract, get_active_option_contracts)
    out: "list[str]" = []
    candidates = list(get_active_option_contracts())
    primary = get_active_option_contract()
    if primary:
        candidates.append(primary)
    for sym in candidates:
        if sym and sym not in out and (sym in listed if listed is not None else _contract_is_for(sym, tk)):
            out.append(sym)
    return out


def _option_contract_admission_summary(tk: str, now: float) -> dict:
    """At `now`, per-symbol admitted/observed/active/pending/rejected accounting for `tk`'s desired
    option contracts, sourced ENTIRELY from PRODUCER acknowledgements (2026-09-16,
    independent-review follow-up mandate item 1: "expose the exact admitted, active,
    pending and rejected contracts"). Every bucket answers a materially different
    question about a desired symbol:
      'active'   — has produced a tick and is live now (live_market_plane.feed_live_for,
                   LEVELONE_OPTIONS -- the rule the overlay and the 'live' cell state use).
      'observed' — has produced a tick but is not live now: a past observation.
      'admitted' — the DAEMON's own durable, heartbeat-confirmed open coverage epoch names
                   this symbol (streaming.read_producer_admitted_option_contracts,
                   LEVELONE_OPTIONS service) but no tick has EVER arrived — the vendor
                   subscription itself is confirmed, only the first observation is still
                   outstanding.
      'pending'  — desired, the daemon is CONFIRMED alive, but neither a tick nor a
                   confirmed admission has landed yet — requested, outcome not yet known.
      'rejected' — {symbol: vendor_error} for every desired symbol the vendor's most
                   recent batched subscribe attempt explicitly refused.
    A desired symbol that fits none of the above (daemon unreachable) is simply omitted
    from every bucket — unknown is never fabricated as any of these five claims; the
    `daemon_available` flag on the returned dict is how a caller tells "genuinely nothing
    to report yet" apart from "cannot know right now". `active` and `observed` are
    mutually exclusive (a symbol is one or the other, never both), and a REJECTED symbol
    is reported ONLY in `rejected` — never also counted as `active`/`observed`/`admitted`/
    `pending`, so a caller cannot mistake "the vendor refused this" for any flavor of
    success by unioning buckets carelessly."""
    from app.options.order_flow.streaming import (
        read_producer_admitted_option_contracts, read_producer_rejected_option_contracts,
        is_option_producer_daemon_available)
    desired = _desired_option_symbols_for_ticker(tk)
    daemon_available = is_option_producer_daemon_available(now)
    rejected_all = read_producer_rejected_option_contracts(now)
    admitted_l1 = set((read_producer_admitted_option_contracts(now) or {}).get("LEVELONE_OPTIONS") or [])
    streamed = _desired_stream_greeks_for_ticker(tk)
    admitted, active, observed, pending = [], [], [], []
    rejected: "dict[str, str]" = {}
    for sym in desired:
        if sym in rejected_all:
            rejected[sym] = rejected_all[sym]
        elif sym in streamed:
            (active if lmp.feed_live_for(sym, "LEVELONE_OPTIONS", now) else observed).append(sym)
        elif sym in admitted_l1:
            admitted.append(sym)
        elif daemon_available:
            pending.append(sym)
        # else: daemon unavailable -- genuinely unknown, omitted from every bucket
    # Requested by the view but left out by the shared Schwab socket's budget
    # (stream_spine.OPTION_CONTRACTS_MAX_HELD): a capacity decision, reported as itself --
    # never as pending (it is not coming) nor as a vendor rejection (the vendor never saw it).
    from app.options.order_flow.streaming import get_option_contracts_over_budget
    not_admitted = sorted(s for s in get_option_contracts_over_budget() if _contract_is_for(s, tk))
    return {
        "daemon_available": daemon_available,
        "admitted": sorted(admitted), "active": sorted(active), "observed": sorted(observed),
        "pending": sorted(pending), "rejected": rejected, "not_admitted": not_admitted,
    }


def _overlaid_symbols(pre: list, post: list) -> list[str]:
    """Which contracts' own dicts `overlay_streamed_contract_fields` actually replaced with a
    freshened copy -- that function's own contract is "sparse, non-destructive... a contract
    absent from streamed_by_symbol is passed through UNCHANGED (SAME dict, not a copy)", so a
    changed contract is identifiable by object identity alone (`is not`), with no need to
    diff field values or touch that function's own return signature.

    A SIXTH independent review (2026-09-13), REPRODUCED: the heatmap's 'observed' demand
    state promoted EVERY currently-accepted column the instant `stream_overlay_contracts`
    (a single surface-wide COUNT) was merely nonzero, whichever contract or expiry
    actually received the freshening -- one overlaid contract on an UNRELATED expiry
    incorrectly marked a completely different column as carrying real observed evidence.
    This is the missing piece: WHICH symbols were actually freshened, so a consumer can
    bind 'observed' to the specific column/contracts it actually covers."""
    return [new.get("symbol") for orig, new in zip(pre, post)
            if new is not orig and isinstance(new, dict) and new.get("symbol")]


def _gamma_surface_contracts_with_stream_overlay(tk: str, contracts: list, now: float) -> tuple[list, int, list[str]]:
    """`contracts` with every option contract of `tk` live at `now` carrying its streamed
    fields (overlay_streamed_contract_fields; RC-UI-3: primary AND every additional contract).
    Changes no formula; the stream owns a live contract's fields.

    Fails closed to the unmodified `contracts` on any error or when nothing applies — this is
    a best-effort freshening, never a precondition for the projection to run at all."""
    try:
        from math_exposure_core import overlay_streamed_contract_fields

        streamed = _live_stream_greeks(_desired_stream_greeks_for_ticker(tk), now)
        if not streamed:
            return contracts, 0, []
        overlaid, n = overlay_streamed_contract_fields(contracts, streamed)
        return overlaid, n, _overlaid_symbols(contracts, overlaid)
    except Exception as e:  # institutional-swallow-ok: best-effort freshening, never load-bearing
        log.debug("gamma-surface stream overlay skipped for %s: %s", tk, e)
        return contracts, 0, []


def _leg_stream_ts_recv(greeks: dict | None) -> float | None:
    """The freshest of a streamed contract's own per-field `_ts_recv` stamps (get_stream_greeks'
    shape, app.options.order_flow.state), or None if `greeks` is absent/empty. Any one of these
    fields ticking is evidence the contract is actively producing observations right now, so the
    MAX (not a single hardcoded field) is the contract's own last-observed instant."""
    if not greeks:
        return None
    candidates = [greeks.get(k) for k in
                  ("gamma_ts_recv", "open_interest_ts_recv", "delta_ts_recv", "total_volume_ts_recv")]
    candidates = [c for c in candidates if isinstance(c, (int, float))]
    return max(candidates) if candidates else None


_STREAM_STATE_ORDER = ("stale", "pending", "daemon_unavailable", "rejected", "not_admitted")


def _stream_state_of(states: list) -> str:
    """One stream state for a set of leg (or cell) states: live when all are live, partial when
    some are, else the first of _STREAM_STATE_ORDER present, else unavailable."""
    if not states:
        return "unavailable"
    if all(s == "live" for s in states):
        return "live"
    if any(s in ("live", "partial") for s in states):
        return "partial"
    return next((o for o in _STREAM_STATE_ORDER if o in states), "unavailable")


def _stamp_gamma_surface_cell_stream_state(surface: dict, streamed: dict, overlay_symbols: set,
                                           rejected_symbols: "dict[str, str] | None" = None,
                                           desired_symbols: "set[str] | None" = None, *,
                                           daemon_available: bool = True) -> None:
    """Operator directive (2026-09-15, always-live heatmap mandate): attach per-leg (call/put)
    and per-cell aggregate STREAM state to an already-projected gamma surface's cells, in place.

    Pure disclosure/gating metadata layered on top of RC-80's single faucet — this NEVER touches
    a cell's already-computed net_gex_1pct/etc value (project_gamma_surface/
    compute_exposures_by_strike remains the sole exposure computation). It only annotates, per
    leg, WHETHER that value is currently backed by a confirmed-fresh Schwab stream tick, so a
    client can honestly render LIVE / PARTIAL / STALE / PENDING / REJECTED / DAEMON_UNAVAILABLE /
    UNAVAILABLE instead of presenting every REST-cadence cell as indistinguishable from a
    genuinely streamed one.

    Per leg, `overlay_symbols` is the EXACT set _publish_levels's stream overlay already
    decided passed this cycle's
    REST-precedence check and the live rule for this specific symbol — reused
    verbatim rather than re-deriving a second staleness policy. `rejected_symbols` (2026-09-16,
    audit finding #6 — "fail the affected cells visibly", bounded-vendor-call reconciliation) is
    the producer's own {symbol: vendor_error} map (streaming.read_producer_rejected_option_
    contracts) — a symbol the vendor explicitly refused, not merely one not yet confirmed.
    `desired_symbols` (2026-09-16, operator's follow-up mandate: disclose PENDING distinctly from
    UNAVAILABLE) is `_desired_option_symbols_for_ticker`'s output — every symbol the daemon has
    asked the vendor for, whether or not a tick has landed yet.

    Independent-review finding (2026-09-16, follow-up mandate): 'pending' used to mean only
    "the CLIENT desires this symbol" — indistinguishable from a daemon that has silently died
    and will never admit anything again. `daemon_available` (streaming.
    is_option_producer_daemon_available — a FRESH producer heartbeat confirmed on this exact
    connection, never inferred) gates 'pending': a desired symbol reads 'pending' only while the
    daemon is confirmed alive; the identical symbol reads 'daemon_unavailable' the instant it
    is not, which is a materially different, and more actionable, fact for an operator ("the
    daemon needs restarting", not "this contract is merely queued behind a live one"):
      'live'                — this symbol's tick was fresh enough to be overlaid THIS cycle.
      'stale'                — the symbol IS currently desired/subscribed (present in
                              `streamed`, which _desired_stream_greeks_for_ticker already
                              filters to symbols matching this ticker) but its tick did not
                              pass this cycle's check.
      'pending'              — the symbol is desired, the daemon is CONFIRMED alive, and no
                              tick/rejection has landed yet — requested, outcome not yet known.
      'daemon_unavailable'   — the symbol is desired but the daemon's own producer heartbeat is
                              stale or absent — the outcome cannot be pending, because nothing
                              is currently working on it.
      'rejected'             — the vendor explicitly refused this contract's subscription; its
                              own error is carried on the leg so the UI can disclose WHY.
      'not_admitted'         — the view asked for this contract but it was not admitted to
                              the shared Schwab socket: outside the spot-ranked budget
                              (stream_spine.OPTION_CONTRACTS_MAX_HELD) or no spot to rank it
                              by. Not a vendor refusal and not coming -- so never 'pending';
                              the reason rides on the leg as `not_admitted_reason`.
      'unavailable'          — no symbol for this leg (missing contract), or a symbol never
                              desired at all — covers unsubscribed, missing, and mismatched-
                              identity alike.

    Cell aggregate, over whichever legs actually exist for this strike/expiry, checked in this
    priority order (live > partial > stale > pending > daemon_unavailable > rejected >
    unavailable) — 'partial' requires at least one live leg, not all; every other aggregate is
    "no leg is any higher-priority state, at least one existing leg is this one"."""
    now = time.time()
    rejected_symbols = rejected_symbols or {}
    desired_symbols = desired_symbols or set()
    from app.options.order_flow.streaming import get_option_contracts_not_admitted
    not_admitted_symbols = get_option_contracts_not_admitted()
    for cell in (surface.get("cells") or []):
        contracts_row = cell.get("contracts") or []
        state_row = []
        for pair in contracts_row:
            if not isinstance(pair, dict):
                state_row.append(None)
                continue
            legs: dict = {}
            leg_states: list[str] = []
            for side in ("call", "put"):
                sym = pair.get(side)
                if not sym:
                    continue
                greeks = streamed.get(sym)
                if sym in overlay_symbols:
                    leg_state = "live"
                elif sym in streamed:
                    leg_state = "stale"
                elif sym in rejected_symbols:
                    leg_state = "rejected"
                elif sym in desired_symbols and not daemon_available:
                    leg_state = "daemon_unavailable"
                elif sym in desired_symbols:
                    leg_state = "pending"
                elif sym in not_admitted_symbols:
                    leg_state = "not_admitted"
                else:
                    leg_state = "unavailable"
                leg_states.append(leg_state)
                ts_recv = _leg_stream_ts_recv(greeks)
                leg_out = {
                    "symbol": sym, "state": leg_state, "ts_recv": ts_recv,
                    "age_sec": (round(now - ts_recv, 1) if ts_recv is not None else None),
                }
                if leg_state == "rejected":
                    leg_out["rejected_reason"] = rejected_symbols.get(sym)
                elif leg_state == "not_admitted":
                    leg_out["not_admitted_reason"] = not_admitted_symbols.get(sym)
                legs[side] = leg_out
            legs["state"] = _stream_state_of(leg_states)
            ages = [leg["age_sec"] for leg in legs.values() if isinstance(leg, dict) and leg["age_sec"] is not None]
            legs["age_sec"] = max(ages) if ages else None   # the cell's oldest confirmed leg
            state_row.append(legs)
        cell["stream"] = state_row
    # each expiry column's state, from its cells' states -- the column header's streaming status
    exps = [e.get("expiry") for e in surface.get("expirations") or []]
    surface["stream_by_expiry"] = {
        e: _stream_state_of([row["stream"][j]["state"] for row in surface.get("cells") or []
                             if j < len(row.get("stream") or []) and row["stream"][j]])
        for j, e in enumerate(exps)}


def _gamma_surface_cell_state_counts(surface: dict) -> dict:
    """Tally the per-cell 'state' _stamp_gamma_surface_cell_stream_state already attached into
    cheap surface-level counts — a client or test's one-field check instead of scanning every
    cell. The seven states are mutually exclusive per cell (see that function's docstring)."""
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "daemon_unavailable": 0,
              "rejected": 0, "not_admitted": 0, "unavailable": 0}
    for cell in (surface.get("cells") or []):
        for col in (cell.get("stream") or []):
            if isinstance(col, dict) and col.get("state") in counts:
                counts[col["state"]] += 1
    return counts


def _gamma_surface_coverage_summary(surface: dict) -> dict:
    """The CANONICAL-SURFACE coverage verdict for a projected surface — every strike x
    every expiry the server projected, not merely whichever subset the client happens to
    be scrolled/scoped to (2026-09-16, audit finding #6; independent-review CORRECTION,
    follow-up mandate: this field's scope must be named honestly, because it is NOT the
    same thing as "coverage of what the operator is currently looking at").

    Independent-review finding (2026-09-16): Auto/Wider/All strike-count windowing
    (EdShell.scopeSelect) and expiry-column windowing (ed-gamma.js's own viewCols) are
    BOTH decided entirely client-side and never communicated to the server — the server
    has no way to know which strikes/expiries are actually rendered right now. Computing
    `meets_live_requirement` over this whole canonical surface therefore answers "is the
    full projected book fully live", which can be STRICTER than what the mandate's own
    "every VISIBLE cell" language asks for (a narrower Auto-scoped view could be 100% live
    while a distant, invisible strike this field still counts is merely 'pending'). This
    field stays a genuinely useful, correctly-labelled canonical/diagnostic metric — the
    CLIENT's own "LIVE" word is gated on a SEPARATE, DOM-derived visible-scope computation
    (ed-gamma.js's `_visibleCellCoverage`, counting only the `.hcell` elements this exact
    render painted) which this field must never be mistaken for. The `scope` key on the
    returned dict makes that explicit in the wire payload itself, not only in this
    docstring.

    Coverage is judged only over cells that HAVE a real contract identity (at least one of
    call/put resolved to an actual OSI symbol) — a strike/expiry combination with no
    contract at all was never a viewable data point, and counting it against the bar would
    make `meets_live_requirement` false on nearly every real chain (different expiries
    legitimately cover different strike ranges) for a reason that has nothing to do with
    streaming health.

    `meets_live_requirement` implements the operator's own already-recorded directive
    (2026-09-15, "always-live heatmap mandate"): "every visible heatmap cell must
    correspond to an exact option contract actively receiving streamed Schwab updates" —
    literally 100% of cells-with-a-contract must be 'live', not merely "at least one cell
    is" — over THIS field's own canonical scope; the client's visible-scope computation is
    the actual authority for the on-screen LIVE word.

    `pending` (2026-09-16, operator's follow-up mandate) is counted and reported distinctly
    from `unavailable`: a cell whose contract has been REQUESTED of the vendor but has not
    yet ticked (or been rejected) is materially different from one nobody asked for at all,
    and both the mandate's coverage-disclosure requirement and a fair 'not yet live' verdict
    need that distinction on screen, not folded into the same bucket. `daemon_unavailable`
    (2026-09-16, follow-up mandate) is likewise counted distinctly from `pending`: the
    capture daemon itself being unreachable is a materially different, more actionable fact
    than a contract merely queued behind a live daemon's own poll cycle."""
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "daemon_unavailable": 0,
              "rejected": 0, "not_admitted": 0, "unavailable": 0}
    relevant = 0
    for cell in (surface.get("cells") or []):
        contracts_row = cell.get("contracts") or []
        stream_row = cell.get("stream") or []
        for j, col in enumerate(stream_row):
            if not isinstance(col, dict):
                continue          # no contract identity at all -- never a viewable data cell
            pair = contracts_row[j] if j < len(contracts_row) else None
            has_identity = bool(isinstance(pair, dict) and (pair.get("call") or pair.get("put")))
            if not has_identity:
                continue
            relevant += 1
            state = col.get("state")
            if state in counts:
                counts[state] += 1
            else:
                counts["unavailable"] += 1
    live_pct = round(100.0 * counts["live"] / relevant, 1) if relevant else 0.0
    return {
        # Independent-review finding (2026-09-16): explicit, machine-readable scope
        # disclosure, not just a docstring comment -- this whole dict describes the
        # CANONICAL surface (every projected strike x expiry), never the client's current
        # Auto/Wider/All-windowed view. A consumer that needs the on-screen LIVE verdict
        # must use the client's own visible-scope computation, not this field.
        "scope": "canonical_surface",
        "total_visible_cells": relevant,
        "live": counts["live"], "partial": counts["partial"], "stale": counts["stale"],
        "pending": counts["pending"], "daemon_unavailable": counts["daemon_unavailable"],
        "rejected": counts["rejected"], "not_admitted": counts["not_admitted"],
        "unavailable": counts["unavailable"],
        "live_pct": live_pct,
        "meets_live_requirement": relevant > 0 and counts["live"] == relevant,
    }


#: At most one tick-driven reprice of a viewed ticker per this many seconds. MEASURED 2026-09-24
#: 14:50 CT (py-spy, 15 samples): repricing on every spot tick held the GIL in 10 of 15 samples
#: and starved the event loop that serves the browser (/api/health took 6 s). The levels move
#: with open interest and implied vol, not tick to tick: 2026-09-25, 30 of 43 tickers kept every
#: wall and flip all session.
LEVELS_REPRICE_MIN_INTERVAL_SEC = 10.0
_levels_locks: "dict[str, threading.Lock]" = {}
_levels_locks_guard = threading.Lock()
_reprice_dirty: "set[str]" = set()
_reprice_running: "set[str]" = set()
_reprice_guard = threading.Lock()


def _contract_is_for(sym: "str | None", tk: str) -> bool:
    """An option contract belongs to `tk` when Schwab listed it in `tk`'s chain -- the same rule
    for every instrument, whatever the contract's root (SPXW and SPX are both $SPX's)."""
    with _terrain_cache_lock:
        return bool(sym) and sym in ((_terrain_cache.get(tk) or {}).get("_contract_symbols") or ())


def _contract_ticker(sym: str) -> "str | None":
    """The ticker whose chain Schwab listed `sym` in, or None."""
    with _terrain_cache_lock:
        return next((tk for tk, p in _terrain_cache.items() if sym in (p.get("_contract_symbols") or ())), None)


def _ensure_default_option_contract(tk: str, now: float) -> None:
    """The option contract whose OPTIONS_BOOK streams follows the page's ticker: the one already
    desired or held by the daemon at `now` when it is this ticker's, else the at-the-money call of
    the ticker's front expiry; cleared when the ticker has none. The operator's POST
    /api/streaming/active-option-contract still wins until the ticker changes."""
    from app.options.order_flow.streaming import (
        clear_active_option_contract, get_active_option_contract, set_active_option_contract)
    if _contract_is_for(get_active_option_contract(), tk):
        return
    held = ((lmp.daemon_status(now) or {}).get("held") or {}).get("OPTIONS_BOOK") or []
    with _terrain_cache_lock:
        default = (_terrain_cache.get(tk) or {}).get("_default_contract")
    sym = held[0] if held and _contract_is_for(held[0], tk) else default
    if sym:
        set_active_option_contract(sym)
    elif get_active_option_contract():
        clear_active_option_contract(reason="no_contract_for_ticker")


def _levels_lock(tk: str) -> threading.Lock:
    with _levels_locks_guard:
        return _levels_locks.setdefault(tk, threading.Lock())


def _publish_levels(tk: str, chain: "list | None" = None, fetched_ts: "float | None" = None,
                    *, captures: "list | None" = None, now: float) -> "TerrainSnapshot | None":
    """THE producer of a ticker's levels, per-strike rows and gamma-surface grid.

    Prices the ticker's chain once -- overlaid with any fresher streamed option greeks, at the
    current spot -- and publishes all three together, so the heatmap, Strike Detail and Key
    Levels always show one computation. The terrain loop passes a newly fetched chain; a tick on
    a viewed ticker passes none and the kept chain is repriced. One call at a time per ticker:
    each publication is computed from inputs read after the one it replaces. `captures` (startup
    and a closed market, DATA_FLOW decision 7) are the two newest market days' stored captures,
    read once: the newest is priced with Schwab's underlying price from that capture, valued and
    dated at its own time, and both feed the forces and prior-day rows. Returns the snapshot, or
    None when there is no chain to price."""
    from math_exposure_core import overlay_streamed_contract_fields
    from app.options.order_flow.streaming import (
        read_producer_rejected_option_contracts, is_option_producer_daemon_available)
    with _levels_lock(tk):
        with _terrain_cache_lock:
            payload = dict(_terrain_cache.get(tk) or {})
        capture = captures[0] if captures else None
        if capture is not None:
            chain, fetched_ts = capture["contracts"], capture["ts_utc"]
        new_chain = chain is not None
        if chain is None:
            chain, fetched_ts = payload.get("_chain"), payload.get("_chain_fetched_ts")
            if not chain:
                return None
        if capture is not None:
            spot, spot_source, spot_ts = capture["spot"], SPOT_SOURCE_CAPTURE, capture["ts_utc"]
        else:
            spot, spot_source, spot_ts = resolve_spot(tk)
        if new_chain:       # the ticker's contracts are the ones Schwab listed in this chain
            payload.update(_contract_symbols=frozenset(c.get("symbol") for c in chain if c.get("symbol")),
                           _default_contract=front_atm_call(chain, spot))
        listed = payload.get("_contract_symbols") or frozenset()
        streamed = _desired_stream_greeks_for_ticker(tk, listed)
        priced, n_live = overlay_streamed_contract_fields(chain, _live_stream_greeks(streamed, now))
        live_syms = _overlaid_symbols(chain, priced)
        snap = compute_terrain(tk, priced, spot, now=(
            datetime.fromtimestamp(fetched_ts, ET) if capture is not None else None))
        payload.update(snap.to_dict())
        viewed = _gamma_surface_wanted(tk)
        payload.update({
            # as of the chain they were computed from: a reprice on a kept chain does not make
            # the levels newer, so a chain that stops arriving shows as stale
            "computed_ts_utc": fetched_ts,
            "levels_source": LEVELS_SOURCE_WIDE_CHAIN,
            "chain_basis": capture["basis"] if capture is not None else CAPTURE_BASIS,
            "spot_source": spot_source, "spot_as_of_ts_utc": spot_ts,
            **_atr_fields(tk),
            "_per_strike": snap.per_strike, "_gamma_surface": None,
            "_vanna_rows": _vanna_rows(snap), "_charm_rows": _charm_rows(snap),
            # only a viewed ticker is repriced between chain fetches, so only its chain is kept
            "_chain": chain if viewed else None, "_chain_fetched_ts": fetched_ts,
        })
        # the values read from the stored chain captures (forces, the prior day's per-strike rows)
        # change only with a new capture or a new chain day: computed then, once, for all readers
        if new_chain:
            captures_key = (newest_capture_ts(get_db().db_path, tk), et_date_str_from_ts_utc(float(fetched_ts)))
            if payload.get("_captures_key") != captures_key:
                stored = captures if captures is not None else last_capture_per_day(get_db().db_path, tk, 2)
                payload.update(_forces=_forces_from_captures(tk, stored),
                               _prior_strikes=_prior_strikes(stored, fetched_ts),
                               _captures_key=captures_key)
        if viewed and spot is not None and snap.books:
            surface = project_gamma_surface(priced, snap.books)
            surface.update(spot=float(spot), spot_source=spot_source, spot_as_of_ts_utc=spot_ts,
                           stream_overlay_contracts=n_live, stream_overlay_symbols=live_syms)
            _stamp_gamma_surface_cell_stream_state(
                surface, streamed, set(live_syms), read_producer_rejected_option_contracts(now),
                set(_desired_option_symbols_for_ticker(tk, listed)),
                daemon_available=is_option_producer_daemon_available(now))
            payload["_gamma_surface"] = surface
        # a stored capture's price is no reference for a live cross: only live publications
        # keep one and record crosses
        crosses, payload["_cross_ref"] = ([], {}) if capture is not None else level_crosses(
            payload.get("_cross_ref") or {}, snap.spot,
            [(name, getattr(snap, k)) for k, name in CROSS_LEVELS if getattr(snap, k) is not None])
        with _terrain_cache_lock:
            if payload["_gamma_surface"] is not None:
                payload["_gamma_surface"]["surface_seq"] = _next_gamma_surface_seq(tk)
            _terrain_cache[tk] = payload
        push_changes.changed(tk, push_changes.LEVELS)
        if new_chain:
            push_changes.changed(tk, push_changes.CHAIN)
        _record_level_crosses(tk, crosses, snap.spot, spot_ts)
        return snap


#: the levels whose crossing by spot is recorded, with their display names
CROSS_LEVELS = (("call_wall", "Call g-Wall"), ("put_wall", "Put g-Wall"), ("gamma_flip", "Gamma Flip"),
                ("net_gex_peak", "Net Γ peak"), ("max_pain", "Max Pain"),
                ("call_delta_wall", "Call d-Wall"), ("put_delta_wall", "Put d-Wall"))


def level_crosses(ref: dict, spot: "float | None", levels: list) -> "tuple[list, dict]":
    """The levels spot has moved through, and the references for the next publication.

    `ref` holds, per level name, the last live spot that was not exactly at that level; `levels`
    is [(name, value)] as published now. A cross is a strict change of side against the level's
    value now: up when ref < level < spot, down when spot < level < ref. Spot exactly at a
    level is on neither side: nothing is recorded and that level's reference stays, so reaching
    a level and turning back records nothing, and passing through after stopping on it records
    one cross. Returns ([(name, level, "up" | "down")], {name: reference})."""
    crosses, refs = [], {}
    for name, level in levels:
        was = ref.get(name)
        if spot is None or spot == level:
            if was is not None:
                refs[name] = was
            continue
        refs[name] = spot
        if was is not None and was != level and (was < level) != (spot < level):
            crosses.append((name, float(level), "up" if spot > level else "down"))
    return crosses, refs


def _record_level_crosses(tk: str, crosses: list, spot: "float | None", spot_ts: "float | None") -> None:
    """Write each cross as one row, at the time of the price that made it (Schwab's trade time
    on the daemon's price row)."""
    if not crosses:
        return
    if spot_ts is None:
        log.warning("level crosses for %s not recorded: the crossing price has no trade time: %s", tk, crosses)
        return
    ts_et = datetime.fromtimestamp(spot_ts, ET).strftime("%Y-%m-%d %H:%M:%S ET")
    for name, level, direction in crosses:
        get_db().log_level_cross(LevelCrossEvent(
            ticker=tk, ts_utc=float(spot_ts), ts_et=ts_et, level_name=name, level_value=level,
            direction=direction, spot_at_cross=float(spot), zone_before=None, zone_after=None,
            timeframe="1m"))


def _vanna_rows(snap: "TerrainSnapshot") -> list:
    """[strike, net dealer vanna] for every strike with open interest, from the published book:
    each strike's net_vanna as compute_exposures_by_strike computed it (+call/-put)."""
    exposures, _diag = merge_exposure_books(snap.books.values())
    rows = []
    for k, b in exposures.items():
        net = bucket_metric(b, "net_vanna")
        if net is None:
            continue
        rows.append([round(float(k), 2), round(net, 2)])
    rows.sort(key=lambda r: r[0])
    return rows


def _charm_rows(snap: "TerrainSnapshot") -> list:
    """[strike, net dealer charm] from the published charm map (the charm walls' own)."""
    return sorted([round(float(k), 2), round(float(b["net_charm"]), 4)]
                  for k, b in (snap.charm_by_strike or {}).items() if b.get("net_charm") is not None)


def _tick_ticker(sym: str) -> "str | None":
    """The cached ticker a streamed symbol moves: the equity itself, or an option contract's
    underlying."""
    from instrument_identity import vendor_option_root
    if not vendor_option_root(sym):
        return ticker_storage_key(sym)
    return _contract_ticker(sym)


def _on_stream_tick(sym: str) -> None:
    """Called by the live feed, on the event loop, for every streamed equity quote and every
    option quote carrying greeks, open interest or volume. Queues a reprice of the symbol's
    ticker when someone is viewing it, and returns at once."""
    tk = _tick_ticker(sym)
    if not tk or not _gamma_surface_wanted(tk) or not _is_loggable_session(time.time()):
        return
    with _reprice_guard:
        _reprice_dirty.add(tk)
        if tk in _reprice_running:
            return
        _reprice_running.add(tk)
    threading.Thread(target=_reprice_worker, args=(tk,), name=f"reprice-{tk}", daemon=True).start()


def _reprice_worker(tk: str) -> None:
    """Reprice `tk` while ticks keep arriving, at most once per LEVELS_REPRICE_MIN_INTERVAL_SEC;
    the last tick of a burst is always priced. A ticker just put on screen has no kept chain
    (only a viewed ticker's is kept): its chain is fetched now, by the one producer, rather than
    when the levels loop next comes round to it."""
    last = float("-inf")
    while True:
        time.sleep(max(0.0, last + LEVELS_REPRICE_MIN_INTERVAL_SEC - time.monotonic()))
        with _reprice_guard:
            if tk not in _reprice_dirty:
                _reprice_running.discard(tk)
                return
            _reprice_dirty.discard(tk)
        last = time.monotonic()
        try:
            now = time.time()
            if _publish_levels(tk, now=now) is None:
                _terrain_refresh_one(tk, now, priority=True)
        except Exception as e:  # noqa: BLE001 -- logged; the next tick or chain fetch reprices
            log.warning("levels reprice failed for %s: %s", tk, e)


def _terrain_refresh_one(ticker: str, now: float, priority: bool = False) -> str:
    """Fetch one chain and compute terrain into the cache, as the market is at `now` (epoch
    seconds); the chain is as of the moment Schwab's answer arrived. Never raises.

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
    if not _is_loggable_session(now):
        # market closed: the newest chain capture is priced, not a download (weekend chains
        # blank open interest -- measured 2026-09-26: every $SPX contract, 18% of SPY's OI)
        _price_stored_chain_when_closed(tk, now)
        return "skip:market_closed"
    if _terrain_quarantine_blocks(tk, now):
        return "skip:quarantined"
    try:
        client = get_client()
        # The FULL chain -- every strike of every listed expiry (fetch_full_chain; operator
        # decision 2026-09-25 after the strike window was measured disagreeing with it).
        resp = fetch_full_chain(client, tk, lambda **d: _gated_safe_get_chain(
            client, tk, strike_range="ALL", priority=priority, **d)[0])
        if resp.status_code != 200:
            _code = resp.status_code
            _msg = f"chain fetch failed ({resp.reason or f'HTTP {_code}'})"
            _terrain_refresh_last_error[tk] = _msg
            # RC-148: classify so the response fits the cause. A 4xx is the vendor refusing THIS
            # SYMBOL and will refuse it identically forever; a 5xx is the venue being busy and
            # deserves a backoff, not a death sentence.
            _note_terrain_failure(tk, _msg, _classify_chain_failure(_code, None), now)
            return "error:chain_http"
        fetched_ts = time.time()   # the chain's as-of: an older streamed value never overrides it
        contracts = flatten_chain_contracts(resp.json())
        snap = _publish_levels(tk, contracts, fetched_ts, now=fetched_ts)
        _terrain_refresh_last_error.pop(tk, None)   # RC-126: success clears the sticky reason
        _note_terrain_success(tk)                   # RC-148: and the failure streak with it
        return f"ok:{snap.confidence}"
    except Exception as e:
        # RC-126: DEBUG here meant $SPX failed silently for a full session while the operator
        # stared at 'not_ready' with no reason. The failure is WARNING-visible AND kept, so
        # the endpoint can tell the operator WHY instead of an eternal shrug.
        _terrain_refresh_last_error[tk] = f"{type(e).__name__}: {e}"
        # RC-148: an exception is never a symbol rejection (those arrive as a 4xx RESPONSE), so
        # it always classifies soft — backoff, never a hard hold. A crash in our own code
        # must not be able to evict a real instrument from the board.
        _note_terrain_failure(tk, f"{type(e).__name__}: {e}", "soft", now)
        log.warning("terrain refresh %s failed: %s", tk, e, exc_info=True)
        return f"error:{type(e).__name__}"


STATUS_EVERY_SEC = 60.0
#: the daemon writes a feed-status row every 60 s; older than this, the record has stopped
FEED_RECORD_STALE_SEC = 150.0


def _feed_record_state(now: float) -> str:
    """How old the newest stream_feed_status row in stream_capture.db is at `now`: it proves the
    whole path (the daemon's loop, the bus, the writer, the database) wrote this minute."""
    from db_authority import canonical_stream_db_path
    path = canonical_stream_db_path()
    if not path.is_file():
        return "feed record: NO DATABASE"
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='stream_feed_status'").fetchone():
            return "feed record: none yet"
        newest = conn.execute("SELECT MAX(ts) FROM stream_feed_status").fetchone()[0]
    finally:
        conn.close()
    if newest is None:
        return "feed record: none yet"
    age = now - float(newest)
    return (f"feed record: written {age:.0f}s ago" if age <= FEED_RECORD_STALE_SEC
            else f"FEED RECORD STALE: last written {age / 60:.0f} min ago")


def _next_refresh_ct(now: float) -> str:
    """The next market day's refresh window after `now`, in Central time."""
    et = datetime.fromtimestamp(now, ET)
    day = et.date()
    for _ in range(15):
        if _refresh_window_et(day.isoformat()) is not None:
            win = _refresh_window_et(day.isoformat())
            if day > et.date() or et.hour * 60 + et.minute <= win[1]:
                label = "today" if day == et.date() else day.strftime("%a %m/%d")
                return f"{label} {_refresh_window_ct(day.isoformat())}"
        day += timedelta(days=1)
    return "(no market day within 15 days)"


def _status_line(now: float) -> str:
    """One line for the console window: is each part working at `now`, from its own check."""
    st = lmp.daemon_status(now)
    with _logger_lock:
        board = list(_logger_tickers)
    priced = sum(1 for tk in board if resolve_spot(tk)[0] is not None)
    with _terrain_cache_lock:
        as_of = [p.get("computed_ts_utc") for p in _terrain_cache.values() if p.get("computed_ts_utc")]
    newest = ct_label(max(as_of)) if as_of else "none"
    return " | ".join([
        "alive",
        f"session {session_label(datetime.fromtimestamp(now, ET))}",
        "daemon link: " + ("connected" if st is not None else "NOT CONNECTED"),
        "Schwab socket: " + ("open" if st and st.get("schwab_socket_open") is True else "NOT OPEN"),
        f"live prices: {priced} of {len(board)} board tickers",
        f"levels: {len(as_of)} tickers, newest as of {newest}",
        _feed_record_state(now),
        (("chain refresh: last sweep of the board took "
          f"{_terrain_last_cycle_sec:.0f} s" if _terrain_last_cycle_sec
          else "chain refresh: first sweep running") if _is_loggable_session(now)
         else "chain refresh next " + _next_refresh_ct(now)),
    ])


def _terrain_loop() -> None:
    # the board's streams first: the daemon drops a console's streams when it disconnects and
    # streams only what the console declares, so a restarted console re-declares them before the
    # start-up work. Then the price levels and the stored option levels, on this thread: the
    # console serves the page meanwhile, and each ticker's levels appear as they are priced
    from app.options.order_flow.streaming import declare_equity_symbols
    with _logger_lock:
        board_now = list(_logger_tickers)
    declare_equity_symbols("board", board_now)
    _publish_missing_price_levels(board_now)
    loaded = _load_stored_levels()
    with _logger_lock:
        board = len(_logger_tickers)
    now = time.time()
    log.info("Ready: levels for %d of %d board tickers loaded (session: %s). %s", loaded, board,
             session_label(datetime.fromtimestamp(now, ET)),
             "Levels refresh every 5 s." if _is_loggable_session(now) else
             "Levels refresh (a full-chain sweep of the board, 1-2 min each) "
             + _next_refresh_ct(now) + ".")
    _terrain_cycle_n = 0        # RC-161: drives the morning rotation; monotonic per loop
    next_status = time.monotonic() + STATUS_EVERY_SEC   # the ready line covers the start
    while _terrain_loop_running:
        cycle_start = time.monotonic()
        if cycle_start >= next_status:
            try:
                log.info(_status_line(time.time()))
            except Exception as e:  # noqa: BLE001 -- the status line says it failed, never silence
                log.warning("status: could not be read (%s: %s)", type(e).__name__, e)
            next_status = cycle_start + STATUS_EVERY_SEC
        with _logger_lock:
            tickers = list(_logger_tickers)
        # Independent-review finding (2026-09-12, state-authority review), REPRODUCED: a
        # ticker merely PREVIEWED (never enrolled onto _logger_tickers -- see
        # TICKER-PREVIEW-NO-ENROLL below) got exactly ONE on-demand terrain compute (the
        # /api/terrain cache-miss priority path) and then NOTHING -- this loop only ever
        # iterated the enrolled board, so its cache entry sat frozen forever while
        # /api/options/gamma-surface kept serving it "live: True" (meaning "sourced from
        # the live pathway", not "currently fresh") alongside a growing stale age with no
        # honest "never enrolled" reason surfaced. Any ticker with LIVE view demand
        # (_gamma_surface_wanted -- the SAME signal /api/options/gamma-surface already
        # records on every request) is folded into this cycle so viewing ANY supported
        # ticker keeps it refreshing for as long as it is actually being viewed, not only
        # the pre-enrolled board.
        _viewed_now = _viewed_tickers()
        _previewed = [tk for tk in _viewed_now if tk not in tickers]
        _publish_missing_price_levels(tickers + _previewed)     # a new session date, a new ticker
        # Every board ticker's spot is the streamed LAST_PRICE only, so the daemon must
        # stream each one (its fixed roster is just --symbols).
        try:
            from app.options.order_flow.streaming import declare_equity_symbols
            declare_equity_symbols("board", tickers + _previewed)
        except Exception as e:  # noqa: BLE001 -- the cycle itself must still run
            log.warning("equity stream declaration failed: %s", e)
        # RC-146: a skip reason is only true for the cycle that recorded it. Cleared at the TOP
        # of every cycle so a pause that has ended cannot keep telling the operator to wait —
        # the branch below re-records it while, and only while, it still applies.
        _clear_terrain_skips()
        # Operator-reproduced defect (2026-09-14, "the collection schedule must not block live
        # viewing"): this whole cycle used to be gated on _is_loggable_session() -- the
        # ARCHIVAL LOGGER's own RTH-only writing policy (RTH_ONLY, "only log during RTH + 30min
        # pre/post buffer") -- so a ticker someone had open and was actively looking at got NO
        # live refresh attempt at all outside that window, not even a try. "should the durable
        # log be written" and "should an operator who is looking at this ticker right now see
        # whatever is currently fetchable" are different questions; this loop answered both with
        # the same switch. The enrolled board's full sweep stays RTH-gated (unchanged -- nobody
        # is necessarily watching all 58 of them, and the morning-contention throttle below is
        # itself an RTH-only concept), but active viewing demand now always gets a live attempt,
        # whether the archival logger is in its window or not.
        now = time.time()                       # this cycle's instant
        if _is_loggable_session(now):
            # During the morning wide-chain window (09:30-10:00 ET) SPY/QQQ/IWM already
            # take 100-strike gated fetches on the money path. Do not pile a full-universe
            # terrain sweep on top of that — refresh sentinels only until the window ends.
            # No try/except: the imports are module-level, so this path cannot fail at
            # runtime — a missing module stops the server at boot instead.
            _mins = et_minute_total_from_ts_utc(now)
            _terrain_cycle_n += 1
            # every viewed ticker (on the board or not) refreshes every cycle; the rest of the
            # board rotates inside the contention window
            tickers, _dropped = terrain_cycle_tickers(list(tickers) + _previewed, _mins,
                                                      _terrain_cycle_n, viewed=_viewed_now)
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
                    f"the rotation cadence ({CONTENTION_ROTATION_SEC:.0f}s) instead of "
                    f"being held out, so this ticker still accrues inside the window",
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=TERRAIN_WORKERS) as pool:
                list(pool.map(lambda t: _terrain_refresh_one(t, now), tickers))
        else:
            tickers = []
        elapsed = time.monotonic() - cycle_start
        # RC-165: publish the DELIVERED cycle so freshness is judged against reality, not the
        # sleep floor. This number was already computed and only logged; readers had no access
        # to it, so terrain_staleness was left comparing against a cadence the loop never meets.
        globals()["_terrain_last_cycle_sec"] = float(elapsed)
        if tickers:   # a cycle with nothing to do prints nothing
            log.info("Terrain cycle: %d tickers in %.1fs", len(tickers), elapsed)
        sleep_end = time.monotonic() + max(0.0, TERRAIN_REFRESH_SEC - elapsed)
        while _terrain_loop_running and time.monotonic() < sleep_end:
            time.sleep(0.5)
    log.info("Terrain loop stopped")


def _load_stored_levels() -> int:
    """At startup, each board ticker's newest full chain capture is priced once (DATA_FLOW
    decision 7), so a restart, a weekend or the close shows the last reading with its time.
    Returns how many tickers were loaded."""
    with _logger_lock:
        board = list(_logger_tickers)
    n = 0
    for tk in board:
        caps = last_capture_per_day(get_db().db_path, tk, 2)
        if caps and _publish_levels(tk, captures=caps, now=time.time()) is not None:
            n += 1
    return n


NO_CAPTURE_REASON = "market closed; no chain capture of this ticker yet"


def _price_stored_chain_when_closed(tk: str, now: float) -> None:
    """A viewed ticker keeps its chain and its heatmap. While the market is closed nothing
    downloads a chain, so the first view prices the ticker's newest chain capture with the chain
    kept -- the same capture the startup load priced (DATA_FLOW decision 7), not a second
    source. The startup load keeps no chains: nobody is viewing anything then. The same rule for
    every ticker, on the board or not: a ticker with no capture has that as its levels' reason."""
    if _is_loggable_session(now) or (terrain_cache_get(tk, now) or {}).get("_chain"):
        return
    caps = last_capture_per_day(get_db().db_path, tk, 2)
    if caps:
        _publish_levels(tk, captures=caps, now=now)
    elif terrain_cache_get(tk, now) is None:
        _terrain_refresh_last_error[tk] = NO_CAPTURE_REASON


def start_terrain_loop() -> None:
    """Start the terrain collection thread.

    Refuses to start under pytest: a background thread inside the test process would fetch
    chains and hold the shared 2-slot chain gate for the rest of the session. Tests that need
    the loop call _terrain_loop / _terrain_refresh_one directly.
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


#: ATR is derived from ~100 sessions of 1-minute bars, so it moves slowly. Recomputing it
#: per radar poll would re-read the bar table for every ticker every 20 seconds.
_atr_cache: dict[str, tuple[float, "AtrPair"]] = {}
_atr_lock = threading.Lock()
ATR_TTL_SEC: float = 900.0


def _atr_pair(ticker: str) -> "AtrPair":
    """The ticker's (daily, 15-minute) ATR from price_bars_1m's completed candles, recomputed
    at most every ATR_TTL_SEC. Too few bars reads as None, never a vendor stand-in."""
    tk = ticker_storage_key(ticker)
    with _atr_lock:
        hit = _atr_cache.get(tk)
    if hit is not None and time.time() - hit[0] < ATR_TTL_SEC:
        return hit[1]
    pair = compute_atr_pair(str(get_db().db_path), tk, now_et())
    with _atr_lock:
        _atr_cache[tk] = (time.time(), pair)
    return pair


def _atr_fields(tk: str) -> dict:
    """atr_daily / atr_15m for every publication of the ticker's levels, whatever the chain's
    source (a live download or a stored capture)."""
    pair = _atr_pair(tk)
    return {"atr_daily": round(pair.daily, 3) if pair.daily is not None else None,
            "atr_15m": round(pair.m15, 3) if pair.m15 is not None else None,
            "atr_daily_reason": pair.daily_reason, "atr_15m_reason": pair.m15_reason}


#: WHICH producer computed a set of levels. The radar deliberately merges two of them, and an
#: unlabelled merge is how systematically-different numbers get ranked as peers (RC-82).
LEVELS_SOURCE_WIDE_CHAIN = "wide_chain_loop"      # _terrain_refresh_one, the single producer


# ── CR-03 screen 1 — per-strike gamma/volume bars for the histogram panel ────
# Feeds the /chart sidebar: today's per-strike dealer gamma + traded volume, plus
# the previous market day's last chain capture (the day-over-day migration ghosts), each in
# three expiry scopes (all / near<=7DTE / far). Read-only, no Schwab call. Bar heights use the
# same exposure math as terrain.
def _prior_strikes(captures: list, chain_ts: float) -> "tuple[dict | None, str | None]":
    """The previous market day's close before the day of the chain the ticker's rows came from,
    as per-strike rows ({all, near, far}), with its source. On a closed market today's rows ARE
    the newest capture; the wall clock's date picked that same capture and compared it with
    itself (every change 0, `compared` true -- 2026-09-27). Run by _publish_levels when the
    ticker's newest capture or its chain's day changes, on the same two newest market days'
    captures the forces read: the chain's day is today or the newest capture's, so the day
    before it is one of those two."""
    from math_exposure_core import compute_exposures_by_strike as _cebs

    def _per_strike(contracts: list, spot: float, now: datetime) -> dict:
        def _scope(cts: list) -> list:
            if not cts:
                return []
            exposures, _diag = _cebs(cts, spot=spot, now=now)   # valued at the capture's own time
            # ONE producer (2026-09-24): this was a second copy of terrain_engine._per_strike_rows
            # carrying the same raw-gamma fallback (audit T-01) -- the live panel and this ghost
            # must be one computation or they draw a positioning shift that did not happen.
            from terrain_engine import _per_strike_rows
            return _per_strike_rows(exposures)

        # Cursor-audit F8: unknown DTE must belong to NEITHER near nor far, not silently to far.
        # This endpoint carried its own near/far splitter with the old 999.0 sentinel — a duplicate
        # of the RC-290-fixed canonical _dte_of, which drops an unreadable DTE from BOTH sides. With
        # 999.0 a parse-failed 0-DTE was rendered in the prior-day MONTHLY+ (far) chip and omitted
        # from the ≤7DTE (near) chip. Use the ONE canonical splitter so the two can't diverge again.
        from terrain_engine import _dte_of
        near = [c for c in contracts if (d := _dte_of(c)) is not None and d <= 7]
        far = [c for c in contracts if (d := _dte_of(c)) is not None and d > 7]
        return {"all": _scope(contracts), "near": _scope(near), "far": _scope(far)}

    chain_day = et_date_str_from_ts_utc(float(chain_ts))
    prior = next((c for c in captures if c["et_date"] < chain_day), None)
    if prior is not None and prior["spot"] is not None:
        return (_per_strike(prior["contracts"], float(prior["spot"]), datetime.fromtimestamp(prior["ts_utc"], ET)),
                f"chain_capture:{prior['et_date']}")
    return None, None


@app.get("/api/terrain/strikes")
def get_terrain_strikes(ticker: str = Query(...)):
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority

    today_src, prior_src = None, None
    today, prior = None, None
    measures: dict = {"dex": [], "oi": []}
    spot_used = None
    today_age_sec = None
    # RC-146: bound BEFORE the try. `_snap` was assigned only inside the try body yet read
    # unconditionally in the response dict below — a raising terrain_cache_get took the
    # logged-and-swallowed path and then killed the endpoint with NameError on the way out,
    # turning a degraded panel into a 500. Absence must degrade, never explode.
    _snap: dict = {}
    _ps: dict = {}
    # RC-68 SINGLE SOURCE FOR TODAY'S PER-STRIKE DATA: the LIVE terrain snapshot.
    # This panel used to render from option_chain_morning_full — MEASURED 2026-07-27 11:31 ET:
    # a 09:47 capture served at 11:31 understated session volume by 281 percent (1,095,874 shown
    # vs 4,176,672 live), ~500K missing on strike 740 alone, while the walls beside it moved on
    # the 60s loop. Two clocks, one story. The terrain loop already computes this exact map from
    # a live wide chain every cycle (terrain_engine._per_strike_map) — it was simply discarded.
    # Reading it here costs ZERO additional vendor calls. The archive is demoted to the
    # prior-day ghost, which is the one thing it is genuinely correct for.
    now = time.time()
    try:
        _snap = terrain_cache_get(tk, now) or {}
        _ps = _snap.get("_per_strike") or {}
        # the terrain loop hands over FINISHED rows ({all,near,far} of
        # [strike, net_gex_1pct$, volume]); they are served as-is
        if isinstance(_ps, dict):
            measures = {m: (_ps.get(m) or []) for m in ("dex", "oi")}
        if isinstance(_ps, dict) and _ps.get("all"):
            today = {k: (_ps.get(k) or []) for k in ("all", "near", "far")}
            spot_used = _snap.get("spot")
            _cts_utc = _snap.get("computed_ts_utc")
            today_age_sec = round(now - float(_cts_utc), 1) if _cts_utc else None
            today_src = "terrain_live_cache"
    except Exception as e:
        log.debug("terrain strikes live read failed %s: %s", tk, e)
    prior, prior_src = _snap.get("_prior_strikes") or (None, None)

    peak = (_ps.get("peak") or {}) if isinstance(_ps, dict) else {}
    live_spot, live_src, _live_ts = resolve_spot(tk)   # the one spot on every screen
    return JSONResponse({
        "ticker": tk, "spot": live_spot,
        "spot_source": live_src,
        "priced_at_spot": spot_used,
        "today": today or {"all": [], "near": [], "far": []},
        # the Chart view's DEX and OI profiles: each measure's rows (terrain_engine
        # _per_strike_measure_rows), its strike nearest the live price (the window's centre) and
        # its largest-magnitude strike, as published (per_strike_view `peak`)
        "measures": {m: {"rows": rows,
                         "spot_strike": nearest_strike([r[0] for r in rows], live_spot),
                         "max_abs_strike": peak.get(m)}
                     for m, rows in measures.items()},
        # net GEX below and above the publication's price, as published (per_strike_view)
        "today_side_sums": _ps.get("side_sums") if today else None,
        "spot_strike": nearest_strike([r[0] for r in (today or {}).get("all") or []], live_spot),
        # the strike with the largest net GEX magnitude (the chart labels it): net_gex_peak
        "max_abs_strike": peak.get("all") if today else None,
        "migration": {sc: positioning_migration((today or {}).get(sc), (prior or {}).get(sc),
                                                _snap.get("call_wall"), _snap.get("put_wall"))
                      for sc in ("all", "near", "far")},
        "today_source": today_src,
        # RC-68: every consumer must be able to render an AGE on the panel's face. A number with
        # no age is how a 2.1-hour-old volume histogram sat under the label "TODAY'S OPTION VOLUME".
        "today_age_sec": today_age_sec,
        # RC-91: PROVENANCE IS NOT FRESHNESS. single_faucet_provenance passes here — one declared
        # source, no fallback — while the panel served levels 90 MINUTES old under a
        # `terrain_live_cache` label, because the terrain loop stops at the background-logging
        # window (16:30 ET) and nothing said so. Naming the right source proves only that the
        # right tap was opened, never that anything is still coming out of it.
        **terrain_staleness(_snap.get("computed_ts_utc") if isinstance(_snap, dict) else None, tk, now),
        "prior": prior or {"all": [], "near": [], "far": []},
        "prior_source": prior_src,
    })


@app.get("/api/bars1m")
def get_bars1m(ticker: str = Query(...),
               limit: int = Query(default=780, ge=1, le=12000),
               tf: str = Query(default="1", pattern=r"^(1|3|5|15|30|60|D)$")):
    """A chart's bar history, as it opens: completed Schwab 1m bars, newest-last, [{t,o,h,l,c,v}]
    epoch-seconds bar starts, rolled up to `tf` (live_price_rows.aggregate_bars). The bars that
    complete after it come on the daemon's push (live_ui), rolled by the same function.
    `limit` counts 1-minute bars: when the read reaches it, the oldest rolled bar may have lost
    its first minutes to the cut and is not served. `last_bar`: the newest completed minute and
    its label."""
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    bars = [_bar_dict(c) for c in _bars_1m(tk, int(limit))]
    rolled = _lpr.aggregate_bars(bars, tf)
    if tf != "1" and len(bars) == int(limit):
        rolled = rolled[1:]
    out = [_lpr.with_change(b) for b in rolled]
    return JSONResponse({"ticker": tk, "bars": out, "tf": tf, "n": len(out),
                         "last_bar": _lpr.last_bar(bars[-1]["t"] if bars else None)})


def aggregate_vwap(rows: list, tf: str, bar_ts: list) -> list:
    """VWAP rows [t, vwap, +1s, -1s, +2s, -2s] rolled up to the chart timeframe as
    live_price_rows.aggregate_bars rolls the bars: each chart bar takes the value as of its last
    minute, stamped with that bar's own `t` -- the first of `bar_ts` (the session's 1-minute bar
    times, VWAP minute or not) in the bar's bucket."""
    if tf == "1":
        return [list(r) for r in rows]
    first: dict = {}
    for t in bar_ts:
        first.setdefault(_lpr.tf_bucket_key(float(t), tf), t)
    out: dict = {}
    for r in rows:
        k = _lpr.tf_bucket_key(float(r[0]), tf)
        out[k] = [first[k]] + list(r[1:])
    return list(out.values())


@app.get("/api/options/vanna-by-strike")
def get_vanna_by_strike(ticker: str = Query(...)):
    """Per-strike dealer VANNA exposure from the published levels (net_vanna = call_vanna -
    put_vanna, aggregated across every expiry; no per-expiry surface yet)."""
    tk = ticker_storage_key(_required_ticker(ticker))
    payload = terrain_cache_get(tk, time.time()) or {}
    if "_vanna_rows" not in payload:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no levels published for this ticker yet"})
    spot = resolve_spot(tk)[0]
    return JSONResponse({"ticker": tk, "available": True, "spot": spot,
                         "priced_at_spot": payload.get("spot"),
                         "rows": payload["_vanna_rows"], "levels_as_of": payload.get("levels_as_of"),
                         "spot_strike": nearest_strike([r[0] for r in payload["_vanna_rows"]], spot),
                         "method": "the published levels' exposure book -> call_vanna - put_vanna"})


@app.get("/api/options/charm-by-strike")
def get_charm_by_strike(ticker: str = Query(...)):
    """Per-strike dealer CHARM exposure from the published levels' charm map (the charm walls'
    own): net_charm = call_charm - put_charm per strike, delta-shares/day."""
    tk = ticker_storage_key(_required_ticker(ticker))
    payload = terrain_cache_get(tk, time.time()) or {}
    if "_charm_rows" not in payload:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no levels published for this ticker yet"})
    rows = payload["_charm_rows"]
    spot = resolve_spot(tk)[0]
    return JSONResponse({"ticker": tk, "available": bool(rows), "spot": spot,
                         "priced_at_spot": payload.get("spot"),
                         "rows": rows, "levels_as_of": payload.get("levels_as_of"),
                         "spot_strike": nearest_strike([r[0] for r in rows], spot),
                         "reason": None if rows else "charm_by_strike produced no usable strikes for this chain",
                         "method": "the published levels' charm map -> call_charm - put_charm"})


@app.get("/api/options/tape")
def get_options_tape(ticker: str = Query(...),
                     contract: Optional[str] = Query(default=None),
                     limit: int = Query(default=100)):
    """The Options Flow tape: each change of a contract's last trade as Schwab streamed it
    (app.options.order_flow.history.tape_rows_for_symbol, from the stored LEVELONE_OPTIONS
    messages), at the trade's own time. Not every trade, and no side.

    `contract`, when given, scopes to exactly that vendor symbol. Otherwise scopes to every
    CURRENTLY DESIRED contract for `ticker` (the primary + additional option contracts the
    operator has actually selected — the same identity `_desired_stream_greeks_for_ticker`
    already resolves for the gamma-surface overlay), merged newest-first and capped at
    `limit` across the whole merge, not per-contract."""
    from app.options.order_flow.streaming import (
        get_active_option_contract, get_active_option_contracts)
    from app.options.order_flow.history import tape_rows_for_symbol

    tk = ticker_storage_key(_required_ticker(ticker))
    try:
        bounded_limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = 100

    if contract:
        symbols = [contract]
    else:
        candidates = list(get_active_option_contracts())
        primary = get_active_option_contract()
        if primary:
            candidates.append(primary)
        seen: set[str] = set()
        symbols = []
        for sym in candidates:
            if sym and sym not in seen and _contract_is_for(sym, tk):
                seen.add(sym)
                symbols.append(sym)

    if not symbols:
        return JSONResponse({"ticker": tk, "available": False, "rows": [],
                             "reason": "no active/additional option contract selected for this ticker"})

    rows: list[dict] = []
    for sym in symbols:
        rows.extend(tape_rows_for_symbol(sym, since_ts=0.0, limit=bounded_limit))
    rows.sort(key=lambda r: r["ts_recv"], reverse=True)
    rows = rows[:bounded_limit]
    return JSONResponse({
        "ticker": tk, "available": bool(rows), "symbols": symbols, "rows": rows,
        "reason": None if rows else "no trade streamed yet for the selected contract(s)",
        "method": ("stored LEVELONE_OPTIONS messages, each merged onto the contract's fields; a "
                   "row is a change of Schwab's last trade (time, price or size), which is not "
                   "every trade; newest first across the selected contracts"),
    })


@app.get("/api/order-flow/book-heatmap")
def get_order_flow_book_heatmap(ticker: str = Query(...),
                                venue: str = Query(..., pattern=r"^(NYSE_BOOK|NASDAQ_BOOK)$"),
                                minutes: float = Query(default=60.0)):
    """Historical book-depth heatmap for one of the ticker's Schwab books, `venue` (operator
    field-inventory audit, 2026-09-13: "we don't have an order flow heatmap"). SERIALIZER, not a
    second producer: delegates entirely to app.options.order_flow.history.book_heatmap_for_ticker,
    which bins the SAME persisted stream_book_raw rows the live /api/order-flow/microstructure
    ladder already reads into a time x price grid. Genuinely historical (a real time axis), which
    the live ladder's one-snapshot view cannot show. The window always ends at the latest row
    actually captured for this ticker, never wall-clock now — see that function's own docstring
    for why. `minutes` is clamped to [5, 240] to bound one request's cost."""
    from app.options.order_flow.history import book_heatmap_for_ticker

    tk = ticker_storage_key(_required_ticker(ticker))
    try:
        bounded_minutes = max(5.0, min(240.0, float(minutes)))
    except (TypeError, ValueError):
        bounded_minutes = 60.0
    payload = book_heatmap_for_ticker(tk, venue, minutes=bounded_minutes)
    return JSONResponse(payload)


#: RC-192/RC-199 FORCES (RE-LANDED 2026-08-02 after a worktree reset destroyed the
#: uncommitted originals — RC-210): ΔOI/DEX from the two newest banked wide chains; the
#: strip's GEX/OV rows come from the live strikes payload client-side; ΔOI and DEX need the
#: two newest wide captures, which only the server can read.


@app.get("/api/forces")
def get_forces(ticker: str = Query(...)):
    """The ticker's forces, as the levels producer computed them from its chain captures."""
    tk = ticker_storage_key(_required_ticker(ticker))
    forces = (terrain_cache_get(tk, time.time()) or {}).get("_forces")
    return JSONResponse(forces if forces is not None else {
        "ticker": tk, "available": False, "reason": "no levels published for this ticker yet"})


def _forces_from_captures(tk: str, captures: list) -> dict:
    """Forces rows from banked chains (RC-192/RC-199): per-strike OI delta FIRST, then
    bucketed by the NEWER capture's spot — bucketing each day by its own spot lets the moving
    boundary masquerade as OI change (measured inversion, OPEN_ITEMS DIR-01 method note).
    DEX is the newer capture's net_dex_dollars side sums. CHARM side sums (RC-199): operator
    2026-08-02 revoked the DIR-01(i) vote-lock — serve dealer-signed net_charm below/above
    spot from the newer banked chain via compute_charm_by_strike (same book as terrain walls).
    Run by _publish_levels when the ticker's newest capture changes, on `captures`: the two
    newest market days' captures (last_capture_per_day, newest first), read once for it.
    """
    from math_exposure_core import compute_exposures_by_strike as _cebs
    from math_levels import compute_charm_by_strike as _ccs

    payload: dict = {"ticker": tk, "available": False,
                     "reason": "fewer than 2 market days of chain captures for this ticker"}
    try:
        rows = [(c["et_date"], c["spot"], c["contracts"], c["ts_utc"])
                for c in captures if c["spot"] is not None]
        if len(rows) >= 2:
            (d1, s1, c1, t1), (d0, s0, c0, t0) = rows[0], rows[1]
            # each capture valued at its own time, not today's clock
            per1 = _cebs(c1, spot=float(s1), now=datetime.fromtimestamp(t1, ET))[0]
            per0 = _cebs(c0, spot=float(s0), now=datetime.fromtimestamp(t0, ET))[0]

            from math_exposure_core import bucket_metric as _bm, strike_total_oi as _sto

            # a strike's OI change exists only when its OI is known on both days
            oi1 = {k: t for k, v in per1.items() if (t := _sto(v)) is not None}
            oi0 = {k: t for k, v in per0.items() if (t := _sto(v)) is not None}
            doi = {k: oi1[k] - oi0[k] for k in oi1 if k in oi0}
            dex1 = {k: d for k, v in per1.items() if (d := _bm(v, "net_dex_dollars")) is not None}
            spot1 = float(s1)
            # RC-199: CHARM below/above from the NEWER banked wide chain (full book).
            # Dealer-signed net_charm = call_charm - put_charm per strike (RC-179).
            charm_below = charm_above = None
            charm_err = None
            try:
                # priced at the capture's own time, not today's clock
                per_ch = _ccs(c1, spot1, now=datetime.fromtimestamp(t1, ET)) if c1 else {}
                if not per_ch:
                    charm_err = "charm_by_strike empty on newer banked chain"
                else:
                    # RC-276: a strike with no net_charm is not a strike with zero charm.
                    # Summed as 0.0 it silently tilted the below/above pair the console
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
                "doi_below": round(sum(d for k, d in doi.items() if k < spot1)),
                "doi_above": round(sum(d for k, d in doi.items() if k > spot1)),
                "dex_below_dollars": round(sum(d for k, d in dex1.items() if k < spot1)),
                "dex_above_dollars": round(sum(d for k, d in dex1.items() if k > spot1)),
                "strikes_diffed": len(doi),
                "charm_below": charm_below,
                "charm_above": charm_above,
                "charm_error": charm_err,
                "newer_et_date": d1, "older_et_date": d0, "bucket_spot": spot1,
                # what the rows are, for the screen: past observations from two stored captures
                "basis": (f"{d1} chain capture against {d0}, split at that capture's price {spot1:.2f}; "
                          f"open interest compared on {len(doi)} strikes"),
            }
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"forces read failed: {e}"}
    return payload


# RC-UI-1: strike × expiry GEX surface for the rebuilt Options→Gamma heatmap. A PROJECTION over the
# one canonical exposure authority, not a second producer: it partitions a wide chain by native
# expirationDate (via the existing _filter_contracts_by_selected_expiry slice) and invokes
# math_exposure_core.compute_exposures_by_strike per slice, shaping net_gex_1pct cells into a grid.
# No gamma/GEX/multiplier/OI/spot/sign/missingness math lives here.
# SOURCE: the live terrain projection only — _terrain_refresh_one projects it from the live wide
# chain + live spot it already fetches each cycle (in-memory, zero extra vendor calls),
# demand-gated to viewed tickers. No banked-morning fallback (operator rule 2026-09-23).

#: NO LAST-VALID BACKFILL (operator rule 2026-09-23: no fallbacks). A heatmap cell with no
#: valid data THIS cycle stays empty ('—'); it used to be refilled from the last valid value
#: (computed at an older spot, possibly hours old) while gamma_available read True and the
#: unavailable reason was cleared. The surface's own cells_with_data / gamma_available /
#: gamma_unavailable_reason (project_gamma_surface) describe the current cycle only.


def _gamma_surface_cell_fields(bucket: "dict | None", syms: "dict | None"):
    """Shape ONE (strike, expiry) cell's gex/dex/vanna/oi/volume/contracts fields from its
    exposure bucket. Returns (gex, dex, vanna, oi, volume, contracts, has_gex_data, has_oi) --
    see project_gamma_surface's inline comments for why each gate exists."""
    from numeric_contract import float_finite_or_none

    def _bf(v):
        fv = float_finite_or_none(v)
        return round(fv) if fv is not None else None

    syms = syms or {}
    _has_oi = bool(bucket is not None and bucket.get("has_oi"))
    _has_gex_data = bool(_has_oi and bucket.get("has_valid_gamma"))
    gex = _bf(bucket.get("net_gex_1pct")) if _has_gex_data else None
    dex = _bf(bucket_metric(bucket, "net_dex_dollars")) if _has_oi else None
    _vn = bucket_metric(bucket, "net_vanna") if _has_oi else None   # the book's own net vanna
    vanna = round(_vn, 2) if _vn is not None else None
    def _legs(legs):
        # the one readers (strike_oi_legs / strike_volume_legs): Schwab's values as sent, 0 a real
        # zero; unknown only when a contract at the strike did not report the field
        if legs is None:
            return {"call": None, "put": None, "total": None}
        return {"call": _bf(legs[0]), "put": _bf(legs[1]), "total": _bf(legs[0] + legs[1])}

    from math_exposure_core import strike_oi_legs, strike_volume_legs
    oi = _legs(strike_oi_legs(bucket) if bucket is not None else None)
    volume = _legs(strike_volume_legs(bucket) if bucket is not None else None)
    contracts = {"call": syms.get("call"), "put": syms.get("put")}
    return gex, dex, vanna, oi, volume, contracts, _has_gex_data, _has_oi


def project_gamma_surface(chain: list, books: dict) -> dict:
    """The strike × expiry grid the gamma heatmap draws, shaped from `books` -- the
    exposure_books compute_terrain priced `chain` into, so every cell is the number the levels
    and per-strike rows were computed from. No exposure math here. A contract with a missing
    or malformed expiry is counted, never given a column."""
    from math_exposure_core import merge_exposure_books
    from numeric_contract import schwab_number

    chain = chain if isinstance(chain, list) else []
    by_expiry: "dict[str, list]" = {}
    for (exp, _dte), book in (books or {}).items():
        if len(exp) == 10:
            by_expiry.setdefault(exp, []).append(book)
    per_expiry = {e: (bs[0][0] if len(bs) == 1 else merge_exposure_books(bs)[0])
                  for e, bs in by_expiry.items()}
    exp_dte: "dict[str, int | None]" = {}
    # when each column's last contract settles (an expiry date can hold AM- and PM-settled
    # contracts): settlement times by (expiry, settlementType), then the latest per column
    settles: "dict[tuple, datetime | None]" = {}
    # the vendor OSI symbol behind each (strike, expiry) leg, so the browser can ask the stream
    # for exactly the contracts it is showing
    symbols_by_expiry: "dict[str, dict[float, dict[str, str]]]" = {}
    contracts_used = 0
    for ct in chain:
        e = str((ct or {}).get("expirationDate") or "")[:10]
        if e not in per_expiry:
            continue
        contracts_used += 1
        if (e, ct.get("settlementType")) not in settles:
            settles[(e, ct.get("settlementType"))] = settlement_et(e, ct.get("settlementType"))
        if exp_dte.get(e) is None:   # native DTE for the column header, never inferred
            d = schwab_number(ct.get("daysToExpiration"))
            exp_dte[e] = int(d) if d is not None else None
        side = (ct.get("putCall") or "").upper()
        sym = ct.get("symbol")
        k = schwab_number(ct.get("strikePrice"))
        if sym and side in ("CALL", "PUT") and k is not None:
            symbols_by_expiry.setdefault(e, {}).setdefault(k, {})[side.lower()] = str(sym)
    total_contracts = len(chain)
    excluded_malformed = total_contracts - contracts_used
    strike_set = {float(k) for ex in per_expiry.values() for k in ex}
    expiries = sorted(per_expiry)
    strikes = sorted(strike_set)
    last_settlement = {e: max((s.timestamp() for (x, _t), s in settles.items() if x == e and s is not None),
                              default=None) for e in expiries}
    expirations = [{"expiry": e, "dte": exp_dte.get(e), "settles_ts_utc": last_settlement[e]} for e in expiries]
    # Each cell carries every measure its bucket already holds -- GEX, DEX, vanna
    # (call - put, the dealer convention of compute_net_vanna), OI and volume -- so one grid
    # serves every heatmap measure. A bucket with no usable OI or greeks reads None, never its
    # initialiser zero (_gamma_surface_cell_fields gates it).
    cells = []
    cells_with_data = 0
    cells_total = 0
    cells_with_oi_but_invalid_greeks = 0
    for k in strikes:
        row, dex_row, vanna_row, oi_row, vol_row, contracts_row = [], [], [], [], [], []
        for col in expirations:
            cells_total += 1
            bucket = per_expiry.get(col["expiry"], {}).get(k)
            syms = symbols_by_expiry.get(col["expiry"], {}).get(k)
            gex, dex, vanna, oi, volume, contracts, has_gex, has_oi = \
                _gamma_surface_cell_fields(bucket, syms)
            if has_gex:
                cells_with_data += 1
            elif has_oi:
                cells_with_oi_but_invalid_greeks += 1
            row.append(gex)
            dex_row.append(dex)
            vanna_row.append(vanna)
            oi_row.append(oi)
            vol_row.append(volume)
            contracts_row.append(contracts)
        cells.append({
            "strike": k, "gex": row, "dex": dex_row, "vanna": vanna_row,
            "oi": oi_row, "volume": vol_row, "contracts": contracts_row,
        })

    # Operator directive (2026-09-14, live SPX reproduction): a grid where every single cell
    # lacks usable OI is not merely "a lot of quiet cells" -- it means this ticker's exposure
    # data is unavailable end to end, and that must be a surface-level fact the caller can
    # check in one field, not something it has to infer by scanning every cell for None.
    # contracts_used > 0 alone is not enough: a wide chain can have thousands of USED
    # contracts (real strike/side/multiplier, real greeks) while still having zero cells with
    # usable OI (exactly the live SPX case this was written from) -- gamma_available is
    # gated on cells_with_data specifically, the same signal each cell's own _has_data used.
    gamma_available = cells_with_data > 0
    _reason = _gamma_surface_unavailable_reason(gamma_available, cells_with_oi_but_invalid_greeks,
                                                cells_total)
    return {
        "expirations": expirations, "strikes": strikes, "cells": cells,
        "contracts_total": total_contracts, "contracts_used": contracts_used,
        "contracts_excluded_malformed_expiry": excluded_malformed,
        "gamma_available": gamma_available,
        "gamma_unavailable_reason": _reason,
        "cells_total": cells_total,
        "cells_with_oi_but_invalid_greeks": cells_with_oi_but_invalid_greeks,
    }


def _gamma_surface_unavailable_reason(gamma_available: bool, cells_with_oi_but_invalid_greeks: int,
                                      cells_total: int) -> "str | None":
    """The ONE message for why a surface has no usable gamma this cycle.
    Operator directive (2026-09-15, canonical input-validity rules): distinguishes a real
    OI outage (SPX, 2026-09-14: the vendor reports zero OI) from an invalid-greeks-only
    outage (SPY/QQQ 0DTE ITM puts, 2026-09-15: OI is real, Schwab's own greeks for it are
    internally self-contradictory) — an operator reading this could not tell "there is
    nothing here" from "there is real interest but Schwab's greeks for it are unusable
    right now" before this split. Both counts are diagnostic-only, never load-bearing for
    any gate (gamma_available/cells_with_data are the actual authorities)."""
    if gamma_available:
        return None
    if cells_with_oi_but_invalid_greeks > 0:
        return (
            "real open interest exists but Schwab's own reported greeks for it are invalid "
            "this cycle ({} of {} strike×expiry cells have OI with unusable greeks)"
        ).format(cells_with_oi_but_invalid_greeks, cells_total)
    return "no usable open interest in this chain (0 of {} strike×expiry cells)".format(cells_total)


def _stamp_surface_session(surface: dict, *, reference_date: Optional[str]) -> dict:
    """Session identity for a projected surface, stamped by the ONE ET clock (server side — a
    browser never decides what day it is): today's ET session date, whether the surface is a
    PRIOR-session reference (a banked capture from an earlier trading day viewed today), and which
    expiration columns have expired: every contract of the column has reached its settlement
    (time_et.settlement_et, the rule that takes a contract out of the book), or its settlement
    is not known. Presentation reads these flags to label an expired column and a prior-session
    reference for what they are; it never infers them. No cell value is touched."""
    now = now_et()
    today = now.strftime("%Y-%m-%d")      # time_et: the ONE ET clock / session-calendar authority
    out = dict(surface)
    out["expirations"] = [
        dict(e, expired=e["settles_ts_utc"] is None or now.timestamp() >= e["settles_ts_utc"])
        for e in (surface.get("expirations") or [])
    ]
    out["session_date_et"] = today
    out["prior_session"] = bool(reference_date and str(reference_date) < today)
    live_cols = [e for e in out["expirations"] if not e["expired"] and e.get("dte") is not None]
    # the front column: the nearest expiry that has not expired, by Schwab's daysToExpiration
    out["front_expiry"] = min(live_cols, key=lambda e: e["dte"])["expiry"] if live_cols else None
    return out


@app.get("/api/options/gamma-surface")
def get_options_gamma_surface(ticker: str = Query(...)):
    """Strike × expiration signed GEX$ surface (cell = net_gex_1pct) through the ONE canonical
    faucet compute_exposures_by_strike.

    ONE source: the LIVE surface _terrain_refresh_one (the single levels producer) projects each
    cycle from the live wide chain + live spot it already fetches (source=terrain_live_cache).
    With no live surface the answer is "unavailable" with the reason -- there is no second source
    (operator rule 2026-09-23: no fallbacks; the banked MORNING wide chain used to stand in).
    Exposes chain/spot as-of, source, and stale/degraded so the UI can fail stale visibly."""

    tk = ticker_storage_key(_required_ticker(ticker))
    now = time.time()
    _price_stored_chain_when_closed(tk, now)

    # ---- LIVE: surface projected this cycle from the canonical live terrain wide chain ----
    live = terrain_cache_get(tk, now)
    surf = (live or {}).get("_gamma_surface")
    _surface_live_spot = resolve_spot(tk)
    if live and surf:
        # ONE freshness authority: terrain_staleness (RC-424) already merged onto the cache by
        # terrain_cache_get — serialize it verbatim, never a second age policy for the same truth.
        stale = bool(live.get("levels_stale"))
        strikes = surf.get("strikes") or []
        # Operator directive (2026-09-14, live SPX reproduction): a surface with real strikes/
        # contracts but zero cells carrying usable open interest is NOT "available" in any
        # sense an operator cares about -- `available` now reflects project_gamma_surface's
        # own gamma_available signal (computed from the SAME per-cell _has_data gate the grid
        # itself renders from), not merely "did the live cache have a surface object at all".
        _gamma_available = surf["gamma_available"]   # project_gamma_surface always sets it
        # Always-live heatmap mandate (2026-09-15): `"live": True` above means "sourced from the
        # live terrain pathway", NOT "currently backed by a confirmed-fresh Schwab stream tick"
        # (a cold-stream surface still reaches here with cells stamped 'stale'/'unavailable' by
        # _publish_levels).
        #
        # Audit finding #6 (2026-09-16), FIXED: `stream_confirmed_live` used to mean "at least
        # one cell is live" (true with 1 of hundreds), and the field the UI actually rendered
        # a "LIVE" label from (this response's own `source`/`live` above) required NO per-cell
        # coverage at all -- a trader could see "LIVE" over a mostly stale/unavailable grid.
        # `stream_confirmed_live` is REMOVED (dead, misleadingly named, never consumed) and
        # replaced by `stream_coverage`, the ONE coverage verdict
        # (_gamma_surface_coverage_summary) with exact live/partial/stale/rejected/unavailable
        # counts and percentages, and `meets_live_requirement` gating the ONLY honest "LIVE"
        # claim: 100% of cells carrying a real contract identity, not source-path identity or
        # one live cell.
        _coverage = _gamma_surface_coverage_summary(surf)
        try:
            # Independent-review finding (2026-09-16, follow-up mandate item 1): "expose the
            # exact admitted, active, pending and rejected contracts" — a symbol-level
            # accounting, distinct from the per-cell disclosure above. Best-effort: a
            # diagnostic field must never take down the surface it is attached to.
            _contract_admission = _option_contract_admission_summary(tk, now)
        except Exception as _ca_e:  # institutional-swallow-ok: diagnostic-only, never load-bearing
            log.debug("contract admission summary skipped for %s: %s", tk, _ca_e)
            _contract_admission = None
        return JSONResponse({
            "ticker": tk, "symbol": tk, "available": _gamma_available,
            # "reason" (not a new field name) -- ed-gamma.js's own unavailable-branch already
            # reads surface.reason for the placeholder message; reusing it here means the
            # existing frontend contract picks this up with no client-side change required.
            "reason": None if _gamma_available else surf.get("gamma_unavailable_reason"),
            "source": "terrain_live_cache", "live": not live.get("levels_market_closed"),
            "stale": stale, "levels_as_of": live.get("levels_as_of"),
            "cell_stream_state_counts": _gamma_surface_cell_state_counts(surf),
            "stream_coverage": _coverage,
            "contract_admission": _contract_admission,
            "degraded": live.get("levels_stale_reason") if stale else None,
            "chain_as_of_ts_utc": live.get("computed_ts_utc"),
            "age_sec": live.get("levels_age_sec"),            # terrain's canonical age
            "refresh_active": live.get("levels_refresh_active"),
            "chain_basis": live.get("chain_basis"),
            "coverage": {
                "chain_basis": live.get("chain_basis"),
                "strike_count": len(strikes),
                "strike_min": (strikes[0] if strikes else None),
                "strike_max": (strikes[-1] if strikes else None),
                "expiry_count": len(surf.get("expirations") or []),
                "note": "every expiry and every strike Schwab listed (strike_range=ALL)",
            },
            **_stamp_surface_session(surf, reference_date=None),
            # one spot on every screen (2026-09-27): the live price, the header's own rule, after
            # the surface's own keys so its stamp cannot overwrite it. The
            # price this surface's cells were computed at is named on its own (operator directive
            # 2026-09-15: the cells and their stamp travel together) -- two names, no switching.
            "spot": _surface_live_spot[0],
            "spot_source": _surface_live_spot[1],
            "spot_as_of_ts_utc": _surface_live_spot[2],
            "priced_at_spot": surf.get("spot"),
            "spot_strike": nearest_strike(surf.get("strikes"), _surface_live_spot[0]),
            "priced_at_spot_as_of_ts_utc": surf.get("spot_as_of_ts_utc"),
            "provenance": {
                "producer": "math_exposure_core.compute_exposures_by_strike",
                "source": "the ticker's published levels (_publish_levels, the full chain)",
                "classification": "DERIVED", "cell_metric": "net_gex_1pct",
                "spot_basis": "live_resolve_spot",
            },
            "method": ("live terrain wide chain (current Greeks + live spot, this refresh cycle) -> "
                       "partition by native expirationDate -> compute_exposures_by_strike per expiry "
                       "-> net_gex_1pct cell; one producer, zero extra vendor calls"),
        })

    # ---- no live surface: unavailable, with the reason. Nothing stands in for it. ----
    # REQUESTED: this ticker is viewed. WARMING: viewed and the levels loop refreshes it now --
    # the refresh state itself (terrain_staleness: the session, a quarantine, a deliberate skip),
    # which is the same with or without published levels and on the board or not (the loop
    # refreshes every viewed ticker each cycle). The reason is that state's own.
    _requested = _gamma_surface_wanted(tk)
    _state = terrain_staleness((live or {}).get("computed_ts_utc"), tk, now)
    _warming = (_requested and _state["levels_refresh_active"] and not _state["levels_quarantined"]
                and not _state["levels_paused_on_purpose"])
    payload: dict = {"ticker": tk, "symbol": tk, "available": False, "source": "unavailable",
                     "live": False, "stale": True, "warming": _warming, "requested": _requested,
                     "reason": _state["levels_stale_reason"] or (
                         "the levels loop projects the surface at its next refresh of this ticker"
                         if _warming else "no gamma surface for this ticker's published levels")}
    return JSONResponse(payload)


# RC-UI-1's dev route (/console) converged into `/` here (operator directive 2026-09-14):
# static/console.html was renamed to static/index.html in this same commit, so the existing
# `/` route above (root(), reading static_dir/index.html) now serves it directly. No
# transitional dual-serving period -- /console is gone, not aliased.


@app.get("/api/terrain")
def get_terrain(ticker: str = Query(...)):
    """Terrain payload — levels only, NO model stack.

    Deliberately separate from /api/state: that path runs the full pipeline (chain +
    greeks + xgb/lstm/transformer x 4 horizons + fusion + decision bundle), which is why
    background collection had to be throttled to keep it responsive. Terrain is ~5 ms of
    math on the same chain, so it never needs to compete for that budget.
    """
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    now = time.time()
    cached = terrain_cache_get(tk, now)
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
        _terrain_refresh_one(tk, now, priority=True)
        now = time.time()                    # the answer is read after the refresh it waited on
        cached = terrain_cache_get(tk, now)
    if cached is not None:
        # the levels as the producer published them, every at-spot value computed at the
        # publication's spot -- the price they were computed at, labelled by spot_source and
        # spot_as_of_ts_utc, never called live (the live price is the daemon's price row);
        # internal fields (the kept chain, the heatmap grid, per-strike rows) have their own routes
        out = {k: v for k, v in cached.items() if not k.startswith("_")}
        out.update(terrain_staleness(cached.get("computed_ts_utc"), tk, now))
        return out
    spot, spot_source, spot_ts = resolve_spot(tk)
    _why = _terrain_refresh_last_error.get(tk)
    return compute_terrain(tk, None, spot).to_dict() | {
        "spot_source": spot_source, "spot_as_of_ts_utc": spot_ts,
        **_atr_fields(tk),              # from the bars, which do not wait for a chain
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
        **terrain_staleness(None, tk, now),
    }


#: The Trade Desk's lookback per chart timeframe: seconds, or "session" (the latest regular
#: session), with the words the page shows for it.
DESK_LOOKBACK = {"1": (900, "last 15 min"), "3": (1800, "last 30 min"), "5": ("session", "this session"),
                 "15": (14400, "last 4 h"), "30": ("session", "this session"),
                 "60": (172800, "last 2 days"), "D": (1728000, "last 20 days")}


def _desk_window_start(tf: str, now: datetime) -> float:
    """Start of the Trade Desk's event window for chart timeframe `tf`: `now` minus its lookback,
    or the open of the latest regular session that has begun."""
    from time_et import is_trading_day_et
    lb = DESK_LOOKBACK[tf][0]
    if lb != "session":
        return now.timestamp() - lb
    day = now.date()
    for _ in range(10):
        start = datetime(day.year, day.month, day.day, RTH_OPEN_MINS // 60, RTH_OPEN_MINS % 60, tzinfo=ET)
        if is_trading_day_et(day.isoformat()) and start <= now:
            return start.timestamp()
        day -= timedelta(days=1)
    raise ValueError(f"no regular session began in the 10 days to {now.date()} (market calendar)")


def _f2(v) -> str:
    return "—" if v is None else f"{float(v):.2f}"


@app.get("/api/desk/events")
def get_desk_events(ticker: str = Query(...),
                    venue: str = Query(..., pattern=r"^(NYSE_BOOK|NASDAQ_BOOK)$"),
                    tf: Annotated[str, Query(pattern=r"^(1|3|5|15|30|60|D)$")] = "30"):
    """The Trade Desk's attention queue, served: level crosses in the timeframe's window as
    recorded (level, direction, price, spot, time), numbered oldest first, the newest cross at
    each level for the newest DESK_MARKERS levels flagged for the chart; wall breaches and stale
    levels from the terrain; the book's size walls at the book's own time -- newest first, an
    item with no time last -- plus the window's up/down cross counts. One item is one event: the
    chart's marker and the queue's entry are the same item. The page draws it; it selects,
    numbers and orders nothing."""
    tk = ticker_storage_key(_required_ticker(ticker))
    start = _desk_window_start(tf, now_et())
    in_window = sorted(_merged_crosses_since(get_db(), tk, start), key=lambda c: c["ts_utc"])
    items = []
    for i, c in enumerate(in_window):
        names = " + ".join(c["level_names"])
        cid = c.get("cross_id")                      # external-key-ok: ed_console.db level_crosses column
        items.append({"key": f"x{cid}", "n": i + 1, "ts": c["ts_utc"], "dom": "LEVELS",
                      "price": c.get("level_value"), "dir": c.get("direction"), "marker": False,
                      "title": f"Crossed {_CROSS_WORD.get(c.get('direction'), 'through')} {names}",
                      "detail": f"{_f2(c.get('level_value'))} · spot {_f2(c.get('spot_at_cross'))} at the cross",
                      "src": "level_crosses"})
    # the chart's few: the newest cross at each level, for the newest DESK_MARKERS levels
    newest_at = {it["price"]: it for it in items}
    for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-DESK_MARKERS:]:
        it["marker"] = True
    t = get_terrain(ticker=tk)                       # the same payload the terrain route serves
    tts = t.get("computed_ts_utc")
    for side, word, key in (("call", "call", "cw"), ("put", "put", "pw")):
        if t.get(f"{side}_wall_state") == "breached":
            items.append({"key": key, "ts": tts, "dom": "OPTIONS", "dir": "up" if side == "call" else "down",
                          "title": f"Spot through the {word} wall",
                          "detail": f"{word} wall {_f2(t.get(f'{side}_wall'))} · spot {_f2(t.get('spot'))}",
                          "src": "/api/terrain"})
    if t.get("levels_stale"):
        items.append({"key": "ls", "ts": tts, "dom": "DATA", "dir": None, "warn": True,
                      "title": "Gamma levels are stale", "detail": t.get("levels_stale_reason") or "",
                      "src": "/api/terrain"})
    # the book's size walls, stamped with the book's own time (BOOK_TIME); a book that is not live
    # is a past observation and says so
    micro = json.loads(api_order_flow_microstructure(ticker=tk, venue=venue).body)
    book_ms = (micro.get("provenance") or {}).get("book_time_ms")
    live_book = (micro.get("ages") or {}).get("book_stale") is False
    for i, w in enumerate((micro.get("wall_candidates") or [])[:3]):
        items.append({"key": f"wall{i}", "ts": None if book_ms is None else book_ms / 1000.0,
                      "dom": "LIQUIDITY", "dir": "up" if w.get("side") == "bid" else "down", "warn": not live_book,
                      "title": f"{venue} size wall · {w.get('side') or ''} {_f2(w.get('price'))}"
                               + ("" if live_book else " (not live)"),
                      "detail": f"{w.get('volume')} shown · "
                                + (f"{w['median_mult']:.1f}× the median level" if w.get("median_mult") is not None else "size outlier")
                                + ("" if live_book else " · a past book, not the current one"),
                      "src": "/api/order-flow/microstructure"})
    items.sort(key=lambda it: (it["ts"] is None, -(it["ts"] if it["ts"] is not None else 0.0)))
    return JSONResponse({"ticker": tk, "tf": tf, "window_start_ts_utc": start,
                         "window_label": DESK_LOOKBACK[tf][1], "items": items,
                         "cross_counts": {d: sum(1 for c in in_window if c.get("direction") == d)
                                          for d in ("up", "down")}})


#: the chart draws the newest cross at each level, for the newest this-many levels (the queue
#: lists every cross)
DESK_MARKERS = 6


#: At most one push per this many seconds per page; changes in between arrive together.
CHANGES_PUSH_MIN_SEC = 1.0
#: The session label and the sign-in are pushed this often, whatever else is pushed (they double
#: as the heartbeat).
CHANGES_SESSION_SEC = 5.0


@app.get("/api/changes")
async def get_changes(ticker: str = Query(...), view: str = Query(..., min_length=1)):
    """The console's push to the page: `levels`, `chain` or `flow` when that value of the
    ticker changed (the page reloads it), and, on connect and every CHANGES_SESSION_SEC after
    (on its own clock: a busy ticker does not hold it back), `session` with the market session
    label and `sign_in` with the Schwab sign-in's state (schwab_sign_in_status). Prices
    and bars come from the daemon's own push. Opening it makes the ticker the active one, whose
    NYSE_BOOK and NASDAQ_BOOK the daemon streams: every page reconnects after a console
    restart, so the books follow the page with no separate request. `view` is the page load's
    id: the connection is what holds the view's option-contract demand, which ends when the
    view's last connection closes."""
    from app.options.order_flow.streaming import release_option_contract_demand, set_streaming_active_ticker

    t = ticker_storage_key(_required_ticker(ticker))
    _get_route_offload_executor().submit(lambda: (set_streaming_active_ticker(t),
                                                  _ensure_default_option_contract(t, time.time())))

    def status() -> str:
        sign_in = json.dumps(schwab_sign_in_status(_schwab_token_creation_ts(), time.time()))
        return f"event: session\ndata: {session_label(now_et())}\n\nevent: sign_in\ndata: {sign_in}\n\n"

    async def event_generator():
        # subscribed only once the response is being sent, so every subscription is closed
        client = push_changes.subscribe(t, view)
        clock = asyncio.get_running_loop().time
        status_due = clock()          # on connect, then on its own clock whatever else is pushed
        try:
            while True:
                if clock() >= status_due:
                    yield status()
                    status_due = clock() + CHANGES_SESSION_SEC
                kinds = await push_changes.next_changes(client, status_due - clock())
                for k in sorted(kinds):
                    yield f"event: {k}\ndata: {t}\n\n"
                if kinds:
                    await asyncio.sleep(CHANGES_PUSH_MIN_SEC)
        finally:
            push_changes.unsubscribe(t, client)
            _get_route_offload_executor().submit(release_option_contract_demand, view)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/order-flow/microstructure")
def api_order_flow_microstructure(ticker: str = Query(...),
                                  venue: str = Query(..., pattern=r"^(NYSE_BOOK|NASDAQ_BOOK)$")):
    """Canonical L2 book microstructure (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1): top-of-book,
    spread, microprice, Top 1/3/5 depth totals + imbalance, depth-pressure curve, book slope,
    liquidity concentration, wall_candidates, and ages — every field classified
    NATIVE/DERIVED. SERIALIZER, not a second producer: it delegates to the ONE canonical
    app.options.order_flow.engine.compute_book_microstructure keyed by this ticker, which carries the
    engine's already-computed structural state for the current book (memoized per ticker +
    BOOK_TIME) rather than re-walking the raw book. No Schwab REST quote call; the client
    renders, never recomputes. `venue` is the one Schwab book shown: NYSE_BOOK (exchanges) or
    NASDAQ_BOOK (market makers); the two are never combined."""
    t = ticker_storage_key(_required_ticker(ticker))
    from app.options.order_flow.state import get_content_for_symbol
    data: dict = {"content": get_content_for_symbol(t, venue)}
    # top of book: the daemon's price row (its fields are None while the quote is not live)
    from app.options.order_flow.streaming import price_row
    _row = price_row(t)
    if _row and _row.get("quote_ts") is not None:
        data["exchange_quote_ts"] = _row["quote_ts"]
    data["top"] = ({k: _row.get(k) for k in ("bid", "ask", "bid_size", "ask_size", "mark")}
                   if _row and (_row.get("bid") is not None or _row.get("ask") is not None) else None)
    now = time.time()
    data["book_live"] = lmp.book_is_live(t, venue, now)
    from app.options.order_flow.engine import compute_book_microstructure
    # ticker=t → serialize the canonical state carried per (ticker, BOOK_TIME); no independent recompute.
    payload = compute_book_microstructure(data, now_ts=now, ticker=t)
    payload["ticker"] = t
    payload["venue"] = venue
    return JSONResponse(payload)


@app.get("/api/order-flow/options-microstructure")
def api_order_flow_options_microstructure(contract: str = Query(...)):
    """Same canonical L2 book microstructure as /api/order-flow/microstructure, for one
    OPTION CONTRACT's live book. SERIALIZER, not a second producer: delegates to
    app.options.order_flow.live_payload.options_live_payload, which reads
    the SAME app.options.order_flow.engine.compute_book_microstructure the equity route reads — no
    parallel book-imbalance computation for options. `contract` MUST be a chain response's
    own "symbol" field (OSI format, e.g. "SPY   260820C00767000"); this route does not
    construct or validate that format, it only serializes whatever content has been
    replayed for the literal string given. No ticker-roster touch here — a contract symbol
    is not a ticker and does not participate in that enrollment concept."""
    c = (contract or "").strip()
    if not c:
        return JSONResponse({"error": "contract is required"}, status_code=400)
    from app.options.order_flow.live_payload import options_live_payload
    from app.options.order_flow.streaming import get_option_contract_streaming_diagnostics
    now = time.time()
    payload = options_live_payload(ticker_storage_key(c), now)
    payload["contract"] = c
    from app.options.order_flow.history import put_call_side
    from app.options.order_flow.state import option_contract_type
    payload["put_call"] = put_call_side(option_contract_type(c))   # Schwab's CONTRACT_TYPE, as streamed
    try:
        # PR214 merge blocker 1A: the diagnostics are bound to the CONTRACT BEING
        # QUERIED, not to whatever contract the plane happens to be streaming. Without
        # `c` this attached the globally-active contract's health verbatim to a book
        # computed for a different contract, so a response could read `contract: A`
        # beside `streaming_healthy: true` that belonged entirely to B. The book above
        # is still served truthfully (replayed content for A is real and is not
        # discarded); only the LIVE HEALTH claim is bound and fails closed on mismatch.
        payload["streaming_plane"] = get_option_contract_streaming_diagnostics(c, now)
    except Exception:  # diagnostics are informational only — never fail the book payload for them
        payload["streaming_plane"] = {}
    return JSONResponse(payload)
@app.post("/api/streaming/active-option-contract")
async def post_streaming_active_option_contract(payload: dict = Body(default={})):
    """Subscribe LEVELONE_OPTIONS+OPTIONS_BOOK to one option contract (dynamic; replaces
    prior subscription): the option-contract slot, separate from the equity books (an equity
    ticker and an option contract on that same underlying
    can be watched at once — see app/options/order_flow/streaming.py's module docstring)."""
    c = str(payload.get("contract") or "").strip()
    if not c:
        return JSONResponse({"ok": False, "error": "contract is required"}, status_code=400)

    # PR214 premerge gap 2: take the command's generation HERE, at admission, before the
    # body is offloaded to the executor. Ordering must reflect the order the operator's
    # commands ARRIVED, not the order their thread-pool bodies happen to finish -- an
    # A admitted first but delayed must not overwrite a B admitted later that already
    # wrote. The browser token cannot cover this: it only suppresses a stale RESPONSE.
    from app.options.order_flow.streaming import (
        StaleOptionCommandError,
        begin_option_contract_command,
    )
    generation = begin_option_contract_command()

    def _apply():
        from app.options.order_flow.streaming import (
            set_active_option_contract,
            get_option_contract_streaming_diagnostics,
        )

        ok = set_active_option_contract(c, command_generation=generation)
        # PR214 merge blocker 1A: bind the acknowledgement's health to the contract
        # THIS request asked for, so a client that validates the ack cannot be handed
        # a healthy-looking plane belonging to a different contract.
        diag = get_option_contract_streaming_diagnostics(c, time.time())
        return {"ok": ok, "contract": c, "command_generation": generation, **diag}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_route_offload_executor(), _apply)
    except StaleOptionCommandError as e:
        # A superseded command is NOT the current authority. 409 Conflict, ok:false --
        # the client must not treat this as a successful subscription of `c`.
        return JSONResponse({"ok": False, "error": str(e), "contract": c,
                             "superseded": True, "command_generation": generation},
                            status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "contract": c}, status_code=500)
    return JSONResponse(out)


@app.post("/api/streaming/watchlist-symbols")
async def post_streaming_watchlist_symbols(payload: dict = Body(default={})):
    """The browser's watchlist, so the daemon streams each row's LEVELONE_EQUITIES (the
    daemon's fixed roster is only its --symbols). Returns the symbols left unstreamed with
    the reason -- a row that can't be streamed says why instead of borrowing a REST quote."""
    from app.options.order_flow.streaming import declare_equity_symbols
    syms = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(syms, list):
        raise HTTPException(status_code=400, detail="symbols must be a list")
    not_admitted = declare_equity_symbols("watchlist", [str(x) for x in syms])
    return {"ok": True, "not_streamed": not_admitted}


@app.post("/api/streaming/active-option-contracts")
async def post_streaming_active_option_contracts(payload: dict = Body(default={})):
    """One view's ADDITIONAL option contracts for LEVELONE_OPTIONS+OPTIONS_BOOK, beside the
    one primary contract /api/streaming/active-option-contract manages (RC-UI-3).

    Body: {client_id, seq, contracts}. Each view (page load) declares its own demand under
    its own client_id (the `view` of its /api/changes connection, which must be open: 409
    `not_connected` otherwise); `seq` orders that view's declarations. The stream carries the
    union of every view's demand ranked to the shared-socket budget
    (app.options.order_flow.streaming.declare_option_contract_demand)."""
    raw = payload.get("contracts")
    contracts = [str(s).strip() for s in raw] if isinstance(raw, list) else []
    contracts = [c for c in contracts if c]
    client_id = payload.get("client_id")
    seq = payload.get("seq")
    if not isinstance(client_id, str) or not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id (this view's id) is required")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise HTTPException(status_code=400,
                            detail="seq (this view's declaration counter) must be an integer")

    from app.options.order_flow.streaming import StaleOptionCommandError, ViewNotConnectedError

    def _apply():
        from app.options.order_flow.streaming import (
            declare_option_contract_demand, get_active_option_contracts,
            get_option_contracts_budget_state, get_option_contracts_not_admitted)
        declared = declare_option_contract_demand(client_id, contracts, seq=seq)
        # `requested` is THIS view's accepted demand (what the view confirms against);
        # `contracts` is what the stream actually carries (the union of every view, ranked
        # to the budget) -- never an echo of the request, so no view believes more is
        # streamed than is. The left-out set rides beside it.
        return {"ok": True, "client_id": client_id, "seq": seq,
                "requested": declared["requested"], "demand_views": declared["demand_views"],
                "contracts": list(get_active_option_contracts()),
                "requested_count": len(contracts),
                "not_admitted": get_option_contracts_not_admitted(),
                **get_option_contracts_budget_state()}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_route_offload_executor(), _apply)
    except StaleOptionCommandError as e:
        return JSONResponse({"ok": False, "error": str(e), "client_id": client_id, "seq": seq,
                             "superseded": True}, status_code=409)
    except ViewNotConnectedError as e:
        return JSONResponse({"ok": False, "error": str(e), "client_id": client_id, "seq": seq,
                             "not_connected": True}, status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "contracts": contracts}, status_code=500)
    return JSONResponse(out)


@app.get("/api/expiries")
def get_expiries(ticker: str = Query(...)):
    """The ticker's listed expiries with each one's dropdown label (MM/DD/YYYY and Schwab's
    daysToExpiration, as sent); with none, the levels' own reason."""
    ticker = ticker_storage_key(_required_ticker(ticker))   # SPX -> $SPX: the cache's own key
    now = time.time()
    t = terrain_cache_get(ticker, now) or {}
    exps, dte = t.get("expiries") or [], t.get("expiry_dte") or {}
    labels = {e: f"{e[5:7]}/{e[8:10]}/{e[:4]}" + (f" · {dte[e]:g}DTE" if dte.get(e) is not None else "")
              for e in exps}
    return JSONResponse({"expiries": exps, "dte": dte, "labels": labels,
                         "reason": None if exps else (terrain_staleness(None, ticker, now)["levels_stale_reason"]
                                                      if not t else "no expiry listed in the published chain")})



@app.get("/api/chain")
def get_chain(ticker: str = Query(...),
              expiry: Optional[str] = Query(default=None)):
    """One expiry of the ticker's full chain -- every contract Schwab listed, every field as sent
    -- from the chain the levels loop downloads (strike_range=ALL), with each live streamed
    contract's streamed fields as its values (the stream owns them). The loop keeps a ticker's chain while a page has it
    open. Answers `status: unavailable` with a reason when no
    chain is held."""
    t = ticker_storage_key(_required_ticker(ticker))
    now = time.time()
    _price_stored_chain_when_closed(t, now)
    held = terrain_cache_get(t, now) or {}
    resolved_expiry = (expiry or "").strip()[:10] or (held.get("expiries") or [None])[0]

    def _unavailable(reason: str) -> JSONResponse:
        return JSONResponse({"ticker": t, "spot": None, "expiry": resolved_expiry,
                             "contracts": [], "status": "unavailable",
                             "scope": {"kind": "unavailable", "requested_expiry": resolved_expiry,
                                       "reason": reason}})

    chain = held.get("_chain")
    if not chain:
        return _unavailable(held.get("error") or "the chain for this ticker has not been downloaded")
    if resolved_expiry is None:
        return _unavailable("no listed expiry for this ticker")
    contracts = [c for c in chain if str(c.get("expirationDate") or "")[:10] == resolved_expiry]
    if not contracts:
        return _unavailable(f"the chain lists no contracts for {resolved_expiry}")
    fetched_ts = held.get("_chain_fetched_ts")
    response_contracts, overlay_n, _ = _gamma_surface_contracts_with_stream_overlay(t, contracts, now)
    live_spot, _src, _ts = resolve_spot(t)       # the one spot on every screen
    ladder, not_on_ladder = chain_ladder(response_contracts, live_spot)
    # this expiry's net GEX per strike, as the heatmap publishes it (its column of the surface):
    # Strike Detail shows it beside this expiry's contracts -- one value, one producer
    surf = held.get("_gamma_surface") or {}
    col = next((i for i, e in enumerate(surf.get("expirations") or [])
                if e.get("expiry") == resolved_expiry), None)
    net_gex_by_strike = [] if col is None else [
        [c["strike"], c["gex"][col]] for c in surf.get("cells") or [] if c["gex"][col] is not None]
    return JSONResponse({
        "ticker": t, "spot": live_spot, "priced_at_spot": held.get("spot"),
        "expiry": resolved_expiry,
        "net_gex_by_strike": net_gex_by_strike,
        "spot_strike": nearest_strike({k for c in response_contracts
                                       if (k := schwab_number(c.get("strikePrice"))) is not None}, live_spot),
        # Schwab's own flag for a non-standard (adjusted) deliverable, as sent
        "adjusted_deliverable_symbols": [c.get("symbol") for c in response_contracts
                                         if c.get("nonStandard") is True],   # external-key-ok: Schwab option chain contract
        # two contracts listed at one (strike, side): the chain is not strike-unique
        "has_duplicate_contracts": len({(schwab_number(c.get("strikePrice")), c.get("putCall")) for c in response_contracts})
                                   < len(response_contracts),
        "chain_as_of_ts_utc": fetched_ts,
        # whether this chain is current (terrain_staleness, the levels' own authority: the levels
        # and the chain are one download): levels_stale, its reason, the age, market closed
        **terrain_staleness(fetched_ts, t, now),
        "contracts": response_contracts, "status": "ok",
        "ladder": ladder, "n_strikes": len({r["strike"] for r in ladder}),
        "contracts_not_on_ladder": not_on_ladder,   # no strike, or a putCall other than CALL/PUT
        "stream_overlay_contracts": overlay_n,
        "scope": {"kind": "complete_single_expiry", "requested_expiry": resolved_expiry,
                  "completeness_basis": held.get("chain_basis")},   # the publication's own label
    })

@app.get("/api/health")
def health():
    with _logger_lock:
        n       = len(_logger_tickers)
    # RC-514 / docs/ARCHITECTURE.md "Failure domains": application availability and capability
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
        "logger_tickers": n,
        "capabilities": capability,
    }


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

    identity_source = "git_startup_capture" if git_available else "unavailable"

    return ProcessIdentityV1(
        schema_version="1",
        startup_git_sha=sha,
        startup_git_sha_short=sha_short,
        startup_git_dirty=dirty,
        startup_git_available=git_available,
        startup_identity_captured_at_utc=captured_at,
        process_started_at_utc=started_at,
        process_id=pid,
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
    repo_head_now = _repo_git_head_sha()
    identity = asdict(PROCESS_IDENTITY_V1)
    startup_sha = identity.get("startup_git_sha")
    return {
        "git_sha": startup_sha,  # PROCESS IDENTITY (startup capture) — never request-time git
        "contract": "meet_or_exceed_v1",
        "process_identity": identity,
        "repository_state_now": {"repo_head_now": repo_head_now},
        "code_drift": {
            "repo_moved_past_process": bool(
                startup_sha and repo_head_now and startup_sha != repo_head_now
            ),
            "running_code": startup_sha,
            "checked_out_code": repo_head_now,
        },
        "git_sha_semantics": "startup_process_identity",
    }


def _publish_price_levels(ticker: str) -> None:
    """THE producer of a ticker's price-level snapshot (Phase 2A): materialized for today's
    session from its completed Schwab 1m bars in price_bars_1m, by the bar writer after each of
    the ticker's bars, and by the levels loop for a ticker with none yet today (a restart, a new
    session date). The routes read what it published (canonical_price_level_snapshot). A failed
    build is logged; the routes serve the last published snapshot with its as-of time, or say
    the levels are absent."""
    from liquidity_value_engine import _bars_to_list, materialize_price_level_snapshot
    from time_et import now_et

    tk = ticker_storage_key(_required_ticker(ticker))
    before = canonical_price_level_snapshot(tk)
    try:
        snap = materialize_price_level_snapshot(tk, now_et().date(), _bars_to_list(_liquidity_1m_bars(tk)),
                                                bar_source="price_bars_1m", config=PlaybookConfig())
    except Exception as e:  # noqa: BLE001 -- logged; the ticker's next bar builds them
        log.warning("price levels for %s not built: %s", tk, e)
        return
    if snap is not before:   # the same object when its bars did not change
        push_changes.changed(tk, push_changes.LEVELS)


def _publish_missing_price_levels(tickers) -> None:
    """Build the price levels of each ticker with none published for today (the console's
    start, a new session date)."""
    for tk in tickers:
        if canonical_price_level_snapshot(tk) is None:
            _publish_price_levels(tk)


def canonical_price_level_snapshot(ticker: str):
    """The ticker's price-level snapshot for today as its producer published it
    (_publish_price_levels), or None when none is published yet. Every server surface reads
    this; none computes a level."""
    from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
    from time_et import now_et

    return _MATERIALIZED_SNAPSHOTS.get((ticker_storage_key(_required_ticker(ticker)), now_et().date().isoformat()))


#: why a route serves no price levels for a ticker
NO_PRICE_LEVELS_REASON = ("no price levels published for this ticker today yet (they are built from its "
                          "1-minute bars on each new bar and at the console's start)")

PRIOR_CLOSE_SOURCE = "Schwab LEVELONE_EQUITIES CLOSE_PRICE (the daemon's price row)"
PRIOR_CLOSE_ABSENT_REASON = "Schwab's prior close (CLOSE_PRICE) is not streaming live for this symbol now"


def _prior_close(tk: str) -> "float | None":
    """The ticker's prior close: Schwab's CLOSE_PRICE on the daemon's price row, which carries it
    only while the symbol's quote is live. The one prior close every surface shows."""
    from app.options.order_flow.streaming import price_row
    return (price_row(tk) or {}).get("prior_close")



#: the terrain's price levels the chart draws (terrain_engine.compute_terrain), in its words
GAMMA_LEVELS = (("call_wall", "Call wall"), ("put_wall", "Put wall"), ("gamma_flip", "Gamma flip"),
                ("max_pain", "Max pain"), ("net_gex_peak", "Net Γ peak"), ("absolute_gamma_strike", "Abs Γ"),
                ("pin_candidate", "Pin candidate"), ("gsf", "GSF"), ("grc", "GRC"), ("hvp", "HVP"),
                ("lvp", "LVP"), ("key_delta_strike", "Key Δ strike"), ("call_charm_wall", "Call charm wall"),
                ("put_charm_wall", "Put charm wall"))


@app.get("/api/levels")
# Phase 2A (operator 2026-08-08): /api/levels is the canonical SERVING CONTRACT for the
# one materialized PriceLevelSnapshot — it serializes, it does not compute. Every other
# surface (liquidity-snapshot, market_context, /api/state, ML features, persistence,
# chart) carries the values out of the same snapshot object and generation.
def get_levels(ticker: str = Query(...),
               tf: Annotated[str, Query(pattern=r"^(1|3|5|15|30|60|D)$")] = "1"):
    """Single levels contract (schema v1): id/price/family/evidence_tier/provenance/staleness."""
    import time as _time

    tk = ticker_storage_key(_required_ticker(ticker))
    served_ts = _time.time()
    spot, spot_source, spot_ts = resolve_spot(tk)
    snap = canonical_price_level_snapshot(tk)

    levels: list[dict] = []
    for lid, value in (snap.levels.items() if snap is not None else ()):
        row = value.to_contract_dict()
        as_of = value.as_of_ts_utc
        row["staleness"] = {
            "as_of_ts_utc": as_of,
            "age_sec": None if as_of is None else round(served_ts - as_of, 1),
            "stale_after_sec": None,
            "stale": None,
            "reason": f"carried from canonical snapshot generation {snap.generation}; a session "
                      "price level has no staleness rule, its age is shown",
        }
        levels.append(row)
    # the prior close, carried from the daemon's price row (Schwab's CLOSE_PRICE)
    pdc = _prior_close(tk)
    if pdc is not None:
        levels.append({"id": "PDC", "price": pdc, "family": "prior_day", "label": LEVEL_NAMES["PDC"][0],
                       "short": LEVEL_NAMES["PDC"][1], "evidence_tier": "price_fact",
                       "provenance": {"producer": PRIOR_CLOSE_SOURCE, "carried": True},
                       "staleness": {"as_of_ts_utc": None, "age_sec": None, "stale_after_sec": None,
                                     "stale": None, "reason": "streamed; served only while its quote is live"}})
    # the gamma family, carried from the terrain (terrain_engine.compute_terrain's own values)
    t = terrain_cache_get(tk, served_ts) or {}
    em = (t.get("implied_1d_move") or {}).get("points")
    carried = [(gid, label, "gamma", t.get(gid)) for gid, label in GAMMA_LEVELS]
    carried += [("em_up", "+1σ move", "expected_move", None if em is None or spot is None else spot + em),
                ("em_dn", "−1σ move", "expected_move", None if em is None or spot is None else spot - em)]
    for gid, label, fam, price in carried:
        if price is not None:
            as_of = t.get("computed_ts_utc")
            levels.append({"id": gid, "price": price, "family": fam, "label": label, "short": label,
                           "evidence_tier": "DERIVED",
                           "provenance": {"producer": "terrain_engine.compute_terrain", "carried": True}
                           if fam == "gamma" else {"producer": "server.get_levels: live spot ± the terrain's "
                                                   "implied_1d_move.points", "carried": False},
                           "staleness": {"as_of_ts_utc": as_of,
                                         "age_sec": None if as_of is None else round(served_ts - as_of, 1),
                                         "stale_after_sec": None, "stale": bool(t.get("levels_stale")),
                                         "reason": "carried from the terrain"}})
    for row in levels:
        price = row.get("price")
        row["distance"] = (price - spot) if price is not None and spot else None
        # which side of spot, at the price's own two decimals (AT: prints as 0.00 away)
        row["side"] = (None if row["distance"] is None else "AT" if round(row["distance"], 2) == 0
                       else "ABOVE" if row["distance"] > 0 else "BELOW")
    # the ladder in price order (highest first, unpriced last), and the order by distance to spot
    levels = (sorted((r for r in levels if r.get("price") is not None), key=lambda r: r["price"], reverse=True)
              + [r for r in levels if r.get("price") is None])
    # the order the chart draws them in: nearest the live price, or on a closed market nearest the
    # last streamed trade, a past observation named in by_distance_ref (display order only:
    # distance and side stay live-price values)
    from app.options.order_flow.streaming import price_row
    last = None if spot is not None else (price_row(tk) or {}).get("closed_last")
    ref = spot if spot is not None else last["price"] if last else None
    by_distance = [] if ref is None else [r["id"] for r in sorted((r for r in levels if r.get("price") is not None),
                                                                  key=lambda r: abs(r["price"] - ref))]

    families_absent = (list(snap.families_absent) if snap is not None
                       else [{"family": "price_levels", "reason": NO_PRICE_LEVELS_REASON}])
    vp = snap.volume_profile if snap is not None else None
    if pdc is None:
        families_absent.append({"family": "PDC", "reason": PRIOR_CLOSE_ABSENT_REASON})
    if em is None or spot is None:
        families_absent.append({"family": "expected_move", "reason": "no live price" if spot is None
                                else "the terrain has no implied 1-day move"})
    # each gamma level the terrain published no value for, with the reason it published
    families_absent += [{"family": gid, "reason": why}
                        for gid, why in (t.get("level_absent_reasons") or {}).items()]

    return JSONResponse({
        "ticker": tk,
        "schema_version": 1,
        "served_ts_utc": served_ts,
        "spot": spot,
        "spot_source": spot_source,
        "spot_as_of_ts_utc": spot_ts,
        "generation": snap.generation if snap is not None else None,
        "snapshot_as_of_ts_utc": snap.as_of_ts_utc if snap is not None else None,
        # how old the snapshot's newest bar is at this serving
        "snapshot_age_sec": (round(served_ts - snap.as_of_ts_utc, 1)
                             if snap is not None and snap.as_of_ts_utc is not None else None),
        "bar_source": snap.bar_source if snap is not None else None,
        "levels": levels,
        "by_distance": by_distance,
        "by_distance_ref": None if ref is None else
        {"price": ref, "source": "live price"} if spot is not None else
        {"price": ref, "source": "last trade", "as_of": last["as_of"]},
        # The VWAP curve and its σ bands, CARRIED. The standalone pages each
        # used to accumulate their own from /api/bars1m — two more VWAPs for one
        # session, drawn beside a level neither of them agreed with.
        # [epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ]
        # one point per chart bar of `tf`, at that bar's own time
        "vwap_series": aggregate_vwap(snap.vwap_series, tf, snap.session_bar_ts) if snap is not None else [],
        # the session's volume profile the value area is read from (absent: families_absent
        # names the value_area reason)
        "volume_profile": None if vp is None else {
            "basis": "Estimated volume by price: each RTH 1-minute bar's volume spread evenly over its "
                     "range (not trades observed at a price)",
            "bars": vp.bars, "bars_without_volume": vp.bars_without_volume, "tick_size": vp.tick_size,
            # [price, volume, inside the value area]
            "bins": [[p, v, vp.val <= p <= vp.vah] for p, v in vp.bins],
            "poc": vp.poc, "vah": vp.vah, "val": vp.val},
        "tf": tf,
        "families_absent": families_absent,
        "degraded": list(snap.degraded) if snap is not None else [],
    })


def _liquidity_1m_bars(ticker: str) -> list[dict]:
    """The ticker's completed Schwab 1-minute bars (price_bars_1m), in the liquidity engine's
    shape."""
    return [{"timestamp": int(float(c.ts) * 1000), "open": c.open, "high": c.high,
             "low": c.low, "close": c.close, "volume": c.volume} for c in _bars_1m(ticker, 2500)]


#: the terrain levels the liquidity zones are fused with, and the tag each carries
TERRAIN_FUSION_LEVELS = (("call_wall", "GAMMA_CALL_WALL"), ("put_wall", "GAMMA_PUT_WALL"),
                         ("call_delta_wall", "DELTA_CALL_WALL"), ("put_delta_wall", "DELTA_PUT_WALL"),
                         ("absolute_gamma_strike", "ABS_GAMMA"), ("net_gex_peak", "NET_GEX_PEAK"),
                         ("max_pain", "MAX_PAIN"), ("gamma_flip", "GAMMA_FLIP"))


def _liquidity_option_levels(terrain: dict) -> list[tuple[float, str]]:
    """The option levels of a published terrain (terrain_cache_get), tagged for the liquidity zones."""
    return [(terrain[k], tag) for k, tag in TERRAIN_FUSION_LEVELS if terrain.get(k) is not None]


def _spot_location(zones: list, spot) -> "dict | None":
    """Where spot sits among the zones, by index into `zones`: the zone it is inside, else the
    nearest zone above and below. None without a spot or a zone."""
    if spot is None or not zones:
        return None
    for i, z in enumerate(zones):
        if z["zone_low"] <= spot <= z["zone_high"]:
            return {"inside": i, "above": None, "below": None}
    above = [i for i, z in enumerate(zones) if z["zone_low"] > spot]
    below = [i for i, z in enumerate(zones) if z["zone_high"] < spot]
    return {"inside": None,
            "above": min(above, key=lambda i: zones[i]["zone_low"]) if above else None,
            "below": max(below, key=lambda i: zones[i]["zone_high"]) if below else None}


#: no zone is wider than this many dollars, for every ticker at every price (the figure's origin
#: is not recorded: ACTIVE_PROGRAM.md ZONE-WIDTH)
ZONE_MAX_WIDTH_DOLLARS: float = 2.0


@app.get("/api/liquidity-snapshot")
def get_liquidity_snapshot(ticker: str = Query(...)):
    """The ticker's zones (liquidity_value_engine.build_zones): the one price-level snapshot's
    levels (the values /api/levels serves), Schwab's prior close and the terrain's option levels,
    clustered and placed against the live price; with today's value context (value_context) and
    where the price sits among the zones. It computes no level of its own. `absent` names each
    input it did not have, with the reason. The two inputs' times ride with the zones: the
    newest bar's (`levels_as_of`) and, in `option_levels`, the terrain's own freshness verdict
    (terrain_staleness, as /api/terrain serves it) for the option levels in them."""
    tk = ticker_storage_key(_required_ticker(ticker))
    canon = canonical_price_level_snapshot(tk)
    if canon is None:
        return {"ticker": tk, "zones": [], "reason": NO_PRICE_LEVELS_REASON}
    spot = resolve_spot(tk)[0]
    terrain = terrain_cache_get(tk, time.time()) or {}
    option_levels, pdc = _liquidity_option_levels(terrain), _prior_close(tk)
    absent = [a for a in (
        None if spot is not None else
        {"input": "live price", "reason": "no live price: a zone has no side and the price has no location"},
        None if option_levels else
        {"input": "option levels", "reason": "no option levels are published for this ticker yet"},
        None if pdc is not None else {"input": "PDC", "reason": PRIOR_CLOSE_ABSENT_REASON}) if a]
    zones = [{"zone_type": z.zone_type.value,
              "zone_label": ZONE_DISPLAY[z.zone_type][0], "zone_side": ZONE_DISPLAY[z.zone_type][1],
              "zone_low": z.zone_low, "zone_high": z.zone_high, "zone_mid": z.zone_mid,
              "source_levels": z.source_levels, "confluence_score": z.confluence_score}
             for z in build_zones(canon, PlaybookConfig(max_zone_width=ZONE_MAX_WIDTH_DOLLARS), spot=spot,
                                  extra_levels=option_levels + ([(pdc, "PDC")] if pdc is not None else []))]
    return {
        "ticker": tk,
        "zones": zones,
        "summary": asdict(value_context(canon)),
        "spot_location": _spot_location(zones, spot),
        "absent": absent,
        # which price-level snapshot the zones are built from, and the time of its newest bar
        "level_generation": canon.generation,
        "level_snapshot_as_of_ts_utc": canon.as_of_ts_utc,
        "levels_as_of": None if canon.as_of_ts_utc is None else ct_label(canon.as_of_ts_utc),
        # the option levels' source and freshness, every `levels_*` field of their terrain
        "option_levels": {k: v for k, v in terrain.items() if k.startswith("levels_")} if option_levels else None,
    }


