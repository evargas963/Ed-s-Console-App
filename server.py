"""Ed Console web server: the levels loop, the bar writer, and the routes the screens read."""

from __future__ import annotations

import os
import signal
import sys
import time
import asyncio
import logging
import concurrent.futures
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional
from dataclasses import asdict, dataclass

import time_et as _time_et
from time_et import (now_et, RTH_OPEN_MINS, is_capturable_session,
                     is_trading_day_et, session_label)

import json
import queue


from fastapi import Body, FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.options_order_flow import router as options_order_flow_router

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
# RC-523: under the RUNTIME root (runtime_layout), which is this checkout unless
# ED_RUNTIME_ROOT moves it — runtime output must not pollute the source tree (§8).
from runtime_layout import data_dir, logs_dir as _runtime_logs_dir, reports_dir as _artifact_reports_dir  # noqa: E402

ED_SERVER_LOG_PATH = _runtime_logs_dir() / "ed_server.log"


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
    inspect_token_file,
    safe_get_chain,
    SchwabAuthError,
)
from instrument_identity import ticker_storage_key   # RC-126: the ONE query-symbol authority
from json_blob_codec import decode_json_blob   # RC-REHAB-3: transparent gzip on JSON blob columns
from math_levels import gamma_at_price
from market_context import (
    market_context_panel_symbols_excluding_core,
)
from terrain_read import build_terrain_read
from terrain_engine import TerrainSnapshot, compute_terrain, wall_geometry_state
from terrain_atr import AtrPair, compute_atr_pair

from db import get_db

import live_market_plane as _lmp
import live_price_rows as _lpr        # THE displayed price row (shared with the capture daemon)

# ── Config + Schwab client (refreshable singleton) ────────────────────────────
load_dotenv_file()
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




#: Precedence for the ONE spot authority. Highest wins; every entry records where the
#: number came from so a caller can never silently accept a lower-confidence source.
#
# Operator-reproduced defect (2026-09-14, "360 audit... spot can be a different number on
# the gamma chart"): resolve_spot's OWN docstring has claimed "THE single spot authority"
# since RC-14, and a real static lock (tests/test_spot_authority_v1.py::
# test_every_vendor_quote_read_goes_through_the_memo) keeps every RAW REST vendor quote
# fetch behind it. That lock is real and it worked -- for the REST world it covers. It
# never covered live_market_plane (Layer A): that module is ALSO an authoritative,
# internally-disciplined quote store (its own docstring: "authoritative in-process live
# quote plane... Tier A GET /api/live/state, Tier B GET /api/analytics/light, and Tier C
# _fetch_state/GET /api/state all read this plane"), fed primarily by the Schwab
# **streaming** websocket, completely independent of resolve_spot's REST-polling
# _memoized_quote_response/_quote_memo. Two individually well-governed producers, never
# reconciled with each other, is what allowed this: resolve_spot's 9 call sites (terrain,
# /api/terrain/strikes -- the Gamma Chart's own inputs -- and others) never saw a streaming
# tick at all, while the header/analytics stack read the plane FIRST and only fell back to
# the REST memo when the plane was empty. Both sides were locked against duplicating
# THEMSELVES; nothing ever locked them against diverging from EACH OTHER. Fixed at the
# root: the plane is now resolve_spot's own highest-precedence source (freshness-gated,
# never trusted stale), so every caller of the one authority function converges on the
# same number the header shows, instead of two parallel hierarchies that happened to
# usually agree.
SPOT_SOURCE_PLANE = "streaming_plane"          # live_market_plane.get_quote — the freshest real trade this process has seen
SPOT_SOURCE_QUOTE = "schwab_quote_last"        # quotes.{SYM}.quote.lastPrice - a real trade


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




def resolve_spot(ticker: str, *, chain_json: dict | None = None,
                 allow_stored: bool = True,
                 quote_node: dict | None = None) -> tuple[float | None, str, float | None]:
    """THE single current-spot authority. Returns (spot, source, as_of_ts_utc).

    SPOT IS Schwab LEVELONE_EQUITIES LAST_PRICE, as streamed -- 0 hops, one source.
    It is served only while that streamed value is fresh. There is NO second source:
    no REST quote, no stale stream value, no MARK/mid/close/chain/snapshot/cache/bar.
    If the stream is not delivering a fresh LAST_PRICE, spot is UNAVAILABLE
    (None, "none", None) so the failure is visible and gets fixed (operator rule,
    2026-09-23: "I would rather know that a field is not working than fallback").

    `chain_json`, `allow_stored` and `quote_node` stay on the signature for existing
    callers and are ignored."""
    _ = chain_json, allow_stored, quote_node
    tk = ticker_storage_key(ticker) or (ticker or "").upper().strip()
    if not tk:
        return None, "none", None
    spot = _lpr.live_spot(tk)             # the one rule, shared with the capture daemon
    if spot is None:
        return None, "none", None
    row = _lmp.get_quote(tk)
    return spot, SPOT_SOURCE_PLANE, (row.get("exchange_quote_ts") if row else None)


def current_spot_state(source: str, ticker: str) -> str:
    """Label resolve_spot's answer: live, stale, or unavailable. Not a second selector."""
    if source in (None, "none"):
        return "unavailable"
    if source == SPOT_SOURCE_QUOTE:
        return "live"
    if source == SPOT_SOURCE_PLANE:
        try:
            row = _lmp.get_quote(ticker)
        except Exception:
            return "stale"
        if (row and _lmp.plane_spot_is_last_price(row) and _lmp.plane_row_is_streamed(row)
                and _lmp.spot_is_fresh(row)):
            return "live"
        return "stale"
    return "unavailable"


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


class FullChainResponse:
    """The whole chain as one response: `status_code` 200 and `.json()` the merged Schwab
    payload, or the failing part's status with no payload. Callers read it exactly like the
    vendor response they used to receive."""

    def __init__(self, status_code: "int | None", payload: "dict | None" = None,
                 parts: int = 0, reason: str = "", gate_wait_sec: float = 0.0,
                 fetch_sec: "float | None" = None):
        self.status_code = status_code
        self._payload = payload
        self.parts = parts
        self.reason = reason
        #: summed over every vendor request this chain took (the gate's own measurements)
        self.gate_wait_sec = gate_wait_sec
        self.fetch_sec = fetch_sec

    def json(self) -> dict:
        return self._payload if self._payload is not None else {}


#: Vendor answers that mean "this request covers too much", not "this symbol is refused".
#: MEASURED 2026-09-25: SPY (13,290 contracts), QQQ (11,710), MU (11,204) and $SPX (29,858)
#: answered a one-shot strike_range=ALL request with HTTP 502; META (7,988) and AMD (6,628)
#: did not. No Schwab document states the limit, so none is assumed here: a refused range is
#: split and retried.
_CHAIN_TOO_BIG_CODES = (502, 413, 500, 504)
#: ticker -> how many date-range parts its whole chain last needed (learned, never guessed).
_full_chain_parts: dict[str, int] = {}
_full_chain_parts_lock = threading.Lock()


def _option_expiries(client, ticker: str) -> "list[date] | None":
    """Every listed expiry for `ticker` that has not passed (ET date), ascending; None when the
    vendor does not answer 200. MEASURED 2026-09-26 (Saturday): the expiration chain still lists
    Friday's expired 2026-09-25, and a chain request whose fromDate is in the past is refused
    with HTTP 400 ("Check Param Values") -- the same range from today answers 200."""
    resp = client.get_option_expiration_chain(ticker)
    if resp is None or resp.status_code != 200:
        return None
    today = now_et().date()
    out = sorted({d for d in (date.fromisoformat(str(e["expirationDate"])[:10])
                              for e in (resp.json().get("expirationList") or []) if e.get("expirationDate"))  # external-key-ok: Schwab expiration chain response
                  if d >= today})
    return out


def fetch_full_chain(client, ticker: str, *, priority: bool = False,
                     expiry: "date | None" = None) -> FullChainResponse:
    """EVERY strike of every listed expiry (or of the one `expiry`) -- the chain all level
    math is computed from.

    MEASURED 2026-09-25 across the 42 board tickers: levels computed from the old strike
    window (strike_count sized to +/-5% around spot, 20 strikes for most names) disagreed
    with the same code run on the full chain -- gamma flip missing for 10 tickers, max pain
    different for 16, put wall for 4, $SPX walls 3-4% apart -- while the window held only
    15-60% of each ticker's open interest. Operator decision 2026-09-25: the full chain for
    all calculations.

    One strike_range=ALL request when Schwab answers it. When the vendor answers that the
    request covers too much, the listed expiries are split into contiguous date ranges and
    each range is fetched the same way, halving any range that is itself refused; the part
    count that worked is remembered per ticker so the next call starts there. Every part must
    land: a missing part is a failed response (the reason names it), never a partial chain."""
    tk = ticker_storage_key(ticker)
    timing = {"gate": 0.0, "fetch": 0.0}

    def _get(**dates):
        resp, gate_wait, fetch_sec = _gated_safe_get_chain(client, tk, strike_range="ALL",
                                                           priority=priority, **dates)
        timing["gate"] += gate_wait or 0.0
        timing["fetch"] += fetch_sec or 0.0
        return resp, getattr(resp, "status_code", None)

    def _answer(code, payload=None, parts=0, reason=""):
        return FullChainResponse(code, payload, parts=parts, reason=reason,
                                 gate_wait_sec=round(timing["gate"], 3),
                                 fetch_sec=round(timing["fetch"], 3))

    if expiry is not None:
        resp, code = _get(from_date=expiry, to_date=expiry)
        if code != 200:
            return _answer(code, reason=f"chain for {expiry} returned HTTP {code}")
        return _answer(200, resp.json(), parts=1)

    with _full_chain_parts_lock:
        known_parts = _full_chain_parts.get(tk, 1)
    if known_parts <= 1:
        resp, code = _get()
        if code == 200:
            return _answer(200, resp.json(), parts=1)
        if code not in _CHAIN_TOO_BIG_CODES:
            return _answer(code, reason=f"full chain returned HTTP {code}")
        known_parts = 2

    expiries = _option_expiries(client, tk)
    if not expiries:
        return _answer(None, reason="expiration list unavailable")
    size = -(-len(expiries) // min(known_parts, len(expiries)))
    pending = [expiries[i:i + size] for i in range(0, len(expiries), size)]
    merged: "dict | None" = None
    done = 0
    while pending:
        part = pending.pop(0)
        resp, code = _get(from_date=part[0], to_date=part[-1])
        if code == 200:
            payload = resp.json()
            if merged is None:
                merged = payload
                merged["callExpDateMap"] = dict(payload.get("callExpDateMap") or {})
                merged["putExpDateMap"] = dict(payload.get("putExpDateMap") or {})
            else:
                merged["callExpDateMap"].update(payload.get("callExpDateMap") or {})
                merged["putExpDateMap"].update(payload.get("putExpDateMap") or {})
            done += 1
            continue
        if code in _CHAIN_TOO_BIG_CODES and len(part) > 1:
            half = len(part) // 2
            pending[:0] = [part[:half], part[half:]]
            continue
        return _answer(code, reason=(f"chain for {part[0]}..{part[-1]} returned HTTP "
                                     f"{code}; the full chain is incomplete"))
    with _full_chain_parts_lock:
        _full_chain_parts[tk] = done
    return _answer(200, merged, parts=done)







# ── Server-side state cache (avoids re-fetching everything on each poll) ─────
# UI-MAXIMIZE — panel warm list + binding SLA budgets (mirrored on /api/build + static ED_UI_MAXIMIZE_SLA_MS).
def panel_warm_tickers() -> tuple[str, ...]:
    """The tickers to pre-warm: whatever the operator is viewing (active ticker + watchlist,
    in that order). Universal -- no ticker is warmed because of its name (operator
    2026-09-23); a ticker nobody is viewing pays its first compute on first view, like any."""
    try:
        from app.options.order_flow.streaming import viewed_equity_symbols
        return tuple(viewed_equity_symbols())
    except Exception as e:  # noqa: BLE001 -- warming is best-effort; nothing is substituted
        log.warning("panel warm roster unavailable: %s", e)
        return ()
UI_MAXIMIZE_SLA_MS: dict[str, int] = {
    "first_quote": int(os.environ.get("ED_UI_SLA_FIRST_QUOTE_MS", "500")),
    "fusion_cards_panel_warm": int(os.environ.get("ED_UI_SLA_FUSION_PANEL_MS", "2000")),
    "fusion_cards_guest_cold": int(os.environ.get("ED_UI_SLA_FUSION_GUEST_MS", "15000")),
}











# ── L1 light SSE (/api/analytics/light/stream) — event-driven delivery; same payload as HTTP GET ──
_l1_light_sse_clients: list[tuple[asyncio.Queue, tuple[str, str | None]]] = []
_l1_light_sse_lock = threading.Lock()
_l1_sse_thread_queue: queue.Queue = queue.Queue(maxsize=500)
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

_recompute_leaf_executor: Optional[ThreadPoolExecutor] = None




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


_l1_sse_dispatch_executor: Optional[ThreadPoolExecutor] = None


def _get_l1_sse_dispatch_executor() -> ThreadPoolExecutor:
    """ONE thread for the L1 SSE fan-in wait -- never shared with /api/analytics/light builds,
    so a slow cold build can never hold up delivery (audit of #280)."""
    global _l1_sse_dispatch_executor
    if _l1_sse_dispatch_executor is None:
        _l1_sse_dispatch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ed_l1_sse_dispatch")
    return _l1_sse_dispatch_executor











# Tier C — background _fetch_state only; HTTP handlers never await heavy work.
_analytics_executor: Optional[ThreadPoolExecutor] = None
_analytics_bg_shutdown: bool = False
_analytics_inflight: set[tuple] = set()
_analytics_bg_lock = threading.Lock()
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None
_operator_priority_executor: Optional[ThreadPoolExecutor] = None
_priority_leaf_executor: Optional[ThreadPoolExecutor] = None
_mkt_ctx_refresh_executor: Optional[ThreadPoolExecutor] = None


def _get_analytics_executor() -> ThreadPoolExecutor:
    global _analytics_executor
    if _analytics_executor is None:
        _analytics_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="ed_analytics_bg",
        )
    return _analytics_executor




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
















































































