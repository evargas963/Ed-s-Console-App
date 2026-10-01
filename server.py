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
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Annotated, Optional
from dataclasses import asdict, dataclass

from time_et import ET, now_et, RTH_OPEN_MINS, ct_label, et_date_str_from_ts_utc, session_label
from math_exposure_core import bucket_metric, merge_exposure_books, overlay_streamed_contract_fields

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
from runtime_layout import logs_dir as _runtime_logs_dir, reports_dir as _artifact_reports_dir  # noqa: E402

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

from instrument_identity import display_symbol, ticker_storage_key   # RC-126: the ONE query-symbol authority
import live_market_plane as lmp
from numeric_contract import schwab_number
from terrain_engine import (TerrainSnapshot, chain_ladder, compute_terrain, nearest_strike, positioning_migration)
from terrain_atr import AtrPair, compute_atr_pair

from db import get_db

import live_price_rows as _lpr        # with_change: the bar-change computation
import push_changes

# ── Config (the token file's age is shown; the console makes no Schwab call) ──
load_dotenv_file()
cfg     = build_config()


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
    """(spot, source, as_of_ts_utc): the daemon's price row's Schwab LAST_PRICE as sent and its
    trade time, at any hour -- the value the header shows; (None, "none", None) until Schwab has
    sent one."""
    from app.options.order_flow.streaming import price_row

    row = price_row(ticker)
    if not row or row.get("spot") is None:
        return None, "none", None
    return row["spot"], SPOT_SOURCE_PLANE, row.get("trade_ts")


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

# ETF zone classification (spy_zone / qqq_zone / iwm_zone)


# Builds OHLC bars from spot price ticks. Server polls every ~30s, so:
#   5-min bars = ~10 ticks per bar
#   1-min bars = ~2 ticks per bar
# Bars are keyed by ticker. Completed bars stored in ring buffer; maxlen from math_exposure.
# ─────────────────────────────────────────────────────────────────────────────
#: one RTH day of 1-minute bars
CANDLE_1M_MAX_BARS: int = 390
from micro_structure import Candle
from app.options.contracts.default import front_atm_call
from calibration.complete_chain_capture import (
    CAPTURE_BASIS,
    last_capture_per_day,
    newest_capture_ts,
)


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
    """Write one streamed 1-minute bar (Schwab CHART_EQUITY) to price_bars_1m; False when it
    lacks a field (then nothing is written)."""
    from numeric_contract import schwab_count, schwab_number
    o, h, lo, c = (schwab_number(msg.get(k)) for k in ("open", "high", "low", "close"))
    start_ms = msg.get("bar_start_ms")
    if None in (o, h, lo, c, start_ms):
        # not a number (AGENTS.md rule 2): absent, -999, text, NaN or infinity
        log.warning("streamed bar for %s lacks a valid field, not written: %s", msg.get("symbol"), msg)
        return False
    get_db().upsert_1m_bars(msg["symbol"], [Candle(ts=float(start_ms) / 1000.0, open=o, high=h, low=lo,
                                                   close=c, volume=schwab_count(msg.get("volume")))])
    push_changes.changed(msg["symbol"], push_changes.LIQUIDITY)
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


def _board() -> "list[str] | None":
    """The board: the capture daemon's one list of tickers, as its heartbeat carries it; None
    while the daemon's status is not current."""
    st = lmp.daemon_status()
    return list(st.get("board") or []) if st is not None else None




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

    # The levels loop: the stored levels at startup, then the status line and the price levels
    # (the chains arrive from the daemon, _on_chain).
    start_terrain_loop()
    # RC-69: bar collection is its own always-on service — never a side-effect of rendering.
    start_bar_writer()

    # The live feed from the capture daemon (the only Schwab client): every streamed equity
    # quote and option greeks/OI/volume quote -> _on_stream_tick, which reprices a viewed
    # ticker; every chain the daemon fetched -> _on_chain, which prices it.
    from app.options.order_flow.streaming import start_order_flow_stream
    start_order_flow_stream(None, None, None, on_tick_callback=_on_stream_tick,
                            on_chain_callback=_on_chain)

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
#: The header's three market-context slots (Trade Desk, operator 2026-09-25): where on the page
#: they sit, not what is streamed. Each shows its board ticker's row; one not on the board reads
#: "not on the board".
HEADER_CONTEXT_SYMBOLS = ("$SPX", "$NDX", "$VIX")


def _with_live_ui_port(html: str) -> str:
    """Tell the page where the capture daemon's price socket listens (the same
    ED_LIVE_UI_PORT the daemon binds) and its header's context slots (HEADER_CONTEXT_SYMBOLS,
    each with its display name). An unfilled page opens no price socket -- its prices read
    UNAVAILABLE rather than reaching a daemon nobody configured it for."""
    from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT
    context = json.dumps([{"key": k, "display": display_symbol(k)} for k in HEADER_CONTEXT_SYMBOLS])
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


def _merged_recent_crosses(edb, ticker: str, n: int) -> "list[dict]":
    """The newest `n` level crosses, each (time, value, direction) one event carrying every
    level named there in `level_names`. The one reader of level crosses for every route.
    Price crossing one strike writes one stored row per named level sitting there; they are
    merged here, at the read, so the stored history keeps its per-level rows."""
    raw = edb.get_recent_crosses(ticker=ticker, n=max(int(n) * 8, 64))
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
    return merged[:n]


def _required_ticker(ticker: Optional[str]) -> str:
    """The ticker the caller asked for -- never a default one (universality, operator
    2026-09-23: a missing ticker used to silently become SPY). Blank -> HTTP 400."""
    t = str(ticker or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail="ticker is required")
    return t


# ── THE LEVELS (from the chains the capture daemon fetches) ──────────────────
_terrain_cache: dict[str, dict] = {}
_terrain_cache_lock = threading.Lock()
#: Why the ticker's newest chain is not priced: the daemon's chain fetch failed with Schwab's
#: answer, or a chain arrived incomplete. Cleared by the next chain priced.
_terrain_refresh_last_error: dict[str, str] = {}

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
        if payload.get("computed_ts_utc") is None:
            return                      # no compute time, no row: never stamped "now"
        _ts = round(float(payload["computed_ts_utc"]), 1)
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