#: a prior session with fewer 1-minute bars than this (of ~390 RTH minutes) is disclosed as
#: partial on the price levels built from it
LEVELS_PRIOR_SESSION_MIN_BARS: int = 300





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
LOGGER_BUFFER_MINS:  int   = 990    # 4:30 PM ET  (logger session buffer end)

# Re-seed the in-memory 1m grid from Schwab pricehistory (canonical OHLCV leaf
# pricehistory.candles[]) whenever the last completed bar is older than this gap.
# Root cause (2026-06-11): seeding ran once per server lifetime, so background-logged
# tickers (visited ~1×/15min) built ~6%-density tick grids — fill_outcomes could not
# find forward bars at +1/+5/+15/+60m and the daily scoreboard never scored them.



# ETF zone classification (spy_zone / qqq_zone / iwm_zone)









# Builds OHLC bars from spot price ticks. Server polls every ~30s, so:
#   5-min bars = ~10 ticks per bar
#   1-min bars = ~2 ticks per bar
# Bars are keyed by ticker. Completed bars stored in ring buffer; maxlen from math_exposure.
# ─────────────────────────────────────────────────────────────────────────────
#: one RTH day of 1-minute bars
CANDLE_1M_MAX_BARS: int = 390
from micro_structure import Candle
from timeframe_config import CANONICAL_TIMEFRAME
# Imported at MODULE LEVEL deliberately: the terrain loop's morning-window guard depends
# on these, and a runtime import inside the loop meant a missing module silently removed
# the guard during the exact 30 minutes it protects. At top level, a broken module stops
# the server AT BOOT -- loud, immediate, and impossible to trade through unnoticed. This
# also ends the fail-open/fail-closed argument (Cursor audit 2026-07-20): the runtime
# path now has no failure mode to pick a policy for.
from calibration.option_chain_morning_full import (
    MAX_DTE_DAYS as COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS,
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
from calibration.complete_chain_capture import (
    eligible_near_term_expiries,
    has_complete_chain_capture_today,
    persist_complete_chain_capture,
)




def _read_bars_1m(tk: str, limit: int) -> list:
    """The newest `limit` rows of price_bars_1m for `tk`, oldest first:
    (bar_start_ts_utc, open, high, low, close, volume)."""
    import sqlite3 as _sq
    con = _sq.connect(f"file:{get_db().db_path}?mode=ro", uri=True, timeout=10.0)
    try:
        rows = con.execute(
            "SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
            "WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT ?",
            (ticker_storage_key(tk), int(limit))).fetchall()
    finally:
        con.close()
    return list(reversed(rows))


def _bars_1m(tk: str, limit: int = CANDLE_1M_MAX_BARS) -> "list[Candle]":
    """`tk`'s completed 1-minute bars, oldest first, from price_bars_1m -- which only Schwab's
    streamed CHART_EQUITY bars write (_bar_writer). A minute the stream did not deliver is
    absent, never filled in."""
    return [Candle(ts=float(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in _read_bars_1m(tk, limit)]




def _bar_dict(c: "Candle") -> dict:
    return {"t": float(c.ts), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}


def _write_streamed_bar(msg: dict) -> bool:
    """Write one streamed 1-minute bar (Schwab CHART_EQUITY) to price_bars_1m; False when it
    lacks a field (then nothing is written)."""
    from numeric_contract import float_positive_or_none
    o, h, lo, c = (float_positive_or_none(msg.get(k)) for k in ("open", "high", "low", "close"))
    start_ms = msg.get("bar_start_ms")
    if None in (o, h, lo, c, start_ms):
        # a missing, zero, negative or non-finite price is not a price
        log.warning("streamed bar for %s lacks a valid field, not written: %s", msg.get("symbol"), msg)
        return False
    _persist_1m_bars(msg["symbol"], [Candle(ts=float(start_ms) / 1000.0, open=float(o), high=float(h),
                                            low=float(lo), close=float(c), volume=msg.get("volume"))])
    return True


def _bar_writer() -> None:
    """The price_bars_1m writer: every streamed bar the capture daemon pushes, as it arrives."""
    from app.options.order_flow.streaming import streamed_bars
    while True:
        msg = streamed_bars.get()
        try:
            _write_streamed_bar(msg)
        except Exception as e:  # noqa: BLE001 -- logged; the next bar is still written
            log.warning("streamed bar for %s not written: %s", msg.get("symbol"), e)


def start_bar_writer() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    threading.Thread(target=_bar_writer, name="bar-writer", daemon=True).start()









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

# ── No built-in ticker list (universality, operator 2026-09-23) ─────────────────
# This used to hard-code 11 "core" tickers (SPY/QQQ/IWM + 8 mega-caps) that were always
# enrolled, exempt from the collectability probe, and could not be removed. Every ticker is
# now enrolled the same way, through the logging_universe table; rows an earlier build
# wrote with category 'core' stay enrolled as ordinary rows (see the roster loaders).
CORE_TICKERS:   list[str] = []
RTH_ONLY:       bool      = True  # only log during RTH + 30min pre/post buffer



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




def _hydrate_logger_tickers_from_db() -> None:
    """Re-merge CORE + user_persisted + pinned + panel_auto from DB (startup / heal drift).
    Issue 22; panel_auto added 2026-08-25 for universal collection (RC-482/RC-483)."""
    global _logger_tickers, _LOGGING_UNIVERSE_DB_LOAD_COUNT
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
            if row.get("category") in ("user_persisted", "pinned", "panel_auto", "core"):
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
_logger_tickers:  list[str] = list(CORE_TICKERS)
_logger_running:  bool      = False
_logger_lock:     threading.Lock   = threading.Lock()



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








def _touch_tracked_ticker_view(ticker: str) -> None:
    """VIEW-path last-seen touch — TICKER-PREVIEW-NO-ENROLL (operator 2026-05-31).

    Merely looking up / viewing levels, quotes, or analytics for an arbitrary symbol must NOT
    enroll it (no ``logging_universe`` row, no scheduler user-ticker file write) — enrollment
    into the training roster is reserved for explicit track/pin actions (``/api/logger/add``,
    ``/api/logger/pin``). For an ALREADY-enrolled ticker this refreshes ``last_seen`` (the same
    update the old ``_register_tracked_ticker`` early-return branch did); for an un-enrolled
    ticker it is a no-op and never writes. Safe to call from the offloaded SSE/async paths.
    """
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










# _operator_mode_cycle_roster REMOVED 2026-08-25 (RC-493): it throttled the background
# logger to trio + one rotating guest while a viewer was connected, refreshing non-trio
# tickers only ~once per 30 min — the operator ruled universal collection unconditional, so
# the throttle is gone (see _logger_loop) rather than left as dead code (RC-474 class).


























































# ─────────────────────────────────────────────────────────────────────────────
# Phase 2A (operator 2026-08-08): `_compute_vwap_from_bars` was DELETED here.
# It was a second, independent VWAP implementation — a fallback for
# fetch_price_levels returning vwap=None — and it wrote into the snapshot table
# and from there into model features, so a persisted row could carry a VWAP that
# /api/levels never served. The one VWAP accumulation is now
# liquidity_value_engine.compute_session_vwap_path, reached only through the
# canonical PriceLevelSnapshot. Absent VWAP persists NULL (RC-68).
# ─────────────────────────────────────────────────────────────────────────────


# Last good bid-ask width (pts) when quote had both sides — reused if a poll drops one side


























































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
        item = await loop.run_in_executor(_get_l1_sse_dispatch_executor(), _blocking_get)
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
    _startup_analytics_executor()
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

    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
    asyncio.create_task(_l1_light_sse_dispatch_loop())



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
    _shutdown_analytics_executor(wait=True)
    # Live-plane feed task (reads the canonical capture daemon's DB — no Schwab socket
    # of its own to close here since single-stream-authority root fix 2026-08-30).
    try:
        from app.options.order_flow.streaming import stop_order_flow_stream

        stop_order_flow_stream(join_timeout=40.0)
    except Exception as e:
        log.warning("Order flow streaming shutdown: %s", e)

    stop_terrain_loop()
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
app.include_router(options_order_flow_router)

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

class _RevalidateStaticFiles(StaticFiles):
    """StaticFiles sends no Cache-Control at all, leaving freshness to each browser's own
    heuristic (commonly ~10% of Last-Modified age, RFC 7234). MEASURED (2026-09-11): after a
    real code change + server restart, a browser served a stale ed-gamma.js across THREE
    separate full navigations (not just a soft reload) with zero requests reaching this
    server for that file -- silent staleness a `curl` or a direct no-store fetch never
    reveals, because it only affects the browser's own normal navigation path. `no-cache`
    forces revalidation on every load (the existing ETag/Last-Modified still make an
    unchanged file a cheap 304, so this costs nothing beyond a round trip) instead of
    trusting a heuristic a shipped fix cannot control. Same reasoning already applied to
    rth_clock_authority.js above, generalized to every static asset.
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


def _with_live_ui_port(html: str) -> str:
    """Tell the page where the capture daemon's price socket listens (the same
    ED_LIVE_UI_PORT the daemon binds). An unfilled page opens no price socket -- its prices
    read UNAVAILABLE rather than reaching a daemon nobody configured it for."""
    from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT
    return html.replace(_LIVE_UI_PORT_META,
                        f'<meta name="ed-live-ui-port" content="{int(LIVE_UI_PORT)}">', 1)


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












@app.get("/api/level_crosses")
def api_level_crosses(ticker: str, n: int = 20, level_name: str | None = None,
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
#: Env override exists for TESTS ONLY (set in tests/conftest.py before any import, so a
#: lazy mid-test `import server` can never write the tracked operator audit file — the
#: class CI's ledger firewall caught 2026-08-24). Production never sets the variable.
TERRAIN_QUARANTINE_LEDGER = Path(
    os.environ.get("ED_TERRAIN_QUARANTINE_LEDGER")
    or (_artifact_reports_dir() / "terrain_quarantine_ledger.jsonl"))   # RC-523: artifacts root

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
        # RC-281: fail CLOSED on a malformed hold. `or 0.0` dated the expiry to 1970, so the
        # branch never fired, the entry was popped, and the ticker went straight back into
        # rotation — the opposite of a quarantine, reached by a missing field.
        from numeric_contract import float_finite_or_none as _fin_qb
        until = _fin_qb(e.get("until_ts"))
        if until is None or now < until:
            _terrain_quarantine_skips[tk] = _terrain_quarantine_skips.get(tk, 0) + 1
            return True
        _terrain_quarantine.pop(tk, None)      # hold expired — back into the rotation
    _quarantine_ledger_append("hold_expired", tk, {"note": "hold elapsed, retrying"})
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
                already = bool(_terrain_quarantine.get(tk, {}).get("hard"))
                next_day = (now_et() + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                                  microsecond=0)
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "hard": True,
                                           "since_ts": time.time(),
                                           "until_ts": next_day.timestamp(), "kind": kind}
                if not already:
                    log_msg = ("terrain QUARANTINE %s until the next ET day after %d hard "
                               "rejections: %s", tk, n, reason)
                    ledger = ("quarantine_hard", {"failures": n, "reason": reason,
                                                  "until_et": next_day.isoformat()})
            else:
                wait = min(TERRAIN_QUARANTINE_SOFT_MAX_SEC,
                           TERRAIN_QUARANTINE_SOFT_BASE_SEC
                           * (2 ** (n - TERRAIN_QUARANTINE_HARD_FAILS)))
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "hard": False,
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
    if had:
        _quarantine_ledger_append("cleared_by_success", tk, {})


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


def _persist_universal_capture(tk: str, key: tuple[str, str],
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
        log.info("morning full-chain capture persisted ticker=%s n=%s",
                 tk, result.get("n_contracts"))
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


def _persist_universal_complete_chain(tk: str, contracts: list,
                                      ts_utc: float | None = None) -> None:
    """Save each near-term expiry of the full chain just fetched into complete_chain_captures,
    once per ET day. Zero vendor calls: the contracts are already in hand (they come from the
    same strike_range=ALL request the capture's completeness basis names). Runs only inside the
    capture window on a trading day; `ts_utc` is the one clock read, so the "already saved
    today" check and the rows it writes agree on the ET day."""
    ts = float(ts_utc if ts_utc is not None else time.time())
    et_date, mins = gex_et_date_and_mins(ts)
    if not universal_capture_window(mins) or not is_trading_day_et(et_date):
        return
    by_expiry: dict[str, list] = {}
    for c in contracts:
        if isinstance(c, dict) and c.get("expirationDate"):
            by_expiry.setdefault(str(c["expirationDate"])[:10], []).append(c)
    db_path = get_db().db_path
    spot = None
    for expiry in eligible_near_term_expiries(set(by_expiry), now_et_date=et_date,
                                              max_dte_days=COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS):
        if has_complete_chain_capture_today(db_path, tk, expiry, et_date):
            continue
        if spot is None:
            spot = resolve_spot(tk)[0]
        result = persist_complete_chain_capture(
            db_path, ticker=tk, expiry=expiry, contracts=by_expiry[expiry], spot=spot,
            completeness_basis=COMPLETENESS_BASIS_STRIKE_RANGE_ALL, ts_utc=ts)
        if result.get("status") != "written":
            log.warning("complete-chain capture ticker=%s expiry=%s not written: %s",
                        tk, expiry, result)


#: Flip-drift measurement (unproven-register row due 2026-07-31): the mechanism is
#: proven (gamma depends on spot/IV/time) but the intraday MAGNITUDE of flip movement
#: is unmeasured. Every terrain-loop compute appends one JSONL row here so a week of
#: cycles yields per-ticker intraday min/max/range. reports/ file, not a table — the
#: operational DB grows by zero bytes (RC-6 discipline). flip=None is absence and is
#: not logged; gaps read as gaps from the timestamps.
_FLIP_DRIFT_LOG_PATH = _artifact_reports_dir() / "flip_drift_log.jsonl"   # RC-523: artifacts root
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
    hard_quarantine = bool(q_entry.get("hard"))
    if not refreshing and computed_ts_utc is not None:
        as_of = datetime.fromtimestamp(float(computed_ts_utc), tz=ZoneInfo("America/Chicago"))
        return {"levels_stale": False, "levels_age_sec": round(time.time() - float(computed_ts_utc), 1),
                "levels_refresh_active": False, "levels_market_closed": True,
                "levels_as_of": as_of.strftime("%a %m/%d %I:%M %p CT"),
                "levels_stale_reason": "", "levels_paused_on_purpose": False,
                "levels_quarantined": False, "levels_failing": False, **token}
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


#: RC-159 accrual cadence, stated rather than implied: ONE floor between writes for every
#: ticker (universality, operator 2026-09-23 -- it used to be 60s for SPY/QQQ/IWM and 300s for
#: everyone else). A FLOOR, not a schedule: the terrain loop's own cycle still governs when a
#: chain exists to bank, and a full-board cycle is longer than this floor.
ACCRUAL_MIN_INTERVAL_SEC: float = 60.0
#: Rotation depth inside the 09:30-10:00 contention window for tickers nobody is viewing: each
#: still refreshes at least once per this many seconds.
CONTENTION_ROTATION_SEC: float = 300.0
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
        floor = ACCRUAL_MIN_INTERVAL_SEC
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
    all_tickers: list[str], mins: int, cycle_n: int,
    viewed: "list[str] | None" = None,
) -> tuple[list[str], list[str]]:
    """Which tickers this cycle refreshes, and which are DEFERRED to a later cycle.

    RC-161. The morning guard used to DROP every non-sentinel for a full half hour, which made
    the accrual mandate sentinel-only in [555, 600) — a universal claim that three tickers were
    meeting. Exclusion is now ROTATION: no enrolled ticker is ever removed from the board, it is
    scheduled later within the window.

    Priority inside the window is by VIEWING DEMAND, never by symbol name (universality,
    operator 2026-09-23): the tickers the operator is looking at (`viewed` -- active ticker +
    watchlist) refresh every cycle; every other enrolled ticker rotates so it still refreshes
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


# RC-UI-1 #1: gamma-surface demand registry — the /api/options/gamma-surface endpoint marks a
# ticker "wanted" on each request; _terrain_refresh_one projects the (measurable) strike x expiry
# surface only for tickers wanted within the TTL, so unviewed tickers pay no surface cost.
_gamma_surface_demand: dict = {}
GAMMA_SURFACE_DEMAND_TTL = 300.0


def _note_gamma_surface_demand(tk: str) -> None:
    now = time.time()
    _gamma_surface_demand[tk] = now
    # opportunistic hygiene (no background thread): drop expired keys so the registry can't grow
    # unbounded from arbitrary/expired tickers.
    if len(_gamma_surface_demand) > 64:
        for _k in [k for k, ts in list(_gamma_surface_demand.items()) if now - ts >= GAMMA_SURFACE_DEMAND_TTL]:
            _gamma_surface_demand.pop(_k, None)


def _gamma_surface_wanted(tk: str) -> bool:
    return (time.time() - _gamma_surface_demand.get(tk, 0.0)) < GAMMA_SURFACE_DEMAND_TTL


#: A streamed GAMMA/DELTA/OPEN_INTEREST value older than this is not trusted AT ALL, even if
#: it is newer than the REST baseline it would override — an app-side absolute bound (not a
#: vendor-documented cadence), chosen to be well inside a stalled-feed operator would notice,
#: composed with (never a substitute for) the REST-baseline precedence check below.
GAMMA_SURFACE_STREAM_STALENESS_SEC = 10.0

#: Per-ticker counter bumped every time `_gamma_surface` is (re)published — by the REST cycle
#: or the eager stream refresh alike. Independent-review finding (2026-09-12), REPRODUCED: the
#: browser's renderSurface() skips its table rebuild when its own revision key (built from
#: chain_as_of_ts_utc/spot_as_of_ts_utc — REST-only fields) is unchanged; the eager refresh
#: changes cell VALUES without ever touching those REST fields, so a genuinely new surface
#: rendered as the old one until the next REST cycle happened to land. This counter is a
#: revision identity ANY publication bumps, REST or streamed, so the browser has something
#: that actually changes when the data does. Guarded by _terrain_cache_lock, like the cache
#: it describes.
_gamma_surface_seq: dict[str, int] = {}


def _next_gamma_surface_seq(tk: str) -> int:
    """Caller must hold _terrain_cache_lock. Also PUSHES a lightweight SSE notify -- no data of
    its own, just {ticker, surface_seq} -- to any /api/analytics/light/stream client currently
    viewing this ticker, so the browser refetches the instant a new generation publishes
    instead of waiting out the slow 3s/12s poll.

    Independent-review finding (2026-09-12): "the browser still polls every 12 seconds. The
    new Playwright test manually triggers the refresh event, bypassing that wait. It proves
    rendering after delivery, not timely delivery." True of the prior commit: surface_seq made
    a change DETECTABLE once the browser next asked, but nothing made it ASK sooner. This
    reuses the EXISTING SSE connection/queue/dispatch pipe wholesale
    (_l1_put_thread_queue_notify -> _l1_light_sse_dispatch_loop -> the /api/analytics/light/
    stream generator, which now picks the wire event name from the envelope instead of
    hardcoding "l1_projection") -- no second SSE endpoint, connection, or daemon. Best-effort:
    a failed push here still leaves surface_seq bumped and the slow poll as an honest fallback
    (SSE down/stalled already falls back to polling on the client)."""
    n = _gamma_surface_seq.get(tk, 0) + 1
    _gamma_surface_seq[tk] = n
    try:
        _l1_put_thread_queue_notify(
            (tk, "__auto__"),
            {"_sse_event_name": "gamma_surface_seq", "scope": {"ticker": tk}, "surface_seq": n},
        )
    except Exception as e:  # institutional-swallow-ok: push notify is best-effort; poll fallback still exists
        log.debug("gamma_surface_seq SSE notify failed for %s: %s", tk, e)
    return n


def _desired_stream_greeks_for_ticker(tk: str) -> dict:
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

    Native contract identity uses app.options.order_flow.streaming.contract_matches_underlying
    (chain-aware: a vendor root that genuinely differs from the ticker's own root, e.g.
    Schwab's $SPX -> SPXW weekly, is still recognized via the nearest banked complete chain) —
    independent-review finding (2026-09-12): a bare vendor-root == ticker-root equality check
    silently excludes exactly this legitimate case."""
    from app.options.order_flow.state import get_stream_greeks
    out: dict = {}
    for sym in _desired_option_symbols_for_ticker(tk):
        greeks = get_stream_greeks(sym)
        if greeks:
            out[sym] = greeks
    return out


def _desired_option_symbols_for_ticker(tk: str) -> "list[str]":
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
        get_active_option_contract, get_active_option_contracts, contract_matches_underlying)
    out: "list[str]" = []
    candidates = list(get_active_option_contracts())
    primary = get_active_option_contract()
    if primary:
        candidates.append(primary)
    for sym in candidates:
        if sym and sym not in out and contract_matches_underlying(sym, tk):
            out.append(sym)
    return out


def _option_contract_admission_summary(tk: str) -> dict:
    """Per-symbol admitted/observed/active/pending/rejected accounting for `tk`'s desired
    option contracts, sourced ENTIRELY from PRODUCER acknowledgements (2026-09-16,
    independent-review follow-up mandate item 1: "expose the exact admitted, active,
    pending and rejected contracts"). Every bucket answers a materially different
    question about a desired symbol:
      'active'   — has produced a tick WITHIN the canonical staleness window
                   (GAMMA_SURFACE_STREAM_STALENESS_SEC, the SAME bound
                   overlay_streamed_contract_fields/the 'live' cell state already use) —
                   freshness-gated, not merely "has ever ticked". A symbol whose only
                   observation is older than this window is 'observed', not 'active':
                   correctness finding (2026-09-17) — a harness or UI claiming a stale
                   historical observation is "currently active" is exactly the false-
                   success shape the operator's own negative controls exist to catch.
      'observed' — has produced at least one real tick EVER (present in
                   _desired_stream_greeks_for_ticker's own output) but that tick is
                   OLDER than the staleness window — the vendor genuinely sent data at
                   some point; it is not necessarily still fresh right now.
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
    daemon_available = is_option_producer_daemon_available()
    rejected_all = read_producer_rejected_option_contracts()
    admitted_l1 = set((read_producer_admitted_option_contracts() or {}).get("LEVELONE_OPTIONS") or [])
    streamed = _desired_stream_greeks_for_ticker(tk)
    now = time.time()
    admitted, active, observed, pending = [], [], [], []
    rejected: "dict[str, str]" = {}
    for sym in desired:
        if sym in rejected_all:
            rejected[sym] = rejected_all[sym]
        elif sym in streamed:
            ts_recv = _leg_stream_ts_recv(streamed.get(sym))
            if ts_recv is not None and (now - ts_recv) <= GAMMA_SURFACE_STREAM_STALENESS_SEC:
                active.append(sym)
            else:
                observed.append(sym)
        elif sym in admitted_l1:
            admitted.append(sym)
        elif daemon_available:
            pending.append(sym)
        # else: daemon unavailable -- genuinely unknown, omitted from every bucket
    # Requested by the view but left out by the shared Schwab socket's budget
    # (stream_spine.OPTION_CONTRACTS_MAX_HELD): a capacity decision, reported as itself --
    # never as pending (it is not coming) nor as a vendor rejection (the vendor never saw it).
    from app.options.order_flow.streaming import (
        contract_matches_underlying, get_option_contracts_over_budget)
    not_admitted = sorted(s for s in get_option_contracts_over_budget()
                          if contract_matches_underlying(s, tk))
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


def _gamma_surface_contracts_with_stream_overlay(
        tk: str, contracts: list, *, newer_than_ts: float | None = None) -> tuple[list, int, list[str]]:
    """Overlay EVERY currently-streaming option contract's freshest known GAMMA/DELTA/
    OPEN_INTEREST/VOLUME onto `contracts` before projection, for whichever of them
    belong to `tk` (RC-UI-3: primary AND every additional contract — see
    _desired_stream_greeks_for_ticker).

    Still the ONE canonical faucet (project_gamma_surface -> compute_exposures_by_strike,
    RC-UI-1): this changes no formula and adds no second producer, it only lets those
    fields be fresher than the REST chain snapshot they arrived in.

    `newer_than_ts`, when given, is passed straight through as the REST-baseline precedence
    bound (see overlay_streamed_contract_fields) — independent-review finding (2026-09-12):
    "being received within ten seconds does not establish that a stream value is newer than
    the REST input it replaces."

    Fails closed to the unmodified `contracts` on any error or when nothing applies — this is
    a best-effort freshening, never a precondition for the projection to run at all."""
    try:
        from math_exposure_core import overlay_streamed_contract_fields

        streamed = _desired_stream_greeks_for_ticker(tk)
        if not streamed:
            return contracts, 0, []
        overlaid, n = overlay_streamed_contract_fields(
            contracts, streamed,
            newer_than_ts=newer_than_ts, max_staleness_sec=GAMMA_SURFACE_STREAM_STALENESS_SEC)
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
    REST-precedence + GAMMA_SURFACE_STREAM_STALENESS_SEC check for this specific symbol — reused
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
            if not leg_states:
                cell_state = "unavailable"
            elif all(s == "live" for s in leg_states):
                cell_state = "live"
            elif any(s == "live" for s in leg_states):
                cell_state = "partial"
            elif any(s == "stale" for s in leg_states):
                cell_state = "stale"
            elif any(s == "pending" for s in leg_states):
                cell_state = "pending"
            elif any(s == "daemon_unavailable" for s in leg_states):
                cell_state = "daemon_unavailable"
            elif any(s == "rejected" for s in leg_states):
                cell_state = "rejected"
            elif any(s == "not_admitted" for s in leg_states):
                cell_state = "not_admitted"
            else:
                cell_state = "unavailable"
            legs["state"] = cell_state
            state_row.append(legs)
        cell["stream"] = state_row


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
#: option contract symbol -> the cached ticker it belongs to (found once per symbol)
_option_ticker: "dict[str, str]" = {}


def _levels_lock(tk: str) -> threading.Lock:
    with _levels_locks_guard:
        return _levels_locks.setdefault(tk, threading.Lock())


def _publish_levels(tk: str, chain: "list | None" = None,
                    fetched_ts: "float | None" = None) -> "TerrainSnapshot | None":
    """THE producer of a ticker's levels, per-strike rows and gamma-surface grid.

    Prices the ticker's chain once -- overlaid with any fresher streamed option greeks, at the
    current spot -- and publishes all three together, so the heatmap, Strike Detail and Key
    Levels always show one computation. The terrain loop passes a newly fetched chain; a tick on
    a viewed ticker passes none and the kept chain is repriced. One call at a time per ticker:
    each publication is computed from inputs read after the one it replaces. Returns the
    snapshot, or None when there is no chain to price."""
    from math_exposure_core import overlay_streamed_contract_fields
    from app.options.order_flow.streaming import (
        read_producer_rejected_option_contracts, is_option_producer_daemon_available)
    with _levels_lock(tk):
        with _terrain_cache_lock:
            payload = dict(_terrain_cache.get(tk) or {})
        if chain is None:
            chain, fetched_ts = payload.get("_chain"), payload.get("_chain_fetched_ts")
            if not chain:
                return None
        spot, spot_source, spot_ts = resolve_spot(tk)
        prev_spot = payload.get("spot")
        streamed = _desired_stream_greeks_for_ticker(tk)
        priced, n_live = overlay_streamed_contract_fields(
            chain, streamed, newer_than_ts=fetched_ts,
            max_staleness_sec=GAMMA_SURFACE_STREAM_STALENESS_SEC)
        live_syms = _overlaid_symbols(chain, priced)
        snap = compute_terrain(tk, priced, spot)
        payload.update(snap.to_dict())
        viewed = _gamma_surface_wanted(tk)
        payload.update({
            "computed_ts_utc": time.time(), "levels_source": LEVELS_SOURCE_WIDE_CHAIN,
            "chain_basis": "full", "spot_source": spot_source, "spot_as_of_ts_utc": spot_ts,
            "_per_strike": snap.per_strike, "_gamma_surface": None,
            "_vanna_rows": _vanna_rows(snap), "_charm_rows": _charm_rows(snap),
            # only a viewed ticker is repriced between chain fetches, so only its chain is kept
            "_chain": chain if viewed else None, "_chain_fetched_ts": fetched_ts,
        })
        if viewed and spot and snap.books:
            surface = project_gamma_surface(priced, snap.books)
            surface.update(spot=float(spot), spot_source=spot_source, spot_as_of_ts_utc=spot_ts,
                           stream_overlay_contracts=n_live, stream_overlay_symbols=live_syms,
                           stream_overlay_computed_ts_utc=payload["computed_ts_utc"])
            _stamp_gamma_surface_cell_stream_state(
                surface, streamed, set(live_syms), read_producer_rejected_option_contracts(),
                set(_desired_option_symbols_for_ticker(tk)),
                daemon_available=is_option_producer_daemon_available())
            payload["_gamma_surface"] = surface
        with _terrain_cache_lock:
            if payload["_gamma_surface"] is not None:
                payload["_gamma_surface"]["surface_seq"] = _next_gamma_surface_seq(tk)
            _terrain_cache[tk] = payload
            _terrain_profile_cache[tk] = snap.profile
        _save_session_levels(tk, payload, snap.profile)
        _log_level_crosses(tk, prev_spot, snap)
        return snap


#: the levels whose crossing by spot is recorded, with their display names
CROSS_LEVELS = (("call_wall", "Call g-Wall"), ("put_wall", "Put g-Wall"), ("gamma_flip", "Gamma Flip"),
                ("net_gex_peak", "Net Γ peak"), ("max_pain", "Max Pain"),
                ("call_delta_wall", "Call d-Wall"), ("put_delta_wall", "Put d-Wall"))


def _log_level_crosses(tk: str, prev_spot: "float | None", snap: "TerrainSnapshot") -> None:
    """Record each level spot moved through between the previous publication and this one."""
    levels = [(getattr(snap, k), name) for k, name in CROSS_LEVELS if getattr(snap, k) is not None]
    now = time.time()
    get_db().detect_and_log_level_crosses(
        ticker=tk, prev_spot=prev_spot, cur_spot=snap.spot, levels=levels, ts_utc=now,
        ts_et=now_et().strftime("%Y-%m-%d %H:%M:%S ET"))


#: The last levels each ticker published while the market was open, one JSON file per ticker:
#: what the screen shows while the market is closed and after a restart then.
SESSION_LEVELS_DIR = data_dir() / "session_levels"


def _save_session_levels(tk: str, payload: dict, profile: list) -> None:
    """Write `tk`'s published payload (without the kept raw chain) and gamma profile."""
    path = SESSION_LEVELS_DIR / f"{tk.replace('$', '_')}.json"
    body = {k: v for k, v in payload.items() if k != "_chain"}
    SESSION_LEVELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"payload": body, "profile": profile}), encoding="utf-8")
    os.replace(tmp, path)


def _load_session_levels() -> int:
    """Put every saved ticker's last published levels into the cache; returns how many. Their
    heatmap cells are marked not streaming -- nothing streamed them since they were saved."""
    n = 0
    for path in sorted(SESSION_LEVELS_DIR.glob("*.json")) if SESSION_LEVELS_DIR.exists() else []:
        saved = json.loads(path.read_text(encoding="utf-8"))
        payload = saved["payload"]
        tk = payload["ticker"]
        if payload.get("_gamma_surface"):
            _stamp_gamma_surface_cell_stream_state(payload["_gamma_surface"], {}, set(), {}, set())
        with _terrain_cache_lock:
            _terrain_cache[tk] = payload
            _terrain_profile_cache[tk] = saved["profile"]
        n += 1
    return n


def _vanna_rows(snap: "TerrainSnapshot") -> list:
    """[strike, net dealer vanna] for every strike with open interest, from the published book:
    net_vanna = call_vanna - put_vanna (+call/-put dealer convention)."""
    from math_exposure_core import merge_exposure_books
    from numeric_contract import float_finite_or_none as _fin
    exposures, _diag = merge_exposure_books(snap.books.values())
    rows = []
    for k, b in exposures.items():
        # call_vanna/put_vanna start as a real 0.0 in every bucket; has_oi is the gate
        if not b.get("has_oi"):
            continue
        cv, pv = b.get("call_vanna"), b.get("put_vanna")
        if cv is None and pv is None:
            continue
        net = _fin(cv or 0.0) - _fin(pv or 0.0) if (_fin(cv) is not None or _fin(pv) is not None) else None
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
    tk = _option_ticker.get(sym)
    if tk is None:
        from app.options.order_flow.streaming import contract_matches_underlying
        with _terrain_cache_lock:
            keys = list(_terrain_cache)
        tk = next((k for k in keys if contract_matches_underlying(sym, k)), None)
        if tk is not None:
            _option_ticker[sym] = tk
    return tk