#: The least age at which a terrain snapshot stops calling itself current (terrain_staleness also
#: allows two of the loop's delivered cycles).
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
        raw = json.loads(Path(cfg.token_path).read_text(encoding="utf-8"))
        return float(raw["creation_timestamp"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def terrain_staleness(computed_ts_utc: float | None, ticker: str | None = None) -> dict:
    """Whether the levels are current, and WHY NOT when they are not: the daemon's last answer
    for the ticker's chain (a failed fetch, an incomplete delivery) outranks its age. The daemon
    fetches every board ticker's chain at any hour, so age past two of its delivered rounds is a
    gap, never a schedule."""
    token = schwab_token_countdown(_schwab_token_creation_ts())   # RC-108: warn BEFORE death
    failure = str(_terrain_refresh_last_error.get(
        ticker_storage_key(ticker) if ticker else "", "") or "")
    if computed_ts_utc is None:
        return {"levels_stale": True, "levels_age_sec": None,
                "levels_stale_reason": (f"no terrain snapshot has been computed yet — {failure}"
                                        if failure else "no terrain snapshot has been computed yet"),
                "levels_failing": bool(failure), **token}
    age = round(time.time() - float(computed_ts_utc), 1)
    # judged against the round the daemon's chain sweep delivers (every board ticker once)
    round_sec = (lmp.daemon_status() or {}).get("chain_round_sec") or 0.0
    # Stale only past the floor *and* past two delivered rounds — one missed round is normal
    # jitter, two is a real gap. The floor is retained so a fast sweep cannot hide staleness.
    stale_after = max(float(TERRAIN_STALE_AFTER_SEC), 2.0 * float(round_sec))
    stale = age > stale_after
    reason = ""
    if stale:
        reason = (f"levels are {age:.0f}s old and every chain since has failed — {failure}"
                  if failure else
                  f"levels are {age:.0f}s old; the daemon's chain sweep has not delivered this "
                  f"ticker in two of its rounds ({float(round_sec):.0f}s each)")
    return {"levels_stale": stale, "levels_age_sec": age, "levels_stale_reason": reason,
            # actively FAILING is a different action (the chain fetch is erroring, the levels
            # will not come back on their own)
            "levels_failing": bool(stale and failure), **token}


def _gamma_surface_wanted(tk: str) -> bool:
    """Viewed: a page has the ticker open (its /api/changes connection), on any workspace, for
    as long as it stays open. It decides only which tickers are repriced on every streamed tick;
    every board ticker's chain is fetched and priced alike."""
    return tk in push_changes.watched()


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


def _option_contract_admission_summary(tk: str) -> dict:
    """Per-symbol admitted/observed/active/pending/rejected accounting for `tk`'s desired
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
    daemon_available = is_option_producer_daemon_available()
    rejected_all = read_producer_rejected_option_contracts()
    admitted_l1 = set((read_producer_admitted_option_contracts() or {}).get("LEVELONE_OPTIONS") or [])
    streamed = _desired_stream_greeks_for_ticker(tk)
    admitted, active, observed, pending = [], [], [], []
    rejected: "dict[str, str]" = {}
    for sym in desired:
        if sym in rejected_all:
            rejected[sym] = rejected_all[sym]
        elif sym in streamed:
            (active if lmp.feed_live_for(sym, "LEVELONE_OPTIONS") else observed).append(sym)
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

    Per leg, `overlay_symbols` is the set of streamed symbols the feed is delivering now
    (live_market_plane.feed_live_for, the one live rule), passed by _publish_levels. `rejected_symbols` (2026-09-16,
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
      'live'                — the feed is delivering this symbol now.
      'stale'                — the symbol has streamed (present in `streamed`, which
                              _desired_stream_greeks_for_ticker already filters to symbols
                              matching this ticker) but the feed is not delivering it now.
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


def _ensure_default_option_contract(tk: str) -> None:
    """The option contract whose OPTIONS_BOOK streams follows the page's ticker: the one already
    desired or held by the daemon when it is this ticker's, else the at-the-money call of the
    ticker's front expiry; cleared when the ticker has none. The operator's POST
    /api/streaming/active-option-contract still wins until the ticker changes."""
    from app.options.order_flow.streaming import (
        clear_active_option_contract, get_active_option_contract, set_active_option_contract)
    if _contract_is_for(get_active_option_contract(), tk):
        return
    held = ((lmp.daemon_status() or {}).get("held") or {}).get("OPTIONS_BOOK") or []
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
                    *, captures: "list | None" = None) -> "TerrainSnapshot | None":
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
        prev_spot = payload.get("spot")
        if new_chain:       # the ticker's contracts are the ones Schwab listed in this chain
            payload.update(_contract_symbols=frozenset(c.get("symbol") for c in chain if c.get("symbol")),
                           _default_contract=front_atm_call(chain, spot))
        listed = payload.get("_contract_symbols") or frozenset()
        streamed = _desired_stream_greeks_for_ticker(tk, listed)
        # each field the newest Schwab sent: a streamed value received after this chain, else the chain's
        priced, n_live = overlay_streamed_contract_fields(chain, streamed, fetched_ts)
        live_syms = _overlaid_symbols(chain, priced)
        snap = compute_terrain(tk, priced, spot, now=(
            datetime.fromtimestamp(fetched_ts, ET) if capture is not None else None))
        payload.update(snap.to_dict())
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
            # every ticker keeps its chain and its heatmap, so a ticker put on screen shows at once
            "_chain": chain, "_chain_fetched_ts": fetched_ts,
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
        if spot is not None and snap.books:
            surface = project_gamma_surface(priced, snap.books)
            surface.update(spot=float(spot), spot_source=spot_source, spot_as_of_ts_utc=spot_ts,
                           stream_overlay_contracts=n_live, stream_overlay_symbols=live_syms,
                           stream_overlay_computed_ts_utc=time.time())
            _stamp_gamma_surface_cell_stream_state(
                surface, streamed, {s for s in streamed if lmp.feed_live_for(s, "LEVELONE_OPTIONS")},
                read_producer_rejected_option_contracts(),
                set(_desired_option_symbols_for_ticker(tk, listed)),
                daemon_available=is_option_producer_daemon_available())
            payload["_gamma_surface"] = surface
        with _terrain_cache_lock:
            if payload["_gamma_surface"] is not None:
                payload["_gamma_surface"]["surface_seq"] = _next_gamma_surface_seq(tk)
            _terrain_cache[tk] = payload
        push_changes.changed(tk, push_changes.LEVELS)
        if new_chain:
            push_changes.changed(tk, push_changes.CHAIN)
        if capture is None:
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


def _vanna_rows(snap: "TerrainSnapshot") -> list:
    """[strike, net dealer vanna] for every strike whose vanna is known, from the published book:
    each strike's net_vanna exactly as compute_exposures_by_strike computed it (+call/-put)."""
    exposures, _diag = merge_exposure_books(snap.books.values())
    rows = []
    for k, b in exposures.items():
        net = bucket_metric(b, "net_vanna")
        if net is None:
            continue
        rows.append([float(k), net])
    rows.sort(key=lambda r: r[0])
    return rows


def _charm_rows(snap: "TerrainSnapshot") -> list:
    """[strike, net dealer charm] from the published charm map (the charm walls' own), exact."""
    return sorted([float(k), float(b["net_charm"])]
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
    if not tk or not _gamma_surface_wanted(tk):
        return
    with _reprice_guard:
        _reprice_dirty.add(tk)
        if tk in _reprice_running:
            return
        _reprice_running.add(tk)
    threading.Thread(target=_reprice_worker, args=(tk,), name=f"reprice-{tk}", daemon=True).start()


def _reprice_worker(tk: str) -> None:
    """Reprice `tk` while ticks keep arriving, at most once per LEVELS_REPRICE_MIN_INTERVAL_SEC;
    the last tick of a burst is always priced. A ticker with no chain yet is priced when the
    daemon delivers its chain (_on_chain)."""
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
        except Exception as e:  # noqa: BLE001 -- logged; the next tick or chain reprices
            log.warning("levels reprice failed for %s: %s", tk, e)


#: prices the chains the daemon delivers, off the event loop that received them
_chain_pricing = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chain-pricing")


def _on_chain(ticker: str, contracts: "list | None", ts: float, reason: "str | None" = None) -> None:
    """The feed's chain callback (streaming.assemble_chain_part), on the event loop: a whole
    chain the daemon fetched is priced on a pricing thread; a chain it could not deliver keeps
    the ticker's last levels, which then say why no newer chain came."""
    tk = ticker_storage_key(ticker)
    if contracts is None:
        _terrain_refresh_last_error[tk] = f"chain fetch failed ({reason})"
        return
    _chain_pricing.submit(_price_chain, tk, contracts, ts)


def _price_chain(tk: str, contracts: list, fetched_ts: float) -> None:
    """THE producer of a ticker's levels from a newly fetched chain (_publish_levels), with the
    chain's own fetch time as its as-of: an older streamed value never overrides it."""
    try:
        _publish_levels(tk, contracts, fetched_ts)
        with _terrain_cache_lock:
            payload = _terrain_cache[tk]
        _log_flip_drift(tk, payload)
        _terrain_refresh_last_error.pop(tk, None)
    except Exception as e:  # noqa: BLE001 -- kept as the ticker's reason, and logged
        _terrain_refresh_last_error[tk] = f"pricing the chain failed: {type(e).__name__}: {e}"
        log.warning("pricing the chain of %s failed: %s", tk, e, exc_info=True)


STATUS_EVERY_SEC = 60.0
#: the daemon writes a feed-status row every 60 s; older than this, the record has stopped
FEED_RECORD_STALE_SEC = 150.0


def _feed_record_state() -> str:
    """How old the newest stream_feed_status row in stream_capture.db is: it proves the whole
    path (the daemon's loop, the bus, the writer, the database) wrote this minute."""
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
    age = time.time() - float(newest)
    return (f"feed record: written {age:.0f}s ago" if age <= FEED_RECORD_STALE_SEC
            else f"FEED RECORD STALE: last written {age / 60:.0f} min ago")


def _status_line() -> str:
    """One line for the console window: is each part working right now, from its own check."""
    st = lmp.daemon_status()
    board = _board() or []
    priced = sum(1 for tk in board if resolve_spot(tk)[0] is not None)
    with _terrain_cache_lock:
        as_of = [p.get("computed_ts_utc") for p in _terrain_cache.values() if p.get("computed_ts_utc")]
    newest = ct_label(max(as_of)) if as_of else "none"
    round_sec = (st or {}).get("chain_round_sec")
    return " | ".join([
        "alive",
        f"session {session_label(now_et())}",
        "daemon link: " + ("connected" if st is not None else "NOT CONNECTED"),
        "Schwab socket: " + ("open" if st and st.get("schwab_socket_open") is True else "NOT OPEN"),
        f"live prices: {priced} of {len(board)} board tickers",
        f"levels: {len(as_of)} tickers, newest as of {newest}",
        _feed_record_state(),
        (f"chains: the daemon's last round of the board took {round_sec:.0f} s" if round_sec
         else "chains: the daemon's first round is running"),
    ])


def _terrain_loop() -> None:
    """The board's stored levels once the daemon has said what the board is, then every
    STATUS_EVERY_SEC the status line and the price levels of a new session date or a new
    ticker. The chains arrive from the daemon (_on_chain)."""
    while _terrain_loop_running and _board() is None:
        time.sleep(0.5)
    board = _board() or []
    _publish_missing_price_levels(board)
    loaded = _load_stored_levels(board)
    log.info("Ready: levels for %d of %d board tickers loaded (session: %s). The daemon's chains "
             "price them from here.", loaded, len(board), session_label(now_et()))
    while _terrain_loop_running:
        time.sleep(STATUS_EVERY_SEC)
        try:
            log.info(_status_line())
            _publish_missing_price_levels(_board() or [])
        except Exception as e:  # noqa: BLE001 -- the status line says it failed, never silence
            log.warning("status: could not be read (%s: %s)", type(e).__name__, e)
    log.info("Terrain loop stopped")


def _load_stored_levels(board: "list[str]") -> int:
    """At startup, each board ticker's newest full chain capture is priced once (DATA_FLOW
    decision 7), so a restart, a weekend or the close shows the last reading with its time.
    Returns how many tickers were loaded."""
    n = 0
    for tk in board:
        caps = last_capture_per_day(get_db().db_path, tk, 2)
        if caps and _publish_levels(tk, captures=caps) is not None:
            n += 1
    return n


def start_terrain_loop() -> None:
    """Start the levels thread. Refuses to start under pytest: tests call _terrain_loop's parts
    directly."""
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


def _atr_fields(tk: str) -> dict:
    """atr_daily / atr_15m for every publication of the ticker's levels, whatever the chain's
    source (a live download or a stored capture)."""
    pair = _atr_pair(tk)
    return {"atr_daily": round(pair.daily, 3) if pair.daily is not None else None,
            "atr_15m": round(pair.m15, 3) if pair.m15 is not None else None,
            "atr_daily_reason": pair.daily_reason, "atr_15m_reason": pair.m15_reason}


#: WHICH producer computed a set of levels. The radar deliberately merges two of them, and an
#: unlabelled merge is how systematically-different numbers get ranked as peers (RC-82).
LEVELS_SOURCE_WIDE_CHAIN = "wide_chain_loop"      # _publish_levels, the single producer


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

    def _per_strike(contracts: list, spot: float) -> dict:
        def _scope(cts: list) -> list:
            if not cts:
                return []
            exposures, _diag = _cebs(cts, spot=spot)
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
        return _per_strike(prior["contracts"], float(prior["spot"])), f"chain_capture:{prior['et_date']}"
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
        # the terrain loop hands over FINISHED rows ({all,near,far} of
        # [strike, net_gex_1pct$, volume]); they are served as-is
        if isinstance(_ps, dict):
            measures = {m: (_ps.get(m) or []) for m in ("dex", "oi")}
        if isinstance(_ps, dict) and _ps.get("all"):
            today = {k: (_ps.get(k) or []) for k in ("all", "near", "far")}
            spot_used = _snap.get("spot")
            _cts_utc = _snap.get("computed_ts_utc")
            today_age_sec = round(time.time() - float(_cts_utc), 1) if _cts_utc else None
            today_src = "terrain_live_cache"
    except Exception as e:
        log.debug("terrain strikes live read failed %s: %s", tk, e)
    prior, prior_src = _snap.get("_prior_strikes") or (None, None)

    # STRIP kill (one-faucet-closeout-v1): per-side GEX/OV sums are computed HERE, against
    # the exact spot this payload serves — the chart strip used to re-derive them in the
    # browser from the same rows (a second aggregation site that breaks silently when the
    # payload changes, and can straddle a different spot than the server's). One aggregator.
    def _side_sums(rows, s):
        from numeric_contract import float_finite_or_none
        if not rows or s is None:
            return None
        gb = ga = vb = va = 0.0
        for r in rows:
            # RC-276: the third copy. A row with no gamma used to add 0.0 to a side sum, which
            # is not neutral -- it drags the below/above comparison toward whichever side holds
            # the unmeasured strikes. Absence is dropped, not counted as flat.
            # A row's GEX and its volume are summed each on its own: one never hides the other.
            k = float_finite_or_none(r[0])
            g = float_finite_or_none(r[1])
            v = float_finite_or_none(r[2])
            if k is None or k == s:
                continue
            below = k < s
            if g is not None:
                if below:
                    gb += g
                else:
                    ga += g
            if v is not None:
                if below:
                    vb += v
                else:
                    va += v
        return {"gex_below": gb, "gex_above": ga,
                "vol_below": int(vb), "vol_above": int(va),
                "spot_basis": float(s)}

    live_spot, live_src, _live_ts = resolve_spot(tk)   # the one spot on every screen
    return JSONResponse({
        "ticker": tk, "spot": live_spot,
        "spot_source": live_src,
        "priced_at_spot": spot_used,
        "today": today or {"all": [], "near": [], "far": []},
        # the Chart view's DEX and OI profiles: each measure's rows (terrain_engine
        # _per_strike_measure_rows), its strike nearest the live price (the window's centre) and
        # its largest-magnitude strike
        "measures": {m: {"rows": rows,
                         "spot_strike": nearest_strike([r[0] for r in rows], live_spot),
                         "max_abs_strike": max(rows, key=lambda r: abs(r[1]), default=[None])[0]}
                     for m, rows in measures.items()},
        "today_side_sums": _side_sums((today or {}).get("all"), live_spot),
        "spot_strike": nearest_strike([r[0] for r in (today or {}).get("all") or []], live_spot),
        # the strike with the largest net GEX magnitude (the chart labels it)
        "max_abs_strike": max(((today or {}).get("all") or []), key=lambda r: abs(r[1]), default=[None])[0],
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
        **terrain_staleness(_snap.get("computed_ts_utc") if isinstance(_snap, dict) else None, tk),
        "prior": prior or {"all": [], "near": [], "far": []},
        "prior_source": prior_src,
    })


# ── CR-03 pre-work (operator directive 2026-07-22 "we have plenty of time"):
# the console's charts read canonical 1m bars via this endpoint.
# Read-only, index-served (ticker+timeframe named — the idx_snap lesson applies to
# price_bars_1m equally), no Schwab call, no model stack. The WS transport replaces
# the page's polling when CR-CAP clears; this endpoint stays as the history hydrator.
@app.get("/api/bars1m")
def get_bars1m(ticker: str = Query(...),
               limit: int = Query(default=780, ge=1, le=12000),
               tf: str = Query(default="1", pattern=r"^(1|3|5|15|30|60|D)$")):
    """Completed Schwab 1m bars, newest-last: [{t,o,h,l,c,v}] epoch-seconds bar starts, rolled
    up to `tf` by aggregate_bars. `last_bar`: the newest completed minute and its label."""
    tk = ticker_storage_key(_required_ticker(ticker))   # RC-126: SPX -> $SPX etc., ONE authority
    bars = [_bar_dict(c) for c in _bars_1m(tk, int(limit))]
    out = [_lpr.with_change(b) for b in aggregate_bars(bars, tf)]
    last = bars[-1]["t"] if bars else None
    return JSONResponse({"ticker": tk, "bars": out, "tf": tf, "n": len(out),
                         "last_bar": {"t": last, "label": ct_label(last)} if last is not None else None})


def _tf_bucket_key(t: float, tf: str):
    """The chart bar a timestamp belongs to: its ET trading date ("D") or its tf-minute bucket."""
    return datetime.fromtimestamp(t, ET).date() if tf == "D" else int(t // (int(tf) * 60))


def aggregate_vwap(rows: list, tf: str) -> list:
    """VWAP rows [t, vwap, +1s, -1s, +2s, -2s] rolled up to the chart timeframe exactly as
    aggregate_bars rolls the bars: each bar takes the value as of its last minute, stamped with the
    bar's first minute (the bar's own `t`)."""
    if tf == "1":
        return [list(r) for r in rows]
    out, cur_key = [], None
    for r in rows:
        k = _tf_bucket_key(float(r[0]), tf)
        if k != cur_key:
            out.append([r[0]] + list(r[1:]))
            cur_key = k
        else:
            out[-1] = [out[-1][0]] + list(r[1:])
    return out


def aggregate_bars(bars: list[dict], tf: str) -> list[dict]:
    """THE chart-timeframe roll-up of 1m bars ("1", "3", "5", "15", "30", "60" minutes, or "D" =
    the ET trading date): first open, max high, min low, last close. Volume is the sum only
    when every minute in the bucket reported one -- otherwise None (unknown), never a partial
    sum or a 0."""
    if tf == "1":
        return list(bars)

    def key(t: float):
        return _tf_bucket_key(t, tf)

    out: list[dict] = []
    cur: dict | None = None
    cur_key = None
    for b in bars:
        k = key(float(b["t"]))
        if cur is None or k != cur_key:
            if cur is not None:
                out.append(cur)
            cur = {"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b.get("v")}
            cur_key = k
            continue
        cur["h"] = max(cur["h"], b["h"])
        cur["l"] = min(cur["l"], b["l"])
        cur["c"] = b["c"]
        cur["v"] = None if (cur["v"] is None or b.get("v") is None) else cur["v"] + b["v"]
    if cur is not None:
        out.append(cur)
    return out


@app.get("/api/options/vanna-by-strike")
def get_vanna_by_strike(ticker: str = Query(...)):
    """Per-strike dealer VANNA exposure from the published levels (net_vanna = call_vanna -
    put_vanna, aggregated across every expiry; no per-expiry surface yet)."""
    tk = ticker_storage_key(_required_ticker(ticker))
    payload = terrain_cache_get(tk) or {}
    if "_vanna_rows" not in payload:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no levels published for this ticker yet"})
    spot = resolve_spot(tk)[0]
    return JSONResponse({"ticker": tk, "available": True, "spot": spot,
                         "priced_at_spot": payload.get("spot"),
                         "rows": payload["_vanna_rows"],
                         "spot_strike": nearest_strike([r[0] for r in payload["_vanna_rows"]], spot),
                         "method": "the published levels' exposure book -> call_vanna - put_vanna"})


@app.get("/api/options/charm-by-strike")
def get_charm_by_strike(ticker: str = Query(...)):
    """Per-strike dealer CHARM exposure from the published levels' charm map (the charm walls'
    own): net_charm = call_charm - put_charm per strike, delta-shares/day."""
    tk = ticker_storage_key(_required_ticker(ticker))
    payload = terrain_cache_get(tk) or {}
    if "_charm_rows" not in payload:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no levels published for this ticker yet"})
    rows = payload["_charm_rows"]
    spot = resolve_spot(tk)[0]
    return JSONResponse({"ticker": tk, "available": bool(rows), "spot": spot,
                         "priced_at_spot": payload.get("spot"),
                         "rows": rows,
                         "spot_strike": nearest_strike([r[0] for r in rows], spot),
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
        "reason": None if rows else "no trade prints captured yet for the selected contract(s)",
        "method": ("stream_options_quotes_raw (native LEVELONE_OPTIONS capture, already "
                   "retained) -> tape_rows_for_symbol (de-duplicated genuine trade prints, "
                   "context carried forward) -> merged newest-first across every currently "
                   "desired contract for this ticker"),
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
    forces = (terrain_cache_get(tk) or {}).get("_forces")
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
            (d1, s1, c1, t1), (d0, s0, c0, _t0) = rows[0], rows[1]
            per1 = _cebs(c1, spot=float(s1))[0]
            per0 = _cebs(c0, spot=float(s0))[0]

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

                    charm_below = sum(
                        c for c in (_ch(v) for k, v in per_ch.items() if k < spot1)
                        if c is not None)
                    charm_above = sum(
                        c for c in (_ch(v) for k, v in per_ch.items() if k > spot1)
                        if c is not None)
            except Exception as _ce:
                charm_err = str(_ce)[:120]
            payload = {
                "ticker": tk, "available": True,
                "doi_below": sum(d for k, d in doi.items() if k < spot1),
                "doi_above": sum(d for k, d in doi.items() if k > spot1),
                "dex_below_dollars": sum(d for k, d in dex1.items() if k < spot1),
                "dex_above_dollars": sum(d for k, d in dex1.items() if k > spot1),
                "strikes_diffed": len(doi),
                "charm_below": charm_below,
                "charm_above": charm_above,
                "charm_error": charm_err,
                "newer_et_date": d1, "older_et_date": d0, "bucket_spot": spot1,
                "method": ("per-strike OI delta first, bucketed by the newer capture's spot; "
                           "DEX = net_dex_dollars side sums on the newer capture; "
                           "CHARM = dealer-signed net_charm side sums on the newer capture"),
            }
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"forces read failed: {e}"}
    return payload


# RC-UI-1: strike × expiry GEX surface for the rebuilt Options→Gamma heatmap. A PROJECTION over the
# one canonical exposure authority, not a second producer: it partitions a wide chain by native
# expirationDate (via the existing _filter_contracts_by_selected_expiry slice) and invokes
# math_exposure_core.compute_exposures_by_strike per slice, shaping net_gex_1pct cells into a grid.
# No gamma/GEX/multiplier/OI/spot/sign/missingness math lives here.
# SOURCE: the live terrain projection only — _publish_levels projects it from the full chain the
# daemon delivers and the live spot (in-memory, zero extra vendor calls). No banked-morning
# fallback (operator rule 2026-09-23).

#: Why a heatmap cell has no value for a measure: the code each cell carries (absent[measure])
#: and the words the page draws for it (the surface's absent_reasons). A cell is absent only
#: where Schwab sent nothing for it; a listed contract with open interest 0 is a computed 0.
CELL_NOT_LISTED = "not_listed"
CELL_EXPOSURE_NOT_SENT = "exposure_not_sent"
CELL_OI_NOT_SENT = "oi_not_sent"
CELL_VOLUME_NOT_SENT = "volume_not_sent"
CELL_ABSENT_REASONS = {
    CELL_NOT_LISTED: "no contract listed",
    # a contract here sent no open interest or multiplier, or has open interest and no Greek
    CELL_EXPOSURE_NOT_SENT: "Schwab sent no Greek/OI",
    CELL_OI_NOT_SENT: "Schwab sent no OI",
    CELL_VOLUME_NOT_SENT: "Schwab sent no volume",
}


def _gamma_surface_cell_fields(bucket: "dict | None", syms: "dict | None"):
    """ONE (strike, expiry) cell's gex/dex/vanna/oi/volume/contracts fields from its exposure
    bucket, Schwab's values and the book's computed values exact, and for each measure with no
    value the CELL_* code saying why. Returns (gex, dex, vanna, oi, volume, contracts, absent)."""
    from math_exposure_core import strike_oi_legs, strike_volume_legs

    syms = syms or {}
    contracts = {"call": syms.get("call"), "put": syms.get("put")}
    if bucket is None:
        none = {"call": None, "put": None, "total": None}
        return (None, None, None, none, none, contracts,
                {m: CELL_NOT_LISTED for m in ("gex", "dex", "vanna", "oi", "volume")})
    gex = bucket_metric(bucket, "net_gex_1pct")
    dex = bucket_metric(bucket, "net_dex_dollars")
    vanna = bucket_metric(bucket, "net_vanna")

    def _legs(legs):
        if legs is None:
            return {"call": None, "put": None, "total": None}
        return {"call": legs[0], "put": legs[1], "total": legs[0] + legs[1]}

    oi = _legs(strike_oi_legs(bucket))
    volume = _legs(strike_volume_legs(bucket))
    absent = {m: (CELL_EXPOSURE_NOT_SENT if v is None else None)
              for m, v in (("gex", gex), ("dex", dex), ("vanna", vanna))}
    absent["oi"] = CELL_OI_NOT_SENT if oi["total"] is None else None
    absent["volume"] = CELL_VOLUME_NOT_SENT if volume["total"] is None else None
    return gex, dex, vanna, oi, volume, contracts, absent


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
    expirations = [{"expiry": e, "dte": exp_dte.get(e)} for e in expiries]
    # Each cell carries every measure its bucket already holds -- GEX, DEX, vanna
    # (call - put, the dealer convention of compute_net_vanna), OI and volume -- so one grid
    # serves every heatmap measure, and for a measure with no value the code saying why
    # (_gamma_surface_cell_fields; absent_reasons words them).
    cells = []
    for k in strikes:
        row, dex_row, vanna_row, oi_row, vol_row, contracts_row = [], [], [], [], [], []
        absent_row: "dict[str, list]" = {m: [] for m in ("gex", "dex", "vanna", "oi", "volume")}
        for col in expirations:
            bucket = per_expiry.get(col["expiry"], {}).get(k)
            syms = symbols_by_expiry.get(col["expiry"], {}).get(k)
            gex, dex, vanna, oi, volume, contracts, absent = _gamma_surface_cell_fields(bucket, syms)
            row.append(gex)
            dex_row.append(dex)
            vanna_row.append(vanna)
            oi_row.append(oi)
            vol_row.append(volume)
            contracts_row.append(contracts)
            for m, code in absent.items():
                absent_row[m].append(code)
        cells.append({
            "strike": k, "gex": row, "dex": dex_row, "vanna": vanna_row,
            "oi": oi_row, "volume": vol_row, "contracts": contracts_row, "absent": absent_row,
        })
    return {
        "expirations": expirations, "strikes": strikes, "cells": cells,
        "absent_reasons": CELL_ABSENT_REASONS,
        "contracts_total": total_contracts, "contracts_used": contracts_used,
        "contracts_excluded_malformed_expiry": excluded_malformed,
    }


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
    live_cols = [e for e in out["expirations"] if not e["expired"] and e.get("dte") is not None]
    # the front column: the nearest expiry that has not expired, by Schwab's daysToExpiration
    out["front_expiry"] = min(live_cols, key=lambda e: e["dte"])["expiry"] if live_cols else None
    return out


@app.get("/api/options/gamma-surface")
def get_options_gamma_surface(ticker: str = Query(...)):
    """Strike × expiration signed GEX$ surface (cell = net_gex_1pct) through the ONE canonical
    faucet compute_exposures_by_strike.

    ONE source: the LIVE surface _publish_levels (the single levels producer) projects from the
    full chain the daemon delivers and the live spot (source=terrain_live_cache).
    With no live surface the answer is "unavailable" with the reason -- there is no second source
    (operator rule 2026-09-23: no fallbacks; the banked MORNING wide chain used to stand in).
    Exposes chain/spot as-of, source, and stale/degraded so the UI can fail stale visibly."""

    tk = ticker_storage_key(_required_ticker(ticker))

    # ---- LIVE: surface projected this cycle from the canonical live terrain wide chain ----
    live = terrain_cache_get(tk)
    surf = (live or {}).get("_gamma_surface")
    _surface_live_spot = resolve_spot(tk)
    if live and surf:
        # ONE freshness authority: terrain_staleness (RC-424) already merged onto the cache by
        # terrain_cache_get — serialize it verbatim, never a second age policy for the same truth.
        stale = bool(live.get("levels_stale"))
        strikes = surf.get("strikes") or []
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
            # every cell Schwab listed is drawn: a cell without a value says why (absent)
            "ticker": tk, "symbol": tk, "available": True, "reason": None,
            "source": "terrain_live_cache", "live": True, "stale": stale,
            "cell_stream_state_counts": _gamma_surface_cell_state_counts(surf),
            "stream_coverage": _coverage,
            "contract_admission": _contract_admission,
            "degraded": live.get("levels_stale_reason") if stale else None,
            "chain_as_of_ts_utc": live.get("computed_ts_utc"),
            "age_sec": live.get("levels_age_sec"),            # terrain's canonical age
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
    # REQUESTED: this ticker is viewed. WARMING: viewed and on the board, so the daemon's chain
    # sweep is fetching it. The reason is that state's own.
    _requested = _gamma_surface_wanted(tk)
    _state = terrain_staleness((live or {}).get("computed_ts_utc"), tk)
    _on_board = tk in (_board() or [])
    _warming = _requested and _on_board
    payload: dict = {"ticker": tk, "symbol": tk, "available": False, "source": "unavailable",
                     "live": False, "stale": True, "warming": _warming, "requested": _requested,
                     "reason": (f"{tk} is not on the board: add it to fetch its chain" if not _on_board
                                else _state["levels_stale_reason"] or (
                                    "the surface is projected when the daemon delivers this ticker's chain"
                                    if _warming else "no gamma surface for this ticker's published levels"))}
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
    cached = terrain_cache_get(tk)
    if cached is not None:
        # the levels as the producer published them, every at-spot value computed at the
        # publication's spot -- the price they were computed at, labelled by spot_source and
        # spot_as_of_ts_utc, never called live (the live price is the daemon's price row);
        # internal fields (the kept chain, the heatmap grid, per-strike rows) have their own routes
        out = {k: v for k, v in cached.items() if not k.startswith("_")}
        out.update(terrain_staleness(cached.get("computed_ts_utc"), tk))
        return out
    spot, spot_source, spot_ts = resolve_spot(tk)
    _why = _terrain_refresh_last_error.get(tk)
    return compute_terrain(tk, None, spot).to_dict() | {
        "spot_source": spot_source, "spot_as_of_ts_utc": spot_ts,
        **_atr_fields(tk),              # from the bars, which do not wait for a chain
        # RC-126: not_ready carries its REASON when the producer has one — an eternal
        # unexplained shrug is how $SPX stayed dark for a session.
        "error": ("terrain_not_ready: no chain from the daemon yet for this ticker"
                  + (f" (last chain error: {_why})" if _why else "")
                  + ("" if tk in (_board() or []) else f"; {tk} is not on the board")),
        # RC-151: and it carries the STRUCTURED state too, so a consumer never parses English
        # to learn the ticker is failing
        **terrain_staleness(None, tk),
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
    crosses = _merged_recent_crosses(get_db(), tk, 200)
    in_window = sorted((c for c in crosses if c.get("ts_utc") is not None and c["ts_utc"] >= start),
                       key=lambda c: c["ts_utc"])
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
#: With no change, the session label is pushed this often (it doubles as the heartbeat).
CHANGES_SESSION_SEC = 5.0


@app.get("/api/changes")
async def get_changes(ticker: str = Query(...)):
    """The console's push to the page: `levels`, `flow` or `liquidity` when that value of the
    ticker changed (the page reloads it), and `session` with the market session label. Prices
    and bars come from the daemon's own push. Opening it makes the ticker the active one, whose
    NYSE_BOOK and NASDAQ_BOOK the daemon streams: every page reconnects after a console
    restart, so the books follow the page with no separate request."""
    from app.options.order_flow.streaming import set_streaming_active_ticker

    t = ticker_storage_key(_required_ticker(ticker))
    _get_route_offload_executor().submit(lambda: (set_streaming_active_ticker(t), _ensure_default_option_contract(t)))
    client = push_changes.subscribe(t)

    async def event_generator():
        try:
            yield f"event: session\ndata: {session_label(now_et())}\n\n"
            while True:
                kinds = await push_changes.next_changes(client, CHANGES_SESSION_SEC)
                for k in sorted(kinds):
                    yield f"event: {k}\ndata: {t}\n\n"
                if not kinds:
                    yield f"event: session\ndata: {session_label(now_et())}\n\n"
                    continue
                await asyncio.sleep(CHANGES_PUSH_MIN_SEC)
        finally:
            push_changes.unsubscribe(t, client)

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
    NATIVE/DERIVED/PROXY. SERIALIZER, not a second producer: it delegates to the ONE canonical
    app.options.order_flow.engine.compute_book_microstructure keyed by this ticker, which carries the
    engine's already-computed structural state for the current book (memoized per ticker +
    BOOK_TIME) rather than re-walking the raw book. No Schwab REST quote call; the client
    renders, never recomputes. `venue` is the one Schwab book shown: NYSE_BOOK (exchanges) or
    NASDAQ_BOOK (market makers); the two are never combined."""
    t = ticker_storage_key(_required_ticker(ticker))
    data: dict = {}
    try:
        from app.options.order_flow.state import get_content_for_symbol
        _content = get_content_for_symbol(t, venue)
        if _content:
            data["content"] = _content
    except Exception as e:  # streaming state optional — fail closed to 'no_book', never fabricate
        log.debug("microstructure content build failed for %s: %s", t, e)
    # top of book: the daemon's price row (each field the last Schwab sent)
    from app.options.order_flow.streaming import price_row
    _row = price_row(t)
    if _row and _row.get("quote_ts") is not None:
        data["exchange_quote_ts"] = _row["quote_ts"]
    data["top"] = ({k: _row.get(k) for k in ("bid", "ask", "bid_size", "ask_size", "mark")}
                   if _row and (_row.get("bid") is not None or _row.get("ask") is not None) else None)
    data["book_live"] = lmp.feed_live_for(t, venue)
    from app.options.order_flow.engine import compute_book_microstructure
    # ticker=t → serialize the canonical state carried per (ticker, BOOK_TIME); no independent recompute.
    now = time.time()
    payload = compute_book_microstructure(data, now_ts=now, ticker=t)
    # The trade-side read the Trade Desk's Order Flow card shows: tick-rule PROXY flow from the
    # same OrderFlowEngine the option book uses (no second classifier).
    try:
        from app.options.order_flow.engine import OrderFlowEngine
        from app.options.order_flow.live_payload import flow_block
        payload["flow"] = flow_block(OrderFlowEngine().compute(data, now=now, ticker=t))
    except Exception as e:  # flow is additive -- the book payload stands without it
        log.debug("microstructure flow failed for %s: %s", t, e)
        payload["flow"] = None
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
    payload = options_live_payload(ticker_storage_key(c), time.time())
    payload["contract"] = c
    from app.options.order_flow.history import put_call_side
    from app.options.order_flow.state import get_content_for_symbol
    payload["put_call"] = put_call_side(next((it.get("CONTRACT_TYPE") for it in get_content_for_symbol(c)  # external-key-ok: Schwab LEVELONE_OPTIONS
                                              if it.get("CONTRACT_TYPE")), None))
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
        diag = get_option_contract_streaming_diagnostics(for_contract=c)
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
        out = await asyncio.get_event_loop().run_in_executor(_get_route_offload_executor(), _apply)
    except StaleOptionCommandError as e:
        return JSONResponse({"ok": False, "error": str(e), "client_id": client_id, "seq": seq,
                             "superseded": True}, status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "contracts": contracts}, status_code=500)
    return JSONResponse(out)


@app.get("/api/expiries")
def get_expiries(ticker: str = Query(...)):
    """The ticker's listed expiries with each one's dropdown label (MM/DD/YYYY and Schwab's
    daysToExpiration, as sent); with none, the levels' own reason."""
    ticker = ticker_storage_key(_required_ticker(ticker))   # SPX -> $SPX: the cache's own key
    t = terrain_cache_get(ticker) or {}
    exps, dte = t.get("expiries") or [], t.get("expiry_dte") or {}
    labels = {e: f"{e[5:7]}/{e[8:10]}/{e[:4]}" + (f" · {dte[e]:g}DTE" if dte.get(e) is not None else "")
              for e in exps}
    return JSONResponse({"expiries": exps, "dte": dte, "labels": labels,
                         "reason": None if exps else (terrain_staleness(None, ticker)["levels_stale_reason"]
                                                      if not t else "no expiry listed in the published chain")})



@app.get("/api/chain")
def get_chain(ticker: str = Query(...),
              expiry: Optional[str] = Query(default=None)):
    """One expiry of the ticker's full chain -- every contract Schwab listed, every field as sent
    -- from the chain the levels loop downloads (strike_range=ALL), with each live streamed
    contract's streamed fields as its values (the stream owns them). The loop keeps every
    ticker's chain. Answers `status: unavailable` with a reason when no
    chain is held."""
    t = ticker_storage_key(_required_ticker(ticker))
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
    # each field the newest Schwab sent (the levels' own rule, _publish_levels)
    response_contracts, overlay_n = overlay_streamed_contract_fields(
        contracts, _desired_stream_greeks_for_ticker(t), fetched_ts)
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
        "contracts": response_contracts, "status": "ok",
        "ladder": ladder, "n_strikes": len({r["strike"] for r in ladder}),
        "contracts_not_on_ladder": not_on_ladder,   # no strike, or a putCall other than CALL/PUT
        "stream_overlay_contracts": overlay_n,
        "scope": {"kind": "complete_single_expiry", "requested_expiry": resolved_expiry,
                  "completeness_basis": held.get("chain_basis")},   # the publication's own label
    })

@app.get("/api/health")
def health():
    # RC-514 / docs/ARCHITECTURE.md "Failure domains": application availability and capability
    # availability are separate, so `status` answers "is the app alive" and never folds a
    # vendor outage into it. Schwab is the capture daemon's: its heartbeat says whether its
    # Schwab socket is open; no current heartbeat is UNAVAILABLE (unmeasurable is not ok, RC-57).
    st = lmp.daemon_status()
    board = _board()
    capability: dict[str, object] = {
        "schwab": "AVAILABLE" if st is not None and st.get("schwab_socket_open") is True else "UNAVAILABLE"}
    if capability["schwab"] == "UNAVAILABLE":
        capability["schwab_reason"] = ("the capture daemon's heartbeat is not current" if st is None
                                       else "the capture daemon's Schwab socket is not open")
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "logger_tickers": len(board) if board is not None else None,
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
    from liquidity_value_engine import PlaybookConfig, _bars_to_list, materialize_price_level_snapshot
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
    # the gamma family, carried from the terrain (terrain_engine.compute_terrain's own values)
    t = terrain_cache_get(tk) or {}
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
        row["distance"] = (price - spot) if price is not None and spot is not None else None
        # which side of spot, at the price's own two decimals (AT: prints as 0.00 away)
        row["side"] = (None if row["distance"] is None else "AT" if round(row["distance"], 2) == 0
                       else "ABOVE" if row["distance"] > 0 else "BELOW")
    # the ladder in price order (highest first, unpriced last), and the order by distance to spot
    levels = (sorted((r for r in levels if r.get("price") is not None), key=lambda r: r["price"], reverse=True)
              + [r for r in levels if r.get("price") is None])
    # the order the chart draws them in: nearest Schwab's last price (spot, with its trade time)
    by_distance = [] if spot is None else [r["id"] for r in sorted((r for r in levels if r.get("price") is not None),
                                                                   key=lambda r: abs(r["price"] - spot))]

    families_absent = (list(snap.families_absent) if snap is not None
                       else [{"family": "price_levels", "reason": NO_PRICE_LEVELS_REASON}])
    vp = snap.volume_profile if snap is not None else None
    if em is None or spot is None:
        families_absent.append({"family": "expected_move", "reason": "no live price" if spot is None
                                else "the terrain has no implied 1-day move"})

    return JSONResponse({
        "ticker": tk,
        "schema_version": 1,
        "served_ts_utc": served_ts,
        "spot": spot,
        "spot_source": spot_source,
        "spot_as_of_ts_utc": spot_ts,
        "generation": snap.generation if snap is not None else None,
        "snapshot_as_of_ts_utc": snap.as_of_ts_utc if snap is not None else None,
        "bar_source": snap.bar_source if snap is not None else None,
        "levels": levels,
        "by_distance": by_distance,
        # The VWAP curve and its σ bands, CARRIED. The standalone pages each
        # used to accumulate their own from /api/bars1m — two more VWAPs for one
        # session, drawn beside a level neither of them agreed with.
        # [epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ]
        "vwap_series": aggregate_vwap(snap.vwap_series, tf) if snap is not None else [],   # one point per chart bar of `tf`
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


def _build_raw_levels_used(raw_levels: dict) -> list:
    """Flatten raw_levels (the one price-level snapshot's values) into [{tag, value}] for
    display, ordered by price, under their canonical ids."""
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
    if raw_levels.get("vwap") is not None:
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


def _spot_location(zones: list, spot) -> "dict | None":
    """Where spot sits among the zones, by index into `zones`: the zone it is inside, else the
    nearest zone above and below. None without a spot or a zone."""
    if spot is None or not zones:
        return None
    for i, z in enumerate(zones):
        if z.get("zone_low") is not None and z.get("zone_high") is not None and z["zone_low"] <= spot <= z["zone_high"]:
            return {"inside": i, "above": None, "below": None}
    above = [i for i, z in enumerate(zones) if z.get("zone_low") is not None and z["zone_low"] > spot]
    below = [i for i, z in enumerate(zones) if z.get("zone_high") is not None and z["zone_high"] < spot]
    return {"inside": None,
            "above": min(above, key=lambda i: zones[i]["zone_low"]) if above else None,
            "below": max(below, key=lambda i: zones[i]["zone_high"]) if below else None}


@app.get("/api/liquidity-snapshot")
# SWITCH-LATENCY FIX: sync def → threadpool. This fires on every ticker switch (client
# setTimeout pollLiquiditySnapshot) and every 60s; it does a blocking Schwab bar fetch with
# no await, so as async it stalled the event loop on each switch.
def get_liquidity_snapshot(ticker: str = Query(...)):
    """Today's liquidity & value zones for the ticker: built from the one price-level snapshot
    (canonical_price_level_snapshot, the same values /api/levels serves) with the terrain's
    option levels and the live price fused in. It computes no level of its own."""
    try:
        from liquidity_value_engine import build_live_snapshot
        from liquidity_models import ZONE_DISPLAY, PlaybookConfig

        ticker_upper = ticker_storage_key(ticker)
        config = PlaybookConfig(max_zone_width=2.0)
        extra, fusion_status = _liquidity_option_levels(ticker_upper)
        # the one spot (resolve_spot); a stale side-cache served 759.725 beside a 760.13 header
        # (2026-09-14, RC spot-360-audit)
        spot_for_zones, _, _ = resolve_spot(ticker_upper)
        if spot_for_zones is not None:
            extra = list(extra) + [(spot_for_zones, "SPOT_LIVE")]
        _canon = canonical_price_level_snapshot(ticker_upper)
        if _canon is None:
            return {"ticker": ticker_upper, "zones": [], "reason": NO_PRICE_LEVELS_REASON}
        out = build_live_snapshot(ticker_upper, config, canonical=_canon, now=now_et(),
                                  extra_levels=extra)
        snapshot_val = out.snapshot_type.value
        zones_payload = []
        for z in out.zones:
            w = z.zone_high - z.zone_low
            merged = len(z.source_tags)
            zp = {
                "zone_type": z.zone_type.value,
                "zone_label": ZONE_DISPLAY[z.zone_type][0],
                "zone_side": ZONE_DISPLAY[z.zone_type][1],
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
            _liquidity_zone_tradeable_fields(zp, spot_for_zones)
            zones_payload.append(zp)
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
            "raw_levels_used": _build_raw_levels_used(out.raw_levels),
            "fusion": fusion_status,
            "as_of_cutoff_et": (out.raw_levels or {}).get("cutoff_et"),
            "spot_used_for_scoring": spot_for_zones,
            "spot_location": _spot_location(zones_payload, spot_for_zones),
            # which snapshot generation these level values ARE
            "level_generation": _canon.generation,
            "level_semantic_scope": (out.raw_levels or {}).get("semantic_scope"),
            "level_snapshot_as_of_ts_utc": _canon.as_of_ts_utc,
            "level_bar_source": _canon.bar_source,
        }
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
        # its own status code (a missing ticker is 400), never re-issued as a bare 500
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