def _on_stream_tick(sym: str) -> None:
    """Called by the live feed, on the event loop, for every streamed equity quote and every
    option quote carrying greeks, open interest or volume. Queues a reprice of the symbol's
    ticker when someone is viewing it, and returns at once."""
    tk = _tick_ticker(sym)
    if not tk or not _gamma_surface_wanted(tk) or not _is_loggable_session():
        return
    with _reprice_guard:
        _reprice_dirty.add(tk)
        if tk in _reprice_running:
            return
        _reprice_running.add(tk)
    threading.Thread(target=_reprice_worker, args=(tk,), name=f"reprice-{tk}", daemon=True).start()


def _reprice_worker(tk: str) -> None:
    """Reprice `tk` while ticks keep arriving, at most once per LEVELS_REPRICE_MIN_INTERVAL_SEC;
    the last tick of a burst is always priced."""
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
            _publish_levels(tk)
        except Exception as e:  # noqa: BLE001 -- logged; the next tick or chain fetch reprices
            log.warning("levels reprice failed for %s: %s", tk, e)


def _ticker_on_terrain_board(tk: str) -> bool:
    # canonical current board membership (the terrain loop's universe = the logger cycle set +
    # core), read under the existing lock — NOT a new registry, and NOT merely "a snapshot exists".
    with _logger_lock:
        return tk in _logger_tickers or tk in CORE_TICKERS


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
    if not _is_loggable_session():
        # market closed: the saved last-session levels stand (weekend chains blank open
        # interest -- measured 2026-09-26: every $SPX contract, 18% of SPY's OI)
        if terrain_cache_get(tk) is None:
            _terrain_refresh_last_error[tk] = "market closed; no levels were saved from the last session"
        return "skip:market_closed"
    if _terrain_quarantine_blocks(tk):
        return "skip:quarantined"
    try:
        client = get_client()
        want_capture, cap_key = _universal_capture_wanted(tk)
        # The FULL chain -- every strike of every listed expiry (fetch_full_chain; operator
        # decision 2026-09-25 after the strike window was measured disagreeing with it).
        resp = fetch_full_chain(client, tk, priority=priority)
        if resp.status_code != 200:
            _code = resp.status_code
            _msg = f"chain fetch failed ({resp.reason or f'HTTP {_code}'})"
            _terrain_refresh_last_error[tk] = _msg
            # RC-148: classify so the response fits the cause. A 4xx is the vendor refusing THIS
            # SYMBOL and will refuse it identically forever; a 5xx is the venue being busy and
            # deserves a backoff, not a death sentence.
            _note_terrain_failure(tk, _msg, _classify_chain_failure(_code, None))
            return "error:chain_http"
        fetched_ts = time.time()   # the chain's as-of: an older streamed value never overrides it
        contracts = flatten_chain_contracts(resp.json())
        if want_capture and contracts:
            _persist_universal_capture(tk, cap_key, contracts, resolve_spot(tk)[0])
        if contracts:
            _persist_universal_complete_chain(tk, contracts)
        snap = _publish_levels(tk, contracts, fetched_ts)
        _atr = _atr_pair(tk)
        with _terrain_cache_lock:
            payload = _terrain_cache[tk]
            payload.update(atr_daily=round(_atr.daily, 3) if _atr.daily else None,
                           atr_15m=round(_atr.m15, 3) if _atr.m15 else None)
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
        # it always classifies soft — backoff, never a hard hold. A crash in our own code
        # must not be able to evict a real instrument from the board.
        _note_terrain_failure(tk, f"{type(e).__name__}: {e}", "soft")
        log.warning("terrain refresh %s failed: %s", tk, e, exc_info=True)
        return f"error:{type(e).__name__}"


def _terrain_loop() -> None:
    log.info("Terrain loop started (levels only, no model stack)")
    _terrain_cycle_n = 0        # RC-161: drives the morning rotation; monotonic per loop
    while _terrain_loop_running:
        cycle_start = time.monotonic()
        tickers: list[str] = []
        try:
            with _logger_lock:
                tickers = list(_logger_tickers)
        except Exception:
            tickers = list(CORE_TICKERS)
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
        # the pre-enrolled board. A snapshot of the keys, never the live dict, since
        # another thread's concurrent _note_gamma_surface_demand write must not raise
        # "dictionary changed size during iteration" here.
        _viewed_now = [tk for tk in list(_gamma_surface_demand.keys()) if _gamma_surface_wanted(tk)]
        _previewed = [tk for tk in _viewed_now if tk not in tickers]
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
        if _is_loggable_session():
            # During the morning wide-chain window (09:30-10:00 ET) SPY/QQQ/IWM already
            # take 100-strike gated fetches on the money path. Do not pile a full-universe
            # terrain sweep on top of that — refresh sentinels only until the window ends.
            # No try/except: the imports are module-level, so this path cannot fail at
            # runtime — a missing module stops the server at boot instead.
            _d, _mins = gex_et_date_and_mins()
            _terrain_cycle_n += 1
            _all_this_cycle = list(tickers)
            try:
                from app.options.order_flow.streaming import viewed_equity_symbols as _viewed_fn
                _viewed_syms = _viewed_fn()
            except Exception:  # noqa: BLE001 -- no viewing signal: every ticker rotates alike
                _viewed_syms = []
            tickers, _dropped = terrain_cycle_tickers(_all_this_cycle, _mins, _terrain_cycle_n,
                                                      viewed=_viewed_syms)
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
            if _previewed:
                # Previewed tickers are a deliberate, ad-hoc operator action (someone typed
                # or clicked a ticker outside the enrolled board) -- they bypass
                # terrain_cycle_tickers' morning-contention throttle (built for the
                # enrolled board's own chain-slot budget) rather than being silently
                # dropped by a mechanism that was never about them.
                tickers = tickers + [tk for tk in _previewed if tk not in tickers]
            with concurrent.futures.ThreadPoolExecutor(max_workers=TERRAIN_WORKERS) as pool:
                list(pool.map(_terrain_refresh_one, tickers))
        else:
            tickers = []
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


#: RC-69 — BAR COLLECTION SERVICE. Collection is not a side-effect of display.
#: Bars used to be written only inside _fetch_state (the render path), so a ticker's chart
#: decayed to whenever it was last LOOKED AT. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar
#: lag 3.1 min vs QQQ 19.1 and IWM 19.1 (off screen) — while all three had ~1.0 min SNAPSHOT lag.
#: The quotes were current; the bars were not. 39.8% of all snapshots (122,795/308,796) carry
#: unfilled outcomes because fill_outcomes reads price_bars_1m for the forward price and the bars
#: were never written. This loop mirrors _terrain_loop (RC-1), which solved the identical problem
#: for levels: a cheap, always-on, viewport-independent path over the WHOLE enrolled universe.
def _persist_1m_bars(tk: str, bars) -> int:
    """THE single price_bars_1m writer in server.py (RC-69 single-faucet contract).

    Called only by _bar_writer with Schwab's streamed bars; the audit counts the literal
    db-write call, so the invariant is that this function is its only occurrence."""
    return get_db().upsert_1m_bars(tk, bars)


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
    log.info("session levels loaded for %d tickers", _load_session_levels())
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
    """The ticker's (daily, 15-minute) ATR from price_bars_1m, recomputed at most every
    ATR_TTL_SEC. Too few bars reads as None, never a vendor stand-in."""
    tk = ticker_storage_key(ticker)
    with _atr_lock:
        hit = _atr_cache.get(tk)
    if hit is not None and time.time() - hit[0] < ATR_TTL_SEC:
        return hit[1]
    pair = compute_atr_pair(str(get_db().db_path), tk)
    with _atr_lock:
        _atr_cache[tk] = (time.time(), pair)
    return pair










#: WHICH producer computed a set of levels. The radar deliberately merges two of them, and an
#: unlabelled merge is how systematically-different numbers get ranked as peers (RC-82).
LEVELS_SOURCE_WIDE_CHAIN = "wide_chain_loop"      # _terrain_refresh_one, the single producer


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
        out = dict(payload)
        out["spot"] = None
        out["spot_source"] = "none"
        out["spot_state"] = "unavailable"
        out["spot_as_of_ts_utc"] = None
        out["spot_disp"] = "UNAVAILABLE"
        return out

    out = dict(payload)
    out["spot"] = spot
    out["spot_source"] = spot_source
    out["spot_state"] = current_spot_state(spot_source, ticker)
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


# ── CR-03 screen 1 — per-strike gamma/volume bars for the histogram panel ────
# Feeds the /chart sidebar: today's per-strike dealer gamma + traded volume, plus
# the PRIOR wide capture's bars (the day-over-day migration ghosts), each in three
# expiry scopes (all / near<=7DTE / far). Sources are STORED chains only (wide
# morning capture preferred, live narrow chain as fallback) — read-only, no Schwab
# call, no model stack. Bar heights use the same exposure math as terrain.
@app.get("/api/terrain/strikes")
def get_terrain_strikes(ticker: str = Query(...)):
    from math_exposure_core import compute_exposures_by_strike as _cebs

    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    # Operator-reproduced defect (2026-09-14, "the collection schedule must not block live
    # viewing"): _note_gamma_surface_demand was only ever called from
    # get_options_gamma_surface (the Heatmap grid's own route) -- GEX-by-Strike, the
    # Positioning Migration panel, and the Chart view all read THIS route instead and never
    # registered that anyone was watching. A ticker viewed only through one of those three
    # screens could never reach _terrain_loop's `_previewed` set, so it never got a live
    # refresh attempt regardless of enrollment. Every screen that shows this ticker's live
    # terrain-derived data must register the same demand signal, not just one of them.
    _note_gamma_surface_demand(tk)

    def _per_strike(contracts: list, spot: float) -> dict:
        def _scope(cts: list) -> list:
            if not cts:
                return []
            exposures, _diag = _cebs(cts, spot=spot, require_oi=True)
            # ONE producer (2026-09-24): this was a second copy of terrain_engine._per_strike_rows
            # carrying the same raw-gamma fallback (audit T-01) -- the live panel and this ghost
            # must be one computation or they draw a positioning shift that did not happen.
            from terrain_engine import _per_strike_rows
            return _per_strike_rows(exposures, cts)

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
                prior = _per_strike(decode_json_blob(c1), float(s1))
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
def get_bars1m(ticker: str = Query(...),
               limit: int = Query(default=780, ge=1, le=12000),
               tf: str = Query(default="1", pattern=r"^(1|3|5|15|30|60|D)$")):
    """Canonical 1m bars, newest-last: [{t,o,h,l,c,v}] epoch-seconds bar starts. `tf` rolls
    them up server-side (aggregate_bars) -- the chart page used to aggregate in the browser."""
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    bars = [_bar_dict(c) for c in _bars_1m(tk, int(limit))]
    out = aggregate_bars(overlay_forming_bar_from_plane(bars, tk), tf)
    return JSONResponse({"ticker": tk, "bars": out, "tf": tf, "n": len(out)})


def aggregate_bars(bars: list[dict], tf: str) -> list[dict]:
    """THE chart-timeframe roll-up of 1m bars ("1", "3", "5", "15", "30", "60" minutes, or "D" =
    the ET trading date): first open, max high, min low, last close. Volume is the sum only
    when every minute in the bucket reported one -- otherwise None (unknown), never a partial
    sum or a 0. A bucket holding the forming minute is itself forming."""
    if tf == "1":
        return list(bars)
    from time_et import ET
    step = None if tf == "D" else int(tf) * 60

    def key(t: float):
        return datetime.fromtimestamp(t, ET).date() if step is None else int(t // step)

    out: list[dict] = []
    cur: dict | None = None
    cur_key = None
    for b in bars:
        k = key(float(b["t"]))
        if cur is None or k != cur_key:
            if cur is not None:
                out.append(cur)
            cur = {"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b.get("v")}
            if b.get("forming"):
                cur["forming"] = True
            cur_key = k
            continue
        cur["h"] = max(cur["h"], b["h"])
        cur["l"] = min(cur["l"], b["l"])
        cur["c"] = b["c"]
        cur["v"] = None if (cur["v"] is None or b.get("v") is None) else cur["v"] + b["v"]
        if b.get("forming"):
            cur["forming"] = True
    if cur is not None:
        out.append(cur)
    return out


def overlay_forming_bar_from_plane(bars: list[dict], ticker: str) -> list[dict]:
    """`bars` with the forming minute from the live price plane (live_price_rows.forming_bar:
    streamed LAST_PRICE placed on its own trade minute) appended or merged."""
    forming = _lpr.forming_bar(ticker)
    return list(bars) if forming is None else _merge_forming_bar(list(bars), forming)


def _merge_forming_bar(bars: list[dict], forming: dict) -> list[dict]:
    bar_t = float(forming["t"])
    out = [dict(b) for b in bars]
    if out and float(out[-1]["t"]) == bar_t:
        last = out[-1]
        last["c"] = forming["c"]
        if last.get("h") is not None:
            last["h"] = max(float(last["h"]), float(forming["h"]))
        else:
            last["h"] = forming["h"]
        if last.get("l") is not None:
            last["l"] = min(float(last["l"]), float(forming["l"]))
        else:
            last["l"] = forming["l"]
        last["forming"] = True
        out[-1] = last
        return out
    if out and float(out[-1]["t"]) > bar_t:
        return out
    out.append(dict(forming))
    return out


@app.get("/api/options/vanna-by-strike")
def get_vanna_by_strike(ticker: str = Query(...)):
    """Per-strike dealer VANNA exposure from the published levels (net_vanna = call_vanna -
    put_vanna, aggregated across every expiry; no per-expiry surface yet)."""
    tk = ticker_storage_key(_required_ticker(ticker))
    _touch_tracked_ticker_view(tk)
    payload = terrain_cache_get(tk) or {}
    if "_vanna_rows" not in payload:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no levels published for this ticker yet"})
    return JSONResponse({"ticker": tk, "available": True, "spot": payload.get("spot"),
                         "rows": payload["_vanna_rows"], "levels_as_of": payload.get("levels_as_of"),
                         "method": "the published levels' exposure book -> call_vanna - put_vanna"})


@app.get("/api/options/charm-by-strike")
def get_charm_by_strike(ticker: str = Query(...)):
    """Per-strike dealer CHARM exposure from the published levels' charm map (the charm walls'
    own): net_charm = call_charm - put_charm per strike, delta-shares/day."""
    tk = ticker_storage_key(_required_ticker(ticker))
    _touch_tracked_ticker_view(tk)
    payload = terrain_cache_get(tk) or {}
    if "_charm_rows" not in payload:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no levels published for this ticker yet"})
    rows = payload["_charm_rows"]
    return JSONResponse({"ticker": tk, "available": bool(rows), "spot": payload.get("spot"),
                         "rows": rows, "levels_as_of": payload.get("levels_as_of"),
                         "reason": None if rows else "charm_by_strike produced no usable strikes for this chain",
                         "method": "the published levels' charm map -> call_charm - put_charm"})


@app.get("/api/options/tape")
def get_options_tape(ticker: str = Query(...),
                     contract: Optional[str] = Query(default=None),
                     limit: int = Query(default=100)):
    """Discrete option TRADE prints (operator field-inventory audit, 2026-09-13) — the
    Options Flow tape, locked to the operator's own required schema: Time/Symbol/Expiry/
    Type/Strike/Bid x Size/Ask x Size/Trade/Size/Premium/Volume/OI/IV/Delta/provenance.
    Sourced from app.options.order_flow.history.tape_rows_for_symbol, which reads the
    ALREADY-CAPTURED native LEVELONE_OPTIONS ticks in stream_options_quotes_raw verbatim —
    no new capture, no derived/estimated field, no fabricated buy/sell aggressor side.

    `contract`, when given, scopes to exactly that vendor symbol. Otherwise scopes to every
    CURRENTLY DESIRED contract for `ticker` (the primary + additional option contracts the
    operator has actually selected — the same identity `_desired_stream_greeks_for_ticker`
    already resolves for the gamma-surface overlay), merged newest-first and capped at
    `limit` across the whole merge, not per-contract."""
    from app.options.order_flow.streaming import (
        get_active_option_contract, get_active_option_contracts, contract_matches_underlying)
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
            if sym and sym not in seen and contract_matches_underlying(sym, tk):
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
        "reason": None if rows else "no trade prints captured yet for the selected contract(s)",
        "method": ("stream_options_quotes_raw (native LEVELONE_OPTIONS capture, already "
                   "retained) -> tape_rows_for_symbol (de-duplicated genuine trade prints, "
                   "context carried forward) -> merged newest-first across every currently "
                   "desired contract for this ticker"),
    })


@app.get("/api/order-flow/book-heatmap")
def get_order_flow_book_heatmap(ticker: str = Query(...),
                                minutes: float = Query(default=60.0)):
    """Historical book-depth heatmap for the underlying ticker's own NASDAQ/NYSE book (operator
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
    payload = book_heatmap_for_ticker(tk, minutes=bounded_minutes)
    return JSONResponse(payload)


#: RC-192/RC-199 FORCES (RE-LANDED 2026-08-02 after a worktree reset destroyed the
#: uncommitted originals — RC-210): ΔOI/DEX from the two newest banked wide chains; the
#: strip's GEX/OV rows come from the live strikes payload client-side; ΔOI and DEX need the
#: two newest wide captures, which only the server can read.
_FORCES_CACHE: dict = {}


@app.get("/api/forces")
def get_forces(ticker: str = Query(...)):
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

    tk = ticker_storage_key(_required_ticker(ticker))
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
            per1 = _cebs(decode_json_blob(c1), spot=float(s1))[0]
            per0 = _cebs(decode_json_blob(c0), spot=float(s0))[0]

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
                chain1 = decode_json_blob(c1)
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
                "doi_below": round(sum(d for k, d in doi.items() if k < spot1)),
                "doi_above": round(sum(d for k, d in doi.items() if k > spot1)),
                "dex_below_dollars": round(sum(d for k, d in dex1.items() if k < spot1)),
                "dex_above_dollars": round(sum(d for k, d in dex1.items() if k > spot1)),
                "strikes_diffed": len(doi),
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
def get_exposure_flow(ticker: str = Query(...)):
    """RC-208: serve option_chain_accrual frames for the latest banked session so the
    Exposure tab paints per-minute Pika/Barney structure, the intraday King path, and
    volume-delta bubbles at the minute they happened. per_strike_json served verbatim
    ([[strike, gex_dollars, session_volume], ...]; MEASURED: SPY 07-31 = 133 frames, ET
    minutes 556-975), spot-windowed ±5%. 5-min cache like /api/forces."""
    import sqlite3 as _sq

    tk = ticker_storage_key(_required_ticker(ticker))
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
    dex = _bf(bucket.get("net_dex_dollars")) if _has_gex_data else None
    _vn = bucket["call_vanna"] - bucket["put_vanna"] if _has_gex_data else None
    vanna = round(_vn, 2) if _vn is not None else None
    call_oi, put_oi = (bucket or {}).get("call_oi"), (bucket or {}).get("put_oi")
    oi = {"call": _bf(call_oi), "put": _bf(put_oi)} if bucket is not None else {"call": None, "put": None}
    call_vol, put_vol = (bucket or {}).get("call_volume"), (bucket or {}).get("put_volume")
    volume = {"call": _bf(call_vol), "put": _bf(put_vol)} if bucket is not None else {"call": None, "put": None}
    contracts = {"call": syms.get("call"), "put": syms.get("put")}
    return gex, dex, vanna, oi, volume, contracts, _has_gex_data, _has_oi


def project_gamma_surface(chain: list, books: dict) -> dict:
    """The strike × expiry grid the gamma heatmap draws, shaped from `books` -- the
    exposure_books compute_terrain priced `chain` into, so every cell is the number the levels
    and per-strike rows were computed from. No exposure math here. A contract with a missing
    or malformed expiry is counted, never given a column."""
    from math_exposure_core import merge_exposure_books
    from numeric_contract import float_finite_or_none

    chain = chain if isinstance(chain, list) else []
    by_expiry: "dict[str, list]" = {}
    for (exp, _dte), book in (books or {}).items():
        if len(exp) == 10:
            by_expiry.setdefault(exp, []).append(book)
    per_expiry = {e: (bs[0][0] if len(bs) == 1 else merge_exposure_books(bs)[0])
                  for e, bs in by_expiry.items()}
    exp_dte: "dict[str, int | None]" = {}
    # the vendor OSI symbol behind each (strike, expiry) leg, so the browser can ask the stream
    # for exactly the contracts it is showing
    symbols_by_expiry: "dict[str, dict[float, dict[str, str]]]" = {}
    contracts_used = 0
    for ct in chain:
        e = str((ct or {}).get("expirationDate") or "")[:10]
        if e not in per_expiry:
            continue
        contracts_used += 1
        if exp_dte.get(e) is None:   # native DTE for the column header, never inferred
            try:
                exp_dte[e] = int(ct.get("daysToExpiration"))
            except (TypeError, ValueError):
                exp_dte[e] = None
        side = (ct.get("putCall") or "").upper()
        sym = ct.get("symbol")
        k = float_finite_or_none(ct.get("strikePrice"))
        if sym and side in ("CALL", "PUT") and k is not None:
            symbols_by_expiry.setdefault(e, {}).setdefault(k, {})[side.lower()] = str(sym)
    total_contracts = len(chain)
    excluded_malformed = total_contracts - contracts_used
    strike_set = {float(k) for ex in per_expiry.values() for k in ex}
    expiries = sorted(per_expiry)
    strikes = sorted(strike_set)
    expirations = [{"expiry": e, "dte": exp_dte.get(e)} for e in expiries]
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
    expiration columns have already expired relative to today. Presentation reads these flags to
    label an expired 0DTE column and a prior-session reference for what they are; it never infers
    them. No cell value is touched."""
    today = now_et().strftime("%Y-%m-%d")      # time_et: the ONE ET clock / session-calendar authority
    out = dict(surface)
    out["expirations"] = [
        dict(e, expired=bool(e.get("expiry") and str(e["expiry"]) < today))
        for e in (surface.get("expirations") or [])
    ]
    out["session_date_et"] = today
    out["prior_session"] = bool(reference_date and str(reference_date) < today)
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
    _note_gamma_surface_demand(tk)   # mark viewed -> the terrain loop will project this ticker's surface

    # ---- LIVE: surface projected this cycle from the canonical live terrain wide chain ----
    live = terrain_cache_get(tk)
    surf = (live or {}).get("_gamma_surface")
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
        _gamma_available = surf.get("gamma_available", True)
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
            _contract_admission = _option_contract_admission_summary(tk)
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
            # ONE spot faucet (operator directive, 2026-09-15): the spot stamped ON THIS SURFACE
            # (by whichever producer computed this exact surface_seq generation) -- its cells
            # were computed from that stamp. No fall-through to the terrain payload's own spot
            # (operator rule 2026-09-23: no fallbacks); an unstamped surface reads no spot.
            "spot": surf.get("spot"),
            "spot_source": surf.get("spot_source"),
            "chain_as_of_ts_utc": live.get("computed_ts_utc"),
            "spot_as_of_ts_utc": surf.get("spot_as_of_ts_utc"),
            "age_sec": live.get("levels_age_sec"),            # terrain's canonical age
            "refresh_active": live.get("levels_refresh_active"),
            "chain_basis": live.get("chain_basis"),
            # coverage: the live terrain chain is strike_count-bounded (near-money), NOT the full
            # strike_range=ALL book — disclosed so the heatmap is never presented as a complete chain.
            "complete": False,
            "coverage": {
                "window": "live_near_money", "chain_basis": live.get("chain_basis"),
                "strike_count": len(strikes),
                "strike_min": (strikes[0] if strikes else None),
                "strike_max": (strikes[-1] if strikes else None),
                "expiry_count": len(surf.get("expirations") or []),
                "note": ("near-money LIVE window (strike_count-bounded terrain chain) — NOT the "
                         "full strike_range=ALL book. Proven-complete captures are per-expiry "
                         "(complete_chain_captures), not exposed by this surface"),
            },
            **_stamp_surface_session(surf, reference_date=None),
            "provenance": {
                "producer": "math_exposure_core.compute_exposures_by_strike",
                "source": "live_terrain_wide_chain (_terrain_refresh_one, strike_count-width basis)",
                "classification": "DERIVED", "cell_metric": "net_gex_1pct",
                "spot_basis": "live_resolve_spot",
            },
            "method": ("live terrain wide chain (current Greeks + live spot, this refresh cycle) -> "
                       "partition by native expirationDate -> compute_exposures_by_strike per expiry "
                       "-> net_gex_1pct cell; one producer, zero extra vendor calls"),
        })

    # ---- no live surface: unavailable, with the reason. Nothing stands in for it. ----
    # #1-A: separate the two truths the UI must not conflate.
    #   REQUESTED = this endpoint has actually recorded demand for the surface (above).
    #   ON BOARD  = the ticker is in the ACTUAL current canonical terrain/logger board — read under
    #               the board's own lock (_ticker_on_terrain_board), NOT inferred from "a cached
    #               snapshot happens to exist". A stale snapshot is not proof of current membership.
    #   WARMING   = requested AND on the board AND the terrain producer can refresh THIS ticker right
    #               now — reusing terrain_staleness's canonical output merged onto `live`
    #               (levels_refresh_active, not quarantined, not paused). No copied scheduler policy.
    _requested = _gamma_surface_wanted(tk)
    _on_board = _ticker_on_terrain_board(tk)
    _warming = (_requested and _on_board and bool(live) and bool(live.get("levels_refresh_active"))
                and not live.get("levels_quarantined") and not live.get("levels_paused_on_purpose"))
    payload: dict = {"ticker": tk, "symbol": tk, "available": False, "source": "unavailable",
                     "live": False, "stale": True, "warming": _warming,
                     "requested": _requested, "on_board": _on_board,
                     "reason": ("no live gamma surface for this ticker yet -- the terrain loop "
                                "projects it once the ticker is viewed and on the board")}
    return JSONResponse(payload)


#: /api/spot single-flight only (Instant-UI Phase 5). No TTL cache and no
#: expired-payload-on-timeout: a waiter that cannot join this resolve gets 504.
_spot_poll_lock = threading.Lock()
_spot_poll_inflight: dict[str, threading.Event] = {}
_spot_poll_inflight_result: dict[str, dict] = {}


@app.get("/api/spot")
def get_spot(ticker: str = Query(...)):
    """Featherweight live spot. The ONE price authority (resolve_spot) plus the
    plane's streamed_chg_pct. Concurrent callers single-flight one resolve;
    a timeout is absence, never a stale payload served as current.
    """
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    deadline = time.time() + 10.0
    while True:
        with _spot_poll_lock:
            leader = tk not in _spot_poll_inflight
            if leader:
                _spot_poll_inflight[tk] = threading.Event()
                _spot_poll_inflight_result.pop(tk, None)
            done = _spot_poll_inflight[tk]
        if not leader:
            remaining = deadline - time.time()
            if remaining <= 0:
                return JSONResponse(
                    {"ticker": tk, "spot": None, "spot_source": None,
                     "spot_state": "unavailable", "spot_as_of_ts_utc": None,
                     "chg_pct": None, "error": "spot_resolve_timeout"},
                    status_code=504,
                )
            done.wait(timeout=remaining)
            with _spot_poll_lock:
                hit = _spot_poll_inflight_result.get(tk)
            if hit is not None:
                return JSONResponse(hit)
            continue
        try:
            spot, source, ts = resolve_spot(tk)
            payload = {"ticker": tk, "spot": spot, "spot_source": source,
                       "spot_state": current_spot_state(source, tk),
                       "spot_as_of_ts_utc": ts,
                       "chg_pct": _lmp.streamed_chg_pct(_lmp.get_quote(tk))}
            with _spot_poll_lock:
                _spot_poll_inflight_result[tk] = payload
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
    p = _artifact_reports_dir() / "terrain_backtest_latest.json"    # RC-523: artifacts root
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
    return HTMLResponse(_with_live_ui_port(p.read_text(encoding="utf-8")),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/exposure", response_class=HTMLResponse)
def exposure_page():
    """RC-200 (re-landed with RC-210) — the Exposure Overlay tab: dealer positioning on
    price (operator #1 project, LIVE order 2026-08-02)."""
    p = static_dir / "exposure.html"
    if not p.exists():
        return HTMLResponse("<p>static/exposure.html not found</p>", status_code=404)
    return HTMLResponse(_with_live_ui_port(p.read_text(encoding="utf-8")),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/options", response_class=HTMLResponse)
def options_page():
    """OPTIONS_ORDER_FLOW_V1 UI/consumer wiring: chain + contract-selection + live
    order-flow microstructure for one option contract. Reads GET /api/chain (contract
    listing), POST /api/streaming/active-option-contract (subscribe), GET /api/order-flow/
    options-microstructure (live book + freshness/health) — no new endpoints, no client-
    side second producer."""
    p = static_dir / "options.html"
    if not p.exists():
        return HTMLResponse("<p>static/options.html not found</p>", status_code=404)
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


# RC-UI-1's dev route (/console) converged into `/` here (operator directive 2026-09-14):
# static/console.html was renamed to static/index.html in this same commit, so the existing
# `/` route above (root(), reading static_dir/index.html) now serves it directly. No
# transitional dual-serving period -- /console is gone, not aliased.


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
def get_desk_dossier(ticker: str = Query(...),
                     as_of: float = Query(default=0.0)):
    """One name's measured structure, as it stood at `as_of`."""
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    tk = ticker_storage_key(_required_ticker(ticker))
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
    ticker: str = Query(...),
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
    tk = ticker_storage_key(_required_ticker(ticker))
    out: dict = {"subject": tk, "as_of_utc": at}
    try:
        # Live LAST_PRICE only when this is a current request. A historical as_of
        # keeps the as-of bar close and must not receive today's live print.
        live_spot = None
        if not (as_of and as_of > 0):
            live_spot, _, _ = resolve_spot(tk)
        out["distribution"] = desk_store.terminal_distribution(
            _desk_db, tk, at, horizon_sessions=max(1, min(int(horizon_sessions), 60)),
            spot=live_spot)
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


@app.get("/api/terrain")
def get_terrain(ticker: str = Query(...)):
    """Terrain payload — levels only, NO model stack.

    Deliberately separate from /api/state: that path runs the full pipeline (chain +
    greeks + xgb/lstm/transformer x 4 horizons + fusion + decision bundle), which is why
    background collection had to be throttled to keep it responsive. Terrain is ~5 ms of
    math on the same chain, so it never needs to compete for that budget.
    """
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    _note_gamma_surface_demand(tk)          # a viewed ticker's full chain is kept by the levels loop
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
        # internal fields (the kept chain, the heatmap grid, per-strike rows) are served by their
        # own endpoints -- never shipped on every terrain poll
        return {k: v for k, v in _reprice_cached_terrain(cached, tk).items() if not k.startswith("_")}
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






def _sse_event_name_for_envelope(env) -> str:
    """The wire `event:` name for one /api/analytics/light/stream envelope. Every existing L1
    envelope omits `_sse_event_name` and gets "l1_projection" exactly as before this function
    existed; `_next_gamma_surface_seq`'s gamma-surface publish notify is the one caller that
    sets it, to "gamma_surface_seq". A small pure function (not inlined in the generator) so it
    is directly unit-testable without driving the async generator/SSE connection."""
    return env.get("_sse_event_name", "l1_projection") if isinstance(env, dict) else "l1_projection"


@app.get("/api/session")
def get_session():
    return JSONResponse({"session_label": session_label(now_et())})


#: spot within this many points of a gamma wall raises a proximity alert
APPROACH_PTS: float = 1.5
#: a cross younger than this is shown as an alert
RECENT_CROSS_SEC: float = 120.0


@app.get("/api/alerts")
def get_alerts(ticker: str = Query(...)):
    """Proximity alerts: spot near a gamma wall, and levels crossed in the last RECENT_CROSS_SEC."""
    tk = ticker_storage_key(_required_ticker(ticker))
    t = terrain_cache_get(tk) or {}
    spot = resolve_spot(tk)[0]
    alerts = []
    if spot is not None:
        for key, word in (("call_wall", "ceiling"), ("put_wall", "floor")):
            lvl = t.get(key)
            if lvl is not None and abs(spot - lvl) <= APPROACH_PTS:
                alerts.append(f"Within {abs(spot - lvl):.1f}pts of {lvl:.2f} {word} wall")
    for c in get_db().get_recent_crosses(tk, n=10):
        if time.time() - float(c["ts_utc"]) <= RECENT_CROSS_SEC:
            alerts.append(f"Just crossed {'up' if c['direction'] == 'up' else 'down'} through {c['level_name']} level")
    return JSONResponse({"ticker": tk, "alerts": alerts})


@app.get("/api/analytics/light/stream")
async def get_analytics_light_stream(
    request: Request,
    ticker: str = Query(...),
    expiry: Optional[str] = Query(default=None),
):
    """
    Server-Sent Events for ANALYTICS only: l1_projection / gamma_surface_seq after _project_l1 /
    surface publish. Prices are not served here -- the capture daemon pushes them straight to
    the browser (app/market_data/schwab/streaming/live_ui.py), so no analytics load in this
    process can ever delay a price.
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
                    yield f"event: {_sse_event_name_for_envelope(env)}\ndata: {json.dumps(env, default=str)}\n\n"
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






@app.get("/api/order-flow/microstructure")
def api_order_flow_microstructure(ticker: str = Query(...)):
    """Canonical L2 book microstructure (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1): top-of-book,
    spread, microprice, Top 1/3/5 depth totals + imbalance, depth-pressure curve, book slope,
    liquidity concentration, wall_candidates, and ages — every field classified
    NATIVE/DERIVED/PROXY. SERIALIZER, not a second producer: it delegates to the ONE canonical
    app.options.order_flow.engine.compute_book_microstructure keyed by this ticker, which carries the
    engine's already-computed structural state for the current book (memoized per ticker +
    BOOK_TIME) rather than re-walking the raw book. No Schwab REST quote call; the client
    renders, never recomputes."""
    t = _required_ticker(ticker).upper().strip()
    # VIEW endpoint: touch last-seen only, never enroll (RC-160 ticker-scope discipline).
    _touch_tracked_ticker_view(t)
    data: dict = {}
    try:
        from app.options.order_flow.state import get_content_for_symbol
        _content = get_content_for_symbol(t)
        if _content:
            data["content"] = _content
    except Exception as e:  # streaming state optional — fail closed to 'no_book', never fabricate
        log.debug("microstructure content build failed for %s: %s", t, e)
    _row = _lmp.get_quote(t)
    if _row and _row.get("exchange_quote_ts") is not None:
        data["exchange_quote_ts"] = _row.get("exchange_quote_ts")
    from app.options.order_flow.engine import compute_book_microstructure
    # ticker=t → serialize the canonical state carried per (ticker, BOOK_TIME); no independent recompute.
    payload = compute_book_microstructure(data, ticker=t)
    # The trade-side read the Trade Desk's Order Flow card shows: tick-rule PROXY flow from the
    # same OrderFlowEngine the analytics state and the option book use (no second classifier).
    try:
        from app.options.order_flow.engine import OrderFlowEngine
        from app.options.order_flow.live_payload import flow_block
        payload["flow"] = flow_block(OrderFlowEngine().compute(data, ticker=t))
    except Exception as e:  # flow is additive -- the book payload stands without it
        log.debug("microstructure flow failed for %s: %s", t, e)
        payload["flow"] = None
    payload["ticker"] = t
    return JSONResponse(payload)


@app.get("/api/order-flow/options-microstructure")
def api_order_flow_options_microstructure(contract: str = Query(...)):
    """Same canonical L2 book microstructure as /api/order-flow/microstructure, for one
    OPTION CONTRACT's live book. SERIALIZER, not a second producer: delegates to
    app.options.order_flow.streaming.get_option_contract_book_microstructure, which delegates
    to the SAME app.options.order_flow.engine.compute_book_microstructure the equity route reads — no
    parallel book-imbalance computation for options. `contract` MUST be a chain response's
    own "symbol" field (OSI format, e.g. "SPY   260820C00767000"); this route does not
    construct or validate that format, it only serializes whatever content has been
    replayed for the literal string given. No ticker-roster touch here — a contract symbol
    is not a ticker and does not participate in that enrollment concept."""
    c = (contract or "").strip()
    if not c:
        return JSONResponse({"error": "contract is required"}, status_code=400)
    from app.options.order_flow.streaming import (
        get_option_contract_book_microstructure,
        get_option_contract_streaming_diagnostics,
    )
    payload = get_option_contract_book_microstructure(c)
    payload["contract"] = c
    try:
        # PR214 merge blocker 1A: the diagnostics are bound to the CONTRACT BEING
        # QUERIED, not to whatever contract the plane happens to be streaming. Without
        # `c` this attached the globally-active contract's health verbatim to a book
        # computed for a different contract, so a response could read `contract: A`
        # beside `streaming_healthy: true` that belonged entirely to B. The book above
        # is still served truthfully (replayed content for A is real and is not
        # discarded); only the LIVE HEALTH claim is bound and fails closed on mismatch.
        payload["streaming_plane"] = get_option_contract_streaming_diagnostics(for_contract=c)
    except Exception:  # diagnostics are informational only — never fail the book payload for them
        payload["streaming_plane"] = {}
    return JSONResponse(payload)
@app.post("/api/streaming/active-option-contract")
async def post_streaming_active_option_contract(payload: dict = Body(default={})):
    """Subscribe LEVELONE_OPTIONS+OPTIONS_BOOK to one option contract (dynamic; replaces
    prior subscription). Mirrors /api/streaming/active-ticker exactly, for the SEPARATE
    option-contract slot (an equity ticker and an option contract on that same underlying
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
        diag = get_option_contract_streaming_diagnostics(for_contract=c)
        return {"ok": ok, "contract": c, "command_generation": generation, **diag}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
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
    its own client_id; `seq` orders that view's declarations. The stream carries the union
    of every live view's demand ranked to the shared-socket budget -- see
    app.options.order_flow.streaming.declare_option_contract_demand for why this is no
    longer one last-writer-wins slot."""
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

    from app.options.order_flow.streaming import StaleOptionCommandError

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
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
    except StaleOptionCommandError as e:
        return JSONResponse({"ok": False, "error": str(e), "client_id": client_id, "seq": seq,
                             "superseded": True}, status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "contracts": contracts}, status_code=500)
    return JSONResponse(out)


@app.post("/api/streaming/active-ticker")
async def post_streaming_active_ticker(payload: dict = Body(default={})):
    """Subscribe Schwab L1+book to the active UI ticker (dynamic; replaces prior subscription)."""
    t = _required_ticker(payload.get("ticker")).upper().strip()
    # SWITCH-LATENCY FIX (critical): set_streaming_active_ticker blocks on fut.result(timeout=30)
    # while it does 6 websocket re-subscribe round-trips, and this endpoint fires on EVERY ticker
    # switch. Running it on the async event loop froze the entire UI (all SSE/requests) for up to
    # 30s per switch. Offload the whole blocking block to the thread pool; the loop stays free.
    def _apply():
        from app.options.order_flow.streaming import set_streaming_active_ticker, get_streaming_diagnostics, get_plane_authority_for_ticker

        ok = set_streaming_active_ticker(t)
        _lmp.reset_sse_push_cursor(t)
        diag = get_streaming_diagnostics()
        return {"ok": ok, "ticker": t, **diag, "plane_quote_authority": get_plane_authority_for_ticker(t)}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "ticker": t}, status_code=500)
    return JSONResponse(out)


#: No Schwab-documented batch-quote symbol ceiling exists anywhere in this repo (checked:
#: schwab_client.py, schwab_field_dictionary*, tools/sync_schwab_field_dictionary.py).
@app.get("/api/watchlist-quotes")
async def api_watchlist_quotes(tickers: str = Query(default="")):
    """
    Every watchlist row from the ONE streamed source: each symbol's live_market_plane row,
    written by the capture daemon's LEVELONE_EQUITIES push. STREAM ONLY (operator rule
    2026-09-23: no fallbacks). This route used to fetch Schwab REST quotes for any symbol
    the stream was not answering and record them into the plane -- a second source that hid
    exactly the gap the operator wants to see. Now:

      spot     LEVELONE_EQUITIES LAST_PRICE, served while that trade price is fresh (0 hops)
      chg_pct  REGULAR_MARKET_CHANGE_PERCENT from the same streamed row (0 hops)

    A symbol with no fresh streamed LAST_PRICE is simply absent from `quotes` (the row
    reads UNAVAILABLE). `ok` is false with error "stream_unavailable" when NO requested
    symbol has one -- the whole live feed is down, not a per-symbol gap. No vendor call.

    Returns {"ok": bool, "error": str|None, "quotes": {SYMBOL: {spot, spot_disp, spot_state,
    spot_source, chg_pct, exchange_quote_ts}}}.
    """
    raw = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()]
    seen: list[str] = []
    for t in raw:
        if t not in seen:
            seen.append(t)
    if not seen:
        return JSONResponse({"ok": True, "error": None, "quotes": {}})
    out: dict = {}
    for t in seen:
        wl = _watchlist_row(t)
        if wl is not None:
            out[t] = wl
    if not out:
        return JSONResponse({"ok": False, "error": "stream_unavailable", "quotes": {}})
    return JSONResponse({"ok": True, "error": None, "quotes": out})


def _watchlist_row(t: str) -> "dict | None":
    """ONE watchlist row: the shared price row (live_price_rows.price_row), withheld when not live."""
    ev = _lpr.price_row(t)
    if ev.get("spot_state") != "live" or ev.get("spot") is None:
        return None
    return {
        "spot": ev["spot"],
        "spot_disp": ev["spot_disp"],
        "spot_state": ev["spot_state"],
        "spot_source": SPOT_SOURCE_PLANE,
        "chg_pct": ev["chg_pct"],
        "ts_recv": ev.get("ts_recv"),
        "quote_ingestion": ev.get("quote_ingestion"),
    }






@app.get("/api/expiries")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write + Schwab expiry fetch, no await).
def get_expiries(ticker: str = Query(...)):
    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: listing expiries is a VIEW — touch last-seen only.
    _touch_tracked_ticker_view(ticker)
    t = terrain_cache_get(ticker) or {}
    return JSONResponse({"expiries": t.get("expiries") or [],
                         "reason": None if t.get("expiries") else "levels not computed yet"})


#: OPTIONS_ORDER_FLOW_V1 completeness repair (2026-08-30, operator-directed, round 2): a
#: fixed strike_count is NEVER proof of completeness — it is by definition a BOUND (N
#: strikes above/below ATM), and MEASURED live 2026-08-30 it silently truncated a real
#: chain: SPY's near expiry at strike_count=250 returned 388 contracts (194 strikes,
#: 645.0-950.0); the SAME expiry via schwab-py's `strike_range=Options.StrikeRange.ALL` —
#: a DIFFERENT vendor selection dimension, not a wider count — returned 526 contracts (263
#: strikes, 420.0-950.0): 69 real strikes strike_count=250 never showed. `strike_range=
#: "ALL"` was independently confirmed to be the vendor's actual complete set (not itself
#: silently bounded) by a saturation check: an unrelated strike_count=500 request on the
#: SAME expiry returned the IDENTICAL strike set, byte-for-byte — the two independent
#: request shapes converged, which a still-truncated response could not do. TSLA's near
#: expiry: strike_count=250 and strike_range=ALL happened to already agree (236 contracts,
#: 118 strikes, 160.0-630.0, 27 fractional) — evidence that a bound merely CAN coincide with
#: completeness on a given day, never proof that it reliably does, which is exactly why
#: `strike_range=ALL` (never a strike_count bound) is now the completeness basis. Real
#: capture evidence: tests/fixtures/real_tsla_complete_chain_strike_range_all.json,
#: tests/fixtures/real_spy_strike_count_vs_strike_range_all_evidence.json.
#:
#: SAFE BY CONSTRUCTION regardless of strike width: this repo's own measured 502s (SPY/QQQ
#: at strikeCount>=150, $SPX at 80-100, server.py:11090-11091) were ALL multi-expiry
#: requests (strikeCount * 2 sides * ~35-55 expiries in ONE response) — bounding one
#: request to exactly ONE expiry via from_date=to_date keeps `strike_range=ALL`'s contract
#: count scoped to that single expiry's real strike population (measured 236-526 contracts
#: above), an order of magnitude under SCHWAB_CHAIN_CONTRACT_BUDGET=6600, regardless of how
#: many strikes that population actually has — the vendor 502 was never about strike width
#: alone, it was strike width MULTIPLIED across every expiry in an unwindowed request.
COMPLETENESS_BASIS_STRIKE_RANGE_ALL = "strike_range=ALL"


@app.get("/api/chain")
def get_chain(ticker: str = Query(...),
              expiry: Optional[str] = Query(default=None)):
    """One expiry of the ticker's full chain -- every contract Schwab listed, every field as sent
    -- from the chain the levels loop downloads (strike_range=ALL), with streamed option updates
    newer than that download overlaid. The loop keeps a ticker's chain while it is viewed
    (/api/terrain and this route mark it). Answers `status: unavailable` with a reason when no
    chain is held."""
    t = ticker_storage_key(_required_ticker(ticker))
    _touch_tracked_ticker_view(t)

    _note_gamma_surface_demand(t)          # a viewed ticker's full chain is kept by the levels loop
    held = terrain_cache_get(t) or {}
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
    response_contracts, overlay_n, _ = _gamma_surface_contracts_with_stream_overlay(
        t, contracts, newer_than_ts=fetched_ts)
    return JSONResponse({
        "ticker": t, "spot": held.get("spot"), "expiry": resolved_expiry,
        "chain_as_of_ts_utc": fetched_ts,
        "contracts": response_contracts, "status": "ok",
        "stream_overlay_contracts": overlay_n,
        "scope": {"kind": "complete_single_expiry", "requested_expiry": resolved_expiry,
                  "completeness_basis": COMPLETENESS_BASIS_STRIKE_RANGE_ALL},
    })

@app.get("/api/health")
def health():
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
        "ui_maximize_panel_warm_tickers": list(panel_warm_tickers()),
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
    }




def _canonical_price_level_bars(tk: str, session_date) -> tuple[list, str, list]:
    """THE bar input for the canonical price-level snapshot: price_bars_1m plus the forming
    minute. A thin prior session is disclosed, never filled."""
    from liquidity_value_engine import _bar_dt_et, _bars_to_list, prior_trading_session_date

    bars_norm = _bars_to_list(_liquidity_live_1m_overlay_bars(tk))
    degraded: list[dict] = []
    prior = prior_trading_session_date(bars_norm, session_date)
    if prior is not None:
        n_prior = sum(1 for b in bars_norm if (lambda d: d is not None and d.date() == prior)(_bar_dt_et(b)))
        if n_prior < LEVELS_PRIOR_SESSION_MIN_BARS:
            degraded.append({"family": "prior_day",
                             "reason": (f"prior session {prior} holds only {n_prior} of >= "
                                        f"{LEVELS_PRIOR_SESSION_MIN_BARS} RTH bars; prior-day "
                                        f"levels derive from a partial tape"),
                             "last_good_ts_utc": None})
    return bars_norm, "price_bars_1m", degraded


def canonical_price_level_snapshot(ticker: str):
    """THE Phase 2A entry point for every server surface.

    Materializes once per generation and returns the SAME object for the rest of that
    generation. No endpoint may call the engine's level helpers directly — the static
    guard `check_phase2a_single_level_computation` fails the build if one does, alias
    or not.
    """
    from liquidity_value_engine import PlaybookConfig, materialize_price_level_snapshot
    from time_et import now_et

    tk = ticker_storage_key(_required_ticker(ticker))
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
def get_levels(ticker: str = Query(...)):
    """Single levels contract (schema v1): id/price/family/evidence_tier/provenance/staleness."""
    import time as _time

    from liquidity_value_engine import carry_snapshot_levels

    tk = ticker_storage_key(_required_ticker(ticker))
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


def _session_bars(tk: str, session_date) -> list[dict]:
    """1-minute bars from the prior trading day's 00:00 ET through `session_date`'s close (the
    liquidity engine's window), from price_bars_1m, with the forming minute when the session is
    today -- in the engine's shape."""
    from datetime import datetime as _dt, time as _time, timedelta as _td
    from time_et import ET, RTH_END_MINS, is_trading_day_et
    prior = session_date - _td(days=1)
    while not is_trading_day_et(prior.isoformat()):
        prior -= _td(days=1)
    lo = _dt.combine(prior, _time(0, 0), tzinfo=ET).timestamp()
    hi = _dt.combine(session_date, _time(RTH_END_MINS // 60, RTH_END_MINS % 60), tzinfo=ET).timestamp()
    bars = [b for b in _liquidity_live_1m_overlay_bars(tk) if lo <= b["timestamp"] / 1000.0 < hi]
    return bars


def _liquidity_live_1m_overlay_bars(ticker: str) -> list[dict]:
    """The ticker's 1-minute bars (price_bars_1m) with the forming minute, in the liquidity
    engine's shape."""
    bars = overlay_forming_bar_from_plane([_bar_dict(c) for c in _bars_1m(ticker, 2500)], ticker)
    return [{"timestamp": int(float(b["t"]) * 1000), "open": b["o"], "high": b["h"],
             "low": b["l"], "close": b["c"], "volume": b.get("v")} for b in bars]


#: the terrain levels the liquidity zones are fused with, and the tag each carries
TERRAIN_FUSION_LEVELS = (("call_wall", "GAMMA_CALL_WALL"), ("put_wall", "GAMMA_PUT_WALL"),
                         ("call_delta_wall", "DELTA_CALL_WALL"), ("put_delta_wall", "DELTA_PUT_WALL"),
                         ("absolute_gamma_strike", "ABS_GAMMA"), ("net_gex_peak", "NET_GEX_PEAK"),
                         ("max_pain", "MAX_PAIN"), ("gamma_flip", "GAMMA_FLIP"))


def _liquidity_option_levels(tk: str) -> tuple[list[tuple[float, str]], str]:
    """The ticker's option levels from its published terrain, tagged for the liquidity zones."""
    t = terrain_cache_get(tk)
    if not t:
        return [], "levels_not_ready"
    levels = [(float(t[k]), tag) for k, tag in TERRAIN_FUSION_LEVELS if t.get(k) is not None]
    return levels, "fused" if levels else "fused_empty"


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
    ticker: str = Query(...),
    date: Optional[str] = Query(default=None, description="Session date YYYY-MM-DD (default: today ET)"),
    snapshot: str = Query(
        default="premarket",
        description="live | premarket | opening | midday | afternoon. live = rolling cutoff (now ET) + optional options fusion",
    ),
    fusion: bool = Query(default=True, description="When snapshot=live, fuse the terrain option levels"),
):
    """Return liquidity & value playbook snapshot (zones, summary, raw_levels) for ticker/session.
    Uses PlaybookConfig(clustering_mode='percent'). ``live`` uses min(now,RTH close) cutoff; checkpoints unchanged."""
    try:
        from liquidity_value_engine import build_live_snapshot, generate_liquidity_value_snapshot
        from liquidity_models import SnapshotType, PlaybookConfig

        session_date = date or now_et().strftime("%Y-%m-%d")
        ticker_upper = ticker.upper().strip()
        # TICKER-PREVIEW-NO-ENROLL: liquidity snapshot is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker_upper)
        from datetime import date as date_type

        session_date_obj = date_type.fromisoformat(session_date)
        bars = _session_bars(ticker_upper, session_date_obj)
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
        bar_merge_note = "price_bars_1m"

        if snap_raw == "live":
            extra, fusion_status = _liquidity_option_levels(ticker_upper) if fusion else ([], "disabled")
            # RC spot-360-audit (2026-09-14, live RTH reproduction): spot_for_zones used to come
            # from _state_cache (the /api/state cache -- last-write-wins, NO freshness gate) via
            # _liquidity_fusion_from_cache / _liquidity_spot_from_cache_any_expiry: a THIRD spot
            # producer next to resolve_spot()/live_market_plane. Reproduced live: this route
            # served 759.725 off a cache entry 1061s (17.7 min) old while the header read 760.13
            # at the same instant. resolve_spot() is THE spot authority for every other consumer
            # in this file (RC-14); zone scoring must read the same one, not a stale side-cache
            # keyed off whichever (ticker, expiry) /api/state happened to be called for last.
            spot_for_zones, _, _ = resolve_spot(ticker_upper)
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
    except HTTPException as e:
        # MEASURED 2026-09-11: get_client() raises HTTPException(503, ...) when Schwab auth is
        # genuinely unavailable -- a real, distinct, already-correct classification (missing/
        # invalid credentials is not "the server is broken"). The blanket `except Exception`
        # below caught it too, along with everything else, and re-issued it as a bare 500 with
        # only the message text -- discarding the status code FastAPI's own exception handling
        # would otherwise have propagated correctly. Preserve it instead of replacing it.
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)




